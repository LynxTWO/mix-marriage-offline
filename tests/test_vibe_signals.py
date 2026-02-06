from __future__ import annotations

import unittest

from mmo.core.vibe_signals import derive_vibe_signals


def _base_report() -> dict:
    return {
        "issues": [],
        "recommendations": [],
        "mix_complexity": {
            "density_mean": 0.0,
            "top_masking_pairs_count": 0,
            "top_masking_pairs": [],
            "masking_risk": {},
        },
    }


class TestVibeSignals(unittest.TestCase):
    def test_low_levels_without_risk_issues(self) -> None:
        report = _base_report()
        report["mix_complexity"]["density_mean"] = 1.8
        report["mix_complexity"]["top_masking_pairs_count"] = 1

        signals = derive_vibe_signals(report)

        self.assertEqual(
            signals,
            {
                "density_level": "low",
                "masking_level": "low",
                "translation_risk": "low",
                "notes": [],
            },
        )

    def test_medium_levels_and_extreme_recommendation_sets_medium_translation(self) -> None:
        report = _base_report()
        report["mix_complexity"]["density_mean"] = 3.2
        report["mix_complexity"]["top_masking_pairs_count"] = 2
        report["recommendations"] = [
            {
                "recommendation_id": "REC.TEST.001",
                "action_id": "ACTION.TEST",
                "risk": "medium",
                "requires_approval": False,
                "params": [],
                "extreme": True,
            }
        ]

        signals = derive_vibe_signals(report)

        self.assertEqual(
            signals,
            {
                "density_level": "medium",
                "masking_level": "medium",
                "translation_risk": "medium",
                "notes": [],
            },
        )

    def test_high_levels_add_musician_language_notes(self) -> None:
        report = _base_report()
        report["mix_complexity"]["density_mean"] = 4.2
        report["mix_complexity"]["top_masking_pairs_count"] = 5
        report["issues"] = [
            {
                "issue_id": "ISSUE.VALIDATION.LOSSY_STEMS_DETECTED",
                "severity": 60,
                "confidence": 1.0,
                "evidence": [{"evidence_id": "EVID.TEST", "value": "x"}],
            }
        ]

        signals = derive_vibe_signals(report)

        self.assertEqual(signals["density_level"], "high")
        self.assertEqual(signals["masking_level"], "high")
        self.assertEqual(signals["translation_risk"], "high")
        self.assertEqual(
            signals["notes"],
            [
                "Lots of layers hitting at once. Make space with arrangement or gentle carving.",
                "Midrange is crowded. Decide what leads and let the rest support.",
                "Translation risk is elevated. Fix clipping/lossy files and check mono.",
            ],
        )

    def test_masking_score_fallback_when_count_is_missing(self) -> None:
        report = _base_report()
        report["mix_complexity"] = {
            "density_mean": 2.0,
            "top_masking_pairs": [
                {"stem_a": "a", "stem_b": "b", "score": 0.91},
            ],
        }

        signals = derive_vibe_signals(report)

        self.assertEqual(signals["masking_level"], "high")

    def test_downmix_qa_delta_gate_reject_sets_high_translation_risk(self) -> None:
        report = _base_report()
        report["recommendations"] = [
            {
                "recommendation_id": "REC.DOWNMIX.RENDER.001",
                "gate_results": [
                    {
                        "gate_id": "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT",
                        "context": "render",
                        "outcome": "reject",
                    }
                ],
            }
        ]

        signals = derive_vibe_signals(report)

        self.assertEqual(signals["translation_risk"], "high")
        self.assertIn(
            "Translation risk is elevated. Fix clipping/lossy files and check mono.",
            signals["notes"],
        )

    def test_derive_is_deterministic_for_same_input(self) -> None:
        report = _base_report()
        report["mix_complexity"]["density_mean"] = 3.0
        report["mix_complexity"]["top_masking_pairs_count"] = 4

        first = derive_vibe_signals(report)
        second = derive_vibe_signals(report)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
