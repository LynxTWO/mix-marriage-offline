"""Thread-safe progress, cancellation, and explainable live-log primitives."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

ProgressListener = Callable[["ProgressSnapshot"], None]
LogListener = Callable[["ExplainableLogEvent"], None]


class CancelledError(RuntimeError):
    """Raised when a cancel token is tripped."""


class CancelToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def cancel(self, reason: str | None = None) -> None:
        with self._lock:
            if self._event.is_set():
                return
            normalized = str(reason).strip() if isinstance(reason, str) else ""
            self._reason = normalized or "cancelled"
            self._event.set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError(self.reason or "cancelled")


@dataclass(frozen=True)
class ProgressSnapshot:
    total_steps: int
    completed_steps: int
    progress: float
    phase: str
    eta_seconds: float | None
    cancelled: bool
    cancel_reason: str | None


@dataclass(frozen=True)
class ExplainableLogEvent:
    kind: str
    scope: str
    what: str
    why: str
    where: tuple[str, ...]
    confidence: float | None
    evidence: dict[str, Any] = field(default_factory=dict)
    step_index: int = 0
    total_steps: int = 0
    progress: float = 0.0
    eta_seconds: float | None = None


def _normalize_where(values: Iterable[str] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values or ():
        text = str(value).replace("\\", "/").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered) if ordered else ("(none)",)


def _clamp_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def format_live_log_line(event: ExplainableLogEvent) -> str:
    """Return a machine-readable deterministic live-log line."""
    payload = {
        "kind": event.kind,
        "scope": event.scope,
        "what": event.what,
        "why": event.why,
        "where": list(event.where),
        "confidence": event.confidence,
        "evidence": event.evidence,
        "step_index": event.step_index,
        "total_steps": event.total_steps,
        "progress": round(event.progress, 6),
        "eta_seconds": (
            round(float(event.eta_seconds), 3)
            if isinstance(event.eta_seconds, (int, float))
            else None
        ),
    }
    return "[MMO-LIVE] " + json.dumps(payload, ensure_ascii=True, sort_keys=True)


class ProgressTracker:
    """Thread-safe tracker for progress snapshots + explainable log events."""

    def __init__(
        self,
        *,
        total_steps: int = 0,
        cancel_token: CancelToken | None = None,
        progress_listener: ProgressListener | None = None,
        log_listener: LogListener | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._total_steps = max(0, int(total_steps))
        self._completed_steps = 0
        self._phase = ""
        self._token = cancel_token or CancelToken()
        self._progress_listeners: list[ProgressListener] = []
        self._log_listeners: list[LogListener] = []
        if progress_listener is not None:
            self._progress_listeners.append(progress_listener)
        if log_listener is not None:
            self._log_listeners.append(log_listener)

    @property
    def cancel_token(self) -> CancelToken:
        return self._token

    def add_progress_listener(self, callback: ProgressListener) -> None:
        with self._lock:
            self._progress_listeners.append(callback)

    def add_log_listener(self, callback: LogListener) -> None:
        with self._lock:
            self._log_listeners.append(callback)

    def set_total_steps(self, total_steps: int) -> ProgressSnapshot:
        self._token.raise_if_cancelled()
        with self._lock:
            self._total_steps = max(0, int(total_steps))
            if self._total_steps and self._completed_steps > self._total_steps:
                self._completed_steps = self._total_steps
            snapshot = self._snapshot_locked()
            listeners = list(self._progress_listeners)
        self._notify_progress(listeners, snapshot)
        return snapshot

    def set_phase(self, phase: str) -> ProgressSnapshot:
        self._token.raise_if_cancelled()
        with self._lock:
            self._phase = str(phase).strip()
            snapshot = self._snapshot_locked()
            listeners = list(self._progress_listeners)
        self._notify_progress(listeners, snapshot)
        return snapshot

    def advance(
        self,
        *,
        steps: int = 1,
        phase: str | None = None,
        kind: str = "action",
        scope: str = "render",
        what: str | None = None,
        why: str | None = None,
        where: Iterable[str] | None = None,
        confidence: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ProgressSnapshot:
        self._token.raise_if_cancelled()
        step_delta = max(0, int(steps))
        with self._lock:
            if phase is not None:
                self._phase = str(phase).strip()
            self._completed_steps += step_delta
            if self._total_steps and self._completed_steps > self._total_steps:
                self._completed_steps = self._total_steps
            snapshot = self._snapshot_locked()
            progress_listeners = list(self._progress_listeners)
            log_listeners = list(self._log_listeners)
            event = self._build_event_locked(
                kind=kind,
                scope=scope,
                what=what,
                why=why,
                where=where,
                confidence=confidence,
                evidence=evidence,
                snapshot=snapshot,
            )
        self._notify_progress(progress_listeners, snapshot)
        if event is not None:
            self._notify_log(log_listeners, event)
        return snapshot

    def emit_log(
        self,
        *,
        kind: str,
        scope: str,
        what: str,
        why: str,
        where: Iterable[str] | None = None,
        confidence: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ExplainableLogEvent:
        self._token.raise_if_cancelled()
        with self._lock:
            snapshot = self._snapshot_locked()
            listeners = list(self._log_listeners)
            event = self._build_event_locked(
                kind=kind,
                scope=scope,
                what=what,
                why=why,
                where=where,
                confidence=confidence,
                evidence=evidence,
                snapshot=snapshot,
            )
        if event is None:
            raise ValueError("what and why are required for explainable logs.")
        self._notify_log(listeners, event)
        return event

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> ProgressSnapshot:
        total = self._total_steps
        done = self._completed_steps
        progress = 0.0
        if total > 0:
            progress = max(0.0, min(1.0, float(done) / float(total)))
        eta_seconds: float | None
        if total <= 0 or done <= 0:
            eta_seconds = None
        elif done >= total:
            eta_seconds = 0.0
        else:
            elapsed = max(0.0, time.monotonic() - self._started_at)
            eta_seconds = (elapsed / float(done)) * float(total - done)
        return ProgressSnapshot(
            total_steps=total,
            completed_steps=done,
            progress=progress,
            phase=self._phase,
            eta_seconds=eta_seconds,
            cancelled=self._token.is_cancelled,
            cancel_reason=self._token.reason,
        )

    def _build_event_locked(
        self,
        *,
        kind: str,
        scope: str,
        what: str | None,
        why: str | None,
        where: Iterable[str] | None,
        confidence: float | None,
        evidence: dict[str, Any] | None,
        snapshot: ProgressSnapshot,
    ) -> ExplainableLogEvent | None:
        normalized_what = str(what).strip() if isinstance(what, str) else ""
        normalized_why = str(why).strip() if isinstance(why, str) else ""
        if not normalized_what or not normalized_why:
            return None
        return ExplainableLogEvent(
            kind=str(kind).strip() or "info",
            scope=str(scope).strip() or "render",
            what=normalized_what,
            why=normalized_why,
            where=_normalize_where(where),
            confidence=_clamp_confidence(confidence),
            evidence=dict(evidence or {}),
            step_index=snapshot.completed_steps,
            total_steps=snapshot.total_steps,
            progress=snapshot.progress,
            eta_seconds=snapshot.eta_seconds,
        )

    @staticmethod
    def _notify_progress(
        listeners: list[ProgressListener],
        snapshot: ProgressSnapshot,
    ) -> None:
        for callback in listeners:
            try:
                callback(snapshot)
            except Exception:
                continue

    @staticmethod
    def _notify_log(
        listeners: list[LogListener],
        event: ExplainableLogEvent,
    ) -> None:
        for callback in listeners:
            try:
                callback(event)
            except Exception:
                continue


__all__ = [
    "CancelToken",
    "CancelledError",
    "ExplainableLogEvent",
    "ProgressSnapshot",
    "ProgressTracker",
    "ProgressListener",
    "LogListener",
    "format_live_log_line",
]

