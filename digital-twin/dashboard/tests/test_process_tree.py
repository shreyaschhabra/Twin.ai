"""The launched run must be killable as a whole tree, not just its top process.

``cli.py system run random`` spawns the two prediction consumers as its own
children. The regression these tests guard against: cancelling a run terminated
only ``cli.py`` and left the consumers running to completion, still pinning CPU
and appending to the prediction JSONL after the dashboard had moved on.
"""

from __future__ import annotations

import subprocess
import sys
import time

from dashboard import process_tree
from dashboard.live.session import LiveRunSession, LiveRunStatus

# A parent that spawns a grandchild, both of which sleep well past the test. Mirrors
# ``cli.py`` launching ``run_current.py`` / ``run_current_defects.py``.
_TREE_SOURCE = (
    "import subprocess, sys, time;"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
    "print(child.pid, flush=True);"
    "time.sleep(120)"
)


def _still_running(pid: int) -> bool:
    if sys.platform.startswith("win"):
        out = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/nh"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not reached in time")


def _spawn_tree() -> tuple[subprocess.Popen, int]:
    proc = subprocess.Popen(
        [sys.executable, "-c", _TREE_SOURCE],
        stdout=subprocess.PIPE, text=True,
        **process_tree.spawn_kwargs(),
    )
    process_tree.track(proc)
    grandchild_pid = int(proc.stdout.readline().strip())
    _wait_until(lambda: _still_running(grandchild_pid))
    return proc, grandchild_pid


def test_terminate_tree_kills_children_too():
    proc, grandchild_pid = _spawn_tree()
    try:
        process_tree.terminate_tree(proc)
        _wait_until(lambda: not _still_running(proc.pid))
        _wait_until(lambda: not _still_running(grandchild_pid))
    finally:
        for pid in (proc.pid, grandchild_pid):
            if _still_running(pid):
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)]
                    if sys.platform.startswith("win")
                    else ["kill", "-9", str(pid)],
                    capture_output=True,
                )


def test_cancelling_a_session_takes_the_whole_tree_down(tmp_path):
    stream = tmp_path / "b.jsonl"
    session = LiveRunSession("tree_run_0001", stream, poll_interval_s=0.05)

    holder: dict[str, int] = {}

    def launch():
        proc, grandchild_pid = _spawn_tree()
        holder["grandchild"] = grandchild_pid
        return proc

    session.start(launch)
    _wait_until(lambda: session.is_running and "grandchild" in holder)
    grandchild_pid = holder["grandchild"]
    assert _still_running(grandchild_pid)

    session.cancel()
    _wait_until(lambda: session.status.finished)
    assert session.status == LiveRunStatus.CANCELLED
    _wait_until(lambda: not _still_running(grandchild_pid))
