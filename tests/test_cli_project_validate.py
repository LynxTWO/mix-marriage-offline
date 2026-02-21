"""Tests for ``mmo project validate``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.event_log import new_event_id, write_event_log

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_validate" / str(os.getpid())
)


# -- helpers -----------------------------------------------------------------

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
    """Create a valid project scaffold and return the project_dir."""
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


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- tests -------------------------------------------------------------------

class TestProjectValidateHappyPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "happy")

    def test_exit_code_zero_on_valid_scaffold(self) -> None:
        exit_code, stdout, stderr = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

    def test_output_is_valid_json(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])
        self.assertNotIn("render_compat", result)

    def test_all_required_files_valid(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        for check in result["checks"]:
            if check["required"]:
                self.assertEqual(
                    check["status"], "valid",
                    msg=f"{check['file']} should be valid: {check}",
                )

    def test_optional_files_missing_is_ok(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        optional_missing = [
            c for c in result["checks"]
            if not c["required"] and c["status"] == "missing"
        ]
        self.assertGreater(len(optional_missing), 0, "Expected some optional files missing")

    def test_summary_counts_correct(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        checks = result["checks"]
        summary = result["summary"]
        self.assertEqual(summary["total"], len(checks))
        self.assertEqual(
            summary["valid"],
            sum(1 for c in checks if c["status"] == "valid"),
        )
        self.assertEqual(
            summary["missing"],
            sum(1 for c in checks if c["status"] == "missing"),
        )
        self.assertEqual(
            summary["invalid"],
            sum(1 for c in checks if c["status"] == "invalid"),
        )


class TestProjectValidatePaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "paths")

    def test_no_backslashes_in_output(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertNotIn("\\", stdout, "Backslashes found in JSON output")

    def test_checks_sorted_by_file(self) -> None:
        _, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        result = json.loads(stdout)
        files = [c["file"] for c in result["checks"]]
        self.assertEqual(files, sorted(files))


class TestProjectValidateDeterminism(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "determinism")

    def test_output_identical_across_runs(self) -> None:
        _, stdout_a, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        _, stdout_b, _ = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertEqual(stdout_a, stdout_b)


class TestProjectValidateOutFlag(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "out_flag")

    def test_out_writes_file_matching_stdout(self) -> None:
        out_path = _SANDBOX / "out_flag" / "validation.json"
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(self.project_dir),
            "--out", str(out_path),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_path.is_file())
        self.assertEqual(out_path.read_text(encoding="utf-8"), stdout)


class TestProjectValidateErrors(unittest.TestCase):

    def test_missing_required_file_returns_exit_2(self) -> None:
        empty_dir = _SANDBOX / "missing_required" / "project"
        empty_dir.mkdir(parents=True, exist_ok=True)
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(empty_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        self.assertFalse(result["ok"])

    def test_invalid_json_reports_errors(self) -> None:
        base = _SANDBOX / "invalid_json"
        project_dir = _init_project(base)
        # Corrupt a required JSON file.
        bad_path = project_dir / "stems" / "stems_index.json"
        bad_path.write_text("{ not valid json !!!", encoding="utf-8")
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        self.assertFalse(result["ok"])
        bad_check = next(
            c for c in result["checks"] if c["file"] == "stems/stems_index.json"
        )
        self.assertEqual(bad_check["status"], "invalid")
        self.assertGreater(len(bad_check["errors"]), 0)

    def test_schema_violation_reports_errors(self) -> None:
        base = _SANDBOX / "schema_violation"
        project_dir = _init_project(base)
        # Write valid JSON but schema-invalid content.
        bad_path = project_dir / "stems" / "stems_index.json"
        bad_path.write_text('{"wrong": true}\n', encoding="utf-8")
        exit_code, stdout, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        bad_check = next(
            c for c in result["checks"] if c["file"] == "stems/stems_index.json"
        )
        self.assertEqual(bad_check["status"], "invalid")
        self.assertGreater(len(bad_check["errors"]), 0)


class TestProjectValidateRenderArtifacts(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "render_artifacts")
        renders_dir = cls.project_dir / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        # Write minimal valid render artifacts.
        _write_json(renders_dir / "render_request.json", {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": "scenes/test/scene.json",
        })
        _write_json(renders_dir / "render_plan.json", {
            "schema_version": "0.1.0",
            "plan_id": "PLAN.test.abcdef01",
            "scene_path": "scenes/test/scene.json",
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
        })
        _write_json(renders_dir / "render_preflight.json", {
            "schema_version": "0.1.0",
            "plan_path": (renders_dir / "render_plan.json").resolve().as_posix(),
            "plan_id": "PLAN.test.abcdef01",
            "checks": [],
            "issues": [],
        })
        _write_json(renders_dir / "render_report.json", {
            "schema_version": "0.1.0",
            "request": {
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes/test/scene.json",
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "status": "skipped",
                    "output_files": [],
                    "notes": ["reason: dry_run"],
                },
            ],
            "policies_applied": {
                "downmix_policy_id": None,
                "gates_policy_id": None,
                "matrix_id": None,
            },
            "qa_gates": {"status": "not_run", "gates": []},
        })
        _write_json(renders_dir / "render_execute.json", {
            "schema_version": "0.1.0",
            "run_id": "RUN.0123456789abcdef",
            "request_sha256": "0" * 64,
            "plan_sha256": "1" * 64,
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "inputs": [
                        {
                            "path": (renders_dir / "input.wav").resolve().as_posix(),
                            "sha256": "2" * 64,
                        }
                    ],
                    "outputs": [
                        {
                            "path": (renders_dir / "output.wav").resolve().as_posix(),
                            "sha256": "3" * 64,
                        }
                    ],
                    "ffmpeg_version": "ffmpeg version N-12345-gdeadbeef",
                    "ffmpeg_commands": [
                        {
                            "args": ["ffmpeg", "-version"],
                            "determinism_flags": [],
                        }
                    ],
                }
            ],
        })
        _write_json(renders_dir / "render_qa.json", {
            "schema_version": "0.1.0",
            "run_id": "RUN.0123456789abcdef",
            "request_sha256": "0" * 64,
            "plan_sha256": "1" * 64,
            "report_sha256": "2" * 64,
            "plugin_chain_used": False,
            "thresholds": {
                "polarity_error_correlation_lte": -0.6,
                "correlation_warn_lte": -0.2,
                "true_peak_warn_dbtp_gt": -2.0,
                "true_peak_error_dbtp_gt": -1.0,
                "lra_warn_lu_lte": 1.5,
                "lra_warn_lu_gte": 18.0,
                "lra_error_lu_gte": 24.0,
                "plugin_delta_lufs_warn_abs": 2.0,
                "plugin_delta_lufs_error_abs": 4.0,
                "plugin_delta_crest_warn_abs": 3.0,
                "plugin_delta_crest_error_abs": 6.0,
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "input": {
                        "path": (renders_dir / "input.wav").resolve().as_posix(),
                        "sha256": "3" * 64,
                        "format": "wav",
                        "channel_count": 2,
                        "sample_rate_hz": 48000,
                        "metrics": {
                            "peak_dbfs": -1.0,
                            "rms_dbfs": -10.0,
                            "integrated_lufs": -12.0,
                            "short_term_lufs_p10": -14.0,
                            "short_term_lufs_p50": -12.0,
                            "short_term_lufs_p90": -10.0,
                            "loudness_range_lu": 4.0,
                            "crest_factor_db": 9.0,
                            "true_peak_dbtp": -0.5,
                            "clip_sample_count": 0,
                            "intersample_over_count": 0,
                            "dc_offset": 0.0,
                            "correlation_lr": 0.5,
                            "mid_rms_dbfs": -11.0,
                            "side_rms_dbfs": -20.0,
                            "side_mid_ratio_db": -9.0,
                            "mono_rms_dbfs": -11.0,
                        },
                        "spectral": {
                            "centers_hz": [16.0, 20.0, 25.0],
                            "levels_db": [-80.0, -78.0, -76.0],
                            "tilt_db_per_oct": 1.0,
                            "section_tilt_db_per_oct": {
                                "sub_bass_low_end": 1.0,
                                "low_midrange": 0.5,
                                "midrange_high_mid": -0.2,
                                "highs_treble": -0.6,
                            },
                            "adjacent_band_slopes_db_per_oct": [
                                {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                                {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386},
                            ],
                            "section_subband_slopes_db_per_oct": {
                                "sub_bass_low_end": [
                                    {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                                    {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386},
                                ],
                                "low_midrange": [],
                                "midrange_high_mid": [],
                                "highs_treble": [],
                            },
                        },
                        "polarity_risk": False,
                    },
                    "outputs": [
                        {
                            "path": (renders_dir / "output.wav").resolve().as_posix(),
                            "sha256": "4" * 64,
                            "format": "wav",
                            "channel_count": 2,
                            "sample_rate_hz": 48000,
                            "metrics": {
                                "peak_dbfs": -1.2,
                                "rms_dbfs": -11.0,
                                "integrated_lufs": -13.0,
                                "short_term_lufs_p10": -14.5,
                                "short_term_lufs_p50": -13.0,
                                "short_term_lufs_p90": -11.0,
                                "loudness_range_lu": 3.5,
                                "crest_factor_db": 8.8,
                                "true_peak_dbtp": -0.6,
                                "clip_sample_count": 0,
                                "intersample_over_count": 0,
                                "dc_offset": 0.0,
                                "correlation_lr": 0.4,
                                "mid_rms_dbfs": -12.0,
                                "side_rms_dbfs": -22.0,
                                "side_mid_ratio_db": -10.0,
                                "mono_rms_dbfs": -12.0,
                            },
                            "spectral": {
                                "centers_hz": [16.0, 20.0, 25.0],
                                "levels_db": [-81.0, -79.0, -77.0],
                                "tilt_db_per_oct": 0.8,
                                "section_tilt_db_per_oct": {
                                    "sub_bass_low_end": 0.8,
                                    "low_midrange": 0.3,
                                    "midrange_high_mid": -0.3,
                                    "highs_treble": -0.7,
                                },
                                "adjacent_band_slopes_db_per_oct": [
                                    {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                                    {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386},
                                ],
                                "section_subband_slopes_db_per_oct": {
                                    "sub_bass_low_end": [
                                        {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                                        {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386},
                                    ],
                                    "low_midrange": [],
                                    "midrange_high_mid": [],
                                    "highs_treble": [],
                                },
                            },
                            "polarity_risk": False,
                        }
                    ],
                    "comparisons": [],
                }
            ],
            "issues": [],
        })
        _write_valid_event_log(renders_dir / "event_log.jsonl")

    def test_render_artifacts_validated_as_valid(self) -> None:
        exit_code, stdout, stderr = _run_main([
            "project", "validate", str(self.project_dir),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        render_checks = [
            c for c in result["checks"]
            if c["file"].startswith("renders/")
        ]
        self.assertEqual(len(render_checks), 7)
        for check in render_checks:
            self.assertFalse(check["required"])
            self.assertEqual(
                check["status"], "valid",
                msg=f"{check['file']} expected valid: {check}",
            )


class TestProjectValidateRenderPlanInvalid(unittest.TestCase):

    def test_invalid_render_plan_rejected_with_deterministic_errors(self) -> None:
        base = _SANDBOX / "bad_render_plan"
        project_dir = _init_project(base)
        renders_dir = project_dir / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        # Schema-invalid render_plan: missing required fields.
        _write_json(renders_dir / "render_plan.json", {"wrong": True})

        exit_code_a, stdout_a, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        exit_code_b, stdout_b, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        # Invalid render_plan should not block ok (it's optional),
        # but should be reported as invalid.
        result = json.loads(stdout_a)
        bad_check = next(
            c for c in result["checks"]
            if c["file"] == "renders/render_plan.json"
        )
        self.assertEqual(bad_check["status"], "invalid")
        self.assertGreater(len(bad_check["errors"]), 0)
        # Deterministic: identical output across runs.
        self.assertEqual(stdout_a, stdout_b)


class TestProjectValidateRenderCompatFlag(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "render_compat_flag")
        renders_dir = cls.project_dir / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        _write_json(renders_dir / "render_request.json", {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": "scenes/test/request_scene.json",
        })
        _write_json(renders_dir / "render_plan.json", {
            "schema_version": "0.1.0",
            "plan_id": "PLAN.test.compat.0001",
            "scene_path": "scenes/test/plan_scene.json",
            "targets": ["TARGET.STEREO.2_0"],
            "policies": {},
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "target_id": "TARGET.STEREO.2_0",
                    "target_layout_id": "LAYOUT.2_0",
                    "output_formats": ["wav"],
                    "contexts": ["render"],
                    "notes": ["compat test job"],
                },
            ],
            "request": {
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes/test/plan_scene.json",
            },
        })
        _write_json(renders_dir / "render_report.json", {
            "schema_version": "0.1.0",
            "request": {
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes/test/report_scene.json",
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "status": "skipped",
                    "output_files": [],
                    "notes": ["reason: dry_run", "target_layout_id: LAYOUT.2_0"],
                },
            ],
            "policies_applied": {
                "downmix_policy_id": None,
                "gates_policy_id": None,
                "matrix_id": None,
            },
            "qa_gates": {"status": "not_run", "gates": []},
        })

    def test_render_compat_flag_adds_issues_and_is_deterministic(self) -> None:
        exit_code_a, stdout_a, stderr_a = _run_main([
            "project", "validate", str(self.project_dir), "--render-compat",
        ])
        exit_code_b, stdout_b, stderr_b = _run_main([
            "project", "validate", str(self.project_dir), "--render-compat",
        ])
        self.assertEqual(exit_code_a, 2, msg=stderr_a)
        self.assertEqual(exit_code_b, 2, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)

        result = json.loads(stdout_a)
        self.assertIn("render_compat", result)
        compat = result.get("render_compat")
        self.assertIsInstance(compat, dict)
        if not isinstance(compat, dict):
            return
        issues = compat.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertGreater(len(issues), 0)

        issue_sort_tuples = [
            (
                issue.get("severity"),
                issue.get("issue_id"),
                issue.get("message"),
                json.dumps(issue.get("evidence", {}), sort_keys=True, separators=(",", ":")),
            )
            for issue in issues
            if isinstance(issue, dict)
        ]
        self.assertEqual(issue_sort_tuples, sorted(issue_sort_tuples))

        issue_ids = [
            issue.get("issue_id")
            for issue in issues
            if isinstance(issue, dict)
        ]
        self.assertIn("ISSUE.RENDER.COMPAT.PLAN_REQUEST_SCENE_PATH_MISMATCH", issue_ids)
        self.assertIn("ISSUE.RENDER.COMPAT.PLAN_REPORT_LINK_MISMATCH", issue_ids)


class TestProjectValidateEventLogInvalid(unittest.TestCase):

    def test_invalid_event_log_rejected_with_line_issue_message(self) -> None:
        base = _SANDBOX / "bad_event_log"
        project_dir = _init_project(base)
        event_log_path = project_dir / "renders" / "event_log.jsonl"
        event_log_path.parent.mkdir(parents=True, exist_ok=True)
        event_log_path.write_text(
            (
                '{"kind":"info","scope":"render"\n'
                '"not-an-object"\n'
                '{"kind":"info","scope":"render"}\n'
            ),
            encoding="utf-8",
        )

        exit_code_a, stdout_a, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        exit_code_b, stdout_b, _ = _run_main([
            "project", "validate", str(project_dir),
        ])
        self.assertEqual(exit_code_a, 2)
        self.assertEqual(exit_code_b, 2)

        result = json.loads(stdout_a)
        check = next(
            item
            for item in result["checks"]
            if item["file"] == "renders/event_log.jsonl"
        )
        self.assertEqual(check["status"], "invalid")

        issues = check.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertGreater(len(issues), 0)
        self.assertEqual(
            issues,
            sorted(
                issues,
                key=lambda issue: (
                    issue["line"],
                    issue["issue_id"],
                    issue["message"],
                ),
            ),
        )
        self.assertEqual(issues[0]["line"], 1)
        self.assertTrue(issues[0]["issue_id"].startswith("ISSUE.EVENT_LOG."))

        errors = check.get("errors")
        self.assertIsInstance(errors, list)
        if isinstance(errors, list):
            self.assertTrue(any("line 1:" in item for item in errors))
            self.assertTrue(any("ISSUE.EVENT_LOG." in item for item in errors))

        self.assertEqual(stdout_a, stdout_b)


def _write_valid_event_log(path: Path) -> None:
    event = {
        "kind": "info",
        "scope": "render",
        "what": "render-run completed",
        "why": "Deterministic dry-run completed.",
        "where": ["renders/render_plan.json"],
        "evidence": {
            "codes": ["RENDER.RUN.COMPLETED"],
            "paths": ["renders/render_plan.json"],
        },
    }
    event["event_id"] = new_event_id(event)
    write_event_log([event], path, force=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
