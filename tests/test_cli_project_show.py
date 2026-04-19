"""Tests for ``mmo project show``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_show" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _init_project(base: Path) -> Path:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")
    project_dir = base / "project"
    exit_code, _, stderr = _run_main(
        [
            "project",
            "init",
            "--stems-root",
            str(stems_root),
            "--out-dir",
            str(project_dir),
        ]
    )
    assert exit_code == 0, f"project init failed: {stderr}"
    return project_dir


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil

    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


def _artifact_rows_by_path(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    return {
        row["path"]: row
        for row in artifacts
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }


class TestProjectShowJSON(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "json")

    def test_json_contains_allowlisted_artifact_metadata(self) -> None:
        exit_code, stdout, stderr = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertEqual(payload["project_dir"], self.project_dir.resolve().as_posix())
        self.assertIn("schema_versions", payload)
        self.assertIn("last_built_markers", payload)

        artifacts = payload.get("artifacts")
        self.assertIsInstance(artifacts, list)
        if not isinstance(artifacts, list):
            return
        artifact_paths = [row["path"] for row in artifacts if isinstance(row, dict)]
        self.assertEqual(artifact_paths, sorted(artifact_paths))
        self.assertIn("stems/stems_index.json", artifact_paths)
        self.assertIn("listen_pack.json", artifact_paths)

        by_path = _artifact_rows_by_path(payload)
        stems_index = by_path["stems/stems_index.json"]
        self.assertTrue(stems_index["exists"])
        self.assertTrue(stems_index["required"])
        self.assertIsInstance(stems_index["sha256"], str)
        if isinstance(stems_index["sha256"], str):
            self.assertEqual(len(stems_index["sha256"]), 64)
        self.assertTrue(stems_index["last_built_marker"].startswith("sha256:"))

        listen_pack = by_path["listen_pack.json"]
        self.assertFalse(listen_pack["exists"])
        self.assertFalse(listen_pack["required"])
        self.assertIsNone(listen_pack["sha256"])
        self.assertEqual(listen_pack["last_built_marker"], "missing")

        self.assertNotIn("\\", stdout)

    def test_json_output_is_byte_identical_across_runs(self) -> None:
        _, stdout_a, _ = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json"]
        )
        _, stdout_b, _ = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json"]
        )
        self.assertEqual(stdout_a, stdout_b)

    def test_shared_json_redacts_machine_local_paths(self) -> None:
        exit_code, stdout, stderr = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json-shared"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertNotIn("project_dir", payload)
        self.assertTrue(payload["paths_redacted"])
        self.assertIn("schema_versions", payload)
        self.assertIn("last_built_markers", payload)
        self.assertNotIn(self.project_dir.resolve().as_posix(), stdout)

        by_path = _artifact_rows_by_path(payload)
        self.assertIn("stems/stems_index.json", by_path)
        self.assertIn("listen_pack.json", by_path)
        self.assertNotIn("absolute_path", by_path["stems/stems_index.json"])
        self.assertTrue(by_path["stems/stems_index.json"]["exists"])
        self.assertTrue(by_path["stems/stems_index.json"]["required"])
        self.assertEqual(by_path["listen_pack.json"]["last_built_marker"], "missing")

    def test_shared_json_output_is_byte_identical_across_runs(self) -> None:
        _, stdout_a, _ = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json-shared"]
        )
        _, stdout_b, _ = _run_main(
            ["project", "show", str(self.project_dir), "--format", "json-shared"]
        )
        self.assertEqual(stdout_a, stdout_b)

    def test_project_show_defaults_to_shared_json(self) -> None:
        exit_code, stdout, stderr = _run_main(["project", "show", str(self.project_dir)])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertNotIn("project_dir", payload)
        self.assertTrue(payload["paths_redacted"])
        by_path = _artifact_rows_by_path(payload)
        self.assertIn("stems/stems_index.json", by_path)
        self.assertNotIn("absolute_path", by_path["stems/stems_index.json"])
        self.assertNotIn(self.project_dir.resolve().as_posix(), stdout)


class TestProjectShowNoScanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "no_scan")
        (cls.project_dir / "renders").mkdir(parents=True, exist_ok=True)
        (cls.project_dir / "logs").mkdir(parents=True, exist_ok=True)
        (cls.project_dir / "logs" / "event_log.jsonl").write_text(
            '{"ignored": true}\n',
            encoding="utf-8",
        )
        (cls.project_dir / "renders" / "ignored.non_allowlisted.json").write_text(
            '{"ignored": true}\n',
            encoding="utf-8",
        )

    def test_project_show_does_not_call_glob_or_rglob(self) -> None:
        project_root = self.project_dir.resolve()
        project_glob_calls: list[tuple[str, str]] = []
        project_rglob_calls: list[tuple[str, str]] = []
        original_glob = Path.glob
        original_rglob = Path.rglob

        def _guarded_glob(path_obj: Path, pattern: str):  # type: ignore[no-untyped-def]
            resolved = path_obj.resolve()
            if resolved == project_root or _is_within(resolved, project_root):
                project_glob_calls.append((resolved.as_posix(), pattern))
            return original_glob(path_obj, pattern)

        def _guarded_rglob(path_obj: Path, pattern: str):  # type: ignore[no-untyped-def]
            resolved = path_obj.resolve()
            if resolved == project_root or _is_within(resolved, project_root):
                project_rglob_calls.append((resolved.as_posix(), pattern))
            return original_rglob(path_obj, pattern)

        with patch("pathlib.Path.glob", new=_guarded_glob), patch(
            "pathlib.Path.rglob",
            new=_guarded_rglob,
        ):
            exit_code, stdout, stderr = _run_main(
                ["project", "show", str(self.project_dir), "--format", "json"]
            )
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(project_glob_calls, [])
        self.assertEqual(project_rglob_calls, [])
        self.assertNotIn("ignored.non_allowlisted.json", stdout)
        self.assertNotIn("logs/event_log.jsonl", stdout)


class TestProjectShowStableErrors(unittest.TestCase):
    def test_missing_project_directory_error_is_stable(self) -> None:
        missing_dir = _SANDBOX / "errors" / "missing_project"
        command = ["project", "show", str(missing_dir), "--format", "json"]
        exit_code_a, stdout_a, stderr_a = _run_main(command)
        exit_code_b, stdout_b, stderr_b = _run_main(command)

        self.assertEqual(exit_code_a, 1)
        self.assertEqual(exit_code_b, 1)
        self.assertEqual(stdout_a, "")
        self.assertEqual(stdout_b, "")
        self.assertEqual(stderr_a, stderr_b)
        self.assertEqual(
            stderr_a.strip(),
            f"Project directory does not exist: {missing_dir.as_posix()}",
        )

    def test_missing_project_directory_argument_error_is_stable(self) -> None:
        command = ["project", "show", "--format", "json"]
        exit_code_a, stdout_a, stderr_a = _run_main(command)
        exit_code_b, stdout_b, stderr_b = _run_main(command)

        self.assertEqual(exit_code_a, 1)
        self.assertEqual(exit_code_b, 1)
        self.assertEqual(stdout_a, "")
        self.assertEqual(stdout_b, "")
        self.assertEqual(stderr_a, stderr_b)
        self.assertEqual(
            stderr_a.strip(),
            (
                "Missing project directory. Usage: "
                "mmo project show <project_dir> "
                "[--format json|json-shared|text]."
            ),
        )


if __name__ == "__main__":
    unittest.main()
