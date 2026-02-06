from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

DEFAULT_BANDS_HZ: tuple[tuple[float, float], ...] = (
    (40.0, 80.0),
    (80.0, 160.0),
    (160.0, 320.0),
    (320.0, 640.0),
    (640.0, 1280.0),
    (1280.0, 2560.0),
    (2560.0, 5120.0),
)
DEFAULT_WINDOW_SIZE = 2048
DEFAULT_HOP_SIZE = 1024
DEFAULT_RMS_THRESHOLD_DBFS = -45.0
DEFAULT_MAX_TIMELINE_POINTS = 200
_EPSILON = 1e-12


def _window_count(max_length: int, window_size: int, hop_size: int) -> int:
    if max_length <= 0:
        return 0
    if max_length <= window_size:
        return 1
    return 1 + (max_length - window_size) // hop_size


def _window_slice(samples: np.ndarray, start: int, size: int) -> np.ndarray:
    chunk = samples[start : start + size]
    if chunk.size == size:
        return chunk
    padded = np.zeros(size, dtype=np.float64)
    if chunk.size:
        padded[: chunk.size] = chunk
    return padded


def _band_bin_masks(
    sample_rate_hz: int,
    window_size: int,
    bands_hz: Sequence[tuple[float, float]],
) -> list[np.ndarray]:
    freqs = np.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
    masks: list[np.ndarray] = []
    for low_hz, high_hz in bands_hz:
        mask = (freqs >= low_hz) & (freqs < high_hz)
        masks.append(mask)
    return masks


def compute_mix_density(
    stems: Iterable[dict[str, Any]],
    *,
    sample_rate_hz: int,
    window_size: int = DEFAULT_WINDOW_SIZE,
    hop_size: int = DEFAULT_HOP_SIZE,
    rms_threshold_dbfs: float = DEFAULT_RMS_THRESHOLD_DBFS,
    max_timeline_points: int = DEFAULT_MAX_TIMELINE_POINTS,
    bands_hz: Sequence[tuple[float, float]] = DEFAULT_BANDS_HZ,
) -> dict[str, Any]:
    """Compute deterministic stem-activity density metrics for a mix."""
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if window_size <= 0 or hop_size <= 0:
        raise ValueError("window_size and hop_size must be positive")

    normalized: list[dict[str, Any]] = []
    for stem in stems:
        stem_id = stem.get("stem_id")
        samples = stem.get("samples")
        if not isinstance(stem_id, str) or not stem_id:
            continue
        if not isinstance(samples, np.ndarray):
            continue
        if samples.ndim != 1:
            continue
        normalized.append({"stem_id": stem_id, "samples": samples.astype(np.float64)})
    normalized.sort(key=lambda item: item["stem_id"])

    if not normalized:
        return {
            "density_mean": 0.0,
            "density_peak": 0,
            "density_timeline": [],
            "timeline_total_windows": 0,
            "timeline_truncated": False,
            "window_size": window_size,
            "hop_size": hop_size,
            "rms_threshold_dbfs": rms_threshold_dbfs,
            "bands_hz": [
                {"low_hz": float(low_hz), "high_hz": float(high_hz)}
                for low_hz, high_hz in bands_hz
            ],
            "stem_count": 0,
        }

    max_length = max(int(item["samples"].size) for item in normalized)
    total_windows = _window_count(max_length, window_size, hop_size)
    if total_windows == 0:
        return {
            "density_mean": 0.0,
            "density_peak": 0,
            "density_timeline": [],
            "timeline_total_windows": 0,
            "timeline_truncated": False,
            "window_size": window_size,
            "hop_size": hop_size,
            "rms_threshold_dbfs": rms_threshold_dbfs,
            "bands_hz": [
                {"low_hz": float(low_hz), "high_hz": float(high_hz)}
                for low_hz, high_hz in bands_hz
            ],
            "stem_count": len(normalized),
        }

    window = np.hanning(window_size).astype(np.float64)
    band_masks = _band_bin_masks(sample_rate_hz, window_size, bands_hz)
    threshold_linear = 10.0 ** (rms_threshold_dbfs / 20.0)

    active_counts = np.zeros(total_windows, dtype=np.int32)
    for stem in normalized:
        samples = stem["samples"]
        for window_index in range(total_windows):
            start = window_index * hop_size
            chunk = _window_slice(samples, start, window_size) * window
            spectrum = np.fft.rfft(chunk)
            power = (spectrum.real * spectrum.real) + (spectrum.imag * spectrum.imag)

            is_active = False
            for mask in band_masks:
                if not np.any(mask):
                    continue
                band_power = float(np.mean(power[mask]))
                if band_power <= 0.0:
                    continue
                band_rms = math.sqrt(max(band_power, 0.0))
                if band_rms >= threshold_linear + _EPSILON:
                    is_active = True
                    break

            if is_active:
                active_counts[window_index] += 1

    density_mean = float(np.mean(active_counts)) if active_counts.size else 0.0
    density_peak = int(np.max(active_counts)) if active_counts.size else 0

    timeline_limit = max(0, int(max_timeline_points))
    include_windows = min(total_windows, timeline_limit)
    timeline: list[dict[str, Any]] = []
    for window_index in range(include_windows):
        start_s = (window_index * hop_size) / float(sample_rate_hz)
        end_s = (window_index * hop_size + window_size) / float(sample_rate_hz)
        timeline.append(
            {
                "start_s": round(start_s, 6),
                "end_s": round(end_s, 6),
                "active_stems": int(active_counts[window_index]),
            }
        )

    return {
        "density_mean": density_mean,
        "density_peak": density_peak,
        "density_timeline": timeline,
        "timeline_total_windows": total_windows,
        "timeline_truncated": include_windows < total_windows,
        "window_size": window_size,
        "hop_size": hop_size,
        "rms_threshold_dbfs": rms_threshold_dbfs,
        "bands_hz": [
            {"low_hz": float(low_hz), "high_hz": float(high_hz)}
            for low_hz, high_hz in bands_hz
        ],
        "stem_count": len(normalized),
    }
