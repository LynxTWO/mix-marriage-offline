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
from mmo.core.portable_refs import relative_posix_ref


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    store: dict[str, dict] = {}
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        store[candidate.resolve().as_uri()] = schema
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
            store[schema_id] = schema
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        return jsonschema.Draft202012Validator(root_schema, registry=registry)
    except TypeError:
        # jsonschema<4.22 does not accept a registry kwarg.
        resolver_cls = getattr(jsonschema, "RefResolver", None)
        if resolver_cls is not None:
            resolver = resolver_cls.from_schema(root_schema, store=store)
            return jsonschema.Draft202012Validator(root_schema, resolver=resolver)
        return jsonschema.Draft202012Validator(root_schema)


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
            self.assertEqual(scene_payload["source"]["stems_dir"], "stems")
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

    def test_scene_cli_build_from_stems_map_and_bus_plan(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")
        stems_map_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_stems_map.json"
        bus_plan_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_bus_plan.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path_a = temp_path / "scene.a.json"
            scene_path_b = temp_path / "scene.b.json"

            build_exit_a = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--out",
                    str(scene_path_a),
                ]
            )
            self.assertEqual(build_exit_a, 0)
            self.assertTrue(scene_path_a.exists())

            payload_a = json.loads(scene_path_a.read_text(encoding="utf-8"))
            validator.validate(payload_a)
            self.assertIn("generated_utc", payload_a)
            self.assertEqual(payload_a.get("metadata", {}).get("profile_id"), "PROFILE.ASSIST")
            self.assertEqual(
                [row.get("stem_id") for row in payload_a.get("objects", []) if isinstance(row, dict)],
                [
                    "STEMFILE.1111111111",
                    "STEMFILE.5555555555",
                    "STEMFILE.2222222222",
                ],
            )
            objects_by_stem = {
                row.get("stem_id"): row
                for row in payload_a.get("objects", [])
                if isinstance(row, dict) and isinstance(row.get("stem_id"), str)
            }
            uncertain = objects_by_stem.get("STEMFILE.5555555555")
            self.assertIsInstance(uncertain, dict)
            if isinstance(uncertain, dict):
                self.assertNotIn("azimuth_hint", uncertain)
                self.assertNotIn("width_hint", uncertain)
                self.assertNotIn("depth_hint", uncertain)

            beds = payload_a.get("beds")
            self.assertIsInstance(beds, list)
            if isinstance(beds, list):
                by_bus_id = {
                    row.get("bus_id"): row
                    for row in beds
                    if isinstance(row, dict) and isinstance(row.get("bus_id"), str)
                }
                self.assertEqual(
                    by_bus_id["BUS.FX.REVERB"].get("stem_ids"),
                    ["STEMFILE.3333333333"],
                )
                self.assertEqual(
                    by_bus_id["BUS.MUSIC.SYNTH"].get("stem_ids"),
                    ["STEMFILE.4444444444"],
                )
            self.assertEqual(
                payload_a.get("source_refs", {}).get("stems_map_ref"),
                relative_posix_ref(
                    anchor_dir=scene_path_a.parent,
                    target_path=stems_map_path,
                ),
            )
            self.assertEqual(
                payload_a.get("source_refs", {}).get("bus_plan_ref"),
                relative_posix_ref(
                    anchor_dir=scene_path_a.parent,
                    target_path=bus_plan_path,
                ),
            )

            build_exit_b = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--out",
                    str(scene_path_b),
                ]
            )
            self.assertEqual(build_exit_b, 0)
            self.assertEqual(
                scene_path_a.read_text(encoding="utf-8"),
                scene_path_b.read_text(encoding="utf-8"),
            )

    def test_scene_cli_build_from_bus_plan_normalizes_stems_index_ref_to_file(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fixture_root = repo_root / "tests" / "fixtures" / "scene_intent"
        stems_map_payload = json.loads((fixture_root / "tiny_stems_map.json").read_text(encoding="utf-8"))
        bus_plan_payload = json.loads((fixture_root / "tiny_bus_plan.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir) / "workspace"
            stems_index_dir = workspace_dir / "project" / "stems"
            stems_index_dir.mkdir(parents=True, exist_ok=True)
            stems_index_path = stems_index_dir / "stems_index.json"
            stems_index_path.write_text("{}\n", encoding="utf-8")

            stems_map_payload["stems_index_ref"] = stems_index_dir.resolve().as_posix()
            stems_map_path = workspace_dir / "stems_map.json"
            bus_plan_path = workspace_dir / "bus_plan.json"
            scene_path = workspace_dir / "scene.json"
            _write_json(stems_map_path, stems_map_payload)
            _write_json(bus_plan_path, bus_plan_payload)

            build_exit = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--out",
                    str(scene_path),
                ]
            )
            self.assertEqual(build_exit, 0)

            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            self.assertEqual(
                scene_payload.get("source_refs", {}).get("stems_index_ref"),
                "project/stems/stems_index.json",
            )
            self.assertEqual(
                scene_payload.get("source", {}).get("stems_dir"),
                "project/stems",
            )

    def test_scene_cli_build_from_bus_plan_bridges_to_report_stem_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fixture_root = repo_root / "tests" / "fixtures" / "scene_intent"
        stems_map_path = fixture_root / "tiny_stems_map.json"
        bus_plan_path = fixture_root / "tiny_bus_plan.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            report_path = workspace_dir / "report.json"
            scene_path = workspace_dir / "scene.json"

            _write_json(
                report_path,
                {
                    "schema_version": "0.1.0",
                    "report_id": "REPORT.SCENE.BRIDGE.TEST",
                    "project_id": "PROJECT.SCENE.BRIDGE.TEST",
                    "generated_at": "2000-01-01T00:00:00Z",
                    "engine_version": "0.1.0",
                    "ontology_version": "0.1.0",
                    "session": {
                        "stems_dir": (workspace_dir / "stems").resolve().as_posix(),
                        "stems": [
                            {"stem_id": "kick", "file_path": "stems/Kick.wav"},
                            {"stem_id": "leadvox", "file_path": "stems/LeadVox.wav"},
                            {"stem_id": "hallverbreturn", "file_path": "stems/HallVerbReturn.wav"},
                            {"stem_id": "mystery", "file_path": "stems/Mystery.wav"},
                            {"stem_id": "padwide", "file_path": "stems/PadWide.wav"},
                        ],
                    },
                    "issues": [],
                    "recommendations": [],
                },
            )

            build_exit = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--out",
                    str(scene_path),
                ]
            )
            self.assertEqual(build_exit, 0)

            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [row.get("stem_id") for row in scene_payload.get("objects", []) if isinstance(row, dict)],
                ["kick", "mystery", "leadvox"],
            )
            self.assertEqual(
                [row.get("object_id") for row in scene_payload.get("objects", []) if isinstance(row, dict)],
                ["OBJ.kick", "OBJ.mystery", "OBJ.leadvox"],
            )

            beds = scene_payload.get("beds")
            self.assertIsInstance(beds, list)
            if isinstance(beds, list):
                by_bus_id = {
                    row.get("bus_id"): row
                    for row in beds
                    if isinstance(row, dict) and isinstance(row.get("bus_id"), str)
                }
                self.assertEqual(
                    by_bus_id["BUS.FX.REVERB"].get("stem_ids"),
                    ["hallverbreturn"],
                )
                self.assertEqual(
                    by_bus_id["BUS.MUSIC.SYNTH"].get("stem_ids"),
                    ["padwide"],
                )

    def test_scene_cli_build_from_stems_map_and_bus_plan_lints_cleanly(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        stems_map_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_stems_map.json"
        bus_plan_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_bus_plan.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            lint_path = temp_path / "scene_lint.json"

            build_exit = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--out",
                    str(scene_path),
                ]
            )
            self.assertEqual(build_exit, 0)

            lint_exit = main(
                [
                    "scene",
                    "lint",
                    "--scene",
                    str(scene_path),
                    "--out",
                    str(lint_path),
                ]
            )
            self.assertEqual(lint_exit, 0)

            lint_payload = json.loads(lint_path.read_text(encoding="utf-8"))
            summary = lint_payload.get("summary")
            self.assertIsInstance(summary, dict)
            if not isinstance(summary, dict):
                return
            self.assertTrue(summary.get("ok"))
            self.assertEqual(summary.get("error_count"), 0)

    def test_scene_cli_build_from_stems_map_bus_plan_with_locks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")
        stems_map_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_stems_map.json"
        bus_plan_path = repo_root / "tests" / "fixtures" / "scene_intent" / "tiny_bus_plan.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            locks_path = temp_path / "scene_locks.yaml"
            scene_path = temp_path / "scene.locked.json"
            locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "overrides:",
                        "  STEMFILE.5555555555:",
                        '    role_id: "ROLE.DRUM.KICK"',
                        '    bus_id: "BUS.DRUMS.KICK"',
                        "    placement:",
                        "      azimuth_deg: 0.0",
                        "      width: 0.1",
                        "      depth: 0.2",
                        "    surround_send_caps:",
                        "      side_max_gain: 0.03",
                        "      rear_max_gain: 0.02",
                        "    height_send_caps:",
                        "      top_max_gain: 0.0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            build_exit = main(
                [
                    "scene",
                    "build",
                    "--map",
                    str(stems_map_path),
                    "--bus",
                    str(bus_plan_path),
                    "--profile",
                    "PROFILE.ASSIST",
                    "--locks",
                    str(locks_path),
                    "--out",
                    str(scene_path),
                ]
            )
            self.assertEqual(build_exit, 0)
            payload = json.loads(scene_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list):
                return
            by_stem = {
                row.get("stem_id"): row
                for row in objects
                if isinstance(row, dict) and isinstance(row.get("stem_id"), str)
            }
            locked = by_stem["STEMFILE.5555555555"]
            self.assertEqual(locked.get("role_id"), "ROLE.DRUM.KICK")
            self.assertEqual(locked.get("bus_id"), "BUS.DRUMS.KICK")
            self.assertEqual(locked.get("group_bus"), "BUS.DRUMS")
            self.assertEqual(locked.get("azimuth_hint"), 0.0)
            self.assertEqual(locked.get("width_hint"), 0.1)
            self.assertEqual(locked["intent"].get("position"), {"azimuth_deg": 0.0})
            self.assertEqual(locked["intent"].get("width"), 0.1)
            self.assertEqual(locked["intent"].get("depth"), 0.2)
            self.assertEqual(locked.get("depth_hint"), 0.2)
            self.assertEqual(
                locked["intent"].get("surround_send_caps"),
                {"side_max_gain": 0.03, "rear_max_gain": 0.02},
            )
            self.assertEqual(
                locked["intent"].get("height_send_caps"),
                {"top_max_gain": 0.0},
            )
            self.assertTrue(locked["locks"]["azimuth_hint"])
            self.assertTrue(locked["locks"]["width_hint"])
            self.assertTrue(locked["locks"]["depth_hint"])

            receipt = payload.get("metadata", {}).get("locks_receipt")
            self.assertIsInstance(receipt, dict)
            if not isinstance(receipt, dict):
                return
            receipt_rows = receipt.get("objects")
            self.assertIsInstance(receipt_rows, list)
            if not isinstance(receipt_rows, list):
                return
            row = next(
                item
                for item in receipt_rows
                if isinstance(item, dict) and item.get("stem_id") == "STEMFILE.5555555555"
            )
            self.assertEqual(row.get("role_source"), "locked")
            self.assertEqual(row.get("bus_source"), "locked")
            self.assertEqual(row.get("bus_id"), "BUS.DRUMS.KICK")
            self.assertEqual(row.get("azimuth_source"), "locked")
            self.assertEqual(row.get("width_source"), "locked")
            self.assertEqual(row.get("depth_source"), "locked")
            self.assertEqual(row.get("surround_send_caps_source"), "locked")
            self.assertEqual(row.get("height_send_caps_source"), "locked")

    def test_scene_cli_lint_reports_deterministic_errors_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            locks_path = temp_path / "scene_locks.yaml"
            report_path_a = temp_path / "scene_lint_a.json"
            report_path_b = temp_path / "scene_lint_b.json"

            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.LINT.ERRORS",
                    "source": {
                        "stems_dir": "/tmp/stems",
                        "created_from": "draft",
                    },
                    "intent": {
                        "perspective": "audience",
                        "locks": ["LOCK.NO_HEIGHT_SEND"],
                    },
                    "objects": [
                        {
                            "object_id": "OBJ.A",
                            "stem_id": "STEM.A",
                            "label": "Kick",
                            "channel_count": 1,
                            "role_id": "ROLE.DRUM.KICK",
                            "intent": {
                                "confidence": 0.2,
                                "width": 1.2,
                                "position": {"azimuth_deg": 210.0},
                                "height_send_caps": {"top_max_gain": 0.2},
                                "locks": ["LOCK.PRESERVE_DYNAMICS"],
                            },
                            "notes": [],
                        },
                        {
                            "object_id": "OBJ.A",
                            "stem_id": "STEM.A",
                            "label": "Kick Double",
                            "channel_count": 1,
                            "intent": {
                                "confidence": 0.6,
                                "locks": [],
                            },
                            "notes": [],
                        },
                        {
                            "object_id": "OBJ.B",
                            "stem_id": "STEM.B",
                            "label": "Pad",
                            "channel_count": 2,
                            "intent": {
                                "confidence": 0.7,
                                "locks": ["LOCK.NO_STEREO_WIDENING"],
                            },
                            "notes": [],
                        },
                    ],
                    "beds": [
                        {
                            "bed_id": "BED.001",
                            "label": "Room",
                            "kind": "bed",
                            "bus_id": "BUS.FX.REVERB",
                            "stem_ids": ["STEM.MISSING", "STEM.MISSING"],
                            "intent": {
                                "confidence": 0.0,
                                "locks": ["LOCK.NO_HEIGHT_SEND"],
                                "height_send_caps": {"top_max_gain": 0.4},
                            },
                            "notes": [],
                        },
                        {
                            "bed_id": "BED.002",
                            "label": "FX",
                            "kind": "bed",
                            "bus_id": "BUS.FX.REVERB",
                            "stem_ids": [],
                            "intent": {
                                "confidence": 0.0,
                                "locks": [],
                            },
                            "notes": [],
                        },
                    ],
                    "metadata": {},
                },
            )
            locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "overrides:",
                        "  STEM.A:",
                        "    height_send_caps:",
                        "      top_max_gain: 0.3",
                        "  STEM.MISSING:",
                        '    role_id: "ROLE.UNKNOWN.LINT"',
                        '    bus_id: "BUS.CUSTOM.LINT"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            first_stdout = StringIO()
            with redirect_stdout(first_stdout):
                first_exit = main(
                    [
                        "scene",
                        "lint",
                        "--scene",
                        str(scene_path),
                        "--scene-locks",
                        str(locks_path),
                        "--out",
                        str(report_path_a),
                    ]
                )

            second_stdout = StringIO()
            with redirect_stdout(second_stdout):
                second_exit = main(
                    [
                        "scene",
                        "lint",
                        "--scene",
                        str(scene_path),
                        "--scene-locks",
                        str(locks_path),
                        "--out",
                        str(report_path_b),
                    ]
                )

            self.assertEqual(first_exit, 2)
            self.assertEqual(second_exit, 2)
            self.assertIn("Scene lint failed", first_stdout.getvalue())
            self.assertIn("Scene lint failed", second_stdout.getvalue())

            first_payload = json.loads(report_path_a.read_text(encoding="utf-8"))
            second_payload = json.loads(report_path_b.read_text(encoding="utf-8"))
            self.assertEqual(first_payload, second_payload)

            summary = first_payload.get("summary")
            self.assertIsInstance(summary, dict)
            if not isinstance(summary, dict):
                return
            self.assertFalse(summary.get("ok"))
            self.assertGreater(summary.get("error_count", 0), 0)
            self.assertGreater(summary.get("warn_count", 0), 0)

            issues = first_payload.get("issues")
            self.assertIsInstance(issues, list)
            if not isinstance(issues, list):
                return
            issue_ids = {
                item.get("issue_id")
                for item in issues
                if isinstance(item, dict) and isinstance(item.get("issue_id"), str)
            }
            self.assertIn("ISSUE.SCENE_LINT.MISSING_STEM_REFERENCE", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.DUPLICATE_OBJECT_REFERENCE", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.DUPLICATE_BUS_REFERENCE", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.OUT_OF_RANGE_AZIMUTH", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.OUT_OF_RANGE_WIDTH", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.LOCK_CONFLICT", issue_ids)
            self.assertIn("ISSUE.SCENE_LINT.LOCK_OVERRIDE_ROLE_UNKNOWN", issue_ids)
            self.assertIn(
                "ISSUE.SCENE_LINT.CRITICAL_ANCHOR_LOW_CONFIDENCE",
                issue_ids,
            )

    def test_scene_cli_lint_warnings_only_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            report_path = temp_path / "scene_lint.json"

            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.LINT.WARN",
                    "source": {
                        "stems_dir": "/tmp/stems",
                        "created_from": "draft",
                    },
                    "intent": {
                        "perspective": "in_band",
                        "locks": [],
                    },
                    "objects": [
                        {
                            "object_id": "OBJ.LEAD",
                            "stem_id": "STEM.LEAD",
                            "label": "Lead Vocal",
                            "channel_count": 1,
                            "role_id": "ROLE.VOCAL.LEAD",
                            "bus_id": "BUS.VOX.LEAD",
                            "group_bus": "BUS.VOX",
                            "intent": {
                                "confidence": 0.9,
                                "locks": [],
                            },
                            "notes": [],
                        }
                    ],
                    "beds": [],
                    "metadata": {},
                },
            )

            lint_stdout = StringIO()
            with redirect_stdout(lint_stdout):
                lint_exit = main(
                    [
                        "scene",
                        "lint",
                        "--scene",
                        str(scene_path),
                        "--out",
                        str(report_path),
                    ]
                )

            self.assertEqual(lint_exit, 0)
            self.assertIn("Scene lint OK", lint_stdout.getvalue())

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            summary = payload.get("summary")
            self.assertIsInstance(summary, dict)
            if not isinstance(summary, dict):
                return
            self.assertTrue(summary.get("ok"))
            self.assertEqual(summary.get("error_count"), 0)
            self.assertEqual(summary.get("warn_count"), 2)

            issues = payload.get("issues")
            self.assertIsInstance(issues, list)
            if not isinstance(issues, list):
                return
            self.assertEqual(
                [item.get("issue_id") for item in issues if isinstance(item, dict)],
                [
                    "ISSUE.SCENE_LINT.IMMERSIVE_NO_BED_OR_AMBIENT",
                    "ISSUE.SCENE_LINT.IMMERSIVE_TEMPLATE_MISSING",
                ],
            )

    def test_scene_cli_lint_detects_missing_stem_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            (stems_dir / "present.wav").write_bytes(b"RIFF")

            scene_path = temp_path / "scene.json"
            report_path = temp_path / "scene_lint.json"
            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.LINT.MISSING.FILE",
                    "source": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "created_from": "draft",
                    },
                    "intent": {
                        "confidence": 0.8,
                        "locks": [],
                    },
                    "objects": [
                        {
                            "object_id": "OBJ.PRESENT",
                            "stem_id": "present",
                            "label": "Present Stem",
                            "channel_count": 1,
                            "role_id": "ROLE.OTHER.UNKNOWN",
                            "intent": {
                                "confidence": 0.8,
                                "locks": [],
                            },
                            "notes": [],
                        },
                        {
                            "object_id": "OBJ.MISSING",
                            "stem_id": "missing_stem",
                            "label": "Missing Stem",
                            "channel_count": 1,
                            "role_id": "ROLE.OTHER.UNKNOWN",
                            "intent": {
                                "confidence": 0.8,
                                "locks": [],
                            },
                            "notes": [],
                        },
                    ],
                    "beds": [],
                    "metadata": {},
                },
            )

            lint_exit = main(
                [
                    "scene",
                    "lint",
                    "--scene",
                    str(scene_path),
                    "--out",
                    str(report_path),
                ]
            )
            self.assertEqual(lint_exit, 2)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            issues = payload.get("issues")
            self.assertIsInstance(issues, list)
            if not isinstance(issues, list):
                return
            issue_ids = {
                row.get("issue_id")
                for row in issues
                if isinstance(row, dict) and isinstance(row.get("issue_id"), str)
            }
            self.assertIn("ISSUE.SCENE_LINT.MISSING_STEM_FILE", issue_ids)

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
                    "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD, "
                    "TEMPLATE.SEATING.BAND.IN_BAND, "
                    "TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA, "
                    "TEMPLATE.SEATING.ORCHESTRA_AUDIENCE"
                ),
                first_stderr.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
