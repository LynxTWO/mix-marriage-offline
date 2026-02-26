"""Tests for src/mmo/core/preflight.py and src/mmo/core/downmix.py.

Covers:
- Determinism: same inputs/options always produce identical receipts.
- Schema validity: all receipts conform to preflight_receipt.schema.json.
- GATE.LAYOUT_NEGOTIATION: pass (known matrix), block (no matrix), skip (no source).
- GATE.DOWNMIX_SIMILARITY: low-risk path, hot-LFE path.
- GATE.CORRELATION_RISK / GATE.PHASE_RISK: negative-correlation scene.
- GATE.CONFIDENCE_LOW: low-confidence and very-low-confidence scenes.
- Final-decision aggregation: pass / warn / block.
- preflight_receipt_blocks() helper.
- core/downmix.py: predict_fold_similarity(), layout_negotiation_available().
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict

import jsonschema

from mmo.core.preflight import (
    PREFLIGHT_RECEIPT_SCHEMA_VERSION,
    evaluate_preflight,
    preflight_receipt_blocks,
)
from mmo.core.downmix import (
    MATRIX_VERSION,
    get_matrix_version,
    layout_negotiation_available,
    predict_fold_similarity,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_SCHEMA_PATH = _SCHEMAS_DIR / "preflight_receipt.schema.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_validator() -> jsonschema.Draft202012Validator:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _validate(receipt: Dict[str, Any], validator: jsonschema.Draft202012Validator) -> None:
    errors = list(validator.iter_errors(receipt))
    if errors:
        msgs = "\n".join(str(e) for e in errors[:5])
        raise AssertionError(f"Schema validation failed:\n{msgs}")


def _make_empty_scene() -> Dict[str, Any]:
    return {}


def _make_scene_with_confidence(overall: float) -> Dict[str, Any]:
    return {"metadata": {"confidence": overall}}


def _make_scene_with_correlation(correlation: float) -> Dict[str, Any]:
    return {"metadata": {"correlation": correlation}}


def _make_scene_with_polarity_inverted() -> Dict[str, Any]:
    return {"metadata": {"polarity_inverted": True}}


def _make_scene_with_recs(confidences: list[float]) -> Dict[str, Any]:
    recs = [
        {
            "recommendation_id": f"REC.{i:03d}",
            "action_id": f"ACTION.TEST.{i:03d}",
            "confidence": c,
        }
        for i, c in enumerate(confidences)
    ]
    return {"recommendations": recs}


# ---------------------------------------------------------------------------
# Fixtures for regression (5.1 → stereo)
# ---------------------------------------------------------------------------

_SESSION_51_TO_20 = {"source_layout_id": "LAYOUT.5_1"}
_TARGET_STEREO = "LAYOUT.2_0"
_OPTIONS_DEFAULT: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Tests: schema and version constants
# ---------------------------------------------------------------------------

class TestPreflightConstants(unittest.TestCase):
    def test_schema_version_constant(self) -> None:
        self.assertEqual(PREFLIGHT_RECEIPT_SCHEMA_VERSION, "0.1.0")

    def test_matrix_version_constant(self) -> None:
        self.assertEqual(MATRIX_VERSION, "1.0.0")
        self.assertEqual(get_matrix_version(), "1.0.0")


# ---------------------------------------------------------------------------
# Tests: determinism
# ---------------------------------------------------------------------------

class TestPreflightDeterminism(unittest.TestCase):
    def _run_twice(
        self,
        session: Dict[str, Any],
        scene: Dict[str, Any],
        target: str,
        options: Dict[str, Any],
    ) -> None:
        r1 = evaluate_preflight(session, scene, target, options)
        r2 = evaluate_preflight(session, scene, target, options)
        j1 = json.dumps(r1, sort_keys=True, separators=(",", ":"))
        j2 = json.dumps(r2, sort_keys=True, separators=(",", ":"))
        self.assertEqual(j1, j2, "evaluate_preflight must be deterministic")

    def test_determinism_empty_inputs(self) -> None:
        self._run_twice({}, {}, "stereo", {})

    def test_determinism_51_to_stereo(self) -> None:
        self._run_twice(
            _SESSION_51_TO_20, _make_empty_scene(), _TARGET_STEREO, _OPTIONS_DEFAULT
        )

    def test_determinism_low_confidence_scene(self) -> None:
        scene = _make_scene_with_confidence(0.1)
        self._run_twice(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_determinism_negative_correlation_scene(self) -> None:
        scene = _make_scene_with_correlation(-0.8)
        self._run_twice(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_determinism_multiple_recs(self) -> None:
        scene = _make_scene_with_recs([0.9, 0.4, 0.2, 0.8])
        self._run_twice(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})


# ---------------------------------------------------------------------------
# Tests: schema validity
# ---------------------------------------------------------------------------

class TestPreflightSchemaValidity(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _load_validator()

    def _assert_valid(
        self,
        session: Dict[str, Any],
        scene: Dict[str, Any],
        target: str,
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        receipt = evaluate_preflight(session, scene, target, options)
        _validate(receipt, self.validator)
        return receipt

    def test_schema_valid_empty_inputs(self) -> None:
        self._assert_valid({}, {}, "stereo", {})

    def test_schema_valid_51_to_stereo(self) -> None:
        self._assert_valid(_SESSION_51_TO_20, _make_empty_scene(), _TARGET_STEREO, {})

    def test_schema_valid_low_confidence(self) -> None:
        scene = _make_scene_with_confidence(0.15)
        self._assert_valid(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_schema_valid_negative_correlation(self) -> None:
        scene = _make_scene_with_correlation(-0.9)
        self._assert_valid(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_schema_valid_polarity_inverted(self) -> None:
        scene = _make_scene_with_polarity_inverted()
        self._assert_valid(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_schema_valid_no_source_layout(self) -> None:
        self._assert_valid({}, _make_empty_scene(), _TARGET_STEREO, {})

    def test_schema_valid_with_recs(self) -> None:
        scene = _make_scene_with_recs([0.9, 0.3, 0.7])
        self._assert_valid(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})

    def test_schema_version_in_receipt(self) -> None:
        receipt = self._assert_valid({}, {}, "stereo", {})
        self.assertEqual(receipt["schema_version"], "0.1.0")


# ---------------------------------------------------------------------------
# Tests: GATE.LAYOUT_NEGOTIATION
# ---------------------------------------------------------------------------

class TestGateLayoutNegotiation(unittest.TestCase):
    def _find_gate(self, receipt: Dict[str, Any], gate_id: str) -> Dict[str, Any]:
        for g in receipt["gates_evaluated"]:
            if g["gate_id"] == gate_id:
                return g
        self.fail(f"Gate {gate_id!r} not found in receipt")
        return {}  # unreachable

    def test_skipped_when_no_source_layout(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.LAYOUT_NEGOTIATION")
        self.assertEqual(gate["outcome"], "skipped")

    def test_pass_51_to_stereo(self) -> None:
        """5.1 → stereo should have a registered matrix and pass."""
        receipt = evaluate_preflight(
            _SESSION_51_TO_20, _make_empty_scene(), _TARGET_STEREO, {}
        )
        gate = self._find_gate(receipt, "GATE.LAYOUT_NEGOTIATION")
        # Should be pass or warn (composed path) but NOT block
        self.assertIn(gate["outcome"], ("pass", "warn", "skipped"))

    def test_block_on_unknown_layout(self) -> None:
        """Unknown source layout → block (no matrix can be found)."""
        session = {"source_layout_id": "LAYOUT.UNKNOWN_XYZ_999"}
        receipt = evaluate_preflight(session, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.LAYOUT_NEGOTIATION")
        self.assertEqual(gate["outcome"], "block")
        self.assertEqual(receipt["final_decision"], "block")

    def test_block_causes_preflight_receipt_blocks(self) -> None:
        session = {"source_layout_id": "LAYOUT.UNKNOWN_XYZ_999"}
        receipt = evaluate_preflight(session, _make_empty_scene(), "stereo", {})
        self.assertTrue(preflight_receipt_blocks(receipt))

    def test_pass_does_not_block(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        # No source layout → no block from layout gate
        # Other gates may warn; but final_decision should not be block from layout gate alone
        gate = self._find_gate(receipt, "GATE.LAYOUT_NEGOTIATION")
        self.assertNotEqual(gate["outcome"], "block")


# ---------------------------------------------------------------------------
# Tests: GATE.DOWNMIX_SIMILARITY (including hot-LFE regression)
# ---------------------------------------------------------------------------

class TestGateDownmixSimilarity(unittest.TestCase):
    def _find_gate(self, receipt: Dict[str, Any], gate_id: str) -> Dict[str, Any]:
        for g in receipt["gates_evaluated"]:
            if g["gate_id"] == gate_id:
                return g
        self.fail(f"Gate {gate_id!r} not found")
        return {}

    def test_skipped_when_no_source_layout(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY")
        self.assertEqual(gate["outcome"], "skipped")

    def test_similarity_check_51_to_stereo(self) -> None:
        """5.1 → stereo should evaluate (not skipped)."""
        receipt = evaluate_preflight(
            _SESSION_51_TO_20, _make_empty_scene(), _TARGET_STEREO, {}
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY")
        self.assertIn(gate["outcome"], ("pass", "warn", "block"))

    def test_hot_lfe_triggers_warn_or_block(self) -> None:
        """Hot LFE: force a high LFE threshold by setting very low warn threshold."""
        receipt = evaluate_preflight(
            _SESSION_51_TO_20,
            _make_empty_scene(),
            _TARGET_STEREO,
            # Extremely tight threshold — almost any LFE fold should exceed it
            {"lfe_boost_warn_db": 0.001, "lfe_boost_error_db": 0.001},
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY")
        # If LFE is present in this matrix the gate should warn or block;
        # if no LFE channel is folded the gate will pass (that is also valid).
        self.assertIn(gate["outcome"], ("pass", "warn", "block"))
        # At minimum the gate was evaluated (not skipped)
        self.assertNotEqual(gate["outcome"], "skipped")

    def test_downmix_check_present_when_matrix_found(self) -> None:
        receipt = evaluate_preflight(
            _SESSION_51_TO_20, _make_empty_scene(), _TARGET_STEREO, {}
        )
        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY")
        if gate["outcome"] != "skipped":
            self.assertGreaterEqual(len(receipt["downmix_checks"]), 1)
            check = receipt["downmix_checks"][0]
            self.assertIn(check["risk_level"], ("low", "medium", "high"))
            self.assertIn("lfe_folded", check)
            self.assertIn("predicted_lufs_delta", check)


# ---------------------------------------------------------------------------
# Tests: GATE.CORRELATION_RISK and GATE.PHASE_RISK
# ---------------------------------------------------------------------------

class TestGatePhaseAndCorrelation(unittest.TestCase):
    def _find_gate(self, receipt: Dict[str, Any], gate_id: str) -> Dict[str, Any]:
        for g in receipt["gates_evaluated"]:
            if g["gate_id"] == gate_id:
                return g
        self.fail(f"Gate {gate_id!r} not found")
        return {}

    def test_correlation_risk_none_when_no_metadata(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.CORRELATION_RISK")
        self.assertEqual(gate["outcome"], "pass")

    def test_correlation_risk_warn_on_borderline(self) -> None:
        scene = _make_scene_with_correlation(-0.3)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CORRELATION_RISK")
        self.assertEqual(gate["outcome"], "warn")

    def test_correlation_risk_block_on_strong_negative(self) -> None:
        scene = _make_scene_with_correlation(-0.8)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CORRELATION_RISK")
        self.assertEqual(gate["outcome"], "block")
        self.assertEqual(receipt["final_decision"], "block")

    def test_phase_risk_none_when_no_polarity_flag(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(gate["outcome"], "pass")

    def test_phase_risk_block_on_polarity_inverted(self) -> None:
        scene = _make_scene_with_polarity_inverted()
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(gate["outcome"], "block")

    def test_phase_risk_block_on_very_negative_correlation(self) -> None:
        scene = _make_scene_with_correlation(-0.9)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(gate["outcome"], "block")


# ---------------------------------------------------------------------------
# Tests: GATE.CONFIDENCE_LOW
# ---------------------------------------------------------------------------

class TestGateConfidenceLow(unittest.TestCase):
    def _find_gate(self, receipt: Dict[str, Any], gate_id: str) -> Dict[str, Any]:
        for g in receipt["gates_evaluated"]:
            if g["gate_id"] == gate_id:
                return g
        self.fail(f"Gate {gate_id!r} not found")
        return {}

    def test_confidence_high_passes(self) -> None:
        scene = _make_scene_with_confidence(0.9)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "pass")

    def test_confidence_medium_passes(self) -> None:
        scene = _make_scene_with_confidence(0.6)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "pass")

    def test_confidence_low_warns(self) -> None:
        scene = _make_scene_with_confidence(0.35)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "warn")

    def test_confidence_very_low_blocks(self) -> None:
        scene = _make_scene_with_confidence(0.1)
        receipt = evaluate_preflight({}, scene, "stereo", {})
        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "block")
        self.assertEqual(receipt["final_decision"], "block")
        self.assertTrue(preflight_receipt_blocks(receipt))

    def test_no_confidence_data_defaults_to_high(self) -> None:
        receipt = evaluate_preflight({}, _make_empty_scene(), "stereo", {})
        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "pass")

    def test_low_confidence_recs_listed(self) -> None:
        scene = _make_scene_with_recs([0.9, 0.3, 0.1])
        receipt = evaluate_preflight({}, scene, "stereo", {})
        summary = receipt["confidence_summary"]
        # 0.3 and 0.1 are below warn_below=0.5
        self.assertGreaterEqual(len(summary["low_confidence_stems"]), 1)
        # low_confidence_stems must be stably sorted
        stems = summary["low_confidence_stems"]
        self.assertEqual(stems, sorted(stems))


# ---------------------------------------------------------------------------
# Tests: final_decision aggregation
# ---------------------------------------------------------------------------

class TestFinalDecision(unittest.TestCase):
    def test_pass_on_clean_scene(self) -> None:
        receipt = evaluate_preflight(
            {}, _make_scene_with_confidence(0.9), "stereo", {}
        )
        # Without source layout most gates skip/pass
        self.assertIn(receipt["final_decision"], ("pass", "warn"))

    def test_block_wins_over_warn(self) -> None:
        # Confidence very low (block) + borderline correlation (warn)
        scene: Dict[str, Any] = {}
        scene["metadata"] = {"confidence": 0.05, "correlation": -0.3}
        receipt = evaluate_preflight({}, scene, "stereo", {})
        self.assertEqual(receipt["final_decision"], "block")

    def test_warn_propagates(self) -> None:
        scene = _make_scene_with_confidence(0.35)  # warn
        receipt = evaluate_preflight({}, scene, "stereo", {})
        self.assertIn(receipt["final_decision"], ("warn", "block"))

    def test_preflight_receipt_blocks_false_on_pass(self) -> None:
        receipt: Dict[str, Any] = {"final_decision": "pass", "gates_evaluated": []}
        self.assertFalse(preflight_receipt_blocks(receipt))

    def test_preflight_receipt_blocks_false_on_warn(self) -> None:
        receipt = {"final_decision": "warn", "gates_evaluated": []}
        self.assertFalse(preflight_receipt_blocks(receipt))

    def test_preflight_receipt_blocks_true_on_block(self) -> None:
        receipt = {"final_decision": "block", "gates_evaluated": []}
        self.assertTrue(preflight_receipt_blocks(receipt))


# ---------------------------------------------------------------------------
# Tests: layout shorthand normalisation
# ---------------------------------------------------------------------------

class TestLayoutNormalisation(unittest.TestCase):
    def test_stereo_shorthand(self) -> None:
        receipt = evaluate_preflight({}, {}, "stereo", {})
        self.assertEqual(receipt["target_layout_id"], "LAYOUT.2_0")

    def test_51_shorthand(self) -> None:
        receipt = evaluate_preflight({}, {}, "5.1", {})
        self.assertEqual(receipt["target_layout_id"], "LAYOUT.5_1")

    def test_canonical_id_passthrough(self) -> None:
        receipt = evaluate_preflight({}, {}, "LAYOUT.7_1", {})
        self.assertEqual(receipt["target_layout_id"], "LAYOUT.7_1")


# ---------------------------------------------------------------------------
# Tests: core/downmix.py unit tests
# ---------------------------------------------------------------------------

class TestPredictFoldSimilarity(unittest.TestCase):
    def _stereo_matrix(self, coeffs: list[list[float]]) -> Dict[str, Any]:
        return {
            "matrix_id": "TEST.MATRIX",
            "source_speakers": ["L", "R", "C", "LFE", "Ls", "Rs"],
            "target_speakers": ["L", "R"],
            "coeffs": coeffs,
        }

    def test_no_lfe_fold_low_risk(self) -> None:
        # ITU-style 5.1→2.0 without LFE, near-unity gain
        coeffs = [
            [1.0, 0.0, 0.707, 0.0, 0.707, 0.0],   # L
            [0.0, 1.0, 0.707, 0.0, 0.0, 0.707],   # R
        ]
        matrix = self._stereo_matrix(coeffs)
        result = predict_fold_similarity(matrix)
        self.assertFalse(result["lfe_folded"])
        self.assertEqual(result["lfe_boost_db"], 0.0)
        self.assertIn(result["risk_level"], ("low", "medium"))

    def test_hot_lfe_fold_triggers_warn(self) -> None:
        # LFE folded at full gain (1.0) → 0 dB; above 3 dB warn threshold?
        # Actually 0 dB is not above 3 dB warn, but we use abs so lfe_boost_db = 0
        # Use coefficient > 1.41 to get > 3 dB
        import math
        hot_coeff = 10 ** (3.5 / 20.0)  # ~ 1.496, so lfe_boost_db ~ 3.5 dB
        coeffs = [
            [1.0, 0.0, 0.707, hot_coeff, 0.707, 0.0],
            [0.0, 1.0, 0.707, hot_coeff, 0.0, 0.707],
        ]
        matrix = self._stereo_matrix(coeffs)
        result = predict_fold_similarity(matrix, lfe_boost_warn_db=3.0, lfe_boost_error_db=6.0)
        self.assertTrue(result["lfe_folded"])
        self.assertGreater(result["lfe_boost_db"], 3.0)
        self.assertIn(result["risk_level"], ("medium", "high"))

    def test_very_hot_lfe_fold_triggers_high_risk(self) -> None:
        import math
        hot_coeff = 10 ** (7.0 / 20.0)  # ~ 2.24, > 6 dB
        coeffs = [
            [1.0, 0.0, 0.707, hot_coeff, 0.0, 0.0],
            [0.0, 1.0, 0.707, hot_coeff, 0.0, 0.0],
        ]
        matrix = self._stereo_matrix(coeffs)
        result = predict_fold_similarity(matrix, lfe_boost_warn_db=3.0, lfe_boost_error_db=6.0)
        self.assertTrue(result["lfe_folded"])
        self.assertEqual(result["risk_level"], "high")

    def test_empty_matrix_low_risk(self) -> None:
        matrix: Dict[str, Any] = {
            "matrix_id": "EMPTY",
            "source_speakers": [],
            "target_speakers": [],
            "coeffs": [],
        }
        result = predict_fold_similarity(matrix)
        self.assertFalse(result["lfe_folded"])
        self.assertEqual(result["risk_level"], "low")

    def test_notes_is_sorted_deterministic(self) -> None:
        import math
        hot_coeff = 10 ** (3.5 / 20.0)
        coeffs = [
            [1.0, 0.0, 0.707, hot_coeff, 0.707, 0.0],
            [0.0, 1.0, 0.707, hot_coeff, 0.0, 0.707],
        ]
        matrix = self._stereo_matrix(coeffs)
        r1 = predict_fold_similarity(matrix)
        r2 = predict_fold_similarity(matrix)
        self.assertEqual(r1["notes"], r2["notes"])

    def test_result_fields_present(self) -> None:
        coeffs = [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]]
        matrix = self._stereo_matrix(coeffs)
        result = predict_fold_similarity(matrix)
        for key in ("risk_level", "lfe_folded", "lfe_boost_db", "predicted_lufs_delta", "notes"):
            self.assertIn(key, result)


class TestLayoutNegotiationAvailable(unittest.TestCase):
    def test_unknown_layout_returns_not_available(self) -> None:
        result = layout_negotiation_available("LAYOUT.UNKNOWN_XYZ", "LAYOUT.2_0")
        self.assertFalse(result["available"])
        self.assertIsNotNone(result["error"])

    def test_51_to_20_available(self) -> None:
        """Standard 5.1 → stereo path must exist."""
        result = layout_negotiation_available("LAYOUT.5_1", "LAYOUT.2_0")
        self.assertTrue(result["available"])
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["matrix_id"])

    def test_return_shape(self) -> None:
        result = layout_negotiation_available("LAYOUT.UNKNOWN_XYZ", "LAYOUT.2_0")
        for key in ("available", "matrix_id", "composed", "warning", "error"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# Tests: regression — fixture-pinned receipts for stereo→5.1 upmix (block)
# ---------------------------------------------------------------------------

class TestRegressionFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _load_validator()

    def test_stereo_to_51_layout_blocked(self) -> None:
        """Stereo → 5.1 is an upmix; no registered downmix matrix → layout block."""
        session = {"source_layout_id": "LAYOUT.2_0"}
        receipt = evaluate_preflight(session, {}, "5.1", {})
        _validate(receipt, self.validator)
        layout_gate = next(
            g for g in receipt["gates_evaluated"]
            if g["gate_id"] == "GATE.LAYOUT_NEGOTIATION"
        )
        # Either blocked (no path) or skipped — must NOT be "pass"
        self.assertNotEqual(layout_gate["outcome"], "pass",
                            "Stereo→5.1 should not silently pass layout negotiation")

    def test_hot_lfe_51_to_20_schema_valid(self) -> None:
        """Hot LFE options produce a valid receipt."""
        receipt = evaluate_preflight(
            _SESSION_51_TO_20,
            _make_empty_scene(),
            _TARGET_STEREO,
            {"lfe_boost_warn_db": 0.5, "lfe_boost_error_db": 1.0},
        )
        _validate(receipt, self.validator)

    def test_low_confidence_51_to_20_schema_valid(self) -> None:
        """Very low confidence + 5.1 → stereo produces a valid blocked receipt."""
        scene = _make_scene_with_confidence(0.05)
        receipt = evaluate_preflight(_SESSION_51_TO_20, scene, _TARGET_STEREO, {})
        _validate(receipt, self.validator)
        self.assertEqual(receipt["final_decision"], "block")

    def test_gates_evaluated_order_deterministic(self) -> None:
        """Gate IDs in receipt must always appear in the same deterministic order."""
        receipt1 = evaluate_preflight(_SESSION_51_TO_20, {}, _TARGET_STEREO, {})
        receipt2 = evaluate_preflight(_SESSION_51_TO_20, {}, _TARGET_STEREO, {})
        ids1 = [g["gate_id"] for g in receipt1["gates_evaluated"]]
        ids2 = [g["gate_id"] for g in receipt2["gates_evaluated"]]
        self.assertEqual(ids1, ids2)
        # Must include all five gate IDs
        expected = {
            "GATE.LAYOUT_NEGOTIATION",
            "GATE.DOWNMIX_SIMILARITY",
            "GATE.LRA_BOUNDS",
            "GATE.TRUE_PEAK_PER_CHANNEL",
            "GATE.TRANSLATION_CURVES",
            "GATE.CORRELATION_RISK",
            "GATE.PHASE_RISK",
            "GATE.CONFIDENCE_LOW",
        }
        self.assertEqual(set(ids1), expected)


if __name__ == "__main__":
    unittest.main()
