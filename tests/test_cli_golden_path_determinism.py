"""Golden-path determinism tripwire for the stems arc.

Exercises the full sequence:
  project init (with --bundle) -> edit overrides -> project refresh (x2)
  -> stems audition (x2) -> index_stems_auditions -> listen_pack snapshot
  -> scan (report.json) -> bundle (ui_bundle.json)

Asserts byte-identical artifacts and identical stdout across reruns.
"""

import contextlib
import hashlib
import io
import json
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.listen_pack import index_stems_auditions

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_golden_path_determinism"

# Short segment keeps audition WAVs small and fast.
_AUDITION_SEGMENT = "1.0"


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


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- test class --------------------------------------------------------------

class TestGoldenPathDeterminism(unittest.TestCase):
    """End-to-end determinism tripwire for the stems arc."""

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
        cls.init_stdout = stdout

        # --- Step 2: write an explicit overrides file ---
        cls.overrides_path = cls.project_dir / "stems" / "stems_overrides.yaml"
        cls.overrides_text = (
            "# Explicit override for golden-path test\n"
            "overrides:\n"
            "  - override_id: OVR.GOLDEN_BASS\n"
            "    match:\n"
            "      rel_path: stems/bass_di.wav\n"
            "    role_id: ROLE.BASS.DI\n"
        )
        cls.overrides_path.write_text(cls.overrides_text, encoding="utf-8")

    # -- refresh determinism -------------------------------------------------

    def test_refresh_stdout_identical_across_runs(self) -> None:
        """Two consecutive project refresh calls produce identical stdout."""
        _, stdout_a, stderr_a = _run_main([
            "project", "refresh",
            "--project-dir", str(self.project_dir),
            "--stems-root", str(self.stems_root),
        ])
        self.assertEqual(
            _run_main([
                "project", "refresh",
                "--project-dir", str(self.project_dir),
                "--stems-root", str(self.stems_root),
            ])[1],
            stdout_a,
            msg="Refresh stdout differs between runs",
        )

    def test_refresh_preserves_overrides(self) -> None:
        """Refresh without --force keeps the user-edited overrides intact."""
        _run_main([
            "project", "refresh",
            "--project-dir", str(self.project_dir),
            "--stems-root", str(self.stems_root),
        ])
        current = self.overrides_path.read_text(encoding="utf-8")
        self.assertEqual(current, self.overrides_text)

    # -- audition determinism ------------------------------------------------

    def test_audition_stdout_identical_across_runs(self) -> None:
        """Two consecutive stems audition calls produce identical stdout."""
        # Ensure we have a fresh map from refresh.
        _run_main([
            "project", "refresh",
            "--project-dir", str(self.project_dir),
            "--stems-root", str(self.stems_root),
        ])
        map_path = self.project_dir / "stems" / "stems_map.json"

        exit_a, stdout_a, stderr_a = _run_main([
            "stems", "audition",
            "--stems-map", str(map_path),
            "--stems-dir", str(self.stems_root),
            "--out-dir", str(self.project_dir),
            "--segment", _AUDITION_SEGMENT,
            "--overwrite",
        ])
        self.assertEqual(exit_a, 0, msg=stderr_a)

        exit_b, stdout_b, stderr_b = _run_main([
            "stems", "audition",
            "--stems-map", str(map_path),
            "--stems-dir", str(self.stems_root),
            "--out-dir", str(self.project_dir),
            "--segment", _AUDITION_SEGMENT,
            "--overwrite",
        ])
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b, msg="Audition stdout differs between runs")

    # -- listen pack via index_stems_auditions -------------------------------

    def test_listen_pack_stems_auditions_deterministic(self) -> None:
        """index_stems_auditions returns identical dicts across calls."""
        manifest_path = self.project_dir / "stems_auditions" / "manifest.json"
        if not manifest_path.exists():
            # Produce auditions if a prior test didn't run yet.
            _run_main([
                "project", "refresh",
                "--project-dir", str(self.project_dir),
                "--stems-root", str(self.stems_root),
            ])
            map_path = self.project_dir / "stems" / "stems_map.json"
            _run_main([
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(self.stems_root),
                "--out-dir", str(self.project_dir),
                "--segment", _AUDITION_SEGMENT,
            ])

        self.assertTrue(manifest_path.exists(), "manifest.json missing")

        block_a = index_stems_auditions(manifest_path)
        block_b = index_stems_auditions(manifest_path)
        self.assertEqual(block_a, block_b)
        self.assertTrue(block_a["present"])

        # Build a minimal listen_pack envelope and snapshot it.
        listen_pack = {
            "schema_version": "0.1.0",
            "stems_auditions": block_a,
        }
        lp_text = json.dumps(listen_pack, indent=2, sort_keys=True) + "\n"
        lp_path = self.project_dir / "listen_pack.json"
        lp_path.write_bytes(lp_text.encode("utf-8"))

        # Re-build and compare bytes.
        listen_pack_2 = {
            "schema_version": "0.1.0",
            "stems_auditions": block_b,
        }
        lp_text_2 = json.dumps(listen_pack_2, indent=2, sort_keys=True) + "\n"
        self.assertEqual(lp_path.read_bytes(), lp_text_2.encode("utf-8"))

    # -- full artifact snapshot ----------------------------------------------

    def test_artifact_bytes_identical_across_full_rerun(self) -> None:
        """All key artifacts are byte-identical after two full reruns."""
        map_path = self.project_dir / "stems" / "stems_map.json"

        def _full_run() -> dict[str, str]:
            _run_main([
                "project", "refresh",
                "--project-dir", str(self.project_dir),
                "--stems-root", str(self.stems_root),
            ])
            exit_a, _, stderr_a = _run_main([
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(self.stems_root),
                "--out-dir", str(self.project_dir),
                "--segment", _AUDITION_SEGMENT,
                "--overwrite",
            ])
            self.assertEqual(exit_a, 0, msg=stderr_a)

            # Build listen_pack.
            manifest_path = self.project_dir / "stems_auditions" / "manifest.json"
            lp = {
                "schema_version": "0.1.0",
                "stems_auditions": index_stems_auditions(manifest_path),
            }
            lp_path = self.project_dir / "listen_pack.json"
            lp_path.write_bytes(
                (json.dumps(lp, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )

            # Generate report.json via `mmo scan` (no meters/peak).
            report_path = self.project_dir / "report.json"
            exit_scan, _, stderr_scan = _run_main([
                "scan",
                str(self.stems_root),
                "--out", str(report_path),
            ])
            self.assertEqual(exit_scan, 0, msg=f"mmo scan failed: {stderr_scan}")

            # Generate ui_bundle.json via `mmo bundle`.
            stems_index_path = self.project_dir / "stems" / "stems_index.json"
            scene_path = self.project_dir / "drafts" / "scene.draft.json"
            ui_bundle_path = self.project_dir / "ui_bundle.json"
            exit_bundle, _, stderr_bundle = _run_main([
                "bundle",
                "--report", str(report_path),
                "--listen-pack", str(lp_path),
                "--stems-index", str(stems_index_path),
                "--stems-map", str(map_path),
                "--scene", str(scene_path),
                "--out", str(ui_bundle_path),
            ])
            self.assertEqual(exit_bundle, 0, msg=f"mmo bundle failed: {stderr_bundle}")

            # Collect artifact hashes.
            artifacts = [
                self.project_dir / "stems" / "stems_index.json",
                self.project_dir / "stems" / "stems_map.json",
                self.project_dir / "drafts" / "scene.draft.json",
                self.project_dir / "drafts" / "routing_plan.draft.json",
                manifest_path,
                lp_path,
                report_path,
                ui_bundle_path,
                self.bundle_path,
            ]
            # Include all rendered audition WAVs.
            auditions_dir = self.project_dir / "stems_auditions"
            if auditions_dir.is_dir():
                artifacts.extend(sorted(auditions_dir.glob("*.wav")))
            return _snapshot_bytes(artifacts)

        snap_1 = _full_run()
        snap_2 = _full_run()

        self.assertGreater(len(snap_1), 0, "No artifacts found")
        self.assertEqual(snap_1, snap_2, msg="Artifact snapshot differs between runs")


if __name__ == "__main__":
    unittest.main()
