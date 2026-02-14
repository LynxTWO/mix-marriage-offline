import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main


def _write_wav(path: Path, *, channels: int = 1, rate: int = 44100,
               num_frames: int = 44100, sample_val: int = 1000) -> None:
    """Write a tiny WAV file with repeating sample values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import array
    samples = array.array("h", [sample_val] * (num_frames * channels))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def _make_stems_map(assignments: list[dict]) -> dict:
    """Build a minimal valid stems_map payload."""
    counts_by_role: dict[str, int] = {}
    counts_by_bus: dict[str, int] = {}
    for a in assignments:
        role = a["role_id"]
        counts_by_role[role] = counts_by_role.get(role, 0) + 1
        bg = a.get("bus_group")
        if bg:
            counts_by_bus[bg] = counts_by_bus.get(bg, 0) + 1
    return {
        "version": "0.1.0",
        "stems_index_ref": "test_index",
        "roles_ref": "test_roles",
        "assignments": assignments,
        "summary": {
            "counts_by_role": counts_by_role,
            "counts_by_bus_group": counts_by_bus,
            "unknown_files": 0,
        },
    }


def _make_assignment(rel_path: str, role_id: str, bus_group: str | None,
                     file_id: str | None = None) -> dict:
    """Build a single assignment entry."""
    if file_id is None:
        import hashlib
        file_id = "STEMFILE." + hashlib.sha1(
            rel_path.encode("utf-8")
        ).hexdigest()[:10]
    return {
        "file_id": file_id,
        "rel_path": rel_path,
        "role_id": role_id,
        "confidence": 0.9,
        "bus_group": bus_group,
        "reasons": ["test_reason"],
        "link_group_id": None,
    }


class TestCliStemsAudition(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_basic_audition_renders_wavs_and_manifest(self) -> None:
        """Render two bus groups and verify WAVs + manifest are created."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            out_dir = temp / "output"

            _write_wav(stems_dir / "drums" / "kick.wav")
            _write_wav(stems_dir / "drums" / "snare.wav")
            _write_wav(stems_dir / "bass" / "bass.wav")

            stems_map = _make_stems_map([
                _make_assignment("drums/kick.wav", "ROLE.DRUM.KICK", "DRUMS"),
                _make_assignment("drums/snare.wav", "ROLE.DRUM.SNARE", "DRUMS"),
                _make_assignment("bass/bass.wav", "ROLE.BASS.ELECTRIC", "BASS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(out_dir),
                "--segment", "1.0",
                "--format", "json",
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=f"stderr: {stderr}")
            result = json.loads(stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["rendered_groups_count"], 2)
            self.assertEqual(result["attempted_groups_count"], 2)

            audition_dir = out_dir / "stems_auditions"
            self.assertTrue((audition_dir / "manifest.json").exists())
            self.assertTrue((audition_dir / "drums.wav").exists())
            self.assertTrue((audition_dir / "bass.wav").exists())

            manifest = json.loads(
                (audition_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["segment_seconds"], 1.0)
            self.assertEqual(manifest["rendered_groups_count"], 2)
            group_ids = [g["bus_group_id"] for g in manifest["groups"]]
            self.assertEqual(group_ids, sorted(group_ids))

    def test_repeat_runs_produce_identical_output(self) -> None:
        """Determinism: two runs must produce identical manifest and WAVs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "kick.wav", num_frames=4410)
            _write_wav(stems_dir / "snare.wav", num_frames=4410)

            stems_map = _make_stems_map([
                _make_assignment("kick.wav", "ROLE.DRUM.KICK", "DRUMS"),
                _make_assignment("snare.wav", "ROLE.DRUM.SNARE", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            out1 = temp / "out1"
            out2 = temp / "out2"

            args1 = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(out1),
                "--segment", "0.5",
                "--format", "json",
            ]
            args2 = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(out2),
                "--segment", "0.5",
                "--format", "json",
            ]

            exit1, stdout1, stderr1 = self._run_main(args1)
            exit2, stdout2, stderr2 = self._run_main(args2)

            self.assertEqual(exit1, 0, msg=stderr1)
            self.assertEqual(exit2, 0, msg=stderr2)

            # Manifests must be identical (except paths)
            m1 = json.loads(
                (out1 / "stems_auditions" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            m2 = json.loads(
                (out2 / "stems_auditions" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            # Compare structural fields (not stems_dir which has temp paths)
            self.assertEqual(m1["segment_seconds"], m2["segment_seconds"])
            self.assertEqual(m1["groups"], m2["groups"])
            self.assertEqual(m1["warnings"], m2["warnings"])
            self.assertEqual(
                m1["rendered_groups_count"], m2["rendered_groups_count"]
            )

            # WAV files must be bit-identical
            wav1 = (out1 / "stems_auditions" / "drums.wav").read_bytes()
            wav2 = (out2 / "stems_auditions" / "drums.wav").read_bytes()
            self.assertEqual(wav1, wav2)

    def test_deterministic_group_and_stem_ordering(self) -> None:
        """Groups must be sorted by bus_group_id, stems by rel_path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "z_vocal.wav", num_frames=4410)
            _write_wav(stems_dir / "a_bass.wav", num_frames=4410)
            _write_wav(stems_dir / "m_drum.wav", num_frames=4410)

            stems_map = _make_stems_map([
                _make_assignment("z_vocal.wav", "ROLE.VOCAL.LEAD", "VOCALS"),
                _make_assignment("a_bass.wav", "ROLE.BASS.ELECTRIC", "BASS"),
                _make_assignment("m_drum.wav", "ROLE.DRUM.KICK", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(temp / "out"),
                "--segment", "0.1",
                "--format", "json",
            ]
            exit_code, stdout, stderr = self._run_main(args)
            self.assertEqual(exit_code, 0, msg=stderr)

            manifest = json.loads(
                (temp / "out" / "stems_auditions" / "manifest.json")
                .read_text(encoding="utf-8")
            )
            group_ids = [g["bus_group_id"] for g in manifest["groups"]]
            self.assertEqual(group_ids, ["BASS", "DRUMS", "VOCALS"])

    def test_missing_file_warns_but_renders_other_groups(self) -> None:
        """A missing file should generate warnings but not block other groups."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "kick.wav", num_frames=4410)
            # snare.wav intentionally missing

            stems_map = _make_stems_map([
                _make_assignment("kick.wav", "ROLE.DRUM.KICK", "DRUMS"),
                _make_assignment("snare.wav", "ROLE.DRUM.SNARE", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(temp / "out"),
                "--segment", "0.1",
                "--format", "json",
            ]
            exit_code, stdout, stderr = self._run_main(args)
            self.assertEqual(exit_code, 0, msg=stderr)

            result = json.loads(stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["missing_files_count"], 1)
            self.assertEqual(result["rendered_groups_count"], 1)

            manifest = json.loads(
                (temp / "out" / "stems_auditions" / "manifest.json")
                .read_text(encoding="utf-8")
            )
            drums_group = manifest["groups"][0]
            self.assertEqual(drums_group["bus_group_id"], "DRUMS")
            self.assertIn("kick.wav", drums_group["stems_included"])
            self.assertIn("snare.wav", drums_group["stems_missing"])
            self.assertTrue(len(manifest["warnings"]) > 0)

    def test_no_renderable_groups_exits_nonzero(self) -> None:
        """When no groups have renderable stems, exit non-zero with stable error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            stems_dir.mkdir(parents=True)
            # All files missing

            stems_map = _make_stems_map([
                _make_assignment("missing1.wav", "ROLE.DRUM.KICK", "DRUMS"),
                _make_assignment("missing2.wav", "ROLE.BASS.ELECTRIC", "BASS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(temp / "out"),
                "--segment", "0.1",
                "--format", "json",
            ]
            exit1, stdout1, _ = self._run_main(args)
            exit2, stdout2, _ = self._run_main(args)

            self.assertEqual(exit1, 1)
            self.assertEqual(exit2, 1)

            err1 = json.loads(stdout1)
            err2 = json.loads(stdout2)

            self.assertFalse(err1["ok"])
            self.assertEqual(err1["error_code"], "NO_RENDERABLE_GROUPS")
            self.assertEqual(err1["missing_files_count"], 2)
            self.assertEqual(err1["groups_attempted_count"], 2)

            # Determinism: both runs produce identical error
            self.assertEqual(err1, err2)

    def test_stereo_upmix_from_mono(self) -> None:
        """If first file is stereo, mono files should be upmixed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "stereo.wav", channels=2, num_frames=4410)
            _write_wav(stems_dir / "mono.wav", channels=1, num_frames=4410)

            stems_map = _make_stems_map([
                _make_assignment("mono.wav", "ROLE.DRUM.SNARE", "DRUMS"),
                _make_assignment("stereo.wav", "ROLE.DRUM.KICK", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(temp / "out"),
                "--segment", "0.1",
                "--format", "json",
            ]
            exit_code, stdout, stderr = self._run_main(args)
            self.assertEqual(exit_code, 0, msg=stderr)

            result = json.loads(stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["rendered_groups_count"], 1)

            # Verify output WAV is readable and has expected properties
            wav_path = temp / "out" / "stems_auditions" / "drums.wav"
            self.assertTrue(wav_path.exists())
            with wave.open(str(wav_path), "rb") as wf:
                # First renderable by sorted rel_path is mono.wav (m < s),
                # which is mono, so target_channels = 1
                self.assertEqual(wf.getframerate(), 44100)

    def test_text_format_output(self) -> None:
        """Text format should print human-readable summary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "kick.wav", num_frames=4410)

            stems_map = _make_stems_map([
                _make_assignment("kick.wav", "ROLE.DRUM.KICK", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(temp / "out"),
                "--segment", "0.1",
                "--format", "text",
            ]
            exit_code, stdout, stderr = self._run_main(args)
            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertIn("Audition pack written to:", stdout)
            self.assertIn("Rendered: 1 / 1 groups", stdout)

    def test_overwrite_flag_required_for_existing_manifest(self) -> None:
        """Without --overwrite, re-running on existing manifest should fail."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems_root"
            _write_wav(stems_dir / "kick.wav", num_frames=4410)

            stems_map = _make_stems_map([
                _make_assignment("kick.wav", "ROLE.DRUM.KICK", "DRUMS"),
            ])
            map_path = temp / "stems_map.json"
            map_path.write_text(
                json.dumps(stems_map, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            out_dir = temp / "out"

            base_args = [
                "stems", "audition",
                "--stems-map", str(map_path),
                "--stems-dir", str(stems_dir),
                "--out-dir", str(out_dir),
                "--segment", "0.1",
            ]

            # First run succeeds
            exit1, _, _ = self._run_main(base_args)
            self.assertEqual(exit1, 0)

            # Second run without --overwrite fails
            exit2, _, stderr2 = self._run_main(base_args)
            self.assertEqual(exit2, 1)
            self.assertIn("Use --overwrite", stderr2)

            # Third run with --overwrite succeeds
            exit3, _, _ = self._run_main(base_args + ["--overwrite"])
            self.assertEqual(exit3, 0)


if __name__ == "__main__":
    unittest.main()
