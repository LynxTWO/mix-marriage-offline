import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def _minimal_scene(stems_dir: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.RENDER.PLANNER.TEST",
        "source": {
            "stems_dir": stems_dir,
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
    }


def _minimal_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.2_0",
        "scene_path": scene_path,
    }


def _request_with_options(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.5_1",
        "scene_path": scene_path,
        "options": {
            "output_formats": ["wav", "flac"],
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "gates_policy_id": "POLICY.GATES.CORE_V0",
        },
    }


def _routing_plan() -> dict:
    return {
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
    }


class TestRenderPlanFromRequestCli(unittest.TestCase):
    def test_happy_path_produces_schema_valid_render_plan(self) -> None:
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            # Verify request echo.
            self.assertIn("request", payload)
            self.assertEqual(
                payload["request"]["target_layout_id"], "LAYOUT.2_0",
            )
            self.assertEqual(payload["request"]["scene_path"], scene_posix)

            # Verify resolved section.
            self.assertIn("resolved", payload)
            self.assertEqual(
                payload["resolved"]["target_layout_id"], "LAYOUT.2_0",
            )
            self.assertIsInstance(payload["resolved"]["channel_order"], list)
            self.assertGreater(len(payload["resolved"]["channel_order"]), 0)

            # Verify jobs.
            jobs = payload["jobs"]
            self.assertIsInstance(jobs, list)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["job_id"], "JOB.001")
            self.assertEqual(jobs[0]["status"], "planned")
            self.assertIsInstance(jobs[0]["inputs"], list)
            self.assertIsInstance(jobs[0]["outputs"], list)
            self.assertGreater(len(jobs[0]["outputs"]), 0)

    def test_happy_path_with_options_and_routing_plan(self) -> None:
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            routing_plan_path = temp_path / "routing_plan.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))
            _write_json(routing_plan_path, _routing_plan())

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--routing-plan", str(routing_plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            # Policies resolved from request options.
            self.assertEqual(
                payload["resolved"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )
            self.assertEqual(
                payload["resolved"]["gates_policy_id"],
                "POLICY.GATES.CORE_V0",
            )

            # Output formats from request options.
            self.assertEqual(
                payload["jobs"][0]["output_formats"], ["wav", "flac"],
            )

    def test_overwrite_refusal_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            # Pre-create the output file.
            out_path.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-plan", "plan",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--out", str(out_path),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_overwrite_allowed_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            # Pre-create the output file.
            out_path.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")

    def test_determinism_two_runs_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out1 = temp_path / "plan1.json"
            out2 = temp_path / "plan2.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))

            exit1 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out1),
            ])
            exit2 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            bytes1 = out1.read_bytes()
            bytes2 = out2.read_bytes()
            self.assertEqual(bytes1, bytes2)

    def test_rejects_backslash_in_request_scene_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes\\bad\\path.json",
            })

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-plan", "plan",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--out", str(out_path),
                ])
            self.assertNotEqual(exit_code, 0)

    def test_existing_render_plan_build_still_works(self) -> None:
        """Regression: the existing render-plan build subcommand must not break."""
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            out_path = temp_path / "render_plan.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))

            exit_code = main([
                "render-plan", "build",
                "--scene", str(scene_path),
                "--targets", "Stereo (streaming)",
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertIn("plan_id", payload)
            self.assertIn("targets", payload)


if __name__ == "__main__":
    unittest.main()
