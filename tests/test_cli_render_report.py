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


def _minimal_render_plan(scene_path: str) -> dict:
    """A minimal render_plan that passes schema validation."""
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.test.abcdef01",
        "scene_path": scene_path,
        "targets": ["TARGET.STEREO.2_0"],
        "policies": {},
        "jobs": [
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "output_formats": ["wav"],
                "contexts": ["render"],
                "notes": ["Test job."],
            },
        ],
        "request": {
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path,
        },
    }


def _render_plan_with_policies(scene_path: str) -> dict:
    """A render_plan with policies and multiple jobs."""
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.multi.12345678",
        "scene_path": scene_path,
        "targets": ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
        "policies": {
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "gates_policy_id": "POLICY.GATES.CORE_V0",
        },
        "jobs": [
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "output_formats": ["wav"],
                "contexts": ["render"],
                "notes": ["Stereo target."],
            },
            {
                "job_id": "JOB.002",
                "target_id": "TARGET.SURROUND.5_1",
                "target_layout_id": "LAYOUT.5_1",
                "output_formats": ["wav", "flac"],
                "contexts": ["render"],
                "notes": ["Surround target."],
            },
        ],
        "request": {
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path,
        },
    }


class TestRenderReportCli(unittest.TestCase):
    def test_produces_schema_valid_render_report(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

    def test_report_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")

            # request summary
            self.assertEqual(payload["request"]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(payload["request"]["scene_path"], scene_posix)

            # jobs default to skipped
            self.assertEqual(len(payload["jobs"]), 1)
            self.assertEqual(payload["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(payload["jobs"][0]["status"], "skipped")
            self.assertEqual(payload["jobs"][0]["output_files"], [])
            self.assertIn("reason: dry_run", payload["jobs"][0]["notes"])

            # policies_applied
            self.assertIsNone(payload["policies_applied"]["downmix_policy_id"])
            self.assertIsNone(payload["policies_applied"]["gates_policy_id"])
            self.assertIsNone(payload["policies_applied"]["matrix_id"])

            # qa_gates not run
            self.assertEqual(payload["qa_gates"]["status"], "not_run")
            self.assertEqual(payload["qa_gates"]["gates"], [])

    def test_report_with_policies_and_multiple_jobs(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_policies(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            self.assertEqual(len(payload["jobs"]), 2)
            self.assertEqual(payload["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(payload["jobs"][1]["job_id"], "JOB.002")
            for job in payload["jobs"]:
                self.assertEqual(job["status"], "skipped")

            self.assertEqual(
                payload["policies_applied"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )
            self.assertEqual(
                payload["policies_applied"]["gates_policy_id"],
                "POLICY.GATES.CORE_V0",
            )


class TestRenderReportOverwrite(unittest.TestCase):
    def test_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))
            out_path.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-report",
                    "--plan", str(plan_path),
                    "--out", str(out_path),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_allows_overwrite_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))
            out_path.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")


class TestRenderReportDeterminism(unittest.TestCase):
    def test_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out1 = temp_path / "report1.json"
            out2 = temp_path / "report2.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_policies(scene_posix))

            exit1 = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out1),
            ])
            exit2 = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            bytes1 = out1.read_bytes()
            bytes2 = out2.read_bytes()
            self.assertEqual(bytes1, bytes2)

    def test_core_function_deterministic(self) -> None:
        from mmo.core.render_reporting import build_render_report_from_plan

        plan = _minimal_render_plan("scenes/test/scene.json")
        first = build_render_report_from_plan(plan)
        second = build_render_report_from_plan(plan)
        self.assertEqual(
            json.dumps(first, indent=2, sort_keys=True),
            json.dumps(second, indent=2, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
