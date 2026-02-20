"""Unit tests for deterministic plugin-chain param validation."""

from __future__ import annotations

import unittest

from mmo.core.render_run_audio import validate_and_normalize_plugin_chain


class TestPluginChainValidation(unittest.TestCase):
    def test_invalid_params_have_stable_error_order(self) -> None:
        raw_chain = [
            {
                "plugin_id": "gain_v0",
                "params": {
                    "gain_db": -6.0,
                    "bypass": "yes",
                    "macro_mix": "bad",
                    "junk": 1,
                },
            }
        ]

        with self.assertRaises(ValueError) as exc_a:
            validate_and_normalize_plugin_chain(
                raw_chain,
                chain_label="plugin_chain",
                lenient_numeric_bounds=True,
            )
        with self.assertRaises(ValueError) as exc_b:
            validate_and_normalize_plugin_chain(
                raw_chain,
                chain_label="plugin_chain",
                lenient_numeric_bounds=True,
            )

        message_a = str(exc_a.exception)
        message_b = str(exc_b.exception)
        self.assertEqual(message_a, message_b)
        self.assertIn("plugin_chain validation failed:", message_a)
        self.assertIn("plugin_chain[1].params has unknown key(s): junk.", message_a)
        self.assertIn("plugin_chain[1].params.bypass must be a boolean.", message_a)
        self.assertIn("plugin_chain[1].params.macro_mix must be a number.", message_a)
        self.assertLess(
            message_a.index("unknown key(s): junk"),
            message_a.index("params.bypass must be a boolean"),
        )
        self.assertLess(
            message_a.index("params.bypass must be a boolean"),
            message_a.index("params.macro_mix must be a number"),
        )

    def test_lenient_mode_clamps_numeric_params_and_records_notes(self) -> None:
        normalized, notes = validate_and_normalize_plugin_chain(
            [
                {
                    "plugin_id": "gain_v0",
                    "params": {
                        "gain_db": 99.0,
                        "macro_mix": 200.0,
                    },
                }
            ],
            chain_label="plugin_chain",
            lenient_numeric_bounds=True,
        )

        self.assertEqual(
            normalized,
            [
                {
                    "plugin_id": "gain_v0",
                    "params": {
                        "gain_db": 24.0,
                        "macro_mix": 100.0,
                    },
                }
            ],
        )
        self.assertEqual(len(notes), 2)
        self.assertIn(
            "plugin_chain[1].params.gain_db clamped from 99.0 to 24.0",
            notes[0],
        )
        self.assertIn(
            "plugin_chain[1].params.macro_mix clamped from 200.0 to 100.0",
            notes[1],
        )

    def test_tilt_eq_requires_tilt_and_pivot_params(self) -> None:
        raw_chain = [
            {
                "plugin_id": "tilt_eq_v0",
                "params": {
                    "tilt_db": 2.0,
                },
            }
        ]

        with self.assertRaises(ValueError) as exc:
            validate_and_normalize_plugin_chain(
                raw_chain,
                chain_label="plugin_chain",
                lenient_numeric_bounds=True,
            )

        message = str(exc.exception)
        self.assertIn("plugin_chain validation failed:", message)
        self.assertIn("plugin_chain[1].params.pivot_hz is required.", message)

    def test_tilt_eq_lenient_mode_clamps_numeric_params_and_records_notes(self) -> None:
        normalized, notes = validate_and_normalize_plugin_chain(
            [
                {
                    "plugin_id": "tilt_eq_v0",
                    "params": {
                        "tilt_db": 99.0,
                        "pivot_hz": 50.0,
                        "macro_mix": 200.0,
                    },
                }
            ],
            chain_label="plugin_chain",
            lenient_numeric_bounds=True,
        )

        self.assertEqual(
            normalized,
            [
                {
                    "plugin_id": "tilt_eq_v0",
                    "params": {
                        "tilt_db": 6.0,
                        "pivot_hz": 200.0,
                        "macro_mix": 100.0,
                    },
                }
            ],
        )
        self.assertEqual(len(notes), 3)
        self.assertIn(
            "plugin_chain[1].params.macro_mix clamped from 200.0 to 100.0",
            notes[0],
        )
        self.assertIn(
            "plugin_chain[1].params.pivot_hz clamped from 50.0 to 200.0",
            notes[1],
        )
        self.assertIn(
            "plugin_chain[1].params.tilt_db clamped from 99.0 to 6.0",
            notes[2],
        )


if __name__ == "__main__":
    unittest.main()
