import unittest
from pathlib import Path

from mmo.core.gates import apply_gates_to_report
from plugins.resolvers.polarity_check_resolver import PolarityCheckGuidanceResolver


class TestPolarityCheckGuidanceResolver(unittest.TestCase):
    def test_guidance_recommendation_and_gates(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "stem-surround",
                    "file_path": "surround.wav",
                    "channel_count": 6,
                }
            ]
        }
        issues = [
            {
                "issue_id": "ISSUE.IMAGING.NEGATIVE_CORRELATION_PAIR",
                "target": {"scope": "stem", "stem_id": "stem-surround"},
                "evidence": [
                    {
                        "evidence_id": "EVID.IMAGE.CORRELATION.FL_FR",
                        "value": -0.5,
                        "unit_id": "UNIT.CORRELATION",
                    },
                    {
                        "evidence_id": "EVID.IMAGE.CORRELATION.SL_SR",
                        "value": 0.2,
                        "unit_id": "UNIT.CORRELATION",
                    },
                    {
                        "evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG",
                        "value": "{}",
                    },
                ],
            }
        ]

        resolver = PolarityCheckGuidanceResolver()
        recommendations = resolver.resolve(session, {}, issues)
        self.assertEqual(len(recommendations), 1)
        rec = recommendations[0]
        self.assertEqual(rec["action_id"], "ACTION.DIAGNOSTIC.CHECK_POLARITY")
        self.assertEqual(rec["params"], [])
        self.assertIn("routing", rec.get("notes", ""))
        self.assertIn("mono", rec.get("notes", ""))

        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": session,
            "issues": issues,
            "recommendations": recommendations,
        }
        apply_gates_to_report(report, policy_path=Path("ontology/policies/gates.yaml"))
        rec = report["recommendations"][0]
        self.assertFalse(rec["eligible_auto_apply"])
        self.assertFalse(rec["eligible_render"])


if __name__ == "__main__":
    unittest.main()
