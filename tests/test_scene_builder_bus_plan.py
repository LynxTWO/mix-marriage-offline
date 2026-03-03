from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.scene_builder import build_scene_from_bus_plan


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


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "scene_intent"


class TestSceneBuilderFromBusPlan(unittest.TestCase):
    def setUp(self) -> None:
        self._validator = _schema_validator(_REPO_ROOT / "schemas" / "scene.schema.json")
        self._stems_map = json.loads((_FIXTURES / "tiny_stems_map.json").read_text(encoding="utf-8"))
        self._bus_plan = json.loads((_FIXTURES / "tiny_bus_plan.json").read_text(encoding="utf-8"))

    def test_deterministic_and_schema_valid(self) -> None:
        scene_a = build_scene_from_bus_plan(
            self._stems_map,
            self._bus_plan,
            profile_id="PROFILE.ASSIST",
            stems_map_ref="fixtures/stems_map.json",
            bus_plan_ref="fixtures/bus_plan.json",
        )
        scene_b = build_scene_from_bus_plan(
            self._stems_map,
            self._bus_plan,
            profile_id="PROFILE.ASSIST",
            stems_map_ref="fixtures/stems_map.json",
            bus_plan_ref="fixtures/bus_plan.json",
        )

        self.assertEqual(scene_a, scene_b)
        self._validator.validate(scene_a)

        self.assertTrue(scene_a["scene_id"].startswith("SCENE.BUS."))
        self.assertEqual(scene_a["generated_utc"], "1970-01-01T00:00:00Z")
        self.assertEqual(scene_a["source_refs"]["stems_map_ref"], "fixtures/stems_map.json")
        self.assertEqual(scene_a["source_refs"]["bus_plan_ref"], "fixtures/bus_plan.json")
        self.assertEqual(scene_a["metadata"]["profile_id"], "PROFILE.ASSIST")

    def test_classification_yields_objects_and_beds(self) -> None:
        scene = build_scene_from_bus_plan(self._stems_map, self._bus_plan)

        objects = scene.get("objects")
        self.assertIsInstance(objects, list)
        if not isinstance(objects, list):
            return
        self.assertEqual(
            [row.get("stem_id") for row in objects if isinstance(row, dict)],
            [
                "STEMFILE.1111111111",
                "STEMFILE.5555555555",
                "STEMFILE.2222222222",
            ],
        )
        by_stem = {row["stem_id"]: row for row in objects if isinstance(row, dict)}

        self.assertIn("STEMFILE.1111111111", by_stem)
        self.assertIn("STEMFILE.2222222222", by_stem)
        self.assertIn("STEMFILE.5555555555", by_stem)
        self.assertNotIn("STEMFILE.3333333333", by_stem)
        self.assertNotIn("STEMFILE.4444444444", by_stem)

        uncertain = by_stem["STEMFILE.5555555555"]
        self.assertLessEqual(uncertain["confidence"], 0.35)
        self.assertNotIn("azimuth_hint", uncertain)

        self.assertEqual(by_stem["STEMFILE.1111111111"].get("azimuth_hint"), 0.0)
        self.assertEqual(by_stem["STEMFILE.2222222222"].get("azimuth_hint"), 0.0)

        beds = scene.get("beds")
        self.assertIsInstance(beds, list)
        if not isinstance(beds, list):
            return
        self.assertEqual(
            [row.get("bus_id") for row in beds if isinstance(row, dict)],
            ["BUS.FX.REVERB", "BUS.MUSIC.SYNTH"],
        )
        bed_bus_ids = {row.get("bus_id") for row in beds if isinstance(row, dict)}
        self.assertIn("BUS.FX.REVERB", bed_bus_ids)
        self.assertIn("BUS.MUSIC.SYNTH", bed_bus_ids)

        rules = scene.get("rules")
        self.assertIsInstance(rules, dict)
        if not isinstance(rules, dict):
            return
        self.assertIn("layout_safety_defaults", rules)
        self.assertIn("lfe_policy_defaults", rules)


if __name__ == "__main__":
    unittest.main()
