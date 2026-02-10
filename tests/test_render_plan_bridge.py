import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_plan_bridge import render_plan_to_variant_plan


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


class TestRenderPlanBridge(unittest.TestCase):
    def test_render_plan_to_variant_plan_is_deterministic_and_schema_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "variant_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            out_dir = temp_path / "variants_out"
            scene_path = temp_path / "scene.json"
            render_plan_path = temp_path / "render_plan.json"

            scene = {
                "schema_version": "0.1.0",
                "scene_id": "SCENE.BRIDGE.TEST",
                "scene_path": scene_path.resolve().as_posix(),
                "source": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "created_from": "analyze",
                    "report": {
                        "run_config": {
                            "downmix": {
                                "source_layout_id": "LAYOUT.5_1",
                            }
                        }
                    },
                },
                "objects": [],
                "beds": [],
                "metadata": {
                    "preset_id": "PRESET.SAFE_CLEANUP",
                    "profile_id": "PROFILE.ASSIST",
                },
            }
            render_plan = {
                "schema_version": "0.1.0",
                "plan_id": "PLAN.SCENE.BRIDGE.TEST.1234abcd",
                "scene_path": scene_path.resolve().as_posix(),
                "render_plan_path": render_plan_path.resolve().as_posix(),
                "targets": [
                    "TARGET.STEREO.2_0",
                    "TARGET.STEREO.2_0",
                ],
                "policies": {"downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"},
                "jobs": [
                    {
                        "job_id": "JOB.001",
                        "target_id": "TARGET.STEREO.2_0",
                        "target_layout_id": "LAYOUT.2_0",
                        "output_formats": ["flac", "wav"],
                        "contexts": ["render"],
                        "notes": [],
                    },
                    {
                        "job_id": "JOB.002",
                        "target_id": "TARGET.STEREO.2_0",
                        "target_layout_id": "LAYOUT.5_1",
                        "routing_plan_path": (temp_path / "routing_plan.json").resolve().as_posix(),
                        "output_formats": ["wav"],
                        "contexts": ["render", "auto_apply"],
                        "notes": [],
                    },
                ],
            }

            first = render_plan_to_variant_plan(
                render_plan,
                scene,
                base_out_dir=out_dir.resolve().as_posix(),
            )
            second = render_plan_to_variant_plan(
                render_plan,
                scene,
                base_out_dir=out_dir.resolve().as_posix(),
            )

            self.assertEqual(first, second)
            validator.validate(first)

            self.assertEqual(
                first.get("metadata"),
                {
                    "scene_path": scene_path.resolve().as_posix(),
                    "render_plan_path": render_plan_path.resolve().as_posix(),
                },
            )
            self.assertEqual(
                first.get("base_run_config"),
                {
                    "schema_version": "0.1.0",
                    "profile_id": "PROFILE.ASSIST",
                    "downmix": {"policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"},
                },
            )

            variants = first.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list):
                return
            self.assertEqual(len(variants), 2)

            first_variant = variants[0]
            second_variant = variants[1]
            self.assertEqual(first_variant.get("variant_id"), "VARIANT.001")
            self.assertEqual(second_variant.get("variant_id"), "VARIANT.002")
            self.assertEqual(first_variant.get("variant_slug"), "target_stereo_2_0")
            self.assertEqual(second_variant.get("variant_slug"), "target_stereo_2_0__a")

            self.assertEqual(first_variant.get("preset_id"), "PRESET.SAFE_CLEANUP")
            self.assertEqual(first_variant.get("source_layout_id"), "LAYOUT.5_1")
            self.assertEqual(first_variant.get("target_layout_id"), "LAYOUT.2_0")
            self.assertEqual(second_variant.get("target_layout_id"), "LAYOUT.5_1")

            first_steps = first_variant.get("steps")
            second_steps = second_variant.get("steps")
            self.assertIsInstance(first_steps, dict)
            self.assertIsInstance(second_steps, dict)
            if not isinstance(first_steps, dict) or not isinstance(second_steps, dict):
                return
            self.assertTrue(first_steps.get("analyze"))
            self.assertTrue(first_steps.get("routing"))
            self.assertFalse(first_steps.get("apply"))
            self.assertTrue(first_steps.get("render"))
            self.assertTrue(first_steps.get("bundle"))
            self.assertEqual(first_steps.get("render_output_formats"), ["wav", "flac"])

            self.assertTrue(second_steps.get("apply"))
            self.assertEqual(second_steps.get("render_output_formats"), ["wav"])

            first_overrides = first_variant.get("run_config_overrides")
            self.assertIsInstance(first_overrides, dict)
            if not isinstance(first_overrides, dict):
                return
            self.assertEqual(first_overrides.get("profile_id"), "PROFILE.ASSIST")
            self.assertEqual(
                first_overrides.get("downmix"),
                {"policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"},
            )


if __name__ == "__main__":
    unittest.main()
