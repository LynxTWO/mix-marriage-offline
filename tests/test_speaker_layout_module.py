"""Tests for mmo.core.speaker_layout: SpeakerPosition, LayoutStandard, SpeakerLayout,
preset constants, remap_channels_fill, and edge cases.

Covers:
- SpeakerPosition enum: completeness, str-enum behaviour, value format.
- LayoutStandard enum: all required standards present.
- SpeakerLayout preset constants: channel counts, LFE pinning, slot semantics.
- get_preset(): lookup by layout_id × standard.
- remap_channels_fill(): zero-fill for missing channels, identity fast path,
  list/tuple/NumPy support, LFE pinning, height isolation.
- Edge cases: 2.1 → 5.1 upmix, 7.1.4 → 5.1 downmix (height fold),
  SMPTE ↔ Film round-trip, LOGIC_PRO / VST3 → SMPTE round-trip.
- Regression fixtures: pinned SMPTE and Film slot assignments.

Determinism guarantee: all assertions produce the same result on repeated runs.
"""

from __future__ import annotations

import unittest

from mmo.core.speaker_layout import (
    FILM_2_0,
    FILM_2_1,
    FILM_5_1,
    FILM_5_1_2,
    FILM_5_1_4,
    FILM_7_1,
    FILM_7_1_2,
    FILM_7_1_4,
    LOGIC_PRO_5_1,
    LOGIC_PRO_7_1,
    SMPTE_2_0,
    SMPTE_2_1,
    SMPTE_5_1,
    SMPTE_5_1_2,
    SMPTE_5_1_4,
    SMPTE_7_1,
    SMPTE_7_1_2,
    SMPTE_7_1_4,
    VST3_7_1,
    VST3_7_1_4,
    LayoutStandard,
    SpeakerLayout,
    SpeakerPosition,
    get_preset,
    remap_channels_fill,
)


# ---------------------------------------------------------------------------
# TestSpeakerPositionEnum
# ---------------------------------------------------------------------------


class TestSpeakerPositionEnum(unittest.TestCase):
    """SpeakerPosition enum correctness and str-enum semantics."""

    def test_required_positions_exist(self) -> None:
        """All positions required by SMPTE 7.1.4 and Film 7.1.4 must be present."""
        required = {
            "FL", "FR", "FC", "LFE", "LFE2",
            "SL", "SR",     # side surrounds
            "BL", "BR",     # rear/back surrounds
            "TFL", "TFR",   # top front heights
            "TBL", "TBR",   # top back heights
            "M",            # mono
        }
        names = {pos.name for pos in SpeakerPosition}
        for name in required:
            self.assertIn(name, names, f"SpeakerPosition.{name} is missing")

    def test_future_placeholder_positions_exist(self) -> None:
        """Placeholder positions for 7.1.6 / 9.1.6 must be present."""
        for name in ("TFC", "TBC", "TC"):
            self.assertIn(
                name,
                {pos.name for pos in SpeakerPosition},
                f"Future placeholder SpeakerPosition.{name} missing",
            )

    def test_values_are_spk_ids(self) -> None:
        """All values must match the SPK.* ontology ID format."""
        for pos in SpeakerPosition:
            self.assertTrue(
                pos.value.startswith("SPK."),
                f"SpeakerPosition.{pos.name} value {pos.value!r} must start with 'SPK.'",
            )

    def test_str_enum_equality(self) -> None:
        """Enum members must compare equal to their string values."""
        self.assertEqual(SpeakerPosition.FL, "SPK.L")
        self.assertEqual(SpeakerPosition.FR, "SPK.R")
        self.assertEqual(SpeakerPosition.FC, "SPK.C")
        self.assertEqual(SpeakerPosition.LFE, "SPK.LFE")
        self.assertEqual(SpeakerPosition.LFE2, "SPK.LFE2")
        self.assertEqual(SpeakerPosition.SL, "SPK.LS")
        self.assertEqual(SpeakerPosition.SR, "SPK.RS")
        self.assertEqual(SpeakerPosition.BL, "SPK.LRS")
        self.assertEqual(SpeakerPosition.BR, "SPK.RRS")
        self.assertEqual(SpeakerPosition.TFL, "SPK.TFL")
        self.assertEqual(SpeakerPosition.TFR, "SPK.TFR")
        self.assertEqual(SpeakerPosition.TBL, "SPK.TRL")
        self.assertEqual(SpeakerPosition.TBR, "SPK.TRR")

    def test_symmetric_equality(self) -> None:
        """String == enum must also be True."""
        self.assertEqual("SPK.L", SpeakerPosition.FL)
        self.assertEqual("SPK.LFE", SpeakerPosition.LFE)
        self.assertEqual("SPK.LFE2", SpeakerPosition.LFE2)

    def test_no_duplicate_values(self) -> None:
        """No two positions may map to the same SPK.* ID."""
        values = [pos.value for pos in SpeakerPosition]
        self.assertEqual(len(values), len(set(values)), "Duplicate SPK.* values in SpeakerPosition")

    def test_lfe_is_not_fl_or_fr(self) -> None:
        """LFE must be a distinct position from any program channel."""
        self.assertNotEqual(SpeakerPosition.LFE, SpeakerPosition.FL)
        self.assertNotEqual(SpeakerPosition.LFE, SpeakerPosition.FR)
        self.assertNotEqual(SpeakerPosition.LFE, SpeakerPosition.FC)
        self.assertNotEqual(SpeakerPosition.LFE2, SpeakerPosition.FL)
        self.assertNotEqual(SpeakerPosition.LFE2, SpeakerPosition.FR)
        self.assertNotEqual(SpeakerPosition.LFE2, SpeakerPosition.FC)
        self.assertNotEqual(SpeakerPosition.LFE2, SpeakerPosition.LFE)


# ---------------------------------------------------------------------------
# TestLayoutStandardEnum
# ---------------------------------------------------------------------------


class TestLayoutStandardEnum(unittest.TestCase):
    """LayoutStandard enum correctness."""

    def test_required_standards_exist(self) -> None:
        names = {std.name for std in LayoutStandard}
        for required in ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"):
            self.assertIn(required, names, f"LayoutStandard.{required} missing")

    def test_str_enum_equality(self) -> None:
        self.assertEqual(LayoutStandard.SMPTE, "SMPTE")
        self.assertEqual(LayoutStandard.FILM, "FILM")
        self.assertEqual(LayoutStandard.LOGIC_PRO, "LOGIC_PRO")
        self.assertEqual(LayoutStandard.VST3, "VST3")

    def test_default_is_smpte(self) -> None:
        """SMPTE is canonical; its string value must be 'SMPTE'."""
        self.assertEqual(LayoutStandard.SMPTE.value, "SMPTE")


# ---------------------------------------------------------------------------
# TestSpeakerLayoutDataclass
# ---------------------------------------------------------------------------


class TestSpeakerLayoutDataclass(unittest.TestCase):
    """SpeakerLayout dataclass interface."""

    def test_num_channels(self) -> None:
        self.assertEqual(SMPTE_2_0.num_channels, 2)
        self.assertEqual(SMPTE_5_1.num_channels, 6)
        self.assertEqual(SMPTE_7_1.num_channels, 8)
        self.assertEqual(SMPTE_7_1_4.num_channels, 12)

    def test_index_of_fl(self) -> None:
        self.assertEqual(SMPTE_5_1.index_of(SpeakerPosition.FL), 0)
        self.assertEqual(FILM_5_1.index_of(SpeakerPosition.FL), 0)

    def test_index_of_lfe_smpte_51(self) -> None:
        """LFE is at slot 3 in SMPTE 5.1 (L=0 R=1 C=2 LFE=3 Ls=4 Rs=5)."""
        self.assertEqual(SMPTE_5_1.index_of(SpeakerPosition.LFE), 3)

    def test_index_of_lfe_film_51(self) -> None:
        """LFE is at slot 5 (last) in Film 5.1 (L=0 C=1 R=2 Ls=3 Rs=4 LFE=5)."""
        self.assertEqual(FILM_5_1.index_of(SpeakerPosition.LFE), 5)

    def test_index_of_absent_returns_none(self) -> None:
        """Stereo layout has no center channel."""
        self.assertIsNone(SMPTE_2_0.index_of(SpeakerPosition.FC))

    def test_is_lfe_channel(self) -> None:
        lfe_slot = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        self.assertTrue(SMPTE_5_1.is_lfe_channel(lfe_slot))
        self.assertFalse(SMPTE_5_1.is_lfe_channel(0))  # FL is not LFE

    def test_lfe_slots_property(self) -> None:
        self.assertEqual(SMPTE_5_1.lfe_slots, [3])
        self.assertEqual(FILM_5_1.lfe_slots, [5])
        self.assertEqual(SMPTE_2_0.lfe_slots, [])

    def test_dual_lfe_slots_include_lfe2(self) -> None:
        dual = SpeakerLayout(
            "LAYOUT.TEST.5_2",
            LayoutStandard.SMPTE,
            (
                SpeakerPosition.FL,
                SpeakerPosition.FR,
                SpeakerPosition.FC,
                SpeakerPosition.LFE,
                SpeakerPosition.LFE2,
                SpeakerPosition.SL,
                SpeakerPosition.SR,
            ),
        )
        self.assertEqual(dual.lfe_slots, [3, 4])
        self.assertTrue(dual.is_lfe_channel(3))
        self.assertTrue(dual.is_lfe_channel(4))

    def test_height_slots_property(self) -> None:
        self.assertEqual(SMPTE_5_1.height_slots, [])
        self.assertEqual(SMPTE_7_1_4.height_slots, [8, 9, 10, 11])
        self.assertEqual(SMPTE_5_1_2.height_slots, [6, 7])

    def test_frozen_immutable(self) -> None:
        with self.assertRaises((AttributeError, TypeError)):
            SMPTE_5_1.layout_id = "LAYOUT.CHANGED"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPresetConstants — pinned regression fixtures
# ---------------------------------------------------------------------------


class TestPresetConstants(unittest.TestCase):
    """Pinned slot assignments for SMPTE and Film presets."""

    # ---- SMPTE fixtures ----
    _SMPTE_51_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
    )
    _SMPTE_71_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
    )
    _SMPTE_714_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    )
    # ---- Film fixtures ----
    _FILM_51_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR, SpeakerPosition.LFE,
    )
    _FILM_71_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.LFE,
    )
    _FILM_714_ORDER = (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR, SpeakerPosition.LFE,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    )

    def test_smpte_51_channel_order(self) -> None:
        self.assertEqual(SMPTE_5_1.channel_order, self._SMPTE_51_ORDER)

    def test_smpte_71_channel_order(self) -> None:
        self.assertEqual(SMPTE_7_1.channel_order, self._SMPTE_71_ORDER)

    def test_smpte_714_channel_order(self) -> None:
        self.assertEqual(SMPTE_7_1_4.channel_order, self._SMPTE_714_ORDER)

    def test_film_51_channel_order(self) -> None:
        self.assertEqual(FILM_5_1.channel_order, self._FILM_51_ORDER)

    def test_film_71_channel_order(self) -> None:
        self.assertEqual(FILM_7_1.channel_order, self._FILM_71_ORDER)

    def test_film_714_channel_order(self) -> None:
        self.assertEqual(FILM_7_1_4.channel_order, self._FILM_714_ORDER)

    def test_smpte_and_film_51_same_speakers_different_order(self) -> None:
        self.assertEqual(set(SMPTE_5_1.channel_order), set(FILM_5_1.channel_order))
        self.assertNotEqual(SMPTE_5_1.channel_order, FILM_5_1.channel_order)

    def test_smpte_and_film_714_same_speakers_different_order(self) -> None:
        self.assertEqual(set(SMPTE_7_1_4.channel_order), set(FILM_7_1_4.channel_order))
        self.assertNotEqual(SMPTE_7_1_4.channel_order, FILM_7_1_4.channel_order)

    def test_lfe_at_slot3_smpte_51(self) -> None:
        self.assertEqual(SMPTE_5_1.channel_order[3], SpeakerPosition.LFE)

    def test_lfe_at_last_slot_film_51(self) -> None:
        self.assertEqual(FILM_5_1.channel_order[-1], SpeakerPosition.LFE)

    def test_lfe_at_last_slot_film_71(self) -> None:
        self.assertEqual(FILM_7_1.channel_order[-1], SpeakerPosition.LFE)

    def test_heights_at_slots_8_to_11_smpte_714(self) -> None:
        heights = {SpeakerPosition.TFL, SpeakerPosition.TFR, SpeakerPosition.TBL, SpeakerPosition.TBR}
        for slot in range(8, 12):
            self.assertIn(SMPTE_7_1_4.channel_order[slot], heights)

    def test_logic_pro_51_order(self) -> None:
        """Logic Pro 5.1: L R Ls Rs C LFE."""
        expected = (
            SpeakerPosition.FL, SpeakerPosition.FR,
            SpeakerPosition.SL, SpeakerPosition.SR,
            SpeakerPosition.FC, SpeakerPosition.LFE,
        )
        self.assertEqual(LOGIC_PRO_5_1.channel_order, expected)

    def test_logic_pro_71_order(self) -> None:
        """Logic Pro 7.1: L R Lrs Rrs Ls Rs C LFE."""
        expected = (
            SpeakerPosition.FL, SpeakerPosition.FR,
            SpeakerPosition.BL, SpeakerPosition.BR,
            SpeakerPosition.SL, SpeakerPosition.SR,
            SpeakerPosition.FC, SpeakerPosition.LFE,
        )
        self.assertEqual(LOGIC_PRO_7_1.channel_order, expected)

    def test_vst3_71_order(self) -> None:
        """VST3 7.1: L R C LFE Lrs Rrs Lss Rss (rears before sides)."""
        expected = (
            SpeakerPosition.FL, SpeakerPosition.FR,
            SpeakerPosition.FC, SpeakerPosition.LFE,
            SpeakerPosition.BL, SpeakerPosition.BR,   # rears at slots 4-5
            SpeakerPosition.SL, SpeakerPosition.SR,   # sides at slots 6-7
        )
        self.assertEqual(VST3_7_1.channel_order, expected)

    def test_vst3_714_order(self) -> None:
        """VST3 7.1.4: L R C LFE Lrs Rrs Lss Rss TFL TFR TBL TBR."""
        expected = (
            SpeakerPosition.FL, SpeakerPosition.FR,
            SpeakerPosition.FC, SpeakerPosition.LFE,
            SpeakerPosition.BL, SpeakerPosition.BR,
            SpeakerPosition.SL, SpeakerPosition.SR,
            SpeakerPosition.TFL, SpeakerPosition.TFR,
            SpeakerPosition.TBL, SpeakerPosition.TBR,
        )
        self.assertEqual(VST3_7_1_4.channel_order, expected)

    def test_vst3_and_smpte_714_differ_at_surround_slots(self) -> None:
        """VST3 and SMPTE 7.1.4 must differ at surround slots 4-7."""
        self.assertNotEqual(SMPTE_7_1_4.channel_order[4:8], VST3_7_1_4.channel_order[4:8])

    def test_vst3_and_smpte_714_same_heights(self) -> None:
        """VST3 and SMPTE 7.1.4 heights (slots 8-11) must be the same."""
        self.assertEqual(SMPTE_7_1_4.channel_order[8:12], VST3_7_1_4.channel_order[8:12])


# ---------------------------------------------------------------------------
# TestGetPreset
# ---------------------------------------------------------------------------


class TestGetPreset(unittest.TestCase):
    """get_preset() lookup table."""

    def test_smpte_51_lookup(self) -> None:
        result = get_preset("LAYOUT.5_1", "SMPTE")
        self.assertIs(result, SMPTE_5_1)

    def test_film_714_lookup(self) -> None:
        result = get_preset("LAYOUT.7_1_4", "FILM")
        self.assertIs(result, FILM_7_1_4)

    def test_logic_pro_51_lookup(self) -> None:
        result = get_preset("LAYOUT.5_1", LayoutStandard.LOGIC_PRO)
        self.assertIs(result, LOGIC_PRO_5_1)

    def test_vst3_714_lookup(self) -> None:
        result = get_preset("LAYOUT.7_1_4", LayoutStandard.VST3)
        self.assertIs(result, VST3_7_1_4)

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(get_preset("LAYOUT.9_1_6", "SMPTE"))

    def test_case_insensitive_standard_str(self) -> None:
        result = get_preset("LAYOUT.5_1", "smpte")
        self.assertIs(result, SMPTE_5_1)


# ---------------------------------------------------------------------------
# TestRemapChannelsFill
# ---------------------------------------------------------------------------


class TestRemapChannelsFill(unittest.TestCase):
    """remap_channels_fill() correctness, edge cases, and type handling."""

    # ---- Identity fast path ----

    def test_identity_same_layout_object_list(self) -> None:
        data = [0, 1, 2, 3, 4, 5]
        result = remap_channels_fill(data, SMPTE_5_1, SMPTE_5_1)
        self.assertIs(result, data)  # exactly the same object

    def test_identity_same_layout_object_tuple(self) -> None:
        data = (0, 1, 2, 3, 4, 5)
        result = remap_channels_fill(data, SMPTE_5_1, SMPTE_5_1)
        self.assertIs(result, data)

    # ---- Length validation ----

    def test_wrong_length_raises(self) -> None:
        with self.assertRaises(ValueError):
            remap_channels_fill([1, 2, 3], SMPTE_5_1, FILM_5_1)

    # ---- SMPTE ↔ Film 5.1 ----

    def test_smpte_to_film_51_list(self) -> None:
        # SMPTE: L=0 R=1 C=2 LFE=3 Ls=4 Rs=5
        # Film:  L=0 C=1 R=2 Ls=3 Rs=4 LFE=5
        data = [10, 20, 30, 40, 50, 60]  # L R C LFE Ls Rs
        result = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        # Expected Film order: [L(10), C(30), R(20), Ls(50), Rs(60), LFE(40)]
        self.assertEqual(list(result), [10, 30, 20, 50, 60, 40])

    def test_film_to_smpte_51_list(self) -> None:
        # Inverse of above
        data = [10, 30, 20, 50, 60, 40]  # Film order
        result = remap_channels_fill(data, FILM_5_1, SMPTE_5_1)
        self.assertEqual(list(result), [10, 20, 30, 40, 50, 60])

    def test_smpte_to_film_51_tuple(self) -> None:
        data = (0, 1, 2, 3, 4, 5)
        result = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, (0, 2, 1, 4, 5, 3))

    def test_returns_list_for_list_input(self) -> None:
        data = [0, 1, 2, 3, 4, 5]
        result = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        self.assertIsInstance(result, list)

    # ---- Zero-fill (upmix) ----

    def test_stereo_to_51_zero_fills_new_channels(self) -> None:
        """2.0 → 5.1: FC, LFE, SL, SR are zero-filled; FL and FR are preserved."""
        data = [100, 200]  # L R
        result = remap_channels_fill(data, SMPTE_2_0, SMPTE_5_1)
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0], 100)  # FL preserved
        self.assertEqual(result[1], 200)  # FR preserved
        self.assertEqual(result[2], 0.0)  # FC zero-filled
        self.assertEqual(result[3], 0.0)  # LFE zero-filled
        self.assertEqual(result[4], 0.0)  # SL zero-filled
        self.assertEqual(result[5], 0.0)  # SR zero-filled

    def test_21_to_51_lfe_is_pinned_to_lfe_slot(self) -> None:
        """2.1 → 5.1: LFE must land at the LFE slot (slot 3 in SMPTE 5.1).
        LFE MUST NEVER be promoted to program audio channels.
        """
        data = [100, 200, 999]  # L R LFE
        result = remap_channels_fill(data, SMPTE_2_1, SMPTE_5_1)
        lfe_dst_slot = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        self.assertIsNotNone(lfe_dst_slot)
        self.assertEqual(result[lfe_dst_slot], 999, "LFE content must land at LFE slot")
        # No program channel should contain 999
        for i, val in enumerate(result):
            if i != lfe_dst_slot:
                self.assertNotEqual(val, 999, f"LFE content leaked to non-LFE slot {i}")

    def test_custom_fill_value(self) -> None:
        """fill_value=float('nan') lets callers detect accidental fills in tests."""
        import math
        data = [1.0, 2.0]
        result = remap_channels_fill(data, SMPTE_2_0, SMPTE_5_1, fill_value=float("nan"))
        self.assertTrue(math.isnan(result[2]), "FC should be NaN fill")
        self.assertTrue(math.isnan(result[3]), "LFE should be NaN fill")

    # ---- Downmix subset (no zero-fill needed; channels simply absent) ----

    def test_51_to_20_only_fl_fr_survive(self) -> None:
        """5.1 → 2.0: only FL and FR are present in the target; others are not filled."""
        data = [10, 20, 30, 40, 50, 60]
        result = remap_channels_fill(data, SMPTE_5_1, SMPTE_2_0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 10)  # FL
        self.assertEqual(result[1], 20)  # FR

    # ---- Height isolation ----

    def test_714_to_51_heights_absent_in_output(self) -> None:
        """7.1.4 → 5.1: height channels have no slots in 5.1; they must not appear."""
        data = list(range(12))
        result = remap_channels_fill(data, SMPTE_7_1_4, SMPTE_5_1)
        self.assertEqual(len(result), 6)
        # The 6 channels in the output are the 5.1 bed from 7.1.4
        lfe_dst = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        lfe_src = SMPTE_7_1_4.index_of(SpeakerPosition.LFE)
        self.assertEqual(result[lfe_dst], data[lfe_src])  # LFE preserved

    def test_714_to_51_height_content_never_in_lfe(self) -> None:
        """7.1.4 → 5.1: height channel data must NEVER appear in the LFE output slot.
        This guards against the fold-to-LFE bug where TFL/TFR get dumped into LFE.
        """
        # Give height channels a sentinel value
        data = [0.0] * 12
        height_sentinel = 9999.0
        for slot in SMPTE_7_1_4.height_slots:
            data[slot] = height_sentinel
        result = remap_channels_fill(data, SMPTE_7_1_4, SMPTE_5_1)
        lfe_dst = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        self.assertNotEqual(result[lfe_dst], height_sentinel, "Height content must NOT appear in LFE slot")

    # ---- LOGIC_PRO ↔ SMPTE round-trip ----

    def test_logic_pro_51_to_smpte_51(self) -> None:
        """Logic Pro → SMPTE 5.1: channels must be correctly reordered."""
        # Logic Pro 5.1: L R Ls Rs C LFE
        data = [10, 20, 50, 60, 30, 40]
        result = remap_channels_fill(data, LOGIC_PRO_5_1, SMPTE_5_1)
        # SMPTE 5.1: L R C LFE Ls Rs
        self.assertEqual(result[0], 10)  # FL
        self.assertEqual(result[1], 20)  # FR
        self.assertEqual(result[2], 30)  # FC
        self.assertEqual(result[3], 40)  # LFE — must be at LFE slot
        self.assertEqual(result[4], 50)  # SL
        self.assertEqual(result[5], 60)  # SR

    def test_logic_pro_51_roundtrip_via_smpte(self) -> None:
        """LOGIC_PRO → SMPTE → LOGIC_PRO is identity."""
        original = [10, 20, 30, 40, 50, 60]
        smpte = remap_channels_fill(original, LOGIC_PRO_5_1, SMPTE_5_1)
        back = remap_channels_fill(smpte, SMPTE_5_1, LOGIC_PRO_5_1)
        self.assertEqual(list(back), original)

    def test_logic_pro_71_lfe_at_last_slot(self) -> None:
        """Logic Pro 7.1: LFE is at the last slot (slot 7)."""
        self.assertEqual(LOGIC_PRO_7_1.index_of(SpeakerPosition.LFE), 7)

    def test_logic_pro_71_to_smpte_71(self) -> None:
        """Logic Pro 7.1 → SMPTE 7.1: all 8 channels correctly routed."""
        # Logic Pro 7.1: L R Lrs Rrs Ls Rs C LFE
        data = [10, 20, 70, 80, 50, 60, 30, 40]
        result = remap_channels_fill(data, LOGIC_PRO_7_1, SMPTE_7_1)
        # SMPTE 7.1: L R C LFE Ls Rs Lrs Rrs
        self.assertEqual(result[0], 10)  # FL
        self.assertEqual(result[1], 20)  # FR
        self.assertEqual(result[2], 30)  # FC
        self.assertEqual(result[3], 40)  # LFE at slot 3
        self.assertEqual(result[4], 50)  # SL
        self.assertEqual(result[5], 60)  # SR
        self.assertEqual(result[6], 70)  # BL (Lrs)
        self.assertEqual(result[7], 80)  # BR (Rrs)

    # ---- VST3 ↔ SMPTE round-trip ----

    def test_vst3_71_to_smpte_71(self) -> None:
        """VST3 7.1 → SMPTE 7.1: surround slots corrected."""
        # VST3 7.1: L R C LFE Lrs Rrs Lss Rss
        data = [10, 20, 30, 40, 70, 80, 50, 60]
        result = remap_channels_fill(data, VST3_7_1, SMPTE_7_1)
        # SMPTE 7.1: L R C LFE Ls Rs Lrs Rrs
        self.assertEqual(result[0], 10)  # FL
        self.assertEqual(result[1], 20)  # FR
        self.assertEqual(result[2], 30)  # FC
        self.assertEqual(result[3], 40)  # LFE
        self.assertEqual(result[4], 50)  # SL (was at VST3 slot 6)
        self.assertEqual(result[5], 60)  # SR
        self.assertEqual(result[6], 70)  # BL (was at VST3 slot 4)
        self.assertEqual(result[7], 80)  # BR

    def test_vst3_714_roundtrip_via_smpte(self) -> None:
        """VST3 7.1.4 → SMPTE → VST3 7.1.4 is identity."""
        original = list(range(12))
        smpte = remap_channels_fill(original, VST3_7_1_4, SMPTE_7_1_4)
        back = remap_channels_fill(smpte, SMPTE_7_1_4, VST3_7_1_4)
        self.assertEqual(list(back), original)

    def test_vst3_714_heights_unchanged_vs_smpte(self) -> None:
        """VST3 7.1.4 → SMPTE: height channels (slots 8-11) must be the same value."""
        data = list(range(12))
        result = remap_channels_fill(data, VST3_7_1_4, SMPTE_7_1_4)
        # Heights are in the same slots in both standards
        for slot in range(8, 12):
            self.assertEqual(result[slot], data[slot])

    # ---- SMPTE ↔ Film round-trips ----

    def test_smpte_to_film_to_smpte_51(self) -> None:
        """SMPTE → Film → SMPTE 5.1 is identity."""
        original = [10, 20, 30, 40, 50, 60]
        film = remap_channels_fill(original, SMPTE_5_1, FILM_5_1)
        back = remap_channels_fill(film, FILM_5_1, SMPTE_5_1)
        self.assertEqual(list(back), original)

    def test_smpte_to_film_to_smpte_714(self) -> None:
        """SMPTE → Film → SMPTE 7.1.4 is identity."""
        original = list(range(12))
        film = remap_channels_fill(original, SMPTE_7_1_4, FILM_7_1_4)
        back = remap_channels_fill(film, FILM_7_1_4, SMPTE_7_1_4)
        self.assertEqual(list(back), original)

    def test_smpte_714_to_film_714_heights_same_values(self) -> None:
        """Heights (TFL TFR TBL TBR) carry the same values in both standards."""
        data = list(range(12))
        film = remap_channels_fill(data, SMPTE_7_1_4, FILM_7_1_4)
        # In Film 714, heights are at slots 8-11 (same as SMPTE)
        height_pos = [SpeakerPosition.TFL, SpeakerPosition.TFR, SpeakerPosition.TBL, SpeakerPosition.TBR]
        for pos in height_pos:
            src_slot = SMPTE_7_1_4.index_of(pos)
            dst_slot = FILM_7_1_4.index_of(pos)
            self.assertIsNotNone(src_slot)
            self.assertIsNotNone(dst_slot)
            self.assertEqual(film[dst_slot], data[src_slot])

    # ---- Determinism ----

    def test_remap_is_deterministic(self) -> None:
        data = [1, 2, 3, 4, 5, 6]
        a = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        b = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        self.assertEqual(list(a), list(b))


# ---------------------------------------------------------------------------
# TestRemapChannelsFillNumPy — same tests but with NumPy arrays
# ---------------------------------------------------------------------------


class TestRemapChannelsFillNumPy(unittest.TestCase):
    """NumPy-specific paths in remap_channels_fill."""

    def setUp(self) -> None:
        try:
            import numpy as np
            self._np = np
        except ImportError:
            self.skipTest("NumPy not installed")

    def test_identity_returns_same_array(self) -> None:
        data = self._np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        result = remap_channels_fill(data, SMPTE_5_1, SMPTE_5_1)
        self.assertIs(result, data)

    def test_1d_array_smpte_to_film_51(self) -> None:
        data = self._np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        result = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        self.assertIsInstance(result, self._np.ndarray)
        self._np.testing.assert_array_equal(result, [10.0, 30.0, 20.0, 50.0, 60.0, 40.0])

    def test_2d_array_stereo_upmix_to_51(self) -> None:
        """2.0 → 5.1: stereo buffer upmixed; new channels are zero-filled."""
        n_samples = 100
        data = self._np.ones((2, n_samples))
        result = remap_channels_fill(data, SMPTE_2_0, SMPTE_5_1)
        self.assertEqual(result.shape, (6, n_samples))
        self._np.testing.assert_array_equal(result[0], 1.0)  # FL
        self._np.testing.assert_array_equal(result[1], 1.0)  # FR
        self._np.testing.assert_array_equal(result[2], 0.0)  # FC zero-filled
        self._np.testing.assert_array_equal(result[3], 0.0)  # LFE zero-filled

    def test_2d_array_lfe_pinned_on_21_to_51(self) -> None:
        """2.1 → 5.1 (2D): LFE content lands exactly at the LFE slot."""
        n = 50
        data = self._np.zeros((3, n))
        data[2] = 1.0  # LFE channel has content
        result = remap_channels_fill(data, SMPTE_2_1, SMPTE_5_1)
        lfe_slot = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        self.assertIsNotNone(lfe_slot)
        self._np.testing.assert_array_equal(result[lfe_slot], 1.0)
        # No program channel should contain LFE content
        for i in range(result.shape[0]):
            if i != lfe_slot:
                self._np.testing.assert_array_equal(result[i], 0.0)

    def test_2d_array_714_to_51_height_not_in_lfe(self) -> None:
        """7.1.4 → 5.1 (2D): height-channel data never appears in LFE slot."""
        n = 30
        data = self._np.zeros((12, n))
        for slot in SMPTE_7_1_4.height_slots:
            data[slot] = 9999.0  # sentinel
        result = remap_channels_fill(data, SMPTE_7_1_4, SMPTE_5_1)
        lfe_slot = SMPTE_5_1.index_of(SpeakerPosition.LFE)
        self.assertIsNotNone(lfe_slot)
        self._np.testing.assert_array_equal(result[lfe_slot], 0.0)

    def test_dtype_preserved(self) -> None:
        data = self._np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], dtype=self._np.float32)
        result = remap_channels_fill(data, SMPTE_5_1, FILM_5_1)
        self.assertEqual(result.dtype, self._np.float32)

    def test_smpte_to_film_to_smpte_714_2d_roundtrip(self) -> None:
        """SMPTE → Film → SMPTE 7.1.4 (2D) is identity."""
        rng = self._np.random.default_rng(42)
        data = rng.standard_normal((12, 200)).astype(self._np.float64)
        film = remap_channels_fill(data, SMPTE_7_1_4, FILM_7_1_4)
        back = remap_channels_fill(film, FILM_7_1_4, SMPTE_7_1_4)
        self._np.testing.assert_array_equal(back, data)


# ---------------------------------------------------------------------------
# TestLayoutContextAndMultichannelPlugin
# ---------------------------------------------------------------------------


class TestLayoutContextAndMultichannelPlugin(unittest.TestCase):
    """LayoutContext and MultichannelPlugin protocol from mmo.dsp.plugins.base."""

    def test_layout_context_import(self) -> None:
        from mmo.dsp.plugins.base import LayoutContext  # noqa: F401

    def test_multichannel_plugin_protocol_import(self) -> None:
        from mmo.dsp.plugins.base import MultichannelPlugin  # noqa: F401

    def test_layout_context_index_of(self) -> None:
        from mmo.dsp.plugins.base import LayoutContext

        ctx = LayoutContext(layout=SMPTE_5_1)
        self.assertEqual(ctx.index_of(SpeakerPosition.LFE), 3)
        self.assertIsNone(ctx.index_of(SpeakerPosition.TFL))

    def test_layout_context_lfe_slots(self) -> None:
        from mmo.dsp.plugins.base import LayoutContext

        ctx = LayoutContext(layout=SMPTE_5_1)
        self.assertEqual(ctx.lfe_slots, [3])

    def test_layout_context_height_slots(self) -> None:
        from mmo.dsp.plugins.base import LayoutContext

        ctx = LayoutContext(layout=SMPTE_7_1_4)
        self.assertEqual(ctx.height_slots, [8, 9, 10, 11])

    def test_layout_context_num_channels(self) -> None:
        from mmo.dsp.plugins.base import LayoutContext

        ctx = LayoutContext(layout=SMPTE_7_1_4)
        self.assertEqual(ctx.num_channels, 12)


# ---------------------------------------------------------------------------
# TestWavMaskHeightBits — WAVEFORMATEXTENSIBLE height channel decoding
# ---------------------------------------------------------------------------


class TestWavMaskHeightBits(unittest.TestCase):
    """Verify that height channel mask bits decode correctly in channel_layout."""

    def test_tfl_mask_bit(self) -> None:
        from mmo.dsp.channel_layout import positions_from_wav_mask

        # 0x00001000 = TFL per WAVEFORMATEXTENSIBLE
        positions = positions_from_wav_mask(0x00001000)
        self.assertIn("TFL", positions)

    def test_tfr_mask_bit(self) -> None:
        from mmo.dsp.channel_layout import positions_from_wav_mask

        positions = positions_from_wav_mask(0x00004000)
        self.assertIn("TFR", positions)

    def test_tbl_mask_bit(self) -> None:
        from mmo.dsp.channel_layout import positions_from_wav_mask

        positions = positions_from_wav_mask(0x00008000)
        self.assertIn("TBL", positions)

    def test_tbr_mask_bit(self) -> None:
        from mmo.dsp.channel_layout import positions_from_wav_mask

        positions = positions_from_wav_mask(0x00020000)
        self.assertIn("TBR", positions)

    def test_714_combined_mask_has_all_heights(self) -> None:
        """A combined mask for 7.1.4 must yield all 12 positions including TFL/TFR/TBL/TBR."""
        from mmo.dsp.channel_layout import positions_from_wav_mask

        # Standard 7.1.4 WAVEFORMATEXTENSIBLE channel mask
        mask_7_1_4 = (
            0x00000001  # FL
            | 0x00000002  # FR
            | 0x00000004  # FC
            | 0x00000008  # LFE
            | 0x00000010  # BL
            | 0x00000020  # BR
            | 0x00000200  # SL
            | 0x00000400  # SR
            | 0x00001000  # TFL
            | 0x00004000  # TFR
            | 0x00008000  # TBL
            | 0x00020000  # TBR
        )
        positions = positions_from_wav_mask(mask_7_1_4)
        self.assertEqual(len(positions), 12)
        for expected in ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR", "TFL", "TFR", "TBL", "TBR"):
            self.assertIn(expected, positions, f"Missing {expected} in 7.1.4 mask decode")

    def test_spk_id_mapping_for_height_labels(self) -> None:
        """_WAV_MASK_LABEL_TO_SPK_ID must map TBL→SPK.TRL and TBR→SPK.TRR."""
        from mmo.dsp.channel_layout import _WAV_MASK_LABEL_TO_SPK_ID

        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["TFL"], "SPK.TFL")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["TFR"], "SPK.TFR")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["TBL"], "SPK.TRL")  # TBL ≡ TRL (two names, one speaker)
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["TBR"], "SPK.TRR")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["SL"], "SPK.LS")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["SR"], "SPK.RS")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["BL"], "SPK.LRS")
        self.assertEqual(_WAV_MASK_LABEL_TO_SPK_ID["BR"], "SPK.RRS")


# ---------------------------------------------------------------------------
# TestOntologyOrderingVariants — layouts.yaml has the new variants
# ---------------------------------------------------------------------------


class TestOntologyOrderingVariants(unittest.TestCase):
    """Verify that layouts.yaml was updated with LOGIC_PRO and VST3 variants."""

    def test_51_has_logic_pro_variant(self) -> None:
        from mmo.core.layout_negotiation import get_channel_order

        order = get_channel_order("LAYOUT.5_1", "LOGIC_PRO")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 6)
        # L R Ls Rs C LFE — surrounds before centre
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.R")
        self.assertEqual(order[4], "SPK.C")
        self.assertEqual(order[5], "SPK.LFE")

    def test_71_has_logic_pro_variant(self) -> None:
        from mmo.core.layout_negotiation import get_channel_order

        order = get_channel_order("LAYOUT.7_1", "LOGIC_PRO")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 8)
        # L R Lrs Rrs Ls Rs C LFE
        self.assertEqual(order[6], "SPK.C")
        self.assertEqual(order[7], "SPK.LFE")

    def test_71_has_vst3_variant(self) -> None:
        from mmo.core.layout_negotiation import get_channel_order

        order = get_channel_order("LAYOUT.7_1", "VST3")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 8)
        # Rears (LRS/RRS) must be at slots 4-5, sides (LS/RS) at slots 6-7
        self.assertEqual(order[4], "SPK.LRS")
        self.assertEqual(order[5], "SPK.RRS")
        self.assertEqual(order[6], "SPK.LS")
        self.assertEqual(order[7], "SPK.RS")

    def test_714_has_vst3_variant(self) -> None:
        from mmo.core.layout_negotiation import get_channel_order

        order = get_channel_order("LAYOUT.7_1_4", "VST3")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 12)
        # Rears before sides in bed, heights same as SMPTE
        self.assertEqual(order[4], "SPK.LRS")
        self.assertEqual(order[5], "SPK.RRS")
        self.assertEqual(order[6], "SPK.LS")
        self.assertEqual(order[7], "SPK.RS")
        # Heights unchanged from SMPTE
        self.assertEqual(order[8], "SPK.TFL")
        self.assertEqual(order[9], "SPK.TFR")

    def test_512_has_film_variant(self) -> None:
        from mmo.core.layout_negotiation import get_channel_order

        order = get_channel_order("LAYOUT.5_1_2", "FILM")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 8)
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.C")  # C in Film slot 1
        self.assertEqual(order[5], "SPK.LFE")  # LFE at end of bed

    def test_714_has_all_four_standards(self) -> None:
        from mmo.core.layout_negotiation import list_supported_standards

        standards = list_supported_standards("LAYOUT.7_1_4")
        self.assertIn("SMPTE", standards)
        self.assertIn("FILM", standards)
        self.assertIn("VST3", standards)

    def test_future_layouts_present(self) -> None:
        from mmo.core.layout_negotiation import list_supported_layouts

        layouts = list_supported_layouts()
        self.assertIn("LAYOUT.SDDS_7_1", layouts)
        self.assertIn("LAYOUT.7_1_6", layouts)
        self.assertIn("LAYOUT.9_1_6", layouts)

    def test_sdds_71_channel_count(self) -> None:
        from mmo.core.layout_negotiation import get_channel_count

        count = get_channel_count("LAYOUT.SDDS_7_1")
        self.assertEqual(count, 8)

    def test_716_channel_count(self) -> None:
        from mmo.core.layout_negotiation import get_channel_count

        count = get_channel_count("LAYOUT.7_1_6")
        self.assertEqual(count, 14)

    def test_916_channel_count(self) -> None:
        from mmo.core.layout_negotiation import get_channel_count

        count = get_channel_count("LAYOUT.9_1_6")
        self.assertEqual(count, 16)


if __name__ == "__main__":
    unittest.main()
