"""Render preflight: safety gate policy engine (DoD 4.4.3 + 4.6).

``evaluate_preflight`` runs all render-safety gates against session/scene
metadata *before* any audio is decoded or written.  It produces a deterministic
``preflight_receipt`` dict that conforms to
``schemas/preflight_receipt.schema.json``.

Gates evaluated (in order):
  1. ``GATE.LAYOUT_NEGOTIATION`` — downmix path exists?
  2. ``GATE.DOWNMIX_SIMILARITY``  — matrix-based LFE / loudness risk
  3. ``GATE.CORRELATION_RISK``    — scene correlation metadata
  4. ``GATE.PHASE_RISK``          — polarity / phase-inversion flags
  5. ``GATE.CONFIDENCE_LOW``      — scene inference confidence

Public API
----------
- ``evaluate_preflight(session, scene, target_layout, options)``
- ``preflight_receipt_blocks(receipt)``
- ``PREFLIGHT_RECEIPT_SCHEMA_VERSION``
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.core.downmix import (
    layout_negotiation_available,
    predict_fold_similarity,
    resolve_preflight_matrix,
)

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_preflight(
    session: Dict[str, Any],
    scene: Dict[str, Any],
    target_layout: str,
    options: Dict[str, Any],
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

    Returns
    -------
    dict
        Conforms to ``schemas/preflight_receipt.schema.json``.  The top-level
        ``final_decision`` field is:

        - ``"block"`` if any gate has outcome ``"block"``
        - ``"warn"`` if any gate has outcome ``"warn"`` (and none block)
        - ``"pass"`` otherwise
    """
    target_layout_id = _normalise_layout_id(target_layout)
    source_layout_id = _extract_source_layout(session, scene)

    # --- Phase / correlation ---
    phase_report = _extract_phase_report(scene, options)

    # --- Confidence ---
    confidence_summary = _extract_confidence_summary(scene, options)

    # --- Gate evaluations (deterministic order) ---
    gates_evaluated: List[Dict[str, Any]] = []
    downmix_checks: List[Dict[str, Any]] = []

    # 1. Layout negotiation
    layout_gate = _eval_layout_negotiation(source_layout_id, target_layout_id, options)
    gates_evaluated.append(layout_gate)

    # 2. Downmix similarity
    similarity_gate, downmix_check = _eval_downmix_similarity(
        source_layout_id, target_layout_id, options
    )
    gates_evaluated.append(similarity_gate)
    if downmix_check is not None:
        downmix_checks.append(downmix_check)

    # 3. Correlation risk
    corr_gate = _eval_correlation_risk(phase_report, options)
    gates_evaluated.append(corr_gate)

    # 4. Phase risk
    phase_gate = _eval_phase_risk(phase_report, options)
    gates_evaluated.append(phase_gate)

    # 5. Confidence
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
        "phase_report": phase_report,
        "confidence_summary": confidence_summary,
        "final_decision": final_decision,
    }
    return receipt


def preflight_receipt_blocks(receipt: Dict[str, Any]) -> bool:
    """Return *True* when the receipt's ``final_decision`` is ``"block"``."""
    return str(receipt.get("final_decision", "")) == "block"
