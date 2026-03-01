"""Tests for tools/validate_user_manual.py and tools/build_user_manual.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_SCRIPT = REPO_ROOT / "tools" / "validate_user_manual.py"
BUILD_SCRIPT = REPO_ROOT / "tools" / "build_user_manual.py"
MANUAL_YAML = REPO_ROOT / "docs" / "manual" / "manual.yaml"
CHAPTERS_DIR = REPO_ROOT / "docs" / "manual"

_HAS_REPORTLAB = False
try:
    import reportlab  # noqa: F401
    _HAS_REPORTLAB = True
except ImportError:
    pass


def _python() -> str:
    return os.fspath(os.getenv("PYTHON", "") or sys.executable)


def _run_validator(extra_args: list[str] | None = None) -> tuple[int, dict]:
    cmd = [_python(), str(VALIDATE_SCRIPT), "--repo-root", str(REPO_ROOT)]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "errors": [f"Invalid JSON output: {result.stdout!r}"]}
    return result.returncode, payload


class TestValidateUserManualOnCurrentRepo(unittest.TestCase):
    """Validate the real docs/manual/ directory."""

    def test_validator_runs_and_produces_json(self) -> None:
        returncode, payload = _run_validator()
        self.assertIsInstance(payload, dict, "stdout must be valid JSON")

    def test_validator_passes_on_valid_repo(self) -> None:
        returncode, payload = _run_validator()
        self.assertTrue(
            payload.get("ok"),
            f"Validator reported errors: {payload.get('errors')}",
        )
        self.assertEqual(returncode, 0)

    def test_chapter_count_matches_manifest(self) -> None:
        with MANUAL_YAML.open(encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh)
        expected = len(manifest.get("chapters", []))
        _returncode, payload = _run_validator()
        self.assertEqual(payload.get("chapter_count"), expected)

    def test_no_missing_chapters(self) -> None:
        _returncode, payload = _run_validator()
        self.assertEqual(
            payload.get("missing_chapters", []),
            [],
            f"Missing chapters: {payload.get('missing_chapters')}",
        )

    def test_glossary_terms_nonzero(self) -> None:
        _returncode, payload = _run_validator()
        self.assertGreater(
            payload.get("glossary_term_count", 0),
            0,
            "Expected at least one glossary term",
        )

    @unittest.skipUnless(_HAS_REPORTLAB, "reportlab not installed")
    def test_pdf_built_and_nonzero(self) -> None:
        _returncode, payload = _run_validator()
        self.assertTrue(payload.get("pdf_built"), "Expected pdf_built=True")
        self.assertGreater(
            payload.get("pdf_bytes", 0),
            0,
            "Expected pdf_bytes > 0",
        )

    def test_reportlab_availability_field_present(self) -> None:
        _returncode, payload = _run_validator()
        self.assertIn("reportlab_available", payload)

    def test_errors_field_is_list(self) -> None:
        _returncode, payload = _run_validator()
        self.assertIsInstance(payload.get("errors"), list)

    def test_warnings_field_is_list(self) -> None:
        _returncode, payload = _run_validator()
        self.assertIsInstance(payload.get("warnings"), list)


class TestValidateUserManualMissingChapter(unittest.TestCase):
    """Test that missing chapter files are detected."""

    def test_detects_missing_chapter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mmo_test_manual_") as tmp:
            tmp_path = Path(tmp)
            # Write a minimal manual.yaml pointing at a nonexistent chapter
            bad_manifest = {
                "title": "Test Manual",
                "version": "0.0.0",
                "chapters": [
                    {"id": "ch00", "file": "nonexistent_chapter.md", "title": "Missing"},
                ],
                "glossary_file": "glossary.yaml",
            }
            manifest_path = tmp_path / "manual.yaml"
            manifest_path.write_text(
                yaml.dump(bad_manifest, allow_unicode=True), encoding="utf-8"
            )
            # Write a minimal glossary so only the chapter fails
            (tmp_path / "glossary.yaml").write_text(
                "terms:\n  - term: Test\n    definition: A test term.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    _python(),
                    str(VALIDATE_SCRIPT),
                    "--repo-root",
                    str(tmp_path),
                    "--manifest",
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON output: {result.stdout!r}")

            self.assertFalse(payload.get("ok"), "Expected ok=False for missing chapter")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nonexistent_chapter.md", payload.get("missing_chapters", []))

    def test_missing_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mmo_test_manual_") as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                [
                    _python(),
                    str(VALIDATE_SCRIPT),
                    "--repo-root",
                    str(tmp_path),
                    "--manifest",
                    str(tmp_path / "does_not_exist.yaml"),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON output: {result.stdout!r}")
            self.assertFalse(payload.get("ok"))
            self.assertNotEqual(result.returncode, 0)


class TestBuildUserManualScript(unittest.TestCase):
    """Smoke-test the builder wrapper script."""

    @unittest.skipUnless(_HAS_REPORTLAB, "reportlab not installed")
    def test_build_produces_nonempty_pdf(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mmo_test_build_") as tmp:
            out_pdf = Path(tmp) / "MMO_User_Manual_test.pdf"
            result = subprocess.run(
                [
                    _python(),
                    str(BUILD_SCRIPT),
                    "--manifest",
                    str(MANUAL_YAML),
                    "--out",
                    str(out_pdf),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(
                result.returncode,
                0,
                f"Build script failed:\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            self.assertTrue(out_pdf.is_file(), "Expected PDF file to be written")
            self.assertGreater(out_pdf.stat().st_size, 0, "Expected non-empty PDF")

    def test_build_script_exits_2_without_reportlab(self) -> None:
        """If reportlab unavailable, build_user_manual exits with code 2."""
        if _HAS_REPORTLAB:
            self.skipTest("reportlab is installed; cannot test missing-dependency path")
        result = subprocess.run(
            [
                _python(),
                str(BUILD_SCRIPT),
                "--manifest",
                str(MANUAL_YAML),
                "--out",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
