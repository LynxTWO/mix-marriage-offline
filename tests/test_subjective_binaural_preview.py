from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

import numpy as np

from mmo.core.speaker_layout import (
    FILM_5_1,
    LOGIC_PRO_5_1,
    SMPTE_5_1,
    VST3_7_1,
    SpeakerLayout,
    SpeakerPosition,
)
from mmo.dsp.plugins.base import LayoutContext, MultichannelPlugin, PluginContext, PluginEvidenceCollector
from mmo.dsp.plugins.registry import get_multichannel_plugin, multichannel_plugin_ids
from mmo.plugins.subjective.binaural_preview_v0 import (
    BinauralPreviewV0Plugin,
    render_headphone_preview_wav,
)

_SAMPLE_RATE = 48000
_NUM_SAMPLES = 4096


def _ctx() -> PluginContext:
    return PluginContext(
        precision_mode="float64",
        max_theoretical_quality=False,
        evidence_collector=PluginEvidenceCollector(),
        stage_index=1,
    )


def _layout_ctx(layout: SpeakerLayout) -> LayoutContext:
    return LayoutContext(layout=layout)


def _tone(frames: int, *, hz: float = 330.0, amp: float = 0.35) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / float(_SAMPLE_RATE)
    return np.sin(2.0 * math.pi * hz * t) * float(amp)


def _rms(samples: Any) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def _write_interleaved_pcm16_wav(path: Path, channels: int, interleaved_float: np.ndarray) -> None:
    if channels <= 0:
        raise ValueError("channels must be positive")
    if interleaved_float.size % channels != 0:
        raise ValueError("interleaved sample count is not frame-aligned")

    frames = interleaved_float.size // channels
    ints = np.clip(np.rint(interleaved_float * 32767.0), -32768.0, 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        handle.writeframes(struct.pack(f"<{ints.size}h", *ints.tolist()))


class TestBinauralPreviewRegistry(unittest.TestCase):
    def test_plugin_registered(self) -> None:
        ids = multichannel_plugin_ids()
        self.assertIn("binaural_preview_v0", ids)
        self.assertIsNotNone(get_multichannel_plugin("binaural_preview_v0"))


class TestBinauralPreviewMeasuredQA(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = BinauralPreviewV0Plugin()

    def test_protocol_and_semantics(self) -> None:
        self.assertIsInstance(self.plugin, MultichannelPlugin)
        self.assertEqual(self.plugin.plugin_id, "binaural_preview_v0")
        self.assertEqual(self.plugin.preferred_standard, "SMPTE")
        self.assertEqual(
            set(self.plugin.supported_standards),
            {"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"},
        )

    def test_deterministic_for_same_input(self) -> None:
        tone = _tone(_NUM_SAMPLES, hz=220.0, amp=0.3)
        buf = np.zeros((SMPTE_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        sl_slot = SMPTE_5_1.index_of(SpeakerPosition.SL)
        self.assertIsNotNone(sl_slot)
        if sl_slot is not None:
            buf[sl_slot] = tone

        params = {
            "gate_rms_dbfs": -80.0,
            "virtualize_width": 1.0,
            "lfe_trim_db": -12.0,
            "macro_mix": 1.0,
        }
        out_a = self.plugin.process_multichannel(buf, _SAMPLE_RATE, params, _ctx(), _layout_ctx(SMPTE_5_1))
        out_b = self.plugin.process_multichannel(buf, _SAMPLE_RATE, params, _ctx(), _layout_ctx(SMPTE_5_1))
        np.testing.assert_array_equal(out_a, out_b)

    def test_gate_mutes_very_quiet_program(self) -> None:
        quiet = np.full((_NUM_SAMPLES,), 1e-7, dtype=np.float64)
        buf = np.zeros((SMPTE_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        fl_slot = SMPTE_5_1.index_of(SpeakerPosition.FL)
        self.assertIsNotNone(fl_slot)
        if fl_slot is not None:
            buf[fl_slot] = quiet

        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "gate_rms_dbfs": -30.0,
                "virtualize_width": 1.0,
                "lfe_trim_db": -12.0,
                "macro_mix": 1.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        self.assertEqual(out.shape, (2, _NUM_SAMPLES))
        self.assertLess(_rms(out[0]), 1e-8)
        self.assertLess(_rms(out[1]), 1e-8)

    def test_measured_ild_for_left_surround(self) -> None:
        tone = _tone(_NUM_SAMPLES, hz=500.0, amp=0.35)
        buf = np.zeros((SMPTE_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        sl_slot = SMPTE_5_1.index_of(SpeakerPosition.SL)
        self.assertIsNotNone(sl_slot)
        if sl_slot is not None:
            buf[sl_slot] = tone

        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "gate_rms_dbfs": -80.0,
                "virtualize_width": 1.0,
                "macro_mix": 1.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        left_rms = _rms(out[0])
        right_rms = _rms(out[1])
        self.assertGreater(left_rms, right_rms * 1.20)

    def test_conservative_hrtf_softens_far_ear_energy(self) -> None:
        tone = _tone(_NUM_SAMPLES, hz=7000.0, amp=0.30)
        buf = np.zeros((SMPTE_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        sl_slot = SMPTE_5_1.index_of(SpeakerPosition.SL)
        self.assertIsNotNone(sl_slot)
        if sl_slot is not None:
            buf[sl_slot] = tone

        params = {
            "gate_rms_dbfs": -80.0,
            "virtualize_width": 1.0,
            "macro_mix": 1.0,
        }
        out_no_hrtf = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                **params,
                "hrtf_amount": 0.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        out_full_hrtf = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                **params,
                "hrtf_amount": 1.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        far_ear_no_hrtf = _rms(out_no_hrtf[1])
        far_ear_with_hrtf = _rms(out_full_hrtf[1])
        self.assertLess(far_ear_with_hrtf, far_ear_no_hrtf * 0.95)

    def test_film_layout_semantic_routing_matches_left_surround(self) -> None:
        tone = _tone(_NUM_SAMPLES, hz=440.0, amp=0.30)
        buf = np.zeros((FILM_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        sl_slot = FILM_5_1.index_of(SpeakerPosition.SL)
        self.assertIsNotNone(sl_slot)
        if sl_slot is not None:
            buf[sl_slot] = tone

        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "gate_rms_dbfs": -80.0,
                "virtualize_width": 1.0,
                "macro_mix": 1.0,
            },
            _ctx(),
            _layout_ctx(FILM_5_1),
        )
        self.assertGreater(_rms(out[0]), _rms(out[1]) * 1.20)

    def test_five_standard_semantic_routing(self) -> None:
        layouts = (SMPTE_5_1, FILM_5_1, LOGIC_PRO_5_1, VST3_7_1)
        for layout in layouts:
            with self.subTest(layout=f"{layout.layout_id}/{layout.standard.value}"):
                tone = _tone(_NUM_SAMPLES, hz=440.0, amp=0.30)
                buf = np.zeros((layout.num_channels, _NUM_SAMPLES), dtype=np.float64)
                sl_slot = layout.index_of(SpeakerPosition.SL)
                self.assertIsNotNone(sl_slot)
                if sl_slot is not None:
                    buf[sl_slot] = tone

                out = self.plugin.process_multichannel(
                    buf,
                    _SAMPLE_RATE,
                    {
                        "gate_rms_dbfs": -80.0,
                        "virtualize_width": 1.0,
                        "hrtf_amount": 0.65,
                        "macro_mix": 1.0,
                    },
                    _ctx(),
                    _layout_ctx(layout),
                )
                self.assertGreater(_rms(out[0]), _rms(out[1]) * 1.15)

    def test_stage_metrics_include_hrtf_fields(self) -> None:
        tone = _tone(_NUM_SAMPLES, hz=360.0, amp=0.24)
        buf = np.zeros((SMPTE_5_1.num_channels, _NUM_SAMPLES), dtype=np.float64)
        sl_slot = SMPTE_5_1.index_of(SpeakerPosition.SL)
        self.assertIsNotNone(sl_slot)
        if sl_slot is not None:
            buf[sl_slot] = tone
        ctx = _ctx()
        self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "gate_rms_dbfs": -80.0,
                "virtualize_width": 1.0,
                "hrtf_amount": 0.75,
                "macro_mix": 1.0,
            },
            ctx,
            _layout_ctx(SMPTE_5_1),
        )
        metrics = {row["name"]: row["value"] for row in ctx.evidence_collector.metrics}
        self.assertIn("hrtf_amount", metrics)
        self.assertIn("hrtf_shaped_channels", metrics)
        self.assertGreater(metrics["hrtf_shaped_channels"], 0.0)

    def test_render_headphone_preview_wav_reports_measured_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_path = root / "source_5_1.wav"
            output_path = root / "preview_headphones.wav"

            frames = _NUM_SAMPLES
            channel_order = FILM_5_1.channel_order
            interleaved = np.zeros(frames * FILM_5_1.num_channels, dtype=np.float64)
            tone = _tone(frames, hz=380.0, amp=0.32)
            for ch, position in enumerate(channel_order):
                if position in {SpeakerPosition.SL, SpeakerPosition.SR}:
                    interleaved[ch::FILM_5_1.num_channels] = tone

            _write_interleaved_pcm16_wav(
                source_path,
                FILM_5_1.num_channels,
                interleaved,
            )

            info = render_headphone_preview_wav(
                source_path=source_path,
                output_path=output_path,
                layout_standard="FILM",
                layout_id_hint="LAYOUT.5_1",
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(info["layout_id"], "LAYOUT.5_1")
            self.assertEqual(info["layout_standard"], "FILM")
            self.assertEqual(info["channel_count"], 2)
            self.assertEqual(info["sample_rate_hz"], _SAMPLE_RATE)
            self.assertGreater(info["frame_count"], 0)
            self.assertIn("processed_channels", {m["name"] for m in info["stage_metrics"]})

    def test_render_headphone_preview_wav_aaf_fallback_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_path = root / "source_5_1.wav"
            output_a = root / "preview_a.headphones.wav"
            output_b = root / "preview_b.headphones.wav"

            frames = _NUM_SAMPLES
            channel_order = FILM_5_1.channel_order
            interleaved = np.zeros(frames * FILM_5_1.num_channels, dtype=np.float64)
            tone = _tone(frames, hz=250.0, amp=0.28)
            for ch, position in enumerate(channel_order):
                if position == SpeakerPosition.FC:
                    interleaved[ch::FILM_5_1.num_channels] = tone
            _write_interleaved_pcm16_wav(
                source_path,
                FILM_5_1.num_channels,
                interleaved,
            )

            info_a = render_headphone_preview_wav(
                source_path=source_path,
                output_path=output_a,
                layout_standard="AAF",
                layout_id_hint="LAYOUT.5_1",
            )
            info_b = render_headphone_preview_wav(
                source_path=source_path,
                output_path=output_b,
                layout_standard="AAF",
                layout_id_hint="LAYOUT.5_1",
            )

            self.assertEqual(info_a["layout_id"], "LAYOUT.5_1")
            self.assertEqual(info_a["layout_standard"], "FILM")
            self.assertEqual(info_a["layout_standard"], info_b["layout_standard"])
            self.assertEqual(info_a["frame_count"], info_b["frame_count"])
            self.assertIn("hrtf_amount", {m["name"] for m in info_a["stage_metrics"]})


if __name__ == "__main__":
    unittest.main()
