"""Build deterministic render_qa payloads for executed render-run jobs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterator, Sequence

from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import detect_format_from_path, read_metadata
from mmo.dsp.io import sha256_file
from mmo.dsp.meters import compute_basic_stats_from_float64, iter_wav_float64_samples

__all__ = [
    "build_render_qa_payload",
    "render_qa_has_error_issues",
]

_WAV_EXTENSIONS = frozenset({".wav", ".wave"})
_STEREO_CHANNELS = 2
_EPSILON = 1e-12
_SHORT_TERM_WINDOW_SECONDS = 3.0
_SHORT_TERM_HOP_SECONDS = 1.0
_SPECTRAL_WINDOW_SIZE = 4096
_SPECTRAL_HOP_SIZE = 2048

_SPECTRAL_BAND_CENTERS_HZ: tuple[float, ...] = (
    16.0,
    20.0,
    25.0,
    31.5,
    40.0,
    50.0,
    63.0,
    80.0,
    100.0,
    125.0,
    160.0,
    200.0,
    250.0,
    315.0,
    400.0,
    500.0,
    630.0,
    800.0,
    1000.0,
    1250.0,
    1600.0,
    2000.0,
    2500.0,
    3150.0,
    4000.0,
    5000.0,
    6300.0,
    8000.0,
    10000.0,
    12500.0,
    16000.0,
    20000.0,
)

_SPECTRAL_SECTION_RANGES: dict[str, tuple[float, float]] = {
    "sub_bass_low_end": (16.0, 160.0),
    "low_midrange": (200.0, 800.0),
    "midrange_high_mid": (1000.0, 4000.0),
    "highs_treble": (5000.0, 20000.0),
}

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "polarity_error_correlation_lte": -0.6,
    "correlation_warn_lte": -0.2,
    "true_peak_warn_dbtp_gt": -2.0,
    "true_peak_error_dbtp_gt": -1.0,
    "lra_warn_lu_lte": 1.5,
    "lra_warn_lu_gte": 18.0,
    "lra_error_lu_gte": 24.0,
    "plugin_delta_lufs_warn_abs": 2.0,
    "plugin_delta_lufs_error_abs": 4.0,
    "plugin_delta_crest_warn_abs": 3.0,
    "plugin_delta_crest_error_abs": 6.0,
}

_SEVERITY_ORDER: dict[str, int] = {
    "error": 0,
    "warn": 1,
    "info": 2,
}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
    if isinstance(value, str) and value.strip():
        try:
            candidate = float(value)
        except ValueError:
            return None
        if math.isfinite(candidate):
            return candidate
    return None


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return round(float(value), digits)


def _linear_to_db(value: float) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return round(20.0 * math.log10(float(value)), 4)


def _power_to_db(value: float) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return round(10.0 * math.log10(float(value)), 4)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_id(*, request_sha256: str, plan_sha256: str) -> str:
    material = f"{request_sha256}:{plan_sha256}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"RUN.{digest[:16]}"


def _normalize_paths(raw_paths: Any) -> list[Path]:
    if not isinstance(raw_paths, list):
        return []
    normalized: dict[str, Path] = {}
    for value in raw_paths:
        if isinstance(value, Path):
            resolved = value.resolve()
        elif isinstance(value, str) and value.strip():
            resolved = Path(value.strip()).resolve()
        else:
            continue
        normalized.setdefault(resolved.as_posix(), resolved)
    return [normalized[key] for key in sorted(normalized.keys())]


def _empty_metrics() -> dict[str, Any]:
    return {
        "peak_dbfs": None,
        "rms_dbfs": None,
        "integrated_lufs": None,
        "short_term_lufs_p10": None,
        "short_term_lufs_p50": None,
        "short_term_lufs_p90": None,
        "loudness_range_lu": None,
        "crest_factor_db": None,
        "true_peak_dbtp": None,
        "clip_sample_count": None,
        "intersample_over_count": None,
        "dc_offset": None,
        "correlation_lr": None,
        "mid_rms_dbfs": None,
        "side_rms_dbfs": None,
        "side_mid_ratio_db": None,
        "mono_rms_dbfs": None,
    }


def _empty_spectral() -> dict[str, Any]:
    return {
        "centers_hz": [float(center) for center in _SPECTRAL_BAND_CENTERS_HZ],
        "levels_db": [None for _ in _SPECTRAL_BAND_CENTERS_HZ],
        "tilt_db_per_oct": None,
        "section_tilt_db_per_oct": {
            "sub_bass_low_end": None,
            "low_midrange": None,
            "midrange_high_mid": None,
            "highs_treble": None,
        },
        "adjacent_band_slopes_db_per_oct": [],
        "section_subband_slopes_db_per_oct": {
            "sub_bass_low_end": [],
            "low_midrange": [],
            "midrange_high_mid": [],
            "highs_treble": [],
        },
    }


def _iter_file_samples(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
    error_context: str,
) -> Iterator[list[float]]:
    if path.suffix.lower() in _WAV_EXTENSIONS:
        return iter_wav_float64_samples(path, error_context=error_context)
    if ffmpeg_cmd:
        return iter_ffmpeg_float64_samples(path, ffmpeg_cmd)
    raise ValueError(
        (
            "ffmpeg is required to decode non-WAV files for render QA metrics: "
            f"{path.as_posix()}"
        )
    )


def _optional_numpy() -> Any | None:
    try:
        import numpy as np  # noqa: WPS433
    except ImportError:
        return None
    return np


def _decode_frames_float64(
    *,
    path: Path,
    channels: int,
    ffmpeg_cmd: Sequence[str] | None,
    np_module: Any,
) -> Any:
    blocks: list[Any] = []
    carry: list[float] = []
    for chunk in _iter_file_samples(
        path,
        ffmpeg_cmd=ffmpeg_cmd,
        error_context="render QA decode",
    ):
        merged = carry + chunk
        remainder = len(merged) % channels
        if remainder:
            carry = merged[-remainder:]
            merged = merged[:-remainder]
        else:
            carry = []
        if not merged:
            continue
        block = np_module.asarray(merged, dtype=np_module.float64).reshape(-1, channels)
        blocks.append(block)
    if not blocks:
        return np_module.zeros((0, channels), dtype=np_module.float64)
    return np_module.concatenate(blocks, axis=0)


def _pearson_correlation(left: Any, right: Any, np_module: Any) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    left_centered = left - np_module.mean(left)
    right_centered = right - np_module.mean(right)
    denom = float(
        np_module.sqrt(
            np_module.sum(left_centered * left_centered)
            * np_module.sum(right_centered * right_centered)
        )
    )
    if denom <= 0.0:
        return 0.0
    corr = float(np_module.sum(left_centered * right_centered) / denom)
    if corr > 1.0:
        return 1.0
    if corr < -1.0:
        return -1.0
    return corr


def _mean_rms_db(samples: Any, np_module: Any) -> float | None:
    if samples.size == 0:
        return None
    mean_square = float(np_module.mean(samples * samples))
    if not math.isfinite(mean_square) or mean_square <= 0.0:
        return None
    return _linear_to_db(math.sqrt(mean_square))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    clamped = min(100.0, max(0.0, float(percentile)))
    position = (clamped / 100.0) * (len(sorted_values) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return sorted_values[lower_index]
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    weight = position - lower_index
    return lower_value + (upper_value - lower_value) * weight


def _compute_loudness_range(short_term_lufs_values: list[float]) -> float | None:
    # EBU R128-style LRA from short-term loudness distribution.
    gated = [value for value in short_term_lufs_values if value >= -70.0]
    if not gated:
        return None

    energies = [
        10.0 ** ((value + 0.691) / 10.0)
        for value in gated
    ]
    mean_energy = sum(energies) / float(len(energies))
    if mean_energy <= 0.0:
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
    return max(0.0, p95 - p10)


def _short_term_lufs_distribution(
    *,
    frames: Any,
    sample_rate_hz: int,
    channels: int,
    channel_mask: int | None,
    channel_layout: str | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    if frames.size == 0:
        return (None, None, None, None)

    try:
        from mmo.dsp.meters_truth import compute_lufs_shortterm_float64  # noqa: WPS433
    except (ImportError, ValueError):
        return (None, None, None, None)

    window_frames = int(round(_SHORT_TERM_WINDOW_SECONDS * sample_rate_hz))
    hop_frames = int(round(_SHORT_TERM_HOP_SECONDS * sample_rate_hz))
    if window_frames <= 0 or hop_frames <= 0:
        return (None, None, None, None)

    values: list[float] = []
    if frames.shape[0] < window_frames:
        candidate = compute_lufs_shortterm_float64(
            frames,
            sample_rate_hz,
            channels,
            channel_mask=channel_mask,
            channel_layout=channel_layout,
        )
        if math.isfinite(candidate):
            values.append(float(candidate))
    else:
        for start in range(0, frames.shape[0] - window_frames + 1, hop_frames):
            window = frames[start : start + window_frames, :]
            candidate = compute_lufs_shortterm_float64(
                window,
                sample_rate_hz,
                channels,
                channel_mask=channel_mask,
                channel_layout=channel_layout,
            )
            if math.isfinite(candidate):
                values.append(float(candidate))

    if not values:
        return (None, None, None, None)

    p10 = _percentile(values, 10.0)
    p50 = _percentile(values, 50.0)
    p90 = _percentile(values, 90.0)
    lra = _compute_loudness_range(values)
    return (
        _round_or_none(p10),
        _round_or_none(p50),
        _round_or_none(p90),
        _round_or_none(lra),
    )


def _design_oversample_fir(np_module: Any, *, upsample: int, taps: int) -> Any:
    if taps <= 1 or taps % 2 == 0:
        raise ValueError("taps must be an odd integer >= 3")
    cutoff = 0.5 / float(upsample)
    n = np_module.arange(taps, dtype=np_module.float64)
    center = (taps - 1) / 2.0
    sinc_arg = 2.0 * cutoff * (n - center)
    kernel = 2.0 * cutoff * np_module.sinc(sinc_arg)
    kernel *= np_module.hanning(taps)
    kernel_sum = float(np_module.sum(kernel))
    if abs(kernel_sum) <= _EPSILON:
        raise ValueError("invalid FIR normalization")
    kernel /= kernel_sum
    return kernel


def _compute_intersample_over_count(frames: Any, np_module: Any) -> int | None:
    if frames.size == 0:
        return 0
    upsample = 4
    try:
        kernel = _design_oversample_fir(np_module, upsample=upsample, taps=63)
    except ValueError:
        return None

    over_count = 0
    channels = int(frames.shape[1])
    for channel_index in range(channels):
        channel = frames[:, channel_index]
        upsampled = np_module.zeros(channel.shape[0] * upsample, dtype=np_module.float64)
        upsampled[::upsample] = channel
        filtered = np_module.convolve(upsampled, kernel, mode="same")
        over_count += int(np_module.sum(np_module.abs(filtered) > 1.0))
    return int(over_count)


def _spectral_band_edges(centers_hz: Sequence[float]) -> list[tuple[float, float]]:
    edges: list[tuple[float, float]] = []
    if not centers_hz:
        return edges
    for index, center in enumerate(centers_hz):
        if index == 0:
            low = center / math.sqrt(2.0)
        else:
            low = math.sqrt(centers_hz[index - 1] * center)
        if index == len(centers_hz) - 1:
            high = center * math.sqrt(2.0)
        else:
            high = math.sqrt(center * centers_hz[index + 1])
        edges.append((low, high))
    return edges


def _spectral_tilt_slope(
    frequencies_hz: Sequence[float],
    levels_db: Sequence[float | None],
) -> float | None:
    pairs = [
        (math.log2(freq_hz), float(level_db))
        for freq_hz, level_db in zip(frequencies_hz, levels_db)
        if freq_hz > 0.0 and level_db is not None and math.isfinite(level_db)
    ]
    if len(pairs) < 2:
        return None
    x_mean = sum(item[0] for item in pairs) / float(len(pairs))
    y_mean = sum(item[1] for item in pairs) / float(len(pairs))
    variance = sum((item[0] - x_mean) ** 2 for item in pairs)
    if variance <= 0.0:
        return None
    covariance = sum((item[0] - x_mean) * (item[1] - y_mean) for item in pairs)
    return covariance / variance


def _band_pair_slope_db_per_oct(
    *,
    low_hz: float,
    high_hz: float,
    low_level_db: float | None,
    high_level_db: float | None,
) -> float | None:
    if (
        low_hz <= 0.0
        or high_hz <= 0.0
        or high_hz <= low_hz
        or low_level_db is None
        or high_level_db is None
    ):
        return None
    if not math.isfinite(low_level_db) or not math.isfinite(high_level_db):
        return None
    octaves = math.log2(high_hz / low_hz)
    if abs(octaves) <= _EPSILON:
        return None
    return round((high_level_db - low_level_db) / octaves, 4)


def _adjacent_band_slopes(
    *,
    centers_hz: Sequence[float],
    levels_db: Sequence[float | None],
) -> list[dict[str, Any]]:
    slopes: list[dict[str, Any]] = []
    for index in range(len(centers_hz) - 1):
        low_hz = float(centers_hz[index])
        high_hz = float(centers_hz[index + 1])
        slope = _band_pair_slope_db_per_oct(
            low_hz=low_hz,
            high_hz=high_hz,
            low_level_db=levels_db[index],
            high_level_db=levels_db[index + 1],
        )
        slopes.append(
            {
                "low_hz": low_hz,
                "high_hz": high_hz,
                "slope_db_per_oct": slope,
            }
        )
    return slopes


def _section_subband_slopes(
    *,
    centers_hz: Sequence[float],
    levels_db: Sequence[float | None],
) -> dict[str, list[dict[str, Any]]]:
    all_slopes = _adjacent_band_slopes(centers_hz=centers_hz, levels_db=levels_db)
    section_payload: dict[str, list[dict[str, Any]]] = {}
    for section_id, (low_hz, high_hz) in _SPECTRAL_SECTION_RANGES.items():
        section_rows: list[dict[str, Any]] = []
        for row in all_slopes:
            row_low_hz = _coerce_float(row.get("low_hz"))
            row_high_hz = _coerce_float(row.get("high_hz"))
            if row_low_hz is None or row_high_hz is None:
                continue
            if row_low_hz < low_hz or row_high_hz > high_hz:
                continue
            section_rows.append(
                {
                    "low_hz": row_low_hz,
                    "high_hz": row_high_hz,
                    "slope_db_per_oct": row.get("slope_db_per_oct"),
                }
            )
        section_payload[section_id] = section_rows
    return section_payload


def _compute_spectral_metrics(frames: Any, *, sample_rate_hz: int, np_module: Any) -> dict[str, Any]:
    spectral = _empty_spectral()
    if frames.size == 0 or sample_rate_hz <= 0:
        return spectral

    mono = np_module.mean(frames, axis=1)
    if mono.size == 0:
        return spectral

    window_size = _SPECTRAL_WINDOW_SIZE
    hop_size = _SPECTRAL_HOP_SIZE
    if mono.shape[0] < window_size:
        window_size = min(window_size, max(256, mono.shape[0]))
        hop_size = max(1, window_size // 2)

    if window_size <= 1:
        return spectral

    if mono.shape[0] <= window_size:
        total_windows = 1
    else:
        total_windows = 1 + (mono.shape[0] - window_size) // hop_size

    window = np_module.hanning(window_size).astype(np_module.float64)
    freqs = np_module.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
    band_edges = _spectral_band_edges(_SPECTRAL_BAND_CENTERS_HZ)
    band_masks = [
        (freqs >= low_hz) & (freqs < high_hz)
        for low_hz, high_hz in band_edges
    ]
    band_power = np_module.zeros(len(_SPECTRAL_BAND_CENTERS_HZ), dtype=np_module.float64)
    band_counts = np_module.zeros(len(_SPECTRAL_BAND_CENTERS_HZ), dtype=np_module.int64)

    for window_index in range(total_windows):
        start = window_index * hop_size
        chunk = mono[start : start + window_size]
        if chunk.shape[0] < window_size:
            padded = np_module.zeros(window_size, dtype=np_module.float64)
            padded[: chunk.shape[0]] = chunk
            chunk = padded
        spectrum = np_module.fft.rfft(chunk * window)
        power = (spectrum.real * spectrum.real) + (spectrum.imag * spectrum.imag)
        for band_index, mask in enumerate(band_masks):
            if not np_module.any(mask):
                continue
            value = float(np_module.mean(power[mask]))
            if value <= 0.0:
                continue
            band_power[band_index] += value
            band_counts[band_index] += 1

    levels_db: list[float | None] = []
    for index in range(len(_SPECTRAL_BAND_CENTERS_HZ)):
        if int(band_counts[index]) <= 0:
            levels_db.append(None)
            continue
        mean_power = float(band_power[index]) / float(band_counts[index])
        levels_db.append(_power_to_db(mean_power))

    full_tilt = _spectral_tilt_slope(_SPECTRAL_BAND_CENTERS_HZ, levels_db)
    section_tilts: dict[str, float | None] = {}
    for section_id, (low_hz, high_hz) in _SPECTRAL_SECTION_RANGES.items():
        section_frequencies: list[float] = []
        section_levels: list[float | None] = []
        for center_hz, level_db in zip(_SPECTRAL_BAND_CENTERS_HZ, levels_db):
            if center_hz < low_hz or center_hz > high_hz:
                continue
            section_frequencies.append(center_hz)
            section_levels.append(level_db)
        section_tilts[section_id] = _round_or_none(
            _spectral_tilt_slope(section_frequencies, section_levels)
        )

    spectral["levels_db"] = levels_db
    spectral["tilt_db_per_oct"] = _round_or_none(full_tilt)
    spectral["section_tilt_db_per_oct"] = section_tilts
    spectral["adjacent_band_slopes_db_per_oct"] = _adjacent_band_slopes(
        centers_hz=_SPECTRAL_BAND_CENTERS_HZ,
        levels_db=levels_db,
    )
    spectral["section_subband_slopes_db_per_oct"] = _section_subband_slopes(
        centers_hz=_SPECTRAL_BAND_CENTERS_HZ,
        levels_db=levels_db,
    )
    return spectral


def _metrics_from_numpy_frames(
    *,
    frames: Any,
    sample_rate_hz: int,
    channels: int,
    channel_mask: int | None,
    channel_layout: str | None,
    np_module: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _empty_metrics()
    spectral = _empty_spectral()
    if frames.size == 0:
        return metrics, spectral

    peak_linear = float(np_module.max(np_module.abs(frames)))
    rms_linear = float(np_module.sqrt(np_module.mean(frames * frames)))
    clip_count = int(np_module.sum(np_module.abs(frames) >= (1.0 - _EPSILON)))
    dc_offset = float(np_module.mean(frames))

    metrics["peak_dbfs"] = _linear_to_db(peak_linear)
    metrics["rms_dbfs"] = _linear_to_db(rms_linear)
    if metrics["peak_dbfs"] is not None and metrics["rms_dbfs"] is not None:
        metrics["crest_factor_db"] = round(
            float(metrics["peak_dbfs"] - metrics["rms_dbfs"]), 4
        )
    metrics["clip_sample_count"] = clip_count
    metrics["dc_offset"] = _round_or_none(dc_offset, digits=8)

    if channels >= _STEREO_CHANNELS:
        left = frames[:, 0]
        right = frames[:, 1]
        correlation_lr = _pearson_correlation(left, right, np_module)
        metrics["correlation_lr"] = _round_or_none(correlation_lr)

        mid = (left + right) * 0.5
        side = (left - right) * 0.5
        mid_rms = _mean_rms_db(mid, np_module)
        side_rms = _mean_rms_db(side, np_module)
        metrics["mid_rms_dbfs"] = _round_or_none(mid_rms)
        metrics["side_rms_dbfs"] = _round_or_none(side_rms)
        metrics["mono_rms_dbfs"] = _round_or_none(mid_rms)
        if mid_rms is not None and side_rms is not None:
            metrics["side_mid_ratio_db"] = _round_or_none(side_rms - mid_rms)

    try:
        from mmo.dsp.meters_truth import (  # noqa: WPS433
            compute_lufs_integrated_float64,
            compute_true_peak_dbtp_float64,
        )
    except (ImportError, ValueError):
        compute_lufs_integrated_float64 = None
        compute_true_peak_dbtp_float64 = None

    if compute_lufs_integrated_float64 is not None:
        integrated_lufs = compute_lufs_integrated_float64(
            frames,
            sample_rate_hz,
            channels,
            channel_mask=channel_mask,
            channel_layout=channel_layout,
        )
        metrics["integrated_lufs"] = _round_or_none(integrated_lufs)

    p10, p50, p90, lra = _short_term_lufs_distribution(
        frames=frames,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        channel_mask=channel_mask,
        channel_layout=channel_layout,
    )
    metrics["short_term_lufs_p10"] = p10
    metrics["short_term_lufs_p50"] = p50
    metrics["short_term_lufs_p90"] = p90
    metrics["loudness_range_lu"] = lra

    if compute_true_peak_dbtp_float64 is not None:
        true_peak = compute_true_peak_dbtp_float64(frames, sample_rate_hz)
        metrics["true_peak_dbtp"] = _round_or_none(true_peak)
        metrics["intersample_over_count"] = _compute_intersample_over_count(
            frames,
            np_module,
        )

    spectral = _compute_spectral_metrics(
        frames,
        sample_rate_hz=sample_rate_hz,
        np_module=np_module,
    )
    return metrics, spectral


def _metrics_without_numpy(
    *,
    path: Path,
    ffmpeg_cmd: Sequence[str] | None,
    channels: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _empty_metrics()
    spectral = _empty_spectral()
    try:
        peak_linear, clip_count, dc_offset, rms_dbfs, crest_db = compute_basic_stats_from_float64(
            _iter_file_samples(
                path,
                ffmpeg_cmd=ffmpeg_cmd,
                error_context="render QA basic meters",
            )
        )
    except ValueError:
        return metrics, spectral

    metrics["peak_dbfs"] = _linear_to_db(peak_linear)
    metrics["rms_dbfs"] = _round_or_none(rms_dbfs)
    metrics["crest_factor_db"] = _round_or_none(crest_db)
    metrics["clip_sample_count"] = int(clip_count)
    metrics["dc_offset"] = _round_or_none(dc_offset, digits=8)

    if channels >= _STEREO_CHANNELS:
        try:
            from mmo.dsp.correlation import (  # noqa: WPS433
                compute_pair_correlations_ffmpeg,
                compute_pair_correlations_wav,
            )
        except ImportError:
            return metrics, spectral

        try:
            if path.suffix.lower() in _WAV_EXTENSIONS:
                correlations = compute_pair_correlations_wav(path, {"lr": (0, 1)})
            elif ffmpeg_cmd:
                correlations = compute_pair_correlations_ffmpeg(
                    path,
                    ffmpeg_cmd,
                    channels=channels,
                    pairs={"lr": (0, 1)},
                )
            else:
                correlations = {}
        except ValueError:
            correlations = {}
        corr = _coerce_float(correlations.get("lr"))
        if corr is not None:
            metrics["correlation_lr"] = _round_or_none(corr)

    return metrics, spectral


def _normalize_channel_layout(raw_value: Any) -> str | None:
    value = _coerce_str(raw_value).strip().lower()
    if value:
        return value
    return None


def _compute_file_metrics(
    *,
    path: Path,
    channels: int | None,
    sample_rate_hz: int | None,
    channel_mask: int | None,
    channel_layout: str | None,
    ffmpeg_cmd: Sequence[str] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _empty_metrics()
    spectral = _empty_spectral()
    if channels is None or sample_rate_hz is None:
        return metrics, spectral
    if channels <= 0 or sample_rate_hz <= 0:
        return metrics, spectral

    np_module = _optional_numpy()
    if np_module is None:
        return _metrics_without_numpy(
            path=path,
            ffmpeg_cmd=ffmpeg_cmd,
            channels=channels,
        )

    try:
        frames = _decode_frames_float64(
            path=path,
            channels=channels,
            ffmpeg_cmd=ffmpeg_cmd,
            np_module=np_module,
        )
    except ValueError:
        return metrics, spectral

    return _metrics_from_numpy_frames(
        frames=frames,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        channel_mask=channel_mask,
        channel_layout=channel_layout,
        np_module=np_module,
    )


def _file_entry(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"render_qa file pointer path is missing: {resolved.as_posix()}")

    metadata: dict[str, Any]
    try:
        metadata = read_metadata(resolved)
    except (NotImplementedError, ValueError):
        metadata = {}

    channels = _coerce_int(metadata.get("channels"))
    if channels is not None and channels <= 0:
        channels = None
    sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
    if sample_rate_hz is not None and sample_rate_hz <= 0:
        sample_rate_hz = None
    channel_mask = _coerce_int(metadata.get("channel_mask"))
    channel_layout = _normalize_channel_layout(metadata.get("channel_layout"))

    metrics, spectral = _compute_file_metrics(
        path=resolved,
        channels=channels,
        sample_rate_hz=sample_rate_hz,
        channel_mask=channel_mask,
        channel_layout=channel_layout,
        ffmpeg_cmd=ffmpeg_cmd,
    )
    correlation_lr = _coerce_float(metrics.get("correlation_lr"))
    polarity_threshold = thresholds["polarity_error_correlation_lte"]
    polarity_risk = (
        channels == _STEREO_CHANNELS
        and correlation_lr is not None
        and correlation_lr <= polarity_threshold
    )

    return {
        "path": resolved.as_posix(),
        "sha256": sha256_file(resolved),
        "format": detect_format_from_path(resolved),
        "channel_count": channels,
        "sample_rate_hz": sample_rate_hz,
        "metrics": metrics,
        "spectral": spectral,
        "polarity_risk": bool(polarity_risk),
    }


def _delta_metric(
    output_metrics: dict[str, Any],
    input_metrics: dict[str, Any],
    key: str,
) -> float | None:
    output_value = _coerce_float(output_metrics.get(key))
    input_value = _coerce_float(input_metrics.get(key))
    if output_value is None or input_value is None:
        return None
    return round(output_value - input_value, 4)


def _delta_metrics(
    *,
    input_entry: dict[str, Any],
    output_entry: dict[str, Any],
) -> dict[str, Any]:
    input_metrics = input_entry.get("metrics")
    output_metrics = output_entry.get("metrics")
    input_spectral = input_entry.get("spectral")
    output_spectral = output_entry.get("spectral")

    if not isinstance(input_metrics, dict) or not isinstance(output_metrics, dict):
        input_metrics = {}
        output_metrics = {}
    if not isinstance(input_spectral, dict) or not isinstance(output_spectral, dict):
        input_spectral = {}
        output_spectral = {}

    return {
        "peak_dbfs": _delta_metric(output_metrics, input_metrics, "peak_dbfs"),
        "rms_dbfs": _delta_metric(output_metrics, input_metrics, "rms_dbfs"),
        "integrated_lufs": _delta_metric(output_metrics, input_metrics, "integrated_lufs"),
        "crest_factor_db": _delta_metric(output_metrics, input_metrics, "crest_factor_db"),
        "true_peak_dbtp": _delta_metric(output_metrics, input_metrics, "true_peak_dbtp"),
        "loudness_range_lu": _delta_metric(output_metrics, input_metrics, "loudness_range_lu"),
        "correlation_lr": _delta_metric(output_metrics, input_metrics, "correlation_lr"),
        "side_mid_ratio_db": _delta_metric(
            output_metrics,
            input_metrics,
            "side_mid_ratio_db",
        ),
        "spectral_tilt_db_per_oct": _delta_metric(
            output_spectral,
            input_spectral,
            "tilt_db_per_oct",
        ),
    }


def _issue(
    *,
    issue_id: str,
    severity: str,
    message: str,
    job_id: str,
    output_path: str,
    metric: str,
    value: float | int | None,
    threshold: float | int | None,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "message": message,
        "job_id": job_id,
        "output_path": output_path,
        "metric": metric,
        "value": value,
        "threshold": threshold,
    }


def _severity_rank(value: Any) -> int:
    if isinstance(value, str):
        return _SEVERITY_ORDER.get(value, 99)
    return 99


def _issue_sort_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    try:
        value_repr = json.dumps(issue.get("value"), sort_keys=True)
    except TypeError:
        value_repr = repr(issue.get("value"))
    try:
        threshold_repr = json.dumps(issue.get("threshold"), sort_keys=True)
    except TypeError:
        threshold_repr = repr(issue.get("threshold"))
    return (
        _severity_rank(issue.get("severity")),
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("job_id")).strip(),
        _coerce_str(issue.get("output_path")).strip(),
        _coerce_str(issue.get("metric")).strip(),
        value_repr,
        threshold_repr,
    )


def _build_qa_issues(
    *,
    jobs: list[dict[str, Any]],
    thresholds: dict[str, float],
    plugin_chain_used: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for job in jobs:
        job_id = _coerce_str(job.get("job_id")).strip()
        outputs = job.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            output_path = _coerce_str(output.get("path")).strip()
            metrics = output.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            correlation = _coerce_float(metrics.get("correlation_lr"))
            if output.get("polarity_risk") is True:
                issues.append(
                    _issue(
                        issue_id="ISSUE.RENDER.QA.POLARITY_RISK",
                        severity="error",
                        message=(
                            "Stereo output has strong anti-phase correlation "
                            "and may collapse poorly in mono."
                        ),
                        job_id=job_id,
                        output_path=output_path,
                        metric="correlation_lr",
                        value=_round_or_none(correlation),
                        threshold=_round_or_none(
                            thresholds["polarity_error_correlation_lte"]
                        ),
                    )
                )
            elif (
                correlation is not None
                and correlation <= thresholds["correlation_warn_lte"]
            ):
                issues.append(
                    _issue(
                        issue_id="ISSUE.RENDER.QA.CORRELATION_LOW",
                        severity="warn",
                        message=(
                            "Stereo output correlation is low; verify mono compatibility."
                        ),
                        job_id=job_id,
                        output_path=output_path,
                        metric="correlation_lr",
                        value=_round_or_none(correlation),
                        threshold=_round_or_none(thresholds["correlation_warn_lte"]),
                    )
                )

            clip_sample_count = output.get("metrics", {})
            if not isinstance(clip_sample_count, dict):
                clip_sample_count = {}
            clip_count_value = clip_sample_count.get("clip_sample_count")
            if isinstance(clip_count_value, int) and clip_count_value > 0:
                issues.append(
                    _issue(
                        issue_id="ISSUE.RENDER.QA.CLIPPING_DETECTED",
                        severity="error",
                        message="Rendered output contains clipped samples.",
                        job_id=job_id,
                        output_path=output_path,
                        metric="clip_sample_count",
                        value=int(clip_count_value),
                        threshold=0,
                    )
                )

            true_peak_dbtp = _coerce_float(metrics.get("true_peak_dbtp"))
            if true_peak_dbtp is not None:
                if true_peak_dbtp > thresholds["true_peak_error_dbtp_gt"]:
                    issues.append(
                        _issue(
                            issue_id="ISSUE.RENDER.QA.TRUE_PEAK_EXCESSIVE",
                            severity="error",
                            message=(
                                "Rendered output true-peak exceeds the configured "
                                "error threshold."
                            ),
                            job_id=job_id,
                            output_path=output_path,
                            metric="true_peak_dbtp",
                            value=_round_or_none(true_peak_dbtp),
                            threshold=_round_or_none(
                                thresholds["true_peak_error_dbtp_gt"]
                            ),
                        )
                    )
                elif true_peak_dbtp > thresholds["true_peak_warn_dbtp_gt"]:
                    issues.append(
                        _issue(
                            issue_id="ISSUE.RENDER.QA.TRUE_PEAK_HIGH",
                            severity="warn",
                            message=(
                                "Rendered output true-peak exceeds the configured "
                                "warning threshold."
                            ),
                            job_id=job_id,
                            output_path=output_path,
                            metric="true_peak_dbtp",
                            value=_round_or_none(true_peak_dbtp),
                            threshold=_round_or_none(
                                thresholds["true_peak_warn_dbtp_gt"]
                            ),
                        )
                    )

            loudness_range_lu = _coerce_float(metrics.get("loudness_range_lu"))
            if loudness_range_lu is not None:
                if loudness_range_lu >= thresholds["lra_error_lu_gte"]:
                    issues.append(
                        _issue(
                            issue_id="ISSUE.RENDER.QA.LRA_EXCESSIVE",
                            severity="error",
                            message=(
                                "Rendered output loudness range exceeds the configured "
                                "error threshold."
                            ),
                            job_id=job_id,
                            output_path=output_path,
                            metric="loudness_range_lu",
                            value=_round_or_none(loudness_range_lu),
                            threshold=_round_or_none(thresholds["lra_error_lu_gte"]),
                        )
                    )
                elif loudness_range_lu >= thresholds["lra_warn_lu_gte"]:
                    issues.append(
                        _issue(
                            issue_id="ISSUE.RENDER.QA.LRA_HIGH",
                            severity="warn",
                            message=(
                                "Rendered output loudness range exceeds the configured "
                                "warning threshold."
                            ),
                            job_id=job_id,
                            output_path=output_path,
                            metric="loudness_range_lu",
                            value=_round_or_none(loudness_range_lu),
                            threshold=_round_or_none(thresholds["lra_warn_lu_gte"]),
                        )
                    )
                elif loudness_range_lu <= thresholds["lra_warn_lu_lte"]:
                    issues.append(
                        _issue(
                            issue_id="ISSUE.RENDER.QA.LRA_LOW",
                            severity="warn",
                            message=(
                                "Rendered output loudness range is below the configured "
                                "warning threshold."
                            ),
                            job_id=job_id,
                            output_path=output_path,
                            metric="loudness_range_lu",
                            value=_round_or_none(loudness_range_lu),
                            threshold=_round_or_none(thresholds["lra_warn_lu_lte"]),
                        )
                    )

    if plugin_chain_used:
        for job in jobs:
            job_id = _coerce_str(job.get("job_id")).strip()
            comparisons = job.get("comparisons")
            if not isinstance(comparisons, list):
                continue
            for comparison in comparisons:
                if not isinstance(comparison, dict):
                    continue
                output_path = _coerce_str(comparison.get("output_path")).strip()
                metrics_delta = comparison.get("metrics_delta")
                if not isinstance(metrics_delta, dict):
                    continue
                delta_lufs = _coerce_float(metrics_delta.get("integrated_lufs"))
                delta_crest = _coerce_float(metrics_delta.get("crest_factor_db"))

                if delta_lufs is not None:
                    delta_lufs_abs = abs(delta_lufs)
                    if delta_lufs_abs > thresholds["plugin_delta_lufs_error_abs"]:
                        issues.append(
                            _issue(
                                issue_id="ISSUE.RENDER.QA.PLUGIN_DELTA_LUFS_EXCESSIVE",
                                severity="error",
                                message=(
                                    "Plugin-chain loudness delta exceeds configured error threshold."
                                ),
                                job_id=job_id,
                                output_path=output_path,
                                metric="delta.integrated_lufs",
                                value=_round_or_none(delta_lufs),
                                threshold=_round_or_none(
                                    thresholds["plugin_delta_lufs_error_abs"]
                                ),
                            )
                        )
                    elif delta_lufs_abs > thresholds["plugin_delta_lufs_warn_abs"]:
                        issues.append(
                            _issue(
                                issue_id="ISSUE.RENDER.QA.PLUGIN_DELTA_LUFS_HIGH",
                                severity="warn",
                                message=(
                                    "Plugin-chain loudness delta exceeds configured warning threshold."
                                ),
                                job_id=job_id,
                                output_path=output_path,
                                metric="delta.integrated_lufs",
                                value=_round_or_none(delta_lufs),
                                threshold=_round_or_none(
                                    thresholds["plugin_delta_lufs_warn_abs"]
                                ),
                            )
                        )

                if delta_crest is not None:
                    delta_crest_abs = abs(delta_crest)
                    if delta_crest_abs > thresholds["plugin_delta_crest_error_abs"]:
                        issues.append(
                            _issue(
                                issue_id="ISSUE.RENDER.QA.PLUGIN_DELTA_CREST_EXCESSIVE",
                                severity="error",
                                message=(
                                    "Plugin-chain crest-factor delta exceeds configured error threshold."
                                ),
                                job_id=job_id,
                                output_path=output_path,
                                metric="delta.crest_factor_db",
                                value=_round_or_none(delta_crest),
                                threshold=_round_or_none(
                                    thresholds["plugin_delta_crest_error_abs"]
                                ),
                            )
                        )
                    elif delta_crest_abs > thresholds["plugin_delta_crest_warn_abs"]:
                        issues.append(
                            _issue(
                                issue_id="ISSUE.RENDER.QA.PLUGIN_DELTA_CREST_HIGH",
                                severity="warn",
                                message=(
                                    "Plugin-chain crest-factor delta exceeds configured warning threshold."
                                ),
                                job_id=job_id,
                                output_path=output_path,
                                metric="delta.crest_factor_db",
                                value=_round_or_none(delta_crest),
                                threshold=_round_or_none(
                                    thresholds["plugin_delta_crest_warn_abs"]
                                ),
                            )
                        )

    issues.sort(key=_issue_sort_key)
    return issues


def _qa_job_from_row(
    *,
    row: dict[str, Any],
    ffmpeg_cmd: Sequence[str] | None,
    thresholds: dict[str, float],
    plugin_chain_used: bool,
) -> dict[str, Any]:
    job_id = _coerce_str(row.get("job_id")).strip()
    if not job_id:
        raise ValueError("render_qa job row is missing job_id.")

    input_paths = _normalize_paths(row.get("input_paths"))
    output_paths = _normalize_paths(row.get("output_paths"))
    if not input_paths:
        raise ValueError(f"render_qa job {job_id} is missing input_paths.")
    if not output_paths:
        raise ValueError(f"render_qa job {job_id} is missing output_paths.")

    input_entry = _file_entry(
        input_paths[0],
        ffmpeg_cmd=ffmpeg_cmd,
        thresholds=thresholds,
    )
    output_entries = [
        _file_entry(
            output_path,
            ffmpeg_cmd=ffmpeg_cmd,
            thresholds=thresholds,
        )
        for output_path in output_paths
    ]
    output_entries.sort(key=lambda entry: _coerce_str(entry.get("path")).strip())

    comparisons: list[dict[str, Any]] = []
    if plugin_chain_used:
        for output_entry in output_entries:
            comparisons.append(
                {
                    "input_path": _coerce_str(input_entry.get("path")).strip(),
                    "output_path": _coerce_str(output_entry.get("path")).strip(),
                    "metrics_delta": _delta_metrics(
                        input_entry=input_entry,
                        output_entry=output_entry,
                    ),
                }
            )

    return {
        "job_id": job_id,
        "input": input_entry,
        "outputs": output_entries,
        "comparisons": comparisons,
    }


def build_render_qa_payload(
    *,
    request_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    report_payload: dict[str, Any],
    job_rows: list[dict[str, Any]],
    plugin_chain_used: bool,
) -> dict[str, Any]:
    """Build a schema-valid deterministic render_qa payload."""
    request_sha256 = _canonical_sha256(request_payload)
    plan_sha256 = _canonical_sha256(plan_payload)
    report_sha256 = _canonical_sha256(report_payload)
    run_id = _run_id(request_sha256=request_sha256, plan_sha256=plan_sha256)
    ffmpeg_cmd = resolve_ffmpeg_cmd()
    thresholds = dict(_DEFAULT_THRESHOLDS)

    jobs: list[dict[str, Any]] = []
    for row in job_rows:
        if not isinstance(row, dict):
            continue
        jobs.append(
            _qa_job_from_row(
                row=row,
                ffmpeg_cmd=ffmpeg_cmd,
                thresholds=thresholds,
                plugin_chain_used=plugin_chain_used,
            )
        )
    if not jobs:
        raise ValueError("render_qa requires at least one executed job row.")
    jobs.sort(key=lambda item: _coerce_str(item.get("job_id")).strip())

    issues = _build_qa_issues(
        jobs=jobs,
        thresholds=thresholds,
        plugin_chain_used=plugin_chain_used,
    )

    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "request_sha256": request_sha256,
        "plan_sha256": plan_sha256,
        "report_sha256": report_sha256,
        "plugin_chain_used": bool(plugin_chain_used),
        "thresholds": thresholds,
        "jobs": jobs,
        "issues": issues,
    }


def render_qa_has_error_issues(payload: dict[str, Any]) -> bool:
    """Return True if any render_qa issue has severity=error."""
    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        return False
    return any(
        isinstance(issue, dict)
        and _coerce_str(issue.get("severity")).strip() == "error"
        for issue in raw_issues
    )
