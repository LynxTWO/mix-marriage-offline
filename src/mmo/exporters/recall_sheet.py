from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _target_scope(issue: Dict[str, Any]) -> str:
    target = issue.get("target")
    if not isinstance(target, dict):
        return ""
    return str(target.get("scope", ""))


def _target_id(issue: Dict[str, Any]) -> str:
    target = issue.get("target")
    if not isinstance(target, dict):
        return ""
    scope = target.get("scope", "")
    if scope == "stem":
        return str(target.get("stem_id", ""))
    if scope == "bus":
        return str(target.get("bus_id", ""))
    return ""


def _evidence_summary(issue: Dict[str, Any]) -> str:
    evidence = issue.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return ""
    parts = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        evid_id = str(item.get("evidence_id", ""))
        value = item.get("value")
        if value is None:
            parts.append(evid_id)
        elif isinstance(value, (dict, list)):
            parts.append(f"{evid_id}:{json.dumps(value, sort_keys=True)}")
        else:
            parts.append(f"{evid_id}:{value}")
    return "; ".join(parts)


def _build_issue_action_map(
    recommendations: Iterable[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return {issue_id: sorted [action_id, ...]} from recommendations."""
    issue_actions: Dict[str, List[str]] = {}
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        issue_id = str(rec.get("issue_id", ""))
        action_id = str(rec.get("action_id", ""))
        if issue_id and action_id:
            issue_actions.setdefault(issue_id, [])
            if action_id not in issue_actions[issue_id]:
                issue_actions[issue_id].append(action_id)
    # Sort each list for determinism
    for key in issue_actions:
        issue_actions[key].sort()
    return issue_actions


def _sort_key(issue: Dict[str, Any]) -> Tuple[int, float, str]:
    severity = issue.get("severity", 0)
    confidence = issue.get("confidence", 0.0)
    issue_id = str(issue.get("issue_id", ""))
    # Sort: severity DESC, confidence DESC, issue_id ASC
    return (-int(severity), -float(confidence), issue_id)


def _sorted_issues(issues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        (issue for issue in issues if isinstance(issue, dict)),
        key=_sort_key,
    )


def _extract_scene_id(scene: Optional[Dict[str, Any]]) -> str:
    if not isinstance(scene, dict):
        return ""
    return str(scene.get("scene_id", ""))


def _extract_scene_object_count(scene: Optional[Dict[str, Any]]) -> str:
    if not isinstance(scene, dict):
        return ""
    objects = scene.get("objects")
    if not isinstance(objects, list):
        return "0"
    return str(len(objects))


def _extract_target_layout_ids(request: Optional[Dict[str, Any]]) -> str:
    """Return pipe-joined target layout IDs from a render_request payload."""
    if not isinstance(request, dict):
        return ""
    # Multi-layout variant
    multi = request.get("target_layout_ids")
    if isinstance(multi, list) and multi:
        return "|".join(sorted(str(lid) for lid in multi if isinstance(lid, str)))
    # Single-layout variant
    single = request.get("target_layout_id")
    if isinstance(single, str) and single.strip():
        return single.strip()
    return ""


def _extract_profile_id(
    profile_id: Optional[str],
    report: Dict[str, Any],
) -> str:
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    # Fallback: read from report
    raw = report.get("profile_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def _extract_preflight_status(preflight: Optional[Dict[str, Any]]) -> str:
    """Return 'pass', 'fail', or 'missing' from a render_preflight payload."""
    if not isinstance(preflight, dict):
        return "missing"
    issues = preflight.get("issues")
    if not isinstance(issues, list):
        return "pass"
    for item in issues:
        if isinstance(item, dict) and str(item.get("severity", "")).strip() == "error":
            return "fail"
    return "pass"


def _extract_render_channel_orders(render_report: Optional[Dict[str, Any]]) -> str:
    """Return pipe-joined ``LAYOUT.*:SPK,...`` entries from render_report jobs."""
    if not isinstance(render_report, dict):
        return ""
    jobs = render_report.get("jobs")
    if not isinstance(jobs, list):
        return ""

    orders_by_layout: dict[str, str] = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        layout_id = str(job.get("target_layout_id", "")).strip()
        channel_order = job.get("channel_order")
        if not layout_id or not isinstance(channel_order, list):
            continue
        normalized = [
            item.strip()
            for item in channel_order
            if isinstance(item, str) and item.strip()
        ]
        if not normalized:
            continue
        orders_by_layout.setdefault(layout_id, ",".join(normalized))

    if not orders_by_layout:
        return ""
    return "|".join(
        f"{layout_id}:{orders_by_layout[layout_id]}"
        for layout_id in sorted(orders_by_layout.keys())
    )


def _extract_render_export_warnings(render_report: Optional[Dict[str, Any]]) -> str:
    """Return deterministic warning summary collected from render_report jobs."""
    if not isinstance(render_report, dict):
        return ""
    jobs = render_report.get("jobs")
    if not isinstance(jobs, list):
        return ""

    warnings: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_warnings = job.get("warnings")
        if isinstance(job_warnings, list):
            for warning in job_warnings:
                if isinstance(warning, str) and warning.strip():
                    warnings.add(warning.strip())
    if not warnings:
        return ""
    return " | ".join(sorted(warnings))


def export_recall_sheet(
    report: Dict[str, Any],
    out_path: Path,
    *,
    scene: Optional[Dict[str, Any]] = None,
    preflight: Optional[Dict[str, Any]] = None,
    profile_id: Optional[str] = None,
    request: Optional[Dict[str, Any]] = None,
    layout_standard: Optional[str] = None,
    render_report: Optional[Dict[str, Any]] = None,
) -> None:
    """Write an issue-centric recall sheet CSV to *out_path*.

    Base columns: rank, issue_id, severity, confidence, message,
                  target_scope, target_id, evidence_summary, action_ids
    Context columns (always emitted; empty when context not provided):
                  scene_id, scene_object_count, target_layout_ids,
                  profile_id, preflight_status, layout_standard,
                  render_channel_orders, render_export_warnings

    Rows sorted by severity DESC, confidence DESC, issue_id ASC.
    """
    issues = report.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    issue_action_map = _build_issue_action_map(recommendations)
    sorted_issues = _sorted_issues(issues)

    # Derive context values once — repeated on every row.
    ctx_scene_id = _extract_scene_id(scene)
    ctx_object_count = _extract_scene_object_count(scene)
    ctx_layout_ids = _extract_target_layout_ids(request)
    ctx_profile_id = _extract_profile_id(profile_id, report)
    ctx_preflight_status = _extract_preflight_status(preflight)
    ctx_layout_standard = layout_standard.strip() if isinstance(layout_standard, str) and layout_standard.strip() else ""
    ctx_render_channel_orders = _extract_render_channel_orders(render_report)
    ctx_render_export_warnings = _extract_render_export_warnings(render_report)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "issue_id",
                "severity",
                "confidence",
                "message",
                "target_scope",
                "target_id",
                "evidence_summary",
                "action_ids",
                "scene_id",
                "scene_object_count",
                "target_layout_ids",
                "profile_id",
                "preflight_status",
                "layout_standard",
                "render_channel_orders",
                "render_export_warnings",
            ]
        )
        for rank, issue in enumerate(sorted_issues, start=1):
            issue_id = str(issue.get("issue_id", ""))
            action_ids = "|".join(issue_action_map.get(issue_id, []))
            writer.writerow(
                [
                    rank,
                    issue_id,
                    issue.get("severity", ""),
                    issue.get("confidence", ""),
                    issue.get("message", ""),
                    _target_scope(issue),
                    _target_id(issue),
                    _evidence_summary(issue),
                    action_ids,
                    ctx_scene_id,
                    ctx_object_count,
                    ctx_layout_ids,
                    ctx_profile_id,
                    ctx_preflight_status,
                    ctx_layout_standard,
                    ctx_render_channel_orders,
                    ctx_render_export_warnings,
                ]
            )
