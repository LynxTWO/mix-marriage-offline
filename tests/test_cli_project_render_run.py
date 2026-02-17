"""Tests for ``mmo project render-run`` CLI command."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_render_run" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _init_project(base: Path) -> Path:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")
    project_dir = base / "project"
    exit_code, _, stderr = _run_main([
        "project", "init",
        "--stems-root", str(stems_root),
        "--out-dir", str(project_dir),
    ])
    assert exit_code == 0, f"project init failed: {stderr}"
    return project_dir


def _project_render_init(project_dir: Path, *, target_layout: str = "LAYOUT.5_1") -> None:
    exit_code, _, stderr = _run_main([
        "project", "render-init", str(project_dir),
        "--target-layout", target_layout,
    ])
    assert exit_code == 0, f"project render-init failed: {stderr}"


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((_SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _run_project_render_run(
    project_dir: Path,
    *,
    force: bool = False,
    event_log: bool = False,
    preflight: bool = False,
    preflight_force: bool = False,
    event_log_force: bool = False,
) -> tuple[int, str, str]:
    args = [
        "project", "render-run", str(project_dir),
    ]
    if force:
        args.append("--force")
    if event_log:
        args.append("--event-log")
    if preflight:
        args.append("--preflight")
    if preflight_force:
        args.append("--preflight-force")
    if event_log_force:
        args.append("--event-log-force")
    return _run_main(args)


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestProjectRenderRunHappyPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "happy")
        _project_render_init(cls.project_dir)

    def test_render_run_writes_schema_valid_plan_and_report(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        exit_code, stdout, stderr = _run_project_render_run(self.project_dir)
        self.assertEqual(exit_code, 0, msg=stderr)

        plan_path = self.project_dir / "renders" / "render_plan.json"
        report_path = self.project_dir / "renders" / "render_report.json"
        self.assertTrue(plan_path.is_file())
        self.assertTrue(report_path.is_file())

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        plan_validator.validate(plan)
        report_validator.validate(report)

        summary = json.loads(stdout)
        self.assertIn("paths_written", summary)
        self.assertIn("plan_id", summary)
        self.assertIn("job_count", summary)
        self.assertIn("targets", summary)
        self.assertEqual(summary["plan_id"], plan["plan_id"])
        self.assertEqual(summary["job_count"], len(plan["jobs"]))
        self.assertEqual(summary["targets"], sorted(summary["targets"]))
        self.assertEqual(
            summary["paths_written"],
            [
                plan_path.resolve().as_posix(),
                report_path.resolve().as_posix(),
            ],
        )


class TestProjectRenderRunDeterminism(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "determinism")
        _project_render_init(cls.project_dir)

    def test_stdout_and_output_bytes_identical_across_runs(self) -> None:
        plan_path = self.project_dir / "renders" / "render_plan.json"
        report_path = self.project_dir / "renders" / "render_report.json"

        exit_a, stdout_a, stderr_a = _run_project_render_run(
            self.project_dir,
            force=True,
        )
        self.assertEqual(exit_a, 0, msg=stderr_a)
        plan_bytes_a = plan_path.read_bytes()
        report_bytes_a = report_path.read_bytes()

        exit_b, stdout_b, stderr_b = _run_project_render_run(
            self.project_dir,
            force=True,
        )
        self.assertEqual(exit_b, 0, msg=stderr_b)
        plan_bytes_b = plan_path.read_bytes()
        report_bytes_b = report_path.read_bytes()

        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(plan_bytes_a, plan_bytes_b)
        self.assertEqual(report_bytes_a, report_bytes_b)


class TestProjectRenderRunOverwrite(unittest.TestCase):

    def test_refuses_overwrite_plan_and_report_without_force(self) -> None:
        project_dir = _init_project(_SANDBOX / "overwrite_refuse")
        _project_render_init(project_dir)

        exit_first, _, stderr_first = _run_project_render_run(project_dir)
        self.assertEqual(exit_first, 0, msg=stderr_first)
        plan_path = project_dir / "renders" / "render_plan.json"
        report_path = project_dir / "renders" / "render_report.json"
        plan_bytes_first = plan_path.read_bytes()
        report_bytes_first = report_path.read_bytes()

        exit_refused, _, stderr_refused = _run_project_render_run(project_dir)
        self.assertEqual(exit_refused, 1)
        self.assertIn("File exists", stderr_refused)
        self.assertIn("--force", stderr_refused)
        self.assertEqual(plan_bytes_first, plan_path.read_bytes())
        self.assertEqual(report_bytes_first, report_path.read_bytes())

    def test_allows_overwrite_plan_and_report_with_force(self) -> None:
        project_dir = _init_project(_SANDBOX / "overwrite_allow")
        _project_render_init(project_dir)

        exit_first, _, stderr_first = _run_project_render_run(project_dir)
        self.assertEqual(exit_first, 0, msg=stderr_first)

        exit_forced, _, stderr_forced = _run_project_render_run(
            project_dir,
            force=True,
        )
        self.assertEqual(exit_forced, 0, msg=stderr_forced)
        self.assertTrue((project_dir / "renders" / "render_plan.json").is_file())
        self.assertTrue((project_dir / "renders" / "render_report.json").is_file())

    def test_event_log_overwrite_requires_event_log_force(self) -> None:
        project_dir = _init_project(_SANDBOX / "event_log_refuse")
        _project_render_init(project_dir)

        event_log_path = project_dir / "renders" / "event_log.jsonl"
        exit_first, _, stderr_first = _run_project_render_run(
            project_dir,
            event_log=True,
        )
        self.assertEqual(exit_first, 0, msg=stderr_first)
        event_bytes_first = event_log_path.read_bytes()

        exit_refused, _, stderr_refused = _run_project_render_run(
            project_dir,
            force=True,
            event_log=True,
        )
        self.assertEqual(exit_refused, 1)
        self.assertIn("--event-log-force", stderr_refused)
        self.assertEqual(event_bytes_first, event_log_path.read_bytes())

        exit_allowed, _, stderr_allowed = _run_project_render_run(
            project_dir,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
        self.assertTrue(event_log_path.is_file())


class TestProjectRenderRunPreflight(unittest.TestCase):

    def test_writes_allowlisted_preflight_artifact_when_requested(self) -> None:
        preflight_validator = _schema_validator("render_preflight.schema.json")
        project_dir = _init_project(_SANDBOX / "preflight_happy")
        _project_render_init(project_dir)

        preflight_path = project_dir / "renders" / "render_preflight.json"
        exit_code, stdout, stderr = _run_project_render_run(
            project_dir,
            preflight=True,
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertTrue(preflight_path.is_file())

        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
        preflight_validator.validate(payload)
        self.assertNotIn("\\", payload.get("plan_path", ""))
        summary = json.loads(stdout)
        self.assertIn(preflight_path.resolve().as_posix(), summary["paths_written"])

    def test_preflight_bytes_are_deterministic(self) -> None:
        project_dir = _init_project(_SANDBOX / "preflight_determinism")
        _project_render_init(project_dir)
        preflight_path = project_dir / "renders" / "render_preflight.json"

        exit_a, stdout_a, stderr_a = _run_project_render_run(
            project_dir,
            preflight=True,
        )
        self.assertEqual(exit_a, 0, msg=stderr_a)
        preflight_bytes_a = preflight_path.read_bytes()

        exit_b, stdout_b, stderr_b = _run_project_render_run(
            project_dir,
            force=True,
            preflight=True,
            preflight_force=True,
        )
        self.assertEqual(exit_b, 0, msg=stderr_b)
        preflight_bytes_b = preflight_path.read_bytes()

        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(preflight_bytes_a, preflight_bytes_b)

    def test_preflight_overwrite_requires_preflight_force(self) -> None:
        project_dir = _init_project(_SANDBOX / "preflight_overwrite")
        _project_render_init(project_dir)
        preflight_path = project_dir / "renders" / "render_preflight.json"

        exit_first, _, stderr_first = _run_project_render_run(
            project_dir,
            preflight=True,
        )
        self.assertEqual(exit_first, 0, msg=stderr_first)
        preflight_bytes_first = preflight_path.read_bytes()

        exit_refused, _, stderr_refused = _run_project_render_run(
            project_dir,
            force=True,
            preflight=True,
        )
        self.assertEqual(exit_refused, 1)
        self.assertIn("File exists", stderr_refused)
        self.assertIn("--preflight-force", stderr_refused)
        self.assertEqual(preflight_bytes_first, preflight_path.read_bytes())

        exit_forced, _, stderr_forced = _run_project_render_run(
            project_dir,
            force=True,
            preflight=True,
            preflight_force=True,
        )
        self.assertEqual(exit_forced, 0, msg=stderr_forced)
        self.assertTrue(preflight_path.is_file())

    def test_preflight_force_requires_preflight_flag(self) -> None:
        project_dir = _init_project(_SANDBOX / "preflight_force_requires")
        _project_render_init(project_dir)

        exit_code, _, stderr = _run_project_render_run(
            project_dir,
            preflight_force=True,
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("--preflight-force requires --preflight", stderr)

    def test_preflight_errors_exit_two_and_skip_report_and_event_log(self) -> None:
        project_dir = _init_project(_SANDBOX / "preflight_error_gate")
        _project_render_init(project_dir)
        plan_path = project_dir / "renders" / "render_plan.json"
        preflight_path = project_dir / "renders" / "render_preflight.json"
        report_path = project_dir / "renders" / "render_report.json"
        event_log_path = project_dir / "renders" / "event_log.jsonl"

        fake_preflight_payload = {
            "schema_version": "0.1.0",
            "plan_path": plan_path.resolve().as_posix(),
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
            exit_code, stdout, stderr = _run_project_render_run(
                project_dir,
                preflight=True,
                event_log=True,
            )

        self.assertEqual(exit_code, 2, msg=stderr)
        self.assertEqual(stdout, "")
        self.assertTrue(plan_path.is_file())
        self.assertTrue(preflight_path.is_file())
        self.assertFalse(report_path.exists())
        self.assertFalse(event_log_path.exists())


class TestProjectRenderRunForwardSlashPaths(unittest.TestCase):

    def test_stdout_summary_paths_use_forward_slashes(self) -> None:
        project_dir = _init_project(_SANDBOX / "path_hygiene")
        _project_render_init(project_dir)

        exit_code, stdout, stderr = _run_project_render_run(
            project_dir,
            event_log=True,
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertNotIn("\\", stdout)

        summary = json.loads(stdout)
        for path_value in summary["paths_written"]:
            self.assertNotIn("\\", path_value)


if __name__ == "__main__":
    unittest.main()
