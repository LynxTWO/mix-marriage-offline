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


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_channel_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


STAGE_ID_PLANNING = "planning"
STAGE_ID_RESAMPLING = "resampling"
STAGE_ID_DSP_HOOKS = "dsp_hooks"
STAGE_ID_EXPORT_FINALIZE = "export_finalize"
STAGE_ID_QA_GATES = "qa_gates"

_DEFAULT_WALL_CLOCK_DISCLAIMER = (
    "wall_clock is opt-in and non-deterministic; keep it disabled for golden "
    "determinism tests."
)


def _normalize_note_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_where_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["(report)"]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_str(item).replace("\\", "/").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered or ["(report)"]


def _normalize_metric_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _coerce_str(item.get("name")).strip() or _coerce_str(item.get("key")).strip()
        metric_value = _coerce_float(item.get("value"))
        if not name or metric_value is None:
            continue
        row: dict[str, Any] = {"name": name, "value": metric_value}
        unit = _coerce_str(item.get("unit")).strip()
        if unit:
            row["unit"] = unit
        rows.append(row)
    return rows


def build_stage_metric_entry(
    *,
    stage_id: str,
    scope: str,
    where: list[str] | tuple[str, ...] | None,
    metrics: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stage_id": _coerce_str(stage_id).strip(),
        "scope": _coerce_str(scope).strip() or "job",
        "where": _normalize_where_list(list(where or [])),
        "metrics": _normalize_metric_rows(metrics or []),
        "notes": _normalize_note_list(notes or []),
    }


def build_stage_evidence_entry(
    *,
    stage_id: str,
    scope: str,
    where: list[str] | tuple[str, ...] | None,
    codes: list[str] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stage_id": _coerce_str(stage_id).strip(),
        "scope": _coerce_str(scope).strip() or "job",
        "where": _normalize_where_list(list(where or [])),
        "evidence": {
            "codes": _normalize_note_list(codes or []),
            "metrics": _normalize_metric_rows(metrics or []),
            "notes": _normalize_note_list(notes or []),
        },
    }


def _stage_job_id(where: list[str]) -> str:
    for item in where:
        if item.startswith("JOB."):
            return item
    return ""


def _stage_sort_key(entry: dict[str, Any]) -> tuple[str, str, tuple[str, ...], str, str]:
    where = _normalize_where_list(entry.get("where"))
    return (
        _stage_job_id(where),
        _coerce_str(entry.get("stage_id")).strip(),
        tuple(where),
        _coerce_str(entry.get("scope")).strip(),
        json.dumps(entry, ensure_ascii=True, sort_keys=True),
    )


def sort_stage_entries(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = [
        _json_clone(entry)
        for entry in entries
        if isinstance(entry, dict)
    ]
    normalized.sort(key=_stage_sort_key)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in normalized:
        signature = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(entry)
    return deduped


def build_wall_clock_report(
    *,
    stages: list[dict[str, Any]] | None,
    disclaimer: str | None = None,
) -> dict[str, Any] | None:
    normalized_stages: list[dict[str, Any]] = []
    for row in stages or []:
        if not isinstance(row, dict):
            continue
        elapsed_seconds = _coerce_float(row.get("elapsed_seconds"))
        if elapsed_seconds is None or elapsed_seconds < 0.0:
            continue
        normalized_stages.append(
            {
                "stage_id": _coerce_str(row.get("stage_id")).strip(),
                "scope": _coerce_str(row.get("scope")).strip() or "report",
                "where": _normalize_where_list(row.get("where")),
                "elapsed_seconds": round(elapsed_seconds, 6),
            }
        )
    if not normalized_stages:
        return None
    normalized_stages.sort(key=_stage_sort_key)
    return {
        "enabled": True,
        "disclaimer": _coerce_str(disclaimer).strip() or _DEFAULT_WALL_CLOCK_DISCLAIMER,
        "stages": normalized_stages,
    }


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


def _requested_sample_rate_hz(plan: dict[str, Any]) -> int | None:
    request_echo = plan.get("request")
    if not isinstance(request_echo, dict):
        return None
    options = request_echo.get("options")
    if not isinstance(options, dict):
        return None
    sample_rate_hz = _coerce_int(options.get("sample_rate_hz"))
    if sample_rate_hz is None or sample_rate_hz <= 0:
        return None
    return sample_rate_hz


def _job_output_rows(plan_job: dict[str, Any]) -> list[dict[str, Any]]:
    raw_outputs = plan_job.get("outputs")
    if not isinstance(raw_outputs, list):
        return []
    return [row for row in raw_outputs if isinstance(row, dict)]


def _job_stage_where(job_id: str, *parts: str) -> list[str]:
    where = [job_id] if job_id else []
    for part in parts:
        text = _coerce_str(part).strip()
        if text:
            where.append(text)
    return where or ["(report)"]


def _append_stage_pair(
    *,
    stage_metrics: list[dict[str, Any]],
    stage_evidence: list[dict[str, Any]],
    stage_id: str,
    scope: str,
    where: list[str],
    metrics: list[dict[str, Any]] | None,
    notes: list[str] | None,
    codes: list[str] | None,
) -> None:
    stage_metrics.append(
        build_stage_metric_entry(
            stage_id=stage_id,
            scope=scope,
            where=where,
            metrics=metrics,
            notes=notes,
        )
    )
    stage_evidence.append(
        build_stage_evidence_entry(
            stage_id=stage_id,
            scope=scope,
            where=where,
            codes=codes,
            metrics=metrics,
            notes=notes,
        )
    )


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
    wall_clock: dict[str, Any] | None = None,
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
    requested_sample_rate_hz = _requested_sample_rate_hz(plan)
    report_jobs: list[dict[str, Any]] = []
    stage_metrics: list[dict[str, Any]] = []
    stage_evidence: list[dict[str, Any]] = []
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

        render_intent = plan_job.get("render_intent")
        if isinstance(render_intent, dict):
            report_job["render_intent"] = _json_clone(render_intent)

        lfe_receipt = plan_job.get("lfe_receipt")
        if isinstance(lfe_receipt, dict):
            report_job["lfe_receipt"] = _json_clone(lfe_receipt)

        resolved_layout = resolved_by_layout.get(target_layout_id)
        channel_count = 0
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

        job_where = _job_stage_where(job_id, target_layout_id)
        planned_outputs = _job_output_rows(plan_job)
        planned_output_paths = sorted(
            _coerce_str(row.get("path")).strip()
            for row in planned_outputs
            if _coerce_str(row.get("path")).strip()
        )
        planned_output_count = len(planned_outputs) or len(list(plan_job.get("output_formats") or []))
        common_metrics: list[dict[str, Any]] = []
        if channel_count > 0:
            common_metrics.append({"name": "channel_count", "value": float(channel_count)})
        if requested_sample_rate_hz is not None:
            common_metrics.append(
                {"name": "sample_rate_hz", "value": float(requested_sample_rate_hz), "unit": "Hz"}
            )
        planning_metrics = [
            *common_metrics,
            {"name": "planned_output_count", "value": float(planned_output_count)},
        ]
        planning_notes = [
            f"status={status}",
            f"reason={reason}",
            *list(report_job.get("notes") or []),
        ]
        _append_stage_pair(
            stage_metrics=stage_metrics,
            stage_evidence=stage_evidence,
            stage_id=STAGE_ID_PLANNING,
            scope="job",
            where=job_where,
            metrics=planning_metrics,
            notes=planning_notes,
            codes=["RENDER.REPORT.PLANNING.DERIVED_FROM_PLAN"],
        )

        resampling_metrics = list(common_metrics)
        if requested_sample_rate_hz is not None:
            resampling_metrics.append({"name": "resample_ratio", "value": 1.0})
        resampling_notes = [
            "No resampling receipt is attached; metrics reflect the planned target state only.",
            f"status={status}",
        ]
        _append_stage_pair(
            stage_metrics=stage_metrics,
            stage_evidence=stage_evidence,
            stage_id=STAGE_ID_RESAMPLING,
            scope="job",
            where=job_where,
            metrics=resampling_metrics,
            notes=resampling_notes,
            codes=["RENDER.REPORT.RESAMPLING.NOT_ATTACHED"],
        )

        dsp_notes = [
            "No DSP hook execution evidence is attached to this render_plan job.",
            f"status={status}",
        ]
        _append_stage_pair(
            stage_metrics=stage_metrics,
            stage_evidence=stage_evidence,
            stage_id=STAGE_ID_DSP_HOOKS,
            scope="job",
            where=job_where,
            metrics=list(common_metrics),
            notes=dsp_notes,
            codes=["RENDER.REPORT.DSP_HOOKS.NOT_ATTACHED"],
        )

        export_metrics = [
            *common_metrics,
            {"name": "planned_output_count", "value": float(planned_output_count)},
        ]
        export_notes = [
            "No export finalization receipt is attached; outputs are inferred from the render_plan.",
            f"status={status}",
        ]
        export_notes.extend(f"output_path={path}" for path in planned_output_paths)
        _append_stage_pair(
            stage_metrics=stage_metrics,
            stage_evidence=stage_evidence,
            stage_id=STAGE_ID_EXPORT_FINALIZE,
            scope="job",
            where=job_where,
            metrics=export_metrics,
            notes=export_notes,
            codes=["RENDER.REPORT.EXPORT_FINALIZE.NOT_ATTACHED"],
        )

        qa_metrics = [{"name": "gate_count", "value": 0.0}]
        qa_notes = ["qa_status=not_run", "QA gates are not evaluated in plan-only render_report assembly."]
        _append_stage_pair(
            stage_metrics=stage_metrics,
            stage_evidence=stage_evidence,
            stage_id=STAGE_ID_QA_GATES,
            scope="job",
            where=job_where,
            metrics=qa_metrics,
            notes=qa_notes,
            codes=["RENDER.REPORT.QA_GATES.NOT_RUN"],
        )

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

    report: dict[str, Any] = {
        "jobs": report_jobs,
        "loudness_profile_receipt": loudness_profile_receipt,
        "policies_applied": policies_applied,
        "qa_gates": qa_gates,
        "request": request_summary,
        "schema_version": "0.1.0",
    }
    report["stage_metrics"] = sort_stage_entries(stage_metrics)
    report["stage_evidence"] = sort_stage_entries(stage_evidence)
    wall_clock_payload = build_wall_clock_report(
        stages=list(wall_clock.get("stages") or []) if isinstance(wall_clock, dict) else None,
        disclaimer=_coerce_str(wall_clock.get("disclaimer")).strip() if isinstance(wall_clock, dict) else None,
    )
    if wall_clock_payload is not None:
        report["wall_clock"] = wall_clock_payload
    return report


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
