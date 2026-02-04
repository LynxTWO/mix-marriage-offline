from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

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
    return str(value)


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _truncate_value(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return f"{value[: max(limit - 12, 0)]}...(truncated)"


def _sorted_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        recommendations,
        key=lambda rec: (
            str(rec.get("risk", "")),
            str(rec.get("action_id", "")),
            str(rec.get("recommendation_id", "")),
        ),
    )


def _issues_table(issues: List[Dict[str, Any]]) -> Table:
    header = ["issue_id", "severity", "confidence", "message"]
    rows = [header]
    for issue in sorted(issues, key=lambda item: str(item.get("issue_id", ""))):
        rows.append(
            [
                _safe_str(issue.get("issue_id")),
                _safe_str(issue.get("severity")),
                _safe_str(issue.get("confidence")),
                _safe_str(issue.get("message")),
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


def _downmix_qa_issues_table(
    issues: List[Dict[str, Any]],
    *,
    truncate_values: int,
) -> Table:
    header = ["issue_id", "severity", "confidence", "message"]
    rows = [header]
    for issue in issues:
        rows.append(
            [
                _safe_str(issue.get("issue_id")),
                _safe_str(issue.get("severity")),
                _safe_str(issue.get("confidence")),
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


def _downmix_qa_measurements_table(
    measurements: List[Dict[str, Any]],
    *,
    truncate_values: int,
) -> Table:
    header = ["evidence_id", "value", "unit_id"]
    rows = [header]
    for measurement in measurements:
        rows.append(
            [
                _safe_str(measurement.get("evidence_id")),
                _truncate_value(_safe_str(measurement.get("value")), truncate_values),
                _safe_str(measurement.get("unit_id")),
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


def _recommendations_table(
    recommendations: List[Dict[str, Any]],
    *,
    include_gates: bool,
    truncate_values: int,
) -> Table:
    header = ["recommendation_id", "action_id", "risk", "requires_approval"]
    if include_gates:
        header.extend(["eligible_auto_apply", "eligible_render"])
    header.extend(["target", "notes"])
    rows = [header]
    for rec in _sorted_recommendations(recommendations):
        row = [
            _safe_str(rec.get("recommendation_id")),
            _safe_str(rec.get("action_id")),
            _safe_str(rec.get("risk")),
            _safe_str(rec.get("requires_approval")),
        ]
        if include_gates:
            row.extend(
                [
                    _safe_str(rec.get("eligible_auto_apply")),
                    _safe_str(rec.get("eligible_render")),
                ]
            )
        target = _compact_json(rec.get("target"))
        notes = _safe_str(rec.get("notes"))
        row.extend(
            [
                target,
                _truncate_value(notes, truncate_values * 2),
            ]
        )
        rows.append(row)
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


def _gate_results_table(
    recommendations: List[Dict[str, Any]],
    *,
    truncate_values: int,
) -> Table:
    header = ["recommendation_id", "context", "outcome", "reason_id", "gate_id"]
    rows = [header]
    context_order = {"suggest": 0, "auto_apply": 1, "render": 2}
    for rec in _sorted_recommendations(recommendations):
        gate_results = rec.get("gate_results", [])
        if not isinstance(gate_results, list):
            continue
        for result in sorted(
            [r for r in gate_results if isinstance(r, dict)],
            key=lambda item: (
                context_order.get(str(item.get("context", "")), 99),
                str(item.get("gate_id", "")),
            ),
        ):
            rows.append(
                [
                    _truncate_value(_safe_str(rec.get("recommendation_id")), truncate_values),
                    _truncate_value(_safe_str(result.get("context")), truncate_values),
                    _truncate_value(_safe_str(result.get("outcome")), truncate_values),
                    _truncate_value(_safe_str(result.get("reason_id")), truncate_values),
                    _truncate_value(_safe_str(result.get("gate_id")), truncate_values),
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


def _measurements_table(
    stems: List[Dict[str, Any]],
    *,
    truncate_values: int,
) -> Table:
    header = ["stem_id", "evidence_id", "value", "unit_id"]
    rows = [header]
    for stem in stems:
        stem_id = stem.get("stem_id")
        measurements = stem.get("measurements", [])
        if not isinstance(measurements, list):
            continue
        for measurement in sorted(
            [m for m in measurements if isinstance(m, dict)],
            key=lambda item: str(item.get("evidence_id", "")),
        ):
            rows.append(
                [
                    _safe_str(stem_id),
                    _safe_str(measurement.get("evidence_id")),
                    _truncate_value(_safe_str(measurement.get("value")), truncate_values),
                    _safe_str(measurement.get("unit_id")),
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


def export_report_pdf(
    report: Dict[str, Any],
    out_path: Path,
    *,
    include_measurements: bool = True,
    include_gates: bool = True,
    truncate_values: int = 200,
) -> None:
    if SimpleDocTemplate is None:
        raise RuntimeError("reportlab is required for PDF export")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("MMO Report", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"generated_at: {_safe_str(report.get('generated_at'))}", styles["Normal"]))
    story.append(Paragraph(f"engine_version: {_safe_str(report.get('engine_version'))}", styles["Normal"]))
    story.append(Paragraph(f"ontology_version: {_safe_str(report.get('ontology_version'))}", styles["Normal"]))
    story.append(Spacer(1, 12))

    issues = report.get("issues", [])
    if isinstance(issues, list) and issues:
        story.append(Paragraph("Issues", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(_issues_table([i for i in issues if isinstance(i, dict)]))
        story.append(Spacer(1, 12))

    recommendations = report.get("recommendations", [])
    if isinstance(recommendations, list) and recommendations:
        clean_recommendations = [r for r in recommendations if isinstance(r, dict)]
        story.append(Paragraph("Recommendations", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            _recommendations_table(
                clean_recommendations,
                include_gates=include_gates,
                truncate_values=truncate_values,
            )
        )
        story.append(Spacer(1, 12))

        if include_gates and any(
            isinstance(rec.get("gate_results"), list) and rec.get("gate_results")
            for rec in clean_recommendations
        ):
            story.append(Paragraph("Gate Results", styles["Heading2"]))
            story.append(Spacer(1, 6))
            story.append(
                _gate_results_table(
                    clean_recommendations,
                    truncate_values=truncate_values,
                )
            )
            story.append(Spacer(1, 12))

    session = report.get("session", {})
    stems = []
    if isinstance(session, dict):
        stems = session.get("stems", [])
    if include_measurements and isinstance(stems, list) and stems:
        story.append(Paragraph("Measurements", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            _measurements_table(
                [s for s in stems if isinstance(s, dict)],
                truncate_values=truncate_values,
            )
        )

    downmix_qa = report.get("downmix_qa")
    if isinstance(downmix_qa, dict):
        story.append(Spacer(1, 12))
        story.append(Paragraph("Downmix QA", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                f"src_path: {_truncate_value(_safe_str(downmix_qa.get('src_path')), truncate_values)}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"ref_path: {_truncate_value(_safe_str(downmix_qa.get('ref_path')), truncate_values)}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"policy_id: {_truncate_value(_safe_str(downmix_qa.get('policy_id')), truncate_values)}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"matrix_id: {_truncate_value(_safe_str(downmix_qa.get('matrix_id')), truncate_values)}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"sample_rate_hz: {_truncate_value(_safe_str(downmix_qa.get('sample_rate_hz')), truncate_values)}",
                styles["Normal"],
            )
        )

        measurements = downmix_qa.get("measurements", [])
        if isinstance(measurements, list) and measurements:
            story.append(Spacer(1, 6))
            story.append(Paragraph("Downmix QA Measurements", styles["Heading3"]))
            story.append(Spacer(1, 6))
            story.append(
                _downmix_qa_measurements_table(
                    [m for m in measurements if isinstance(m, dict)],
                    truncate_values=truncate_values,
                )
            )

        issues = downmix_qa.get("issues", [])
        if isinstance(issues, list) and issues:
            story.append(Spacer(1, 6))
            story.append(Paragraph("Downmix QA Issues", styles["Heading3"]))
            story.append(Spacer(1, 6))
            story.append(
                _downmix_qa_issues_table(
                    [i for i in issues if isinstance(i, dict)],
                    truncate_values=truncate_values,
                )
            )

    doc.build(story)
