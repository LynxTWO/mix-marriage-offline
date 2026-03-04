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
- ``apply_downmix_matrix_deterministic()`` — apply a resolved matrix deterministically.
- ``compare_rendered_surround_to_stereo_reference()`` — compare surround fold-down vs stereo.
- ``enforce_rendered_surround_similarity_gate()`` — one-shot fallback gate for
  5.1/7.1/7.1.4/9.1.6 renders.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from mmo.core.loudness_methods import DEFAULT_LOUDNESS_METHOD_ID
from mmo.dsp.downmix import (
    apply_matrix_to_audio,
    resolve_downmix_matrix,
)
from mmo.resources import ontology_dir

# Public version tag for the coefficient specification.
MATRIX_VERSION = "1.0.0"

# Version tag for rendered surround-vs-stereo similarity gate logic.
RENDERED_SIMILARITY_GATE_VERSION = "1.0.0"

# LFE channel identifiers recognised in matrix speaker lists.
_LFE_CHANNEL_IDS: frozenset[str] = frozenset(
    {"LFE", "LFE1", "LFE2", "SPK.LFE", "SPK.LFE1", "SPK.LFE2"}
)
_BACKOFF_SPK_IDS: frozenset[str] = frozenset(
    {
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
        "SPK.TFL",
        "SPK.TFR",
        "SPK.TRL",
        "SPK.TRR",
        "SPK.TFC",
        "SPK.TBC",
        "SPK.LW",
        "SPK.RW",
    }
)
_SUPPORTED_SURROUND_FALLBACK_LAYOUTS: frozenset[str] = frozenset(
    {"LAYOUT.5_1", "LAYOUT.7_1", "LAYOUT.7_1_4", "LAYOUT.9_1_6"}
)
_TARGET_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_PCM24_MIN = -8_388_608
_PCM24_MAX = 8_388_607
_FLOAT_MAX = math.nextafter(1.0, 0.0)


def _is_lfe_speaker_id(speaker_id: str) -> bool:
    token = str(speaker_id).strip().upper()
    if not token:
        return False
    if token in _LFE_CHANNEL_IDS:
        return True
    return token.startswith("SPK.LFE")


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
        if _is_lfe_speaker_id(sp)
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
    lufs_raw = compute_lufs_integrated_wav(
        rendered_file,
        method_id=DEFAULT_LOUDNESS_METHOD_ID,
    )
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


def apply_downmix_matrix_deterministic(
    source_interleaved: List[float],
    *,
    source_layout_id: str,
    target_layout_id: str = _TARGET_STEREO_LAYOUT_ID,
    policy_id: Optional[str] = None,
    sample_rate_hz: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply a resolved downmix matrix deterministically to interleaved samples.

    Returns matrix metadata plus the downmixed interleaved output.
    """
    matrix = resolve_preflight_matrix(
        source_layout_id,
        target_layout_id,
        policy_id=policy_id,
    )
    source_speakers = list(matrix.get("source_speakers") or [])
    target_speakers = list(matrix.get("target_speakers") or [])
    coeffs = list(matrix.get("coeffs") or [])
    source_channels = len(source_speakers)
    target_channels = len(target_speakers)
    if source_channels <= 0 or target_channels <= 0:
        raise ValueError("Resolved matrix must include source and target speakers.")
    output_interleaved = apply_matrix_to_audio(
        coeffs,
        source_interleaved,
        source_channels,
        target_channels=target_channels,
        source_pre_filters=matrix.get("source_pre_filters"),
        source_speakers=source_speakers,
        sample_rate_hz=sample_rate_hz,
    )
    return {
        "gate_id": "GATE.DOWNMIX_MATRIX_APPLY",
        "matrix_id": str(matrix.get("matrix_id") or ""),
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "source_channels": source_channels,
        "target_channels": target_channels,
        "output_interleaved": output_interleaved,
    }


def _clamp_sample(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > _FLOAT_MAX:
        return _FLOAT_MAX
    return value


def _float_samples_to_pcm24_bytes(samples: Iterable[float]) -> bytes:
    scale = float(_PCM24_MAX)
    out = bytearray()
    for sample in samples:
        value = _clamp_sample(float(sample))
        quantized = int(round(value * scale))
        if quantized < _PCM24_MIN:
            quantized = _PCM24_MIN
        elif quantized > _PCM24_MAX:
            quantized = _PCM24_MAX
        out.extend(int(quantized).to_bytes(4, byteorder="little", signed=True)[:3])
    return bytes(out)


def _load_wav_frames_float64(path: Path) -> Dict[str, Any]:
    from mmo.dsp.io import read_wav_metadata
    from mmo.dsp.meters import iter_wav_float64_samples

    resolved = Path(path)
    metadata = read_wav_metadata(resolved)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    if channels <= 0:
        raise ValueError(f"Invalid WAV channel count: {resolved}")
    if sample_rate_hz <= 0:
        raise ValueError(f"Invalid WAV sample rate: {resolved}")
    interleaved: List[float] = []
    for chunk in iter_wav_float64_samples(
        resolved,
        error_context="downmix rendered similarity",
    ):
        if chunk:
            interleaved.extend(chunk)
    total = len(interleaved) - (len(interleaved) % channels)
    if total <= 0:
        return {
            "path": resolved,
            "channels": channels,
            "sample_rate_hz": sample_rate_hz,
            "interleaved": [],
            "frames": 0,
        }
    clipped = interleaved[:total]
    return {
        "path": resolved,
        "channels": channels,
        "sample_rate_hz": sample_rate_hz,
        "interleaved": clipped,
        "frames": total // channels,
    }


def _to_dbfs(peak_linear: float) -> Optional[float]:
    if not isinstance(peak_linear, (int, float)):
        return None
    value = float(peak_linear)
    if value <= 0.0 or not math.isfinite(value):
        return None
    return 20.0 * math.log10(value)


def _round_optional(value: Optional[float], digits: int = 6) -> Optional[float]:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _pearson(a: Any, b: Any, np_module: Any) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    a_centered = a - np_module.mean(a)
    b_centered = b - np_module.mean(b)
    denom = float(
        np_module.sqrt(
            np_module.sum(a_centered * a_centered)
            * np_module.sum(b_centered * b_centered)
        )
    )
    if denom <= 0.0:
        return 0.0
    corr = float(np_module.sum(a_centered * b_centered) / denom)
    if corr > 1.0:
        return 1.0
    if corr < -1.0:
        return -1.0
    return corr


def _windowed_correlations(
    ref_mono: Any,
    fold_mono: Any,
    *,
    sample_rate_hz: int,
    np_module: Any,
) -> Dict[str, float]:
    total = int(min(ref_mono.shape[0], fold_mono.shape[0]))
    if total <= 0:
        return {"min": 0.0, "mean": 0.0, "count": 0}
    window = max(1, int(sample_rate_hz))  # 1 second
    hop = max(1, int(window // 2))
    corr_values: List[float] = []
    if total < window:
        corr_values.append(_pearson(ref_mono[:total], fold_mono[:total], np_module))
    else:
        for start in range(0, total - window + 1, hop):
            end = start + window
            corr_values.append(
                _pearson(ref_mono[start:end], fold_mono[start:end], np_module)
            )
    if not corr_values:
        corr_values = [0.0]
    return {
        "min": float(min(corr_values)),
        "mean": float(sum(corr_values) / len(corr_values)),
        "count": int(len(corr_values)),
    }


def _coarse_spectral_band_levels_db(
    mono: Any,
    *,
    sample_rate_hz: int,
    np_module: Any,
) -> Dict[str, float]:
    bands: Dict[str, tuple[float, float]] = {
        "low": (20.0, 120.0),
        "low_mid": (120.0, 500.0),
        "mid": (500.0, 2000.0),
        "high": (2000.0, 8000.0),
        "air": (8000.0, 20000.0),
    }
    sample_count = int(mono.shape[0])
    if sample_count <= 0:
        return {band_id: float("-inf") for band_id in sorted(bands.keys())}
    # Deterministic wide snapshot of the available window.
    window_size = min(sample_count, 65536)
    signal = mono[:window_size]
    window = np_module.hanning(window_size)
    fft = np_module.fft.rfft(signal * window)
    power = (np_module.abs(fft) ** 2) + 1e-24
    freqs = np_module.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
    levels: Dict[str, float] = {}
    for band_id in sorted(bands.keys()):
        low_hz, high_hz = bands[band_id]
        mask = (freqs >= low_hz) & (freqs < high_hz)
        if not bool(np_module.any(mask)):
            levels[band_id] = float("-inf")
            continue
        mean_power = float(np_module.mean(power[mask]))
        levels[band_id] = 10.0 * math.log10(mean_power)
    return levels


def _compute_rendered_similarity_metrics(
    *,
    stereo_data: Dict[str, Any],
    folded_interleaved: List[float],
) -> Dict[str, Any]:
    try:
        import numpy as np  # noqa: WPS433
        from mmo.dsp import meters_truth
    except ImportError as exc:
        raise RuntimeError(
            "Rendered similarity gate requires numpy/truth meters."
        ) from exc

    sample_rate_hz = int(stereo_data["sample_rate_hz"])
    ref_frames = int(stereo_data["frames"])
    ref_interleaved = list(stereo_data["interleaved"])
    fold_frames = len(folded_interleaved) // 2
    frames = min(ref_frames, fold_frames)
    if frames <= 0:
        raise ValueError("Rendered similarity gate requires non-empty reference and folded audio.")

    ref_total = frames * 2
    fold_total = frames * 2
    ref_array = np.asarray(ref_interleaved[:ref_total], dtype=np.float64).reshape(-1, 2)
    fold_array = np.asarray(folded_interleaved[:fold_total], dtype=np.float64).reshape(-1, 2)

    ref_lufs = float(
        meters_truth.compute_lufs_integrated_float64(
            ref_array,
            sample_rate_hz,
            channels=2,
            channel_mask=None,
            channel_layout="stereo",
            method_id=DEFAULT_LOUDNESS_METHOD_ID,
        )
    )
    fold_lufs = float(
        meters_truth.compute_lufs_integrated_float64(
            fold_array,
            sample_rate_hz,
            channels=2,
            channel_mask=None,
            channel_layout="stereo",
            method_id=DEFAULT_LOUDNESS_METHOD_ID,
        )
    )
    ref_lufs_opt = None if math.isinf(ref_lufs) else ref_lufs
    fold_lufs_opt = None if math.isinf(fold_lufs) else fold_lufs
    loudness_delta_lufs: Optional[float]
    if ref_lufs_opt is None or fold_lufs_opt is None:
        loudness_delta_lufs = None
    else:
        loudness_delta_lufs = fold_lufs_opt - ref_lufs_opt

    ref_peak_linear = float(np.max(np.abs(ref_array))) if ref_array.size else 0.0
    fold_peak_linear = float(np.max(np.abs(fold_array))) if fold_array.size else 0.0
    ref_peak_dbfs = _to_dbfs(ref_peak_linear)
    fold_peak_dbfs = _to_dbfs(fold_peak_linear)
    peak_delta_dbfs: Optional[float]
    if ref_peak_dbfs is None or fold_peak_dbfs is None:
        peak_delta_dbfs = None
    else:
        peak_delta_dbfs = fold_peak_dbfs - ref_peak_dbfs

    ref_true_peak = float(meters_truth.compute_true_peak_dbtp_float64(ref_array, sample_rate_hz))
    fold_true_peak = float(meters_truth.compute_true_peak_dbtp_float64(fold_array, sample_rate_hz))
    ref_true_peak_opt = None if math.isinf(ref_true_peak) else ref_true_peak
    fold_true_peak_opt = None if math.isinf(fold_true_peak) else fold_true_peak
    true_peak_delta_dbtp: Optional[float]
    if ref_true_peak_opt is None or fold_true_peak_opt is None:
        true_peak_delta_dbtp = None
    else:
        true_peak_delta_dbtp = fold_true_peak_opt - ref_true_peak_opt

    ref_mono = np.mean(ref_array, axis=1)
    fold_mono = np.mean(fold_array, axis=1)
    corr_summary = _windowed_correlations(
        ref_mono,
        fold_mono,
        sample_rate_hz=sample_rate_hz,
        np_module=np,
    )
    ref_levels = _coarse_spectral_band_levels_db(
        ref_mono,
        sample_rate_hz=sample_rate_hz,
        np_module=np,
    )
    fold_levels = _coarse_spectral_band_levels_db(
        fold_mono,
        sample_rate_hz=sample_rate_hz,
        np_module=np,
    )
    band_distance_db: Dict[str, float] = {}
    for band_id in sorted(ref_levels.keys()):
        ref_level = ref_levels[band_id]
        fold_level = fold_levels.get(band_id, float("-inf"))
        if not math.isfinite(ref_level) or not math.isfinite(fold_level):
            band_distance_db[band_id] = 0.0
        else:
            band_distance_db[band_id] = abs(fold_level - ref_level)
    spectral_distance_db = (
        sum(band_distance_db.values()) / float(len(band_distance_db))
        if band_distance_db
        else 0.0
    )

    return {
        "sample_rate_hz": sample_rate_hz,
        "frames_compared": frames,
        "loudness_delta_lufs": _round_optional(loudness_delta_lufs),
        "correlation_over_time_min": _round_optional(corr_summary["min"]),
        "correlation_over_time_mean": _round_optional(corr_summary["mean"]),
        "correlation_window_count": int(corr_summary["count"]),
        "spectral_distance_db": _round_optional(spectral_distance_db),
        "spectral_band_distance_db": {
            band_id: _round_optional(value)
            for band_id, value in sorted(band_distance_db.items())
        },
        "peak_delta_dbfs": _round_optional(peak_delta_dbfs),
        "true_peak_delta_dbtp": _round_optional(true_peak_delta_dbtp),
    }


def compare_rendered_surround_to_stereo_reference(
    *,
    stereo_render_file: Path,
    surround_render_file: Path,
    source_layout_id: str,
    policy_id: Optional[str] = None,
    loudness_delta_warn_abs: float = 1.0,
    loudness_delta_error_abs: float = 2.0,
    correlation_time_warn_lte: float = 0.5,
    correlation_time_error_lte: float = 0.25,
    spectral_distance_warn_db: float = 3.0,
    spectral_distance_error_db: float = 6.0,
    peak_delta_warn_abs: float = 1.5,
    peak_delta_error_abs: float = 3.0,
    true_peak_delta_warn_abs: float = 1.0,
    true_peak_delta_error_abs: float = 2.0,
) -> Dict[str, Any]:
    """Compare stereo render against downmix(rendered surround) for QA gating."""
    stereo_data = _load_wav_frames_float64(Path(stereo_render_file))
    if int(stereo_data["channels"]) != 2:
        raise ValueError("stereo_render_file must be 2-channel audio.")

    surround_data = _load_wav_frames_float64(Path(surround_render_file))
    source_channels = int(surround_data["channels"])
    if source_channels <= 2:
        raise ValueError("surround_render_file must be multichannel (>2 channels).")
    if int(stereo_data["sample_rate_hz"]) != int(surround_data["sample_rate_hz"]):
        raise ValueError(
            "Stereo and surround sample rates must match for similarity comparison."
        )

    matrix = resolve_preflight_matrix(
        source_layout_id,
        _TARGET_STEREO_LAYOUT_ID,
        policy_id=policy_id,
    )
    source_speakers = list(matrix.get("source_speakers") or [])
    if len(source_speakers) != source_channels:
        raise ValueError(
            "Matrix/source channel mismatch for rendered surround file: "
            f"matrix={len(source_speakers)} source={source_channels}"
        )

    folded = apply_matrix_to_audio(
        list(matrix.get("coeffs") or []),
        list(surround_data["interleaved"]),
        source_channels=source_channels,
        target_channels=2,
        source_pre_filters=matrix.get("source_pre_filters"),
        source_speakers=source_speakers,
        sample_rate_hz=int(surround_data["sample_rate_hz"]),
    )
    metrics = _compute_rendered_similarity_metrics(
        stereo_data=stereo_data,
        folded_interleaved=folded,
    )

    notes: List[str] = []
    risk_level = "low"

    loudness_delta = metrics.get("loudness_delta_lufs")
    if isinstance(loudness_delta, (int, float)):
        if abs(float(loudness_delta)) >= float(loudness_delta_error_abs):
            risk_level = "high"
            notes.append(
                "Loudness delta exceeds error threshold "
                f"(abs={abs(float(loudness_delta)):.3f} LUFS)."
            )
        elif abs(float(loudness_delta)) >= float(loudness_delta_warn_abs):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Loudness delta exceeds warning threshold "
                f"(abs={abs(float(loudness_delta)):.3f} LUFS)."
            )

    corr_min = metrics.get("correlation_over_time_min")
    if isinstance(corr_min, (int, float)):
        if float(corr_min) <= float(correlation_time_error_lte):
            risk_level = "high"
            notes.append(
                "Correlation-over-time minimum is below error threshold "
                f"({float(corr_min):.3f})."
            )
        elif float(corr_min) <= float(correlation_time_warn_lte):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Correlation-over-time minimum is below warning threshold "
                f"({float(corr_min):.3f})."
            )

    spectral_distance = metrics.get("spectral_distance_db")
    if isinstance(spectral_distance, (int, float)):
        if float(spectral_distance) >= float(spectral_distance_error_db):
            risk_level = "high"
            notes.append(
                "Coarse spectral distance exceeds error threshold "
                f"({float(spectral_distance):.3f} dB)."
            )
        elif float(spectral_distance) >= float(spectral_distance_warn_db):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Coarse spectral distance exceeds warning threshold "
                f"({float(spectral_distance):.3f} dB)."
            )

    peak_delta = metrics.get("peak_delta_dbfs")
    if isinstance(peak_delta, (int, float)):
        if abs(float(peak_delta)) >= float(peak_delta_error_abs):
            risk_level = "high"
            notes.append(
                "Peak delta exceeds error threshold "
                f"(abs={abs(float(peak_delta)):.3f} dBFS)."
            )
        elif abs(float(peak_delta)) >= float(peak_delta_warn_abs):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Peak delta exceeds warning threshold "
                f"(abs={abs(float(peak_delta)):.3f} dBFS)."
            )

    true_peak_delta = metrics.get("true_peak_delta_dbtp")
    if isinstance(true_peak_delta, (int, float)):
        if abs(float(true_peak_delta)) >= float(true_peak_delta_error_abs):
            risk_level = "high"
            notes.append(
                "True-peak delta exceeds error threshold "
                f"(abs={abs(float(true_peak_delta)):.3f} dBTP)."
            )
        elif abs(float(true_peak_delta)) >= float(true_peak_delta_warn_abs):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "True-peak delta exceeds warning threshold "
                f"(abs={abs(float(true_peak_delta)):.3f} dBTP)."
            )

    return {
        "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
        "gate_version": RENDERED_SIMILARITY_GATE_VERSION,
        "source_layout_id": source_layout_id,
        "target_layout_id": _TARGET_STEREO_LAYOUT_ID,
        "matrix_id": str(matrix.get("matrix_id") or ""),
        "stereo_render_path": str(Path(stereo_render_file)),
        "surround_render_path": str(Path(surround_render_file)),
        "metrics": metrics,
        "thresholds": {
            "loudness_delta_warn_abs": float(loudness_delta_warn_abs),
            "loudness_delta_error_abs": float(loudness_delta_error_abs),
            "correlation_time_warn_lte": float(correlation_time_warn_lte),
            "correlation_time_error_lte": float(correlation_time_error_lte),
            "spectral_distance_warn_db": float(spectral_distance_warn_db),
            "spectral_distance_error_db": float(spectral_distance_error_db),
            "peak_delta_warn_abs": float(peak_delta_warn_abs),
            "peak_delta_error_abs": float(peak_delta_error_abs),
            "true_peak_delta_warn_abs": float(true_peak_delta_warn_abs),
            "true_peak_delta_error_abs": float(true_peak_delta_error_abs),
        },
        "risk_level": risk_level,
        "passed": risk_level == "low",
        "notes": notes,
    }


def _surround_channel_indices(layout_id: str, channel_count: int) -> List[int]:
    from mmo.core.layout_negotiation import get_layout_channel_order

    order = get_layout_channel_order(layout_id)
    if not isinstance(order, list) or not order:
        raise ValueError(f"Unable to resolve channel order for layout: {layout_id}")
    indices = [
        index
        for index, speaker_id in enumerate(order)
        if isinstance(speaker_id, str)
        and speaker_id in _BACKOFF_SPK_IDS
        and index < channel_count
    ]
    if not indices:
        raise ValueError(
            f"Layout {layout_id} has no fallback backoff channel indices within {channel_count} channels."
        )
    return sorted(indices)


def _attenuate_wav_channels_inplace(
    *,
    wav_path: Path,
    channel_indices: List[int],
    gain_db: float,
) -> None:
    from mmo.dsp.io import read_wav_metadata
    from mmo.dsp.meters import iter_wav_float64_samples

    metadata = read_wav_metadata(wav_path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    if channels <= 0 or sample_rate_hz <= 0:
        raise ValueError(f"Invalid WAV metadata for attenuation: {wav_path}")
    linear = math.pow(10.0, float(gain_db) / 20.0)
    target_indices = {index for index in channel_indices if 0 <= index < channels}
    if not target_indices:
        raise ValueError("No valid surround channels available for attenuation.")

    tmp_path = wav_path.parent / f"{wav_path.name}.mmo_retry.tmp"
    try:
        with wave.open(str(tmp_path), "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(3)  # deterministic PCM24 output
            handle.setframerate(sample_rate_hz)
            for chunk in iter_wav_float64_samples(
                wav_path,
                error_context="downmix similarity fallback attenuation",
            ):
                if not chunk:
                    continue
                total = len(chunk) - (len(chunk) % channels)
                if total <= 0:
                    continue
                adjusted: List[float] = list(chunk[:total])
                frames = total // channels
                for frame_index in range(frames):
                    base = frame_index * channels
                    for channel_index in target_indices:
                        sample_index = base + channel_index
                        adjusted[sample_index] = _clamp_sample(
                            float(adjusted[sample_index]) * linear
                        )
                handle.writeframes(_float_samples_to_pcm24_bytes(adjusted))
        tmp_path.replace(wav_path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def enforce_rendered_surround_similarity_gate(
    *,
    stereo_render_file: Path,
    surround_render_file: Path,
    source_layout_id: str,
    policy_id: Optional[str] = None,
    surround_backoff_db: float = -3.0,
    loudness_delta_warn_abs: float = 1.0,
    loudness_delta_error_abs: float = 2.0,
    correlation_time_warn_lte: float = 0.5,
    correlation_time_error_lte: float = 0.25,
    spectral_distance_warn_db: float = 3.0,
    spectral_distance_error_db: float = 6.0,
    peak_delta_warn_abs: float = 1.5,
    peak_delta_error_abs: float = 3.0,
    true_peak_delta_warn_abs: float = 1.0,
    true_peak_delta_error_abs: float = 2.0,
) -> Dict[str, Any]:
    """Run rendered similarity gate and apply a single deterministic fallback pass.

    Fallback is layout-scoped to 5.1/7.1/7.1.4/9.1.6 and attenuates one pass of
    surround/height/wide channels.
    """
    first = compare_rendered_surround_to_stereo_reference(
        stereo_render_file=stereo_render_file,
        surround_render_file=surround_render_file,
        source_layout_id=source_layout_id,
        policy_id=policy_id,
        loudness_delta_warn_abs=loudness_delta_warn_abs,
        loudness_delta_error_abs=loudness_delta_error_abs,
        correlation_time_warn_lte=correlation_time_warn_lte,
        correlation_time_error_lte=correlation_time_error_lte,
        spectral_distance_warn_db=spectral_distance_warn_db,
        spectral_distance_error_db=spectral_distance_error_db,
        peak_delta_warn_abs=peak_delta_warn_abs,
        peak_delta_error_abs=peak_delta_error_abs,
        true_peak_delta_warn_abs=true_peak_delta_warn_abs,
        true_peak_delta_error_abs=true_peak_delta_error_abs,
    )
    attempts = [dict(first)]
    fallback_applied = False

    if (
        not bool(first.get("passed"))
        and source_layout_id in _SUPPORTED_SURROUND_FALLBACK_LAYOUTS
    ):
        surround_data = _load_wav_frames_float64(Path(surround_render_file))
        channel_indices = _surround_channel_indices(
            source_layout_id,
            int(surround_data["channels"]),
        )
        _attenuate_wav_channels_inplace(
            wav_path=Path(surround_render_file),
            channel_indices=channel_indices,
            gain_db=surround_backoff_db,
        )
        fallback_applied = True
        second = compare_rendered_surround_to_stereo_reference(
            stereo_render_file=stereo_render_file,
            surround_render_file=surround_render_file,
            source_layout_id=source_layout_id,
            policy_id=policy_id,
            loudness_delta_warn_abs=loudness_delta_warn_abs,
            loudness_delta_error_abs=loudness_delta_error_abs,
            correlation_time_warn_lte=correlation_time_warn_lte,
            correlation_time_error_lte=correlation_time_error_lte,
            spectral_distance_warn_db=spectral_distance_warn_db,
            spectral_distance_error_db=spectral_distance_error_db,
            peak_delta_warn_abs=peak_delta_warn_abs,
            peak_delta_error_abs=peak_delta_error_abs,
            true_peak_delta_warn_abs=true_peak_delta_warn_abs,
            true_peak_delta_error_abs=true_peak_delta_error_abs,
        )
        attempts.append(dict(second))

    final = attempts[-1]
    return {
        "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
        "gate_version": RENDERED_SIMILARITY_GATE_VERSION,
        "source_layout_id": source_layout_id,
        "target_layout_id": _TARGET_STEREO_LAYOUT_ID,
        "stereo_render_path": str(Path(stereo_render_file)),
        "surround_render_path": str(Path(surround_render_file)),
        "fallback_applied": fallback_applied,
        "surround_backoff_db": float(surround_backoff_db) if fallback_applied else None,
        "attempts": attempts,
        "passed": bool(final.get("passed")),
        "risk_level": str(final.get("risk_level") or "high"),
        "matrix_id": str(final.get("matrix_id") or ""),
        "metrics": dict(final.get("metrics") or {}),
        "thresholds": dict(final.get("thresholds") or {}),
        "notes": list(final.get("notes") or []),
    }
