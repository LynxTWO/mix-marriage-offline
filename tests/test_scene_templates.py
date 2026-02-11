import tempfile
import unittest
from pathlib import Path

from mmo.core.scene_templates import apply_scene_templates, list_scene_templates, load_scene_templates


def _sample_scene(*, stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEMPLATES.TEST",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [
            {
                "object_id": "OBJ.GTR",
                "stem_id": "STEM.GTR",
                "label": "Guitar",
                "channel_count": 1,
                "intent": {
                    "confidence": 0.25,
                    "locks": [],
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.LEAD",
                "stem_id": "STEM.LEAD",
                "label": "Lead Vocal",
                "channel_count": 1,
                "intent": {
                    "width": 0.9,
                    "confidence": 0.5,
                    "locks": ["LOCK.NO_EXTRA_BASS"],
                },
                "notes": [],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.4, "confidence": 0.0, "locks": []},
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _sample_scene_scope_registry() -> str:
    return """
schema_version: "0.1.0"
templates:
  TEMPLATE.SCENE.TEST.SCENE_SCOPE:
    label: "Scene scope test"
    description: "Set scene-wide intent fields."
    patches:
      - scope: "scene"
        match: {}
        set:
          width: 0.5
"""


class TestSceneTemplates(unittest.TestCase):
    def test_list_scene_templates_is_sorted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = list_scene_templates(repo_root / "ontology" / "scene_templates.yaml")
        template_ids = [
            item.get("template_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("template_id"), str)
        ]
        self.assertEqual(template_ids, sorted(template_ids))
        self.assertEqual(
            template_ids,
            [
                "TEMPLATE.SCENE.LIVE.YOU_ARE_THERE",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD",
            ],
        )

    def test_load_scene_templates_rejects_unsorted_template_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "scene_templates.unsorted.yaml"
            registry_path.write_text(
                """
schema_version: "0.1.0"
templates:
  TEMPLATE.SCENE.ZZZ:
    label: "ZZZ"
    description: "last"
    patches: []
  TEMPLATE.SCENE.AAA:
    label: "AAA"
    description: "first"
    patches: []
""",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as err:
                load_scene_templates(registry_path)
        self.assertIn("sorted by template_id", str(err.exception))

    def test_load_scene_templates_rejects_invalid_label_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "scene_templates.invalid_regex.yaml"
            registry_path.write_text(
                """
schema_version: "0.1.0"
templates:
  TEMPLATE.SCENE.TEST.INVALID_REGEX:
    label: "Invalid regex"
    description: "Compile check."
    patches:
      - scope: "object"
        match:
          label_regex: "["
        set:
          width: 0.5
""",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as err:
                load_scene_templates(registry_path)
        self.assertIn("failed to compile", str(err.exception))

    def test_apply_scene_templates_missing_only_preserves_existing_fields_and_locks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            edited = apply_scene_templates(
                scene,
                ["TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER"],
                scene_templates_path=repo_root / "ontology" / "scene_templates.yaml",
                scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
            )

        objects = edited.get("objects")
        self.assertIsInstance(objects, list)
        if not isinstance(objects, list):
            return
        self.assertEqual([item.get("object_id") for item in objects], ["OBJ.GTR", "OBJ.LEAD"])

        by_id = {
            item.get("object_id"): item
            for item in objects
            if isinstance(item, dict) and isinstance(item.get("object_id"), str)
        }
        lead_intent = by_id["OBJ.LEAD"]["intent"]
        self.assertEqual(lead_intent.get("width"), 0.9)
        self.assertEqual(lead_intent.get("depth"), 0.2)
        self.assertEqual(lead_intent.get("loudness_bias"), "forward")
        self.assertEqual(lead_intent.get("position"), {"azimuth_deg": 0.0})
        self.assertEqual(lead_intent.get("locks"), ["LOCK.NO_EXTRA_BASS"])

        gtr_intent = by_id["OBJ.GTR"]["intent"]
        self.assertEqual(gtr_intent.get("width"), 0.6)
        self.assertEqual(gtr_intent.get("depth"), 0.4)
        self.assertEqual(gtr_intent.get("loudness_bias"), "neutral")
        self.assertEqual(gtr_intent.get("locks"), [])

    def test_apply_scene_templates_force_overwrites_unlocked_and_skips_hard_locked(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            scene["objects"][0]["intent"].update(
                {"width": 0.1, "depth": 0.1, "loudness_bias": "back"}
            )
            scene["objects"][1]["intent"] = {
                "position": {"azimuth_deg": 45.0},
                "width": 0.9,
                "depth": 0.1,
                "loudness_bias": "back",
                "confidence": 0.5,
                "locks": ["LOCK.PRESERVE_DYNAMICS"],
            }

            edited = apply_scene_templates(
                scene,
                ["TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER"],
                force=True,
                scene_templates_path=repo_root / "ontology" / "scene_templates.yaml",
                scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
            )

        objects = edited.get("objects")
        self.assertIsInstance(objects, list)
        if not isinstance(objects, list):
            return
        by_id = {
            item.get("object_id"): item
            for item in objects
            if isinstance(item, dict) and isinstance(item.get("object_id"), str)
        }

        gtr_intent = by_id["OBJ.GTR"]["intent"]
        self.assertEqual(gtr_intent.get("width"), 0.6)
        self.assertEqual(gtr_intent.get("depth"), 0.4)
        self.assertEqual(gtr_intent.get("loudness_bias"), "neutral")
        self.assertEqual(gtr_intent.get("locks"), [])

        lead_intent = by_id["OBJ.LEAD"]["intent"]
        self.assertEqual(lead_intent.get("position"), {"azimuth_deg": 45.0})
        self.assertEqual(lead_intent.get("width"), 0.9)
        self.assertEqual(lead_intent.get("depth"), 0.1)
        self.assertEqual(lead_intent.get("loudness_bias"), "back")
        self.assertEqual(lead_intent.get("locks"), ["LOCK.PRESERVE_DYNAMICS"])

    def test_apply_scene_templates_scene_scope_creates_scene_intent(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            registry_path = temp_path / "scene_templates.scene_scope.yaml"
            registry_path.write_text(_sample_scene_scope_registry(), encoding="utf-8")

            edited = apply_scene_templates(
                scene,
                ["TEMPLATE.SCENE.TEST.SCENE_SCOPE"],
                scene_templates_path=registry_path,
                scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
            )

        intent = edited.get("intent")
        self.assertIsInstance(intent, dict)
        if not isinstance(intent, dict):
            return
        self.assertEqual(intent.get("confidence"), 0.0)
        self.assertEqual(intent.get("locks"), [])
        self.assertEqual(intent.get("width"), 0.5)

    def test_apply_scene_templates_scene_scope_skips_hard_locked_scene_intent(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            scene["intent"] = {
                "confidence": 0.2,
                "locks": ["LOCK.NO_STEREO_WIDENING"],
                "width": 0.1,
            }
            registry_path = temp_path / "scene_templates.scene_scope.yaml"
            registry_path.write_text(_sample_scene_scope_registry(), encoding="utf-8")

            edited = apply_scene_templates(
                scene,
                ["TEMPLATE.SCENE.TEST.SCENE_SCOPE"],
                force=True,
                scene_templates_path=registry_path,
                scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
            )

        intent = edited.get("intent")
        self.assertIsInstance(intent, dict)
        if not isinstance(intent, dict):
            return
        self.assertEqual(intent.get("width"), 0.1)
        self.assertEqual(intent.get("locks"), ["LOCK.NO_STEREO_WIDENING"])


if __name__ == "__main__":
    unittest.main()
