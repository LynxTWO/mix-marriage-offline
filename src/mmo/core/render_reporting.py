"""Build deterministic render_report payloads from render_plan artifacts."""

from __future__ import annotations

import json
from typing import Any

from mmo.core.layout_export import (
    dual_lfe_wav_export_warnings,
    ffmpeg_layout_string_from_channel_order,
)
from mmo.core.loudness_profiles import (
    DEFAULT_LOUDNESS_PROFILE_ID,
    resolve_loudness_profile_receipt,
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_channel_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _resolved_layout_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = plan.get("resolved_layouts")
    if isinstance(raw_rows, list):
        rows.extend(row for row in raw_rows if isinstance(row, dict))
    if not rows:
        single = plan.get("resolved")
        if isinstance(single, dict):
            rows.append(single)
    return rows


def _resolved_layout_index(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _resolved_layout_rows(plan):
        layout_id = _coerce_str(row.get("target_layout_id")).strip()
        channel_order = _coerce_channel_order(row.get("channel_order"))
        if not layout_id or not channel_order:
            continue
        channel_count = _coerce_int(row.get("channel_count"))
        if channel_count is None or channel_count <= 0:
            channel_count = len(channel_order)
        index.setdefault(
            layout_id,
            {
                "channel_count": channel_count,
                "channel_order": list(channel_order),
            },
        )
    return index


def _job_writes_wav(plan_job: dict[str, Any]) -> bool:
    output_formats = plan_job.get("output_formats")
    if not isinstance(output_formats, list):
        return True
    return any(
        _coerce_str(item).strip().lower() == "wav"
        for item in output_formats
    )


def _requested_loudness_profile_id(plan: dict[str, Any]) -> str | None:
    request_echo = plan.get("request")
    if isinstance(request_echo, dict):
        options = request_echo.get("options")
        if isinstance(options, dict):
            profile_id = _coerce_str(options.get("loudness_profile_id")).strip()
            if profile_id:
                return profile_id

    policies = plan.get("policies")
    if isinstance(policies, dict):
        profile_id = _coerce_str(policies.get("loudness_profile_id")).strip()
        if profile_id:
            return profile_id
    return None


def _loudness_profile_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    requested_profile_id = _requested_loudness_profile_id(plan)
    try:
        return resolve_loudness_profile_receipt(requested_profile_id)
    except ValueError as exc:
        fallback = resolve_loudness_profile_receipt(DEFAULT_LOUDNESS_PROFILE_ID)
        warnings = list(fallback.get("warnings") or [])
        warnings.insert(
            0,
            (
                f"{exc}. Falling back to default loudness_profile_id "
                f"{DEFAULT_LOUDNESS_PROFILE_ID!r}."
            ),
        )
        fallback["warnings"] = warnings
        return fallback


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

    request_summary: dict[str, Any] = {}

    if isinstance(request_echo, dict):
        # Multi-target: echo has target_layout_ids.
        target_layout_ids = request_echo.get("target_layout_ids")
        if isinstance(target_layout_ids, list) and target_layout_ids:
            request_summary["scene_path"] = request_echo.get("scene_path", scene_path)
            request_summary["target_layout_ids"] = sorted(target_layout_ids)
        elif request_echo.get("target_layout_id"):
            request_summary["scene_path"] = request_echo.get("scene_path", scene_path)
            request_summary["target_layout_id"] = request_echo["target_layout_id"]
        else:
            # Fallback: derive from first job.
            request_summary = _summary_from_first_job(plan, scene_path)
    else:
        request_summary = _summary_from_first_job(plan, scene_path)

    # Add routing_plan_path if present.
    routing_plan_path: str | None = None
    if isinstance(request_echo, dict):
        routing_plan_path = request_echo.get("routing_plan_path")
    if isinstance(routing_plan_path, str) and routing_plan_path:
        request_summary["routing_plan_path"] = routing_plan_path

    # ── jobs ─────────────────────────────────────────────────────
    plan_jobs = plan.get("jobs")
    if not isinstance(plan_jobs, list):
        plan_jobs = []

    resolved_by_layout = _resolved_layout_index(plan)
    report_jobs: list[dict[str, Any]] = []
    for plan_job in plan_jobs:
        if not isinstance(plan_job, dict):
            continue
        job_id = _coerce_str(plan_job.get("job_id")).strip()
        target_layout_id = _coerce_str(plan_job.get("target_layout_id")).strip()
        report_job: dict[str, Any] = {
            "job_id": job_id,
            "notes": [f"reason: {reason}"],
            "output_files": [],
            "status": status,
        }
        if target_layout_id:
            report_job["target_layout_id"] = target_layout_id

        lfe_receipt = plan_job.get("lfe_receipt")
        if isinstance(lfe_receipt, dict):
            report_job["lfe_receipt"] = json.loads(json.dumps(lfe_receipt))

        resolved_layout = resolved_by_layout.get(target_layout_id)
        if resolved_layout is not None:
            channel_order = list(resolved_layout.get("channel_order") or [])
            channel_count = int(resolved_layout.get("channel_count") or len(channel_order))
            if channel_order and channel_count > 0:
                report_job["channel_order"] = channel_order
                report_job["channel_count"] = channel_count
                ffmpeg_layout = ffmpeg_layout_string_from_channel_order(channel_order)
                if ffmpeg_layout:
                    report_job["ffmpeg_channel_layout"] = ffmpeg_layout
                if _job_writes_wav(plan_job):
                    warnings = dual_lfe_wav_export_warnings(
                        channel_order=channel_order,
                        ffmpeg_layout_string=ffmpeg_layout,
                    )
                    if warnings:
                        report_job["warnings"] = warnings
                        report_job["notes"].extend(warnings)
        report_jobs.append(report_job)

    # ── policies_applied ─────────────────────────────────────────
    plan_policies = plan.get("policies")
    if not isinstance(plan_policies, dict):
        plan_policies = {}

    policies_applied: dict[str, Any] = {
        "downmix_policy_id": plan_policies.get("downmix_policy_id") or None,
        "gates_policy_id": plan_policies.get("gates_policy_id") or None,
        "lfe_derivation_profile_id": plan_policies.get("lfe_derivation_profile_id") or None,
        "matrix_id": None,
    }

    # ── qa_gates ─────────────────────────────────────────────────
    qa_gates: dict[str, Any] = {
        "gates": [],
        "status": "not_run",
    }

    loudness_profile_receipt = _loudness_profile_receipt(plan)

    return {
        "jobs": report_jobs,
        "loudness_profile_receipt": loudness_profile_receipt,
        "policies_applied": policies_applied,
        "qa_gates": qa_gates,
        "request": request_summary,
        "schema_version": "0.1.0",
    }


def _summary_from_first_job(
    plan: dict[str, Any],
    scene_path: str,
) -> dict[str, Any]:
    """Derive request_summary from the first job (fallback)."""
    jobs_raw = plan.get("jobs")
    if isinstance(jobs_raw, list) and jobs_raw:
        target_layout_id = jobs_raw[0].get("target_layout_id", "")
    else:
        target_layout_id = ""
    return {
        "scene_path": scene_path,
        "target_layout_id": target_layout_id,
    }
