"""Deterministic stereo feature extraction used for scene hint inference."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples

_EPSILON = 1e-12
_DEFAULT_WINDOW_FRAMES = 2_048

_FRONT_STAGE_MAX_AZIMUTH_DEG = 60.0
_ILD_DB_FOR_STAGE_EDGE = 12.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _safe_db(ratio: float) -> float:
    if ratio <= _EPSILON:
        return -120.0
    return 20.0 * math.log10(ratio)


def compute_stereo_width(
    *,
    lr_correlation: float,
    side_mid_ratio_db: float,
) -> tuple[float, float]:
    """Return (width_hint, confidence) from correlation + side/mid ratio.

    Width is normalized to [0, 1], where larger values are wider.
    """
    correlation = _clamp(lr_correlation, -1.0, 1.0)
    corr_wide = _clamp((1.0 - correlation) * 0.5, 0.0, 1.0)

    # -18 dB side/mid is very narrow, +6 dB is very wide.
    side_wide = _clamp((side_mid_ratio_db + 18.0) / 24.0, 0.0, 1.0)

    width_hint = _clamp((0.55 * side_wide) + (0.45 * corr_wide), 0.0, 1.0)

    evidence_strength = max(abs(corr_wide - 0.5), abs(side_wide - 0.5)) * 2.0
    agreement = 1.0 - abs(corr_wide - side_wide)
    confidence = _clamp(
        0.25 + (0.45 * evidence_strength) + (0.30 * agreement),
        0.0,
        1.0,
    )
    return round(width_hint, 3), round(confidence, 3)


def compute_azimuth_hint(
    *,
    ild_db_windows: Sequence[float],
    window_weights: Sequence[float],
) -> tuple[float, float, float]:
    """Return (azimuth_deg_hint, confidence, weighted_ild_db)."""
    if not ild_db_windows or len(ild_db_windows) != len(window_weights):
        return 0.0, 0.0, 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    weighted_abs_sum = 0.0
    active_windows = 0

    for ild_db, raw_weight in zip(ild_db_windows, window_weights):
        weight = float(raw_weight)
        if weight <= 0.0:
            continue
        active_windows += 1
        weighted_sum += float(ild_db) * weight
        weighted_abs_sum += abs(float(ild_db)) * weight
        weight_total += weight

    if active_windows == 0 or weight_total <= 0.0:
        return 0.0, 0.0, 0.0

    weighted_ild_db = weighted_sum / weight_total
    weighted_abs_ild_db = weighted_abs_sum / weight_total

    azimuth_deg = _clamp(
        (weighted_ild_db / _ILD_DB_FOR_STAGE_EDGE) * _FRONT_STAGE_MAX_AZIMUTH_DEG,
        -_FRONT_STAGE_MAX_AZIMUTH_DEG,
        _FRONT_STAGE_MAX_AZIMUTH_DEG,
    )
    if weighted_abs_ild_db <= _EPSILON:
        directional_consistency = 1.0
    else:
        directional_consistency = _clamp(
            abs(weighted_ild_db) / (weighted_abs_ild_db + _EPSILON),
            0.0,
            1.0,
        )
    magnitude_score = _clamp(weighted_abs_ild_db / 6.0, 0.0, 1.0)
    window_factor = _clamp(active_windows / 4.0, 0.0, 1.0)

    confidence = _clamp(
        (0.20 + (0.45 * directional_consistency) + (0.35 * magnitude_score))
        * window_factor,
        0.0,
        1.0,
    )

    return round(azimuth_deg, 3), round(confidence, 3), round(weighted_ild_db, 6)


def _append_ild_window(
    *,
    window_l2: float,
    window_r2: float,
    window_frames: int,
    ild_windows: list[float],
    window_weights: list[float],
) -> None:
    if window_frames <= 0:
        return

    rms_l = math.sqrt(window_l2 / window_frames) if window_l2 > 0.0 else 0.0
    rms_r = math.sqrt(window_r2 / window_frames) if window_r2 > 0.0 else 0.0
    energy = window_l2 + window_r2
    if energy <= _EPSILON:
        return

    ild_db = _safe_db((rms_l + _EPSILON) / (rms_r + _EPSILON))
    ild_windows.append(ild_db)
    window_weights.append(energy)


def infer_stereo_hints(
    path: Path,
    *,
    window_frames: int = _DEFAULT_WINDOW_FRAMES,
) -> dict[str, Any]:
    """Compute deterministic stereo placement hints for a WAV file."""
    metadata = read_wav_metadata(path)
    channels = metadata.get("channels")
    if channels != 2:
        raise ValueError(f"Stereo hint extraction requires 2 channels, got {channels}")

    window_size = max(128, int(window_frames))

    frame_count = 0
    sum_l2 = 0.0
    sum_r2 = 0.0
    sum_lr = 0.0
    sum_mid2 = 0.0
    sum_side2 = 0.0

    window_l2 = 0.0
    window_r2 = 0.0
    window_count = 0
    ild_windows: list[float] = []
    window_weights: list[float] = []

    for chunk in iter_wav_float64_samples(path, error_context="stereo hint inference"):
        total = len(chunk) - (len(chunk) % 2)
        for index in range(0, total, 2):
            left = float(chunk[index])
            right = float(chunk[index + 1])
            frame_count += 1

            left_sq = left * left
            right_sq = right * right
            sum_l2 += left_sq
            sum_r2 += right_sq
            sum_lr += left * right

            mid = 0.5 * (left + right)
            side = 0.5 * (left - right)
            sum_mid2 += mid * mid
            sum_side2 += side * side

            window_l2 += left_sq
            window_r2 += right_sq
            window_count += 1
            if window_count >= window_size:
                _append_ild_window(
                    window_l2=window_l2,
                    window_r2=window_r2,
                    window_frames=window_count,
                    ild_windows=ild_windows,
                    window_weights=window_weights,
                )
                window_l2 = 0.0
                window_r2 = 0.0
                window_count = 0

    if window_count > 0:
        _append_ild_window(
            window_l2=window_l2,
            window_r2=window_r2,
            window_frames=window_count,
            ild_windows=ild_windows,
            window_weights=window_weights,
        )

    if frame_count <= 0:
        return {
            "width_hint": 0.0,
            "azimuth_deg_hint": 0.0,
            "confidence": 0.0,
            "metrics": {
                "lr_correlation": 0.0,
                "side_mid_ratio_db": -120.0,
                "ild_weighted_db": 0.0,
                "active_windows": 0,
            },
        }

    denom = math.sqrt(max(sum_l2, _EPSILON) * max(sum_r2, _EPSILON))
    correlation = sum_lr / denom if denom > 0.0 else 0.0
    correlation = _clamp(correlation, -1.0, 1.0)

    side_mid_ratio_db = _safe_db(
        math.sqrt((sum_side2 + _EPSILON) / (sum_mid2 + _EPSILON))
    )

    width_hint, width_confidence = compute_stereo_width(
        lr_correlation=correlation,
        side_mid_ratio_db=side_mid_ratio_db,
    )
    azimuth_deg_hint, azimuth_confidence, ild_weighted_db = compute_azimuth_hint(
        ild_db_windows=ild_windows,
        window_weights=window_weights,
    )

    rms_total = math.sqrt((sum_l2 + sum_r2) / (2.0 * frame_count))
    energy_confidence = _clamp((rms_total - 1e-4) / 0.02, 0.0, 1.0)
    combined_confidence = _clamp(
        (0.6 * width_confidence + 0.4 * azimuth_confidence)
        * (0.3 + (0.7 * energy_confidence)),
        0.0,
        1.0,
    )

    return {
        "width_hint": round(width_hint, 3),
        "azimuth_deg_hint": round(azimuth_deg_hint, 3),
        "confidence": round(combined_confidence, 3),
        "metrics": {
            "lr_correlation": round(correlation, 6),
            "side_mid_ratio_db": round(side_mid_ratio_db, 6),
            "ild_weighted_db": round(ild_weighted_db, 6),
            "active_windows": len(ild_windows),
        },
    }
