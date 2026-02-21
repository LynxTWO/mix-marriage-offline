import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from mmo.cli import main

_SANDBOX_ROOT = Path("sandbox_tmp") / "test_cli_render_compat"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_request() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
        "scene_path": "scenes/test/scene.json",
        "routing_plan_path": "plans/routing_plan.json",
    }


def _base_plan() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.render.compat.1234abcd",
        "scene_path": "scenes/test/scene.json",
        "targets": ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
        "policies": {},
        "jobs": [
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "resolved_target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "routing_plan_path": "plans/routing_plan.json",
                "output_formats": ["wav"],
                "contexts": ["render"],
                "notes": ["compat job 1"],
            },
            {
                "job_id": "JOB.002",
                "target_id": "TARGET.SURROUND.5_1",
                "resolved_target_id": "TARGET.SURROUND.5_1",
                "target_layout_id": "LAYOUT.5_1",
                "routing_plan_path": "plans/routing_plan.json",
                "output_formats": ["wav", "flac"],
                "contexts": ["render"],
                "notes": ["compat job 2"],
            },
        ],
        "request": {
            "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
            "scene_path": "scenes/test/scene.json",
            "routing_plan_path": "plans/routing_plan.json",
        },
        "resolved": {
            "target_layout_id": "LAYOUT.2_0",
            "channel_order": ["SPK.L", "SPK.R"],
            "channel_count": 2,
            "family": "stereo",
            "has_lfe": False,
            "downmix_policy_id": None,
            "gates_policy_id": None,
        },
        "resolved_layouts": [
            {
                "target_layout_id": "LAYOUT.2_0",
                "channel_order": ["SPK.L", "SPK.R"],
                "channel_count": 2,
                "family": "stereo",
                "has_lfe": False,
                "downmix_policy_id": None,
                "gates_policy_id": None,
            },
            {
                "target_layout_id": "LAYOUT.5_1",
                "channel_order": ["SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"],
                "channel_count": 6,
                "family": "surround",
                "has_lfe": True,
                "downmix_policy_id": None,
                "gates_policy_id": None,
            },
        ],
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "request": {
            "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
            "scene_path": "scenes/test/scene.json",
            "routing_plan_path": "plans/routing_plan.json",
        },
        "jobs": [
            {
                "job_id": "JOB.001",
                "status": "skipped",
                "output_files": [],
                "notes": [
                    "reason: dry_run",
                    "target_layout_id: LAYOUT.2_0",
                    "resolved_target_id: TARGET.STEREO.2_0",
                ],
            },
            {
                "job_id": "JOB.002",
                "status": "skipped",
                "output_files": [],
                "notes": [
                    "reason: dry_run",
                    "target_layout_id: LAYOUT.5_1",
                    "resolved_target_id: TARGET.SURROUND.5_1",
                ],
            },
        ],
        "policies_applied": {
            "downmix_policy_id": None,
            "gates_policy_id": None,
            "matrix_id": None,
        },
        "qa_gates": {
            "status": "not_run",
            "gates": [],
        },
    }


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exit_code = main(args)
    return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()


def _fresh_case_dir(case_id: str) -> Path:
    _SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    for idx in range(1000):
        suffix = f"{idx:03d}"
        case_dir = _SANDBOX_ROOT / f"{case_id}_{suffix}"
        if case_dir.exists():
            continue
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir
    raise AssertionError(f"Could not allocate a fresh sandbox directory for case: {case_id}")


def _assert_no_backslash_path_evidence(test_case: unittest.TestCase, payload: dict[str, Any]) -> None:
    issues = payload.get("issues")
    test_case.assertIsInstance(issues, list)
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        evidence = issue.get("evidence")
        if not isinstance(evidence, dict):
            continue
        for key, value in evidence.items():
            if "path" not in str(key).lower():
                continue
            if isinstance(value, str):
                test_case.assertNotIn("\\", value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        test_case.assertNotIn("\\", item)


class TestRenderCompatCli(unittest.TestCase):
    def test_happy_path_no_issues(self) -> None:
        temp_path = _fresh_case_dir("happy_path")
        request_path = temp_path / "render_request.json"
        plan_path = temp_path / "render_plan.json"
        report_path = temp_path / "render_report.json"

        _write_json(request_path, _base_request())
        _write_json(plan_path, _base_plan())
        _write_json(report_path, _base_report())

        exit_code, stdout, stderr = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--report", str(report_path),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload, {"issues": []})

    def test_mismatch_issues_are_stable_and_sorted(self) -> None:
        temp_path = _fresh_case_dir("mismatch_path")
        request_path = temp_path / "render_request.json"
        plan_path = temp_path / "render_plan.json"
        report_path = temp_path / "render_report.json"

        request_payload = _base_request()
        plan_payload = _base_plan()
        report_payload = _base_report()

        plan_payload["scene_path"] = "scenes/plan_scene.json"
        plan_payload["request"] = {
            "target_layout_ids": ["LAYOUT.2_0"],
            "scene_path": "scenes/plan_scene.json",
        }
        plan_payload["jobs"] = [plan_payload["jobs"][0]]
        plan_payload["targets"] = ["TARGET.STEREO.2_0"]

        report_payload["request"] = {
            "target_layout_ids": ["LAYOUT.9_1"],
            "scene_path": "scenes/report_scene.json",
        }
        report_payload["jobs"] = [
            {
                "job_id": "JOB.001",
                "status": "skipped",
                "output_files": [],
                "notes": [
                    "reason: dry_run",
                    "target_layout_id: LAYOUT.5_1",
                ],
            },
            {
                "job_id": "JOB.999",
                "status": "skipped",
                "output_files": [],
                "notes": [
                    "reason: dry_run",
                    "target_layout_id: LAYOUT.9_1",
                ],
            },
        ]

        _write_json(request_path, request_payload)
        _write_json(plan_path, plan_payload)
        _write_json(report_path, report_payload)

        exit_code, stdout, stderr = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--report", str(report_path),
        ])
        self.assertEqual(exit_code, 2, msg=stderr)
        payload = json.loads(stdout)
        _assert_no_backslash_path_evidence(self, payload)

        issues = payload.get("issues")
        self.assertIsInstance(issues, list)
        issue_triplets = [
            (
                issue.get("severity"),
                issue.get("issue_id"),
                issue.get("message"),
            )
            for issue in issues
            if isinstance(issue, dict)
        ]
        self.assertEqual(
            issue_triplets,
            sorted(
                issue_triplets,
                key=lambda item: (str(item[0]), str(item[1]), str(item[2])),
            ),
        )

        expected_issue_ids = [
            "ISSUE.RENDER.COMPAT.PLAN_JOB_COUNT_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REPORT_JOB_SET_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REPORT_LAYOUT_ID_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REPORT_LINK_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REQUEST_ROUTING_PATH_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REQUEST_SCENE_PATH_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REQUEST_TARGETS_MISMATCH",
            "ISSUE.RENDER.COMPAT.PLAN_REPORT_RESOLVED_TARGET_MISSING",
        ]
        self.assertEqual([triplet[1] for triplet in issue_triplets], expected_issue_ids)

    def test_determinism_two_runs_identical_bytes(self) -> None:
        temp_path = _fresh_case_dir("determinism")
        request_path = temp_path / "render_request.json"
        plan_path = temp_path / "render_plan.json"
        report_path = temp_path / "render_report.json"
        out_a = temp_path / "compat_a.json"
        out_b = temp_path / "compat_b.json"

        _write_json(request_path, _base_request())
        _write_json(plan_path, _base_plan())
        _write_json(report_path, _base_report())

        exit_a, _, err_a = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--report", str(report_path),
            "--out", str(out_a),
        ])
        exit_b, _, err_b = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--report", str(report_path),
            "--out", str(out_b),
        ])
        self.assertEqual(exit_a, 0, msg=err_a)
        self.assertEqual(exit_b, 0, msg=err_b)
        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_target_id_variants_allow_more_jobs_than_target_layout_ids(self) -> None:
        temp_path = _fresh_case_dir("target_id_variants_job_count")
        request_path = temp_path / "render_request.json"
        plan_path = temp_path / "render_plan.json"
        report_path = temp_path / "render_report.json"

        request_payload = {
            "schema_version": "0.1.0",
            "target_layout_ids": ["LAYOUT.2_0"],
            "scene_path": "scenes/test/scene.json",
            "options": {
                "target_ids": [
                    "TARGET.STEREO.2_0",
                    "TARGET.STEREO.2_0_ALT",
                ]
            },
        }
        plan_payload = {
            "schema_version": "0.1.0",
            "plan_id": "PLAN.render.compat.stereo.variants.1234abcd",
            "scene_path": "scenes/test/scene.json",
            "targets": ["TARGET.STEREO.2_0", "TARGET.STEREO.2_0_ALT"],
            "policies": {},
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "target_id": "TARGET.STEREO.2_0",
                    "resolved_target_id": "TARGET.STEREO.2_0",
                    "target_layout_id": "LAYOUT.2_0",
                    "output_formats": ["wav"],
                    "contexts": ["render"],
                    "notes": [],
                },
                {
                    "job_id": "JOB.002",
                    "target_id": "TARGET.STEREO.2_0_ALT",
                    "resolved_target_id": "TARGET.STEREO.2_0_ALT",
                    "target_layout_id": "LAYOUT.2_0",
                    "output_formats": ["wav"],
                    "contexts": ["render"],
                    "notes": [],
                },
            ],
            "request": {
                "target_layout_ids": ["LAYOUT.2_0"],
                "scene_path": "scenes/test/scene.json",
                "options": {
                    "target_ids": [
                        "TARGET.STEREO.2_0",
                        "TARGET.STEREO.2_0_ALT",
                    ]
                },
            },
            "resolved": {
                "target_layout_id": "LAYOUT.2_0",
                "channel_order": ["SPK.L", "SPK.R"],
            },
            "resolved_layouts": [
                {
                    "target_layout_id": "LAYOUT.2_0",
                    "channel_order": ["SPK.L", "SPK.R"],
                }
            ],
        }
        report_payload = {
            "schema_version": "0.1.0",
            "request": {
                "target_layout_ids": ["LAYOUT.2_0"],
                "scene_path": "scenes/test/scene.json",
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "status": "completed",
                    "output_files": [],
                    "notes": [
                        "target_layout_id: LAYOUT.2_0",
                        "resolved_target_id: TARGET.STEREO.2_0",
                    ],
                },
                {
                    "job_id": "JOB.002",
                    "status": "completed",
                    "output_files": [],
                    "notes": [
                        "target_layout_id: LAYOUT.2_0",
                        "resolved_target_id: TARGET.STEREO.2_0_ALT",
                    ],
                },
            ],
            "policies_applied": {
                "downmix_policy_id": None,
                "gates_policy_id": None,
                "matrix_id": None,
            },
            "qa_gates": {"status": "not_run", "gates": []},
        }

        _write_json(request_path, request_payload)
        _write_json(plan_path, plan_payload)
        _write_json(report_path, report_payload)

        exit_code, stdout, stderr = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--report", str(report_path),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload, {"issues": []})

    def test_overwrite_refusal_without_force(self) -> None:
        temp_path = _fresh_case_dir("overwrite")
        request_path = temp_path / "render_request.json"
        plan_path = temp_path / "render_plan.json"
        out_path = temp_path / "compat.json"

        _write_json(request_path, _base_request())
        _write_json(plan_path, _base_plan())
        out_path.write_text("{}", encoding="utf-8")

        exit_code, stdout, stderr = _run_main([
            "render-compat",
            "--request", str(request_path),
            "--plan", str(plan_path),
            "--out", str(out_path),
        ])
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("File exists", stderr)
        self.assertIn("--force", stderr)
        self.assertEqual(out_path.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
