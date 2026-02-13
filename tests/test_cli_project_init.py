"""CLI integration tests for mmo project init."""

import contextlib
import io
import json
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_project_init"


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _make_stems_root(base: Path) -> Path:
    root = base / "stems_root"
    _write_tiny_wav(root / "stems" / "kick.wav")
    _write_tiny_wav(root / "stems" / "snare.wav")
    return root


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestCliProjectInit(unittest.TestCase):
    def test_init_creates_expected_tree(self) -> None:
        base = _SANDBOX / "tree"
        root = _make_stems_root(base)
        out_dir = base / "out"

        exit_code, stdout, stderr = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)

        # stems/ subfolder
        self.assertTrue((out_dir / "stems" / "stems_index.json").exists())
        self.assertTrue((out_dir / "stems" / "stems_map.json").exists())
        self.assertTrue((out_dir / "stems" / "stems_overrides.yaml").exists())

        # drafts/ subfolder
        self.assertTrue((out_dir / "drafts" / "scene.draft.json").exists())
        self.assertTrue((out_dir / "drafts" / "routing_plan.draft.json").exists())
        self.assertTrue((out_dir / "drafts" / "README.txt").exists())

        # root README
        self.assertTrue((out_dir / "README.txt").exists())

        # JSON output
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertTrue(result["preview_only"])
        self.assertGreater(result["file_count"], 0)
        self.assertGreater(result["assignment_count"], 0)

    def test_init_deterministic_across_runs(self) -> None:
        base = _SANDBOX / "determinism"
        root = _make_stems_root(base)
        out1 = base / "out1"
        out2 = base / "out2"

        exit1, _, stderr1 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out1),
        ])
        exit2, _, stderr2 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out2),
        ])

        self.assertEqual(exit1, 0, msg=stderr1)
        self.assertEqual(exit2, 0, msg=stderr2)

        for rel in [
            "stems/stems_index.json",
            "stems/stems_map.json",
            "drafts/scene.draft.json",
            "drafts/routing_plan.draft.json",
        ]:
            content1 = (out1 / rel).read_text(encoding="utf-8")
            content2 = (out2 / rel).read_text(encoding="utf-8")
            self.assertEqual(content1, content2, msg=f"{rel} differs between runs")

    def test_init_does_not_overwrite_overrides_without_force(self) -> None:
        base = _SANDBOX / "no_force"
        root = _make_stems_root(base)
        out_dir = base / "out"

        # First run — should succeed.
        exit1, _, stderr1 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])
        self.assertEqual(exit1, 0, msg=stderr1)

        # Modify overrides to detect if it gets overwritten.
        overrides_path = out_dir / "stems" / "stems_overrides.yaml"
        original = overrides_path.read_text(encoding="utf-8")
        overrides_path.write_text(original + "# user edit\n", encoding="utf-8")

        # Second run without --force — should fail.
        exit2, _, stderr2 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])
        self.assertNotEqual(exit2, 0)
        self.assertIn("--force", stderr2)

        # Overrides should be unchanged.
        current = overrides_path.read_text(encoding="utf-8")
        self.assertIn("# user edit", current)

    def test_init_force_overwrites_overrides(self) -> None:
        base = _SANDBOX / "with_force"
        root = _make_stems_root(base)
        out_dir = base / "out"

        _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])

        # Modify overrides.
        overrides_path = out_dir / "stems" / "stems_overrides.yaml"
        overrides_path.write_text("# user edit\n", encoding="utf-8")

        # Second run with --force — should succeed and overwrite.
        exit_code, _, stderr = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
            "--force",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

        current = overrides_path.read_text(encoding="utf-8")
        self.assertNotIn("# user edit", current)

    def test_init_drafts_have_draft_names(self) -> None:
        base = _SANDBOX / "draft_names"
        root = _make_stems_root(base)
        out_dir = base / "out"

        exit_code, _, stderr = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

        scene_path = out_dir / "drafts" / "scene.draft.json"
        routing_path = out_dir / "drafts" / "routing_plan.draft.json"
        self.assertTrue(scene_path.exists())
        self.assertTrue(routing_path.exists())

        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        self.assertEqual(scene["source"]["created_from"], "draft")
        self.assertTrue(scene["scene_id"].startswith("SCENE.DRAFT."))

    def test_init_bundle_pointer_stable(self) -> None:
        base = _SANDBOX / "bundle"
        root = _make_stems_root(base)
        out1 = base / "out1"
        out2 = base / "out2"
        bundle1 = base / "bundle1.json"
        bundle2 = base / "bundle2.json"

        exit1, _, stderr1 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out1),
            "--bundle", str(bundle1),
        ])
        exit2, _, stderr2 = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out2),
            "--bundle", str(bundle2),
        ])

        self.assertEqual(exit1, 0, msg=stderr1)
        self.assertEqual(exit2, 0, msg=stderr2)
        self.assertTrue(bundle1.exists())
        self.assertTrue(bundle2.exists())

        b1 = json.loads(bundle1.read_text(encoding="utf-8"))
        b2 = json.loads(bundle2.read_text(encoding="utf-8"))

        # Paths differ by out dir, but structure and counts must match.
        self.assertEqual(
            b1["stems_summary"],
            b2["stems_summary"],
        )
        self.assertIn("stems_index_path", b1)
        self.assertIn("scene_draft_path", b1)

    def test_init_json_paths_use_forward_slashes(self) -> None:
        base = _SANDBOX / "slashes"
        root = _make_stems_root(base)
        out_dir = base / "out"

        exit_code, stdout, stderr = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)

        # All paths in paths_written must use forward slashes.
        for p in result["paths_written"]:
            self.assertNotIn("\\", p, msg=f"Backslash in path: {p}")

        # stems_root and out_dir too.
        self.assertNotIn("\\", result["stems_root"])
        self.assertNotIn("\\", result["out_dir"])

    def test_init_text_format(self) -> None:
        base = _SANDBOX / "text_fmt"
        root = _make_stems_root(base)
        out_dir = base / "out"

        exit_code, stdout, stderr = _run_main([
            "project", "init",
            "--stems-root", str(root),
            "--out-dir", str(out_dir),
            "--format", "text",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        lower = stdout.lower()
        self.assertIn("preview-only", lower)
        self.assertIn("scaffold", lower)


if __name__ == "__main__":
    unittest.main()
