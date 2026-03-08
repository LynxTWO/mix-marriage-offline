import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.locks import apply_scene_build_locks, load_scene_build_locks


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


def _scene_fixture() -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.LOCKS",
        "source": {
            "stems_dir": "/tmp/stems",
            "created_from": "draft",
        },
        "objects": [
            {
                "object_id": "OBJ.STEM.A",
                "stem_id": "STEM.A",
                "role_id": "ROLE.OTHER.UNKNOWN",
                "group_bus": "BUS.OTHER",
                "label": "Stem A",
                "channel_count": 1,
                "azimuth_hint": 30.0,
                "width_hint": 0.8,
                "locks": {
                    "azimuth_hint": False,
                    "width_hint": False,
                    "depth_hint": False,
                },
                "intent": {
                    "confidence": 0.6,
                    "locks": [],
                    "position": {"azimuth_deg": 15.0},
                    "width": 0.2,
                    "depth": 0.5,
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.STEM.B",
                "stem_id": "STEM.B",
                "role_id": "ROLE.OTHER.UNKNOWN",
                "group_bus": "BUS.OTHER",
                "label": "Stem B",
                "channel_count": 1,
                "azimuth_hint": 45.0,
                "width_hint": 0.7,
                "locks": {
                    "azimuth_hint": False,
                    "width_hint": False,
                    "depth_hint": False,
                },
                "intent": {
                    "confidence": 0.3,
                    "locks": [],
                    "depth": 0.6,
                },
                "notes": [],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


class TestSceneBuildLocks(unittest.TestCase):
    def test_load_scene_build_locks_accepts_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            locks_path = Path(temp_dir) / "scene_locks.json"
            locks_path.write_text(
                json.dumps(
                    {
                        "version": "0.1.0",
                        "overrides": {
                            "STEM.A": {
                                "role_id": "ROLE.VOCAL.LEAD",
                                "placement": {
                                    "width": 0.25,
                                },
                            }
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = load_scene_build_locks(locks_path)
            self.assertEqual(loaded.get("version"), "0.1.0")
            overrides = loaded.get("overrides")
            self.assertIsInstance(overrides, dict)
            if not isinstance(overrides, dict):
                return
            self.assertEqual(
                overrides.get("STEM.A"),
                {
                    "placement": {"width": 0.25},
                    "role_id": "ROLE.VOCAL.LEAD",
                },
            )

    def test_load_scene_build_locks_accepts_scene_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            locks_path = Path(temp_dir) / "scene_locks.yaml"
            locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "scene:",
                        '  perspective: "audience"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = load_scene_build_locks(locks_path)
            self.assertEqual(
                loaded,
                {
                    "version": "0.1.0",
                    "scene": {"perspective": "audience"},
                    "overrides": {},
                },
            )

    def test_load_scene_build_locks_sorted_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            locks_path = Path(temp_dir) / "scene_locks.yaml"
            locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "overrides:",
                        "  STEM.A:",
                        '    role_id: "ROLE.VOCAL.LEAD"',
                        "  STEM.B:",
                        '    bus_id: "BUS.VOX.LEAD"',
                        "    placement:",
                        "      azimuth_deg: 0.0",
                        "      width: 0.15",
                        "      depth: 0.35",
                        "    surround_send_caps:",
                        "      side_max_gain: 0.05",
                        "    height_send_caps:",
                        "      top_max_gain: 0.04",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            first = load_scene_build_locks(locks_path)
            second = load_scene_build_locks(locks_path)
            self.assertEqual(first, second)
            self.assertEqual(first.get("version"), "0.1.0")
            overrides = first.get("overrides")
            self.assertIsInstance(overrides, dict)
            if not isinstance(overrides, dict):
                return
            self.assertEqual(list(overrides.keys()), ["STEM.A", "STEM.B"])
            self.assertEqual(
                overrides["STEM.B"].get("placement"),
                {"azimuth_deg": 0.0, "width": 0.15, "depth": 0.35},
            )
            self.assertEqual(
                overrides["STEM.B"].get("height_send_caps"),
                {"top_max_gain": 0.04},
            )

    def test_load_scene_build_locks_rejects_unsorted_stem_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            locks_path = Path(temp_dir) / "scene_locks.yaml"
            locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "overrides:",
                        "  STEM.Z:",
                        '    role_id: "ROLE.VOCAL.LEAD"',
                        "  STEM.A:",
                        '    role_id: "ROLE.DRUM.KICK"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "sorted by stem_id"):
                load_scene_build_locks(locks_path)

    def test_apply_scene_build_locks_precedence_and_receipt(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")

        scene = _scene_fixture()
        locks_payload = {
            "version": "0.1.0",
            "overrides": {
                "STEM.B": {
                    "role_id": "ROLE.DRUM.KICK",
                    "bus_id": "BUS.DRUMS.KICK",
                    "placement": {"azimuth_deg": 0.0, "width": 0.1, "depth": 0.22},
                    "surround_send_caps": {
                        "side_max_gain": 0.05,
                        "rear_max_gain": 0.03,
                    },
                    "height_send_caps": {
                        "top_max_gain": 0.0,
                    },
                }
            },
        }

        patched = apply_scene_build_locks(scene, locks_payload)
        validator.validate(patched)

        objects = {
            row["stem_id"]: row
            for row in patched["objects"]
            if isinstance(row, dict) and isinstance(row.get("stem_id"), str)
        }

        stem_a = objects["STEM.A"]
        # Explicit intent value beats inferred hint when no lock override exists.
        self.assertEqual(stem_a["intent"]["width"], 0.2)
        self.assertEqual(stem_a["width_hint"], 0.2)
        self.assertEqual(stem_a["intent"]["position"]["azimuth_deg"], 15.0)
        self.assertEqual(stem_a["azimuth_hint"], 15.0)
        self.assertEqual(stem_a["intent"]["depth"], 0.5)
        self.assertEqual(stem_a["depth_hint"], 0.5)

        stem_b = objects["STEM.B"]
        self.assertEqual(stem_b["role_id"], "ROLE.DRUM.KICK")
        self.assertEqual(stem_b["bus_id"], "BUS.DRUMS.KICK")
        self.assertEqual(stem_b["group_bus"], "BUS.DRUMS")
        self.assertEqual(stem_b["intent"]["width"], 0.1)
        self.assertEqual(stem_b["width_hint"], 0.1)
        self.assertEqual(stem_b["intent"]["position"]["azimuth_deg"], 0.0)
        self.assertEqual(stem_b["azimuth_hint"], 0.0)
        self.assertEqual(stem_b["intent"]["depth"], 0.22)
        self.assertEqual(stem_b["depth_hint"], 0.22)
        self.assertEqual(
            stem_b["intent"].get("surround_send_caps"),
            {
                "side_max_gain": 0.05,
                "rear_max_gain": 0.03,
            },
        )
        self.assertEqual(
            stem_b["intent"].get("height_send_caps"),
            {"top_max_gain": 0.0},
        )
        self.assertTrue(stem_b["locks"]["azimuth_hint"])
        self.assertTrue(stem_b["locks"]["width_hint"])
        self.assertTrue(stem_b["locks"]["depth_hint"])

        receipt = patched.get("metadata", {}).get("locks_receipt")
        self.assertIsInstance(receipt, dict)
        if not isinstance(receipt, dict):
            return
        rows = receipt.get("objects")
        self.assertIsInstance(rows, list)
        if not isinstance(rows, list):
            return
        by_stem = {
            row.get("stem_id"): row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("stem_id"), str)
        }
        self.assertEqual(by_stem["STEM.A"].get("width_source"), "explicit")
        self.assertEqual(by_stem["STEM.A"].get("azimuth_source"), "explicit")
        self.assertEqual(by_stem["STEM.A"].get("depth_source"), "explicit")
        self.assertEqual(by_stem["STEM.A"].get("height_send_caps_source"), "inferred")
        self.assertEqual(by_stem["STEM.B"].get("role_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("bus_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("bus_id"), "BUS.DRUMS.KICK")
        self.assertEqual(by_stem["STEM.B"].get("width_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("azimuth_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("depth_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("surround_send_caps_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("height_send_caps_source"), "locked")
        self.assertEqual(by_stem["STEM.B"].get("depth"), 0.22)
        self.assertEqual(by_stem["STEM.B"].get("height_send_caps"), {"top_max_gain": 0.0})


if __name__ == "__main__":
    unittest.main()
