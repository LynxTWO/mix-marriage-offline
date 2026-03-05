from __future__ import annotations

import os
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any
from unittest import mock

from mmo.core.downmix import enforce_rendered_surround_similarity_gate
from mmo.core.layout_negotiation import get_layout_channel_order
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
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


def _write_stereo_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.12,
    freq_hz: float = 220.0,
    left_amplitude: float = 0.25,
    right_amplitude: float = 0.25,
    phase_offset_rad: float = 0.0,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for index in range(frames):
        phase = 2.0 * math.pi * freq_hz * index / sample_rate_hz
        left = int(left_amplitude * 32767.0 * math.sin(phase))
        right = int(right_amplitude * 32767.0 * math.sin(phase + phase_offset_rad))
        interleaved.extend((left, right))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _write_fake_ffprobe(directory: Path) -> Path:
    script_path = directory / "fake_ffprobe.py"
    script_path.write_text(
        """
import json
import sys
from pathlib import Path

_CODECS = {
    ".flac": "flac",
    ".wv": "wavpack",
    ".aiff": "pcm_s16be",
    ".aif": "pcm_s16be",
    ".ape": "ape",
    ".wav": "pcm_s16le",
}


def main() -> None:
    path = Path(sys.argv[-1])
    suffix = path.suffix.lower()
    sample_rate = 44100 if "44k1" in path.stem.lower() else 48000
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": _CODECS.get(suffix, "flac"),
                "channels": 1,
                "sample_rate": str(sample_rate),
                "duration": "0.25",
                "bits_per_raw_sample": "16",
                "channel_layout": "mono",
            }
        ],
        "format": {
            "duration": "0.25",
            "format_name": suffix.lstrip(".") or "unknown",
        },
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )
    return script_path


def _write_fake_ffmpeg(directory: Path) -> Path:
    script_path = directory / "fake_ffmpeg.py"
    script_path.write_text(
        """
import math
import struct
import sys


def main() -> None:
    sample_rate_hz = 48000
    frame_count = 4096
    values = [
        0.18 * math.sin(2.0 * math.pi * 330.0 * index / sample_rate_hz)
        for index in range(frame_count)
    ]
    sys.stdout.buffer.write(struct.pack(f"<{len(values)}d", *values))


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )
    return script_path


def _channel_energy(path: Path) -> tuple[list[float], int]:
    metadata = read_wav_metadata(path)
    channels = int(metadata["channels"])
    sums = [0.0] * channels
    frames = 0
    for chunk in iter_wav_float64_samples(path, error_context="placement renderer test"):
        total = len(chunk)
        if channels <= 0 or total % channels != 0:
            continue
        for index in range(0, total, channels):
            for channel_index in range(channels):
                sample = float(chunk[index + channel_index])
                sums[channel_index] += sample * sample
            frames += 1
    return sums, max(frames, 1)


def _peak_abs(path: Path) -> float:
    peak = 0.0
    for chunk in iter_wav_float64_samples(path, error_context="placement renderer peak"):
        if not chunk:
            continue
        chunk_peak = max(abs(float(sample)) for sample in chunk)
        if chunk_peak > peak:
            peak = chunk_peak
    return peak


def _single_stereo_scene_payload(
    stems_dir: Path,
    *,
    role_id: str = "ROLE.SYNTH.LEAD",
    confidence: float = 0.95,
    perspective: str | None = None,
) -> dict:
    scene = {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.PLACEMENT.STEREO",
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
                "object_id": "OBJ.STEM.STEREO",
                "stem_id": "STEM.STEREO",
                "role_id": role_id,
                "group_bus": "BUS.MUSIC",
                "label": "Stereo Stem",
                "channel_count": 2,
                "width_hint": 0.8,
                "azimuth_hint": 25.0,
                "depth_hint": 0.3,
                "confidence": confidence,
                "intent": {
                    "confidence": confidence,
                    "width": 0.8,
                    "depth": 0.3,
                    "position": {"azimuth_deg": 25.0},
                    "locks": [],
                },
                "notes": [],
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
    if perspective is not None:
        scene["intent"]["perspective"] = perspective
    return scene


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
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []},
                "notes": [],
            },
            {
                "bed_id": "BED.BUS.MUSIC.SYNTH",
                "label": "Music Synth",
                "kind": "bed",
                "bus_id": "BUS.MUSIC.SYNTH",
                "stem_ids": ["STEM.PAD"],
                "content_hint": "pad_texture",
                "width_hint": 0.9,
                "confidence": 0.9,
                "intent": {"diffuse": 0.9, "confidence": 0.9, "locks": []},
                "notes": ["content_hint: pad_texture"],
            },
            {
                "bed_id": "BED.BUS.FX.AMBIENCE",
                "label": "Fx Ambience",
                "kind": "bed",
                "bus_id": "BUS.FX.AMBIENCE",
                "stem_ids": ["STEM.SFX"],
                "content_hint": "ambience",
                "width_hint": 0.95,
                "confidence": 0.88,
                "intent": {"diffuse": 0.95, "confidence": 0.88, "locks": []},
                "notes": ["content_hint: ambience"],
            },
        ],
        "metadata": {},
    }


def _scene_payload_for_stem_ids(stems_dir: Path, stem_ids: list[str]) -> dict:
    objects = []
    for stem_id in stem_ids:
        objects.append(
            {
                "object_id": f"OBJ.{stem_id}",
                "stem_id": stem_id,
                "role_id": "ROLE.SYNTH.LEAD",
                "group_bus": "BUS.MUSIC",
                "label": stem_id,
                "channel_count": 1,
                "width_hint": 0.6,
                "depth_hint": 0.3,
                "confidence": 0.95,
                "intent": {"confidence": 0.95, "width": 0.6, "depth": 0.3, "locks": []},
                "notes": [],
            }
        )
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.PLACEMENT.MULTIFORMAT",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "draft",
        },
        "intent": {
            "confidence": 0.0,
            "locks": [],
        },
        "objects": objects,
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
            "LAYOUT.7_1_6",
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
            surround_sends = by_stem[stem_id].get("surround_sends")
            overhead_sends = by_stem[stem_id].get("overhead_sends")
            why = by_stem[stem_id].get("why")
            self.assertIsInstance(surround_sends, dict)
            self.assertIsInstance(overhead_sends, dict)
            self.assertIsInstance(why, list)
            if isinstance(why, list):
                self.assertIn("surround_send_enabled", why)

    def test_stereo_layout_preserves_lr_energy_ratio(self) -> None:
        stem_path = self.stems_dir / "stereo_lr.wav"
        _write_stereo_wav(
            stem_path,
            left_amplitude=0.56,
            right_amplitude=0.14,
        )
        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {"stem_id": "STEM.STEREO", "file_path": "stereo_lr.wav", "channel_count": 2},
            ],
            "scene_payload": _single_stereo_scene_payload(self.stems_dir),
        }

        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)
        stereo_row = by_layout.get("LAYOUT.2_0")
        self.assertIsInstance(stereo_row, dict)
        if not isinstance(stereo_row, dict):
            return

        rendered_path = self.out_dir / Path(stereo_row["file_path"])
        source_energy, _ = _channel_energy(stem_path)
        rendered_energy, _ = _channel_energy(rendered_path)

        src_ratio_db = 10.0 * math.log10((source_energy[0] + 1e-12) / (source_energy[1] + 1e-12))
        out_ratio_db = 10.0 * math.log10(
            (rendered_energy[0] + 1e-12) / (rendered_energy[1] + 1e-12)
        )
        self.assertAlmostEqual(out_ratio_db, src_ratio_db, delta=0.5)
        self.assertGreater(rendered_energy[0], rendered_energy[1])

        metadata = stereo_row.get("metadata")
        self.assertIsInstance(metadata, dict)
        if not isinstance(metadata, dict):
            return
        summary = metadata.get("stem_send_summary")
        self.assertIsInstance(summary, list)
        if not isinstance(summary, list):
            return
        row = next(
            item
            for item in summary
            if isinstance(item, dict) and item.get("stem_id") == "STEM.STEREO"
        )
        self.assertEqual(row.get("mix_mode"), "stereo_channel_wise_ratio_preserve")
        self.assertFalse(bool(row.get("stereo_reinterpret_allowed")))

    def test_stereo_2_0_ratio_is_preserved_while_immersive_keeps_placement_mix(self) -> None:
        stem_path = self.stems_dir / "stereo_ratio_vs_immersive.wav"
        _write_stereo_wav(
            stem_path,
            left_amplitude=0.92,
            right_amplitude=0.06,
        )
        scene = _single_stereo_scene_payload(
            self.stems_dir,
            role_id="ROLE.SYNTH.LEAD",
            confidence=0.95,
            perspective="in_band",
        )
        scene["intent"]["stereo_reinterpret_allowed"] = True
        scene_object = scene.get("objects")[0]
        if isinstance(scene_object, dict):
            scene_object["azimuth_hint"] = 58.0
            intent_payload = scene_object.get("intent")
            if isinstance(intent_payload, dict):
                position = intent_payload.get("position")
                if isinstance(position, dict):
                    position["azimuth_deg"] = 58.0

        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": "STEM.STEREO",
                    "file_path": "stereo_ratio_vs_immersive.wav",
                    "channel_count": 2,
                },
            ],
            "scene_payload": scene,
        }

        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)
        stereo_row = by_layout.get("LAYOUT.2_0")
        immersive_row = by_layout.get("LAYOUT.9_1_6")
        self.assertIsInstance(stereo_row, dict)
        self.assertIsInstance(immersive_row, dict)
        if not isinstance(stereo_row, dict) or not isinstance(immersive_row, dict):
            return

        rendered_stereo_path = self.out_dir / Path(stereo_row["file_path"])
        source_energy, _ = _channel_energy(stem_path)
        rendered_stereo_energy, _ = _channel_energy(rendered_stereo_path)

        src_ratio_db = 10.0 * math.log10((source_energy[0] + 1e-12) / (source_energy[1] + 1e-12))
        out_ratio_db = 10.0 * math.log10(
            (rendered_stereo_energy[0] + 1e-12) / (rendered_stereo_energy[1] + 1e-12)
        )
        self.assertAlmostEqual(out_ratio_db, src_ratio_db, delta=0.5)

        immersive_meta = immersive_row.get("metadata")
        self.assertIsInstance(immersive_meta, dict)
        if not isinstance(immersive_meta, dict):
            return
        summary = immersive_meta.get("stem_send_summary")
        self.assertIsInstance(summary, list)
        if not isinstance(summary, list):
            return
        stem_summary = next(
            item
            for item in summary
            if isinstance(item, dict) and item.get("stem_id") == "STEM.STEREO"
        )
        self.assertTrue(bool(stem_summary.get("stereo_reinterpret_allowed")))
        mix_mode = stem_summary.get("mix_mode")
        self.assertIsInstance(mix_mode, str)
        if isinstance(mix_mode, str):
            self.assertTrue(mix_mode.startswith("stereo_mid_side_preserve"))
        nonzero_channels = set(stem_summary.get("nonzero_channels") or [])
        self.assertTrue(any(channel not in {"SPK.L", "SPK.R"} for channel in nonzero_channels))

    def test_anchor_stereo_does_not_wrap_without_immersive_perspective(self) -> None:
        stem_path = self.stems_dir / "anchor.wav"
        _write_stereo_wav(
            stem_path,
            left_amplitude=0.48,
            right_amplitude=0.20,
        )
        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {"stem_id": "STEM.STEREO", "file_path": "anchor.wav", "channel_count": 2},
            ],
            "scene_payload": _single_stereo_scene_payload(
                self.stems_dir,
                role_id="ROLE.DRUM.KICK",
                confidence=0.98,
            ),
        }

        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)
        immersive_row = by_layout.get("LAYOUT.9_1_6")
        self.assertIsInstance(immersive_row, dict)
        if not isinstance(immersive_row, dict):
            return

        rendered_path = self.out_dir / Path(immersive_row["file_path"])
        energies, frame_count = _channel_energy(rendered_path)
        order = get_layout_channel_order("LAYOUT.9_1_6")
        per_speaker = {
            speaker_id: energies[index] / frame_count
            for index, speaker_id in enumerate(order)
        }
        front_energy = per_speaker["SPK.L"] + per_speaker["SPK.R"]
        wrap_energy = sum(
            per_speaker.get(speaker_id, 0.0)
            for speaker_id in ("SPK.LS", "SPK.RS", "SPK.LRS", "SPK.RRS", "SPK.LW", "SPK.RW")
        )
        self.assertLess(wrap_energy, front_energy * 1e-4)

    def test_stereo_wrap_to_wides_requires_immersive_perspective_and_confidence(self) -> None:
        stem_path = self.stems_dir / "wrap.wav"
        _write_stereo_wav(
            stem_path,
            left_amplitude=0.52,
            right_amplitude=0.18,
        )
        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {"stem_id": "STEM.STEREO", "file_path": "wrap.wav", "channel_count": 2},
            ],
            "scene_payload": _single_stereo_scene_payload(
                self.stems_dir,
                role_id="ROLE.SYNTH.LEAD",
                confidence=0.95,
                perspective="in_band",
            ),
        }

        renderer = PlacementMixdownRenderer()
        manifest = renderer.render(session, [], self.out_dir)
        by_layout = _output_by_layout(manifest)
        immersive_row = by_layout.get("LAYOUT.9_1_6")
        self.assertIsInstance(immersive_row, dict)
        if not isinstance(immersive_row, dict):
            return

        rendered_path = self.out_dir / Path(immersive_row["file_path"])
        energies, frame_count = _channel_energy(rendered_path)
        order = get_layout_channel_order("LAYOUT.9_1_6")
        per_speaker = {
            speaker_id: energies[index] / frame_count
            for index, speaker_id in enumerate(order)
        }
        front_energy = per_speaker["SPK.L"] + per_speaker["SPK.R"]
        wide_energy = per_speaker.get("SPK.LW", 0.0) + per_speaker.get("SPK.RW", 0.0)
        self.assertGreater(wide_energy, 0.0)
        self.assertLess(wide_energy, front_energy * 0.05)

        metadata = immersive_row.get("metadata")
        self.assertIsInstance(metadata, dict)
        if not isinstance(metadata, dict):
            return
        summary = metadata.get("stem_send_summary")
        self.assertIsInstance(summary, list)
        if not isinstance(summary, list):
            return
        row = next(
            item
            for item in summary
            if isinstance(item, dict) and item.get("stem_id") == "STEM.STEREO"
        )
        mix_mode = row.get("mix_mode")
        self.assertIsInstance(mix_mode, str)
        if isinstance(mix_mode, str):
            self.assertIn("wide_wrap", mix_mode)

    def test_two_pass_streaming_long_fixture_has_stable_hash_and_peak_limit(self) -> None:
        stem_path = self.stems_dir / "long_stereo.wav"
        _write_stereo_wav(
            stem_path,
            sample_rate_hz=8_000,
            duration_s=75.0,
            freq_hz=110.0,
            left_amplitude=0.9,
            right_amplitude=0.5,
            phase_offset_rad=0.7,
        )
        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": [
                {"stem_id": "STEM.STEREO", "file_path": "long_stereo.wav", "channel_count": 2},
            ],
            "scene_payload": _single_stereo_scene_payload(
                self.stems_dir,
                role_id="ROLE.SYNTH.LEAD",
                confidence=0.95,
                perspective="in_band",
            ),
        }

        renderer = PlacementMixdownRenderer()
        out_a = self.temp / "long_render_a"
        out_b = self.temp / "long_render_b"
        manifest_a = renderer.render(session, [], out_a)
        manifest_b = renderer.render(session, [], out_b)
        by_layout_a = _output_by_layout(manifest_a)
        by_layout_b = _output_by_layout(manifest_b)

        row_a = by_layout_a.get("LAYOUT.7_1_4")
        row_b = by_layout_b.get("LAYOUT.7_1_4")
        self.assertIsInstance(row_a, dict)
        self.assertIsInstance(row_b, dict)
        if not isinstance(row_a, dict) or not isinstance(row_b, dict):
            return

        path_a = out_a / Path(row_a["file_path"])
        path_b = out_b / Path(row_b["file_path"])
        self.assertTrue(path_a.exists())
        self.assertTrue(path_b.exists())

        expected_channels = len(get_layout_channel_order("LAYOUT.7_1_4"))
        with wave.open(str(path_a), "rb") as handle:
            self.assertEqual(handle.getnchannels(), expected_channels)

        target_peak_linear = math.pow(10.0, -1.0 / 20.0)
        self.assertLessEqual(_peak_abs(path_a), target_peak_linear + 1e-4)

        self.assertEqual(row_a.get("sha256"), sha256_file(path_a))
        self.assertEqual(row_b.get("sha256"), sha256_file(path_b))
        self.assertEqual(row_a.get("sha256"), row_b.get("sha256"))

        metadata = row_a.get("metadata")
        self.assertIsInstance(metadata, dict)
        if not isinstance(metadata, dict):
            return
        self.assertEqual(metadata.get("render_strategy"), "two_pass_streaming")
        self.assertEqual(metadata.get("render_passes"), 2)
        self.assertEqual(metadata.get("chunk_frames"), 4096)

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

    def test_renderer_decodes_mixed_lossless_formats_in_one_session(self) -> None:
        _write_mono_wav(self.stems_dir / "stem_wav.wav", freq_hz=130.0, amplitude=0.2)
        for extension in ("flac", "wv", "aiff", "ape"):
            (self.stems_dir / f"stem_{extension}.{extension}").write_bytes(b"")

        stem_rows = [
            {"stem_id": "STEM.WAV", "file_path": "stem_wav.wav"},
            {"stem_id": "STEM.FLAC", "file_path": "stem_flac.flac"},
            {"stem_id": "STEM.WV", "file_path": "stem_wv.wv"},
            {"stem_id": "STEM.AIFF", "file_path": "stem_aiff.aiff"},
            {"stem_id": "STEM.APE", "file_path": "stem_ape.ape"},
        ]
        session = {
            "stems_dir": self.stems_dir.resolve().as_posix(),
            "stems": stem_rows,
            "scene_payload": _scene_payload_for_stem_ids(
                self.stems_dir,
                [row["stem_id"] for row in stem_rows],
            ),
        }
        fake_ffprobe = _write_fake_ffprobe(self.temp)
        fake_ffmpeg = _write_fake_ffmpeg(self.temp)

        with mock.patch.dict(
            os.environ,
            {
                "MMO_FFPROBE_PATH": str(fake_ffprobe),
                "MMO_FFMPEG_PATH": str(fake_ffmpeg),
            },
            clear=False,
        ):
            renderer = PlacementMixdownRenderer()
            manifest = renderer.render(session, [], self.out_dir / "mixed_lossless")

        by_layout = _output_by_layout(manifest)
        stereo_row = by_layout.get("LAYOUT.2_0")
        self.assertIsInstance(stereo_row, dict)
        if not isinstance(stereo_row, dict):
            return

        rendered_path = self.out_dir / "mixed_lossless" / Path(stereo_row["file_path"])
        self.assertTrue(rendered_path.exists())
        self.assertGreater(rendered_path.stat().st_size, 44)

        metadata = stereo_row.get("metadata")
        self.assertIsInstance(metadata, dict)
        if not isinstance(metadata, dict):
            return
        self.assertEqual(metadata.get("decoded_stem_count"), 5)
        resampling = metadata.get("resampling")
        self.assertIsInstance(resampling, dict)
        if isinstance(resampling, dict):
            self.assertEqual(resampling.get("target_sample_rate_hz"), 48000)
            self.assertEqual(resampling.get("resampled_stems"), [])

    def test_renderer_resampling_policy_majority_then_higher_tiebreak(self) -> None:
        fake_ffprobe = _write_fake_ffprobe(self.temp)
        fake_ffmpeg = _write_fake_ffmpeg(self.temp)

        def _render_session(stem_rows: list[dict[str, str]], out_dir: Path) -> dict[str, Any]:
            session = {
                "stems_dir": self.stems_dir.resolve().as_posix(),
                "stems": stem_rows,
                "scene_payload": _scene_payload_for_stem_ids(
                    self.stems_dir,
                    [row["stem_id"] for row in stem_rows],
                ),
            }
            with mock.patch.dict(
                os.environ,
                {
                    "MMO_FFPROBE_PATH": str(fake_ffprobe),
                    "MMO_FFMPEG_PATH": str(fake_ffmpeg),
                },
                clear=False,
            ):
                renderer = PlacementMixdownRenderer()
                return renderer.render(session, [], out_dir)

        _write_mono_wav(self.stems_dir / "wav_48k.wav", sample_rate_hz=48000, freq_hz=180.0)
        for rel in ("flac_44k1.flac", "wv_44k1.wv", "flac_48k.flac", "aiff_44k1.aiff"):
            (self.stems_dir / rel).write_bytes(b"")

        majority_manifest = _render_session(
            [
                {"stem_id": "STEM.WAV48", "file_path": "wav_48k.wav"},
                {"stem_id": "STEM.FLAC44", "file_path": "flac_44k1.flac"},
                {"stem_id": "STEM.WV44", "file_path": "wv_44k1.wv"},
            ],
            self.out_dir / "resample_majority",
        )
        majority_row = _output_by_layout(majority_manifest).get("LAYOUT.2_0")
        self.assertIsInstance(majority_row, dict)
        if not isinstance(majority_row, dict):
            return
        self.assertEqual(majority_row.get("sample_rate_hz"), 44100)
        majority_meta = majority_row.get("metadata")
        self.assertIsInstance(majority_meta, dict)
        if isinstance(majority_meta, dict):
            resampling = majority_meta.get("resampling")
            self.assertIsInstance(resampling, dict)
            if isinstance(resampling, dict):
                selection = resampling.get("selection")
                self.assertIsInstance(selection, dict)
                if isinstance(selection, dict):
                    self.assertEqual(selection.get("selection_reason"), "majority")
                resampled = resampling.get("resampled_stems")
                self.assertIsInstance(resampled, list)
                if isinstance(resampled, list):
                    stem_ids = {
                        item.get("stem_id")
                        for item in resampled
                        if isinstance(item, dict)
                    }
                    self.assertIn("STEM.WAV48", stem_ids)

        tie_manifest = _render_session(
            [
                {"stem_id": "STEM.WAV48", "file_path": "wav_48k.wav"},
                {"stem_id": "STEM.FLAC48", "file_path": "flac_48k.flac"},
                {"stem_id": "STEM.WV44", "file_path": "wv_44k1.wv"},
                {"stem_id": "STEM.AIFF44", "file_path": "aiff_44k1.aiff"},
            ],
            self.out_dir / "resample_tie",
        )
        tie_row = _output_by_layout(tie_manifest).get("LAYOUT.2_0")
        self.assertIsInstance(tie_row, dict)
        if not isinstance(tie_row, dict):
            return
        self.assertEqual(tie_row.get("sample_rate_hz"), 48000)
        tie_meta = tie_row.get("metadata")
        self.assertIsInstance(tie_meta, dict)
        if isinstance(tie_meta, dict):
            resampling = tie_meta.get("resampling")
            self.assertIsInstance(resampling, dict)
            if isinstance(resampling, dict):
                selection = resampling.get("selection")
                self.assertIsInstance(selection, dict)
                if isinstance(selection, dict):
                    self.assertEqual(
                        selection.get("selection_reason"),
                        "tie_higher_sample_rate",
                    )


if __name__ == "__main__":
    unittest.main()
