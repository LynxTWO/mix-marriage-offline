import json
import unittest
from pathlib import Path

import jsonschema

from mmo.core.pipeline import load_plugins, run_detectors, run_resolvers


class TestPipelineClipHeadroom(unittest.TestCase):
    def test_clip_and_headroom_pipeline(self) -> None:
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
                        "stem_id": "stem-clip",
                        "file_path": "clip.wav",
                        "measurements": [
                            {
                                "evidence_id": "EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
                                "value": 4,
                                "unit_id": "UNIT.COUNT",
                            },
                            {
                                "evidence_id": "EVID.METER.SAMPLE_PEAK_DBFS",
                                "value": -0.5,
                                "unit_id": "UNIT.DBFS",
                            },
                        ],
                    },
                    {
                        "stem_id": "stem-headroom",
                        "file_path": "headroom.wav",
                        "measurements": [
                            {
                                "evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT",
                                "value": 0,
                                "unit_id": "UNIT.COUNT",
                            },
                            {
                                "evidence_id": "EVID.METER.PEAK_DBFS",
                                "value": -0.2,
                                "unit_id": "UNIT.DBFS",
                            },
                        ],
                    },
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
        self.assertEqual(len(issues), 2)
        self.assertEqual(len(recommendations), 2)

        issue_pairs = [(issue["issue_id"], issue.get("target", {}).get("stem_id")) for issue in issues]
        self.assertEqual(
            issue_pairs,
            [
                ("ISSUE.SAFETY.CLIPPING_SAMPLES", "stem-clip"),
                ("ISSUE.SAFETY.INSUFFICIENT_HEADROOM", "stem-headroom"),
            ],
        )

        rec_pairs = [
            (rec["issue_id"], rec.get("target", {}).get("stem_id"), rec["params"][0]["value"])
            for rec in recommendations
        ]
        self.assertEqual(
            rec_pairs,
            [
                ("ISSUE.SAFETY.CLIPPING_SAMPLES", "stem-clip", -3.0),
                ("ISSUE.SAFETY.INSUFFICIENT_HEADROOM", "stem-headroom", -0.8),
            ],
        )


if __name__ == "__main__":
    unittest.main()
