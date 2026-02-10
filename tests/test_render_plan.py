import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_plan import build_render_plan


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


class TestRenderPlan(unittest.TestCase):
    def test_build_render_plan_is_deterministic_and_sorted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene = {
                "schema_version": "0.1.0",
                "scene_id": "SCENE.REPORT.RENDER.PLAN.TEST",
                "scene_path": (temp_path / "scene.json").resolve().as_posix(),
                "source": {
                    "stems_dir": (temp_path / "stems").resolve().as_posix(),
                    "created_from": "analyze",
                },
                "metadata": {},
            }
            render_targets = {
                "targets": [
                    {
                        "target_id": "TARGET.SURROUND.5_1",
                        "layout_id": "LAYOUT.5_1",
                        "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        "safety_policy_id": "POLICY.GATES.CORE_V0",
                    },
                    {
                        "target_id": "TARGET.STEREO.2_0",
                        "layout_id": "LAYOUT.2_0",
                        "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        "safety_policy_id": "POLICY.GATES.CORE_V0",
                    },
                ]
            }
            routing_plan_path = (temp_path / "routing_plan.json").resolve().as_posix()

            first = build_render_plan(
                scene,
                render_targets,
                routing_plan_path=routing_plan_path,
                output_formats=["flac", "wav", "flac"],
                contexts=["auto_apply", "render", "render"],
                policies=None,
            )
            second = build_render_plan(
                scene,
                render_targets,
                routing_plan_path=routing_plan_path,
                output_formats=["flac", "wav", "flac"],
                contexts=["auto_apply", "render", "render"],
                policies=None,
            )

            self.assertEqual(first, second)
            validator.validate(first)
            self.assertEqual(
                first["targets"],
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )
            jobs = first["jobs"]
            self.assertEqual([job["job_id"] for job in jobs], ["JOB.001", "JOB.002"])
            self.assertEqual(
                [job["target_id"] for job in jobs],
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )
            self.assertEqual(jobs[0]["output_formats"], ["wav", "flac"])
            self.assertEqual(jobs[0]["contexts"], ["render", "auto_apply"])
            self.assertEqual(jobs[0]["routing_plan_path"], routing_plan_path)
            self.assertIn("Stereo is a deliverable target for stereo", jobs[0]["notes"])
            self.assertIn("Routing applied", jobs[0]["notes"])
            self.assertEqual(first["policies"]["gates_policy_id"], "POLICY.GATES.CORE_V0")
            self.assertEqual(
                first["policies"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )


if __name__ == "__main__":
    unittest.main()
