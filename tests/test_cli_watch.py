from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mmo.cli import main
from mmo.core.watch_folder import WatchFolderConfig, WatchQueueSnapshot


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestCliWatch(unittest.TestCase):
    def test_watch_command_builds_config_and_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            watch_dir = Path(td) / "incoming"
            watch_dir.mkdir(parents=True, exist_ok=True)

            with patch("mmo.cli.run_watch_folder", return_value=0) as run_watch:
                exit_code, stdout_text, stderr_text = _run_main(
                    [
                        "watch",
                        watch_dir.as_posix(),
                        "--once",
                        "--targets",
                        "TARGET.STEREO.2_0,TARGET.SURROUND.5_1",
                        "--no-existing",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout_text, "")
            self.assertEqual(stderr_text, "")
            run_watch.assert_called_once()
            config = run_watch.call_args.args[0]
            self.assertIsInstance(config, WatchFolderConfig)
            self.assertEqual(config.watch_dir, watch_dir)
            self.assertTrue(config.once)
            self.assertFalse(config.include_existing)
            self.assertEqual(
                config.target_ids,
                ("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
            )

    def test_watch_command_rejects_empty_targets_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            watch_dir = Path(td) / "incoming"
            watch_dir.mkdir(parents=True, exist_ok=True)

            exit_code, _stdout_text, stderr_text = _run_main(
                [
                    "watch",
                    watch_dir.as_posix(),
                    "--targets",
                    ",,,",
                ]
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("cannot be empty", stderr_text.lower())

    def test_watch_command_visual_queue_prints_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            watch_dir = Path(td) / "incoming"
            watch_dir.mkdir(parents=True, exist_ok=True)

            def _fake_watch(config: WatchFolderConfig, **kwargs: object) -> int:
                del config
                listener = kwargs.get("queue_listener")
                self.assertTrue(callable(listener))
                if callable(listener):
                    listener(
                        WatchQueueSnapshot(
                            tick=1,
                            total=1,
                            completed=0,
                            running=1,
                            failed=0,
                            pending=0,
                            progress=0.6,
                            items=(),
                        )
                    )
                return 0

            with patch("mmo.cli.run_watch_folder", side_effect=_fake_watch):
                exit_code, stdout_text, stderr_text = _run_main(
                    [
                        "watch",
                        watch_dir.as_posix(),
                        "--visual-queue",
                        "--cinematic-progress",
                        "--once",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr_text, "")
            self.assertIn("watch queue | total=1 done=0 run=1 fail=0 pending=0", stdout_text)
            self.assertIn("mood=lift", stdout_text)


if __name__ == "__main__":
    unittest.main()
