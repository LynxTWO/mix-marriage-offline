import json
from contextlib import redirect_stderr, redirect_stdout
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestCliScene(unittest.TestCase):
    def test_scene_cli_build_show_validate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            report_path = temp_path / "report.json"
            timeline_path = temp_path / "timeline.json"
            scene_path = temp_path / "scene.json"

            _write_json(
                report_path,
                {
                    "schema_version": "0.1.0",
                    "report_id": "REPORT.CLI.SCENE.TEST",
                    "project_id": "PROJECT.CLI.SCENE.TEST",
                    "generated_at": "2000-01-01T00:00:00Z",
                    "engine_version": "0.1.0",
                    "ontology_version": "0.1.0",
                    "session": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "stems": [
                            {
                                "stem_id": "STEM.002",
                                "file_path": "stems/002.wav",
                                "channel_count": 2,
                            },
                            {
                                "stem_id": "STEM.001",
                                "file_path": "stems/001.wav",
                                "channel_count": 1,
                            },
                        ],
                    },
                    "issues": [],
                    "recommendations": [],
                },
            )
            _write_json(
                timeline_path,
                {
                    "schema_version": "0.1.0",
                    "sections": [
                        {
                            "id": "SEC.002",
                            "label": "Verse",
                            "start_s": 12.0,
                            "end_s": 24.0,
                        },
                        {
                            "id": "SEC.001",
                            "label": "Intro",
                            "start_s": 0.0,
                            "end_s": 12.0,
                        },
                    ],
                },
            )

            build_exit = main(
                [
                    "scene",
                    "build",
                    "--report",
                    str(report_path),
                    "--timeline",
                    str(timeline_path),
                    "--out",
                    str(scene_path),
                ]
            )
            self.assertEqual(build_exit, 0)
            self.assertTrue(scene_path.exists())

            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            validator.validate(scene_payload)
            self.assertEqual(
                [item["stem_id"] for item in scene_payload["objects"]],
                ["STEM.001", "STEM.002"],
            )
            self.assertEqual(
                scene_payload.get("timeline"),
                {
                    "schema_version": "0.1.0",
                    "sections": [
                        {
                            "id": "SEC.001",
                            "label": "Intro",
                            "start_s": 0.0,
                            "end_s": 12.0,
                        },
                        {
                            "id": "SEC.002",
                            "label": "Verse",
                            "start_s": 12.0,
                            "end_s": 24.0,
                        },
                    ],
                },
            )

            show_json_stdout = StringIO()
            with redirect_stdout(show_json_stdout):
                show_json_exit = main(
                    [
                        "scene",
                        "show",
                        "--scene",
                        str(scene_path),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(show_json_exit, 0)
            shown_scene = json.loads(show_json_stdout.getvalue())
            self.assertEqual(shown_scene, scene_payload)

            show_text_stdout = StringIO()
            with redirect_stdout(show_text_stdout):
                show_text_exit = main(
                    [
                        "scene",
                        "show",
                        "--scene",
                        str(scene_path),
                        "--format",
                        "text",
                    ]
                )
            self.assertEqual(show_text_exit, 0)
            self.assertIn("scene_id: SCENE.REPORT.CLI.SCENE.TEST", show_text_stdout.getvalue())

            validate_stdout = StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(
                    [
                        "scene",
                        "validate",
                        "--scene",
                        str(scene_path),
                    ]
                )
            self.assertEqual(validate_exit, 0)
            self.assertIn("Scene is valid.", validate_stdout.getvalue())

    def test_scene_cli_build_templates_respect_order_and_force_flag(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            report_path = temp_path / "report.json"
            out_default_path = temp_path / "scene.default.json"
            out_forced_path = temp_path / "scene.forced.json"

            _write_json(
                report_path,
                {
                    "schema_version": "0.1.0",
                    "report_id": "REPORT.CLI.SCENE.TEMPLATE.TEST",
                    "project_id": "PROJECT.CLI.SCENE.TEMPLATE.TEST",
                    "generated_at": "2000-01-01T00:00:00Z",
                    "engine_version": "0.1.0",
                    "ontology_version": "0.1.0",
                    "session": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "stems": [
                            {
                                "stem_id": "STEM.LEAD",
                                "file_path": "stems/Lead Vocal.wav",
                                "channel_count": 1,
                            },
                            {
                                "stem_id": "STEM.GTR",
                                "file_path": "stems/Guitar.wav",
                                "channel_count": 1,
                            },
                        ],
                    },
                    "issues": [],
                    "recommendations": [],
                },
            )

            template_csv = (
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER,"
                "TEMPLATE.SCENE.LIVE.YOU_ARE_THERE"
            )

            default_exit = main(
                [
                    "scene",
                    "build",
                    "--report",
                    str(report_path),
                    "--templates",
                    template_csv,
                    "--out",
                    str(out_default_path),
                ]
            )
            self.assertEqual(default_exit, 0)
            default_payload = json.loads(out_default_path.read_text(encoding="utf-8"))
            validator.validate(default_payload)

            forced_exit = main(
                [
                    "scene",
                    "build",
                    "--report",
                    str(report_path),
                    "--templates",
                    template_csv,
                    "--force-templates",
                    "--out",
                    str(out_forced_path),
                ]
            )
            self.assertEqual(forced_exit, 0)
            forced_payload = json.loads(out_forced_path.read_text(encoding="utf-8"))
            validator.validate(forced_payload)

            def _objects_by_id(scene_payload: dict) -> dict[str, dict]:
                objects = scene_payload.get("objects")
                self.assertIsInstance(objects, list)
                if not isinstance(objects, list):
                    return {}
                return {
                    item.get("object_id"): item
                    for item in objects
                    if isinstance(item, dict) and isinstance(item.get("object_id"), str)
                }

            default_by_id = _objects_by_id(default_payload)
            forced_by_id = _objects_by_id(forced_payload)

            default_lead = default_by_id["OBJ.STEM.LEAD"]["intent"]
            self.assertEqual(default_lead.get("width"), 0.15)
            self.assertEqual(default_lead.get("depth"), 0.2)
            self.assertEqual(default_lead.get("loudness_bias"), "forward")
            self.assertEqual(default_lead.get("locks"), [])

            default_gtr = default_by_id["OBJ.STEM.GTR"]["intent"]
            self.assertEqual(default_gtr.get("width"), 0.6)
            self.assertEqual(default_gtr.get("depth"), 0.4)
            self.assertEqual(default_gtr.get("loudness_bias"), "neutral")
            self.assertEqual(default_gtr.get("locks"), [])

            forced_lead = forced_by_id["OBJ.STEM.LEAD"]["intent"]
            self.assertEqual(forced_lead.get("width"), 0.6)
            self.assertEqual(forced_lead.get("depth"), 0.55)
            self.assertEqual(forced_lead.get("loudness_bias"), "back")
            self.assertEqual(forced_lead.get("locks"), [])

            forced_gtr = forced_by_id["OBJ.STEM.GTR"]["intent"]
            self.assertEqual(forced_gtr.get("width"), 0.6)
            self.assertEqual(forced_gtr.get("depth"), 0.55)
            self.assertEqual(forced_gtr.get("loudness_bias"), "back")
            self.assertEqual(forced_gtr.get("locks"), [])

    def test_scene_cli_build_unknown_templates_error_is_sorted_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            report_path = temp_path / "report.json"
            out_path = temp_path / "scene.json"
            _write_json(
                report_path,
                {
                    "schema_version": "0.1.0",
                    "report_id": "REPORT.CLI.SCENE.UNKNOWN_TEMPLATE.TEST",
                    "project_id": "PROJECT.CLI.SCENE.UNKNOWN_TEMPLATE.TEST",
                    "generated_at": "2000-01-01T00:00:00Z",
                    "engine_version": "0.1.0",
                    "ontology_version": "0.1.0",
                    "session": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "stems": [],
                    },
                    "issues": [],
                    "recommendations": [],
                },
            )

            command = [
                "scene",
                "build",
                "--report",
                str(report_path),
                "--templates",
                "TEMPLATE.SCENE.ZZZ_DOES_NOT_EXIST,TEMPLATE.SCENE.AAA_DOES_NOT_EXIST",
                "--out",
                str(out_path),
            ]

            first_stderr = StringIO()
            with redirect_stderr(first_stderr):
                first_exit = main(command)

            second_stderr = StringIO()
            with redirect_stderr(second_stderr):
                second_exit = main(command)

            self.assertEqual(first_exit, 1)
            self.assertEqual(second_exit, 1)
            self.assertEqual(first_stderr.getvalue(), second_stderr.getvalue())
            self.assertIn(
                "Unknown template_id: TEMPLATE.SCENE.AAA_DOES_NOT_EXIST, "
                "TEMPLATE.SCENE.ZZZ_DOES_NOT_EXIST.",
                first_stderr.getvalue(),
            )
            self.assertIn(
                (
                    "Available templates: TEMPLATE.SCENE.LIVE.YOU_ARE_THERE, "
                    "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER, "
                    "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD"
                ),
                first_stderr.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
