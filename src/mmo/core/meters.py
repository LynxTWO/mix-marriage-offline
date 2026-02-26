from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

_EPSILON = 1e-12

_DEFAULT_TRANSLATION_CURVES_DB: dict[str, dict[float, float]] = {
    "stereo": {
        63.0: 0.0,
        125.0: 0.0,
        250.0: 0.0,
        500.0: 0.0,
        1000.0: 0.0,
        2000.0: 0.0,
        4000.0: 0.0,
        8000.0: 0.0,
    },
    "mono": {
        63.0: -0.6,
        125.0: -0.4,
        250.0: -0.2,
        500.0: -0.1,
        1000.0: 0.0,
        2000.0: 0.0,
        4000.0: -0.2,
        8000.0: -0.4,
    },
    "earbuds": {
        63.0: -3.0,
        125.0: -2.0,
        250.0: -1.0,
        500.0: -0.4,
        1000.0: 0.0,
        2000.0: 0.6,
        4000.0: 1.0,
        8000.0: 0.8,
    },
    "car": {
        63.0: 2.0,
        125.0: 1.5,
        250.0: 0.8,
        500.0: 0.1,
        1000.0: 0.0,
        2000.0: -0.3,
        4000.0: -0.7,
        8000.0: -1.2,
    },
}

_TRANSLATION_CURVE_ALIASES: dict[str, str] = {
    "stereo": "stereo",
    "trans.device.stereo": "stereo",
    "trans.device.2_0": "stereo",
    "mono": "mono",
    "trans.mono.collapse": "mono",
    "earbuds": "earbuds",
    "trans.device.earbuds": "earbuds",
    "car": "car",
    "trans.device.car": "car",
}


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    sorted_values = sorted(float(value) for value in values)
    clamped = min(100.0, max(0.0, float(percentile)))
    pos = (clamped / 100.0) * (len(sorted_values) - 1)
    lower_index = int(math.floor(pos))
    upper_index = int(math.ceil(pos))
    if lower_index == upper_index:
        return sorted_values[lower_index]
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    blend = pos - lower_index
    return lower + (upper - lower) * blend


def compute_lra_lu(short_term_lufs_values: Sequence[float]) -> float | None:
    gated = [float(value) for value in short_term_lufs_values if float(value) >= -70.0]
    if not gated:
        return None

    energies = [10.0 ** ((value + 0.691) / 10.0) for value in gated]
    mean_energy = sum(energies) / float(len(energies))
    if mean_energy <= _EPSILON:
        return None

    relative_gate = (-0.691 + 10.0 * math.log10(mean_energy)) - 20.0
    gated = [value for value in gated if value >= relative_gate]
    if not gated:
        return None
    if len(gated) == 1:
        return 0.0

    p10 = _percentile(gated, 10.0)
    p95 = _percentile(gated, 95.0)
    if p10 is None or p95 is None:
        return None
    return max(0.0, float(p95 - p10))


def _dbtp_from_peak(peak_linear: float) -> float | None:
    if peak_linear <= _EPSILON:
        return None
    return 20.0 * math.log10(peak_linear)


def _interpolated_channel_peak(samples: Sequence[float], *, upsample: int) -> float:
    if not samples:
        return 0.0
    peak = max(abs(float(value)) for value in samples)
    if len(samples) < 2 or upsample <= 1:
        return peak
    for index in range(len(samples) - 1):
        start = float(samples[index])
        end = float(samples[index + 1])
        delta = (end - start) / float(upsample)
        for step in range(1, upsample):
            candidate = abs(start + (delta * step))
            if candidate > peak:
                peak = candidate
    return peak


def compute_true_peak_per_channel_dbtp(
    interleaved_samples: Sequence[float],
    *,
    channels: int,
    channel_labels: Sequence[str] | None = None,
    upsample: int = 4,
) -> dict[str, float | None]:
    if channels <= 0:
        raise ValueError("channels must be >= 1")
    if upsample <= 0:
        raise ValueError("upsample must be >= 1")

    labels: list[str] = []
    if channel_labels is not None:
        labels = [str(label).strip() for label in channel_labels][:channels]
    while len(labels) < channels:
        labels.append(f"CH{len(labels) + 1}")

    channel_samples: list[list[float]] = [[] for _ in range(channels)]
    for index, sample in enumerate(interleaved_samples):
        channel_samples[index % channels].append(float(sample))

    result: dict[str, float | None] = {}
    for channel_index, label in enumerate(labels):
        peak = _interpolated_channel_peak(channel_samples[channel_index], upsample=upsample)
        result[label] = _dbtp_from_peak(peak)
    return result


def normalize_translation_curve_id(profile_id: str) -> str | None:
    key = str(profile_id or "").strip().lower()
    if not key:
        return None
    return _TRANSLATION_CURVE_ALIASES.get(key)


def translation_curve_reference(profile_id: str) -> dict[float, float]:
    normalized = normalize_translation_curve_id(profile_id)
    if normalized is None:
        known = ", ".join(sorted(_DEFAULT_TRANSLATION_CURVES_DB.keys()))
        raise ValueError(f"Unknown translation curve profile: {profile_id!r}. Known: {known}")
    return dict(_DEFAULT_TRANSLATION_CURVES_DB[normalized])


def _to_float_map(values: Mapping[Any, Any]) -> dict[float, float]:
    parsed: dict[float, float] = {}
    for key, value in values.items():
        try:
            freq_hz = float(key)
            level_db = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(freq_hz) or not math.isfinite(level_db):
            continue
        parsed[freq_hz] = level_db
    return parsed


def compute_translation_curve_delta_db(
    measured_levels_db: Mapping[Any, Any],
    *,
    profile_id: str,
) -> float | None:
    measured = _to_float_map(measured_levels_db)
    reference = translation_curve_reference(profile_id)
    common_freqs = sorted(set(reference.keys()) & set(measured.keys()))
    if not common_freqs:
        return None
    diffs = [abs(measured[freq] - reference[freq]) for freq in common_freqs]
    return sum(diffs) / float(len(diffs))


def assess_translation_curves(
    measured_levels_db: Mapping[Any, Any],
    *,
    profile_ids: Sequence[str] = ("stereo", "mono", "earbuds", "car"),
    warn_delta_db: float = 2.5,
    error_delta_db: float = 4.0,
) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    max_delta: float | None = None

    for profile_id in profile_ids:
        normalized = normalize_translation_curve_id(profile_id)
        if normalized is None:
            continue
        delta = compute_translation_curve_delta_db(
            measured_levels_db,
            profile_id=normalized,
        )
        if delta is not None:
            if max_delta is None or delta > max_delta:
                max_delta = delta
        if delta is None:
            status = "skipped"
        elif delta > error_delta_db:
            status = "high"
        elif delta > warn_delta_db:
            status = "medium"
        else:
            status = "low"
        profiles.append(
            {
                "profile_id": normalized,
                "delta_db": None if delta is None else round(delta, 6),
                "status": status,
            }
        )

    profiles.sort(key=lambda item: str(item.get("profile_id", "")))
    return {
        "profiles": profiles,
        "max_delta_db": None if max_delta is None else round(max_delta, 6),
    }
