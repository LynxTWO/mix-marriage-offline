import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.scene import build_scene_from_report


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


class TestSceneContract(unittest.TestCase):
    def test_build_scene_from_report_is_deterministic_and_schema_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.SCENE.CONTRACT.TEST",
                "project_id": "PROJECT.SCENE.CONTRACT.TEST",
                "profile_id": "PROFILE.ASSIST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "STEM.B",
                            "file_path": "stems/stem_b.wav",
                            "channel_count": 1,
                        },
                        {
                            "stem_id": "STEM.A",
                            "file_path": "stems/stem_a.wav",
                            "channel_count": 2,
                        },
                        {
                            "stem_id": "STEM.C",
                            "file_path": "stems/stem_c.wav",
                        },
                    ],
                },
                "issues": [],
                "recommendations": [],
                "run_config": {
                    "schema_version": "0.1.0",
                    "preset_id": "PRESET.SAFE_CLEANUP",
                },
                "vibe_signals": {
                    "density_level": "low",
                    "masking_level": "medium",
                    "translation_risk": "high",
                    "notes": ["Keep vocals clear."],
                },
            }
            timeline = {
                "schema_version": "0.1.0",
                "sections": [
                    {"id": "SEC.001", "label": "Intro", "start_s": 0.0, "end_s": 10.0}
                ],
            }

            scene_a = build_scene_from_report(
                report,
                timeline=timeline,
                lock_hash="abcdef1234567890",
            )
            scene_b = build_scene_from_report(
                report,
                timeline=timeline,
                lock_hash="abcdef1234567890",
            )

            self.assertEqual(scene_a, scene_b)
            validator.validate(scene_a)

            self.assertEqual(
                [item["stem_id"] for item in scene_a["objects"]],
                ["STEM.A", "STEM.B", "STEM.C"],
            )
            self.assertEqual(scene_a["objects"][2]["channel_count"], 1)

            for entry in scene_a["objects"]:
                intent = entry["intent"]
                self.assertEqual(intent["confidence"], 0.0)
                self.assertEqual(intent["locks"], [])
                self.assertNotIn("position", intent)
                self.assertNotIn("width", intent)
                self.assertNotIn("depth", intent)

            self.assertEqual(scene_a["source"]["created_from"], "analyze")
            self.assertEqual(scene_a["scene_id"], "SCENE.REPORT.SCENE.CONTRACT.TEST")


if __name__ == "__main__":
    unittest.main()
