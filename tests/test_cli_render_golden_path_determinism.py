"""Golden-path determinism tripwire for the render arc.

Exercises the full sequence:
  project init (with --bundle) -> edit overrides -> project refresh
  -> write render_request -> scan (report.json) -> render-run
  -> bundle (ui_bundle.json) -> project validate -> project pack

Runs the pipeline twice and asserts byte-identical artifacts and identical
stdout across reruns.
"""

import contextlib
import hashlib
import io
import json
import os
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_render_golden_path_determinism" / str(os.getpid())
)


# -- helpers -----------------------------------------------------------------

def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    """Write a deterministic 16-bit WAV with 8 frames of silence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _make_stems_root(base: Path) -> Path:
    """Create a stems_root with 4 deterministic WAVs across 3 bus groups."""
    root = base / "stems_root"
    _write_tiny_wav(root / "stems" / "kick.wav")
    _write_tiny_wav(root / "stems" / "snare.wav")
    _write_tiny_wav(root / "stems" / "bass_di.wav")
    _write_tiny_wav(root / "stems" / "vox_lead.wav")
    return root


def _snapshot_bytes(paths: list[Path]) -> dict[str, str]:
    """Return {posix_relative: sha256} for every existing path."""
    result: dict[str, str] = {}
    for p in sorted(paths, key=lambda x: x.as_posix()):
        if p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            result[p.as_posix()] = digest
    return result


def _write_json(path: Path, payload: dict) -> None:
    """Write deterministic JSON (indent=2, sort_keys=True)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- test class --------------------------------------------------------------

class TestRenderGoldenPathDeterminism(unittest.TestCase):
    """End-to-end determinism tripwire for the render arc."""

    @classmethod
    def setUpClass(cls) -> None:
        base = _SANDBOX / "golden"
        cls.stems_root = _make_stems_root(base)
        cls.project_dir = base / "project"
        cls.bundle_path = base / "bundle.json"

        # --- Step 1: project init (with --bundle) ---
        exit_code, stdout, stderr = _run_main([
            "project", "init",
            "--stems-root", str(cls.stems_root),
            "--out-dir", str(cls.project_dir),
            "--bundle", str(cls.bundle_path),
        ])
        assert exit_code == 0, f"project init failed: {stderr}"

        # --- Step 2: write an explicit overrides file ---
        cls.overrides_path = cls.project_dir / "stems" / "stems_overrides.yaml"
        cls.overrides_text = (
            "# Explicit override for render golden-path test\n"
            "version: \"0.1.0\"\n"
            "overrides:\n"
            "  - override_id: OVR.RENDER_GOLDEN_BASS\n"
            "    match:\n"
            "      rel_path: stems/bass_di.wav\n"
            "    role_id: ROLE.BASS.DI\n"
        )
        cls.overrides_path.write_text(cls.overrides_text, encoding="utf-8")

    # -- full render arc determinism -----------------------------------------

    def test_artifact_bytes_identical_across_full_rerun(self) -> None:
        """All key artifacts are byte-identical after two full render-arc reruns."""

        def _full_run() -> tuple[str, dict[str, str]]:
            # 1. project refresh
            exit_refresh, _, stderr_refresh = _run_main([
                "project", "refresh",
                "--project-dir", str(self.project_dir),
                "--stems-root", str(self.stems_root),
            ])
            self.assertEqual(exit_refresh, 0, msg=f"refresh failed: {stderr_refresh}")

            # 2. Write render_request.json
            scene_path = self.project_dir / "drafts" / "scene.draft.json"
            scene_posix = scene_path.resolve().as_posix()
            render_request_path = self.project_dir / "renders" / "render_request.json"
            _write_json(render_request_path, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
            })

            # 3. mmo scan -> report.json
            report_path = self.project_dir / "report.json"
            exit_scan, _, stderr_scan = _run_main([
                "scan",
                str(self.stems_root),
                "--out", str(report_path),
            ])
            self.assertEqual(exit_scan, 0, msg=f"mmo scan failed: {stderr_scan}")

            # 4. mmo render-run --force
            render_plan_path = self.project_dir / "renders" / "render_plan.json"
            render_report_path = self.project_dir / "renders" / "render_report.json"
            exit_render, render_stdout, stderr_render = _run_main([
                "render-run",
                "--request", str(render_request_path),
                "--scene", str(scene_path),
                "--plan-out", str(render_plan_path),
                "--report-out", str(render_report_path),
                "--force",
            ])
            self.assertEqual(exit_render, 0, msg=f"render-run failed: {stderr_render}")

            # 5. mmo bundle
            stems_index_path = self.project_dir / "stems" / "stems_index.json"
            stems_map_path = self.project_dir / "stems" / "stems_map.json"
            ui_bundle_path = self.project_dir / "ui_bundle.json"
            exit_bundle, _, stderr_bundle = _run_main([
                "bundle",
                "--report", str(report_path),
                "--render-request", str(render_request_path),
                "--render-plan", str(render_plan_path),
                "--render-report", str(render_report_path),
                "--stems-index", str(stems_index_path),
                "--stems-map", str(stems_map_path),
                "--scene", str(scene_path),
                "--out", str(ui_bundle_path),
            ])
            self.assertEqual(exit_bundle, 0, msg=f"mmo bundle failed: {stderr_bundle}")

            # 6. mmo project validate --out
            validation_path = self.project_dir / "validation.json"
            exit_validate, stdout_validate, stderr_validate = _run_main([
                "project", "validate", str(self.project_dir),
                "--out", str(validation_path),
            ])
            self.assertEqual(exit_validate, 0, msg=f"project validate failed: {stdout_validate}")

            # 7. mmo project pack --force
            pack_path = self.project_dir / "project.zip"
            exit_pack, _, stderr_pack = _run_main([
                "project", "pack", str(self.project_dir),
                "--out", str(pack_path),
                "--force",
            ])
            self.assertEqual(exit_pack, 0, msg=f"project pack failed: {stderr_pack}")

            # 8. Collect SHA-256 snapshot of all artifacts
            artifacts = [
                stems_index_path,
                stems_map_path,
                self.project_dir / "drafts" / "scene.draft.json",
                self.project_dir / "drafts" / "routing_plan.draft.json",
                report_path,
                render_request_path,
                render_plan_path,
                render_report_path,
                ui_bundle_path,
                validation_path,
                pack_path,
                self.bundle_path,
            ]
            return render_stdout, _snapshot_bytes(artifacts)

        stdout_1, snap_1 = _full_run()
        stdout_2, snap_2 = _full_run()

        # render-run stdout identical (includes plan_id with hash)
        self.assertEqual(stdout_1, stdout_2, msg="render-run stdout differs between runs")

        # All artifact SHA-256 hashes identical
        self.assertGreater(len(snap_1), 0, "No artifacts found")
        self.assertEqual(snap_1, snap_2, msg="Artifact snapshot differs between runs")


if __name__ == "__main__":
    unittest.main()
