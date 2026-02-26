from __future__ import annotations

import unittest
from typing import Any

from mmo.core.meters import (
    assess_translation_curves,
    compute_lra_lu,
    compute_true_peak_per_channel_dbtp,
)
from mmo.core.preflight import evaluate_preflight


_LAYOUT_FIXTURES: dict[str, dict[str, Any]] = {
    "mono": {
        "channels": 1,
        "labels": ["M"],
        "interleaved_samples": [0.0, 0.1, -0.2, 0.3, -0.4, 0.25, -0.15, 0.05],
    },
    "stereo": {
        "channels": 2,
        "labels": ["L", "R"],
        "interleaved_samples": [
            0.0, 0.0,
            0.25, 0.24,
            -0.4, -0.35,
            0.55, 0.52,
            -0.5, -0.46,
            0.2, 0.18,
        ],
    },
}

_CURVE_FIXTURE_STEREO_SAFE = {
    63.0: 0.1,
    125.0: 0.0,
    250.0: -0.1,
    500.0: 0.0,
    1000.0: 0.1,
    2000.0: 0.0,
    4000.0: -0.1,
    8000.0: 0.0,
}


class TestAdvancedObjectiveMeters(unittest.TestCase):
    def test_compute_lra_lu_is_deterministic(self) -> None:
        short_term = [-20.0, -18.5, -16.0, -14.5, -13.0, -12.0, -11.5]
        first = compute_lra_lu(short_term)
        second = compute_lra_lu(short_term)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        if isinstance(first, float):
            self.assertGreater(first, 0.0)

    def test_true_peak_per_channel_is_layout_aware(self) -> None:
        mono = _LAYOUT_FIXTURES["mono"]
        stereo = _LAYOUT_FIXTURES["stereo"]

        mono_peaks = compute_true_peak_per_channel_dbtp(
            mono["interleaved_samples"],
            channels=mono["channels"],
            channel_labels=mono["labels"],
        )
        stereo_peaks = compute_true_peak_per_channel_dbtp(
            stereo["interleaved_samples"],
            channels=stereo["channels"],
            channel_labels=stereo["labels"],
        )

        self.assertEqual(sorted(mono_peaks.keys()), ["M"])
        self.assertEqual(sorted(stereo_peaks.keys()), ["L", "R"])
        self.assertLess(float(stereo_peaks["R"]), 0.0)
        self.assertLess(float(stereo_peaks["L"]), 0.0)

    def test_translation_curve_profiles_include_stereo_mono_earbuds_car(self) -> None:
        summary = assess_translation_curves(_CURVE_FIXTURE_STEREO_SAFE)
        profiles = summary.get("profiles")
        self.assertIsInstance(profiles, list)
        ids = [
            item.get("profile_id")
            for item in profiles
            if isinstance(item, dict)
        ]
        self.assertEqual(ids, ["car", "earbuds", "mono", "stereo"])

        stereo_row = next(
            item for item in profiles
            if isinstance(item, dict) and item.get("profile_id") == "stereo"
        )
        self.assertEqual(stereo_row.get("status"), "low")


class TestPreflightObjectiveGates(unittest.TestCase):
    def _find_gate(self, receipt: dict[str, Any], gate_id: str) -> dict[str, Any]:
        for gate in receipt.get("gates_evaluated", []):
            if isinstance(gate, dict) and gate.get("gate_id") == gate_id:
                return gate
        self.fail(f"Gate missing from receipt: {gate_id}")
        return {}

    def test_new_objective_gates_are_integrated(self) -> None:
        scene = {
            "metadata": {
                "objective_meters": {
                    "loudness_range_lu": 12.0,
                    "true_peak_per_channel_dbtp": {"L": -3.1, "R": -3.0},
                    "translation_curve_levels_db": dict(_CURVE_FIXTURE_STEREO_SAFE),
                }
            }
        }
        receipt = evaluate_preflight(
            {"source_layout_id": "LAYOUT.5_1"},
            scene,
            "stereo",
            {},
        )

        self.assertEqual(self._find_gate(receipt, "GATE.LRA_BOUNDS")["outcome"], "pass")
        self.assertEqual(
            self._find_gate(receipt, "GATE.TRUE_PEAK_PER_CHANNEL")["outcome"],
            "pass",
        )
        self.assertEqual(
            self._find_gate(receipt, "GATE.TRANSLATION_CURVES")["outcome"],
            "pass",
        )

    def test_objective_gates_block_on_extreme_values(self) -> None:
        scene = {
            "objective_meters": {
                "loudness_range_lu": 30.0,
                "true_peak_per_channel_dbtp": {"L": -0.2, "R": -0.8},
                "translation_curve_deltas_db": {"stereo": 5.5, "mono": 4.8},
            }
        }
        receipt = evaluate_preflight(
            {"source_layout_id": "LAYOUT.5_1"},
            scene,
            "LAYOUT.2_0",
            {},
        )
        self.assertEqual(self._find_gate(receipt, "GATE.LRA_BOUNDS")["outcome"], "block")
        self.assertEqual(
            self._find_gate(receipt, "GATE.TRUE_PEAK_PER_CHANNEL")["outcome"],
            "block",
        )
        self.assertEqual(
            self._find_gate(receipt, "GATE.TRANSLATION_CURVES")["outcome"],
            "block",
        )
        self.assertEqual(receipt.get("final_decision"), "block")


if __name__ == "__main__":
    unittest.main()
