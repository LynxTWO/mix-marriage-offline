import json
import unittest
from pathlib import Path

import jsonschema

from mmo.core.gates import apply_gates_to_report


class TestGates(unittest.TestCase):
    def test_gates_evaluate_recommendations(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": [{"stem_id": "stem-1", "file_path": "a.wav"}]},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.GAIN.SMALL",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -2.0,
                            "unit_id": "UNIT.DB",
                        }
                    ],
                },
                {
                    "recommendation_id": "REC.GAIN.LARGE",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -8.0,
                            "unit_id": "UNIT.DB",
                        }
                    ],
                },
                {
                    "recommendation_id": "REC.POLARITY.INVERT",
                    "action_id": "ACTION.UTILITY.POLARITY_INVERT",
                    "risk": "medium",
                    "requires_approval": True,
                    "params": [],
                },
            ],
        }

        policy_path = Path("ontology/policies/gates.yaml")
        apply_gates_to_report(report, policy_path=policy_path)

        schema_path = Path("schemas/report.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(report)

        recommendations = report["recommendations"]

        self.assertTrue(recommendations[0]["eligible_auto_apply"])
        self.assertTrue(recommendations[0]["eligible_render"])
        self.assertEqual(recommendations[0]["gate_results"], [])

        gate_results_large = recommendations[1]["gate_results"]
        self.assertFalse(recommendations[1]["eligible_auto_apply"])
        self.assertFalse(recommendations[1]["eligible_render"])
        self.assertEqual(
            [(result["context"], result["reason_id"]) for result in gate_results_large],
            [
                ("auto_apply", "REASON.GAIN_TOO_LARGE"),
                ("render", "REASON.GAIN_TOO_LARGE"),
            ],
        )

        gate_results_polarity = recommendations[2]["gate_results"]
        self.assertFalse(recommendations[2]["eligible_auto_apply"])
        self.assertFalse(recommendations[2]["eligible_render"])
        self.assertEqual(
            [(result["context"], result["reason_id"]) for result in gate_results_polarity],
            [
                ("auto_apply", "REASON.APPROVAL_REQUIRED"),
                ("render", "REASON.APPROVAL_REQUIRED"),
            ],
        )

    def test_gates_action_prefix_limit(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.DIAGNOSTIC.CHECK_POLARITY.001",
                    "action_id": "ACTION.DIAGNOSTIC.CHECK_POLARITY",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [],
                }
            ],
        }

        policy_path = Path("ontology/policies/gates.yaml")
        apply_gates_to_report(report, policy_path=policy_path)

        rec = report["recommendations"][0]
        self.assertFalse(rec["eligible_auto_apply"])
        self.assertFalse(rec["eligible_render"])
        self.assertEqual(
            [(result["context"], result["reason_id"]) for result in rec["gate_results"]],
            [
                ("auto_apply", "REASON.DIAGNOSTIC_SUGGEST_ONLY"),
                ("render", "REASON.DIAGNOSTIC_SUGGEST_ONLY"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
