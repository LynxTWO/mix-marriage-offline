from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _sorted_recommendations(recommendations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
        reason_id = str(result.get("reason_id", ""))
        parts.append(f"{context}:{outcome}({reason_id})")
    return ";".join(parts)


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
        header = [
            "recommendation_id",
            "issue_id",
            "action_id",
            "risk",
            "requires_approval",
            "target",
            "params",
            "notes",
        ]
        if include_gates:
            header.extend(
                [
                    "eligible_auto_apply",
                    "eligible_render",
                    "gate_summary",
                ]
            )
        # Always emit the header row even when there are no recommendations.
        writer.writerow(header)
        for rec in _sorted_recommendations(
            rec for rec in recommendations if isinstance(rec, dict)
        ):
            row = [
                rec.get("recommendation_id", ""),
                rec.get("issue_id", ""),
                rec.get("action_id", ""),
                rec.get("risk", ""),
                rec.get("requires_approval", ""),
                json.dumps(rec.get("target"), sort_keys=True),
                json.dumps(rec.get("params"), sort_keys=True),
                rec.get("notes", ""),
            ]
            if include_gates:
                row.extend(
                    [
                        rec.get("eligible_auto_apply", ""),
                        rec.get("eligible_render", ""),
                        _gate_summary(rec),
                    ]
                )
            writer.writerow(row)
