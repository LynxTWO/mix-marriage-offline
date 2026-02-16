import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        "scene_id": "SCENE.RENDER.RUN.TEST",
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


def _run_render_run(
    temp_path: Path,
    *,
    request_payload: dict | None = None,
    with_routing_plan: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str, Path, Path]:
    stems_dir = temp_path / "stems"
    stems_dir.mkdir(exist_ok=True)

    scene_path = temp_path / "scene.json"
    request_path = temp_path / "render_request.json"
    plan_out = temp_path / "render_plan.json"
    report_out = temp_path / "render_report.json"

    scene_posix = scene_path.resolve().as_posix()
    _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
    _write_json(
        request_path,
        request_payload if request_payload is not None else _minimal_request(scene_posix),
    )

    args = [
        "render-run",
        "--request", str(request_path),
        "--scene", str(scene_path),
        "--plan-out", str(plan_out),
        "--report-out", str(report_out),
    ]
    if with_routing_plan:
        routing_plan_path = temp_path / "routing_plan.json"
        _write_json(routing_plan_path, _routing_plan())
        args.extend(["--routing-plan", str(routing_plan_path)])
    if extra_args:
        args.extend(extra_args)

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exit_code = main(args)
    return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue(), plan_out, report_out


class TestRenderRunHappyPath(unittest.TestCase):
    def test_produces_schema_valid_plan_and_report(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, stdout, stderr, plan_out, report_out = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(plan_out.exists())
            self.assertTrue(report_out.exists())

            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

    def test_plan_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, plan_out, _ = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            self.assertIn("plan_id", plan)
            self.assertIn("request", plan)
            self.assertEqual(plan["request"]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(len(plan["jobs"]), 1)
            self.assertEqual(plan["jobs"][0]["job_id"], "JOB.001")

    def test_report_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, _, report_out = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "0.1.0")
            self.assertEqual(len(report["jobs"]), 1)
            self.assertEqual(report["jobs"][0]["status"], "skipped")
            self.assertIn("reason: dry_run", report["jobs"][0]["notes"])
            self.assertEqual(report["qa_gates"]["status"], "not_run")

    def test_with_routing_plan(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()
            scene_posix = scene_path.resolve().as_posix()
            exit_code, _, stderr, plan_out, report_out = _run_render_run(
                temp_path,
                request_payload=_request_with_options(scene_posix),
                with_routing_plan=True,
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

            self.assertEqual(
                plan["resolved"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )


class TestRenderRunDeterminism(unittest.TestCase):
    def test_byte_identical_plan_and_report_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))

            plan_out_1 = temp_path / "plan1.json"
            report_out_1 = temp_path / "report1.json"
            plan_out_2 = temp_path / "plan2.json"
            report_out_2 = temp_path / "report2.json"

            exit1 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_1),
                "--report-out", str(report_out_1),
            ])
            exit2 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_2),
                "--report-out", str(report_out_2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            self.assertEqual(plan_out_1.read_bytes(), plan_out_2.read_bytes())
            self.assertEqual(report_out_1.read_bytes(), report_out_2.read_bytes())

    def test_stdout_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            def _capture_stdout(plan_out: Path, report_out: Path) -> str:
                stdout_buf = StringIO()
                with redirect_stdout(stdout_buf):
                    main([
                        "render-run",
                        "--request", str(request_path),
                        "--scene", str(scene_path),
                        "--plan-out", str(plan_out),
                        "--report-out", str(report_out),
                    ])
                return stdout_buf.getvalue()

            stdout1 = _capture_stdout(
                temp_path / "plan_a.json", temp_path / "report_a.json",
            )
            stdout2 = _capture_stdout(
                temp_path / "plan_b.json", temp_path / "report_b.json",
            )
            # stdout contains resolved paths, which differ per output name;
            # verify structure is valid JSON and has expected keys.
            parsed1 = json.loads(stdout1)
            parsed2 = json.loads(stdout2)
            self.assertEqual(parsed1["plan_id"], parsed2["plan_id"])
            self.assertEqual(parsed1["jobs"], parsed2["jobs"])
            self.assertEqual(parsed1["targets"], parsed2["targets"])


class TestRenderRunOverwrite(unittest.TestCase):
    def test_refuses_overwrite_plan_out_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "render_plan.json"
            report_out = temp_path / "render_report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            plan_out.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_refuses_overwrite_report_out_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            report_out.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())

    def test_allows_overwrite_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            plan_out.write_text("{}", encoding="utf-8")
            report_out.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out),
                "--report-out", str(report_out),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(plan["schema_version"], "0.1.0")
            self.assertEqual(report["schema_version"], "0.1.0")


class TestRenderRunBackslashRejection(unittest.TestCase):
    def test_rejects_backslash_in_request_scene_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes\\bad\\path.json",
            })

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertNotEqual(exit_code, 0)


class TestRenderRunErrorPaths(unittest.TestCase):
    """Deterministic, stable error messages for invalid inputs."""

    def test_unknown_layout_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.DOES_NOT_EXIST",
                "scene_path": scene_posix,
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown layout_id", err)
            self.assertIn("LAYOUT.DOES_NOT_EXIST", err)
            self.assertIn("LAYOUT.1_0", err)
            self.assertIn("LAYOUT.2_0", err)
            self.assertLess(err.index("LAYOUT.1_0"), err.index("LAYOUT.2_0"))

    def test_unknown_downmix_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "downmix_policy_id": "POLICY.DOWNMIX.FAKE_V99",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown policy_id", err)
            self.assertIn("POLICY.DOWNMIX.FAKE_V99", err)
            self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", err)

    def test_unknown_gates_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "gates_policy_id": "POLICY.GATES.NONEXISTENT",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown gates_policy_id", err)
            self.assertIn("POLICY.GATES.NONEXISTENT", err)
            self.assertIn("POLICY.GATES.CORE_V0", err)

    def test_routing_plan_path_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "routing_plan_path": "routing/plan.json",
            })
            self.assertEqual(rc, 1)
            self.assertIn("routing_plan_path is set", err)
            self.assertIn("routing/plan.json", err)


if __name__ == "__main__":
    unittest.main()
