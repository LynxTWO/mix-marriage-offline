import json
import tempfile
import unittest
from pathlib import Path

from mmo.core.intent_params import load_intent_params, validate_scene_intent
from mmo.core.scene_editor import add_lock, remove_lock, set_intent


def _sample_scene(*, stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.EDITOR.TEST",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [
            {
                "object_id": "OBJ.B",
                "stem_id": "STEM.B",
                "label": "B",
                "channel_count": 1,
                "intent": {"confidence": 0.2, "locks": []},
                "notes": ["keep B notes"],
            },
            {
                "object_id": "OBJ.A",
                "stem_id": "STEM.A",
                "label": "A",
                "channel_count": 1,
                "intent": {"confidence": 0.2, "locks": []},
                "notes": ["keep A notes"],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []},
                "notes": [],
            }
        ],
        "metadata": {},
    }


class TestSceneEditor(unittest.TestCase):
    def test_add_remove_lock_are_idempotent_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)

            first = add_lock(
                scene,
                scope="scene",
                target_id=None,
                lock_id="LOCK.PRESERVE_DYNAMICS",
            )
            second = add_lock(
                first,
                scope="scene",
                target_id=None,
                lock_id="LOCK.PRESERVE_DYNAMICS",
            )
            self.assertEqual(first, second)

            scene_intent = first.get("intent")
            self.assertIsInstance(scene_intent, dict)
            if not isinstance(scene_intent, dict):
                return
            self.assertEqual(scene_intent.get("locks"), ["LOCK.PRESERVE_DYNAMICS"])

            object_ids = [item.get("object_id") for item in first.get("objects", [])]
            self.assertEqual(object_ids, ["OBJ.A", "OBJ.B"])
            first_object = first.get("objects", [])[0]
            self.assertIsInstance(first_object, dict)
            if isinstance(first_object, dict):
                self.assertEqual(first_object.get("notes"), ["keep A notes"])

            removed_first = remove_lock(
                second,
                scope="scene",
                target_id=None,
                lock_id="LOCK.PRESERVE_DYNAMICS",
            )
            removed_second = remove_lock(
                removed_first,
                scope="scene",
                target_id=None,
                lock_id="LOCK.PRESERVE_DYNAMICS",
            )
            self.assertEqual(removed_first, removed_second)
            intent_after_remove = removed_first.get("intent")
            self.assertIsInstance(intent_after_remove, dict)
            if isinstance(intent_after_remove, dict):
                self.assertEqual(intent_after_remove.get("locks"), [])

    def test_set_width_out_of_range_triggers_intent_validator_issue(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        intent_params = load_intent_params(repo_root / "ontology" / "intent_params.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            edited = set_intent(
                scene,
                scope="object",
                target_id="OBJ.A",
                param_key="width",
                value=2.0,
            )

        issues = validate_scene_intent(edited, intent_params)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(
            issue.get("issue_id"),
            "ISSUE.VALIDATION.SCENE_INTENT_PARAM_OUT_OF_RANGE",
        )
        target = issue.get("target")
        self.assertIsInstance(target, dict)
        if isinstance(target, dict):
            self.assertEqual(target.get("scope"), "object")
            self.assertEqual(target.get("object_id"), "OBJ.A")
            self.assertEqual(target.get("param_id"), "INTENT.WIDTH")

    def test_set_invalid_loudness_bias_triggers_intent_validator_issue(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        intent_params = load_intent_params(repo_root / "ontology" / "intent_params.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene = _sample_scene(stems_dir=stems_dir)
            edited = set_intent(
                scene,
                scope="object",
                target_id="OBJ.A",
                param_key="loudness_bias",
                value="way_too_forward",
            )

        issues = validate_scene_intent(edited, intent_params)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(
            issue.get("issue_id"),
            "ISSUE.VALIDATION.SCENE_INTENT_ENUM_INVALID",
        )
        target = issue.get("target")
        self.assertIsInstance(target, dict)
        if isinstance(target, dict):
            self.assertEqual(target.get("scope"), "object")
            self.assertEqual(target.get("object_id"), "OBJ.A")
            self.assertEqual(target.get("param_id"), "INTENT.LOUDNESS_BIAS")


if __name__ == "__main__":
    unittest.main()
