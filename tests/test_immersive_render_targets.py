"""Tests for immersive render targets (7.1.4 beds) + height scene_builder notes.

Covers:
- All four immersive TARGET.IMMERSIVE.* entries are registered and loadable.
- Each immersive target maps to the correct LAYOUT.* and has the right channel count.
- scene_builder emits height_bed_714_candidate note for 12-channel stems.
- scene_builder emits height_bed_10ch_candidate note for 10-channel stems.
- scene_builder routing_intent includes height notes for immersive sessions.
- Downmix QA smoke test for 7.1.4 → 2.0 with fake ffprobe/ffmpeg (12ch source).
- Determinism: same inputs → same scene output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _python_cmd() -> str:
    return os.fspath(os.getenv("PYTHON", "") or sys.executable)


def _write_fake_ffprobe_714(directory: Path) -> Path:
    """Fake ffprobe returning 12-channel source, 2-channel reference."""
    script_path = directory / "fake_ffprobe_714.py"
    script_path.write_text(
        (
            "import json\n"
            "import os\n"
            "import sys\n"
            "\n"
            "def main() -> None:\n"
            "    path = sys.argv[-1]\n"
            "    name = os.path.basename(path)\n"
            "    if name.startswith('src'):\n"
            "        payload = {\n"
            "            'streams': [\n"
            "                {\n"
            "                    'codec_type': 'audio',\n"
            "                    'codec_name': 'wav',\n"
            "                    'channels': 12,\n"
            "                    'sample_rate': '48000',\n"
            "                    'duration': '0.5',\n"
            "                    'channel_layout': '7.1.4',\n"
            "                }\n"
            "            ],\n"
            "            'format': {'duration': '0.5'},\n"
            "        }\n"
            "    else:\n"
            "        payload = {\n"
            "            'streams': [\n"
            "                {\n"
            "                    'codec_type': 'audio',\n"
            "                    'codec_name': 'wav',\n"
            "                    'channels': 2,\n"
            "                    'sample_rate': '48000',\n"
            "                    'duration': '0.5',\n"
            "                    'channel_layout': 'stereo',\n"
            "                }\n"
            "            ],\n"
            "            'format': {'duration': '0.5'},\n"
            "        }\n"
            "    print(json.dumps(payload))\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )
    return script_path


def _write_fake_ffmpeg_714(directory: Path) -> Path:
    """Fake ffmpeg emitting 12-channel source samples, 2-channel reference."""
    script_path = directory / "fake_ffmpeg_714.py"
    script_path.write_text(
        (
            "import os\n"
            "import struct\n"
            "import sys\n"
            "\n"
            "def main() -> None:\n"
            "    args = sys.argv[1:]\n"
            "    path = args[args.index('-i') + 1] if '-i' in args else args[-1]\n"
            "    name = os.path.basename(path)\n"
            "    frames = 24000\n"
            "    if name.startswith('src'):\n"
            "        # 12 channels: 7.1.4 bed (all low-level correlated signal)\n"
            "        samples = [0.05] * 12 * frames\n"
            "    else:\n"
            "        samples = [0.05, 0.05] * frames\n"
            "    payload = struct.pack(f'<{len(samples)}d', *samples)\n"
            "    sys.stdout.buffer.write(payload)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )
    return script_path


# ---------------------------------------------------------------------------
# Tests: immersive render targets registry
# ---------------------------------------------------------------------------

class TestImmersiveRenderTargetsRegistry(unittest.TestCase):
    """Verify all four immersive targets are registered and structurally correct."""

    def setUp(self) -> None:
        from mmo.core.registries.render_targets_registry import load_render_targets_registry
        self._registry = load_render_targets_registry()

    def _target(self, target_id: str) -> dict:
        return self._registry.get_target(target_id)

    def test_all_four_immersive_targets_present(self) -> None:
        ids = set(self._registry.list_target_ids())
        for expected_id in (
            "TARGET.IMMERSIVE.5_1_2",
            "TARGET.IMMERSIVE.5_1_4",
            "TARGET.IMMERSIVE.7_1_2",
            "TARGET.IMMERSIVE.7_1_4",
        ):
            self.assertIn(expected_id, ids, f"Missing target: {expected_id}")

    def test_714_target_layout_id(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        self.assertEqual(t["layout_id"], "LAYOUT.7_1_4")

    def test_714_target_channel_count(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        self.assertEqual(len(t["channel_order"]), 12)

    def test_712_target_channel_count(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_2")
        self.assertEqual(len(t["channel_order"]), 10)

    def test_514_target_channel_count(self) -> None:
        t = self._target("TARGET.IMMERSIVE.5_1_4")
        self.assertEqual(len(t["channel_order"]), 10)

    def test_512_target_channel_count(self) -> None:
        t = self._target("TARGET.IMMERSIVE.5_1_2")
        self.assertEqual(len(t["channel_order"]), 8)

    def test_714_container_is_wav(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        self.assertEqual(t["container"], "wav")

    def test_714_filename_template(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        self.assertIn("{container}", t["filename_template"])
        self.assertIn("7_1_4", t["filename_template"])

    def test_714_notes_mention_height(self) -> None:
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        notes = t.get("notes", [])
        combined = " ".join(notes).lower()
        self.assertIn("height", combined)

    def test_714_channel_order_starts_with_lrcfle(self) -> None:
        """7.1.4 SMPTE order: L, R, C, LFE, Ls, Rs, Lrs, Rrs, TFL, TFR, TRL, TRR."""
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        order = t["channel_order"]
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.R")
        self.assertEqual(order[2], "SPK.C")
        self.assertEqual(order[3], "SPK.LFE")

    def test_714_channel_order_ends_with_height_speakers(self) -> None:
        """Height speakers must be the last four channels in 7.1.4."""
        t = self._target("TARGET.IMMERSIVE.7_1_4")
        order = t["channel_order"]
        height_speakers = {"SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR"}
        self.assertEqual(set(order[-4:]), height_speakers)

    def test_find_targets_for_714_layout(self) -> None:
        targets = self._registry.find_targets_for_layout("LAYOUT.7_1_4")
        target_ids = [t["target_id"] for t in targets]
        self.assertIn("TARGET.IMMERSIVE.7_1_4", target_ids)

    def test_target_ids_sorted(self) -> None:
        ids = self._registry.list_target_ids()
        self.assertEqual(ids, sorted(ids), "Registry target_ids must be in sorted order")


# ---------------------------------------------------------------------------
# Tests: scene_builder height notes
# ---------------------------------------------------------------------------

class TestSceneBuilderHeightNotes(unittest.TestCase):
    """Verify scene_builder emits height_bed_* advisory notes for immersive stems."""

    def _build_scene(self, channel_count: int, stem_id: str = "STEM.001") -> dict:
        from mmo.core.scene_builder import build_scene_from_session
        # Use tempfile.gettempdir() for a cross-platform absolute path (supports
        # full immersive layouts + real DAW round-tripping on Linux/macOS/Windows).
        stems_dir = str(Path(tempfile.gettempdir()) / "mmo_test_stems")
        session = {
            "stems_dir": stems_dir,
            "stems": [
                {"stem_id": stem_id, "channel_count": channel_count, "label": "test"},
            ],
        }
        return build_scene_from_session(session)

    def test_12ch_object_has_714_candidate_note(self) -> None:
        scene = self._build_scene(12)
        objects = scene["objects"]
        self.assertEqual(len(objects), 1)
        notes = objects[0]["notes"]
        self.assertIn("height_bed_714_candidate", notes)

    def test_12ch_object_has_multichannel_note(self) -> None:
        scene = self._build_scene(12)
        notes = scene["objects"][0]["notes"]
        self.assertIn("multichannel_as_object", notes)

    def test_10ch_object_has_10ch_candidate_note(self) -> None:
        scene = self._build_scene(10)
        notes = scene["objects"][0]["notes"]
        self.assertIn("height_bed_10ch_candidate", notes)

    def test_10ch_object_has_multichannel_note(self) -> None:
        scene = self._build_scene(10)
        notes = scene["objects"][0]["notes"]
        self.assertIn("multichannel_as_object", notes)

    def test_6ch_object_has_no_height_note(self) -> None:
        scene = self._build_scene(6)
        notes = scene["objects"][0]["notes"]
        self.assertNotIn("height_bed_714_candidate", notes)
        self.assertNotIn("height_bed_10ch_candidate", notes)

    def test_2ch_object_has_no_height_note(self) -> None:
        scene = self._build_scene(2)
        notes = scene["objects"][0]["notes"]
        self.assertNotIn("height_bed_714_candidate", notes)
        self.assertNotIn("height_bed_10ch_candidate", notes)

    def test_routing_intent_immersive_for_12ch(self) -> None:
        scene = self._build_scene(12)
        intent = scene["routing_intent"]
        self.assertEqual(intent["suggested_layout_class"], "immersive")
        self.assertIn("height_bed_714_candidate", intent["notes"])

    def test_routing_intent_immersive_for_10ch(self) -> None:
        scene = self._build_scene(10)
        intent = scene["routing_intent"]
        self.assertEqual(intent["suggested_layout_class"], "immersive")
        self.assertIn("height_bed_10ch_candidate", intent["notes"])

    def test_routing_intent_has_base_immersive_note_for_12ch(self) -> None:
        scene = self._build_scene(12)
        intent = scene["routing_intent"]
        self.assertIn("multichannel_stem_gt6ch", intent["notes"])

    def test_routing_intent_confidence_immersive(self) -> None:
        scene = self._build_scene(12)
        intent = scene["routing_intent"]
        self.assertGreaterEqual(intent["confidence"], 0.7)

    def test_determinism_12ch(self) -> None:
        s1 = self._build_scene(12)
        s2 = self._build_scene(12)
        self.assertEqual(
            json.dumps(s1, sort_keys=True),
            json.dumps(s2, sort_keys=True),
        )

    def test_determinism_10ch(self) -> None:
        s1 = self._build_scene(10)
        s2 = self._build_scene(10)
        self.assertEqual(
            json.dumps(s1, sort_keys=True),
            json.dumps(s2, sort_keys=True),
        )


# ---------------------------------------------------------------------------
# Tests: downmix QA smoke for 7.1.4 → 2.0
# ---------------------------------------------------------------------------

class TestDownmixQaImmersive714(unittest.TestCase):
    """Smoke test: downmix QA for LAYOUT.7_1_4 → LAYOUT.2_0 with fake backends."""

    def test_714_to_20_basic_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            src_path = temp_path / "src_714.flac"
            ref_path = temp_path / "ref_stereo.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = _write_fake_ffprobe_714(temp_path)
            ffmpeg_path = _write_fake_ffmpeg_714(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(_REPO_ROOT / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

            result = subprocess.run(
                [
                    _python_cmd(),
                    "-m", "mmo",
                    "downmix", "qa",
                    "--src", os.fspath(src_path),
                    "--ref", os.fspath(ref_path),
                    "--source-layout", "LAYOUT.7_1_4",
                    "--target-layout", "LAYOUT.2_0",
                    "--meters", "basic",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            dqa = payload.get("downmix_qa", {})
            self.assertEqual(dqa.get("source_layout_id") or
                             _get_log_field(dqa, "source_layout_id"),
                             "LAYOUT.7_1_4")

    def test_714_to_20_matrix_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            src_path = temp_path / "src_714b.flac"
            ref_path = temp_path / "ref_714b.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = _write_fake_ffprobe_714(temp_path)
            ffmpeg_path = _write_fake_ffmpeg_714(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(_REPO_ROOT / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

            result = subprocess.run(
                [
                    _python_cmd(),
                    "-m", "mmo",
                    "downmix", "qa",
                    "--src", os.fspath(src_path),
                    "--ref", os.fspath(ref_path),
                    "--source-layout", "LAYOUT.7_1_4",
                    "--target-layout", "LAYOUT.2_0",
                    "--meters", "basic",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            dqa = payload.get("downmix_qa", {})
            matrix_id = dqa.get("matrix_id")
            # matrix_id must reference the 7.1.4 → 2.0 composed matrix
            self.assertIsNotNone(matrix_id)
            self.assertIn("7_1_4", str(matrix_id))

    def test_714_to_20_log_evidence_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            src_path = temp_path / "src_714c.flac"
            ref_path = temp_path / "ref_714c.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = _write_fake_ffprobe_714(temp_path)
            ffmpeg_path = _write_fake_ffmpeg_714(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(_REPO_ROOT / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

            result = subprocess.run(
                [
                    _python_cmd(),
                    "-m", "mmo",
                    "downmix", "qa",
                    "--src", os.fspath(src_path),
                    "--ref", os.fspath(ref_path),
                    "--source-layout", "LAYOUT.7_1_4",
                    "--target-layout", "LAYOUT.2_0",
                    "--meters", "basic",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            measurements = payload.get("downmix_qa", {}).get("measurements", [])
            evidence_ids = {
                item.get("evidence_id")
                for item in measurements
                if isinstance(item, dict)
            }
            self.assertIn("EVID.DOWNMIX.QA.LOG", evidence_ids)
            self.assertIn("EVID.DOWNMIX.QA.CORR_FOLD", evidence_ids)
            self.assertIn("EVID.DOWNMIX.QA.CORR_REF", evidence_ids)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_log_field(dqa: dict, field: str):
    """Extract a field from the EVID.DOWNMIX.QA.LOG measurement."""
    for m in dqa.get("measurements", []):
        if isinstance(m, dict) and m.get("evidence_id") == "EVID.DOWNMIX.QA.LOG":
            try:
                log_payload = json.loads(m["value"])
                return log_payload.get(field)
            except (json.JSONDecodeError, KeyError):
                pass
    return None


if __name__ == "__main__":
    unittest.main()
