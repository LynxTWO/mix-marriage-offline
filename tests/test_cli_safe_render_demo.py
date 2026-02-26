"""Tests for ``mmo safe-render --demo`` CLI flow.

Covers:
- --demo flag loads the fixtures/immersive/report.7_1_4.json fixture.
- --demo renders all 5 channel-ordering standards in parallel (dry-run).
- Per-standard receipt files are written under --out-dir.
- _run_safe_render_demo() unit: all standards attempted, exit 0 on all-pass.
- _DEMO_LAYOUT_STANDARDS contains exactly the 5 expected standards.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main
from mmo.cli_commands._renderers import (
    _DEMO_LAYOUT_STANDARDS,
    _run_safe_render_demo,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_FIXTURE_PATH = _REPO_ROOT / "fixtures" / "immersive" / "report.7_1_4.json"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_safe_render_demo" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestDemoLayoutStandards(unittest.TestCase):
    """Verify the demo constants are correct."""

    def test_five_standards_defined(self) -> None:
        self.assertEqual(len(_DEMO_LAYOUT_STANDARDS), 5)

    def test_all_expected_standards_present(self) -> None:
        expected = {"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"}
        self.assertEqual(set(_DEMO_LAYOUT_STANDARDS), expected)

    def test_standards_are_strings(self) -> None:
        for std in _DEMO_LAYOUT_STANDARDS:
            self.assertIsInstance(std, str)


class TestDemoFixture(unittest.TestCase):
    """Verify the 7.1.4 fixture is present and valid JSON."""

    def test_fixture_exists(self) -> None:
        self.assertTrue(_FIXTURE_PATH.exists(), f"Fixture missing: {_FIXTURE_PATH}")

    def test_fixture_is_valid_json(self) -> None:
        data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

    def test_fixture_has_required_fields(self) -> None:
        data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        for field in ("schema_version", "report_id", "session"):
            self.assertIn(field, data, f"Missing field: {field}")

    def test_fixture_source_layout_is_7_1_4(self) -> None:
        data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        layout = data.get("session", {}).get("source_layout_id", "")
        self.assertEqual(layout, "LAYOUT.7_1_4")


class TestRunSafeRenderDemo(unittest.TestCase):
    """Unit tests for _run_safe_render_demo()."""

    def test_demo_returns_0_all_standards(self) -> None:
        """All 5 standards complete in dry-run and return exit code 0."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "demo_out"
            rc = _run_safe_render_demo(
                fixture_path=_FIXTURE_PATH,
                plugins_dir=_PLUGINS_DIR,
                out_dir=out_dir,
                profile_id="PROFILE.ASSIST",
                run_config=None,
                force=True,
            )
        self.assertEqual(rc, 0, "Expected exit code 0 for all-pass demo")

    def test_demo_missing_fixture_returns_1(self) -> None:
        """Missing fixture path returns exit code 1 immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            rc = _run_safe_render_demo(
                fixture_path=Path(tmp) / "nonexistent.json",
                plugins_dir=_PLUGINS_DIR,
                out_dir=None,
                profile_id="PROFILE.ASSIST",
            )
        self.assertEqual(rc, 1, "Expected exit code 1 for missing fixture")

    def test_demo_writes_receipts_per_standard(self) -> None:
        """Each standard produces a receipt.json under its sub-directory."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "demo_out"
            rc = _run_safe_render_demo(
                fixture_path=_FIXTURE_PATH,
                plugins_dir=_PLUGINS_DIR,
                out_dir=out_dir,
                profile_id="PROFILE.ASSIST",
                force=True,
            )
            self.assertEqual(rc, 0)
            for std in _DEMO_LAYOUT_STANDARDS:
                receipt = out_dir / std / "receipt.json"
                self.assertTrue(receipt.exists(), f"Missing receipt for {std}: {receipt}")


class TestCliSafeRenderDemo(unittest.TestCase):
    """Integration tests for ``mmo safe-render --demo`` via CLI."""

    def test_demo_flag_no_report_required(self) -> None:
        """--demo runs without --report (uses built-in fixture)."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            exit_code, _out, stderr = _run_main([
                "safe-render",
                "--demo",
                "--plugins", str(_PLUGINS_DIR),
                "--out-dir", str(out_dir),
                "--profile", "PROFILE.ASSIST",
            ])
        self.assertEqual(exit_code, 0, f"safe-render --demo failed:\n{stderr}")

    def test_demo_flag_stderr_mentions_standards(self) -> None:
        """--demo stderr output mentions the 5 standards."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            _exit_code, _out, stderr = _run_main([
                "safe-render",
                "--demo",
                "--plugins", str(_PLUGINS_DIR),
                "--out-dir", str(out_dir),
                "--profile", "PROFILE.ASSIST",
            ])
        self.assertIn("SMPTE", stderr)
        self.assertIn("FILM", stderr)

    def test_report_required_without_demo(self) -> None:
        """Missing --report without --demo returns exit code 1."""
        exit_code, _out, stderr = _run_main([
            "safe-render",
            "--plugins", str(_PLUGINS_DIR),
            "--dry-run",
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("--report", stderr)
