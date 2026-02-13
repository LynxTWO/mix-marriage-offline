"""Unit tests for mmo.core.stems_draft — draft scene and routing_plan generation."""

import json
import re
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.stems_draft import build_draft_routing_plan, build_draft_scene


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

_SAMPLE_STEMS_MAP: dict = {
    "version": "0.1.0",
    "stems_index_ref": "stems_index.json",
    "roles_ref": "ontology/roles.yaml",
    "assignments": [
        {
            "file_id": "STEMFILE.bbbbbbbbbb",
            "rel_path": "stems/snare.wav",
            "role_id": "ROLE.DRUMS.SNARE",
            "confidence": 0.85,
            "bus_group": "drums",
            "reasons": ["lexicon match: snare"],
            "link_group_id": None,
        },
        {
            "file_id": "STEMFILE.aaaaaaaaaa",
            "rel_path": "stems/kick.wav",
            "role_id": "ROLE.DRUMS.KICK",
            "confidence": 0.90,
            "bus_group": "drums",
            "reasons": ["lexicon match: kick"],
            "link_group_id": None,
        },
        {
            "file_id": "STEMFILE.cccccccccc",
            "rel_path": "stems/vocal_lead.wav",
            "role_id": "ROLE.VOCAL.LEAD",
            "confidence": 0.70,
            "bus_group": "vocals",
            "reasons": ["lexicon match: vocal"],
            "link_group_id": None,
        },
    ],
    "summary": {
        "counts_by_role": {
            "ROLE.DRUMS.KICK": 1,
            "ROLE.DRUMS.SNARE": 1,
            "ROLE.VOCAL.LEAD": 1,
        },
        "counts_by_bus_group": {
            "drums": 2,
            "vocals": 1,
        },
        "unknown_files": 0,
    },
}


class TestBuildDraftScene(unittest.TestCase):
    def test_build_draft_scene_deterministic(self) -> None:
        scene1 = build_draft_scene(_SAMPLE_STEMS_MAP)
        scene2 = build_draft_scene(_SAMPLE_STEMS_MAP)
        self.assertEqual(
            json.dumps(scene1, sort_keys=True),
            json.dumps(scene2, sort_keys=True),
        )

    def test_build_draft_scene_schema_valid(self) -> None:
        validator = _schema_validator(_REPO_ROOT / "schemas" / "scene.schema.json")
        scene = build_draft_scene(_SAMPLE_STEMS_MAP)
        errors = list(validator.iter_errors(scene))
        self.assertEqual(errors, [], msg=f"Schema errors: {errors}")

    def test_build_draft_scene_stable_sorting(self) -> None:
        scene = build_draft_scene(_SAMPLE_STEMS_MAP)
        objects = scene["objects"]
        # Assignments sorted by (rel_path, file_id):
        #   stems/kick.wav < stems/snare.wav < stems/vocal_lead.wav
        self.assertEqual(objects[0]["label"], "kick")
        self.assertEqual(objects[1]["label"], "snare")
        self.assertEqual(objects[2]["label"], "vocal_lead")

        # object_ids are sequential
        self.assertEqual(objects[0]["object_id"], "OBJ.001")
        self.assertEqual(objects[1]["object_id"], "OBJ.002")
        self.assertEqual(objects[2]["object_id"], "OBJ.003")

    def test_draft_scene_has_no_timestamps(self) -> None:
        scene = build_draft_scene(_SAMPLE_STEMS_MAP)
        serialized = json.dumps(scene)
        # ISO-8601 timestamp pattern
        self.assertIsNone(
            re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", serialized),
            msg="Scene contains a timestamp-like string",
        )

    def test_draft_bus_group_info_in_notes(self) -> None:
        scene = build_draft_scene(_SAMPLE_STEMS_MAP)
        for obj in scene["objects"]:
            notes_text = " ".join(obj["notes"])
            self.assertIn("bus_group:", notes_text)

    def test_build_draft_scene_created_from_is_draft(self) -> None:
        scene = build_draft_scene(_SAMPLE_STEMS_MAP)
        self.assertEqual(scene["source"]["created_from"], "draft")

    def test_build_draft_scene_custom_stems_dir(self) -> None:
        scene = build_draft_scene(_SAMPLE_STEMS_MAP, stems_dir="/my/stems")
        self.assertEqual(scene["source"]["stems_dir"], "/my/stems")


class TestBuildDraftRoutingPlan(unittest.TestCase):
    def test_build_draft_routing_plan_deterministic(self) -> None:
        plan1 = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        plan2 = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        self.assertEqual(
            json.dumps(plan1, sort_keys=True),
            json.dumps(plan2, sort_keys=True),
        )

    def test_build_draft_routing_plan_schema_valid(self) -> None:
        validator = _schema_validator(
            _REPO_ROOT / "schemas" / "routing_plan.schema.json"
        )
        plan = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        errors = list(validator.iter_errors(plan))
        self.assertEqual(errors, [], msg=f"Schema errors: {errors}")

    def test_build_draft_routing_plan_stable_sorting(self) -> None:
        plan = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        routes = plan["routes"]
        # Same sort order as scene: by (rel_path, file_id)
        stem_ids = [r["stem_id"] for r in routes]
        self.assertEqual(
            stem_ids,
            ["STEMFILE.aaaaaaaaaa", "STEMFILE.bbbbbbbbbb", "STEMFILE.cccccccccc"],
        )

    def test_draft_routing_plan_bus_group_in_notes(self) -> None:
        plan = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        for route in plan["routes"]:
            notes_text = " ".join(route["notes"])
            self.assertIn("bus_group:", notes_text)

    def test_draft_routing_plan_center_pan_mapping(self) -> None:
        plan = build_draft_routing_plan(_SAMPLE_STEMS_MAP)
        for route in plan["routes"]:
            self.assertEqual(route["stem_channels"], 1)
            self.assertEqual(route["target_channels"], 2)
            self.assertEqual(len(route["mapping"]), 2)
            self.assertEqual(route["mapping"][0]["src_ch"], 0)
            self.assertEqual(route["mapping"][0]["dst_ch"], 0)
            self.assertEqual(route["mapping"][1]["src_ch"], 0)
            self.assertEqual(route["mapping"][1]["dst_ch"], 1)


if __name__ == "__main__":
    unittest.main()
