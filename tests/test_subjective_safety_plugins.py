from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from mmo.core.speaker_layout import FILM_5_1, SMPTE_5_1, SpeakerLayout, SpeakerPosition
from mmo.dsp.plugins.base import LayoutContext, MultichannelPlugin, PluginContext, PluginEvidenceCollector
from mmo.dsp.plugins.registry import get_multichannel_plugin, multichannel_plugin_ids
from mmo.plugins.subjective.eq_safety_v0 import EqSafetyV0Plugin
from mmo.plugins.subjective.reverb_safety_v0 import ReverbSafetyV0Plugin

_SAMPLE_RATE = 48000
_NUM_SAMPLES = 4096


def _ctx() -> PluginContext:
    return PluginContext(
        precision_mode="f32",
        max_theoretical_quality=False,
        evidence_collector=PluginEvidenceCollector(),
        stage_index=0,
    )


def _layout_ctx(layout: SpeakerLayout) -> LayoutContext:
    return LayoutContext(layout=layout)


def _noise(layout: SpeakerLayout, *, seed: int, amplitude: float = 0.25) -> Any:
    rng = np.random.default_rng(seed)
    return (
        rng.random((layout.num_channels, _NUM_SAMPLES), dtype=np.float32) * np.float32(amplitude)
    )


class TestSafetyPluginRegistry(unittest.TestCase):
    def test_plugins_registered(self) -> None:
        ids = multichannel_plugin_ids()
        self.assertIn("eq_safety_v0", ids)
        self.assertIn("reverb_safety_v0", ids)
        self.assertIsNotNone(get_multichannel_plugin("eq_safety_v0"))
        self.assertIsNotNone(get_multichannel_plugin("reverb_safety_v0"))


class TestEqSafetyV0(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = EqSafetyV0Plugin()

    def test_protocol_and_semantics(self) -> None:
        self.assertIsInstance(self.plugin, MultichannelPlugin)
        self.assertEqual(self.plugin.plugin_id, "eq_safety_v0")
        self.assertEqual(self.plugin.preferred_standard, "SMPTE")
        self.assertEqual(
            set(self.plugin.supported_standards),
            {"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"},
        )

    def test_preserves_center_and_lfe(self) -> None:
        buf = _noise(SMPTE_5_1, seed=301)
        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "low_mid_trim_db": -2.5,
                "high_shelf_trim_db": -1.5,
                "macro_mix": 1.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        center_slot = SMPTE_5_1.index_of(SpeakerPosition.FC)
        self.assertIsNotNone(center_slot)
        if center_slot is not None:
            np.testing.assert_array_equal(out[center_slot], buf[center_slot])
        for lfe_slot in SMPTE_5_1.lfe_slots:
            np.testing.assert_array_equal(out[lfe_slot], buf[lfe_slot])

    def test_gate_skips_very_quiet_channels(self) -> None:
        buf = _noise(SMPTE_5_1, seed=302, amplitude=1e-4)
        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {
                "gate_rms_dbfs": -40.0,
                "macro_mix": 1.0,
            },
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        np.testing.assert_array_equal(out, buf)

    def test_determinism(self) -> None:
        buf = _noise(FILM_5_1, seed=303)
        params = {"macro_mix": 0.75}
        out_a = self.plugin.process_multichannel(
            buf, _SAMPLE_RATE, params, _ctx(), _layout_ctx(FILM_5_1)
        )
        out_b = self.plugin.process_multichannel(
            buf, _SAMPLE_RATE, params, _ctx(), _layout_ctx(FILM_5_1)
        )
        np.testing.assert_array_equal(out_a, out_b)


class TestReverbSafetyV0(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = ReverbSafetyV0Plugin()

    def test_protocol_and_semantics(self) -> None:
        self.assertIsInstance(self.plugin, MultichannelPlugin)
        self.assertEqual(self.plugin.plugin_id, "reverb_safety_v0")
        self.assertEqual(self.plugin.preferred_standard, "SMPTE")
        self.assertEqual(
            set(self.plugin.supported_standards),
            {"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"},
        )

    def test_bypass_is_exact_passthrough(self) -> None:
        buf = _noise(SMPTE_5_1, seed=401)
        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {"bypass": True},
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        np.testing.assert_array_equal(out, buf)

    def test_preserves_center_and_lfe(self) -> None:
        buf = _noise(FILM_5_1, seed=402)
        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {"macro_mix": 1.0, "wet_db": -12.0},
            _ctx(),
            _layout_ctx(FILM_5_1),
        )
        center_slot = FILM_5_1.index_of(SpeakerPosition.FC)
        self.assertIsNotNone(center_slot)
        if center_slot is not None:
            np.testing.assert_array_equal(out[center_slot], buf[center_slot])
        for lfe_slot in FILM_5_1.lfe_slots:
            np.testing.assert_array_equal(out[lfe_slot], buf[lfe_slot])

    def test_processing_changes_non_protected_channels(self) -> None:
        buf = _noise(SMPTE_5_1, seed=403)
        out = self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {"wet_db": -10.0, "macro_mix": 1.0, "gate_rms_dbfs": -70.0},
            _ctx(),
            _layout_ctx(SMPTE_5_1),
        )
        changed = False
        for slot in range(SMPTE_5_1.num_channels):
            if slot in SMPTE_5_1.lfe_slots:
                continue
            if slot == SMPTE_5_1.index_of(SpeakerPosition.FC):
                continue
            if not np.array_equal(out[slot], buf[slot]):
                changed = True
                break
        self.assertTrue(changed)

    def test_evidence_includes_gate_reference(self) -> None:
        buf = _noise(SMPTE_5_1, seed=404)
        ctx = _ctx()
        self.plugin.process_multichannel(
            buf,
            _SAMPLE_RATE,
            {"macro_mix": 0.6},
            ctx,
            _layout_ctx(SMPTE_5_1),
        )
        notes_text = " ".join(ctx.evidence_collector.notes or [])
        self.assertIn("GATE.NO_CLIP", notes_text)
        self.assertIn("GATE.DOWNMIX_SIMILARITY_MEASURED", notes_text)


if __name__ == "__main__":
    unittest.main()
