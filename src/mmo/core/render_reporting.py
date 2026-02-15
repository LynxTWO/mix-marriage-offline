"""Build deterministic render_report payloads from render_plan artifacts."""

from __future__ import annotations

from typing import Any


def build_render_report_from_plan(
    plan: dict[str, Any],
    *,
    status: str = "skipped",
    reason: str = "dry_run",
) -> dict[str, Any]:
    """Build a schema-valid render_report from a render_plan.

    Every job in the plan is mapped to a report job with the given
    *status* and an empty output_files list.  A note of the form
    ``"reason: <reason>"`` is attached to each job.

    No timestamps are emitted.  If a time field is required later it
    must be passed in explicitly and tested.
    """
    # ── request summary ──────────────────────────────────────────
    request_echo = plan.get("request")
    scene_path = plan.get("scene_path", "")

    if isinstance(request_echo, dict) and request_echo.get("target_layout_id"):
        target_layout_id = request_echo["target_layout_id"]
        request_scene_path = request_echo.get("scene_path", scene_path)
    else:
        # Fallback: derive from first job.
        jobs_raw = plan.get("jobs")
        if isinstance(jobs_raw, list) and jobs_raw:
            target_layout_id = jobs_raw[0].get("target_layout_id", "")
        else:
            target_layout_id = ""
        request_scene_path = scene_path

    request_summary: dict[str, Any] = {
        "scene_path": request_scene_path,
        "target_layout_id": target_layout_id,
    }
    routing_plan_path: str | None = None
    if isinstance(request_echo, dict):
        routing_plan_path = request_echo.get("routing_plan_path")
    if isinstance(routing_plan_path, str) and routing_plan_path:
        request_summary["routing_plan_path"] = routing_plan_path

    # ── jobs ─────────────────────────────────────────────────────
    plan_jobs = plan.get("jobs")
    if not isinstance(plan_jobs, list):
        plan_jobs = []

    report_jobs: list[dict[str, Any]] = []
    for plan_job in plan_jobs:
        if not isinstance(plan_job, dict):
            continue
        job_id = plan_job.get("job_id", "")
        report_job: dict[str, Any] = {
            "job_id": job_id,
            "notes": [f"reason: {reason}"],
            "output_files": [],
            "status": status,
        }
        report_jobs.append(report_job)

    # ── policies_applied ─────────────────────────────────────────
    plan_policies = plan.get("policies")
    if not isinstance(plan_policies, dict):
        plan_policies = {}

    policies_applied: dict[str, Any] = {
        "downmix_policy_id": plan_policies.get("downmix_policy_id") or None,
        "gates_policy_id": plan_policies.get("gates_policy_id") or None,
        "matrix_id": None,
    }

    # ── qa_gates ─────────────────────────────────────────────────
    qa_gates: dict[str, Any] = {
        "gates": [],
        "status": "not_run",
    }

    return {
        "jobs": report_jobs,
        "policies_applied": policies_applied,
        "qa_gates": qa_gates,
        "request": request_summary,
        "schema_version": "0.1.0",
    }
