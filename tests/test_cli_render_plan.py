import json
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestCliRenderPlan(unittest.TestCase):
    def test_render_plan_cli_build_show_validate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            routing_plan_path = temp_path / "routing_plan.json"
            render_plan_path = temp_path / "render_plan.json"

            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.CLI.RENDER.PLAN.TEST",
                    "source": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "created_from": "analyze",
                    },
                    "objects": [],
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
                },
            )
            _write_json(
                routing_plan_path,
                {
                    "schema_version": "0.1.0",
                    "source_layout_id": "LAYOUT.5_1",
                    "target_layout_id": "LAYOUT.2_0",
                    "routes": [
                        {
                            "stem_id": "STEM.001",
                            "stem_channels": 2,
                            "target_channels": 2,
                            "mapping": [
                                {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                                {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
                            ],
                            "notes": [],
                        }
                    ],
                },
            )

            build_exit = main(
                [
                    "render-plan",
                    "build",
                    "--scene",
                    str(scene_path),
                    "--targets",
                    "Stereo (streaming),5.1 (home theater)",
                    "--out",
                    str(render_plan_path),
                    "--routing-plan",
                    str(routing_plan_path),
                    "--output-formats",
                    "wav,flac",
                    "--context",
                    "render",
                    "--context",
                    "auto_apply",
                    "--policy-id",
                    "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                ]
            )
            self.assertEqual(build_exit, 0)
            self.assertTrue(render_plan_path.exists())

            payload = json.loads(render_plan_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(
                payload.get("targets"),
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )
            jobs = payload.get("jobs")
            self.assertIsInstance(jobs, list)
            if isinstance(jobs, list):
                self.assertEqual(
                    [
                        item.get("target_id")
                        for item in jobs
                        if isinstance(item, dict)
                    ],
                    ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
                )

            show_json_stdout = StringIO()
            with redirect_stdout(show_json_stdout):
                show_json_exit = main(
                    [
                        "render-plan",
                        "show",
                        "--render-plan",
                        str(render_plan_path),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(show_json_exit, 0)
            shown_payload = json.loads(show_json_stdout.getvalue())
            self.assertEqual(shown_payload, payload)

            show_text_stdout = StringIO()
            with redirect_stdout(show_text_stdout):
                show_text_exit = main(
                    [
                        "render-plan",
                        "show",
                        "--render-plan",
                        str(render_plan_path),
                        "--format",
                        "text",
                    ]
                )
            self.assertEqual(show_text_exit, 0)
            self.assertIn("plan_id: PLAN.SCENE.CLI.RENDER.PLAN.TEST.", show_text_stdout.getvalue())

            validate_stdout = StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(
                    [
                        "render-plan",
                        "validate",
                        "--render-plan",
                        str(render_plan_path),
                    ]
                )
            self.assertEqual(validate_exit, 0)
            self.assertIn("Render plan is valid.", validate_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
