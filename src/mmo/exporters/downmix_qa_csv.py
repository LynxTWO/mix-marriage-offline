from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, TextIO


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _sorted_measurements(measurements: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        measurements,
        key=lambda item: (
            str(item.get("evidence_id", "")),
            _safe_str(item.get("value")),
        ),
    )


def _sorted_issues(issues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _severity(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    return sorted(
        issues,
        key=lambda item: (
            -_severity(item.get("severity")),
            str(item.get("issue_id", "")),
            str(item.get("message", "")),
        ),
    )


def _write_downmix_qa_csv(payload: Dict[str, Any], handle: TextIO) -> None:
    downmix_qa = payload.get("downmix_qa", {})
    if not isinstance(downmix_qa, dict):
        downmix_qa = {}
    writer = csv.writer(handle)

    writer.writerow(["section", "key", "value"])
    writer.writerow(["summary", "src_path", _safe_str(downmix_qa.get("src_path"))])
    writer.writerow(["summary", "ref_path", _safe_str(downmix_qa.get("ref_path"))])
    writer.writerow(["summary", "policy_id", _safe_str(downmix_qa.get("policy_id"))])
    writer.writerow(["summary", "matrix_id", _safe_str(downmix_qa.get("matrix_id"))])
    writer.writerow(
        ["summary", "sample_rate_hz", _safe_str(downmix_qa.get("sample_rate_hz"))]
    )

    writer.writerow([])
    writer.writerow(["section", "evidence_id", "value", "unit_id"])
    measurements = downmix_qa.get("measurements", [])
    if isinstance(measurements, list):
        for measurement in _sorted_measurements(
            item for item in measurements if isinstance(item, dict)
        ):
            writer.writerow(
                [
                    "measurement",
                    _safe_str(measurement.get("evidence_id")),
                    _safe_str(measurement.get("value")),
                    _safe_str(measurement.get("unit_id")),
                ]
            )

    writer.writerow([])
    writer.writerow(["section", "issue_id", "severity", "confidence", "message"])
    issues = downmix_qa.get("issues", [])
    if isinstance(issues, list):
        for issue in _sorted_issues(item for item in issues if isinstance(item, dict)):
            writer.writerow(
                [
                    "issue",
                    _safe_str(issue.get("issue_id")),
                    _safe_str(issue.get("severity")),
                    _safe_str(issue.get("confidence")),
                    _safe_str(issue.get("message")),
                ]
            )


def render_downmix_qa_csv(payload: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    _write_downmix_qa_csv(payload, buffer)
    return buffer.getvalue()


def export_downmix_qa_csv(payload: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        _write_downmix_qa_csv(payload, handle)
