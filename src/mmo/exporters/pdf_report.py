from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from mmo.core.gates import load_gates_policy
from mmo.exporters.pdf_utils import render_maybe_json, truncate_value

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


_EXTREME_CHANGES_NOTE = "Extreme changes present: review before applying"


def _recommendation_extreme_tag(rec: Dict[str, Any]) -> str:
    return "[EXTREME]" if rec.get("extreme") is True else ""


def _format_recommendation_id(rec: Dict[str, Any]) -> str:
    recommendation_id = _safe_str(rec.get("recommendation_id"))
    extreme_tag = _recommendation_extreme_tag(rec)
    if not extreme_tag:
        return recommendation_id
    if not recommendation_id:
        return extreme_tag
    return f"{recommendation_id} {extreme_tag}"


def _extreme_changes_note(recommendations: List[Dict[str, Any]]) -> str | None:
    if any(rec.get("extreme") is True for rec in recommendations):
        return _EXTREME_CHANGES_NOTE
    return None


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _format_threshold(value: float) -> str:
    if float(value).is_integer():
        return f"{value:.1f}"
    if abs(value) < 1:
        return f"{value:.2f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _find_gates_policy_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "ontology" / "policies" / "gates.yaml"
        if candidate.exists():
            return candidate
    return None


def _read_gate_limit(config: Dict[str, Any], key: str) -> float | None:
    value = config.get(key)
    if isinstance(value, dict):
        return _coerce_number(value.get("value"))
    return _coerce_number(value)


def _downmix_qa_delta_thresholds() -> List[tuple[str, float, float]] | None:
    policy_path = _find_gates_policy_path()
    if policy_path is None:
        return None
    try:
        gates = load_gates_policy(policy_path)
    except Exception:
        return None

    gate_map = [
        ("LUFS Δ", "GATE.DOWNMIX_QA_LUFS_DELTA_LIMIT"),
        ("True Peak Δ", "GATE.DOWNMIX_QA_TRUE_PEAK_DELTA_LIMIT"),
        ("Correlation Δ", "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"),
    ]
    thresholds: List[tuple[str, float, float]] = []
    for label, gate_id in gate_map:
        gate = gates.get(gate_id)
        if not isinstance(gate, dict):
            return None
        config = gate.get("config")
        if not isinstance(config, dict):
            return None
        warn_abs_max = _read_gate_limit(config, "warn_abs_max")
        fail_abs_max = _read_gate_limit(config, "fail_abs_max")
        if warn_abs_max is None or fail_abs_max is None:
            return None
        thresholds.append((label, warn_abs_max, fail_abs_max))
    return thresholds


def _downmix_qa_thresholds_line() -> str | None:
    thresholds = _downmix_qa_delta_thresholds()
    if not thresholds:
        return None
    parts = [
        f"{label} warn {_format_threshold(warn)} / fail {_format_threshold(fail)}"
        for label, warn, fail in thresholds
    ]
    return f"Thresholds: {', '.join(parts)}"


def _downmix_qa_provenance_line() -> str:
    return (
        "Provenance: matrix_id resolved via ontology/policies/downmix.yaml and its "
        "referenced policy pack for the selected policy_id and layouts."
    )


def _has_downmix_qa_delta_gate_results(report: Dict[str, Any]) -> bool:
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        return False
    gate_ids = {
        "GATE.DOWNMIX_QA_LUFS_DELTA_LIMIT",
        "GATE.DOWNMIX_QA_TRUE_PEAK_DELTA_LIMIT",
        "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT",
    }
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        gate_results = rec.get("gate_results", [])
        if not isinstance(gate_results, list):
            continue
        for result in gate_results:
            if not isinstance(result, dict):
                continue
            if result.get("gate_id") in gate_ids:
                return True
    return False


def _downmix_qa_next_checks(report: Dict[str, Any]) -> List[str]:
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        return []

    render_blocked_by_qa_delta = False
    qa_delta_gate_ids = {
        "GATE.DOWNMIX_QA_LUFS_DELTA_LIMIT",
        "GATE.DOWNMIX_QA_TRUE_PEAK_DELTA_LIMIT",
        "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT",
    }

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        if rec.get("action_id") != "ACTION.DOWNMIX.RENDER":
            continue
        if rec.get("eligible_render") is not False:
            continue
        gate_results = rec.get("gate_results", [])
        if not isinstance(gate_results, list):
            continue
        for result in gate_results:
            if not isinstance(result, dict):
                continue
            if (
                result.get("context") == "render"
                and result.get("outcome") == "reject"
                and result.get("gate_id") in qa_delta_gate_ids
            ):
                render_blocked_by_qa_delta = True
                break
        if render_blocked_by_qa_delta:
            break

    if not render_blocked_by_qa_delta:
        return []

    recommendation_ids = {
        rec.get("recommendation_id")
        for rec in recommendations
        if isinstance(rec, dict) and isinstance(rec.get("recommendation_id"), str)
    }
    checks: List[str] = []
    ordered_checks = [
        ("REC.DIAGNOSTIC.REVIEW_POLICY_MATRIX.001", "Review downmix policy matrix"),
        ("REC.DIAGNOSTIC.CHECK_REFERENCE_LEVELS.001", "Check reference levels"),
        ("REC.DIAGNOSTIC.CHECK_PHASE_CORRELATION.001", "Check phase correlation"),
    ]
    for recommendation_id, label in ordered_checks:
        if recommendation_id in recommendation_ids:
            checks.append(label)
    return checks


def _compact_json(value: Any) -> str:
    return render_maybe_json(value, 10_000, pretty=False)


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
    header = ["issue_id", "severity", "message"]
    rows = [header]
    for issue in sorted(
        issues,
        key=lambda item: (
            str(item.get("issue_id", "")),
            str(item.get("severity", "")),
            str(item.get("message", "")),
        ),
    ):
        rows.append(
            [
                _safe_str(issue.get("issue_id")),
                _safe_str(issue.get("severity")),
                truncate_value(_safe_str(issue.get("message")), truncate_values),
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
                render_maybe_json(measurement.get("value"), truncate_values),
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
            _format_recommendation_id(rec),
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
                truncate_value(notes, truncate_values * 2),
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
                    truncate_value(_format_recommendation_id(rec), truncate_values),
                    truncate_value(_safe_str(result.get("context")), truncate_values),
                    truncate_value(_safe_str(result.get("outcome")), truncate_values),
                    truncate_value(_safe_str(result.get("reason_id")), truncate_values),
                    truncate_value(_safe_str(result.get("gate_id")), truncate_values),
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
                    render_maybe_json(measurement.get("value"), truncate_values),
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


def _gate_legend_table() -> Table:
    rows = [
        ["outcome", "meaning"],
        ["PASS", "Recommendation is approved for the given context."],
        ["WARN", "Recommendation is eligible but needs attention before apply."],
        ["FAIL", "Recommendation is not eligible for the given context."],
        ["SKIP", "Gate not evaluated for this context."],
    ]
    table = Table(rows, repeatRows=1, colWidths=[60, 400])
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


def _downmix_qa_log_payload(downmix_qa: Dict[str, Any]) -> Dict[str, Any]:
    log_value = downmix_qa.get("log")
    if isinstance(log_value, dict):
        return log_value
    if isinstance(log_value, str):
        try:
            parsed = json.loads(log_value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    measurements = downmix_qa.get("measurements", [])
    if isinstance(measurements, list):
        for measurement in measurements:
            if not isinstance(measurement, dict):
                continue
            if measurement.get("evidence_id") != "EVID.DOWNMIX.QA.LOG":
                continue
            value = measurement.get("value")
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
    return {}


def _downmix_qa_summary_fields(downmix_qa: Dict[str, Any]) -> List[tuple[str, Any]]:
    log_payload = _downmix_qa_log_payload(downmix_qa)
    def _pick(key: str) -> Any:
        if key in downmix_qa and downmix_qa.get(key) is not None:
            return downmix_qa.get(key)
        return log_payload.get(key)

    return [
        ("src_path", _pick("src_path")),
        ("ref_path", _pick("ref_path")),
        ("policy_id", _pick("policy_id")),
        ("matrix_id", _pick("matrix_id")),
        ("source_layout_id", log_payload.get("source_layout_id")),
        ("target_layout_id", log_payload.get("target_layout_id")),
        ("sample_rate_hz", _pick("sample_rate_hz")),
        ("seconds_compared", log_payload.get("seconds_compared")),
        ("max_seconds", log_payload.get("max_seconds")),
    ]


def _downmix_qa_key_measurement_rows(
    measurements: List[Dict[str, Any]],
) -> List[List[str]]:
    measurement_map: Dict[str, Dict[str, Any]] = {}
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        evidence_id = _safe_str(measurement.get("evidence_id"))
        if evidence_id and evidence_id not in measurement_map:
            measurement_map[evidence_id] = measurement

    def _value_for(evidence_id: str) -> tuple[str, str]:
        entry = measurement_map.get(evidence_id, {})
        return _safe_str(entry.get("value")), _safe_str(entry.get("unit_id"))

    rows: List[List[str]] = []
    for label, src_id, ref_id, delta_id in [
        ("LUFS", "EVID.DOWNMIX.QA.LUFS_FOLD", "EVID.DOWNMIX.QA.LUFS_REF", "EVID.DOWNMIX.QA.LUFS_DELTA"),
        (
            "True Peak",
            "EVID.DOWNMIX.QA.TRUE_PEAK_FOLD",
            "EVID.DOWNMIX.QA.TRUE_PEAK_REF",
            "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
        ),
        (
            "Correlation",
            "EVID.DOWNMIX.QA.CORR_FOLD",
            "EVID.DOWNMIX.QA.CORR_REF",
            "EVID.DOWNMIX.QA.CORR_DELTA",
        ),
    ]:
        src_value, src_unit = _value_for(src_id)
        ref_value, ref_unit = _value_for(ref_id)
        delta_value, delta_unit = _value_for(delta_id)
        if not (src_value or ref_value or delta_value):
            continue
        unit = src_unit or ref_unit or delta_unit
        rows.append([label, src_value, ref_value, delta_value, unit])
    return rows


def _downmix_qa_summary_table(rows: List[List[str]]) -> Table:
    table_rows = [["metric", "src", "ref", "delta", "unit"], *rows]
    table = Table(table_rows, repeatRows=1)
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


def _mix_complexity_top_pairs(
    mix_complexity: Dict[str, Any], *, limit: int = 3
) -> List[Dict[str, Any]]:
    top_pairs = mix_complexity.get("top_masking_pairs")
    if not isinstance(top_pairs, list):
        return []
    rows = [pair for pair in top_pairs if isinstance(pair, dict)]
    rows.sort(
        key=lambda pair: (
            -(_coerce_number(pair.get("score")) or 0.0),
            _safe_str(pair.get("stem_a")),
            _safe_str(pair.get("stem_b")),
        )
    )
    return rows[: max(0, int(limit))]


def _vibe_signals_lines(vibe_signals: Dict[str, Any]) -> List[str]:
    density_level = _safe_str(vibe_signals.get("density_level"))
    masking_level = _safe_str(vibe_signals.get("masking_level"))
    translation_risk = _safe_str(vibe_signals.get("translation_risk"))
    lines = [
        "Density: "
        f"{density_level} | Masking: {masking_level} | Translation risk: {translation_risk}"
    ]
    notes = vibe_signals.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if isinstance(note, str) and note:
                lines.append(f"- {note}")
    return lines


def _compare_table(rows: List[List[str]]) -> Table:
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


def _compare_list_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    items = [_safe_str(item).strip() for item in value]
    normalized = [item for item in items if item]
    if not normalized:
        return "<none>"
    return ",".join(normalized)


def _compare_overview_table(
    compare_report: Dict[str, Any],
    *,
    truncate_values: int,
) -> Table:
    diffs = compare_report.get("diffs", {})
    if not isinstance(diffs, dict):
        diffs = {}
    profile_id = diffs.get("profile_id", {})
    preset_id = diffs.get("preset_id", {})
    meters = diffs.get("meters", {})
    output_formats = diffs.get("output_formats", {})

    rows = [
        ["field", "A", "B"],
        [
            "profile_id",
            truncate_value(_safe_str(profile_id.get("a")), truncate_values),
            truncate_value(_safe_str(profile_id.get("b")), truncate_values),
        ],
        [
            "preset_id",
            truncate_value(_safe_str(preset_id.get("a")), truncate_values),
            truncate_value(_safe_str(preset_id.get("b")), truncate_values),
        ],
        [
            "meters",
            truncate_value(_safe_str(meters.get("a")), truncate_values),
            truncate_value(_safe_str(meters.get("b")), truncate_values),
        ],
        [
            "output_formats",
            truncate_value(_compare_list_text(output_formats.get("a")), truncate_values),
            truncate_value(_compare_list_text(output_formats.get("b")), truncate_values),
        ],
    ]
    return _compare_table(rows)


def export_compare_report_pdf(
    compare_report: Dict[str, Any],
    out_path: Path,
    *,
    truncate_values: int = 200,
) -> None:
    if SimpleDocTemplate is None:
        raise RuntimeError("reportlab is required for PDF export")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(out_path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    side_a = compare_report.get("a", {})
    if not isinstance(side_a, dict):
        side_a = {}
    side_b = compare_report.get("b", {})
    if not isinstance(side_b, dict):
        side_b = {}

    story.append(Paragraph("MMO Compare Report", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "A: "
            f"{truncate_value(_safe_str(side_a.get('label')), truncate_values)}"
            " | report_path: "
            f"{truncate_value(_safe_str(side_a.get('report_path')), truncate_values)}",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            "B: "
            f"{truncate_value(_safe_str(side_b.get('label')), truncate_values)}"
            " | report_path: "
            f"{truncate_value(_safe_str(side_b.get('report_path')), truncate_values)}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph("High-Level Diffs", styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(
        _compare_overview_table(
            compare_report,
            truncate_values=truncate_values,
        )
    )
    story.append(Spacer(1, 12))

    diffs = compare_report.get("diffs", {})
    metrics = {}
    if isinstance(diffs, dict):
        metrics = diffs.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    downmix_qa = metrics.get("downmix_qa")
    if isinstance(downmix_qa, dict):
        rows = [["metric", "A", "B", "delta"]]
        for key, label in (
            ("lufs_delta", "LUFS delta"),
            ("true_peak_delta", "True peak delta"),
            ("corr_delta", "Correlation delta"),
        ):
            value = downmix_qa.get(key, {})
            if not isinstance(value, dict):
                value = {}
            rows.append(
                [
                    label,
                    _safe_str(value.get("a")),
                    _safe_str(value.get("b")),
                    _safe_str(value.get("delta")),
                ]
            )
        story.append(Paragraph("Downmix QA Metrics", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(_compare_table(rows))
        story.append(Spacer(1, 12))

    mix_complexity = metrics.get("mix_complexity")
    if isinstance(mix_complexity, dict):
        rows = [["metric", "A", "B", "delta"]]
        for key, label in (
            ("density_mean", "Density mean"),
            ("density_peak", "Density peak"),
            ("masking_pairs_count", "Masking pairs count"),
        ):
            value = mix_complexity.get(key, {})
            if not isinstance(value, dict):
                value = {}
            rows.append(
                [
                    label,
                    _safe_str(value.get("a")),
                    _safe_str(value.get("b")),
                    _safe_str(value.get("delta")),
                ]
            )
        story.append(Paragraph("Mix Complexity Metrics", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(_compare_table(rows))
        story.append(Spacer(1, 12))

    change_flags = metrics.get("change_flags", {})
    if isinstance(change_flags, dict):
        extreme_count = change_flags.get("extreme_count", {})
        if not isinstance(extreme_count, dict):
            extreme_count = {}
        translation_risk = change_flags.get("translation_risk", {})
        if not isinstance(translation_risk, dict):
            translation_risk = {}
        rows = [
            ["flag", "A", "B", "delta_or_shift"],
            [
                "extreme_count",
                _safe_str(extreme_count.get("a")),
                _safe_str(extreme_count.get("b")),
                _safe_str(extreme_count.get("delta")),
            ],
            [
                "translation_risk",
                _safe_str(translation_risk.get("a")),
                _safe_str(translation_risk.get("b")),
                _safe_str(translation_risk.get("shift")),
            ],
        ]
        story.append(Paragraph("Change Flags", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(_compare_table(rows))
        story.append(Spacer(1, 12))

    notes = compare_report.get("notes", [])
    if isinstance(notes, list) and notes:
        story.append(Paragraph("Notes", styles["Heading2"]))
        story.append(Spacer(1, 6))
        for note in notes:
            if isinstance(note, str) and note:
                story.append(
                    Paragraph(
                        f"- {truncate_value(note, truncate_values)}",
                        styles["Normal"],
                    )
                )
        story.append(Spacer(1, 12))

    warnings = compare_report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        story.append(Paragraph("Warnings", styles["Heading2"]))
        story.append(Spacer(1, 6))
        for warning in warnings:
            if isinstance(warning, str) and warning:
                story.append(
                    Paragraph(
                        f"- {truncate_value(warning, truncate_values)}",
                        styles["Normal"],
                    )
                )

    doc.build(story)


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
    profile_id = _safe_str(report.get("profile_id"))
    if profile_id:
        story.append(Paragraph(f"Authority profile: {profile_id}", styles["Normal"]))
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
        extreme_note = _extreme_changes_note(clean_recommendations)
        if extreme_note:
            story.append(Paragraph(extreme_note, styles["Normal"]))
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
            story.append(_gate_legend_table())
            story.append(Spacer(1, 6))
            story.append(
                Paragraph(
                    "Note: suggest-only diagnostic actions are never auto-applied.",
                    styles["Normal"],
                )
            )
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

    mix_complexity = report.get("mix_complexity")
    if isinstance(mix_complexity, dict):
        density_mean = _safe_str(mix_complexity.get("density_mean"))
        density_peak = _safe_str(mix_complexity.get("density_peak"))
        top_pairs = _mix_complexity_top_pairs(mix_complexity, limit=3)

        story.append(Spacer(1, 12))
        story.append(Paragraph("Mix Complexity", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                f"Density mean: {density_mean} | Density peak: {density_peak}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 6))
        story.append(Paragraph("Top masking risk pairs", styles["Heading3"]))
        if top_pairs:
            for pair in top_pairs:
                stem_a = _safe_str(pair.get("stem_a"))
                stem_b = _safe_str(pair.get("stem_b"))
                score = _safe_str(pair.get("score"))
                start_s = _safe_str(pair.get("start_s"))
                end_s = _safe_str(pair.get("end_s"))
                story.append(
                    Paragraph(
                        f"- {stem_a} / {stem_b} | score={score} | {start_s}s to {end_s}s",
                        styles["Normal"],
                    )
                )
        else:
            story.append(Paragraph("- No masking-risk pairs detected.", styles["Normal"]))

    vibe_signals = report.get("vibe_signals")
    if isinstance(vibe_signals, dict):
        story.append(Spacer(1, 12))
        story.append(Paragraph("Vibe Signals", styles["Heading2"]))
        story.append(Spacer(1, 6))
        for line in _vibe_signals_lines(vibe_signals):
            story.append(Paragraph(line, styles["Normal"]))

    downmix_qa = report.get("downmix_qa")
    has_downmix_qa = isinstance(downmix_qa, dict)
    has_downmix_qa_gates = _has_downmix_qa_delta_gate_results(report)
    if has_downmix_qa or has_downmix_qa_gates:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Downmix QA", styles["Heading2"]))
        story.append(Spacer(1, 6))
        if has_downmix_qa:
            for label, value in _downmix_qa_summary_fields(downmix_qa):
                story.append(
                    Paragraph(
                        f"{label}: {truncate_value(_safe_str(value), truncate_values)}",
                        styles["Normal"],
                    )
                )
        thresholds_line = _downmix_qa_thresholds_line()
        if thresholds_line:
            story.append(Paragraph(thresholds_line, styles["Normal"]))
        story.append(Paragraph(_downmix_qa_provenance_line(), styles["Normal"]))
        next_checks = _downmix_qa_next_checks(report)
        if next_checks:
            story.append(Spacer(1, 6))
            story.append(Paragraph("Next checks", styles["Heading3"]))
            story.append(Spacer(1, 4))
            for check in next_checks:
                story.append(Paragraph(f"- {check}", styles["Normal"]))

        if has_downmix_qa:
            measurements = downmix_qa.get("measurements", [])
            if isinstance(measurements, list) and measurements:
                summary_rows = _downmix_qa_key_measurement_rows(measurements)
                if summary_rows:
                    story.append(Spacer(1, 6))
                    story.append(Paragraph("Downmix QA Summary", styles["Heading3"]))
                    story.append(Spacer(1, 6))
                    story.append(_downmix_qa_summary_table(summary_rows))
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
                    Paragraph(f"issues_count: {len([i for i in issues if isinstance(i, dict)])}", styles["Normal"])
                )
                story.append(Spacer(1, 4))
                story.append(
                    _downmix_qa_issues_table(
                        [i for i in issues if isinstance(i, dict)],
                        truncate_values=truncate_values,
                    )
                )

    doc.build(story)
