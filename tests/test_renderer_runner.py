import unittest
from pathlib import Path

from mmo.core.gates import apply_gates_to_report
from mmo.core.pipeline import load_plugins, run_renderers


class TestRendererRunner(unittest.TestCase):
    def test_run_renderers_filters_and_records_skipped(self) -> None:
        eligible_id = "REC.RENDER.ELIGIBLE"
        blocked_id = "REC.RENDER.BLOCKED"
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
                    "recommendation_id": eligible_id,
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.DOWNMIX.POLICY_ID",
                            "value": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.TARGET_LAYOUT_ID",
                            "value": "LAYOUT.2_0",
                        },
                    ],
                },
                {
                    "recommendation_id": blocked_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -8.0,
                        }
                    ],
                },
            ],
        }

        apply_gates_to_report(report, policy_path=Path("ontology/policies/gates.yaml"))
        plugins = load_plugins(Path("plugins"))
        manifests = run_renderers(report, plugins)

        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest.get("renderer_id"), "PLUGIN.RENDERER.SAFE")

        skipped = manifest.get("skipped")
        self.assertIsInstance(skipped, list)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["recommendation_id"], blocked_id)
        self.assertIn("GATE.MAX_GAIN_DB", skipped[0]["gate_summary"])

        self.assertEqual(manifest.get("received_recommendation_ids"), [eligible_id])


if __name__ == "__main__":
    unittest.main()
