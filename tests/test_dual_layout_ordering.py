"""Regression tests for dual SMPTE/Film channel-ordering standard support.

Covers:
- ``layout_negotiation.get_channel_order()`` — SMPTE and FILM variants for
  5.1, 7.1, and 7.1.4 layouts.
- ``layout_negotiation.list_supported_standards()`` — available standards.
- ``layout_negotiation.reorder_channels()`` — data reordering between
  orderings; list, tuple, and NumPy-array inputs.
- ``render_contract.build_render_contract()`` — ``layout_standard`` param
  propagates to ``channel_order`` and ``layout_standard`` fields.
- ``render_engine.render_scene_to_targets()`` — ``layout_standard`` option
  propagated to contracts; report schema-valid for both standards.

Determinism guarantee: all assertions must produce the same result across
repeated runs (no randomness, no timestamps).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.layout_negotiation import (
    DEFAULT_CHANNEL_STANDARD,
    get_channel_order,
    list_supported_standards,
    reorder_channels,
)
from mmo.core.render_contract import (
    DEFAULT_LAYOUT_STANDARD,
    build_render_contract,
)
from mmo.core.render_engine import render_scene_to_targets

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------


def _build_registry() -> Registry:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _report_validator() -> jsonschema.Draft202012Validator:
    schema_path = SCHEMAS_DIR / "render_report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=_build_registry())


# ---------------------------------------------------------------------------
# TestGetChannelOrder — standard-aware channel order lookup
# ---------------------------------------------------------------------------


class TestGetChannelOrder(unittest.TestCase):
    """Tests for layout_negotiation.get_channel_order()."""

    # --- Default (SMPTE) behavior ---

    def test_stereo_smpte_default(self) -> None:
        order = get_channel_order("LAYOUT.2_0")
        self.assertEqual(order, ["SPK.L", "SPK.R"])

    def test_stereo_smpte_explicit(self) -> None:
        order = get_channel_order("LAYOUT.2_0", "SMPTE")
        self.assertEqual(order, ["SPK.L", "SPK.R"])

    def test_51_smpte_channel_positions(self) -> None:
        """5.1 SMPTE: L R C LFE Ls Rs."""
        order = get_channel_order("LAYOUT.5_1", "SMPTE")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 6)
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.R")
        self.assertEqual(order[2], "SPK.C")
        self.assertEqual(order[3], "SPK.LFE")

    def test_51_film_channel_positions(self) -> None:
        """5.1 Film: L C R Ls Rs LFE (LFE moves to end)."""
        order = get_channel_order("LAYOUT.5_1", "FILM")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 6)
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.C")
        self.assertEqual(order[2], "SPK.R")
        # LFE is at the end in Film ordering.
        self.assertEqual(order[-1], "SPK.LFE")

    def test_51_film_and_smpte_same_channels_different_order(self) -> None:
        """Both SMPTE and Film variants contain the same set of channels."""
        smpte = get_channel_order("LAYOUT.5_1", "SMPTE")
        film = get_channel_order("LAYOUT.5_1", "FILM")
        self.assertIsNotNone(smpte)
        self.assertIsNotNone(film)
        self.assertEqual(set(smpte), set(film))
        self.assertNotEqual(smpte, film)

    def test_71_smpte_channel_count(self) -> None:
        order = get_channel_order("LAYOUT.7_1", "SMPTE")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 8)

    def test_714_smpte_channel_count(self) -> None:
        order = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        self.assertIsNotNone(order)
        self.assertEqual(len(order), 12)

    def test_714_film_defined(self) -> None:
        """7.1.4 FILM variant should be defined in ordering_variants."""
        film = get_channel_order("LAYOUT.7_1_4", "FILM")
        self.assertIsNotNone(film)
        # FILM variant: 12 channels (LFE after surrounds, heights at end)
        self.assertEqual(len(film), 12)

    def test_714_smpte_starts_with_l_r(self) -> None:
        order = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(order[0], "SPK.L")
        self.assertEqual(order[1], "SPK.R")

    def test_unknown_standard_falls_back_to_canonical(self) -> None:
        """An unrecognised standard falls back to the canonical channel_order."""
        smpte = get_channel_order("LAYOUT.5_1", "SMPTE")
        unknown = get_channel_order("LAYOUT.5_1", "UNKNOWN_STD")
        self.assertEqual(smpte, unknown)

    def test_unknown_layout_returns_none(self) -> None:
        self.assertIsNone(get_channel_order("LAYOUT.DOES_NOT_EXIST"))

    def test_empty_layout_id_returns_none(self) -> None:
        self.assertIsNone(get_channel_order(""))

    def test_result_is_list_of_spk_ids(self) -> None:
        order = get_channel_order("LAYOUT.5_1", "SMPTE")
        self.assertIsInstance(order, list)
        for ch in order:
            self.assertIsInstance(ch, str)
            self.assertTrue(ch.startswith("SPK."), f"Expected SPK.* id, got: {ch!r}")

    def test_smpte_is_deterministic(self) -> None:
        a = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        b = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(a, b)

    def test_film_is_deterministic(self) -> None:
        a = get_channel_order("LAYOUT.5_1", "FILM")
        b = get_channel_order("LAYOUT.5_1", "FILM")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# TestListSupportedStandards — available standards per layout
# ---------------------------------------------------------------------------


class TestListSupportedStandards(unittest.TestCase):
    """Tests for layout_negotiation.list_supported_standards()."""

    def test_always_includes_smpte_for_51(self) -> None:
        standards = list_supported_standards("LAYOUT.5_1")
        self.assertIn("SMPTE", standards)

    def test_includes_film_for_51(self) -> None:
        """5.1 has an explicit FILM variant in ordering_variants."""
        standards = list_supported_standards("LAYOUT.5_1")
        self.assertIn("FILM", standards)

    def test_714_has_smpte_and_film(self) -> None:
        standards = list_supported_standards("LAYOUT.7_1_4")
        self.assertIn("SMPTE", standards)
        self.assertIn("FILM", standards)

    def test_stereo_has_smpte(self) -> None:
        standards = list_supported_standards("LAYOUT.2_0")
        self.assertIn("SMPTE", standards)

    def test_result_is_sorted(self) -> None:
        standards = list_supported_standards("LAYOUT.5_1")
        self.assertEqual(standards, sorted(standards))

    def test_unknown_layout_returns_empty(self) -> None:
        standards = list_supported_standards("LAYOUT.DOES_NOT_EXIST")
        self.assertEqual(standards, [])

    def test_default_standard_constant(self) -> None:
        self.assertEqual(DEFAULT_CHANNEL_STANDARD, "SMPTE")


# ---------------------------------------------------------------------------
# TestReorderChannels — channel data reordering
# ---------------------------------------------------------------------------


class TestReorderChannels(unittest.TestCase):
    """Tests for layout_negotiation.reorder_channels()."""

    # 5.1 SMPTE: L=0 R=1 C=2 LFE=3 Ls=4 Rs=5
    _SMPTE_51 = ["SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"]
    # 5.1 Film:  L=0 C=1 R=2 Ls=3 Rs=4 LFE=5
    _FILM_51 = ["SPK.L", "SPK.C", "SPK.R", "SPK.LS", "SPK.RS", "SPK.LFE"]

    def test_identity_reorder(self) -> None:
        data = [0, 1, 2, 3, 4, 5]
        result = reorder_channels(data, self._SMPTE_51, self._SMPTE_51)
        self.assertEqual(result, [0, 1, 2, 3, 4, 5])

    def test_smpte_to_film_reorder(self) -> None:
        """SMPTE → Film: L stays, C and R swap, LFE moves to end."""
        data = [0, 1, 2, 3, 4, 5]  # L R C LFE Ls Rs indices
        result = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        # Film output: L C R Ls Rs LFE → indices 0 2 1 4 5 3
        self.assertEqual(list(result), [0, 2, 1, 4, 5, 3])

    def test_film_to_smpte_reorder(self) -> None:
        """Film → SMPTE: inverse of SMPTE → Film."""
        film_data = [0, 2, 1, 4, 5, 3]  # already Film-ordered
        result = reorder_channels(film_data, self._FILM_51, self._SMPTE_51)
        # Recover SMPTE order
        self.assertEqual(list(result), [0, 1, 2, 3, 4, 5])

    def test_returns_list_for_list_input(self) -> None:
        data = [10, 20, 30, 40, 50, 60]
        result = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        self.assertIsInstance(result, list)

    def test_returns_tuple_for_tuple_input(self) -> None:
        data = (10, 20, 30, 40, 50, 60)
        result = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        self.assertIsInstance(result, tuple)

    def test_mismatched_length_raises(self) -> None:
        with self.assertRaises(ValueError):
            reorder_channels([1, 2, 3], self._SMPTE_51, self._FILM_51)

    def test_unknown_channel_in_to_order_is_dropped(self) -> None:
        """Channels in to_order not present in from_order are silently dropped."""
        from_order = ["SPK.L", "SPK.R"]
        to_order = ["SPK.L", "SPK.C", "SPK.R"]  # SPK.C not in from_order
        data = [10, 20]
        result = reorder_channels(data, from_order, to_order)
        # Only L and R survive (C dropped).
        self.assertEqual(list(result), [10, 20])

    def test_reorder_is_deterministic(self) -> None:
        data = [1, 2, 3, 4, 5, 6]
        a = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        b = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        self.assertEqual(list(a), list(b))

    def test_numpy_array_if_available(self) -> None:
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not installed")
        data = np.array([0, 1, 2, 3, 4, 5])
        result = reorder_channels(data, self._SMPTE_51, self._FILM_51)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(result.tolist(), [0, 2, 1, 4, 5, 3])

    def test_714_reorder_preserves_channel_count(self) -> None:
        smpte = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        film = get_channel_order("LAYOUT.7_1_4", "FILM")
        self.assertIsNotNone(smpte)
        self.assertIsNotNone(film)
        # Only channels present in both orderings are in the output.
        data = list(range(len(smpte)))
        result = reorder_channels(data, smpte, film)
        # Result length = |intersection(smpte, film)|
        common = set(smpte) & set(film)
        self.assertEqual(len(result), len(common))


# ---------------------------------------------------------------------------
# TestRenderContractLayoutStandard — layout_standard in contracts
# ---------------------------------------------------------------------------


class TestRenderContractLayoutStandard(unittest.TestCase):
    """Tests for layout_standard parameter in build_render_contract()."""

    def test_default_standard_is_smpte(self) -> None:
        contract = build_render_contract("TARGET.TEST", "LAYOUT.5_1")
        self.assertEqual(contract["layout_standard"], "SMPTE")

    def test_explicit_smpte(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE"
        )
        self.assertEqual(contract["layout_standard"], "SMPTE")

    def test_film_standard_stored_in_contract(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM"
        )
        self.assertEqual(contract["layout_standard"], "FILM")

    def test_smpte_channel_order_matches_smpte_variant(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE"
        )
        expected = get_channel_order("LAYOUT.5_1", "SMPTE")
        self.assertEqual(contract["channel_order"], expected)

    def test_film_channel_order_matches_film_variant(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM"
        )
        expected = get_channel_order("LAYOUT.5_1", "FILM")
        self.assertEqual(contract["channel_order"], expected)

    def test_smpte_and_film_channel_orders_differ_for_51(self) -> None:
        smpte = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE")
        film = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM")
        self.assertNotEqual(smpte["channel_order"], film["channel_order"])

    def test_lfe_at_index_3_in_smpte_51(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE"
        )
        self.assertEqual(contract["channel_order"][3], "SPK.LFE")

    def test_lfe_at_end_in_film_51(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM"
        )
        self.assertEqual(contract["channel_order"][-1], "SPK.LFE")

    def test_714_smpte_contract_has_12_channels(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.7_1_4", layout_standard="SMPTE"
        )
        self.assertEqual(contract["channel_count"], 12)
        self.assertEqual(len(contract["channel_order"]), 12)

    def test_standard_is_uppercased(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="film"
        )
        self.assertEqual(contract["layout_standard"], "FILM")

    def test_default_layout_standard_constant(self) -> None:
        self.assertEqual(DEFAULT_LAYOUT_STANDARD, "SMPTE")

    def test_contract_deterministic_across_standards(self) -> None:
        a_smpte = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE")
        b_smpte = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE")
        self.assertEqual(a_smpte, b_smpte)

        a_film = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM")
        b_film = build_render_contract("TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM")
        self.assertEqual(a_film, b_film)


# ---------------------------------------------------------------------------
# TestRenderEngineLayoutStandard — layout_standard wired through engine
# ---------------------------------------------------------------------------


class TestRenderEngineLayoutStandard(unittest.TestCase):
    """Tests for layout_standard option in render_scene_to_targets()."""

    def _make_scene(self, source_layout_id: str = "LAYOUT.5_1") -> dict:
        return {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.TEST.DUAL_LAYOUT",
            "scene_path": "scenes/test/dual_layout.json",
            "source": {
                "stems_dir": "stems/test",
                "layout_id": source_layout_id,
                "created_from": "analyze",
            },
            "metadata": {},
        }

    def setUp(self) -> None:
        self.validator = _report_validator()

    def _assert_valid(self, report: dict) -> None:
        errors = list(self.validator.iter_errors(report))
        if errors:
            detail = "\n".join(str(e) for e in errors)
            self.fail(f"render_report schema errors:\n{detail}")

    # --- Schema conformance for both standards ---

    def test_smpte_report_schema_valid(self) -> None:
        scene = self._make_scene("LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                layout_standard="SMPTE",
            )
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "SMPTE"}
        )
        self._assert_valid(report)

    def test_film_report_schema_valid(self) -> None:
        scene = self._make_scene("LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                layout_standard="FILM",
            )
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "FILM"}
        )
        self._assert_valid(report)

    def test_714_smpte_report_schema_valid(self) -> None:
        scene = self._make_scene("LAYOUT.7_1_4")
        contracts = [
            build_render_contract(
                "TARGET.IMMERSIVE.7_1_4",
                "LAYOUT.7_1_4",
                layout_standard="SMPTE",
            )
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "SMPTE"}
        )
        self._assert_valid(report)

    def test_714_film_report_schema_valid(self) -> None:
        scene = self._make_scene("LAYOUT.7_1_4")
        contracts = [
            build_render_contract(
                "TARGET.IMMERSIVE.7_1_4",
                "LAYOUT.7_1_4",
                layout_standard="FILM",
            )
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "FILM"}
        )
        self._assert_valid(report)

    # --- Explainability: notes mention the standard ---

    def test_smpte_note_in_job(self) -> None:
        scene = self._make_scene("LAYOUT.2_0")
        contracts = [
            build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0", layout_standard="SMPTE")
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "SMPTE"}
        )
        all_notes = [n for job in report["jobs"] for n in job.get("notes", [])]
        smpte_notes = [n for n in all_notes if "SMPTE" in n]
        self.assertGreater(len(smpte_notes), 0, "Expected SMPTE mentioned in job notes")

    def test_film_note_in_job(self) -> None:
        scene = self._make_scene("LAYOUT.5_1")
        contracts = [
            build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0", layout_standard="FILM")
        ]
        report = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "layout_standard": "FILM"}
        )
        all_notes = [n for job in report["jobs"] for n in job.get("notes", [])]
        film_notes = [n for n in all_notes if "FILM" in n or "Film" in n or "Cinema" in n]
        self.assertGreater(len(film_notes), 0, "Expected Film/Cinema mentioned in job notes")

    # --- Determinism across standards ---

    def test_smpte_report_deterministic(self) -> None:
        scene = self._make_scene("LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                layout_standard="SMPTE",
            )
        ]
        opts = {"dry_run": True, "layout_standard": "SMPTE"}
        a = render_scene_to_targets(scene, contracts, opts)
        b = render_scene_to_targets(scene, contracts, opts)
        self.assertEqual(a, b)

    def test_film_report_deterministic(self) -> None:
        scene = self._make_scene("LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                layout_standard="FILM",
            )
        ]
        opts = {"dry_run": True, "layout_standard": "FILM"}
        a = render_scene_to_targets(scene, contracts, opts)
        b = render_scene_to_targets(scene, contracts, opts)
        self.assertEqual(a, b)

    def test_smpte_and_film_reports_differ(self) -> None:
        """SMPTE and Film contracts must produce different channel_order in the contract."""
        smpte_c = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="SMPTE"
        )
        film_c = build_render_contract(
            "TARGET.TEST", "LAYOUT.5_1", layout_standard="FILM"
        )
        self.assertNotEqual(smpte_c["channel_order"], film_c["channel_order"])


# ---------------------------------------------------------------------------
# TestRegressionFixtures — explicit per-standard regression checks
# ---------------------------------------------------------------------------


class TestRegressionFixtures(unittest.TestCase):
    """Pinned regression fixtures for 5.1 and 7.1.4 SMPTE/Film orderings.

    These tests fix the canonical channel orderings; if layouts.yaml changes,
    these tests will fail and force a deliberate review of the change.
    """

    # 5.1 SMPTE (per SMPTE 428-12 / ITU-R BS.775)
    _51_SMPTE = ["SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"]

    # 5.1 Film/Cinema (L C R Ls Rs LFE)
    _51_FILM = ["SPK.L", "SPK.C", "SPK.R", "SPK.LS", "SPK.RS", "SPK.LFE"]

    # 7.1.4 SMPTE (ITU-R BS.2051-3 recommended)
    _714_SMPTE_EXPECTED = [
        "SPK.L", "SPK.R", "SPK.C", "SPK.LFE",
        "SPK.LS", "SPK.RS", "SPK.LRS", "SPK.RRS",
        "SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR",
    ]

    def test_51_smpte_fixture(self) -> None:
        order = get_channel_order("LAYOUT.5_1", "SMPTE")
        self.assertEqual(order, self._51_SMPTE)

    def test_51_film_fixture(self) -> None:
        order = get_channel_order("LAYOUT.5_1", "FILM")
        self.assertEqual(order, self._51_FILM)

    # 7.1.4 Film: bed in Film order (L C R Ls Rs Lrs Rrs LFE) + heights
    _714_FILM_EXPECTED = [
        "SPK.L", "SPK.C", "SPK.R", "SPK.LS", "SPK.RS", "SPK.LRS", "SPK.RRS",
        "SPK.LFE", "SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR",
    ]

    def test_714_smpte_fixture(self) -> None:
        order = get_channel_order("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(order, self._714_SMPTE_EXPECTED)

    def test_714_film_fixture(self) -> None:
        order = get_channel_order("LAYOUT.7_1_4", "FILM")
        self.assertEqual(order, self._714_FILM_EXPECTED)

    def test_51_smpte_reorder_to_film(self) -> None:
        """Pinned reorder result: SMPTE data → Film order."""
        # Input: channel indices 0-5 in SMPTE order (L R C LFE Ls Rs)
        data = list(range(6))
        result = reorder_channels(data, self._51_SMPTE, self._51_FILM)
        # Film order picks: L(0) C(2) R(1) Ls(4) Rs(5) LFE(3)
        self.assertEqual(result, [0, 2, 1, 4, 5, 3])

    def test_51_film_reorder_to_smpte(self) -> None:
        """Pinned reorder result: Film data → SMPTE order."""
        # Input already in Film order (L C R Ls Rs LFE)
        data = [0, 2, 1, 4, 5, 3]
        result = reorder_channels(data, self._51_FILM, self._51_SMPTE)
        self.assertEqual(result, list(range(6)))


if __name__ == "__main__":
    unittest.main()
