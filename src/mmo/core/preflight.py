"""Render preflight: safety gate policy engine (DoD 4.4.3 + 4.6).

``evaluate_preflight`` runs all render-safety gates against session/scene
metadata *before* any audio is decoded or written.  It produces a deterministic
``preflight_receipt`` dict that conforms to
``schemas/preflight_receipt.schema.json``.

Gates evaluated (in order):
  1. ``GATE.LAYOUT_NEGOTIATION`` — downmix path exists?
  2. ``GATE.DOWNMIX_SIMILARITY``  — matrix-based LFE / loudness risk
  3. ``GATE.DOWNMIX_SIMILARITY_MEASURED`` — measured similarity from rendered audio
  4. ``GATE.LRA_BOUNDS``          — loudness range (if objective meters provided)
  5. ``GATE.TRUE_PEAK_PER_CHANNEL`` — per-channel true peak (if objective meters provided)
  6. ``GATE.TRANSLATION_CURVES``  — translation-curve deltas (if objective meters provided)
  7. ``GATE.CORRELATION_RISK``    — scene correlation metadata
  8. ``GATE.PHASE_RISK``          — polarity / phase-inversion flags
  9. ``GATE.CONFIDENCE_LOW``      — scene inference confidence

Public API
----------
- ``evaluate_preflight(session, scene, target_layout, options)``
- ``preflight_receipt_blocks(receipt)``
- ``PREFLIGHT_RECEIPT_SCHEMA_VERSION``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.core.downmix import (
    layout_negotiation_available,
    measure_downmix_similarity,
    predict_fold_similarity,
    resolve_preflight_matrix,
)
from mmo.core.meters import assess_translation_curves

PREFLIGHT_RECEIPT_SCHEMA_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Layout ID normalisation
# ---------------------------------------------------------------------------

_LAYOUT_SHORTHANDS: Dict[str, str] = {
    "stereo": "LAYOUT.2_0",
    "2.0": "LAYOUT.2_0",
    "2_0": "LAYOUT.2_0",
    "5.1": "LAYOUT.5_1",
    "5_1": "LAYOUT.5_1",
    "7.1": "LAYOUT.7_1",
    "7_1": "LAYOUT.7_1",
    "mono": "LAYOUT.1_0",
    "1.0": "LAYOUT.1_0",
    "2.1": "LAYOUT.2_1",
    "4.0": "LAYOUT.4_0",
    "4.1": "LAYOUT.4_1",
    "7.1.4": "LAYOUT.7_1_4",
    "binaural": "LAYOUT.BINAURAL",
}


def _normalise_layout_id(raw: str) -> str:
    """Normalise a shorthand or LAYOUT.* ID to canonical form."""
    stripped = raw.strip()
    if stripped.startswith("LAYOUT."):
        return stripped
    lower = stripped.lower()
    return _LAYOUT_SHORTHANDS.get(lower, stripped)


# ---------------------------------------------------------------------------
# Source layout extraction from scene / session
# ---------------------------------------------------------------------------

def _extract_source_layout(
    session: Dict[str, Any],
    scene: Dict[str, Any],
) -> Optional[str]:
    """Best-effort extraction of source_layout_id from session or scene."""
    # 1. Direct key in session
    v = session.get("source_layout_id")
    if isinstance(v, str) and v.strip():
        return v.strip()

    # 2. run_config in scene (analysis report pattern)
    run_config = scene.get("run_config")
    if isinstance(run_config, dict):
        v = run_config.get("source_layout_id")
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 3. Direct key in scene
    v = scene.get("source_layout_id")
    if isinstance(v, str) and v.strip():
        return v.strip()

    # 4. stems / items in scene (report has a "stems" or "items" list)
    for key in ("stems", "items", "objects", "beds"):
        entries = scene.get(key)
        if isinstance(entries, list) and entries:
            first = entries[0] if isinstance(entries[0], dict) else {}
            v = first.get("layout_id") or first.get("source_layout_id")
            if isinstance(v, str) and v.strip():
                return v.strip()

    return None


# ---------------------------------------------------------------------------
# Confidence extraction
# ---------------------------------------------------------------------------

def _extract_confidence_summary(
    scene: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute overall_confidence from scene metadata and per-recommendation scores."""
    warn_below: float = float(options.get("confidence_warn_below", 0.5))
    error_below: float = float(options.get("confidence_error_below", 0.2))

    scores: List[float] = []
    low_confidence_stems: List[str] = []

    # Extract confidence from report recommendations
    recommendations = scene.get("recommendations")
    if isinstance(recommendations, list):
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            conf = rec.get("confidence")
            if isinstance(conf, (int, float)):
                scores.append(float(conf))
                if float(conf) < warn_below:
                    rec_id = rec.get("recommendation_id") or rec.get("action_id") or ""
                    if isinstance(rec_id, str) and rec_id:
                        low_confidence_stems.append(rec_id)

    # Extract confidence from scene objects (scene.schema.json pattern)
    for container_key in ("objects", "beds"):
        container = scene.get(container_key)
        if not isinstance(container, list):
            continue
        for obj in container:
            if not isinstance(obj, dict):
                continue
            intent = obj.get("intent")
            if isinstance(intent, dict):
                conf = intent.get("confidence")
                if isinstance(conf, (int, float)):
                    scores.append(float(conf))
                    if float(conf) < warn_below:
                        obj_id = obj.get("object_id") or obj.get("stem_id") or ""
                        if isinstance(obj_id, str) and obj_id:
                            low_confidence_stems.append(obj_id)

    # Direct metadata confidence override
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        conf = metadata.get("confidence")
        if isinstance(conf, (int, float)):
            scores = [float(conf)]  # use direct metadata confidence as sole value

    # Compute overall
    if not scores:
        overall = 1.0  # assume full confidence when no data
    else:
        overall = sum(scores) / len(scores)

    overall = max(0.0, min(1.0, overall))

    if overall < error_below:
        level = "very_low"
    elif overall < warn_below:
        level = "low"
    elif overall < 0.75:
        level = "medium"
    else:
        level = "high"

    # Stable ordering
    low_confidence_stems = sorted(set(low_confidence_stems))

    return {
        "overall_confidence": round(overall, 6),
        "confidence_level": level,
        "stem_count": len(scores),
        "low_confidence_stems": low_confidence_stems,
    }


# ---------------------------------------------------------------------------
# Phase / correlation risk extraction
# ---------------------------------------------------------------------------

def _extract_phase_report(
    scene: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Assess phase and correlation risk from scene metadata."""
    corr_warn: float = float(options.get("correlation_warn_lte", -0.2))
    corr_error: float = float(options.get("correlation_error_lte", -0.6))
    polarity_warn: float = float(options.get("polarity_warn_lte", -0.2))
    polarity_error: float = float(options.get("polarity_error_lte", -0.6))

    correlation_value: Optional[float] = None
    polarity_inverted = False
    details: Dict[str, Any] = {}

    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        corr = metadata.get("correlation")
        if isinstance(corr, (int, float)):
            correlation_value = float(corr)
            details["scene_correlation"] = correlation_value
        if metadata.get("polarity_inverted"):
            polarity_inverted = True
            details["polarity_inverted"] = True

    # Check render_qa issues from a prior analysis pass (if embedded in scene/report)
    qa_issues = scene.get("qa_issues")
    if isinstance(qa_issues, list):
        for issue in qa_issues:
            if not isinstance(issue, dict):
                continue
            issue_id = str(issue.get("issue_id") or "")
            if "POLARITY" in issue_id or "PHASE" in issue_id:
                polarity_inverted = True
                details["qa_polarity_issue"] = issue_id
            if "CORRELATION" in issue_id:
                corr_val = issue.get("value")
                if isinstance(corr_val, (int, float)):
                    correlation_value = float(corr_val)
                    details["qa_correlation_issue"] = issue_id

    # Assess correlation risk
    if correlation_value is not None:
        if correlation_value <= corr_error:
            correlation_risk = "high"
        elif correlation_value <= corr_warn:
            correlation_risk = "medium"
        else:
            correlation_risk = "none"
    else:
        correlation_risk = "none"

    # Assess polarity risk
    if polarity_inverted:
        polarity_risk = "high"
    elif correlation_value is not None and correlation_value <= polarity_error:
        polarity_risk = "high"
    elif correlation_value is not None and correlation_value <= polarity_warn:
        polarity_risk = "medium"
    else:
        polarity_risk = "none"

    return {
        "correlation_risk": correlation_risk,
        "polarity_risk": polarity_risk,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Objective meter extraction
# ---------------------------------------------------------------------------

def _extract_objective_meters(scene: Dict[str, Any]) -> Dict[str, Any]:
    objective = scene.get("objective_meters")
    if isinstance(objective, dict):
        return dict(objective)
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        objective = metadata.get("objective_meters")
        if isinstance(objective, dict):
            return dict(objective)
    return {}


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------

def _gate_result(
    gate_id: str,
    outcome: str,
    severity: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "gate_id": gate_id,
        "outcome": outcome,
        "severity": severity,
        "message": message,
    }
    if details:
        result["details"] = details
    return result


def _eval_layout_negotiation(
    source_layout_id: Optional[str],
    target_layout_id: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.LAYOUT_NEGOTIATION"
    warn_on_composed = bool(options.get("warn_on_composed_path", True))

    if not source_layout_id:
        return _gate_result(
            gate_id,
            "skipped",
            "info",
            "Source layout unknown; layout negotiation skipped.",
            {"reason": "source_layout_id_unavailable"},
        )

    negotiation = layout_negotiation_available(
        source_layout_id,
        target_layout_id,
        warn_on_composed_path=warn_on_composed,
    )

    if not negotiation["available"]:
        return _gate_result(
            gate_id,
            "block",
            "error",
            (
                f"No downmix path found from {source_layout_id} to "
                f"{target_layout_id}: {negotiation['error']}"
            ),
            {
                "source_layout_id": source_layout_id,
                "target_layout_id": target_layout_id,
                "error": negotiation["error"],
            },
        )

    if negotiation.get("warning"):
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            negotiation["warning"],
            {
                "source_layout_id": source_layout_id,
                "target_layout_id": target_layout_id,
                "matrix_id": negotiation.get("matrix_id"),
                "composed": True,
            },
        )

    return _gate_result(
        gate_id,
        "pass",
        "info",
        f"Downmix path found: {source_layout_id} → {target_layout_id}.",
        {
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "matrix_id": negotiation.get("matrix_id"),
            "composed": negotiation.get("composed", False),
        },
    )


def _eval_downmix_similarity(
    source_layout_id: Optional[str],
    target_layout_id: str,
    options: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Evaluate GATE.DOWNMIX_SIMILARITY.

    Returns ``(gate_result, downmix_check | None)``.
    """
    gate_id = "GATE.DOWNMIX_SIMILARITY"

    lfe_boost_warn_db: float = float(options.get("lfe_boost_warn_db", 3.0))
    lfe_boost_error_db: float = float(options.get("lfe_boost_error_db", 6.0))
    lufs_warn: float = float(options.get("predicted_lufs_delta_warn_abs", 2.0))
    lufs_error: float = float(options.get("predicted_lufs_delta_error_abs", 4.0))

    if not source_layout_id:
        gate = _gate_result(
            gate_id,
            "skipped",
            "info",
            "Source layout unknown; downmix similarity check skipped.",
            {"reason": "source_layout_id_unavailable"},
        )
        return gate, None

    try:
        matrix = resolve_preflight_matrix(source_layout_id, target_layout_id)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        gate = _gate_result(
            gate_id,
            "skipped",
            "info",
            f"Matrix unavailable for similarity check: {exc}",
            {"reason": "matrix_unavailable"},
        )
        return gate, None

    prediction = predict_fold_similarity(
        matrix,
        lfe_boost_warn_db=lfe_boost_warn_db,
        lfe_boost_error_db=lfe_boost_error_db,
        predicted_lufs_delta_warn_abs=lufs_warn,
        predicted_lufs_delta_error_abs=lufs_error,
    )

    risk_level = prediction["risk_level"]
    matrix_id: str = str(matrix.get("matrix_id") or "unknown")

    downmix_check: Dict[str, Any] = {
        "matrix_id": matrix_id,
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "risk_level": risk_level,
        "lfe_folded": prediction["lfe_folded"],
        "lfe_boost_db": prediction["lfe_boost_db"],
        "predicted_lufs_delta": prediction["predicted_lufs_delta"],
        "notes": list(prediction["notes"]),
    }

    if risk_level == "high":
        gate = _gate_result(
            gate_id,
            "block",
            "error",
            f"High fold-similarity risk: {'; '.join(prediction['notes'])}",
            {
                "risk_level": risk_level,
                "lfe_folded": prediction["lfe_folded"],
                "lfe_boost_db": prediction["lfe_boost_db"],
                "predicted_lufs_delta": prediction["predicted_lufs_delta"],
            },
        )
    elif risk_level == "medium":
        gate = _gate_result(
            gate_id,
            "warn",
            "warn",
            f"Medium fold-similarity risk: {'; '.join(prediction['notes'])}",
            {
                "risk_level": risk_level,
                "lfe_folded": prediction["lfe_folded"],
                "lfe_boost_db": prediction["lfe_boost_db"],
                "predicted_lufs_delta": prediction["predicted_lufs_delta"],
            },
        )
    else:
        gate = _gate_result(
            gate_id,
            "pass",
            "info",
            f"Downmix similarity risk: {risk_level}.",
            {"risk_level": risk_level},
        )

    return gate, downmix_check


def _eval_correlation_risk(
    phase_report: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.CORRELATION_RISK"
    corr_risk = phase_report.get("correlation_risk", "none")

    if corr_risk == "high":
        return _gate_result(
            gate_id,
            "block",
            "error",
            "Strong negative correlation detected; render likely to produce phase-cancelled output.",
            {"correlation_risk": corr_risk, "details": phase_report.get("details", {})},
        )
    if corr_risk in ("medium", "low"):
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            "Borderline negative correlation; review stereo width and polarity before render.",
            {"correlation_risk": corr_risk, "details": phase_report.get("details", {})},
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        "Correlation risk: none.",
        {"correlation_risk": corr_risk},
    )


def _eval_phase_risk(
    phase_report: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.PHASE_RISK"
    polarity_risk = phase_report.get("polarity_risk", "none")

    if polarity_risk == "high":
        return _gate_result(
            gate_id,
            "block",
            "error",
            "Phase / polarity inversion risk is high; render may produce severe cancellation.",
            {"polarity_risk": polarity_risk, "details": phase_report.get("details", {})},
        )
    if polarity_risk in ("medium", "low"):
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            "Phase risk is elevated; verify polarity before render.",
            {"polarity_risk": polarity_risk, "details": phase_report.get("details", {})},
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        "Phase / polarity risk: none.",
        {"polarity_risk": polarity_risk},
    )


def _eval_confidence_low(
    confidence_summary: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.CONFIDENCE_LOW"
    level = confidence_summary.get("confidence_level", "high")
    overall = confidence_summary.get("overall_confidence", 1.0)

    if level == "very_low":
        return _gate_result(
            gate_id,
            "block",
            "error",
            (
                f"Scene confidence is very low ({overall:.2f}); automated render "
                "unsafe — manual review required."
            ),
            {
                "overall_confidence": overall,
                "confidence_level": level,
                "stem_count": confidence_summary.get("stem_count", 0),
                "low_confidence_stems": confidence_summary.get("low_confidence_stems", []),
            },
        )
    if level == "low":
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            (
                f"Scene confidence is low ({overall:.2f}); review recommendations "
                "before render."
            ),
            {
                "overall_confidence": overall,
                "confidence_level": level,
                "stem_count": confidence_summary.get("stem_count", 0),
                "low_confidence_stems": confidence_summary.get("low_confidence_stems", []),
            },
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        f"Scene confidence: {level} ({overall:.2f}).",
        {"overall_confidence": overall, "confidence_level": level},
    )


def _eval_downmix_similarity_measured(
    rendered_file: Path,
    target_layout_id: str,
    options: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Evaluate GATE.DOWNMIX_SIMILARITY_MEASURED from a rendered audio file.

    Returns ``(gate_result, measured_check | None)``.
    """
    gate_id = "GATE.DOWNMIX_SIMILARITY_MEASURED"

    true_peak_warn: float = float(options.get("true_peak_warn_dbtp", -3.0))
    true_peak_error: float = float(options.get("true_peak_error_dbtp", -1.0))
    lufs_delta_warn: float = float(options.get("lufs_delta_warn_abs", 3.0))
    lufs_delta_error: float = float(options.get("lufs_delta_error_abs", 6.0))
    corr_warn: float = float(options.get("correlation_warn_lte", -0.2))
    corr_error: float = float(options.get("correlation_error_lte", -0.6))
    reference_lufs: Optional[float] = (
        float(options["reference_lufs"])
        if options.get("reference_lufs") is not None
        else None
    )

    try:
        check = measure_downmix_similarity(
            rendered_file,
            target_layout_id,
            true_peak_warn_dbtp=true_peak_warn,
            true_peak_error_dbtp=true_peak_error,
            lufs_delta_warn_abs=lufs_delta_warn,
            lufs_delta_error_abs=lufs_delta_error,
            correlation_warn_lte=corr_warn,
            correlation_error_lte=corr_error,
            reference_lufs=reference_lufs,
        )
    except (ValueError, OSError) as exc:
        gate = _gate_result(
            gate_id,
            "skipped",
            "info",
            f"Measured similarity check skipped: {exc}",
            {"reason": "measurement_failed"},
        )
        return gate, None

    risk_level = check["risk_level"]
    notes: List[str] = list(check.get("notes") or [])
    detail_summary: Dict[str, Any] = {
        "risk_level": risk_level,
        "true_peak_dbtp": check.get("true_peak_dbtp"),
        "stereo_correlation": check.get("stereo_correlation"),
    }

    if risk_level == "high":
        gate = _gate_result(
            gate_id,
            "block",
            "error",
            (
                f"High measured similarity risk: {'; '.join(notes)}"
                if notes
                else "High measured similarity risk."
            ),
            detail_summary,
        )
    elif risk_level == "medium":
        gate = _gate_result(
            gate_id,
            "warn",
            "warn",
            (
                f"Medium measured similarity risk: {'; '.join(notes)}"
                if notes
                else "Medium measured similarity risk."
            ),
            detail_summary,
        )
    else:
        gate = _gate_result(
            gate_id,
            "pass",
            "info",
            f"Measured similarity risk: {risk_level}.",
            {"risk_level": risk_level},
        )

    return gate, check


def _eval_lra_bounds(
    objective_meters: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.LRA_BOUNDS"
    lra_raw = objective_meters.get("loudness_range_lu")
    if not isinstance(lra_raw, (int, float)):
        return _gate_result(
            gate_id,
            "skipped",
            "info",
            "LRA objective meter unavailable; LRA gate skipped.",
            {"reason": "loudness_range_lu_unavailable"},
        )
    lra_lu = float(lra_raw)
    warn_low = float(options.get("lra_warn_lu_lte", 1.5))
    warn_high = float(options.get("lra_warn_lu_gte", 18.0))
    error_high = float(options.get("lra_error_lu_gte", 24.0))

    if lra_lu >= error_high:
        return _gate_result(
            gate_id,
            "block",
            "error",
            f"LRA {lra_lu:.2f} LU exceeds error threshold ({error_high:.2f} LU).",
            {
                "loudness_range_lu": round(lra_lu, 6),
                "warn_low_lu": warn_low,
                "warn_high_lu": warn_high,
                "error_high_lu": error_high,
            },
        )
    if lra_lu <= warn_low or lra_lu >= warn_high:
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            (
                f"LRA {lra_lu:.2f} LU is outside recommended range "
                f"[{warn_low:.2f}, {warn_high:.2f}] LU."
            ),
            {
                "loudness_range_lu": round(lra_lu, 6),
                "warn_low_lu": warn_low,
                "warn_high_lu": warn_high,
            },
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        f"LRA within bounds: {lra_lu:.2f} LU.",
        {"loudness_range_lu": round(lra_lu, 6)},
    )


def _eval_true_peak_per_channel(
    objective_meters: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.TRUE_PEAK_PER_CHANNEL"
    raw = objective_meters.get("true_peak_per_channel_dbtp")
    if not isinstance(raw, dict):
        return _gate_result(
            gate_id,
            "skipped",
            "info",
            "Per-channel true-peak data unavailable; true-peak gate skipped.",
            {"reason": "true_peak_per_channel_unavailable"},
        )

    per_channel: Dict[str, float] = {}
    for key in sorted(raw.keys()):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            per_channel[str(key)] = float(value)

    if not per_channel:
        return _gate_result(
            gate_id,
            "skipped",
            "info",
            "Per-channel true-peak data unavailable; true-peak gate skipped.",
            {"reason": "true_peak_per_channel_unavailable"},
        )

    warn_dbtp = float(options.get("true_peak_channel_warn_dbtp", -2.0))
    error_dbtp = float(options.get("true_peak_channel_error_dbtp", -1.0))
    hottest_channel, hottest_value = max(
        per_channel.items(),
        key=lambda item: (item[1], item[0]),
    )
    rounded = {
        key: round(value, 6)
        for key, value in sorted(per_channel.items(), key=lambda item: item[0])
    }

    if hottest_value > error_dbtp:
        return _gate_result(
            gate_id,
            "block",
            "error",
            (
                f"Channel {hottest_channel} true-peak {hottest_value:+.2f} dBTP "
                f"exceeds error threshold ({error_dbtp:+.2f} dBTP)."
            ),
            {
                "hottest_channel": hottest_channel,
                "hottest_value_dbtp": round(hottest_value, 6),
                "warn_dbtp": warn_dbtp,
                "error_dbtp": error_dbtp,
                "per_channel_dbtp": rounded,
            },
        )
    if hottest_value > warn_dbtp:
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            (
                f"Channel {hottest_channel} true-peak {hottest_value:+.2f} dBTP "
                f"exceeds warning threshold ({warn_dbtp:+.2f} dBTP)."
            ),
            {
                "hottest_channel": hottest_channel,
                "hottest_value_dbtp": round(hottest_value, 6),
                "warn_dbtp": warn_dbtp,
                "per_channel_dbtp": rounded,
            },
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        f"Per-channel true-peak within bounds (max {hottest_value:+.2f} dBTP).",
        {
            "hottest_channel": hottest_channel,
            "hottest_value_dbtp": round(hottest_value, 6),
            "per_channel_dbtp": rounded,
        },
    )


def _eval_translation_curves(
    objective_meters: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    gate_id = "GATE.TRANSLATION_CURVES"
    warn_delta_db = float(options.get("translation_curve_warn_db", 2.5))
    error_delta_db = float(options.get("translation_curve_error_db", 4.0))

    raw_deltas = objective_meters.get("translation_curve_deltas_db")
    if isinstance(raw_deltas, dict):
        profiles: list[dict[str, Any]] = []
        max_delta: float | None = None
        for profile_id in sorted(raw_deltas.keys()):
            value = raw_deltas.get(profile_id)
            if not isinstance(value, (int, float)):
                continue
            delta_db = float(value)
            if max_delta is None or delta_db > max_delta:
                max_delta = delta_db
            if delta_db > error_delta_db:
                status = "high"
            elif delta_db > warn_delta_db:
                status = "medium"
            else:
                status = "low"
            profiles.append(
                {
                    "profile_id": str(profile_id),
                    "delta_db": round(delta_db, 6),
                    "status": status,
                }
            )
        curves_summary: Dict[str, Any] = {
            "profiles": profiles,
            "max_delta_db": None if max_delta is None else round(max_delta, 6),
        }
    else:
        measured_curve = objective_meters.get("translation_curve_levels_db")
        if not isinstance(measured_curve, dict):
            return _gate_result(
                gate_id,
                "skipped",
                "info",
                "Translation-curve objective data unavailable; translation gate skipped.",
                {"reason": "translation_curve_data_unavailable"},
            )
        curves_summary = assess_translation_curves(
            measured_curve,
            warn_delta_db=warn_delta_db,
            error_delta_db=error_delta_db,
        )

    max_delta_db = curves_summary.get("max_delta_db")
    if not isinstance(max_delta_db, (int, float)):
        return _gate_result(
            gate_id,
            "skipped",
            "info",
            "Translation-curve objective data unavailable; translation gate skipped.",
            {"reason": "translation_curve_data_unavailable"},
        )
    max_delta = float(max_delta_db)

    if max_delta > error_delta_db:
        return _gate_result(
            gate_id,
            "block",
            "error",
            (
                f"Translation curve drift {max_delta:.2f} dB exceeds error threshold "
                f"({error_delta_db:.2f} dB)."
            ),
            {
                "max_delta_db": round(max_delta, 6),
                "warn_delta_db": warn_delta_db,
                "error_delta_db": error_delta_db,
                "profiles": curves_summary.get("profiles", []),
            },
        )
    if max_delta > warn_delta_db:
        return _gate_result(
            gate_id,
            "warn",
            "warn",
            (
                f"Translation curve drift {max_delta:.2f} dB exceeds warning threshold "
                f"({warn_delta_db:.2f} dB)."
            ),
            {
                "max_delta_db": round(max_delta, 6),
                "warn_delta_db": warn_delta_db,
                "profiles": curves_summary.get("profiles", []),
            },
        )
    return _gate_result(
        gate_id,
        "pass",
        "info",
        f"Translation curve drift within bounds (max {max_delta:.2f} dB).",
        {
            "max_delta_db": round(max_delta, 6),
            "profiles": curves_summary.get("profiles", []),
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_preflight(
    session: Dict[str, Any],
    scene: Dict[str, Any],
    target_layout: str,
    options: Dict[str, Any],
    *,
    user_profile: Optional[Dict[str, Any]] = None,
    rendered_file: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run all render-safety gates and return a deterministic preflight receipt.

    Parameters
    ----------
    session:
        Project/session context dict.  Recognised keys:

        - ``source_layout_id`` (str): canonical layout ID of the source material.
        - ``profile_id`` (str): authority profile in use (informational only).

    scene:
        Scene or analysis-report dict.  The function extracts what it needs
        from flexible locations (``run_config``, ``metadata``, ``objects``,
        ``recommendations``, ``qa_issues``).

    target_layout:
        Target layout ID (e.g. ``"LAYOUT.2_0"``) or a shorthand string
        (``"stereo"``, ``"5.1"``).  Normalised internally.

    options:
        Optional threshold overrides.  All keys are optional; defaults match
        ``ontology/gates.yaml``::

            lfe_boost_warn_db         (float, default 3.0)
            lfe_boost_error_db        (float, default 6.0)
            predicted_lufs_delta_warn_abs  (float, default 2.0)
            predicted_lufs_delta_error_abs (float, default 4.0)
            correlation_warn_lte      (float, default -0.2)
            correlation_error_lte     (float, default -0.6)
            polarity_warn_lte         (float, default -0.2)
            polarity_error_lte        (float, default -0.6)
            confidence_warn_below     (float, default 0.5)
            confidence_error_below    (float, default 0.2)
            warn_on_composed_path     (bool, default True)
            lra_warn_lu_lte           (float, default 1.5)
            lra_warn_lu_gte           (float, default 18.0)
            lra_error_lu_gte          (float, default 24.0)
            true_peak_channel_warn_dbtp  (float, default -2.0)
            true_peak_channel_error_dbtp (float, default -1.0)
            translation_curve_warn_db    (float, default 2.5)
            translation_curve_error_db   (float, default 4.0)

    user_profile:
        Optional user style/safety profile dict (as returned by
        ``mmo.core.profiles.get_profile``).  When provided, the profile's
        ``gate_overrides`` are merged into ``options`` before gate evaluation.
        Profile values take precedence over keys already in ``options``.
    rendered_file:
        Optional path to a rendered WAV file.  When provided,
        ``GATE.DOWNMIX_SIMILARITY_MEASURED`` is evaluated using real audio
        measurements (LUFS, true-peak, stereo correlation).  If ``None`` the
        gate is omitted from the receipt entirely.

    Returns
    -------
    dict
        Conforms to ``schemas/preflight_receipt.schema.json``.  The top-level
        ``final_decision`` field is:

        - ``"block"`` if any gate has outcome ``"block"``
        - ``"warn"`` if any gate has outcome ``"warn"`` (and none block)
        - ``"pass"`` otherwise
    """
    # Merge user profile gate overrides into options (profile wins over caller options)
    if isinstance(user_profile, dict):
        from mmo.core.profiles import apply_to_gates
        options = apply_to_gates(user_profile, options)

    target_layout_id = _normalise_layout_id(target_layout)
    source_layout_id = _extract_source_layout(session, scene)

    # --- Phase / correlation ---
    phase_report = _extract_phase_report(scene, options)

    # --- Confidence ---
    confidence_summary = _extract_confidence_summary(scene, options)
    objective_meters = _extract_objective_meters(scene)

    # --- Gate evaluations (deterministic order) ---
    gates_evaluated: List[Dict[str, Any]] = []
    downmix_checks: List[Dict[str, Any]] = []
    measured_similarity_checks: List[Dict[str, Any]] = []

    # 1. Layout negotiation
    layout_gate = _eval_layout_negotiation(source_layout_id, target_layout_id, options)
    gates_evaluated.append(layout_gate)

    # 2. Downmix similarity (matrix-coefficient prediction)
    similarity_gate, downmix_check = _eval_downmix_similarity(
        source_layout_id, target_layout_id, options
    )
    gates_evaluated.append(similarity_gate)
    if downmix_check is not None:
        downmix_checks.append(downmix_check)

    # 3. Measured similarity (real audio, only when rendered_file is provided)
    if rendered_file is not None:
        measured_gate, measured_check = _eval_downmix_similarity_measured(
            Path(rendered_file), target_layout_id, options
        )
        gates_evaluated.append(measured_gate)
        if measured_check is not None:
            measured_similarity_checks.append(measured_check)

    # 4. LRA objective gate
    lra_gate = _eval_lra_bounds(objective_meters, options)
    gates_evaluated.append(lra_gate)

    # 5. Per-channel true-peak objective gate
    true_peak_gate = _eval_true_peak_per_channel(objective_meters, options)
    gates_evaluated.append(true_peak_gate)

    # 6. Translation-curve objective gate
    translation_gate = _eval_translation_curves(objective_meters, options)
    gates_evaluated.append(translation_gate)

    # 7. Correlation risk
    corr_gate = _eval_correlation_risk(phase_report, options)
    gates_evaluated.append(corr_gate)

    # 8. Phase risk
    phase_gate = _eval_phase_risk(phase_report, options)
    gates_evaluated.append(phase_gate)

    # 9. Confidence
    conf_gate = _eval_confidence_low(confidence_summary, options)
    gates_evaluated.append(conf_gate)

    # --- Final decision ---
    outcomes = [g["outcome"] for g in gates_evaluated]
    if "block" in outcomes:
        final_decision = "block"
    elif "warn" in outcomes:
        final_decision = "warn"
    else:
        final_decision = "pass"

    receipt: Dict[str, Any] = {
        "schema_version": PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        "target_layout_id": target_layout_id,
        "source_layout_id": source_layout_id,
        "gates_evaluated": gates_evaluated,
        "downmix_checks": downmix_checks,
        "measured_similarity_checks": measured_similarity_checks,
        "phase_report": phase_report,
        "confidence_summary": confidence_summary,
        "final_decision": final_decision,
    }
    if isinstance(user_profile, dict):
        user_profile_id = user_profile.get("profile_id")
        if isinstance(user_profile_id, str) and user_profile_id:
            receipt["user_profile_id"] = user_profile_id
    return receipt


def preflight_receipt_blocks(receipt: Dict[str, Any]) -> bool:
    """Return *True* when the receipt's ``final_decision`` is ``"block"``."""
    return str(receipt.get("final_decision", "")) == "block"
