import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.cli import main


class TestCliEnvDoctor(unittest.TestCase):
    def _write_fake_tool(self, path: Path) -> Path:
        path.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        return path

    def _run_main(
        self,
        args: list[str],
        *,
        env_overrides: dict[str, str],
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env_overrides, clear=False):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _doctor_env(self, repo_root: Path, tools_dir: Path) -> dict[str, str]:
        ffmpeg_path = self._write_fake_tool(tools_dir / "ffmpeg.py")
        ffprobe_path = self._write_fake_tool(tools_dir / "ffprobe.py")
        return {
            "MMO_DATA_ROOT": os.fspath(repo_root),
            "MMO_CACHE_DIR": os.fspath(repo_root / ".mmo_cache" / "env_doctor_test"),
            "MMO_TEMP_DIR": os.fspath(repo_root / ".mmo_tmp" / "env_doctor_test"),
            "MMO_FFMPEG_PATH": os.fspath(ffmpeg_path),
            "MMO_FFPROBE_PATH": os.fspath(ffprobe_path),
        }

    def _assert_forward_slash_paths(self, payload: dict) -> None:
        path_fields = [
            payload["python"]["executable"],
            payload["paths"]["data_root"],
            payload["paths"]["schemas_dir"],
            payload["paths"]["ontology_dir"],
            payload["paths"]["presets_dir"],
            payload["paths"]["cache_dir"],
            payload["paths"]["temp_dir"],
            payload["paths"]["temp_root_selection"],
            payload["env_overrides"]["MMO_DATA_ROOT"]["path"],
            payload["env_overrides"]["MMO_CACHE_DIR"]["path"],
            payload["env_overrides"]["MMO_TEMP_DIR"]["path"],
            payload["env_overrides"]["MMO_FFMPEG_PATH"]["path"],
            payload["env_overrides"]["MMO_FFPROBE_PATH"]["path"],
        ]
        for field in path_fields:
            self.assertIsInstance(field, str)
            self.assertNotIn("\\", field, msg=f"Path must use forward slashes: {field}")

    def test_env_doctor_json_is_deterministic_and_shape_stable(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            env = self._doctor_env(repo_root, Path(temp_dir))

            first_exit, first_stdout, first_stderr = self._run_main(
                ["env", "doctor", "--format", "json"],
                env_overrides=env,
            )
            second_exit, second_stdout, second_stderr = self._run_main(
                ["env", "doctor", "--format", "json"],
                env_overrides=env,
            )

            self.assertEqual(first_exit, 0, msg=first_stderr)
            self.assertEqual(second_exit, 0, msg=second_stderr)
            self.assertEqual(first_stderr, second_stderr)
            self.assertEqual(first_stdout, second_stdout)

            payload = json.loads(first_stdout)
            self.assertEqual(sorted(payload.keys()), ["checks", "env_overrides", "paths", "python"])
            self.assertEqual(
                sorted(payload["python"].keys()),
                ["executable", "platform", "version"],
            )
            self.assertEqual(
                sorted(payload["paths"].keys()),
                [
                    "cache_dir",
                    "data_root",
                    "ontology_dir",
                    "presets_dir",
                    "schemas_dir",
                    "temp_dir",
                    "temp_root_selection",
                ],
            )
            self.assertEqual(
                sorted(payload["checks"].keys()),
                [
                    "cache_dir_writable",
                    "data_root_readable",
                    "ffmpeg_available",
                    "ffprobe_available",
                    "numpy_available",
                    "reportlab_available",
                    "temp_dir_writable",
                ],
            )
            self.assertEqual(
                sorted(payload["env_overrides"].keys()),
                [
                    "MMO_CACHE_DIR",
                    "MMO_DATA_ROOT",
                    "MMO_FFMPEG_PATH",
                    "MMO_FFPROBE_PATH",
                    "MMO_TEMP_DIR",
                ],
            )

            for env_name in (
                "MMO_DATA_ROOT",
                "MMO_CACHE_DIR",
                "MMO_TEMP_DIR",
                "MMO_FFMPEG_PATH",
                "MMO_FFPROBE_PATH",
            ):
                env_entry = payload["env_overrides"][env_name]
                self.assertEqual(sorted(env_entry.keys()), ["path", "present"])
                self.assertTrue(env_entry["present"])
                self.assertIsInstance(env_entry["path"], str)

            self.assertTrue(payload["checks"]["cache_dir_writable"])
            self.assertTrue(payload["checks"]["temp_dir_writable"])
            self.assertTrue(payload["checks"]["data_root_readable"])
            self.assertTrue(payload["checks"]["ffmpeg_available"])
            self.assertTrue(payload["checks"]["ffprobe_available"])
            self.assertIsInstance(payload["checks"]["numpy_available"], bool)
            self.assertIsInstance(payload["checks"]["reportlab_available"], bool)
            self.assertIn("source=", payload["paths"]["temp_root_selection"])
            self.assertIn("root=", payload["paths"]["temp_root_selection"])
            self.assertIn("fallback=", payload["paths"]["temp_root_selection"])
            self._assert_forward_slash_paths(payload)

    def test_env_doctor_text_has_stable_line_order(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            env = self._doctor_env(repo_root, Path(temp_dir))

            first_exit, first_stdout, first_stderr = self._run_main(
                ["env", "doctor", "--format", "text"],
                env_overrides=env,
            )
            second_exit, second_stdout, second_stderr = self._run_main(
                ["env", "doctor", "--format", "text"],
                env_overrides=env,
            )

            self.assertEqual(first_exit, 0, msg=first_stderr)
            self.assertEqual(second_exit, 0, msg=second_stderr)
            self.assertEqual(first_stderr, second_stderr)
            self.assertEqual(first_stdout, second_stdout)

            lines = [line for line in first_stdout.splitlines() if line]
            keys = [line.split("=", 1)[0] for line in lines]
            self.assertEqual(
                keys,
                [
                    "python.version",
                    "python.executable",
                    "python.platform",
                    "paths.data_root",
                    "paths.schemas_dir",
                    "paths.ontology_dir",
                    "paths.presets_dir",
                    "paths.cache_dir",
                    "paths.temp_dir",
                    "paths.temp_root_selection",
                    "checks.cache_dir_writable",
                    "checks.temp_dir_writable",
                    "checks.data_root_readable",
                    "checks.numpy_available",
                    "checks.ffmpeg_available",
                    "checks.ffprobe_available",
                    "checks.reportlab_available",
                    "env_overrides.MMO_DATA_ROOT.present",
                    "env_overrides.MMO_DATA_ROOT.path",
                    "env_overrides.MMO_CACHE_DIR.present",
                    "env_overrides.MMO_CACHE_DIR.path",
                    "env_overrides.MMO_TEMP_DIR.present",
                    "env_overrides.MMO_TEMP_DIR.path",
                    "env_overrides.MMO_FFMPEG_PATH.present",
                    "env_overrides.MMO_FFMPEG_PATH.path",
                    "env_overrides.MMO_FFPROBE_PATH.present",
                    "env_overrides.MMO_FFPROBE_PATH.path",
                ],
            )


if __name__ == "__main__":
    unittest.main()

# hash-pad-111
