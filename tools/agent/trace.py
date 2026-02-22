"""Structured NDJSON trace logging for human audit of harness runs.

Each trace event is one JSON line appended to a file.
No timestamps are written — the trace is deterministic and reproducible.

Usage::

    tracer = Tracer(pathlib.Path("sandbox_tmp/agent_trace.ndjson"))
    tracer.emit("file_read", path="src/mmo/cli.py", lines=300)
    tracer.emit("budget_exceeded", budget="max_file_reads", value=61, limit=60)

    # No-op tracer (useful in tests that don't need trace output):
    silent = Tracer()
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Optional


class Tracer:
    """Appends structured trace events to an NDJSON file.

    If *path* is ``None`` all emit calls are silently ignored — useful for
    callers that don't need a persistent trace (e.g. unit tests).

    Each record contains at minimum:
        ``seq`` (int)   — monotonically increasing sequence number.
        ``event`` (str) — short event name.
        ...any extra keyword arguments passed to :meth:`emit`.

    Keys are written in sorted order for determinism.
    """

    def __init__(self, path: Optional[pathlib.Path] = None) -> None:
        self._path = path
        self._seq = 0
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")  # truncate / create fresh

    # ------------------------------------------------------------------

    def emit(self, event: str, **kwargs: Any) -> None:
        """Append one trace event to the NDJSON file.

        Args:
            event: Short snake_case event name (e.g. ``"file_read"``).
            **kwargs: Additional fields merged into the record.
        """
        self._seq += 1
        record: dict[str, Any] = {"event": event, "seq": self._seq}
        record.update(kwargs)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")

    @property
    def seq(self) -> int:
        """Current sequence counter (number of events emitted so far)."""
        return self._seq
