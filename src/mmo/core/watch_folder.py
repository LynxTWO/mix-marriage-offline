from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from mmo.core.session import discover_stem_files
from mmo.core.stems_index import find_stem_sets
from mmo.core.target_tokens import resolve_target_token

DEFAULT_WATCH_TARGET_IDS: tuple[str, ...] = (
    "TARGET.STEREO.2_0",
    "TARGET.SURROUND.5_1",
    "TARGET.SURROUND.7_1",
)

_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9._-]+")

WATCH_QUEUE_STATE_PENDING = "pending"
WATCH_QUEUE_STATE_RUNNING = "running"
WATCH_QUEUE_STATE_SUCCEEDED = "succeeded"
WATCH_QUEUE_STATE_FAILED = "failed"
_WATCH_QUEUE_DONE_STATES = {
    WATCH_QUEUE_STATE_SUCCEEDED,
    WATCH_QUEUE_STATE_FAILED,
}
_WATCH_QUEUE_STATE_TOKENS: dict[str, str] = {
    WATCH_QUEUE_STATE_PENDING: "[..]",
    WATCH_QUEUE_STATE_RUNNING: "[>>]",
    WATCH_QUEUE_STATE_SUCCEEDED: "[OK]",
    WATCH_QUEUE_STATE_FAILED: "[!!]",
}
_WATCH_QUEUE_MOODS: tuple[str, ...] = (
    "fade-in",
    "lift",
    "drive",
    "resolve",
)


@dataclass(frozen=True)
class WatchFolderConfig:
    watch_dir: Path
    out_dir: Path | None = None
    target_ids: tuple[str, ...] = DEFAULT_WATCH_TARGET_IDS
    profile_id: str = "PROFILE.ASSIST"
    settle_seconds: float = 3.0
    poll_interval_seconds: float = 0.5
    include_existing: bool = True
    once: bool = False


@dataclass(frozen=True)
class ResolvedWatchFolderConfig:
    watch_dir: Path
    out_dir: Path
    target_ids: tuple[str, ...]
    profile_id: str
    settle_seconds: float
    poll_interval_seconds: float
    include_existing: bool
    once: bool


@dataclass(frozen=True)
class WatchQueueItem:
    batch_key: str
    stems_dir: Path
    out_dir: Path
    state: str = WATCH_QUEUE_STATE_PENDING
    return_code: int | None = None


@dataclass(frozen=True)
class WatchQueueSnapshot:
    tick: int
    total: int
    completed: int
    running: int
    failed: int
    pending: int
    progress: float
    items: tuple[WatchQueueItem, ...]


WatchQueueListener = Callable[[WatchQueueSnapshot], None]


class _WatchQueueState:
    def __init__(self, items: Sequence[WatchQueueItem]) -> None:
        self._tick = 0
        self._order = [item.batch_key for item in items]
        self._items = {item.batch_key: item for item in items}

    def snapshot(self) -> WatchQueueSnapshot:
        ordered_items = tuple(self._items[key] for key in self._order)
        total = len(ordered_items)
        running = sum(1 for row in ordered_items if row.state == WATCH_QUEUE_STATE_RUNNING)
        failed = sum(1 for row in ordered_items if row.state == WATCH_QUEUE_STATE_FAILED)
        pending = sum(1 for row in ordered_items if row.state == WATCH_QUEUE_STATE_PENDING)
        completed = sum(1 for row in ordered_items if row.state in _WATCH_QUEUE_DONE_STATES)
        if total == 0:
            progress = 1.0
        else:
            weighted = 0.0
            for row in ordered_items:
                if row.state == WATCH_QUEUE_STATE_PENDING:
                    weighted += 0.0
                elif row.state == WATCH_QUEUE_STATE_RUNNING:
                    weighted += 0.6
                else:
                    weighted += 1.0
            progress = weighted / float(total)
        return WatchQueueSnapshot(
            tick=self._tick,
            total=total,
            completed=completed,
            running=running,
            failed=failed,
            pending=pending,
            progress=progress,
            items=ordered_items,
        )

    def mark_running(self, batch_key: str) -> WatchQueueSnapshot:
        item = self._items.get(batch_key)
        if item is None:
            return self.snapshot()
        if item.state == WATCH_QUEUE_STATE_RUNNING:
            return self.snapshot()
        self._items[batch_key] = replace(
            item,
            state=WATCH_QUEUE_STATE_RUNNING,
            return_code=None,
        )
        self._tick += 1
        return self.snapshot()

    def mark_finished(self, batch_key: str, *, exit_code: int) -> WatchQueueSnapshot:
        item = self._items.get(batch_key)
        if item is None:
            return self.snapshot()
        state = WATCH_QUEUE_STATE_SUCCEEDED if int(exit_code) == 0 else WATCH_QUEUE_STATE_FAILED
        self._items[batch_key] = replace(
            item,
            state=state,
            return_code=int(exit_code),
        )
        self._tick += 1
        return self.snapshot()


@dataclass
class WatchBatchTracker:
    _signatures: dict[str, str] = field(default_factory=dict)

    def collect_changed_stem_sets(self, watch_dir: Path) -> list[Path]:
        resolved_watch_dir = _resolve_existing_directory(watch_dir, label="Watch folder")
        current_signatures: dict[str, str] = {}
        changed_stem_sets: list[Path] = []

        candidate_stem_sets = sorted(
            find_stem_sets(resolved_watch_dir),
            key=lambda item: item.resolve().as_posix(),
        )
        for candidate in candidate_stem_sets:
            stems_dir = candidate.resolve()
            batch_key = batch_key_from_stems_dir(
                watch_dir=resolved_watch_dir,
                stems_dir=stems_dir,
            )
            signature = stem_set_signature(stems_dir)
            if not signature:
                continue
            current_signatures[batch_key] = signature
            if self._signatures.get(batch_key) != signature:
                changed_stem_sets.append(stems_dir)

        self._signatures = current_signatures
        return changed_stem_sets


class _DirtyState:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._dirty = False
        self._last_change_s = 0.0

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            self._last_change_s = self._clock()

    def consume_if_ready(self, settle_seconds: float) -> bool:
        with self._lock:
            if not self._dirty:
                return False
            if self._clock() - self._last_change_s < settle_seconds:
                return False
            self._dirty = False
            return True


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _resolve_existing_directory(path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError(f"{label} does not exist: {path}")
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory: {path}")
    return resolved


def parse_watch_targets_csv(raw_value: str | None) -> tuple[str, ...]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return DEFAULT_WATCH_TARGET_IDS

    seen: set[str] = set()
    target_ids: list[str] = []
    from mmo.core.registries.render_targets_registry import (  # noqa: WPS433
        load_render_targets_registry,
    )
    target_registry = load_render_targets_registry()

    for part in raw_value.split(","):
        token = part.strip()
        if not token:
            continue
        resolved = resolve_target_token(token)
        resolved_target_id: str | None = resolved.target_id
        if not resolved_target_id:
            candidates = sorted(
                {
                    _coerce_str(row.get("target_id")).strip()
                    for row in target_registry.find_targets_for_layout(resolved.layout_id)
                    if isinstance(row, dict)
                    and _coerce_str(row.get("target_id")).strip()
                }
            )
            if len(candidates) == 1:
                resolved_target_id = candidates[0]
            elif len(candidates) > 1:
                raise ValueError(
                    (
                        f"Ambiguous target token: {token}. "
                        f"Candidates: {', '.join(candidates)}"
                    )
                )
            else:
                raise ValueError(
                    (
                        f"Target token resolved to {resolved.layout_id}, "
                        "but no render target maps to that layout."
                    )
                )

        if resolved_target_id in seen:
            continue
        seen.add(resolved_target_id)
        target_ids.append(resolved_target_id)

    if not target_ids:
        raise ValueError("Watch targets list cannot be empty.")
    return tuple(target_ids)


def resolve_watch_folder_config(config: WatchFolderConfig) -> ResolvedWatchFolderConfig:
    watch_dir = _resolve_existing_directory(config.watch_dir, label="Watch folder")
    out_dir = (config.out_dir.resolve() if config.out_dir else (watch_dir / "_mmo_watch_out").resolve())

    if config.settle_seconds <= 0.0:
        raise ValueError("--settle-seconds must be a positive number.")
    if config.poll_interval_seconds <= 0.0:
        raise ValueError("--poll-interval must be a positive number.")
    if not config.target_ids:
        raise ValueError("At least one watch target is required.")

    normalized_profile = config.profile_id.strip() if isinstance(config.profile_id, str) else ""
    if not normalized_profile:
        raise ValueError("--profile must be a non-empty string.")

    return ResolvedWatchFolderConfig(
        watch_dir=watch_dir,
        out_dir=out_dir,
        target_ids=tuple(config.target_ids),
        profile_id=normalized_profile,
        settle_seconds=float(config.settle_seconds),
        poll_interval_seconds=float(config.poll_interval_seconds),
        include_existing=bool(config.include_existing),
        once=bool(config.once),
    )


def batch_key_from_stems_dir(*, watch_dir: Path, stems_dir: Path) -> str:
    resolved_watch_dir = watch_dir.resolve()
    resolved_stems_dir = stems_dir.resolve()
    try:
        relative = resolved_stems_dir.relative_to(resolved_watch_dir)
    except ValueError:
        return resolved_stems_dir.as_posix()
    if str(relative) in {"", "."}:
        return "."
    return relative.as_posix()


def stem_set_signature(stems_dir: Path) -> str:
    resolved_stems_dir = stems_dir.resolve()
    digest = hashlib.sha1()
    seen_files = 0
    for stem_path in discover_stem_files(resolved_stems_dir):
        try:
            stem_stat = stem_path.stat()
        except OSError:
            continue

        try:
            relative_path = stem_path.relative_to(resolved_stems_dir).as_posix()
        except ValueError:
            relative_path = stem_path.resolve().as_posix()

        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stem_stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stem_stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\n")
        seen_files += 1

    if seen_files == 0:
        return ""
    return digest.hexdigest()


def _slugify_path_token(token: str) -> str:
    normalized = _SLUG_CLEAN_RE.sub("_", token.casefold()).strip("._-")
    return normalized or "set"


def batch_out_dir_for_stems_dir(
    *,
    out_root: Path,
    watch_dir: Path,
    stems_dir: Path,
) -> Path:
    batch_key = batch_key_from_stems_dir(watch_dir=watch_dir, stems_dir=stems_dir)
    if batch_key == ".":
        slug = "root"
    else:
        slug = "__".join(_slugify_path_token(part) for part in batch_key.split("/"))
    key_hash = hashlib.sha1(batch_key.encode("utf-8")).hexdigest()[:8]
    return out_root.resolve() / f"{slug}__{key_hash}"


def _clamp(value: float, *, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _watch_queue_label(item: WatchQueueItem) -> str:
    label = "root" if item.batch_key == "." else item.batch_key
    return label.replace("\\", "/")


def render_watch_queue_snapshot(
    snapshot: WatchQueueSnapshot,
    *,
    width: int = 44,
    cinematic: bool = True,
) -> str:
    bar_width = max(12, min(96, int(width)))
    progress = _clamp(snapshot.progress, lo=0.0, hi=1.0)
    filled = int(round(progress * bar_width))
    if filled <= 0:
        bar = "." * bar_width
    elif filled >= bar_width:
        bar = "=" * bar_width
    else:
        bar = ("=" * (filled - 1)) + ">" + ("." * (bar_width - filled))

    mood = _WATCH_QUEUE_MOODS[snapshot.tick % len(_WATCH_QUEUE_MOODS)] if cinematic else "steady"
    lines = [
        (
            "watch queue | total="
            f"{snapshot.total} done={snapshot.completed} run={snapshot.running} "
            f"fail={snapshot.failed} pending={snapshot.pending}"
        ),
        f"[{bar}] {int(round(progress * 100.0)):3d}% | mood={mood}",
    ]

    for item in snapshot.items[:8]:
        state_token = _WATCH_QUEUE_STATE_TOKENS.get(item.state, "[??]")
        suffix = ""
        if item.state == WATCH_QUEUE_STATE_FAILED and item.return_code is not None:
            suffix = f" (exit {item.return_code})"
        elif item.state == WATCH_QUEUE_STATE_RUNNING:
            suffix = " (rendering)"
        lines.append(f"{state_token} {_watch_queue_label(item)}{suffix}")

    if len(snapshot.items) > 8:
        lines.append(f"... +{len(snapshot.items) - 8} more batch(es)")

    return "\n".join(lines)


def build_render_many_run_argv(
    *,
    stems_dir: Path,
    out_dir: Path,
    target_ids: Sequence[str],
    profile_id: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "mmo",
        "run",
        "--stems",
        stems_dir.resolve().as_posix(),
        "--out",
        out_dir.resolve().as_posix(),
        "--render-many",
        "--targets",
        ",".join(target_ids),
        "--profile",
        profile_id,
    ]


def _default_command_runner(argv: Sequence[str]) -> int:
    completed = subprocess.run(list(argv), check=False)
    return int(completed.returncode)


def _start_watchdog_observer(
    *,
    watch_dir: Path,
    mark_dirty: Callable[[], None],
) -> Any:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except Exception as exc:  # pragma: no cover - dependency/runtime specific
        raise RuntimeError(
            "watch mode requires the optional 'watchdog' dependency. Install with: pip install watchdog"
        ) from exc

    class _WatchHandler(FileSystemEventHandler):  # pragma: no cover - callback-only
        def on_any_event(self, event: Any) -> None:
            if getattr(event, "event_type", "") in {"opened", "closed"}:
                return
            mark_dirty()

    observer = Observer()
    observer.schedule(_WatchHandler(), str(watch_dir), recursive=True)
    observer.start()
    return observer


def _stop_watchdog_observer(observer: Any) -> None:
    try:
        observer.stop()
        observer.join(timeout=5.0)
    except Exception:
        return


def _process_changed_stem_sets(
    *,
    config: ResolvedWatchFolderConfig,
    tracker: WatchBatchTracker,
    command_runner: Callable[[Sequence[str]], int],
    log: Callable[[str], None],
    log_error: Callable[[str], None],
    queue_listener: WatchQueueListener | None = None,
) -> int:
    failures = 0
    changed_stem_sets = tracker.collect_changed_stem_sets(config.watch_dir)
    queue_items: list[WatchQueueItem] = []
    for stems_dir in changed_stem_sets:
        queue_items.append(
            WatchQueueItem(
                batch_key=batch_key_from_stems_dir(
                    watch_dir=config.watch_dir,
                    stems_dir=stems_dir,
                ),
                stems_dir=stems_dir,
                out_dir=batch_out_dir_for_stems_dir(
                    out_root=config.out_dir,
                    watch_dir=config.watch_dir,
                    stems_dir=stems_dir,
                ),
            )
        )

    queue_state = _WatchQueueState(queue_items)
    if queue_listener is not None:
        queue_listener(queue_state.snapshot())

    for item in queue_items:
        if queue_listener is not None:
            queue_listener(queue_state.mark_running(item.batch_key))

        stems_dir = item.stems_dir
        out_dir = item.out_dir
        batch_key = item.batch_key
        out_dir.mkdir(parents=True, exist_ok=True)
        argv = build_render_many_run_argv(
            stems_dir=stems_dir,
            out_dir=out_dir,
            target_ids=config.target_ids,
            profile_id=config.profile_id,
        )
        log(f"watch: batch={batch_key} -> {out_dir.as_posix()}")
        exit_code = command_runner(argv)
        if queue_listener is not None:
            queue_listener(queue_state.mark_finished(batch_key, exit_code=exit_code))
        if exit_code != 0:
            failures += 1
            log_error(f"watch: batch failed ({exit_code}) for {stems_dir.as_posix()}")
    return 0 if failures == 0 else 1


def run_watch_folder(
    config: WatchFolderConfig,
    *,
    command_runner: Callable[[Sequence[str]], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    stop_event: threading.Event | None = None,
    log: Callable[[str], None] = print,
    log_error: Callable[[str], None] | None = None,
    queue_listener: WatchQueueListener | None = None,
) -> int:
    resolved = resolve_watch_folder_config(config)
    resolved.out_dir.mkdir(parents=True, exist_ok=True)
    command = command_runner or _default_command_runner
    error_writer = log_error or (lambda message: print(message, file=sys.stderr))
    tracker = WatchBatchTracker()

    if resolved.once:
        if not resolved.include_existing:
            return 0
        return _process_changed_stem_sets(
            config=resolved,
            tracker=tracker,
            command_runner=command,
            log=log,
            log_error=error_writer,
            queue_listener=queue_listener,
        )

    if not resolved.include_existing:
        # Prime signatures so the first filesystem event only processes
        # newly changed/newly added stem sets, not everything already present.
        tracker.collect_changed_stem_sets(resolved.watch_dir)

    dirty_state = _DirtyState(clock)
    if resolved.include_existing:
        dirty_state.mark_dirty()

    observer = _start_watchdog_observer(watch_dir=resolved.watch_dir, mark_dirty=dirty_state.mark_dirty)
    log(f"watch: listening for stems under {resolved.watch_dir.as_posix()}")
    log(f"watch: writing batches under {resolved.out_dir.as_posix()}")
    overall_status = 0

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return overall_status
            if dirty_state.consume_if_ready(resolved.settle_seconds):
                batch_status = _process_changed_stem_sets(
                    config=resolved,
                    tracker=tracker,
                    command_runner=command,
                    log=log,
                    log_error=error_writer,
                    queue_listener=queue_listener,
                )
                if batch_status != 0:
                    overall_status = 1
            sleeper(resolved.poll_interval_seconds)
    except KeyboardInterrupt:
        return 130
    finally:
        _stop_watchdog_observer(observer)


__all__ = [
    "DEFAULT_WATCH_TARGET_IDS",
    "WATCH_QUEUE_STATE_PENDING",
    "WATCH_QUEUE_STATE_RUNNING",
    "WATCH_QUEUE_STATE_SUCCEEDED",
    "WATCH_QUEUE_STATE_FAILED",
    "WatchFolderConfig",
    "ResolvedWatchFolderConfig",
    "WatchBatchTracker",
    "WatchQueueItem",
    "WatchQueueSnapshot",
    "WatchQueueListener",
    "batch_key_from_stems_dir",
    "stem_set_signature",
    "batch_out_dir_for_stems_dir",
    "build_render_many_run_argv",
    "render_watch_queue_snapshot",
    "parse_watch_targets_csv",
    "resolve_watch_folder_config",
    "run_watch_folder",
]
