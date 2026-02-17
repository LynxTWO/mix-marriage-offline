import json
import tempfile
import unittest
import wave
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
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exit_code = main(args)
    return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()


def _render_plan(scene_path: str, jobs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.render.preflight.abcdef01",
        "scene_path": scene_path,
        "targets": ["TARGET.STEREO.2_0"],
        "policies": {},
        "jobs": jobs,
        "request": {
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path,
        },
    }


class TestRenderPreflightCli(unittest.TestCase):
    def test_happy_path_schema_valid_sorted_and_posix(self) -> None:
        validator = _schema_validator("render_preflight.schema.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_a = temp_path / "audio_b.wav"
            stems_b = temp_path / "audio_a.wav"
            _write_tiny_wav(stems_a)
            _write_tiny_wav(stems_b)

            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_preflight.json"
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan(
                    scene_posix,
                    jobs=[
                        {
                            "job_id": "JOB.002",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["preflight job 2"],
                            "inputs": [
                                {"path": stems_a.resolve().as_posix(), "role": "ROLE.B"},
                            ],
                        },
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["preflight job 1"],
                            "inputs": [
                                {"path": stems_a.resolve().as_posix(), "role": "ROLE.B"},
                                {"path": stems_b.resolve().as_posix(), "role": "ROLE.A"},
                            ],
                        },
                    ],
                ),
            )

            with patch("mmo.core.render_preflight._ffprobe_command_from_env", return_value=None):
                exit_code, stdout, stderr = _run_main(
                    [
                        "render-preflight",
                        "--plan",
                        str(plan_path),
                        "--out",
                        str(out_path),
                    ]
                )

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(payload["issues"], [])
            self.assertEqual(
                [row["job_id"] for row in payload["checks"]],
                ["JOB.001", "JOB.002"],
            )
            first_job_checks = payload["checks"][0]["input_checks"]
            self.assertEqual(
                [row["path"] for row in first_job_checks],
                sorted(row["path"] for row in first_job_checks),
            )
            self.assertNotIn("\\", out_path.read_text(encoding="utf-8"))

    def test_determinism_two_runs_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.wav"
            _write_tiny_wav(input_path)

            plan_path = temp_path / "render_plan.json"
            out_a = temp_path / "preflight_a.json"
            out_b = temp_path / "preflight_b.json"
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan(
                    scene_posix,
                    jobs=[
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["deterministic preflight"],
                            "inputs": [
                                {"path": input_path.resolve().as_posix(), "role": "ROLE.IN"},
                            ],
                        }
                    ],
                ),
            )

            with patch("mmo.core.render_preflight._ffprobe_command_from_env", return_value=None):
                exit_a, stdout_a, stderr_a = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(out_a)]
                )
                exit_b, stdout_b, stderr_b = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(out_b)]
                )

            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertEqual(stdout_a, "")
            self.assertEqual(stdout_b, "")
            self.assertEqual(stderr_a, "")
            self.assertEqual(stderr_b, "")
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_overwrite_refusal_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.wav"
            _write_tiny_wav(input_path)

            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_preflight.json"
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan(
                    scene_posix,
                    jobs=[
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["overwrite preflight"],
                            "inputs": [
                                {"path": input_path.resolve().as_posix(), "role": "ROLE.IN"},
                            ],
                        }
                    ],
                ),
            )
            out_path.write_text("{}", encoding="utf-8")

            exit_code, stdout, stderr = _run_main(
                ["render-preflight", "--plan", str(plan_path), "--out", str(out_path)]
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("File exists", stderr)
            self.assertIn("--force", stderr)
            self.assertEqual(out_path.read_text(encoding="utf-8"), "{}")

    def test_missing_input_produces_error_issue_with_stable_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_a = (temp_path / "a_missing.wav").resolve().as_posix()
            missing_b = (temp_path / "z_missing.wav").resolve().as_posix()

            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_preflight.json"
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan(
                    scene_posix,
                    jobs=[
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["missing inputs"],
                            "inputs": [
                                {"path": missing_b, "role": "ROLE.Z"},
                                {"path": missing_a, "role": "ROLE.A"},
                            ],
                        }
                    ],
                ),
            )

            with patch("mmo.core.render_preflight._ffprobe_command_from_env", return_value=None):
                exit_code, stdout, stderr = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(out_path)]
                )

            self.assertEqual(exit_code, 2, msg=stderr)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            issues = payload["issues"]
            self.assertEqual(len(issues), 2)
            self.assertTrue(all(issue["severity"] == "error" for issue in issues))
            self.assertTrue(
                all(
                    issue["issue_id"] == "ISSUE.RENDER.PREFLIGHT.INPUT_MISSING"
                    for issue in issues
                )
            )
            self.assertEqual(
                [issue["evidence"]["path"] for issue in issues],
                [missing_a, missing_b],
            )
            self.assertEqual(
                issues,
                sorted(
                    issues,
                    key=lambda issue: (
                        issue["severity"],
                        issue["issue_id"],
                        issue["message"],
                        issue["evidence"]["job_id"],
                        issue["evidence"]["path"],
                        issue["evidence"]["role"],
                    ),
                ),
            )
            self.assertEqual(payload["checks"][0]["status"], "error")
            self.assertNotIn("\\", out_path.read_text(encoding="utf-8"))

    def test_ffprobe_present_vs_absent_behavior_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.wav"
            _write_tiny_wav(input_path)

            plan_path = temp_path / "render_plan.json"
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan(
                    scene_posix,
                    jobs=[
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": ["ffprobe preflight"],
                            "inputs": [
                                {"path": input_path.resolve().as_posix(), "role": "ROLE.IN"},
                            ],
                        }
                    ],
                ),
            )

            absent_a = temp_path / "absent_a.json"
            absent_b = temp_path / "absent_b.json"
            with patch("mmo.core.render_preflight._ffprobe_command_from_env", return_value=None):
                exit_absent_a, _, err_absent_a = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(absent_a)]
                )
                exit_absent_b, _, err_absent_b = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(absent_b)]
                )
            self.assertEqual(exit_absent_a, 0, msg=err_absent_a)
            self.assertEqual(exit_absent_b, 0, msg=err_absent_b)
            self.assertEqual(absent_a.read_bytes(), absent_b.read_bytes())

            present_a = temp_path / "present_a.json"
            present_b = temp_path / "present_b.json"
            with patch(
                "mmo.core.render_preflight._ffprobe_command_from_env",
                return_value=("ffprobe",),
            ), patch(
                "mmo.core.render_preflight._run_ffprobe",
                return_value={
                    "sample_rate": 48000,
                    "channel_count": 2,
                    "duration_seconds": 0.5,
                },
            ):
                exit_present_a, _, err_present_a = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(present_a)]
                )
                exit_present_b, _, err_present_b = _run_main(
                    ["render-preflight", "--plan", str(plan_path), "--out", str(present_b)]
                )
            self.assertEqual(exit_present_a, 0, msg=err_present_a)
            self.assertEqual(exit_present_b, 0, msg=err_present_b)
            self.assertEqual(present_a.read_bytes(), present_b.read_bytes())

            absent_payload = json.loads(absent_a.read_text(encoding="utf-8"))
            present_payload = json.loads(present_a.read_text(encoding="utf-8"))
            absent_ffprobe = absent_payload["checks"][0]["input_checks"][0]["ffprobe"]
            present_ffprobe = present_payload["checks"][0]["input_checks"][0]["ffprobe"]

            self.assertEqual(
                absent_ffprobe,
                {"status": "skipped", "reason": "ffprobe unavailable"},
            )
            self.assertEqual(
                present_ffprobe,
                {
                    "status": "ok",
                    "sample_rate": 48000,
                    "channel_count": 2,
                    "duration_seconds": 0.5,
                },
            )


if __name__ == "__main__":
    unittest.main()
