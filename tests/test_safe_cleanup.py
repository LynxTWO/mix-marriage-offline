"""Tests for tools/safe_cleanup.py — allowlist-only temp cleanup."""

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "safe_cleanup.py"

# Unique suffix per process to avoid collisions on parallel/OneDrive runs.
_PID = os.getpid()


def _unique_root(label: str) -> Path:
    """Return a unique fake_root under .tmp_claude for this PID + label."""
    return REPO_ROOT / ".tmp_claude" / f"_test_safe_cleanup_{label}_{_PID}"


def _run_cleanup(fake_root: Path, *, dry_run: bool = False) -> dict:
    cmd = [sys.executable, str(TOOL_PATH), "--repo-root", str(fake_root)]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"cleanup failed: {result.stderr}"
    return json.loads(result.stdout)


class TestSafeCleanupRemovesAllowlisted(unittest.TestCase):
    """Create dummy dirs under each allowlisted name, assert they are removed."""

    ALLOWLISTED = (
        ".pytest_cache",
        ".tmp_claude",
        ".tmp_codex",
        ".tmp_pytest",
        "sandbox_tmp",
    )

    def setUp(self):
        self.fake_root = _unique_root("root")
        self.fake_root.mkdir(parents=True, exist_ok=True)
        for name in self.ALLOWLISTED:
            d = self.fake_root / name
            d.mkdir(exist_ok=True)
            (d / "dummy.txt").write_text("temp", encoding="utf-8")
        # Also create a pytest-cache-files-* dir
        pcd = self.fake_root / "pytest-cache-files-abcd1234"
        pcd.mkdir(exist_ok=True)
        (pcd / "dummy.txt").write_text("temp", encoding="utf-8")

    def tearDown(self):
        if self.fake_root.exists():
            shutil.rmtree(self.fake_root, ignore_errors=True)

    def test_allowlisted_dirs_removed(self):
        summary = _run_cleanup(self.fake_root)
        for name in self.ALLOWLISTED:
            self.assertIn(name, summary["removed"])
            self.assertFalse(
                (self.fake_root / name).exists(),
                f"{name} should have been removed",
            )
        self.assertIn("pytest-cache-files-abcd1234", summary["removed"])
        self.assertFalse(
            (self.fake_root / "pytest-cache-files-abcd1234").exists(),
        )
        self.assertEqual(summary["errors"], [])

    def test_dry_run_does_not_delete(self):
        summary = _run_cleanup(self.fake_root, dry_run=True)
        self.assertTrue(summary["dry_run"])
        for name in self.ALLOWLISTED:
            self.assertIn(name, summary["removed"])
            self.assertTrue(
                (self.fake_root / name).exists(),
                f"{name} should still exist after dry run",
            )

    def test_missing_dirs_are_skipped(self):
        empty_root = self.fake_root / "_empty_sub"
        empty_root.mkdir(exist_ok=True)
        summary = _run_cleanup(empty_root)
        self.assertEqual(summary["removed"], [])
        self.assertEqual(sorted(summary["skipped"]), sorted(self.ALLOWLISTED))


class TestSafeCleanupIgnoresNonAllowlisted(unittest.TestCase):
    """Non-allowlisted dirs must NOT be touched."""

    def setUp(self):
        self.fake_root = _unique_root("nonallow")
        self.fake_root.mkdir(parents=True, exist_ok=True)
        # Create non-allowlisted dirs of various kinds
        self.non_allowlisted = [
            "src",
            "my_project",
            "a1b2c3d4",
            ".git",
            "node_modules",
        ]
        for name in self.non_allowlisted:
            d = self.fake_root / name
            d.mkdir(exist_ok=True)
            (d / "important.txt").write_text("keep", encoding="utf-8")

    def tearDown(self):
        if self.fake_root.exists():
            shutil.rmtree(self.fake_root, ignore_errors=True)

    def test_non_allowlisted_dirs_not_removed(self):
        summary = _run_cleanup(self.fake_root)
        for name in self.non_allowlisted:
            self.assertTrue(
                (self.fake_root / name).exists(),
                f"{name} should NOT have been removed",
            )
            self.assertNotIn(name, summary.get("removed", []))
        self.assertEqual(summary["errors"], [])


class TestSafeCleanupJsonDeterminism(unittest.TestCase):
    """Output must be valid JSON with stable key order."""

    def setUp(self):
        self.fake_root = _unique_root("json")
        self.fake_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.fake_root.exists():
            shutil.rmtree(self.fake_root, ignore_errors=True)

    def test_output_keys_are_sorted(self):
        cmd = [
            sys.executable, str(TOOL_PATH),
            "--repo-root", str(self.fake_root),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO_ROOT,
        )
        parsed = json.loads(result.stdout)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))

    def test_two_runs_produce_identical_output(self):
        cmd = [
            sys.executable, str(TOOL_PATH),
            "--repo-root", str(self.fake_root),
        ]
        r1 = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
        r2 = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(r1.stdout, r2.stdout)


class TestSafeCleanupReadOnlyFiles(unittest.TestCase):
    """Read-only files inside allowlisted dirs must not cause errors."""

    ALLOWLISTED = (
        ".pytest_cache",
        ".tmp_claude",
        ".tmp_codex",
        ".tmp_pytest",
        "sandbox_tmp",
    )

    def setUp(self):
        self.fake_root = _unique_root("readonly")
        self.fake_root.mkdir(parents=True, exist_ok=True)
        for name in self.ALLOWLISTED:
            d = self.fake_root / name
            d.mkdir(exist_ok=True)
            f = d / "locked.txt"
            f.write_text("read-only content", encoding="utf-8")
            # Make the file read-only
            f.chmod(stat.S_IREAD)

    def tearDown(self):
        # Restore write permissions so tearDown can clean up
        if self.fake_root.exists():
            for root, dirs, files in os.walk(self.fake_root):
                for fname in files:
                    fp = Path(root) / fname
                    try:
                        fp.chmod(stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            shutil.rmtree(self.fake_root, ignore_errors=True)

    def test_readonly_files_removed_without_errors(self):
        summary = _run_cleanup(self.fake_root)
        for name in self.ALLOWLISTED:
            self.assertIn(name, summary["removed"])
            self.assertFalse(
                (self.fake_root / name).exists(),
                f"{name} should have been removed despite read-only files",
            )
        self.assertEqual(summary["errors"], [])


if __name__ == "__main__":
    unittest.main()
