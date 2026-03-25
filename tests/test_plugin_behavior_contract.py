from __future__ import annotations

import unittest

from mmo.core.plugin_behavior import (
    evaluate_behavior_contract,
    validate_behavior_contract_definition,
)


class TestPluginBehaviorContract(unittest.TestCase):
    def test_auto_apply_resolver_defaults_to_conservative_bounds(self) -> None:
        result = evaluate_behavior_contract(
            plugin_type="resolver",
            capabilities={"supported_contexts": ["suggest", "auto_apply"]},
            behavior_contract=None,
            metrics_delta={
                "integrated_lufs": 0.05,
                "true_peak_dbtp": 0.08,
            },
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["applied"])
        self.assertEqual(
            result["contract"],
            {
                "loudness_behavior": "preserve",
                "max_integrated_lufs_delta": 0.1,
                "peak_behavior": "bounded",
                "max_true_peak_delta_db": 0.1,
                "gain_compensation": "required",
            },
        )
        self.assertEqual(result["violations"], [])

    def test_auto_apply_resolver_flags_lufs_and_true_peak_overages(self) -> None:
        result = evaluate_behavior_contract(
            plugin_type="resolver",
            capabilities={"supported_contexts": ["suggest", "auto_apply"]},
            behavior_contract=None,
            metrics_delta={
                "integrated_lufs": 0.25,
                "true_peak_dbtp": 0.3,
            },
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["applied"])
        self.assertEqual(
            [violation["metric"] for violation in result["violations"]],
            ["integrated_lufs", "true_peak_dbtp"],
        )

    def test_detector_may_omit_behavior_contract(self) -> None:
        result = evaluate_behavior_contract(
            plugin_type="detector",
            capabilities={"supported_contexts": ["suggest"]},
            behavior_contract=None,
            metrics_delta={
                "integrated_lufs": 3.0,
                "true_peak_dbtp": 3.0,
            },
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["applied"])
        self.assertIsNone(result["contract"])
        self.assertEqual(result["violations"], [])

    def test_looser_bounds_require_explicit_rationale(self) -> None:
        missing_rationale = validate_behavior_contract_definition(
            plugin_type="renderer",
            capabilities={"supported_contexts": ["render", "auto_apply"]},
            behavior_contract={
                "loudness_behavior": "bounded",
                "max_integrated_lufs_delta": 0.5,
                "peak_behavior": "bounded",
                "max_true_peak_delta_db": 0.5,
            },
        )
        explicit_rationale = validate_behavior_contract_definition(
            plugin_type="renderer",
            capabilities={"supported_contexts": ["render", "auto_apply"]},
            behavior_contract={
                "loudness_behavior": "bounded",
                "max_integrated_lufs_delta": 0.5,
                "peak_behavior": "bounded",
                "max_true_peak_delta_db": 0.5,
                "rationale": "This renderer intentionally writes a checksum tone.",
            },
        )

        self.assertTrue(missing_rationale)
        self.assertEqual(explicit_rationale, [])


if __name__ == "__main__":
    unittest.main()
