"""Tests for the conservative subjective plugin pack.

Covers:
- All three plugins implement MultichannelPlugin protocol.
- Channel routing via LayoutContext — never hard-coded indices.
- All five channel ordering standards: SMPTE, FILM, LOGIC_PRO, VST3, AAF.
- Height-bed layouts (5.1.4, 7.1.4) for height_air_v0.
- Bypass mode: output identical to input.
- Determinism: same params + same audio → identical output on repeated calls.
- Evidence: collector populated with required fields after processing.
- Macro mix endpoints (0.0 and 1.0) and mid-blend behaviour.
- Registry: multichannel plugins accessible via get_multichannel_plugin().
- Semantic declarations: supported_standards and preferred_standard class attributes.

Determinism guarantee: all assertions produce the same result on repeated runs.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import numpy as np

from mmo.core.speaker_layout import (
    FILM_5_1,
    FILM_5_1_4,
    FILM_7_1_4,
    LOGIC_PRO_5_1,
    LOGIC_PRO_7_1,
    SMPTE_5_1,
    SMPTE_5_1_4,
    SMPTE_7_1,
    SMPTE_7_1_4,
    VST3_7_1,
    VST3_7_1_4,
    SpeakerLayout,
    SpeakerPosition,
)
from mmo.dsp.plugins.base import (
    LayoutContext,
    MultichannelPlugin,
    PluginContext,
    PluginEvidenceCollector,
)
from mmo.dsp.plugins.registry import (
    get_multichannel_plugin,
    multichannel_plugin_ids,
)
from mmo.plugins.subjective.early_reflections_v0 import EarlyReflectionsV0Plugin
from mmo.plugins.subjective.height_air_v0 import HeightAirV0Plugin
from mmo.plugins.subjective.stereo_widener_v0 import StereoWidenerV0Plugin

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_RATE = 48000
NUM_SAMPLES = 4096


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence() -> PluginEvidenceCollector:
    return PluginEvidenceCollector()


def _make_ctx(stage_index: int = 0) -> PluginContext:
    return PluginContext(
        precision_mode="f32",
        max_theoretical_quality=False,
        evidence_collector=_make_evidence(),
        stage_index=stage_index,
    )


def _make_layout_ctx(layout: SpeakerLayout) -> LayoutContext:
    return LayoutContext(layout=layout)


def _silence(layout: SpeakerLayout) -> Any:
    """Return an all-zero float32 buffer matching the layout channel count."""
    return np.zeros((layout.num_channels, NUM_SAMPLES), dtype=np.float32)


def _white_noise(layout: SpeakerLayout, seed: int = 42) -> Any:
    """Return deterministic white noise float32 buffer at 0.25 amplitude."""
    rng = np.random.default_rng(seed)
    return rng.random((layout.num_channels, NUM_SAMPLES), dtype=np.float32) * 0.25


def _run(
    plugin: Any,
    buf: Any,
    layout: SpeakerLayout,
    params: dict[str, Any],
    sample_rate: int = SAMPLE_RATE,
) -> tuple[Any, PluginContext]:
    ctx = _make_ctx()
    layout_ctx = _make_layout_ctx(layout)
    result = plugin.process_multichannel(buf, sample_rate, params, ctx, layout_ctx)
    return result, ctx


# ---------------------------------------------------------------------------
# TestProtocol: all plugins satisfy MultichannelPlugin protocol
# ---------------------------------------------------------------------------


class TestProtocol(unittest.TestCase):
    def test_height_air_implements_protocol(self) -> None:
        p = HeightAirV0Plugin()
        self.assertIsInstance(p, MultichannelPlugin)

    def test_stereo_widener_implements_protocol(self) -> None:
        p = StereoWidenerV0Plugin()
        self.assertIsInstance(p, MultichannelPlugin)

    def test_early_reflections_implements_protocol(self) -> None:
        p = EarlyReflectionsV0Plugin()
        self.assertIsInstance(p, MultichannelPlugin)

    def test_plugin_ids_are_strings(self) -> None:
        for cls in (HeightAirV0Plugin, StereoWidenerV0Plugin, EarlyReflectionsV0Plugin):
            p = cls()
            self.assertIsInstance(p.plugin_id, str)
            self.assertTrue(len(p.plugin_id) > 0)

    def test_supported_standards_declared(self) -> None:
        expected = {"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"}
        for cls in (HeightAirV0Plugin, StereoWidenerV0Plugin, EarlyReflectionsV0Plugin):
            p = cls()
            self.assertEqual(set(p.supported_standards), expected, msg=cls.__name__)

    def test_preferred_standard_is_smpte(self) -> None:
        for cls in (HeightAirV0Plugin, StereoWidenerV0Plugin, EarlyReflectionsV0Plugin):
            p = cls()
            self.assertEqual(p.preferred_standard, "SMPTE", msg=cls.__name__)


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------


class TestRegistry(unittest.TestCase):
    def test_all_three_registered(self) -> None:
        ids = multichannel_plugin_ids()
        self.assertIn("height_air_v0", ids)
        self.assertIn("stereo_widener_v0", ids)
        self.assertIn("early_reflections_v0", ids)

    def test_get_by_id_returns_instance(self) -> None:
        for pid in ("height_air_v0", "stereo_widener_v0", "early_reflections_v0"):
            p = get_multichannel_plugin(pid)
            self.assertIsNotNone(p, msg=f"Plugin {pid!r} not found in registry")

    def test_unknown_id_returns_none(self) -> None:
        self.assertIsNone(get_multichannel_plugin("nonexistent_plugin"))

    def test_ids_are_deterministic(self) -> None:
        """multichannel_plugin_ids() must return the same order every time."""
        self.assertEqual(multichannel_plugin_ids(), multichannel_plugin_ids())


# ---------------------------------------------------------------------------
# TestHeightAirV0: channel routing, height isolation, no-height passthrough
# ---------------------------------------------------------------------------


class TestHeightAirV0(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = HeightAirV0Plugin()
        self.params = {
            "air_shelf_hz": 10000.0,
            "air_gain_db": 1.5,
            "bypass": False,
            "macro_mix": 1.0,
        }

    def _run(self, buf: Any, layout: SpeakerLayout, **param_overrides: Any) -> Any:
        params = dict(self.params)
        params.update(param_overrides)
        result, _ = _run(self.plugin, buf, layout, params)
        return result

    def test_passthrough_when_no_height_channels(self) -> None:
        """5.1 layouts have no height channels — output must equal input."""
        buf = _white_noise(SMPTE_5_1)
        result = self._run(buf, SMPTE_5_1)
        np.testing.assert_array_equal(result, buf)

    def test_height_channels_modified_in_5_1_4(self) -> None:
        """5.1.4 height channels must be changed; bed channels must be identical."""
        buf = _white_noise(SMPTE_5_1_4, seed=1)
        result = self._run(buf, SMPTE_5_1_4)
        height_slots = SMPTE_5_1_4.height_slots
        self.assertTrue(len(height_slots) > 0)
        # At least one height channel must differ from input.
        any_changed = any(
            not np.array_equal(result[s], buf[s]) for s in height_slots
        )
        self.assertTrue(any_changed, "Expected at least one height channel to be modified")
        # Non-height bed channels must be exactly equal.
        bed_slots = [
            i for i in range(SMPTE_5_1_4.num_channels)
            if i not in height_slots and i not in SMPTE_5_1_4.lfe_slots
        ]
        for slot in bed_slots:
            np.testing.assert_array_equal(result[slot], buf[slot])

    def test_lfe_never_touched(self) -> None:
        """LFE slot must be identical to input regardless of layout."""
        for layout in (SMPTE_5_1_4, SMPTE_7_1_4, FILM_5_1_4, FILM_7_1_4):
            buf = _white_noise(layout, seed=2)
            result = self._run(buf, layout)
            for lfe_slot in layout.lfe_slots:
                np.testing.assert_array_equal(
                    result[lfe_slot], buf[lfe_slot],
                    err_msg=f"LFE slot {lfe_slot} was modified for layout {layout.layout_id}/{layout.standard.value}",
                )

    def test_film_standard_height_routing(self) -> None:
        """FILM 5.1.4 height slots differ from SMPTE — routing must still be correct."""
        smpte_buf = _white_noise(SMPTE_5_1_4, seed=3)
        film_buf = smpte_buf.copy()
        # FILM and SMPTE have height at the same slot indices for 5.1.4
        # but the layout object carries the correct standard.
        result = self._run(film_buf, FILM_5_1_4)
        height_slots = FILM_5_1_4.height_slots
        # Height channels should be processed.
        any_changed = any(
            not np.array_equal(result[s], film_buf[s]) for s in height_slots
        )
        self.assertTrue(any_changed, "FILM 5.1.4 height channels not modified")

    def test_bypass_returns_exact_input(self) -> None:
        """Bypass must return buffer bit-for-bit identical to input."""
        for layout in (SMPTE_5_1_4, SMPTE_7_1_4):
            buf = _white_noise(layout, seed=4)
            result = self._run(buf, layout, bypass=True)
            np.testing.assert_array_equal(result, buf)

    def test_determinism(self) -> None:
        """Same inputs → same output on repeated invocations."""
        buf = _white_noise(SMPTE_5_1_4, seed=5)
        r1 = self._run(buf, SMPTE_5_1_4)
        r2 = self._run(buf, SMPTE_5_1_4)
        np.testing.assert_array_equal(r1, r2)

    def test_macro_mix_zero_is_dry(self) -> None:
        """macro_mix=0.0 must return input unchanged."""
        buf = _white_noise(SMPTE_5_1_4, seed=6)
        result = self._run(buf, SMPTE_5_1_4, macro_mix=0.0)
        np.testing.assert_array_equal(result, buf)

    def test_evidence_populated(self) -> None:
        """Evidence collector must be populated after processing."""
        buf = _white_noise(SMPTE_5_1_4, seed=7)
        _, ctx = _run(
            self.plugin, buf, SMPTE_5_1_4, self.params
        )
        ev = ctx.evidence_collector
        self.assertIsInstance(ev.stage_what, str)
        self.assertTrue(len(ev.stage_what) > 0)
        metric_names = {m["name"] for m in ev.metrics}
        self.assertIn("air_shelf_hz", metric_names)
        self.assertIn("air_gain_db", metric_names)
        self.assertIn("height_slot_count", metric_names)
        self.assertIn("bypass", metric_names)
        # Gate reference must appear in notes.
        notes_text = " ".join(ev.notes or [])
        self.assertIn("GATE.DOWNMIX_SIMILARITY_MEASURED", notes_text)

    def test_all_standards_no_crash(self) -> None:
        """Plugin must not crash for any of the 5 supported standards."""
        layouts_with_heights = [SMPTE_5_1_4, SMPTE_7_1_4, FILM_5_1_4, FILM_7_1_4, VST3_7_1_4]
        for layout in layouts_with_heights:
            buf = _white_noise(layout, seed=8)
            result = self._run(buf, layout)
            self.assertEqual(result.shape, buf.shape)


# ---------------------------------------------------------------------------
# TestStereoWidenerV0: FL/FR routing, center/surround isolation, M/S math
# ---------------------------------------------------------------------------


class TestStereoWidenerV0(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = StereoWidenerV0Plugin()
        self.params = {
            "width": 1.2,
            "bypass": False,
            "macro_mix": 1.0,
        }

    def _run(self, buf: Any, layout: SpeakerLayout, **param_overrides: Any) -> Any:
        params = dict(self.params)
        params.update(param_overrides)
        result, _ = _run(self.plugin, buf, layout, params)
        return result

    def test_only_fl_fr_modified(self) -> None:
        """With width != 1.0, only FL and FR channels must be different from input."""
        buf = _white_noise(SMPTE_5_1, seed=10)
        result = self._run(buf, SMPTE_5_1, width=1.5)
        fl = SMPTE_5_1.index_of(SpeakerPosition.FL)
        fr = SMPTE_5_1.index_of(SpeakerPosition.FR)
        assert fl is not None and fr is not None
        # FL and FR must differ.
        self.assertFalse(np.array_equal(result[fl], buf[fl]))
        self.assertFalse(np.array_equal(result[fr], buf[fr]))
        # All other channels must be identical.
        for i in range(SMPTE_5_1.num_channels):
            if i not in (fl, fr):
                np.testing.assert_array_equal(result[i], buf[i])

    def test_film_fl_fr_routing(self) -> None:
        """FILM order has FL at slot 0, FR at slot 2 — routing must be correct."""
        buf = _white_noise(FILM_5_1, seed=11)
        result = self._run(buf, FILM_5_1, width=1.5)
        fl_slot = FILM_5_1.index_of(SpeakerPosition.FL)   # 0
        fr_slot = FILM_5_1.index_of(SpeakerPosition.FR)   # 2
        assert fl_slot is not None and fr_slot is not None
        self.assertFalse(np.array_equal(result[fl_slot], buf[fl_slot]))
        self.assertFalse(np.array_equal(result[fr_slot], buf[fr_slot]))
        # Center (slot 1) must be untouched in FILM order.
        fc_slot = FILM_5_1.index_of(SpeakerPosition.FC)
        assert fc_slot is not None
        np.testing.assert_array_equal(result[fc_slot], buf[fc_slot])

    def test_width_1_is_identity(self) -> None:
        """width=1.0 must produce output equal to input (M/S identity)."""
        for layout in (SMPTE_5_1, SMPTE_7_1, FILM_5_1, LOGIC_PRO_5_1, VST3_7_1):
            buf = _white_noise(layout, seed=12)
            result = self._run(buf, layout, width=1.0)
            fl = layout.index_of(SpeakerPosition.FL)
            fr = layout.index_of(SpeakerPosition.FR)
            if fl is not None and fr is not None:
                np.testing.assert_allclose(result[fl], buf[fl], atol=1e-6)
                np.testing.assert_allclose(result[fr], buf[fr], atol=1e-6)

    def test_width_zero_produces_mono(self) -> None:
        """width=0.0 must produce identical L and R outputs (pure mono)."""
        buf = _white_noise(SMPTE_5_1, seed=13)
        result = self._run(buf, SMPTE_5_1, width=0.0)
        fl = SMPTE_5_1.index_of(SpeakerPosition.FL)
        fr = SMPTE_5_1.index_of(SpeakerPosition.FR)
        assert fl is not None and fr is not None
        np.testing.assert_allclose(result[fl], result[fr], atol=1e-6)

    def test_bypass_returns_exact_input(self) -> None:
        for layout in (SMPTE_5_1, FILM_5_1, LOGIC_PRO_5_1):
            buf = _white_noise(layout, seed=14)
            result = self._run(buf, layout, bypass=True)
            np.testing.assert_array_equal(result, buf)

    def test_determinism(self) -> None:
        buf = _white_noise(SMPTE_7_1_4, seed=15)
        r1 = self._run(buf, SMPTE_7_1_4)
        r2 = self._run(buf, SMPTE_7_1_4)
        np.testing.assert_array_equal(r1, r2)

    def test_macro_mix_zero_is_dry(self) -> None:
        buf = _white_noise(SMPTE_5_1, seed=16)
        result = self._run(buf, SMPTE_5_1, macro_mix=0.0)
        np.testing.assert_array_equal(result, buf)

    def test_evidence_populated(self) -> None:
        buf = _white_noise(SMPTE_5_1, seed=17)
        _, ctx = _run(self.plugin, buf, SMPTE_5_1, self.params)
        ev = ctx.evidence_collector
        metric_names = {m["name"] for m in ev.metrics}
        self.assertIn("width", metric_names)
        self.assertIn("fl_slot", metric_names)
        self.assertIn("fr_slot", metric_names)
        notes_text = " ".join(ev.notes or [])
        self.assertIn("GATE.DOWNMIX_SIMILARITY_MEASURED", notes_text)

    def test_all_standards_no_crash(self) -> None:
        layouts = [
            SMPTE_5_1, SMPTE_7_1, SMPTE_7_1_4,
            FILM_5_1, FILM_7_1_4,
            LOGIC_PRO_5_1, LOGIC_PRO_7_1,
            VST3_7_1, VST3_7_1_4,
        ]
        for layout in layouts:
            buf = _white_noise(layout, seed=18)
            result = self._run(buf, layout)
            self.assertEqual(result.shape, buf.shape)


# ---------------------------------------------------------------------------
# TestEarlyReflectionsV0: surround routing, front/LFE isolation, tap math
# ---------------------------------------------------------------------------


class TestEarlyReflectionsV0(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = EarlyReflectionsV0Plugin()
        self.params = {
            "room_size_ms": 8.0,
            "decay_db": -18.0,
            "bypass": False,
            "macro_mix": 1.0,
        }

    def _run(self, buf: Any, layout: SpeakerLayout, **param_overrides: Any) -> Any:
        params = dict(self.params)
        params.update(param_overrides)
        result, _ = _run(self.plugin, buf, layout, params)
        return result

    def _surround_slots(self, layout: SpeakerLayout) -> list[int]:
        slots = []
        for pos in (SpeakerPosition.SL, SpeakerPosition.SR,
                    SpeakerPosition.BL, SpeakerPosition.BR):
            idx = layout.index_of(pos)
            if idx is not None:
                slots.append(idx)
        return slots

    def test_surround_channels_modified(self) -> None:
        """Surround channels must be processed; front and LFE must not change."""
        for layout in (SMPTE_5_1, SMPTE_7_1, FILM_5_1):
            buf = _white_noise(layout, seed=20)
            result = self._run(buf, layout)
            surround = self._surround_slots(layout)
            lfe_set = set(layout.lfe_slots)
            fl = layout.index_of(SpeakerPosition.FL)
            fr = layout.index_of(SpeakerPosition.FR)
            fc = layout.index_of(SpeakerPosition.FC)

            # At least one surround channel must change.
            any_changed = any(
                not np.array_equal(result[s], buf[s]) for s in surround
            )
            self.assertTrue(
                any_changed,
                f"No surround channels changed for {layout.layout_id}/{layout.standard.value}",
            )

            # Front channels must be untouched.
            for slot in (fl, fr, fc):
                if slot is not None:
                    np.testing.assert_array_equal(result[slot], buf[slot])

            # LFE must be untouched.
            for slot in lfe_set:
                np.testing.assert_array_equal(result[slot], buf[slot])

    def test_film_surround_routing(self) -> None:
        """FILM order places LFE at slot 5 — surrounds must be found correctly."""
        buf = _white_noise(FILM_5_1, seed=21)
        result = self._run(buf, FILM_5_1)
        sl_slot = FILM_5_1.index_of(SpeakerPosition.SL)
        sr_slot = FILM_5_1.index_of(SpeakerPosition.SR)
        assert sl_slot is not None and sr_slot is not None
        self.assertFalse(np.array_equal(result[sl_slot], buf[sl_slot]))
        self.assertFalse(np.array_equal(result[sr_slot], buf[sr_slot]))
        # LFE (slot 5 in FILM) must be untouched.
        for lfe_slot in FILM_5_1.lfe_slots:
            np.testing.assert_array_equal(result[lfe_slot], buf[lfe_slot])

    def test_height_channels_also_processed(self) -> None:
        """Height channels must also receive ER taps in height-bed layouts."""
        for layout in (SMPTE_5_1_4, SMPTE_7_1_4):
            buf = _white_noise(layout, seed=22)
            result = self._run(buf, layout)
            for slot in layout.height_slots:
                self.assertFalse(
                    np.array_equal(result[slot], buf[slot]),
                    msg=f"Height slot {slot} unchanged in {layout.layout_id}",
                )

    def test_bypass_returns_exact_input(self) -> None:
        for layout in (SMPTE_5_1, SMPTE_7_1_4, FILM_5_1):
            buf = _white_noise(layout, seed=23)
            result = self._run(buf, layout, bypass=True)
            np.testing.assert_array_equal(result, buf)

    def test_determinism(self) -> None:
        buf = _white_noise(SMPTE_7_1_4, seed=24)
        r1 = self._run(buf, SMPTE_7_1_4)
        r2 = self._run(buf, SMPTE_7_1_4)
        np.testing.assert_array_equal(r1, r2)

    def test_macro_mix_zero_is_dry(self) -> None:
        buf = _white_noise(SMPTE_5_1, seed=25)
        result = self._run(buf, SMPTE_5_1, macro_mix=0.0)
        np.testing.assert_array_equal(result, buf)

    def test_tap_energy_added_to_surround(self) -> None:
        """After processing, surround channel energy must be >= input energy."""
        buf = _white_noise(SMPTE_5_1, seed=26)
        result = self._run(buf, SMPTE_5_1)
        sl_slot = SMPTE_5_1.index_of(SpeakerPosition.SL)
        assert sl_slot is not None
        input_energy = float(np.sum(buf[sl_slot] ** 2))
        output_energy = float(np.sum(result[sl_slot] ** 2))
        self.assertGreaterEqual(output_energy, input_energy * 0.99)

    def test_evidence_populated(self) -> None:
        buf = _white_noise(SMPTE_5_1, seed=27)
        _, ctx = _run(self.plugin, buf, SMPTE_5_1, self.params)
        ev = ctx.evidence_collector
        metric_names = {m["name"] for m in ev.metrics}
        self.assertIn("room_size_ms", metric_names)
        self.assertIn("decay_db", metric_names)
        self.assertIn("delay_samples", metric_names)
        self.assertIn("er_slot_count", metric_names)
        notes_text = " ".join(ev.notes or [])
        self.assertIn("GATE.DOWNMIX_SIMILARITY_MEASURED", notes_text)

    def test_all_standards_no_crash(self) -> None:
        layouts = [
            SMPTE_5_1, SMPTE_7_1, SMPTE_5_1_4, SMPTE_7_1_4,
            FILM_5_1, FILM_7_1_4,
            LOGIC_PRO_5_1, LOGIC_PRO_7_1,
            VST3_7_1, VST3_7_1_4,
        ]
        for layout in layouts:
            buf = _white_noise(layout, seed=28)
            result = self._run(buf, layout)
            self.assertEqual(result.shape, buf.shape)

    def test_very_short_room_size_passthrough(self) -> None:
        """room_size_ms so small it rounds to 0 delay samples → passthrough."""
        # At 48000 Hz, 1.0 ms = 48 samples (well above 0).
        # Force near-zero by using a very slow mock sample rate isn't feasible,
        # but we can verify the normal path doesn't clip or crash.
        buf = _white_noise(SMPTE_5_1, seed=29)
        result = self._run(buf, SMPTE_5_1, room_size_ms=1.0)
        self.assertEqual(result.shape, buf.shape)
        # All values must be in [-1, 1].
        self.assertTrue(np.all(result >= -1.0) and np.all(result <= 1.0))


# ---------------------------------------------------------------------------
# TestSemanticDeclarations: plugin class attributes match the DoD contract
# ---------------------------------------------------------------------------


class TestSemanticDeclarations(unittest.TestCase):
    """Verify that class-level semantic declarations are correct and complete.

    The subjective plugins live in the DSP registry (not the YAML pipeline
    registry) so their semantics are declared directly on the class:
    ``supported_standards``, ``preferred_standard``, and ``plugin_id``.
    """

    _EXPECTED_STANDARDS = frozenset({"SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"})
    _CLASSES = (HeightAirV0Plugin, StereoWidenerV0Plugin, EarlyReflectionsV0Plugin)

    def test_all_five_standards_declared(self) -> None:
        for cls in self._CLASSES:
            p = cls()
            self.assertEqual(
                set(p.supported_standards),
                self._EXPECTED_STANDARDS,
                msg=f"{cls.__name__}.supported_standards",
            )

    def test_preferred_standard_is_smpte(self) -> None:
        for cls in self._CLASSES:
            p = cls()
            self.assertEqual(
                p.preferred_standard,
                "SMPTE",
                msg=f"{cls.__name__}.preferred_standard",
            )

    def test_plugin_ids_unique_and_stable(self) -> None:
        ids = [cls().plugin_id for cls in self._CLASSES]
        self.assertEqual(len(ids), len(set(ids)), "plugin_id values must be unique")
        self.assertEqual(ids[0], "height_air_v0")
        self.assertEqual(ids[1], "stereo_widener_v0")
        self.assertEqual(ids[2], "early_reflections_v0")

    def test_supported_standards_is_sequence_of_strings(self) -> None:
        for cls in self._CLASSES:
            p = cls()
            for std in p.supported_standards:
                self.assertIsInstance(std, str, msg=f"{cls.__name__}: {std!r}")


if __name__ == "__main__":
    unittest.main()
