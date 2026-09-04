"""Incremental reader for a prediction JSONL file that is still being written.

The coordinated runtime's bottleneck consumer appends to
``bottleneck_predictions.jsonl`` in batches, re-opening and closing the file for each
batch (``bottlenecks_prediction/output/prediction_output.py::append_jsonl``). Every
completed batch is therefore durable on disk while the run is still executing, which is
what makes tailing safe: this module never guesses at a record the consumer has not
written yet.

What it does *not* do: it does not interpret, score, interpolate or synthesise
predictions. It hands back exactly the records the runtime emitted, in emission order.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TailResult:
    """One incremental read."""

    records: list[dict[str, Any]]
    malformed: int = 0
    #: True when the file vanished or shrank and the tailer restarted from byte 0.
    restarted: bool = False

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self.records)


class JsonlTailer:
    """Reads newly appended JSON objects from a growing JSONL file.

    Progress is tracked as a byte offset rather than a line count, so a partially
    flushed final line is buffered and re-parsed once its newline arrives instead of
    being reported as malformed. A file that shrinks or disappears -- the consumer
    deletes its output before a replay starts -- resets the tailer instead of yielding
    garbage from a stale offset.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._offset = 0
        self._pending = ""
        self.total_records = 0
        self.total_malformed = 0

    # -- state ----------------------------------------------------------------------

    @property
    def offset(self) -> int:
        """Bytes consumed so far, excluding any buffered partial line."""
        return self._offset

    def reset(self) -> None:
        self._offset = 0
        self._pending = ""

    def exists(self) -> bool:
        return self.path.is_file()

    # -- reading --------------------------------------------------------------------

    def read_new(self) -> TailResult:
        """Return every complete record appended since the previous call."""
        restarted = False
        if not self.path.is_file():
            if self._offset or self._pending:
                self.reset()
                restarted = True
            return TailResult([], 0, restarted)

        try:
            size = self.path.stat().st_size
        except OSError as error:  # pragma: no cover - defensive
            logger.warning("could not stat prediction stream %s: %s", self.path, error)
            return TailResult([], 0, False)

        if size < self._offset:
            # The stream was truncated or rewritten; the old offset means nothing now.
            self.reset()
            restarted = True
        if size == self._offset and not self._pending:
            return TailResult([], 0, restarted)

        try:
            # Binary, so the tracked offset is a true byte count comparable with
            # st_size. A text handle's tell() is an opaque cookie, not an offset.
            with self.path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError as error:  # pragma: no cover - defensive
            logger.warning("could not read prediction stream %s: %s", self.path, error)
            return TailResult([], 0, restarted)

        buffer = self._pending + chunk.decode("utf-8", errors="replace")
        lines = buffer.split("\n")
        # The trailing fragment is only complete if the chunk ended with a newline.
        self._pending = lines.pop()

        records: list[dict[str, Any]] = []
        malformed = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                malformed += 1

        self.total_records += len(records)
        self.total_malformed += malformed
        return TailResult(records, malformed, restarted)

    def read_all(self) -> TailResult:
        """Read the whole file from the start, discarding any previous progress."""
        self.reset()
        self.total_records = 0
        self.total_malformed = 0
        return self.read_new()
