from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

DEFAULT_WINDOW_SIZE = 2048
DEFAULT_HOP_SIZE = 1024
DEFAULT_LOW_HZ = 300.0
DEFAULT_HIGH_HZ = 3000.0
DEFAULT_TOP_N = 3
_EPSILON = 1e-12


def _window_count(length: int, window_size: int, hop_size: int) -> int:
    if length <= 0:
        return 0
    if length <= window_size:
        return 1
    return 1 + (length - window_size) // hop_size


def _window_slice(samples: np.ndarray, start: int, size: int) -> np.ndarray:
    chunk = samples[start : start + size]
    if chunk.size == size:
        return chunk
    padded = np.zeros(size, dtype=np.float64)
    if chunk.size:
        padded[: chunk.size] = chunk
    return padded


def _best_time_range(
    scores: np.ndarray,
    weights: np.ndarray,
    *,
    hop_size: int,
    window_size: int,
    sample_rate_hz: int,
) -> tuple[float, float]:
    if scores.size == 0:
        return 0.0, 0.0
    weighted = scores * np.maximum(weights, 0.0)
    if np.max(weighted) <= 0.0:
        best_index = int(np.argmax(scores))
    else:
        best_index = int(np.argmax(weighted))

    peak_score = float(scores[best_index])
    threshold = peak_score * 0.9
    start = best_index
    end = best_index

    while start > 0 and scores[start - 1] >= threshold:
        start -= 1
    while end + 1 < scores.size and scores[end + 1] >= threshold:
        end += 1

    start_s = (start * hop_size) / float(sample_rate_hz)
    end_s = (end * hop_size + window_size) / float(sample_rate_hz)
    return start_s, end_s


def compute_masking_risk(
    stems: Iterable[dict[str, Any]],
    *,
    sample_rate_hz: int,
    window_size: int = DEFAULT_WINDOW_SIZE,
    hop_size: int = DEFAULT_HOP_SIZE,
    low_hz: float = DEFAULT_LOW_HZ,
    high_hz: float = DEFAULT_HIGH_HZ,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Compute deterministic spectral overlap risk between stem pairs."""
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if window_size <= 0 or hop_size <= 0:
        raise ValueError("window_size and hop_size must be positive")
    if low_hz < 0.0 or high_hz <= low_hz:
        raise ValueError("Invalid masking band")

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

    if len(normalized) < 2:
        return {
            "top_pairs": [],
            "pair_count": 0,
            "window_size": window_size,
            "hop_size": hop_size,
            "mid_band_hz": {"low_hz": low_hz, "high_hz": high_hz},
        }

    window = np.hanning(window_size).astype(np.float64)
    freqs = np.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
    band_mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not np.any(band_mask):
        return {
            "top_pairs": [],
            "pair_count": 0,
            "window_size": window_size,
            "hop_size": hop_size,
            "mid_band_hz": {"low_hz": low_hz, "high_hz": high_hz},
        }

    pairs: list[dict[str, Any]] = []
    for index_a, stem_a in enumerate(normalized):
        for stem_b in normalized[index_a + 1 :]:
            samples_a = stem_a["samples"]
            samples_b = stem_b["samples"]
            length = min(int(samples_a.size), int(samples_b.size))
            window_count = _window_count(length, window_size, hop_size)
            if window_count == 0:
                continue

            scores = np.zeros(window_count, dtype=np.float64)
            weights = np.zeros(window_count, dtype=np.float64)
            for window_index in range(window_count):
                start = window_index * hop_size
                chunk_a = _window_slice(samples_a, start, window_size) * window
                chunk_b = _window_slice(samples_b, start, window_size) * window
                spectrum_a = np.fft.rfft(chunk_a)
                spectrum_b = np.fft.rfft(chunk_b)
                band_a = np.abs(spectrum_a[band_mask])
                band_b = np.abs(spectrum_b[band_mask])

                energy_a = float(np.dot(band_a, band_a))
                energy_b = float(np.dot(band_b, band_b))
                if energy_a <= _EPSILON or energy_b <= _EPSILON:
                    continue

                dot_value = float(np.dot(band_a, band_b))
                score = dot_value / (math.sqrt(energy_a * energy_b) + _EPSILON)
                score = max(0.0, min(1.0, score))
                weight = math.sqrt(energy_a * energy_b)

                scores[window_index] = score
                weights[window_index] = weight

            if float(np.sum(weights)) > _EPSILON:
                pair_score = float(np.sum(scores * weights) / np.sum(weights))
            else:
                pair_score = float(np.mean(scores))

            start_s, end_s = _best_time_range(
                scores,
                weights,
                hop_size=hop_size,
                window_size=window_size,
                sample_rate_hz=sample_rate_hz,
            )
            pairs.append(
                {
                    "stem_a": stem_a["stem_id"],
                    "stem_b": stem_b["stem_id"],
                    "score": pair_score,
                    "start_s": round(start_s, 6),
                    "end_s": round(end_s, 6),
                    "window_count": int(window_count),
                }
            )

    pairs.sort(
        key=lambda item: (
            -float(item.get("score", 0.0)),
            str(item.get("stem_a", "")),
            str(item.get("stem_b", "")),
        )
    )
    top_count = max(0, int(top_n))
    top_pairs = pairs[:top_count]

    return {
        "top_pairs": top_pairs,
        "pair_count": len(pairs),
        "window_size": window_size,
        "hop_size": hop_size,
        "mid_band_hz": {"low_hz": low_hz, "high_hz": high_hz},
    }
