from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from mmo.core.watch_folder import (
    DEFAULT_WATCH_TARGET_IDS,
    WatchBatchTracker,
    WatchFolderConfig,
    WatchQueueSnapshot,
    batch_out_dir_for_stems_dir,
    parse_watch_targets_csv,
    render_watch_queue_snapshot,
    run_watch_folder,
)


def _write_audio(path: Path, payload: bytes = b"\x00\x01\x02\x03") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class TestWatchFolder(unittest.TestCase):
    def test_parse_watch_targets_csv_defaults_and_deduplicates(self) -> None:
        self.assertEqual(parse_watch_targets_csv(None), DEFAULT_WATCH_TARGET_IDS)
        self.assertEqual(
            parse_watch_targets_csv("TARGET.STEREO.2_0, TARGET.STEREO.2_0 ,TARGET.SURROUND.5_1"),
            ("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
        )

    def test_batch_tracker_detects_changed_stem_sets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            watch_root = Path(td) / "watch"
            stems_dir = watch_root / "album_a"
            stem_file = stems_dir / "kick.wav"
            _write_audio(stem_file, b"\x01\x02")

            tracker = WatchBatchTracker()
            first = tracker.collect_changed_stem_sets(watch_root)
            self.assertEqual(first, [stems_dir.resolve()])

            second = tracker.collect_changed_stem_sets(watch_root)
            self.assertEqual(second, [])

            _write_audio(stem_file, b"\x01\x02\x03\x04\x05")
            os.utime(stem_file, None)
            third = tracker.collect_changed_stem_sets(watch_root)
            self.assertEqual(third, [stems_dir.resolve()])

    def test_batch_out_dir_for_stems_dir_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch_dir = root / "watch"
            stems_dir = watch_dir / "mix 01"
            out_root = root / "out"
            _write_audio(stems_dir / "kick.wav")

            first = batch_out_dir_for_stems_dir(
                out_root=out_root,
                watch_dir=watch_dir,
                stems_dir=stems_dir,
            )
            second = batch_out_dir_for_stems_dir(
                out_root=out_root,
                watch_dir=watch_dir,
                stems_dir=stems_dir,
            )
            self.assertEqual(first, second)
            self.assertTrue(first.name.startswith("mix_01__"))

    def test_run_watch_folder_once_executes_render_many_batches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch_dir = root / "watch"
            _write_audio(watch_dir / "set_a" / "kick.wav")
            _write_audio(watch_dir / "set_b" / "snare.wav")

            seen_argvs: list[list[str]] = []

            def _fake_runner(argv: list[str] | tuple[str, ...]) -> int:
                seen_argvs.append(list(argv))
                return 0

            config = WatchFolderConfig(
                watch_dir=watch_dir,
                out_dir=root / "renders",
                target_ids=("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
                once=True,
                include_existing=True,
            )
            exit_code = run_watch_folder(
                config,
                command_runner=_fake_runner,
                log=lambda _: None,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(seen_argvs), 2)
            for argv in seen_argvs:
                self.assertEqual(argv[:4], [sys.executable, "-m", "mmo", "run"])
                self.assertIn("--render-many", argv)
                self.assertIn("--targets", argv)
                self.assertIn("TARGET.STEREO.2_0,TARGET.SURROUND.5_1", argv)

    def test_render_watch_queue_snapshot_is_stable_and_cinematic(self) -> None:
        snapshot = WatchQueueSnapshot(
            tick=3,
            total=3,
            completed=1,
            running=1,
            failed=0,
            pending=1,
            progress=0.53,
            items=(),
        )

        rendered = render_watch_queue_snapshot(snapshot, width=20, cinematic=True)
        self.assertIn("watch queue | total=3 done=1 run=1 fail=0 pending=1", rendered)
        self.assertIn("| mood=resolve", rendered)
        self.assertIn("[==========>.........]  53%", rendered)

    def test_run_watch_folder_once_emits_visual_queue_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch_dir = root / "watch"
            _write_audio(watch_dir / "set_a" / "kick.wav")
            _write_audio(watch_dir / "set_b" / "snare.wav")

            seen_snapshots: list[WatchQueueSnapshot] = []
            run_calls = 0

            def _fake_runner(_argv: list[str] | tuple[str, ...]) -> int:
                nonlocal run_calls
                run_calls += 1
                return 0

            config = WatchFolderConfig(
                watch_dir=watch_dir,
                out_dir=root / "renders",
                target_ids=("TARGET.STEREO.2_0",),
                once=True,
                include_existing=True,
            )
            exit_code = run_watch_folder(
                config,
                command_runner=_fake_runner,
                queue_listener=seen_snapshots.append,
                log=lambda _: None,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_calls, 2)
            self.assertEqual(len(seen_snapshots), 5)
            first = seen_snapshots[0]
            self.assertEqual(first.pending, 2)
            self.assertEqual(first.running, 0)
            self.assertEqual(first.completed, 0)
            self.assertAlmostEqual(first.progress, 0.0)

            last = seen_snapshots[-1]
            self.assertEqual(last.total, 2)
            self.assertEqual(last.completed, 2)
            self.assertEqual(last.running, 0)
            self.assertEqual(last.failed, 0)
            self.assertAlmostEqual(last.progress, 1.0)
            self.assertEqual(
                tuple(item.state for item in last.items),
                ("succeeded", "succeeded"),
            )

    def test_watch_mode_no_existing_processes_only_new_sets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch_dir = root / "watch"
            _write_audio(watch_dir / "existing_set" / "kick.wav")

            seen_argvs: list[list[str]] = []

            def _fake_runner(argv: list[str] | tuple[str, ...]) -> int:
                seen_argvs.append(list(argv))
                return 0

            mark_dirty_holder: dict[str, object] = {}
            stop_event = threading.Event()

            fake_time = 0.0

            def _fake_clock() -> float:
                return fake_time

            class _FakeObserver:
                def stop(self) -> None:
                    return None

                def join(self, timeout: float | None = None) -> None:
                    return None

            def _fake_start_watchdog_observer(*, watch_dir: Path, mark_dirty: object) -> _FakeObserver:
                del watch_dir
                mark_dirty_holder["callback"] = mark_dirty
                return _FakeObserver()

            sleep_calls = 0

            def _fake_sleep(_seconds: float) -> None:
                nonlocal sleep_calls, fake_time
                sleep_calls += 1
                fake_time += max(_seconds, 1e-5)  # always advance at least a tick
                if sleep_calls == 1:
                    _write_audio(watch_dir / "new_set" / "snare.wav")
                    callback = mark_dirty_holder.get("callback")
                    self.assertTrue(callable(callback))
                    if callable(callback):
                        callback()
                    fake_time += 0.01  # guarantee > settle_seconds=1e-6
                elif sleep_calls >= 5:
                    stop_event.set()

            config = WatchFolderConfig(
                watch_dir=watch_dir,
                out_dir=root / "renders",
                target_ids=("TARGET.STEREO.2_0",),
                settle_seconds=1e-6,
                poll_interval_seconds=1e-6,
                include_existing=False,
                once=False,
            )

            with patch(
                "mmo.core.watch_folder._start_watchdog_observer",
                side_effect=_fake_start_watchdog_observer,
            ):
                exit_code = run_watch_folder(
                    config,
                    command_runner=_fake_runner,
                    sleeper=_fake_sleep,
                    stop_event=stop_event,
                    clock=_fake_clock,
                    log=lambda _: None,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(seen_argvs), 1)
            argv = seen_argvs[0]
            stems_idx = argv.index("--stems") + 1
            self.assertEqual(
                argv[stems_idx],
                (watch_dir / "new_set").resolve().as_posix(),
            )


if __name__ == "__main__":
    unittest.main()
