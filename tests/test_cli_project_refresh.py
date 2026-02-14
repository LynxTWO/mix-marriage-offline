"""CLI integration tests for mmo project refresh."""

import contextlib
import io
import json
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_project_refresh"


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


def _init_project(base: Path) -> tuple[Path, Path]:
    """Run project init and return (out_dir, stems_root)."""
    root = _make_stems_root(base)
    out_dir = base / "out"
    exit_code, _, stderr = _run_main([
        "project", "init",
        "--stems-root", str(root),
        "--out-dir", str(out_dir),
    ])
    assert exit_code == 0, f"project init failed: {stderr}"
    return out_dir, root


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestCliProjectRefresh(unittest.TestCase):
    def test_refresh_rewrites_expected_files(self) -> None:
        base = _SANDBOX / "rewrite"
        out_dir, stems_root = _init_project(base)

        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertTrue((out_dir / "stems" / "stems_index.json").exists())
        self.assertTrue((out_dir / "stems" / "stems_map.json").exists())
        self.assertTrue((out_dir / "drafts" / "scene.draft.json").exists())
        self.assertTrue((out_dir / "drafts" / "routing_plan.draft.json").exists())

        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertGreater(result["file_count"], 0)
        self.assertGreater(result["assignment_count"], 0)

    def test_refresh_deterministic_across_runs(self) -> None:
        base = _SANDBOX / "determinism"
        out_dir, stems_root = _init_project(base)

        _, stdout1, _ = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
        ])
        _, stdout2, _ = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
        ])

        for rel in [
            "stems/stems_index.json",
            "stems/stems_map.json",
            "drafts/scene.draft.json",
            "drafts/routing_plan.draft.json",
        ]:
            content1 = (out_dir / rel).read_text(encoding="utf-8")
            content2 = (out_dir / rel).read_text(encoding="utf-8")
            self.assertEqual(content1, content2, msg=f"{rel} differs between runs")

    def test_refresh_does_not_overwrite_overrides_without_force(self) -> None:
        base = _SANDBOX / "no_force"
        out_dir, stems_root = _init_project(base)

        overrides_path = out_dir / "stems" / "stems_overrides.yaml"
        original = overrides_path.read_text(encoding="utf-8")
        overrides_path.write_text(original + "# user edit\n", encoding="utf-8")

        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)

        current = overrides_path.read_text(encoding="utf-8")
        self.assertIn("# user edit", current)

        result = json.loads(stdout)
        self.assertFalse(result["overrides_written"])
        self.assertTrue(result["overrides_skipped"])

    def test_refresh_overwrites_overrides_with_force(self) -> None:
        base = _SANDBOX / "with_force"
        out_dir, stems_root = _init_project(base)

        overrides_path = out_dir / "stems" / "stems_overrides.yaml"
        overrides_path.write_text("# user edit\n", encoding="utf-8")

        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
            "--force",
        ])

        self.assertEqual(exit_code, 0, msg=stderr)

        current = overrides_path.read_text(encoding="utf-8")
        self.assertNotIn("# user edit", current)

        result = json.loads(stdout)
        self.assertTrue(result["overrides_written"])

    def test_refresh_requires_stems_root_if_no_default(self) -> None:
        base = _SANDBOX / "no_stems_root"
        out_dir, _ = _init_project(base)

        exit_code, _, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
        ])

        self.assertNotEqual(exit_code, 0)
        self.assertIn("--stems-root", stderr)

    def test_refresh_uses_stems_source_default(self) -> None:
        base = _SANDBOX / "stems_source_default"
        out_dir, _ = _init_project(base)

        stems_source = out_dir / "stems_source"
        _write_tiny_wav(stems_source / "stems" / "kick.wav")
        _write_tiny_wav(stems_source / "stems" / "snare.wav")

        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])

    def test_refresh_json_paths_use_forward_slashes(self) -> None:
        base = _SANDBOX / "slashes"
        out_dir, stems_root = _init_project(base)

        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems_root),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)

        for p in result["paths_written"]:
            self.assertNotIn("\\", p, msg=f"Backslash in path: {p}")

        self.assertNotIn("\\", result["project_dir"])
        self.assertNotIn("\\", result["stems_root"])

    def test_refresh_fails_if_project_dir_missing(self) -> None:
        nonexistent = _SANDBOX / "does_not_exist"

        exit_code, _, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(nonexistent),
        ])

        self.assertNotEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
