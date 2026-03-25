import unittest

from mmo.core.recommendations import (
    normalize_recommendation_contract,
    recommendation_snapshot,
)
from mmo.core.report_builders import build_minimal_report_for_downmix_qa


class TestRecommendationScopeContract(unittest.TestCase):
    def test_normalize_recommendation_contract_strips_legacy_target(self) -> None:
        recommendation = {
            "recommendation_id": "REC.TEST.SCOPE.001",
            "action_id": "ACTION.UTILITY.GAIN",
            "risk": "low",
            "requires_approval": False,
            "target": {"scope": "stem", "stem_id": "kick"},
            "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.0}],
        }

        normalized = normalize_recommendation_contract(recommendation)

        self.assertEqual(normalized.get("scope"), {"stem_id": "kick"})
        self.assertNotIn("target", normalized)

    def test_recommendation_snapshot_uses_scope_only(self) -> None:
        recommendation = normalize_recommendation_contract(
            {
                "recommendation_id": "REC.TEST.SCOPE.002",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "bed", "bed_id": "BED.AMB"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.5}],
            }
        )

        snapshot = recommendation_snapshot(recommendation)

        self.assertEqual(snapshot.get("scope"), {"bed_id": "BED.AMB"})
        self.assertNotIn("target", snapshot)

    def test_downmix_qa_report_recommendations_emit_scope_without_target(self) -> None:
        report = build_minimal_report_for_downmix_qa(
            qa_payload={
                "downmix_qa": {
                    "issues": [
                        {
                            "issue_id": "ISSUE.DOWNMIX.QA.TEST",
                            "severity": 50,
                            "confidence": 1.0,
                            "evidence": [
                                {"evidence_id": "EVID.TEST", "value": "x"},
                            ],
                        }
                    ],
                    "measurements": [
                        {
                            "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                            "value": 1.2,
                            "unit_id": "UNIT.LUFS",
                        }
                    ],
                    "src_path": "src.wav",
                    "ref_path": "ref.wav",
                    "log": "{}",
                    "policy_id": "POLICY.TEST",
                }
            }
        )

        recommendations = report.get("recommendations")
        self.assertIsInstance(recommendations, list)
        if not isinstance(recommendations, list):
            return

        self.assertGreaterEqual(len(recommendations), 2)
        for recommendation in recommendations:
            self.assertIn("scope", recommendation)
            self.assertNotIn("target", recommendation)
            self.assertEqual(recommendation.get("scope"), {"global": True})


if __name__ == "__main__":
    unittest.main()
