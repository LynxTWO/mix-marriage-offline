from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


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


def export_recall_sheet(
    report: Dict[str, Any],
    out_path: Path,
) -> None:
    """Write an issue-centric recall sheet CSV to *out_path*.

    Columns: rank, issue_id, severity, confidence, message,
             target_scope, target_id, evidence_summary, action_ids
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
                ]
            )
