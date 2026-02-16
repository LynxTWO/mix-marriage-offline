"""Tests for tools/sync_claude_agents.py."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import sync_claude_agents


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestSyncAllowlist(unittest.TestCase):
    """Only allowlisted files are synced."""

    def test_allowlist_is_sorted(self) -> None:
        self.assertEqual(
            list(sync_claude_agents.AGENT_FILES),
            sorted(sync_claude_agents.AGENT_FILES),
        )

    def test_allowlist_matches_source_dir(self) -> None:
        src = REPO_ROOT / "docs" / "claude_agents"
        actual = sorted(f.name for f in src.iterdir() if f.is_file())
        self.assertEqual(actual, list(sync_claude_agents.AGENT_FILES))

    def test_non_allowlisted_file_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            dst.mkdir()

            # Create one allowlisted file and one extra.
            (src / "mmo-core-coder.md").write_text("test", encoding="utf-8")
            (src / "rogue-agent.md").write_text("rogue", encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                result = sync_claude_agents.sync()

            self.assertIn("mmo-core-coder.md", result["copied"])
            self.assertFalse((dst / "rogue-agent.md").exists())


class TestSyncContentCompare(unittest.TestCase):
    """Files with identical content are skipped."""

    def test_identical_file_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            dst.mkdir()

            content = "---\ndescription: test\n---\nTest agent.\n"
            (src / "mmo-core-coder.md").write_text(content, encoding="utf-8")
            (dst / "mmo-core-coder.md").write_text(content, encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                result = sync_claude_agents.sync()

            self.assertEqual(result["copied"], [])
            self.assertIn("mmo-core-coder.md", result["skipped"])

    def test_changed_file_copied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            dst.mkdir()

            (src / "mmo-core-coder.md").write_text("v2", encoding="utf-8")
            (dst / "mmo-core-coder.md").write_text("v1", encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                result = sync_claude_agents.sync()

            self.assertIn("mmo-core-coder.md", result["copied"])
            self.assertEqual(
                (dst / "mmo-core-coder.md").read_text(encoding="utf-8"), "v2",
            )


class TestSyncDryRun(unittest.TestCase):
    """Dry-run mode must not write anything."""

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            # Do NOT create dst — sync should not create it in dry-run.

            (src / "mmo-core-coder.md").write_text("test", encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                result = sync_claude_agents.sync(dry_run=True)

            self.assertIn("mmo-core-coder.md", result["copied"])
            self.assertFalse(dst.exists())


class TestSyncDeterminism(unittest.TestCase):
    """Output lists must be sorted for determinism."""

    def test_result_lists_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            dst.mkdir()

            for name in sync_claude_agents.AGENT_FILES:
                (src / name).write_text(f"content-{name}", encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                result = sync_claude_agents.sync()

            self.assertEqual(result["copied"], sorted(result["copied"]))
            self.assertEqual(result["skipped"], sorted(result["skipped"]))


class TestSyncIdempotent(unittest.TestCase):
    """Running sync twice with no source changes copies nothing on second run."""

    def test_second_run_copies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            src.mkdir()
            dst.mkdir()

            for name in sync_claude_agents.AGENT_FILES:
                (src / name).write_text(f"content-{name}", encoding="utf-8")

            with mock.patch.object(sync_claude_agents, "SRC_DIR", src), \
                 mock.patch.object(sync_claude_agents, "DST_DIR", dst):
                run1 = sync_claude_agents.sync()
                run2 = sync_claude_agents.sync()

            self.assertGreater(len(run1["copied"]), 0)
            self.assertEqual(run2["copied"], [])
            self.assertEqual(
                sorted(run2["skipped"]),
                sorted(run1["copied"]),
            )


class TestSyncRealRepo(unittest.TestCase):
    """Integration: sync against the real repo dirs (non-destructive)."""

    def test_real_sync_is_already_up_to_date(self) -> None:
        """After the initial sync, a second run should find everything current."""
        # Run sync to bring local up to date.
        sync_claude_agents.sync()
        # Second run: everything should be skipped.
        result = sync_claude_agents.sync()
        self.assertEqual(result["copied"], [])
        self.assertEqual(len(result["skipped"]), len(sync_claude_agents.AGENT_FILES))


if __name__ == "__main__":
    unittest.main()
