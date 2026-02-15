"""Tests for ``mmo project pack``."""

import contextlib
import io
import json
import os
import unittest
import wave
import zipfile
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_pack" / str(os.getpid())
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


def _init_project_with_auditions(base: Path) -> Path:
    """Create a valid project scaffold with auditions and return project_dir."""
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
    # Run auditions so we have WAVs.
    map_path = project_dir / "stems" / "stems_map.json"
    exit_code, _, stderr = _run_main([
        "stems", "audition",
        "--stems-map", str(map_path),
        "--stems-dir", str(stems_root),
        "--out-dir", str(project_dir),
        "--segment", "1.0",
    ])
    assert exit_code == 0, f"stems audition failed: {stderr}"
    return project_dir


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- tests -------------------------------------------------------------------

class TestProjectPackHappyPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "happy")

    def test_exit_code_zero(self) -> None:
        out = _SANDBOX / "happy" / "pack.zip"
        exit_code, stdout, stderr = _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

    def test_zip_created(self) -> None:
        out = _SANDBOX / "happy" / "pack_created.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        self.assertTrue(out.is_file())

    def test_stdout_is_valid_json(self) -> None:
        out = _SANDBOX / "happy" / "pack_json.zip"
        _, stdout, _ = _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertGreater(result["file_count"], 0)

    def test_zip_contains_manifest(self) -> None:
        out = _SANDBOX / "happy" / "pack_manifest.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            self.assertIn("manifest.json", zf.namelist())

    def test_manifest_has_correct_structure(self) -> None:
        out = _SANDBOX / "happy" / "pack_struct.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        self.assertIn("files", manifest)
        self.assertIn("file_count", manifest)
        self.assertEqual(manifest["file_count"], len(manifest["files"]))
        for entry in manifest["files"]:
            self.assertIn("path", entry)
            self.assertIn("sha256", entry)
            self.assertIn("size", entry)


class TestProjectPackNoWavsByDefault(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "no_wavs")

    def test_no_wav_files_in_zip(self) -> None:
        out = _SANDBOX / "no_wavs" / "pack.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            wav_files = [n for n in zf.namelist() if n.endswith(".wav")]
        self.assertEqual(wav_files, [])


class TestProjectPackIncludeWavs(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "with_wavs")

    def test_wav_files_included_with_flag(self) -> None:
        out = _SANDBOX / "with_wavs" / "pack.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
            "--include-wavs",
        ])
        with zipfile.ZipFile(out, "r") as zf:
            wav_files = [n for n in zf.namelist() if n.endswith(".wav")]
        self.assertGreater(len(wav_files), 0)


class TestProjectPackForce(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "force")

    def test_refuses_overwrite_without_force(self) -> None:
        out = _SANDBOX / "force" / "pack.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        self.assertTrue(out.is_file())
        exit_code, _, stderr = _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("--force", stderr)

    def test_overwrites_with_force(self) -> None:
        out = _SANDBOX / "force" / "pack_force.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        exit_code, _, _ = _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
            "--force",
        ])
        self.assertEqual(exit_code, 0)


class TestProjectPackDeterminism(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "determ")

    def test_zip_bytes_identical_across_runs(self) -> None:
        out_a = _SANDBOX / "determ" / "pack_a.zip"
        out_b = _SANDBOX / "determ" / "pack_b.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_a),
        ])
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_b),
        ])
        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())


class TestProjectPackPaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "paths")

    def test_manifest_paths_use_forward_slashes(self) -> None:
        out = _SANDBOX / "paths" / "pack.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        for entry in manifest["files"]:
            self.assertNotIn("\\", entry["path"])

    def test_zip_entry_names_use_forward_slashes(self) -> None:
        out = _SANDBOX / "paths" / "pack_entries.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            for name in zf.namelist():
                self.assertNotIn("\\", name)

    def test_manifest_files_sorted(self) -> None:
        out = _SANDBOX / "paths" / "pack_sorted.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        paths = [e["path"] for e in manifest["files"]]
        self.assertEqual(paths, sorted(paths))


class TestProjectPackRenderArtifacts(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project_with_auditions(_SANDBOX / "render_pack")
        renders_dir = cls.project_dir / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        _write_json(renders_dir / "render_request.json", {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": "scenes/test/scene.json",
        })
        _write_json(renders_dir / "render_plan.json", {
            "schema_version": "0.1.0",
            "plan_id": "PLAN.test.abcdef01",
            "scene_path": "scenes/test/scene.json",
            "targets": ["TARGET.STEREO.2_0"],
            "policies": {},
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "target_id": "TARGET.STEREO.2_0",
                    "target_layout_id": "LAYOUT.2_0",
                    "output_formats": ["wav"],
                    "contexts": ["render"],
                    "notes": ["Test job."],
                },
            ],
        })
        _write_json(renders_dir / "render_report.json", {
            "schema_version": "0.1.0",
            "request": {
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes/test/scene.json",
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "status": "skipped",
                    "output_files": [],
                    "notes": ["reason: dry_run"],
                },
            ],
            "policies_applied": {
                "downmix_policy_id": None,
                "gates_policy_id": None,
                "matrix_id": None,
            },
            "qa_gates": {"status": "not_run", "gates": []},
        })

    def test_render_artifacts_in_zip(self) -> None:
        out = _SANDBOX / "render_pack" / "pack.zip"
        exit_code, _, stderr = _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        self.assertIn("renders/render_request.json", names)
        self.assertIn("renders/render_plan.json", names)
        self.assertIn("renders/render_report.json", names)

    def test_render_artifacts_in_manifest(self) -> None:
        out = _SANDBOX / "render_pack" / "pack_manifest.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out),
        ])
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        manifest_paths = [e["path"] for e in manifest["files"]]
        self.assertIn("renders/render_request.json", manifest_paths)
        self.assertIn("renders/render_plan.json", manifest_paths)
        self.assertIn("renders/render_report.json", manifest_paths)
        # Manifest still sorted.
        self.assertEqual(manifest_paths, sorted(manifest_paths))

    def test_determinism_with_render_artifacts(self) -> None:
        out_a = _SANDBOX / "render_pack" / "det_a.zip"
        out_b = _SANDBOX / "render_pack" / "det_b.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_a),
        ])
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_b),
        ])
        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_manifest_determinism_with_render_artifacts(self) -> None:
        out_a = _SANDBOX / "render_pack" / "man_a.zip"
        out_b = _SANDBOX / "render_pack" / "man_b.zip"
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_a),
        ])
        _run_main([
            "project", "pack", str(self.project_dir),
            "--out", str(out_b),
        ])
        with zipfile.ZipFile(out_a, "r") as zf:
            manifest_a = zf.read("manifest.json")
        with zipfile.ZipFile(out_b, "r") as zf:
            manifest_b = zf.read("manifest.json")
        self.assertEqual(manifest_a, manifest_b)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
