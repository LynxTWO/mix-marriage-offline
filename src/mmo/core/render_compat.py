from __future__ import annotations

import json
from typing import Any


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _to_posix(value: str) -> str:
    return value.replace("\\", "/")


def _normalize_path(value: Any) -> str:
    return _to_posix(_coerce_str(value).strip())


def _normalize_id(value: Any) -> str:
    return _coerce_str(value).strip()


def _extract_target_layout_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []

    target_layout_ids = payload.get("target_layout_ids")
    if isinstance(target_layout_ids, list):
        normalized = sorted(
            {
                _normalize_id(item)
                for item in target_layout_ids
                if _normalize_id(item)
            }
        )
        if normalized:
            return normalized

    target_layout_id = _normalize_id(payload.get("target_layout_id"))
    if target_layout_id:
        return [target_layout_id]
    return []


def _extract_target_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    options = payload.get("options")
    if not isinstance(options, dict):
        return []
    target_ids = options.get("target_ids")
    if not isinstance(target_ids, list):
        return []
    return sorted(
        {
            _normalize_id(target_id)
            for target_id in target_ids
            if _normalize_id(target_id)
        }
    )


def _extract_job_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [item for item in jobs if isinstance(item, dict)]


def _job_ids(jobs: list[dict[str, Any]]) -> list[str]:
    return sorted({_normalize_id(job.get("job_id")) for job in jobs if _normalize_id(job.get("job_id"))})


def _duplicate_ids(jobs: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for job in jobs:
        job_id = _normalize_id(job.get("job_id"))
        if not job_id:
            continue
        counts[job_id] = counts.get(job_id, 0) + 1
    return sorted(job_id for job_id, count in counts.items() if count > 1)


def _jobs_by_id(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for job in jobs:
        job_id = _normalize_id(job.get("job_id"))
        if not job_id:
            continue
        if job_id not in by_id:
            by_id[job_id] = job
    return by_id


def _normalized_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in sorted(evidence.keys()):
        value = evidence[key]
        key_lower = key.lower()
        if isinstance(value, str):
            normalized[key] = _to_posix(value) if "path" in key_lower else value
            continue
        if isinstance(value, list):
            converted: list[Any] = []
            for item in value:
                if isinstance(item, str) and "path" in key_lower:
                    converted.append(_to_posix(item))
                else:
                    converted.append(item)
            normalized[key] = converted
            continue
        if isinstance(value, dict):
            normalized[key] = _normalized_evidence(value)
            continue
        normalized[key] = value
    return normalized


def _issue(
    *,
    issue_id: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "message": message,
        "evidence": _normalized_evidence(evidence),
    }


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _normalize_id(issue.get("severity")),
        _normalize_id(issue.get("issue_id")),
        _normalize_id(issue.get("message")),
        json.dumps(issue.get("evidence", {}), sort_keys=True, separators=(",", ":")),
    )


def _sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=_issue_sort_key)


def _job_note_value(job: dict[str, Any], prefixes: tuple[str, ...]) -> str:
    notes = job.get("notes")
    if not isinstance(notes, list):
        return ""
    for note in notes:
        note_text = _coerce_str(note).strip()
        if not note_text:
            continue
        for prefix in prefixes:
            if note_text.startswith(prefix):
                return _normalize_id(note_text[len(prefix):])
    return ""


def _report_job_layout_id(job: dict[str, Any]) -> str:
    direct_layout = _normalize_id(job.get("target_layout_id"))
    if direct_layout:
        return direct_layout
    direct_layout = _normalize_id(job.get("layout_id"))
    if direct_layout:
        return direct_layout
    return _job_note_value(job, ("target_layout_id:", "layout_id:"))


def _report_job_target_id(job: dict[str, Any]) -> str:
    direct_target = _normalize_id(job.get("target_id"))
    if direct_target:
        return direct_target
    return _job_note_value(job, ("target_id:",))


def _report_job_resolved_target_id(job: dict[str, Any]) -> str:
    direct_resolved = _normalize_id(job.get("resolved_target_id"))
    if direct_resolved:
        return direct_resolved
    return _job_note_value(job, ("resolved_target_id:",))


def _extract_plan_target_layout_ids(plan: dict[str, Any]) -> list[str]:
    plan_request = plan.get("request")
    from_request = _extract_target_layout_ids(plan_request)
    if from_request:
        return from_request

    layout_ids: set[str] = set()
    for job in _extract_job_rows(plan):
        layout_id = _normalize_id(job.get("target_layout_id"))
        if layout_id:
            layout_ids.add(layout_id)
    return sorted(layout_ids)


def validate_request_plan_compat(
    request: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    plan_request = plan.get("request")
    if not isinstance(plan_request, dict):
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REQUEST_MISSING",
                severity="error",
                message="Render plan request echo must be present.",
                evidence={},
            )
        )
        plan_request = {}

    request_target_layout_ids = _extract_target_layout_ids(request)
    plan_target_layout_ids = _extract_target_layout_ids(plan_request)
    if request_target_layout_ids != plan_target_layout_ids:
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REQUEST_TARGETS_MISMATCH",
                severity="error",
                message="Render plan request targets must match render request targets.",
                evidence={
                    "request_target_layout_ids": request_target_layout_ids,
                    "plan_request_target_layout_ids": plan_target_layout_ids,
                },
            )
        )

    request_scene_path = _normalize_path(request.get("scene_path"))
    plan_request_scene_path = _normalize_path(plan_request.get("scene_path"))
    if request_scene_path != plan_request_scene_path:
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REQUEST_SCENE_PATH_MISMATCH",
                severity="error",
                message="Render plan request scene_path must match render request scene_path.",
                evidence={
                    "request_scene_path": request_scene_path,
                    "plan_request_scene_path": plan_request_scene_path,
                },
            )
        )

    request_routing_plan_path = _normalize_path(request.get("routing_plan_path"))
    plan_routing_plan_path = _normalize_path(plan_request.get("routing_plan_path"))
    if bool(request_routing_plan_path) != bool(plan_routing_plan_path):
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REQUEST_ROUTING_PATH_MISMATCH",
                severity="error",
                message=(
                    "Render plan request routing_plan_path presence must match render request "
                    "routing_plan_path presence."
                ),
                evidence={
                    "request_routing_plan_path": request_routing_plan_path,
                    "plan_request_routing_plan_path": plan_routing_plan_path,
                },
            )
        )
    elif request_routing_plan_path and request_routing_plan_path != plan_routing_plan_path:
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REQUEST_ROUTING_PATH_MISMATCH",
                severity="error",
                message="Render plan request routing_plan_path must match render request routing_plan_path.",
                evidence={
                    "request_routing_plan_path": request_routing_plan_path,
                    "plan_request_routing_plan_path": plan_routing_plan_path,
                },
            )
        )

    if isinstance(request.get("target_layout_ids"), list):
        request_target_ids = _extract_target_ids(request)
        expected_job_count = (
            len(request_target_ids)
            if request_target_ids
            else len(request_target_layout_ids)
        )
        plan_job_count = len(_extract_job_rows(plan))
        if expected_job_count != plan_job_count:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_JOB_COUNT_MISMATCH",
                    severity="error",
                    message=(
                        "Render plan jobs count must match render request target_layout_ids "
                        "count for multi-target requests, or request.options.target_ids count "
                        "when explicit target variants are provided."
                    ),
                    evidence={
                        "request_target_layout_ids_count": len(request_target_layout_ids),
                        "request_target_ids_count": len(request_target_ids),
                        "plan_jobs_count": plan_job_count,
                    },
                )
            )

    return _sort_issues(issues)


def validate_plan_report_compat(
    plan: dict[str, Any],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    plan_plan_id = _normalize_id(plan.get("plan_id"))
    report_request = report.get("request")
    report_request_payload = report_request if isinstance(report_request, dict) else {}
    report_plan_id = _normalize_id(report_request_payload.get("plan_id"))

    if report_plan_id:
        if report_plan_id != plan_plan_id:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_PLAN_ID_MISMATCH",
                    severity="error",
                    message="Render report plan_id must match render plan plan_id.",
                    evidence={
                        "plan_plan_id": plan_plan_id,
                        "report_request_plan_id": report_plan_id,
                    },
                )
            )
    else:
        plan_scene_path = _normalize_path(plan.get("scene_path"))
        report_scene_path = _normalize_path(report_request_payload.get("scene_path"))
        plan_target_layout_ids = _extract_plan_target_layout_ids(plan)
        report_target_layout_ids = _extract_target_layout_ids(report_request_payload)
        if (
            plan_scene_path != report_scene_path
            or plan_target_layout_ids != report_target_layout_ids
        ):
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_LINK_MISMATCH",
                    severity="error",
                    message=(
                        "Render report request link must be consistent with render plan when "
                        "report.request.plan_id is absent."
                    ),
                    evidence={
                        "plan_scene_path": plan_scene_path,
                        "report_scene_path": report_scene_path,
                        "plan_target_layout_ids": plan_target_layout_ids,
                        "report_target_layout_ids": report_target_layout_ids,
                    },
                )
            )

    plan_jobs = _extract_job_rows(plan)
    report_jobs = _extract_job_rows(report)
    plan_job_ids = _job_ids(plan_jobs)
    report_job_ids = _job_ids(report_jobs)
    missing_job_ids = sorted(set(plan_job_ids) - set(report_job_ids))
    unexpected_job_ids = sorted(set(report_job_ids) - set(plan_job_ids))
    duplicate_plan_job_ids = _duplicate_ids(plan_jobs)
    duplicate_report_job_ids = _duplicate_ids(report_jobs)
    if missing_job_ids or unexpected_job_ids or duplicate_plan_job_ids or duplicate_report_job_ids:
        issues.append(
            _issue(
                issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_JOB_SET_MISMATCH",
                severity="error",
                message="Render report jobs must correspond 1:1 with render plan jobs by job_id.",
                evidence={
                    "plan_job_ids": plan_job_ids,
                    "report_job_ids": report_job_ids,
                    "missing_job_ids": missing_job_ids,
                    "unexpected_job_ids": unexpected_job_ids,
                    "duplicate_plan_job_ids": duplicate_plan_job_ids,
                    "duplicate_report_job_ids": duplicate_report_job_ids,
                },
            )
        )

    plan_jobs_by_id = _jobs_by_id(plan_jobs)
    report_jobs_by_id = _jobs_by_id(report_jobs)
    common_job_ids = sorted(set(plan_jobs_by_id.keys()) & set(report_jobs_by_id.keys()))
    for job_id in common_job_ids:
        plan_job = plan_jobs_by_id[job_id]
        report_job = report_jobs_by_id[job_id]

        plan_layout_id = _normalize_id(plan_job.get("target_layout_id"))
        report_layout_id = _report_job_layout_id(report_job)
        if not report_layout_id:
            # Fall back to request summary for deterministic single-target reports.
            request_target_layout_ids = _extract_target_layout_ids(report_request_payload)
            if len(request_target_layout_ids) == 1 and len(common_job_ids) == 1:
                report_layout_id = request_target_layout_ids[0]
        if not report_layout_id:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_LAYOUT_ID_MISMATCH",
                    severity="error",
                    message="Render report job layout_id must match render plan job target_layout_id.",
                    evidence={
                        "job_id": job_id,
                        "plan_target_layout_id": plan_layout_id,
                        "report_target_layout_id": report_layout_id,
                    },
                )
            )
        elif plan_layout_id != report_layout_id:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_LAYOUT_ID_MISMATCH",
                    severity="error",
                    message="Render report job layout_id must match render plan job target_layout_id.",
                    evidence={
                        "job_id": job_id,
                        "plan_target_layout_id": plan_layout_id,
                        "report_target_layout_id": report_layout_id,
                    },
                )
            )

        plan_resolved_target_id = _normalize_id(plan_job.get("resolved_target_id"))
        if not plan_resolved_target_id:
            continue

        report_resolved_target_id = _report_job_resolved_target_id(report_job)
        report_target_id = _report_job_target_id(report_job)
        compared_report_target_id = report_resolved_target_id or report_target_id
        if not compared_report_target_id:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_RESOLVED_TARGET_MISSING",
                    severity="warn",
                    message=(
                        "Render report job resolved_target_id is missing while render plan job "
                        "resolved_target_id is present."
                    ),
                    evidence={
                        "job_id": job_id,
                        "plan_resolved_target_id": plan_resolved_target_id,
                    },
                )
            )
            continue

        if compared_report_target_id != plan_resolved_target_id:
            issues.append(
                _issue(
                    issue_id="ISSUE.RENDER.COMPAT.PLAN_REPORT_RESOLVED_TARGET_MISMATCH",
                    severity="error",
                    message=(
                        "Render report job resolved target must not contradict render plan job "
                        "resolved_target_id."
                    ),
                    evidence={
                        "job_id": job_id,
                        "plan_resolved_target_id": plan_resolved_target_id,
                        "report_resolved_target_id": compared_report_target_id,
                    },
                )
            )

    return _sort_issues(issues)
