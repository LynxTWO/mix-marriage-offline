from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from wave import open as wave_open

from mmo.core.preflight import evaluate_preflight


class TestPreflightChaos(unittest.TestCase):
    def _find_gate(self, receipt: dict, gate_id: str) -> dict:
        for gate in receipt.get("gates_evaluated", []):
            if gate.get("gate_id") == gate_id:
                return gate
        self.fail(f"Gate {gate_id!r} not found")
        return {}

    def test_explicit_scene_skips_when_session_stems_missing(self) -> None:
        receipt = evaluate_preflight(
            {"scene_mode": "explicit"},
            {"objects": [{"object_id": "OBJ.001", "stem_id": "kick"}]},
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.SCENE_STEM_BINDING_OVERLAP")
        self.assertEqual(gate["outcome"], "skipped")
        details = gate.get("details", {})
        self.assertEqual(details.get("reason"), "session_stems_unavailable")
        self.assertEqual(receipt["scene_stem_overlap_summary"]["status"], "not_applicable")

    def test_explicit_scene_skips_when_no_scene_refs_exist(self) -> None:
        receipt = evaluate_preflight(
            {
                "scene_mode": "explicit",
                "session_stem_ids": ["kick", "snare"],
            },
            {"objects": [{"object_id": "OBJ.001"}]},
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.SCENE_STEM_BINDING_OVERLAP")
        self.assertEqual(gate["outcome"], "skipped")
        self.assertEqual(gate.get("details", {}).get("reason"), "scene_references_unavailable")

    def test_partial_overlap_can_be_forced_to_warn_by_lowering_threshold(self) -> None:
        receipt = evaluate_preflight(
            {
                "scene_mode": "explicit",
                "session_stem_ids": ["kick", "snare", "pad"],
            },
            {
                "objects": [
                    {"object_id": "OBJ.001", "stem_id": "kick"},
                    {"object_id": "OBJ.002", "stem_id": "ghost"},
                ]
            },
            "stereo",
            {"scene_binding_overlap_min_ratio": 0.49},
        )

        gate = self._find_gate(receipt, "GATE.SCENE_STEM_BINDING_OVERLAP")
        self.assertEqual(gate["outcome"], "warn")
        self.assertEqual(receipt["final_decision"], "warn")
        self.assertEqual(receipt["scene_stem_overlap_summary"]["overlap_ratio"], 0.5)

    def test_binaural_target_bypasses_layout_negotiation_even_without_source_layout(self) -> None:
        receipt = evaluate_preflight({}, {}, "binaural", {})

        gate = self._find_gate(receipt, "GATE.LAYOUT_NEGOTIATION")
        self.assertEqual(gate["outcome"], "pass")
        self.assertEqual(gate.get("details", {}).get("virtualization"), "binaural")

    def test_objective_meter_block_overrides_otherwise_clean_scene(self) -> None:
        receipt = evaluate_preflight(
            {"source_layout_id": "LAYOUT.5_1"},
            {
                "metadata": {
                    "objective_meters": {
                        "loudness_range_lu": 26.0,
                        "true_peak_per_channel_dbtp": {"L": -0.4, "R": -0.3},
                        "translation_curve_deltas_db": {"consumer": 4.5},
                    }
                }
            },
            "stereo",
            {},
        )

        self.assertEqual(receipt["final_decision"], "block")
        self.assertEqual(self._find_gate(receipt, "GATE.LRA_BOUNDS")["outcome"], "block")
        self.assertEqual(self._find_gate(receipt, "GATE.TRUE_PEAK_PER_CHANNEL")["outcome"], "block")
        self.assertEqual(self._find_gate(receipt, "GATE.TRANSLATION_CURVES")["outcome"], "block")

    def test_measured_similarity_gate_appears_when_rendered_file_provided(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "tiny.wav"
            with wave_open(str(wav_path), "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(b"\x00\x00" * 480)

            receipt = evaluate_preflight(
                {"source_layout_id": "LAYOUT.2_0"},
                {},
                "stereo",
                {},
                rendered_file=wav_path,
            )

        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertIn(gate["outcome"], {"pass", "warn", "block", "skipped"})
        self.assertIn("measured_similarity_checks", receipt)

    def test_invalid_rendered_file_yields_measured_similarity_skip_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bogus_path = Path(temp_dir) / "broken.wav"
            bogus_path.write_text("definitely not audio\n", encoding="utf-8")

            receipt = evaluate_preflight(
                {"source_layout_id": "LAYOUT.2_0"},
                {},
                "stereo",
                {},
                rendered_file=bogus_path,
            )

        gate = self._find_gate(receipt, "GATE.DOWNMIX_SIMILARITY_MEASURED")
        self.assertEqual(gate["outcome"], "skipped")
        self.assertEqual(gate.get("details", {}).get("reason"), "measurement_failed")


    # ------------------------------------------------------------------
    # Correlation and phase risk gates
    # ------------------------------------------------------------------

    def test_high_correlation_blocks_gate(self) -> None:
        receipt = evaluate_preflight(
            {},
            {"metadata": {"correlation": -0.75}},
            "stereo",
            {},
        )

        corr_gate = self._find_gate(receipt, "GATE.CORRELATION_RISK")
        phase_gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(corr_gate["outcome"], "block")
        self.assertEqual(corr_gate["details"]["correlation_risk"], "high")
        # polarity risk also triggers because value <= polarity_error (-0.6)
        self.assertEqual(phase_gate["outcome"], "block")
        self.assertEqual(receipt["final_decision"], "block")

    def test_medium_correlation_warns(self) -> None:
        receipt = evaluate_preflight(
            {},
            {"metadata": {"correlation": -0.3}},
            "stereo",
            {},
        )

        corr_gate = self._find_gate(receipt, "GATE.CORRELATION_RISK")
        self.assertEqual(corr_gate["outcome"], "warn")
        self.assertEqual(corr_gate["details"]["correlation_risk"], "medium")
        self.assertIn(receipt["final_decision"], {"warn", "block"})

    def test_polarity_inverted_metadata_blocks_phase_gate(self) -> None:
        receipt = evaluate_preflight(
            {},
            {"metadata": {"polarity_inverted": True}},
            "stereo",
            {},
        )

        phase_gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(phase_gate["outcome"], "block")
        self.assertEqual(phase_gate["details"]["polarity_risk"], "high")
        self.assertEqual(receipt["final_decision"], "block")

    def test_qa_polarity_issue_triggers_phase_gate_block(self) -> None:
        receipt = evaluate_preflight(
            {},
            {
                "qa_issues": [
                    {"issue_id": "ISSUE.PHASE.POLARITY_INVERSION", "value": -0.9}
                ]
            },
            "stereo",
            {},
        )

        phase_gate = self._find_gate(receipt, "GATE.PHASE_RISK")
        self.assertEqual(phase_gate["outcome"], "block")

    # ------------------------------------------------------------------
    # Confidence gates
    # ------------------------------------------------------------------

    def test_very_low_confidence_blocks(self) -> None:
        receipt = evaluate_preflight(
            {},
            {"metadata": {"confidence": 0.1}},
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "block")
        self.assertEqual(gate["details"]["confidence_level"], "very_low")
        self.assertEqual(receipt["final_decision"], "block")

    def test_low_confidence_warns(self) -> None:
        receipt = evaluate_preflight(
            {},
            {"metadata": {"confidence": 0.35}},
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.CONFIDENCE_LOW")
        self.assertEqual(gate["outcome"], "warn")
        self.assertEqual(gate["details"]["confidence_level"], "low")

    # ------------------------------------------------------------------
    # LRA, true-peak, translation-curve gates
    # ------------------------------------------------------------------

    def test_lra_below_warn_threshold_warns(self) -> None:
        # loudness_range_lu=1.0 is below the warn_low default of 1.5
        receipt = evaluate_preflight(
            {},
            {"metadata": {"objective_meters": {"loudness_range_lu": 1.0}}},
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.LRA_BOUNDS")
        self.assertEqual(gate["outcome"], "warn")
        self.assertAlmostEqual(gate["details"]["loudness_range_lu"], 1.0, places=3)

    def test_true_peak_at_warn_but_not_error_threshold(self) -> None:
        # -1.5 dBTP is above warn default (-2.0) but below error default (-1.0)
        receipt = evaluate_preflight(
            {},
            {
                "metadata": {
                    "objective_meters": {
                        "true_peak_per_channel_dbtp": {"L": -1.5, "R": -3.0}
                    }
                }
            },
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.TRUE_PEAK_PER_CHANNEL")
        self.assertEqual(gate["outcome"], "warn")
        self.assertEqual(gate["details"]["hottest_channel"], "L")

    def test_true_peak_skipped_when_channel_dict_is_empty(self) -> None:
        receipt = evaluate_preflight(
            {},
            {
                "metadata": {
                    "objective_meters": {"true_peak_per_channel_dbtp": {}}
                }
            },
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.TRUE_PEAK_PER_CHANNEL")
        self.assertEqual(gate["outcome"], "skipped")
        self.assertEqual(gate["details"]["reason"], "true_peak_per_channel_unavailable")

    def test_translation_curve_warn_threshold(self) -> None:
        # 3.0 dB is above warn default (2.5) but below error default (4.0)
        receipt = evaluate_preflight(
            {},
            {
                "metadata": {
                    "objective_meters": {
                        "translation_curve_deltas_db": {"consumer": 3.0}
                    }
                }
            },
            "stereo",
            {},
        )

        gate = self._find_gate(receipt, "GATE.TRANSLATION_CURVES")
        self.assertEqual(gate["outcome"], "warn")


if __name__ == "__main__":
    unittest.main()
