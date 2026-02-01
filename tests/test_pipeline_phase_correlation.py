import json
import unittest
from pathlib import Path

import jsonschema

from mmo.core.pipeline import load_plugins, run_detectors, run_resolvers


class TestPipelinePhaseCorrelation(unittest.TestCase):
    def test_negative_correlation_pipeline(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {
                "stems": [
                    {
                        "stem_id": "stem-phase",
                        "file_path": "phase.wav",
                        "measurements": [
                            {
                                "evidence_id": "EVID.IMAGE.CORRELATION",
                                "value": -0.5,
                                "unit_id": "UNIT.CORRELATION",
                            }
                        ],
                    }
                ]
            },
            "issues": [],
            "recommendations": [],
        }

        plugins = load_plugins(Path("plugins"))
        run_detectors(report, plugins)
        run_resolvers(report, plugins)

        schema_path = Path("schemas/report.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(report)

        issues = report.get("issues", [])
        recommendations = report.get("recommendations", [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(recommendations), 1)

        issue = issues[0]
        self.assertEqual(issue["issue_id"], "ISSUE.IMAGING.NEGATIVE_CORRELATION")
        self.assertEqual(issue.get("target", {}).get("stem_id"), "stem-phase")

        rec = recommendations[0]
        self.assertEqual(rec["issue_id"], "ISSUE.IMAGING.NEGATIVE_CORRELATION")
        self.assertEqual(rec["action_id"], "ACTION.UTILITY.POLARITY_INVERT")
        self.assertEqual(rec["risk"], "medium")
        self.assertTrue(rec["requires_approval"])

        evidence_ids = [entry["evidence_id"] for entry in rec.get("evidence", [])]
        self.assertIn("EVID.IMAGE.CORRELATION", evidence_ids)


if __name__ == "__main__":
    unittest.main()
