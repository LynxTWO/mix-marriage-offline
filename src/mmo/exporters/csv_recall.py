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


def export_recall_csv(report: Dict[str, Any], out_path: Path) -> None:
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "recommendation_id",
                "issue_id",
                "action_id",
                "risk",
                "requires_approval",
                "target",
                "params",
                "notes",
            ]
        )
        for rec in _sorted_recommendations(
            rec for rec in recommendations if isinstance(rec, dict)
        ):
            writer.writerow(
                [
                    rec.get("recommendation_id", ""),
                    rec.get("issue_id", ""),
                    rec.get("action_id", ""),
                    rec.get("risk", ""),
                    rec.get("requires_approval", ""),
                    json.dumps(rec.get("target"), sort_keys=True),
                    json.dumps(rec.get("params"), sort_keys=True),
                    rec.get("notes", ""),
                ]
            )
