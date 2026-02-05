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
        self.assertTrue(recommendations[1]["eligible_render"])
        self.assertEqual(
            [(result["context"], result["reason_id"]) for result in gate_results_large],
            [
                ("auto_apply", "REASON.GAIN_TOO_LARGE"),
            ],
        )
        self.assertEqual(gate_results_large[0]["details"]["param_id"], "PARAM.GAIN.DB")
        self.assertEqual(gate_results_large[0]["details"]["value"], -8.0)
        self.assertEqual(gate_results_large[0]["details"]["abs_value"], 8.0)
        self.assertEqual(gate_results_large[0]["details"]["limit"], 3.0)
        self.assertEqual(gate_results_large[0]["details"]["limit_kind"], "auto_apply_abs_max")
        self.assertTrue(gate_results_large[0]["details"]["use_abs"])

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

    def test_gates_metric_delta_limit(self) -> None:
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
                    "recommendation_id": "REC.DOWNMIX.QA.CORR_DELTA",
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.DOWNMIX.QA.CORR_DELTA",
                            "value": 0.2,
                            "unit_id": "UNIT.CORRELATION",
                        }
                    ],
                }
            ],
        }

        policy_path = Path("ontology/policies/gates.yaml")
        apply_gates_to_report(report, policy_path=policy_path)

        rec = report["recommendations"][0]
        delta_results = [
            result
            for result in rec["gate_results"]
            if result["gate_id"] == "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"
        ]
        self.assertEqual(
            {(result["context"], result["outcome"]) for result in delta_results},
            {
                ("suggest", "suggest_only"),
                ("auto_apply", "suggest_only"),
            },
        )
        self.assertFalse(rec["eligible_auto_apply"])
        self.assertTrue(rec["eligible_render"])

    def test_count_limit_can_block_auto_apply_but_allow_render(self) -> None:
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
                    "recommendation_id": "REC.EQ.BANDS.SIX",
                    "action_id": "ACTION.EQ.PEAK",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.EQ.GAIN_DB",
                            "value": 1.0,
                            "unit_id": "UNIT.DB",
                        }
                        for _ in range(6)
                    ],
                }
            ],
        }

        policy_path = Path("ontology/policies/gates.yaml")
        apply_gates_to_report(report, policy_path=policy_path)

        rec = report["recommendations"][0]
        self.assertFalse(rec["eligible_auto_apply"])
        self.assertTrue(rec["eligible_render"])
        self.assertEqual(
            [
                (result["context"], result["outcome"], result["reason_id"])
                for result in rec["gate_results"]
            ],
            [("auto_apply", "suggest_only", "REASON.EQ_BANDS_TOO_MANY")],
        )
        self.assertEqual(rec["gate_results"][0]["details"]["limit"], 4.0)
        self.assertEqual(rec["gate_results"][0]["details"]["limit_kind"], "auto_apply_max")

    def test_profile_guide_disables_auto_apply_but_not_render(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
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
                }
            ],
        }

        apply_gates_to_report(
            report,
            policy_path=Path("ontology/policies/gates.yaml"),
            profile_id="PROFILE.GUIDE",
            profiles_path=Path("ontology/policies/authority_profiles.yaml"),
        )

        rec = report["recommendations"][0]
        self.assertEqual(report.get("profile_id"), "PROFILE.GUIDE")
        self.assertFalse(rec["eligible_auto_apply"])
        self.assertTrue(rec["eligible_render"])
        self.assertEqual(
            [(result["context"], result["reason_id"]) for result in rec["gate_results"]],
            [("auto_apply", "REASON.PROFILE_AUTO_APPLY_DISABLED")],
        )

    def test_profile_full_send_expands_auto_apply_for_gain(self) -> None:
        base_report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [
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
                }
            ],
        }
        full_send_report = json.loads(json.dumps(base_report))

        apply_gates_to_report(
            base_report,
            policy_path=Path("ontology/policies/gates.yaml"),
        )
        apply_gates_to_report(
            full_send_report,
            policy_path=Path("ontology/policies/gates.yaml"),
            profile_id="PROFILE.FULL_SEND",
            profiles_path=Path("ontology/policies/authority_profiles.yaml"),
        )

        default_rec = base_report["recommendations"][0]
        full_send_rec = full_send_report["recommendations"][0]
        self.assertFalse(default_rec["eligible_auto_apply"])
        self.assertTrue(full_send_rec["eligible_auto_apply"])
        self.assertTrue(full_send_rec["eligible_render"])
        self.assertEqual(full_send_report.get("profile_id"), "PROFILE.FULL_SEND")

    def test_schema_validation_with_and_without_profile_id(self) -> None:
        schema = json.loads(Path("schemas/report.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)

        report_without_profile = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.NO.PROFILE",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [],
        }
        report_with_profile = {
            **report_without_profile,
            "report_id": "REPORT.WITH.PROFILE",
            "profile_id": "PROFILE.ASSIST",
        }

        validator.validate(report_without_profile)
        validator.validate(report_with_profile)


if __name__ == "__main__":
    unittest.main()
