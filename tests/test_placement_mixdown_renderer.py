from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.downmix import enforce_rendered_surround_similarity_gate
from mmo.core.layout_negotiation import get_layout_channel_order
from mmo.plugins.renderers.placement_mixdown_renderer import PlacementMixdownRenderer


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.12,
    freq_hz: float = 220.0,
    amplitude: float = 0.25,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for index in range(frames):
        sample = int(
            amplitude
            * 32767.0
            * math.sin(2.0 * math.pi * freq_hz * index / sample_rate_hz)
        )
        interleaved.append(sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _scene_payload(stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.PLACEMENT.RENDERER",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "draft",
        },
        "intent": {
            "confidence": 0.0,
            "locks": [],
        },
        "objects": [
            {
                "object_id": "OBJ.STEM.KICK",
                "stem_id": "STEM.KICK",
                "role_id": "ROLE.DRUM.KICK",
                "group_bus": "BUS.DRUMS",
                "label": "Kick",
                "channel_count": 1,
                "width_hint": 0.2,
                "depth_hint": 0.2,
                "confidence": 0.95,
                "intent": {"confidence": 0.95, "width": 0.2, "depth": 0.2, "locks": []},
                "notes": [],
            },
            {
                "object_id": "OBJ.STEM.SNARE",
                "stem_id": "STEM.SNARE",
                "role_id": "ROLE.DRUM.SNARE",
                "group_bus": "BUS.DRUMS",
                "label": "Snare",
                "channel_count": 1,
                "width_hint": 0.24,
                "depth_hint": 0.22,
                "confidence": 0.92,
                "intent": {"confidence": 0.92, "width": 0.24, "depth": 0.22, "locks": []},
                "notes": [],
            },
            {
                "object_id": "OBJ.STEM.PAD",
                "stem_id": "STEM.PAD",
                "role_id": "ROLE.SYNTH.PAD",
                "group_bus": "BUS.MUSIC.SYNTH",
                "label": "Pad",
                "channel_count": 1,
                "width_hint": 0.93,
                "depth_hint": 0.65,
                "confidence": 0.9,
                "intent": {"confidence": 0.9, "width": 0.93, "depth": 0.65, "locks": []},
                "notes": ["long texture"],
            },
            {
                "object_id": "OBJ.STEM.SFX",
                "stem_id": "STEM.SFX",
                "role_id": "ROLE.SFX.WHOOSH",
                "group_bus": "BUS.FX.AMBIENCE",
                "label": "SFX",
                "channel_count": 1,
                "width_hint": 0.9,
                "depth_hint": 0.8,
                "confidence": 0.88,
                "intent": {"confidence": 0.88, "width": 0.9, "depth": 0.8, "locks": []},
                "notes": ["room", "wash"],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []},
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _output_by_layout(manifest: dict) -> dict[str, dict]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return {}
    out: dict[str, dict] = {}
    for row in outputs:
        if not isinstance(row, dict):
            continue
        layout_id = row.get("layout_id")
        if isinstance(layout_id, str):
            out[layout_id] = row
    return out


class TestPlacementMixdownRenderer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.temp = Path(self._tmp.name)
        self.stems_dir = self.temp / "stems"
        self.out_dir = self.temp / "renders"

        _write_mono_wav(self.stems_dir / "kick.wav", freq_hz=55.0, amplitude=0.3)
        _write_mono_wav(self.stems_dir / "snare.wav", freq_hz=190.0, amplitude=0.24)
        _write_mono_wav(self.stems_dir / "pad.wav", freq_hz=440.0, amplitude=0.2)
        _write_mono_wav(self.stems_dir / "sfx.wav", freq_hz=880.0, amplitude=0.18)

        self.session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {"stem_id": "STEM.KICK", "file_path": "kick.wav", "channel_count": 1},
                {"stem_id": "STEM.SNARE", "file_path": "snare.wav", "channel_count": 1},
                {"stem_id": "STEM.PAD", "file_path": "pad.wav", "channel_count": 1},
                {"stem_id": "STEM.SFX", "file_path": "sfx.wav", "channel_count": 1},
            ],
            "scene_payload": _scene_payload(self.stems_dir),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_renderer_writes_multichannel_outputs_with_expected_channel_counts(self) -> None:
        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(self.session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)

        expected_layouts = (
            "LAYOUT.5_1",
            "LAYOUT.7_1",
            "LAYOUT.7_1_4",
            "LAYOUT.9_1_6",
        )
        for layout_id in expected_layouts:
            output = by_layout.get(layout_id)
            self.assertIsNotNone(output, f"missing manifest output for {layout_id}")
            if not isinstance(output, dict):
                continue
            output_path = self.out_dir / Path(output["file_path"])
            self.assertTrue(output_path.exists(), f"missing rendered file: {output_path}")

            expected_channels = len(get_layout_channel_order(layout_id))
            with wave.open(str(output_path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), expected_channels)

    def test_surround_and_height_sends_only_on_ambient_stems_by_default(self) -> None:
        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(self.session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)
        immersive_row = by_layout.get("LAYOUT.9_1_6")
        self.assertIsInstance(immersive_row, dict)
        if not isinstance(immersive_row, dict):
            return

        metadata = immersive_row.get("metadata")
        self.assertIsInstance(metadata, dict)
        if not isinstance(metadata, dict):
            return

        summary = metadata.get("stem_send_summary")
        self.assertIsInstance(summary, list)
        if not isinstance(summary, list):
            return

        by_stem: dict[str, dict] = {}
        for row in summary:
            if not isinstance(row, dict):
                continue
            stem_id = row.get("stem_id")
            if isinstance(stem_id, str):
                by_stem[stem_id] = row

        backoff_channels = {
            "SPK.LS",
            "SPK.RS",
            "SPK.LRS",
            "SPK.RRS",
            "SPK.LW",
            "SPK.RW",
            "SPK.TFL",
            "SPK.TFR",
            "SPK.TRL",
            "SPK.TRR",
            "SPK.TFC",
            "SPK.TBC",
        }

        for stem_id in ("STEM.KICK", "STEM.SNARE"):
            channels = set(by_stem[stem_id].get("nonzero_channels") or [])
            self.assertEqual(channels & backoff_channels, set())

        for stem_id in ("STEM.PAD", "STEM.SFX"):
            channels = set(by_stem[stem_id].get("nonzero_channels") or [])
            self.assertTrue(channels & backoff_channels)

    def test_similarity_gate_supports_rendered_fallback_after_placement_render(self) -> None:
        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(self.session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)

        stereo = by_layout.get("LAYOUT.2_0")
        surround = by_layout.get("LAYOUT.5_1")
        self.assertIsInstance(stereo, dict)
        self.assertIsInstance(surround, dict)
        if not isinstance(stereo, dict) or not isinstance(surround, dict):
            return

        result = enforce_rendered_surround_similarity_gate(
            stereo_render_file=self.out_dir / Path(stereo["file_path"]),
            surround_render_file=self.out_dir / Path(surround["file_path"]),
            source_layout_id="LAYOUT.5_1",
            surround_backoff_db=-24.0,
            loudness_delta_warn_abs=0.0,
            loudness_delta_error_abs=0.0,
            correlation_time_warn_lte=1.0,
            correlation_time_error_lte=1.0,
            spectral_distance_warn_db=0.0,
            spectral_distance_error_db=0.0,
            peak_delta_warn_abs=0.0,
            peak_delta_error_abs=0.0,
            true_peak_delta_warn_abs=0.0,
            true_peak_delta_error_abs=0.0,
        )

        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("fallback_applied"))
        attempts = result.get("attempts")
        self.assertIsInstance(attempts, list)
        if isinstance(attempts, list):
            self.assertEqual(len(attempts), 2)
        self.assertIn("metrics", result)


if __name__ == "__main__":
    unittest.main()
