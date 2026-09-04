"""Kill a launched pipeline as a whole tree, not just its top process.

The dashboard launches ``cli.py system run random`` as one subprocess, but that
process goes on to spawn its own children -- the bottleneck consumer
(``bottlenecks_prediction/run_current.py``) and the defect consumer
(``Defect_Model/run_current_defects.py``), both started by
``system_runtime._run_pair``. Terminating only the top process leaves those
grandchildren running: on Windows nothing reaps a process when its parent dies, so
after "Stop run" the consumers would keep burning CPU and appending to the
prediction JSONL for minutes.

This module makes the launched process killable as a group:

* **POSIX** -- :func:`spawn_kwargs` adds ``start_new_session=True`` so the child is a
  process-group leader; :func:`terminate_tree` signals the whole group.
* **Windows** -- :func:`track` assigns the child to an anonymous Job Object whose
  ``KILL_ON_JOB_CLOSE`` limit means every process in the job dies when the job
  handle is closed; :func:`terminate_tree` calls ``TerminateJobObject`` and closes
  it. Child processes join their parent's job automatically, so the two consumers
  are covered without the dashboard knowing they exist.

Nothing here changes what the pipeline computes -- it is purely process lifecycle.
It has no dependency on the simulator, the ML runtimes, or ``dashboard.live`` /
``dashboard.orchestration``, so both packages can import it without a cycle.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess

logger = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"

#: Attribute name under which :func:`track` stashes a Windows Job Object handle on
#: the ``Popen``. Kept private to this module; callers only use the functions.
_JOB_ATTR = "_dashboard_job_handle"


def spawn_kwargs() -> dict:
    """Extra ``subprocess.Popen`` keyword arguments for a group-killable child.

    On POSIX this puts the child in its own session/process group so a later
    ``killpg`` cannot touch the dashboard itself. On Windows the equivalent
    (Job Object assignment) happens after spawn in :func:`track`, so there is
    nothing to add here.
    """
    if _IS_WINDOWS:
        return {}
    return {"start_new_session": True}


def track(process: subprocess.Popen) -> None:
    """On Windows, put ``process`` in a kill-on-close Job Object.

    Best effort: any failure is logged and left alone, and :func:`terminate_tree`
    then falls back to terminating just the top process (the pre-existing
    behaviour). No-op on POSIX, where :func:`spawn_kwargs` already did the work.

    There is a small window between the child being created and being assigned to
    the job in which a grandchild it spawns would escape. In practice ``cli.py``
    spends seconds on scenario generation and simulation before it launches the
    prediction consumers, so assignment (which happens immediately after spawn)
    always wins the race.
    """
    if not _IS_WINDOWS:
        return
    handle = getattr(process, "_handle", None)
    if handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())

        info = _EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)

        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(handle))):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)

        setattr(process, _JOB_ATTR, job)
    except OSError as error:  # pragma: no cover - depends on the OS/job nesting rules
        logger.warning(
            "could not place run process %s in a job object; only the top process "
            "will be terminated on cancel: %s",
            getattr(process, "pid", "?"), error,
        )


def terminate_tree(process, *, timeout: float = 5.0) -> None:
    """Terminate ``process`` and every child it started, then wait briefly.

    Windows: close the tracked Job Object (``KILL_ON_JOB_CLOSE`` takes the whole
    tree down), and also call ``terminate()`` for the untracked-fallback case.
    POSIX: signal the process group, escalating ``SIGTERM`` -> ``SIGKILL``.
    Tolerant of a plain object that only implements ``terminate()`` (test doubles).
    """
    job = getattr(process, _JOB_ATTR, None)
    if job is not None:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            # Terminating the job kills every process in it now; closing the handle
            # would do it too via KILL_ON_JOB_CLOSE, but being explicit is clearer.
            kernel32.TerminateJobObject(wintypes.HANDLE(job), 1)
            kernel32.CloseHandle(wintypes.HANDLE(job))
        except OSError as error:  # pragma: no cover - defensive
            logger.warning("could not terminate job object for run process: %s", error)
        finally:
            try:
                delattr(process, _JOB_ATTR)
            except AttributeError:
                pass

    pid = getattr(process, "pid", None)
    if not _IS_WINDOWS and pid is not None:
        _posix_kill_group(process, pid, timeout=timeout)
        return

    # Windows, or a test double: terminate the single process. When a job was
    # tracked the tree is already gone and this is a harmless no-op.
    try:
        process.terminate()
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("could not terminate run process %s: %s", pid, error)
    _wait(process, timeout)


def _posix_kill_group(process, pid: int, *, timeout: float) -> None:
    try:
        group = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return
    try:
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        # Not our group after all -- fall back to the single process.
        try:
            process.terminate()
        except Exception:  # pragma: no cover - defensive
            pass
    if _wait(process, timeout) is not None:
        return
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        return
    _wait(process, timeout)


def _wait(process, timeout: float):
    """``process.wait(timeout=...)`` where supported, plain ``wait()`` otherwise."""
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except TypeError:  # a test double whose wait() takes no timeout
        try:
            return process.wait()
        except Exception:  # pragma: no cover - defensive
            return None
    except Exception:  # pragma: no cover - defensive
        return None
