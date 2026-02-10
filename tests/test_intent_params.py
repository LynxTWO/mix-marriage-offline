import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.intent_params import load_intent_params, validate_scene_intent


class TestIntentParams(unittest.TestCase):
    def test_intent_params_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "intent_params.schema.json"
        registry_path = repo_root / "ontology" / "intent_params.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_intent_params_returns_schema_version_and_params(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_intent_params(repo_root / "ontology" / "intent_params.yaml")

        self.assertEqual(registry.get("schema_version"), "0.1.0")
        params = registry.get("params")
        self.assertIsInstance(params, dict)
        if not isinstance(params, dict):
            return
        self.assertIn("INTENT.POSITION.AZIMUTH_DEG", params)
        self.assertIn("INTENT.WIDTH", params)
        self.assertIn("INTENT.DEPTH", params)
        self.assertIn("INTENT.LOUDNESS_BIAS", params)
        self.assertIn("INTENT.CONFIDENCE", params)

    def test_validate_scene_intent_out_of_range_width_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        intent_params = load_intent_params(repo_root / "ontology" / "intent_params.yaml")

        scene = {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.TEST.INTENT",
            "objects": [
                {
                    "object_id": "OBJ.LEAD",
                    "intent": {
                        "width": 2.0,
                        "confidence": 0.5,
                    },
                }
            ],
            "beds": [],
        }

        first = validate_scene_intent(scene, intent_params)
        second = validate_scene_intent(scene, intent_params)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            [
                {
                    "issue_id": "ISSUE.VALIDATION.SCENE_INTENT_PARAM_OUT_OF_RANGE",
                    "severity": 40,
                    "confidence": 1.0,
                    "target": {
                        "scope": "object",
                        "object_id": "OBJ.LEAD",
                        "param_id": "INTENT.WIDTH",
                    },
                    "message": (
                        "Scene intent value for INTENT.WIDTH exceeds maximum 1.0: 2.0."
                    ),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
