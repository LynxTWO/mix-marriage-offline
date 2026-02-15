"""Tests for ``mmo project validate``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_validate" / str(os.getpid())
)


# -- helpers -----------------------------------------------------------------

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
    """Create a valid project scaffold and return the project_dir."""
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")
    project_dir = base / "project"
    exit_code, _, stderr = _run_main([
        "project", "init",
        "--stems-root", str(stems_root),
        "--out-dir", str(project_dir),
    ])
    assert exit_code == 0, f"project init failed: {stderr}"
    return project_dir


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- tests -------------------------------------------------------------------

class TestProjectValidateHappyPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "happy")

    def test_exit_code_zero_on_valid_scaffold(self) -> None:
        exit_code, stdout, stderr = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

    def test_output_is_valid_json(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])

    def test_all_required_files_valid(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        for check in result["checks"]:
            if check["required"]:
                self.assertEqual(
                    check["status"], "valid",
                    msg=f"{check['file']} should be valid: {check}",
                )

    def test_optional_files_missing_is_ok(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        optional_missing = [
            c for c in result["checks"]
            if not c["required"] and c["status"] == "missing"
        ]
        self.assertGreater(len(optional_missing), 0, "Expected some optional files missing")

    def test_summary_counts_correct(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        checks = result["checks"]
        summary = result["summary"]
        self.assertEqual(summary["total"], len(checks))
        self.assertEqual(
            summary["valid"],
            sum(1 for c in checks if c["status"] == "valid"),
        )
        self.assertEqual(
            summary["missing"],
            sum(1 for c in checks if c["status"] == "missing"),
        )
        self.assertEqual(
            summary["invalid"],
            sum(1 for c in checks if c["status"] == "invalid"),
        )


class TestProjectValidatePaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "paths")

    def test_no_backslashes_in_output(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertNotIn("\\", stdout, "Backslashes found in JSON output")

    def test_checks_sorted_by_file(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        files = [c["file"] for c in result["checks"]]
        self.assertEqual(files, sorted(files))


class TestProjectValidateDeterminism(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "determinism")

    def test_output_identical_across_runs(self) -> None:
        _, stdout_a, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        _, stdout_b, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertEqual(stdout_a, stdout_b)


class TestProjectValidateOutFlag(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "out_flag")

    def test_out_writes_file_matching_stdout(self) -> None:
        out_path = _SANDBOX / "out_flag" / "validation.json"
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
            "--out", str(out_path),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_path.is_file())
        self.assertEqual(out_path.read_text(encoding="utf-8"), stdout)


class TestProjectValidateErrors(unittest.TestCase):

    def test_missing_required_file_returns_exit_2(self) -> None:
        empty_dir = _SANDBOX / "missing_required" / "project"
        empty_dir.mkdir(parents=True, exist_ok=True)
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(empty_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        self.assertFalse(result["ok"])

    def test_invalid_json_reports_errors(self) -> None:
        base = _SANDBOX / "invalid_json"
        project_dir = _init_project(base)
        # Corrupt a required JSON file.
        bad_path = project_dir / "stems" / "stems_index.json"
        bad_path.write_text("{ not valid json !!!", encoding="utf-8")
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        self.assertFalse(result["ok"])
        bad_check = next(
            c for c in result["checks"] if c["file"] == "stems/stems_index.json"
        )
        self.assertEqual(bad_check["status"], "invalid")
        self.assertGreater(len(bad_check["errors"]), 0)

    def test_schema_violation_reports_errors(self) -> None:
        base = _SANDBOX / "schema_violation"
        project_dir = _init_project(base)
        # Write valid JSON but schema-invalid content.
        bad_path = project_dir / "stems" / "stems_index.json"
        bad_path.write_text('{"wrong": true}\n', encoding="utf-8")
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        bad_check = next(
            c for c in result["checks"] if c["file"] == "stems/stems_index.json"
        )
        self.assertEqual(bad_check["status"], "invalid")
        self.assertGreater(len(bad_check["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
