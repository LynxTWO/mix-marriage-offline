from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from mmo.core.recommendations import normalize_recommendation_scope


def _sorted_recommendations(recommendations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Keep recall.csv diffable when upstream code hands in recommendations in
    # a different list order.
    return sorted(
        recommendations,
        key=lambda rec: (
            str(rec.get("risk", "")),
            str(rec.get("action_id", "")),
            str(rec.get("recommendation_id", "")),
        ),
    )


def _gate_summary(rec: Dict[str, Any]) -> str:
    gate_results = rec.get("gate_results")
    if not isinstance(gate_results, list) or not gate_results:
        return ""
    # Keep gate contexts in a fixed order so the summary reads the same way in
    # CSV exports, CLI output, and tests.
    context_order = {"suggest": 0, "auto_apply": 1, "render": 2}
    parts = []
    for result in sorted(
        [r for r in gate_results if isinstance(r, dict)],
        key=lambda item: (
            context_order.get(str(item.get("context", "")), 99),
            str(item.get("gate_id", "")),
        ),
    ):
        context = str(result.get("context", ""))
        outcome = str(result.get("outcome", ""))
        gate_id = str(result.get("gate_id", ""))
        reason_id = str(result.get("reason_id", ""))
        parts.append(f"{context}:{outcome}({gate_id}|{reason_id})")
    return ";".join(parts)


def _extreme_gate_ids(rec: Dict[str, Any]) -> str:
    extreme_reasons = rec.get("extreme_reasons")
    if not isinstance(extreme_reasons, list):
        return ""
    # Extreme recommendations can collect several blocking gates. Emit them in
    # sorted order so the same evidence does not churn across runs.
    gate_ids = sorted(
        {
            str(reason.get("gate_id"))
            for reason in extreme_reasons
            if isinstance(reason, dict) and isinstance(reason.get("gate_id"), str)
        }
    )
    return "|".join(gate_ids)


def export_recall_csv(
    report: Dict[str, Any],
    out_path: Path,
    *,
    include_gates: bool = True,
) -> None:
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        profile_id = report.get("profile_id", "")
        header = [
            "recommendation_id",
            "profile_id",
            "issue_id",
            "action_id",
            "risk",
            "requires_approval",
            "scope",
            "params",
            "notes",
            "extreme",
            "extreme_gate_ids",
        ]
        if include_gates:
            header.extend(
                [
                    "eligible_auto_apply",
                    "eligible_render",
                    "gate_summary",
                ]
            )
        # Keep the header stable even when there are no recommendations. Downstream
        # tools use the column shape as part of the artifact contract.
        writer.writerow(header)
        for rec in _sorted_recommendations(
            rec for rec in recommendations if isinstance(rec, dict)
        ):
            row = [
                rec.get("recommendation_id", ""),
                profile_id,
                rec.get("issue_id", ""),
                rec.get("action_id", ""),
                rec.get("risk", ""),
                rec.get("requires_approval", ""),
                json.dumps(normalize_recommendation_scope(rec), sort_keys=True),
                json.dumps(rec.get("params"), sort_keys=True),
                rec.get("notes", ""),
                rec.get("extreme", False),
                _extreme_gate_ids(rec),
            ]
            if include_gates:
                # Gate fields stay at the tail so callers can drop them with
                # one flag without rewriting the rest of the row contract.
                row.extend(
                    [
                        rec.get("eligible_auto_apply", ""),
                        rec.get("eligible_render", ""),
                        _gate_summary(rec),
                    ]
                )
            writer.writerow(row)
