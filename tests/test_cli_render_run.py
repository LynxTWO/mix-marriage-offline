import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

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


def _read_jsonl(path: Path) -> list[dict]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [json.loads(line) for line in lines]


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


class TestRenderRunPreflight(unittest.TestCase):
    def test_preflight_bytes_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_a = temp_path / "preflight_a.json"
            preflight_b = temp_path / "preflight_b.json"

            exit_a, _, stderr_a, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_a),
                ],
            )
            exit_b, _, stderr_b, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_b),
                    "--force",
                ],
            )

            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertTrue(preflight_a.exists())
            self.assertTrue(preflight_b.exists())
            self.assertEqual(preflight_a.read_bytes(), preflight_b.read_bytes())

    def test_preflight_overwrite_requires_preflight_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"
            preflight_out.write_text(
                json.dumps({"existing": True}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            existing_bytes = preflight_out.read_bytes()

            exit_refused, _, stderr_refused, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                ],
            )
            self.assertEqual(exit_refused, 1)
            self.assertIn("File exists", stderr_refused)
            self.assertIn("--preflight-force", stderr_refused)
            self.assertEqual(existing_bytes, preflight_out.read_bytes())

            exit_allowed, _, stderr_allowed, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                    "--preflight-force",
                ],
            )
            self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
            self.assertNotEqual(existing_bytes, preflight_out.read_bytes())

    def test_preflight_force_requires_preflight_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, _, _ = _run_render_run(
                temp_path,
                extra_args=["--preflight-force"],
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("--preflight-force requires --preflight-out", stderr)

    def test_preflight_error_issues_exit_two_and_skip_report_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"
            event_log_out = temp_path / "event_log.jsonl"

            fake_preflight_payload = {
                "schema_version": "0.1.0",
                "plan_path": (temp_path / "render_plan.json").resolve().as_posix(),
                "plan_id": "PLAN.render.preflight.abcdef01",
                "checks": [
                    {
                        "job_id": "JOB.001",
                        "input_count": 1,
                        "status": "error",
                        "input_checks": [
                            {
                                "path": "missing/input.wav",
                                "role": "scene",
                                "exists": False,
                                "is_file": False,
                                "ffprobe": {
                                    "status": "skipped",
                                    "reason": "input path does not exist",
                                },
                            }
                        ],
                    }
                ],
                "issues": [
                    {
                        "issue_id": "ISSUE.RENDER.PREFLIGHT.INPUT_MISSING",
                        "severity": "error",
                        "message": "Input path does not exist.",
                        "evidence": {
                            "job_id": "JOB.001",
                            "path": "missing/input.wav",
                            "role": "scene",
                        },
                    }
                ],
            }

            with patch(
                "mmo.core.render_preflight.build_render_preflight_payload",
                return_value=fake_preflight_payload,
            ):
                exit_code, stdout, stderr, plan_out, report_out = _run_render_run(
                    temp_path,
                    extra_args=[
                        "--preflight-out", str(preflight_out),
                        "--event-log-out", str(event_log_out),
                    ],
                )

            self.assertEqual(exit_code, 2, msg=stderr)
            self.assertEqual(stdout, "")
            self.assertTrue(plan_out.exists())
            self.assertTrue(preflight_out.exists())
            self.assertFalse(report_out.exists())
            self.assertFalse(event_log_out.exists())

    def test_preflight_payload_paths_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"

            exit_code, _, stderr, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                ],
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            payload = json.loads(preflight_out.read_text(encoding="utf-8"))
            self.assertNotIn("\\", payload.get("plan_path", ""))
            for job_check in payload.get("checks", []):
                if not isinstance(job_check, dict):
                    continue
                for input_check in job_check.get("input_checks", []):
                    if isinstance(input_check, dict):
                        self.assertNotIn("\\", str(input_check.get("path", "")))
            for issue in payload.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                evidence = issue.get("evidence")
                if isinstance(evidence, dict):
                    self.assertNotIn("\\", str(evidence.get("path", "")))


class TestRenderRunEventLog(unittest.TestCase):
    def test_writes_schema_valid_event_log_when_requested(self) -> None:
        event_validator = _schema_validator("event.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_out = temp_path / "render_events.jsonl"
            exit_code, _, stderr, plan_out, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(event_log_out.exists())

            events = _read_jsonl(event_log_out)
            self.assertEqual(len(events), 4)
            for event in events:
                event_validator.validate(event)
                for where_item in event.get("where", []):
                    self.assertNotIn("\\", where_item)
                evidence = event.get("evidence", {})
                if isinstance(evidence, dict):
                    for path_item in evidence.get("paths", []):
                        self.assertNotIn("\\", path_item)

            events_by_what = {
                str(event.get("what", "")): event
                for event in events
            }
            self.assertIn("render-run started", events_by_what)
            self.assertIn("render plan built", events_by_what)
            self.assertIn("render report built", events_by_what)
            self.assertIn("render-run completed", events_by_what)

            request_posix = (temp_path / "render_request.json").resolve().as_posix()
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            self.assertEqual(
                events_by_what["render-run started"]["where"],
                [request_posix, scene_posix],
            )

            plan_payload = json.loads(plan_out.read_text(encoding="utf-8"))
            plan_event = events_by_what["render plan built"]
            self.assertEqual(plan_event["where"], [plan_out.resolve().as_posix()])
            plan_evidence = plan_event.get("evidence", {})
            self.assertIn(plan_payload["plan_id"], plan_evidence.get("ids", []))
            for target in sorted(plan_payload.get("targets", [])):
                self.assertIn(target, plan_evidence.get("ids", []))
            metrics = {
                metric.get("name"): metric.get("value")
                for metric in plan_evidence.get("metrics", [])
                if isinstance(metric, dict)
            }
            self.assertEqual(metrics.get("job_count"), len(plan_payload.get("jobs", [])))

            report_event = events_by_what["render report built"]
            report_notes = report_event.get("evidence", {}).get("notes", [])
            self.assertIn("status=skipped", report_notes)
            self.assertIn("reason=dry_run", report_notes)

    def test_event_log_bytes_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_a = temp_path / "events_a.jsonl"
            event_log_b = temp_path / "events_b.jsonl"

            exit_a, _, stderr_a, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_a),
                ],
            )
            exit_b, _, stderr_b, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_b),
                    "--force",
                ],
            )

            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertEqual(event_log_a.read_bytes(), event_log_b.read_bytes())

    def test_event_log_overwrite_requires_event_log_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_out = temp_path / "events.jsonl"

            exit_first, _, stderr_first, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )
            self.assertEqual(exit_first, 0, msg=stderr_first)
            first_bytes = event_log_out.read_bytes()

            exit_refused, _, stderr_refused, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                    "--force",
                ],
            )
            self.assertEqual(exit_refused, 1)
            self.assertIn("--event-log-force", stderr_refused)
            self.assertEqual(first_bytes, event_log_out.read_bytes())

            exit_allowed, _, stderr_allowed, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                    "--force",
                    "--event-log-force",
                ],
            )
            self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
            self.assertTrue(event_log_out.exists())

    def test_stdout_unchanged_when_event_log_flag_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, stdout, stderr, _, _ = _run_render_run(temp_path)
            self.assertEqual(exit_code, 0, msg=stderr)

            self.assertNotIn("render-run started", stdout)
            self.assertNotIn("render plan built", stdout)
            self.assertNotIn("render report built", stdout)
            self.assertNotIn("render-run completed", stdout)
            parsed = json.loads(stdout)
            self.assertIn("plan_id", parsed)


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


def _multi_target_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
        "scene_path": scene_path,
    }


class TestRenderRunMultiTarget(unittest.TestCase):
    """Multi-target render-run tests."""

    def test_multi_target_plan_and_report_schema_valid(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, stdout, stderr, plan_out, report_out = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(plan_out.exists())
            self.assertTrue(report_out.exists())

            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

    def test_multi_target_report_has_all_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(len(report["jobs"]), 2)
            self.assertEqual(report["jobs"][0]["status"], "skipped")
            self.assertEqual(report["jobs"][1]["status"], "skipped")
            self.assertEqual(report["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(report["jobs"][1]["job_id"], "JOB.002")

    def test_multi_target_stdout_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, stdout, stderr, _, _ = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            parsed = json.loads(stdout)
            self.assertEqual(parsed["jobs"], 2)
            self.assertEqual(parsed["targets"], sorted(parsed["targets"]))

    def test_multi_target_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _multi_target_request(scene_posix))

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


if __name__ == "__main__":
    unittest.main()
