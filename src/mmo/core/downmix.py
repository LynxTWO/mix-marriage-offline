"""Core-layer downmix utilities: versioned matrix access and similarity scorer.

This module is the *core/* counterpart to :mod:`mmo.dsp.downmix`.  It wraps the
DSP-layer matrix resolution with higher-level risk-scoring functions that operate
on matrix coefficients alone — no audio decoding required — making them safe to
call during preflight checks.

Exported public API
-------------------
- ``MATRIX_VERSION`` — version tag for the coefficient spec.
- ``get_matrix_version()`` — returns ``MATRIX_VERSION``.
- ``resolve_preflight_matrix()`` — resolve a downmix matrix for preflight use.
- ``predict_fold_similarity()`` — score fold risk from matrix coefficients.
- ``layout_negotiation_available()`` — check whether a conversion path exists.
- ``measure_downmix_similarity()`` — measure actual similarity from rendered audio.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.dsp.downmix import (
    resolve_downmix_matrix,
)
from mmo.resources import ontology_dir

# Public version tag for the coefficient specification.
MATRIX_VERSION = "1.0.0"

# LFE channel identifiers recognised in layout channel_order lists.
_LFE_CHANNEL_IDS: frozenset[str] = frozenset({"LFE", "LFE1", "LFE2"})


def get_matrix_version() -> str:
    """Return the matrix specification version string."""
    return MATRIX_VERSION


def resolve_preflight_matrix(
    source_layout_id: str,
    target_layout_id: str,
    *,
    policy_id: Optional[str] = None,
    layouts_path: Optional[Any] = None,
    registry_path: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolve the downmix matrix for a given layout conversion.

    Wraps :func:`mmo.dsp.downmix.resolve_downmix_matrix` with the standard
    ontology paths, returning the resolved matrix dict.

    Raises :class:`ValueError` if no conversion path exists.
    """
    kwargs: Dict[str, Any] = {
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "policy_id": policy_id,
    }
    if layouts_path is not None:
        kwargs["layouts_path"] = layouts_path
    else:
        kwargs["layouts_path"] = ontology_dir() / "layouts.yaml"
    if registry_path is not None:
        kwargs["registry_path"] = registry_path
    else:
        kwargs["registry_path"] = ontology_dir() / "policies" / "downmix.yaml"
    return resolve_downmix_matrix(**kwargs)


def layout_negotiation_available(
    source_layout_id: str,
    target_layout_id: str,
    *,
    policy_id: Optional[str] = None,
    warn_on_composed_path: bool = True,
) -> Dict[str, Any]:
    """Check whether a downmix path exists between two layouts.

    Returns a dict::

        {
            "available": bool,
            "matrix_id": str | None,
            "composed": bool,
            "warning": str | None,
            "error": str | None,
        }

    ``available`` is *True* when a matrix (direct or composed) can be resolved.
    ``composed`` is *True* when the path requires multi-step composition.
    ``warning`` is set when ``warn_on_composed_path`` is *True* and a composed
    path is required.
    ``error`` is set when no path exists.
    """
    try:
        matrix = resolve_preflight_matrix(
            source_layout_id,
            target_layout_id,
            policy_id=policy_id,
        )
    except (ValueError, KeyError, FileNotFoundError) as exc:
        return {
            "available": False,
            "matrix_id": None,
            "composed": False,
            "warning": None,
            "error": str(exc),
        }

    matrix_id: str = str(matrix.get("matrix_id") or "")
    is_composed = bool(matrix.get("steps"))  # composed matrices carry a "steps" list
    warning: Optional[str] = None
    if is_composed and warn_on_composed_path:
        warning = (
            f"Conversion {source_layout_id} → {target_layout_id} uses a composed "
            f"(multi-step) matrix path; results may differ from a direct fold."
        )
    return {
        "available": True,
        "matrix_id": matrix_id,
        "composed": is_composed,
        "warning": warning,
        "error": None,
    }


def predict_fold_similarity(
    matrix: Dict[str, Any],
    *,
    lfe_boost_warn_db: float = 3.0,
    lfe_boost_error_db: float = 6.0,
    predicted_lufs_delta_warn_abs: float = 2.0,
    predicted_lufs_delta_error_abs: float = 4.0,
) -> Dict[str, Any]:
    """Predict fold-similarity risk from matrix coefficients alone (no audio).

    Uses linear algebra on the coefficient matrix to estimate:

    - **LFE fold gain**: maximum absolute coefficient for any LFE source channel.
    - **Predicted LUFS delta**: RMS gain change (relative to unity) per output
      channel, expressed in dB.
    - **Risk level**: ``"low"``, ``"medium"``, or ``"high"`` derived from the
      above measurements against configurable thresholds.

    Parameters
    ----------
    matrix:
        Matrix dict as returned by :func:`resolve_preflight_matrix`.  Must
        contain ``"source_speakers"``, ``"target_speakers"``, and ``"coeffs"``.
    lfe_boost_warn_db:
        LFE fold gain (dB) that triggers a *medium* risk classification.
    lfe_boost_error_db:
        LFE fold gain (dB) that triggers a *high* risk classification.
    predicted_lufs_delta_warn_abs:
        Absolute predicted LUFS delta that triggers *medium* risk.
    predicted_lufs_delta_error_abs:
        Absolute predicted LUFS delta that triggers *high* risk.

    Returns
    -------
    dict with keys: ``risk_level``, ``lfe_folded``, ``lfe_boost_db``,
    ``predicted_lufs_delta``, ``notes``.
    """
    source_speakers: List[str] = [
        str(s) for s in (matrix.get("source_speakers") or [])
    ]
    target_speakers: List[str] = [
        str(s) for s in (matrix.get("target_speakers") or [])
    ]
    coeffs: List[List[float]] = list(matrix.get("coeffs") or [])

    lfe_source_indices: List[int] = [
        i
        for i, sp in enumerate(source_speakers)
        if sp.upper() in _LFE_CHANNEL_IDS
    ]

    notes: List[str] = []
    lfe_folded = False
    lfe_boost_db = 0.0

    # --- LFE fold analysis ---------------------------------------------------
    if lfe_source_indices and coeffs:
        max_lfe_coeff = 0.0
        for row in coeffs:
            for lfe_idx in lfe_source_indices:
                if lfe_idx < len(row):
                    v = abs(float(row[lfe_idx]))
                    if v > max_lfe_coeff:
                        max_lfe_coeff = v
        if max_lfe_coeff > 0.0:
            lfe_folded = True
            lfe_boost_db = round(20.0 * math.log10(max_lfe_coeff), 3)
            notes.append(
                f"LFE channel folded with max coefficient "
                f"{max_lfe_coeff:.4f} ({lfe_boost_db:+.1f} dB)"
            )

    # --- Predicted LUFS delta -----------------------------------------------
    # Compute per-target-channel RMS gain from the coefficient rows.
    # Compare against unity (0 dB) to estimate the loudness change.
    predicted_lufs_delta = 0.0
    n_source = len(source_speakers)
    n_target = len(target_speakers)
    if coeffs and n_source > 0 and n_target > 0:
        target_gains: List[float] = []
        for row in coeffs:
            row_sq_sum = sum(
                float(v) ** 2
                for i, v in enumerate(row)
                if isinstance(v, (int, float))
                and i not in lfe_source_indices  # exclude LFE from loudness estimate
            )
            rms_gain = math.sqrt(row_sq_sum) if row_sq_sum > 0 else 0.0
            target_gains.append(rms_gain)
        non_zero = [g for g in target_gains if g > 0.0]
        if non_zero:
            avg_gain = sum(non_zero) / len(non_zero)
            predicted_lufs_delta = round(20.0 * math.log10(avg_gain), 3)

    # --- Risk classification -------------------------------------------------
    risk_level = "low"

    if lfe_folded:
        if abs(lfe_boost_db) >= lfe_boost_error_db:
            risk_level = "high"
            notes.append(
                f"LFE boost {lfe_boost_db:+.1f} dB ≥ error threshold "
                f"({lfe_boost_error_db:+.1f} dB)"
            )
        elif abs(lfe_boost_db) >= lfe_boost_warn_db:
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                f"LFE boost {lfe_boost_db:+.1f} dB ≥ warn threshold "
                f"({lfe_boost_warn_db:+.1f} dB)"
            )

    if abs(predicted_lufs_delta) >= predicted_lufs_delta_error_abs:
        risk_level = "high"
        notes.append(
            f"Predicted LUFS delta {predicted_lufs_delta:+.1f} dB ≥ error threshold "
            f"(±{predicted_lufs_delta_error_abs:.1f} dB)"
        )
    elif abs(predicted_lufs_delta) >= predicted_lufs_delta_warn_abs:
        if risk_level == "low":
            risk_level = "medium"
        notes.append(
            f"Predicted LUFS delta {predicted_lufs_delta:+.1f} dB ≥ warn threshold "
            f"(±{predicted_lufs_delta_warn_abs:.1f} dB)"
        )

    return {
        "risk_level": risk_level,
        "lfe_folded": lfe_folded,
        "lfe_boost_db": lfe_boost_db if lfe_folded else 0.0,
        "predicted_lufs_delta": predicted_lufs_delta,
        "notes": notes,
    }


def measure_downmix_similarity(
    rendered_file: Path,
    target_layout: str,
    *,
    true_peak_warn_dbtp: float = -3.0,
    true_peak_error_dbtp: float = -1.0,
    lufs_delta_warn_abs: float = 3.0,
    lufs_delta_error_abs: float = 6.0,
    correlation_warn_lte: float = -0.2,
    correlation_error_lte: float = -0.6,
    reference_lufs: Optional[float] = None,
) -> Dict[str, Any]:
    """Measure actual downmix similarity from a rendered audio file.

    Uses three complementary measurements:

    - **Spectral (LUFS integrated)**: BS.1770-style gated loudness of the
      rendered output.  When *reference_lufs* is supplied the delta against
      the reference is classified for risk.
    - **Cross-channel correlation**: Pearson L-R correlation for stereo output
      (2-channel files only).  Strong negative correlation indicates
      phase-cancellation risk.
    - **True-peak**: 4× oversampled true-peak per ITU-R BS.1770-4.
      ``true_peak_delta_db`` is the headroom below 0 dBTP ceiling
      (positive = headroom; negative would exceed ceiling).

    Parameters
    ----------
    rendered_file:
        Path to a WAV file produced by the downmix render step.
    target_layout:
        Canonical target layout ID (e.g. ``"LAYOUT.2_0"``), used for labelling.
    true_peak_warn_dbtp:
        True-peak threshold (dBTP) that triggers *medium* risk when exceeded.
    true_peak_error_dbtp:
        True-peak threshold (dBTP) that triggers *high* risk when exceeded.
    lufs_delta_warn_abs:
        Absolute LUFS delta (dB) that triggers *medium* risk.  Only evaluated
        when *reference_lufs* is supplied.
    lufs_delta_error_abs:
        Absolute LUFS delta (dB) that triggers *high* risk.
    correlation_warn_lte:
        Stereo correlation value at or below which *medium* risk is triggered.
    correlation_error_lte:
        Stereo correlation value at or below which *high* risk is triggered.
    reference_lufs:
        Optional reference loudness (LUFS) to compare against.  When given,
        ``lufs_delta_db`` is computed and classified.

    Returns
    -------
    dict
        Keys: ``gate_id``, ``target_layout_id``, ``channels``,
        ``lufs_integrated``, ``true_peak_dbtp``, ``true_peak_delta_db``,
        ``stereo_correlation``, ``lufs_delta_db`` (optional),
        ``risk_level``, ``notes``, ``measured``.

    Raises
    ------
    ValueError
        If the WAV file cannot be read or has an unsupported format.
    """
    # Lazy imports to avoid adding numpy/dsp deps to module-load time.
    from mmo.dsp.io import read_wav_metadata
    from mmo.dsp.meters_truth import (
        compute_lufs_integrated_wav,
        compute_true_peak_dbtp_wav,
    )
    from mmo.dsp.stereo import compute_stereo_correlation_wav

    rendered_file = Path(rendered_file)
    metadata = read_wav_metadata(rendered_file)
    channels = int(metadata["channels"])

    notes: List[str] = []

    # --- Spectral: integrated LUFS -------------------------------------------
    lufs_raw = compute_lufs_integrated_wav(rendered_file)
    lufs_integrated: Optional[float] = (
        None if math.isinf(lufs_raw) else round(lufs_raw, 3)
    )

    # --- True-peak (dBTP) ----------------------------------------------------
    tp_raw = compute_true_peak_dbtp_wav(rendered_file)
    true_peak_dbtp: Optional[float] = (
        None if math.isinf(tp_raw) else round(tp_raw, 3)
    )
    # Headroom below 0 dBTP ceiling (positive = safe distance from clipping)
    true_peak_delta_db: Optional[float] = (
        None if true_peak_dbtp is None else round(0.0 - true_peak_dbtp, 3)
    )

    # --- Cross-channel correlation (stereo only) -----------------------------
    stereo_correlation: Optional[float] = None
    if channels == 2:
        corr_raw = compute_stereo_correlation_wav(rendered_file)
        stereo_correlation = round(corr_raw, 6)

    # --- LUFS delta (only when reference supplied) ---------------------------
    lufs_delta_db: Optional[float] = None
    if reference_lufs is not None and lufs_integrated is not None:
        lufs_delta_db = round(lufs_integrated - float(reference_lufs), 3)

    # --- Risk classification -------------------------------------------------
    risk_level = "low"

    # True-peak risk
    if true_peak_dbtp is not None:
        if true_peak_dbtp > true_peak_error_dbtp:
            risk_level = "high"
            notes.append(
                f"True-peak {true_peak_dbtp:+.1f} dBTP exceeds error threshold "
                f"({true_peak_error_dbtp:+.1f} dBTP)"
            )
        elif true_peak_dbtp > true_peak_warn_dbtp:
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                f"True-peak {true_peak_dbtp:+.1f} dBTP exceeds warn threshold "
                f"({true_peak_warn_dbtp:+.1f} dBTP)"
            )

    # Stereo correlation risk
    if stereo_correlation is not None:
        if stereo_correlation <= correlation_error_lte:
            risk_level = "high"
            notes.append(
                f"Stereo correlation {stereo_correlation:.3f} ≤ error threshold "
                f"({correlation_error_lte:.1f})"
            )
        elif stereo_correlation <= correlation_warn_lte:
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                f"Stereo correlation {stereo_correlation:.3f} ≤ warn threshold "
                f"({correlation_warn_lte:.1f})"
            )

    # LUFS delta risk (only when reference provided)
    if lufs_delta_db is not None:
        if abs(lufs_delta_db) >= lufs_delta_error_abs:
            risk_level = "high"
            notes.append(
                f"LUFS delta {lufs_delta_db:+.1f} dB ≥ error threshold "
                f"(±{lufs_delta_error_abs:.1f} dB)"
            )
        elif abs(lufs_delta_db) >= lufs_delta_warn_abs:
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                f"LUFS delta {lufs_delta_db:+.1f} dB ≥ warn threshold "
                f"(±{lufs_delta_warn_abs:.1f} dB)"
            )

    result: Dict[str, Any] = {
        "gate_id": "GATE.DOWNMIX_SIMILARITY_MEASURED",
        "target_layout_id": target_layout,
        "channels": channels,
        "lufs_integrated": lufs_integrated,
        "true_peak_dbtp": true_peak_dbtp,
        "true_peak_delta_db": true_peak_delta_db,
        "stereo_correlation": stereo_correlation,
        "risk_level": risk_level,
        "notes": notes,
        "measured": True,
    }
    if lufs_delta_db is not None:
        result["lufs_delta_db"] = lufs_delta_db
    return result
