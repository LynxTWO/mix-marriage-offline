from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError:  # pragma: no cover - optional dependency
    colors = None
    letter = None
    getSampleStyleSheet = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _truncate_value(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return f"{value[: max(limit - 12, 0)]}...(truncated)"


def _severity_label(severity: Any) -> str:
    try:
        value = int(severity)
    except (TypeError, ValueError):
        value = 0
    if value >= 80:
        return "error"
    if value >= 60:
        return "warn"
    return "info"


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


def _measurements_table(
    measurements: List[Dict[str, Any]], *, truncate_values: int
) -> Table:
    header = ["evidence_id", "value"]
    rows = [header]
    for measurement in _sorted_measurements(measurements):
        value = measurement.get("value")
        rendered = _truncate_value(_safe_str(value), truncate_values)
        rows.append(
            [
                _safe_str(measurement.get("evidence_id")),
                rendered,
            ]
        )
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _issues_table(issues: List[Dict[str, Any]], *, truncate_values: int) -> Table:
    header = ["issue_id", "severity_label", "message"]
    rows = [header]
    for issue in _sorted_issues(issues):
        rows.append(
            [
                _safe_str(issue.get("issue_id")),
                _severity_label(issue.get("severity")),
                _truncate_value(_safe_str(issue.get("message")), truncate_values),
            ]
        )
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def export_downmix_qa_pdf(
    payload: Dict[str, Any],
    out_path: Path,
    *,
    truncate_values: int = 200,
) -> None:
    if SimpleDocTemplate is None:
        raise RuntimeError("reportlab is required for PDF export")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    downmix_qa = payload.get("downmix_qa", {})
    if not isinstance(downmix_qa, dict):
        downmix_qa = {}

    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Downmix QA", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"src_path: {_safe_str(downmix_qa.get('src_path'))}", styles["Normal"]))
    story.append(Paragraph(f"ref_path: {_safe_str(downmix_qa.get('ref_path'))}", styles["Normal"]))
    story.append(Paragraph(f"policy_id: {_safe_str(downmix_qa.get('policy_id'))}", styles["Normal"]))
    story.append(Paragraph(f"matrix_id: {_safe_str(downmix_qa.get('matrix_id'))}", styles["Normal"]))
    story.append(
        Paragraph(f"sample_rate_hz: {_safe_str(downmix_qa.get('sample_rate_hz'))}", styles["Normal"])
    )
    story.append(Spacer(1, 12))

    measurements = downmix_qa.get("measurements", [])
    if isinstance(measurements, list) and measurements:
        story.append(Paragraph("Measurements", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            _measurements_table(
                [m for m in measurements if isinstance(m, dict)],
                truncate_values=truncate_values,
            )
        )
        story.append(Spacer(1, 12))

    issues = downmix_qa.get("issues", [])
    if isinstance(issues, list) and issues:
        story.append(Paragraph("Issues", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            _issues_table(
                [i for i in issues if isinstance(i, dict)],
                truncate_values=truncate_values,
            )
        )
        story.append(Spacer(1, 12))

    log_value = downmix_qa.get("log")
    if log_value is not None:
        story.append(Paragraph("Log", styles["Heading2"]))
        story.append(Spacer(1, 6))
        raw_log = _safe_str(log_value)
        rendered_log = _truncate_value(raw_log, truncate_values)
        if raw_log and not rendered_log:
            story.append(Paragraph("log omitted (truncate limit <= 0)", styles["Normal"]))
        else:
            story.append(Paragraph(rendered_log, styles["Normal"]))
            if len(raw_log) > truncate_values:
                story.append(
                    Paragraph(
                        f"log truncated to {truncate_values} chars",
                        styles["Normal"],
                    )
                )
        story.append(Spacer(1, 6))

    doc.build(story)
