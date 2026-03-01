from __future__ import annotations

import math
from typing import Any, Sequence

from mmo.dsp.downmix import _design_biquad

PHASE_DELTA_THRESHOLD_DB = 0.1
_ENERGY_EPSILON = 1e-15
_STAGE_SLOPE_DB_PER_OCT = 12.0
_VALID_LFE_MODES = frozenset({"mono", "stereo"})


def _coerce_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _VALID_LFE_MODES else "mono"


def _trim_to_shortest(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[list[float], list[float]]:
    clean_left = [float(sample) for sample in left]
    clean_right = [float(sample) for sample in right]
    length = min(len(clean_left), len(clean_right))
    return clean_left[:length], clean_right[:length]


def _lowpass(
    samples: Sequence[float],
    *,
    sample_rate_hz: int,
    cutoff_hz: float,
    slope_db_per_oct: int,
) -> list[float]:
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    stage_count = max(1, int(round(abs(float(slope_db_per_oct)) / _STAGE_SLOPE_DB_PER_OCT)))
    chain = [
        _design_biquad("lowpass", float(cutoff_hz), int(sample_rate_hz))
        for _ in range(stage_count)
    ]
    output: list[float] = []
    for sample in samples:
        value = float(sample)
        for biquad in chain:
            value = biquad.process(value)
        output.append(value)
    return output


def _mean_square(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    accumulator = 0.0
    for sample in samples:
        value = float(sample)
        accumulator += value * value
    return accumulator / float(len(samples))


def _energy_db(samples: Sequence[float]) -> float:
    return 10.0 * math.log10(max(_mean_square(samples), _ENERGY_EPSILON))


def _apply_gain(samples: Sequence[float], *, gain_db: float) -> list[float]:
    linear = 10.0 ** (float(gain_db) / 20.0)
    return [float(sample) * linear for sample in samples]


def _mirror_mono(samples: Sequence[float], count: int) -> list[list[float]]:
    channel = [float(sample) for sample in samples]
    return [list(channel) for _ in range(count)]


def derive_missing_lfe(
    *,
    left: Sequence[float],
    right: Sequence[float],
    sample_rate_hz: int,
    target_lfe_channel_count: int,
    profile: dict[str, Any],
    lfe_mode: str = "mono",
    delta_threshold_db: float = PHASE_DELTA_THRESHOLD_DB,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Derive deterministic LFE channel content from LR program audio.

    Returns ``(lfe_channels, receipt)`` where ``lfe_channels`` is a list of mono
    channels (length equals ``target_lfe_channel_count``) and ``receipt`` records
    the chosen derivation mode and phase-maximization decision.
    """
    if target_lfe_channel_count <= 0:
        return [], {
            "status": "not_applicable",
            "derivation_applied": False,
            "derivation_ran": False,
            "derivation_reason": "target_layout_has_no_lfe_channels",
            "profile_id": str(profile.get("lfe_derivation_profile_id") or ""),
            "profile_lowpass_hz": None,
            "profile_slope_db_per_oct": None,
            "profile_trim_db": None,
            "lfe_mode": _coerce_mode(lfe_mode),
            "target_lfe_channel_count": 0,
            "chosen_sum_mode": "not_applicable",
            "delta_db": 0.0,
            "delta_threshold_db": float(delta_threshold_db),
        }

    mode = _coerce_mode(lfe_mode)
    cutoff_hz = float(profile.get("lowpass_hz") or 120.0)
    slope_db_per_oct = int(profile.get("slope_db_per_oct") or 24)
    trim_db = float(profile.get("gain_trim_db") or -10.0)
    profile_id = str(profile.get("lfe_derivation_profile_id") or "").strip()

    left_samples, right_samples = _trim_to_shortest(left, right)
    derivation_ran = bool(left_samples and right_samples)
    if not derivation_ran:
        empty_channels = [[] for _ in range(target_lfe_channel_count)]
        return empty_channels, {
            "status": "derived",
            "derivation_applied": True,
            "derivation_ran": False,
            "derivation_reason": "no_lr_samples_available_for_phase_test",
            "profile_id": profile_id,
            "profile_lowpass_hz": cutoff_hz,
            "profile_slope_db_per_oct": slope_db_per_oct,
            "profile_trim_db": trim_db,
            "lfe_mode": mode,
            "target_lfe_channel_count": int(target_lfe_channel_count),
            "chosen_sum_mode": "L+R",
            "delta_db": 0.0,
            "delta_threshold_db": float(delta_threshold_db),
        }

    low_left = _lowpass(
        left_samples,
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=cutoff_hz,
        slope_db_per_oct=slope_db_per_oct,
    )
    low_right = _lowpass(
        right_samples,
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=cutoff_hz,
        slope_db_per_oct=slope_db_per_oct,
    )

    threshold = float(delta_threshold_db)

    if mode == "stereo" and target_lfe_channel_count >= 2:
        default_mono_sum = [l + r for l, r in zip(low_left, low_right)]
        flipped_mono_sum = [l - r for l, r in zip(low_left, low_right)]
        default_energy_db = _energy_db(default_mono_sum)
        flipped_energy_db = _energy_db(flipped_mono_sum)
        delta_db = abs(flipped_energy_db - default_energy_db)
        flip_right = delta_db >= threshold and flipped_energy_db > default_energy_db

        out_left = _apply_gain(low_left, gain_db=trim_db)
        if flip_right:
            out_right_source = [-sample for sample in low_right]
        else:
            out_right_source = list(low_right)
        out_right = _apply_gain(out_right_source, gain_db=trim_db)

        channels: list[list[float]] = [out_left, out_right]
        while len(channels) < target_lfe_channel_count:
            channels.append(list(out_left if len(channels) % 2 == 0 else out_right))

        return channels, {
            "status": "derived",
            "derivation_applied": True,
            "derivation_ran": True,
            "derivation_reason": "target_layout_has_lfe_without_source_lfe_program_content",
            "profile_id": profile_id,
            "profile_lowpass_hz": cutoff_hz,
            "profile_slope_db_per_oct": slope_db_per_oct,
            "profile_trim_db": trim_db,
            "lfe_mode": mode,
            "target_lfe_channel_count": int(target_lfe_channel_count),
            "chosen_sum_mode": "flipped R" if flip_right else "L+R",
            "delta_db": float(round(delta_db, 6)),
            "delta_threshold_db": threshold,
        }

    # Fallback to mono for all single-LFE targets or explicitly mono mode.
    mono_sum = [l + r for l, r in zip(low_left, low_right)]
    mono_diff = [l - r for l, r in zip(low_left, low_right)]
    sum_energy_db = _energy_db(mono_sum)
    diff_energy_db = _energy_db(mono_diff)
    delta_db = abs(diff_energy_db - sum_energy_db)
    use_diff = delta_db >= threshold and diff_energy_db > sum_energy_db
    chosen_mode = "L-R" if use_diff else "L+R"
    chosen = mono_diff if use_diff else mono_sum
    trimmed = _apply_gain(chosen, gain_db=trim_db)

    return _mirror_mono(trimmed, int(target_lfe_channel_count)), {
        "status": "derived",
        "derivation_applied": True,
        "derivation_ran": True,
        "derivation_reason": "target_layout_has_lfe_without_source_lfe_program_content",
        "profile_id": profile_id,
        "profile_lowpass_hz": cutoff_hz,
        "profile_slope_db_per_oct": slope_db_per_oct,
        "profile_trim_db": trim_db,
        "lfe_mode": mode,
        "target_lfe_channel_count": int(target_lfe_channel_count),
        "chosen_sum_mode": chosen_mode,
        "delta_db": float(round(delta_db, 6)),
        "delta_threshold_db": threshold,
    }
