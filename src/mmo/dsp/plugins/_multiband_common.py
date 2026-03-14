"""Shared deterministic multiband dynamics implementation."""

from __future__ import annotations

import math
from typing import Any, Sequence

from mmo.dsp.plugins.base import (
    AudioBufferF64,
    ProcessContext,
    PluginContext,
    PluginValidationError,
    coerce_audio_buffer_for_process_context,
    optional_float_param,
    optional_int_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
    precision_mode_numpy_dtype,
    require_finite_float_param,
)

OPERATION_COMPRESS = "compress"
OPERATION_EXPAND = "expand"
OPERATION_AUTO = "auto"
DETECTOR_MODE_RMS = "rms"
DETECTOR_MODE_PEAK = "peak"
DETECTOR_MODE_LUFS_SHORTTERM = "lufs_shortterm"
DETECTOR_MODES = frozenset(
    {
        DETECTOR_MODE_RMS,
        DETECTOR_MODE_PEAK,
        DETECTOR_MODE_LUFS_SHORTTERM,
    },
)
MIN_BANDS = 2
MAX_BANDS = 8
WINDOW_SIZE = 2048
HOP_SIZE = 512
MAX_LOOKAHEAD_MS = 20.0
MAX_OVERSAMPLING = 2
SPECTRAL_BAND_CENTERS_HZ: tuple[float, ...] = (
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


def parse_detector_mode(*, plugin_id: str, params: dict[str, Any]) -> str:
    raw_mode = params.get("detector_mode")
    if raw_mode is None:
        return DETECTOR_MODE_RMS
    if not isinstance(raw_mode, str):
        raise PluginValidationError(
            f"{plugin_id} requires string params.detector_mode. "
            f"Allowed: {', '.join(sorted(DETECTOR_MODES))}.",
        )
    mode = raw_mode.strip().lower()
    if mode in DETECTOR_MODES:
        return mode
    raise PluginValidationError(
        f"{plugin_id} requires params.detector_mode in "
        f"{', '.join(sorted(DETECTOR_MODES))}.",
    )


def _db_from_linear_level(linear_level: float) -> float:
    if linear_level <= 1e-12:
        return -120.0
    return 20.0 * math.log10(linear_level)


def _spectral_band_edges(centers_hz: Sequence[float]) -> list[tuple[float, float]]:
    edges: list[tuple[float, float]] = []
    if not centers_hz:
        return edges
    for index, center_hz in enumerate(centers_hz):
        if index == 0:
            low_hz = center_hz / math.sqrt(2.0)
        else:
            low_hz = math.sqrt(centers_hz[index - 1] * center_hz)
        if index == len(centers_hz) - 1:
            high_hz = center_hz * math.sqrt(2.0)
        else:
            high_hz = math.sqrt(center_hz * centers_hz[index + 1])
        edges.append((low_hz, high_hz))
    return edges


def _adjacent_slopes_db_per_oct(
    *,
    centers_hz: Sequence[float],
    levels_db: Sequence[float | None],
) -> list[float | None]:
    slopes: list[float | None] = []
    for index in range(len(centers_hz) - 1):
        low_hz = float(centers_hz[index])
        high_hz = float(centers_hz[index + 1])
        low_level = levels_db[index]
        high_level = levels_db[index + 1]
        if low_level is None or high_level is None or low_hz <= 0.0 or high_hz <= low_hz:
            slopes.append(None)
            continue
        octaves = math.log2(high_hz / low_hz)
        if abs(octaves) <= 1e-12:
            slopes.append(None)
            continue
        slope = float(high_level - low_level) / float(octaves)
        slopes.append(slope if math.isfinite(slope) else None)
    return slopes


def _compute_multiband_levels_and_slopes(
    *,
    signal: Any,
    sample_rate_hz: int,
    window_size: int,
    hop_size: int,
) -> tuple[list[float | None], list[float | None]]:
    import numpy as np

    dry64 = signal.astype(np.float64, copy=False)
    if dry64.size <= 0:
        empty_levels = [None for _ in SPECTRAL_BAND_CENTERS_HZ]
        empty_slopes = [None for _ in range(len(SPECTRAL_BAND_CENTERS_HZ) - 1)]
        return empty_levels, empty_slopes

    mono = np.mean(dry64, axis=1)
    if mono.size <= 0 or sample_rate_hz <= 0:
        empty_levels = [None for _ in SPECTRAL_BAND_CENTERS_HZ]
        empty_slopes = [None for _ in range(len(SPECTRAL_BAND_CENTERS_HZ) - 1)]
        return empty_levels, empty_slopes

    effective_window = min(max(int(window_size), 256), int(max(mono.shape[0], 256)))
    effective_hop = max(1, min(int(hop_size), effective_window // 2))
    if effective_window <= 1:
        empty_levels = [None for _ in SPECTRAL_BAND_CENTERS_HZ]
        empty_slopes = [None for _ in range(len(SPECTRAL_BAND_CENTERS_HZ) - 1)]
        return empty_levels, empty_slopes

    if mono.shape[0] <= effective_window:
        frame_total = 1
    else:
        frame_total = 1 + (mono.shape[0] - effective_window) // effective_hop

    window = np.hanning(effective_window).astype(np.float64)
    freqs_hz = np.fft.rfftfreq(effective_window, d=1.0 / float(sample_rate_hz))
    band_edges = _spectral_band_edges(SPECTRAL_BAND_CENTERS_HZ)
    band_masks = [
        (freqs_hz >= low_hz) & (freqs_hz < high_hz)
        for low_hz, high_hz in band_edges
    ]
    band_power = np.zeros(len(SPECTRAL_BAND_CENTERS_HZ), dtype=np.float64)
    band_counts = np.zeros(len(SPECTRAL_BAND_CENTERS_HZ), dtype=np.int64)

    for frame_index in range(frame_total):
        start = frame_index * effective_hop
        frame = mono[start : start + effective_window]
        if frame.shape[0] < effective_window:
            padded = np.zeros(effective_window, dtype=np.float64)
            padded[: frame.shape[0]] = frame
            frame = padded
        spectrum = np.fft.rfft(frame * window)
        power = (spectrum.real * spectrum.real) + (spectrum.imag * spectrum.imag)
        for band_index, mask in enumerate(band_masks):
            if not np.any(mask):
                continue
            value = float(np.mean(power[mask]))
            if value <= 0.0:
                continue
            band_power[band_index] += value
            band_counts[band_index] += 1

    levels_db: list[float | None] = []
    for band_index in range(len(SPECTRAL_BAND_CENTERS_HZ)):
        if int(band_counts[band_index]) <= 0:
            levels_db.append(None)
            continue
        mean_power = float(band_power[band_index]) / float(band_counts[band_index])
        levels_db.append(_db_from_linear_level(math.sqrt(max(mean_power, 0.0))))
    slopes = _adjacent_slopes_db_per_oct(
        centers_hz=SPECTRAL_BAND_CENTERS_HZ,
        levels_db=levels_db,
    )
    return levels_db, slopes


def _derive_multiband_split_indices(
    *,
    slopes_db_per_oct: Sequence[float | None],
    min_band_count: int,
    max_band_count: int,
    slope_sensitivity: float,
) -> tuple[list[int], float]:
    valid_slopes = [
        abs(float(value))
        for value in slopes_db_per_oct
        if value is not None and math.isfinite(float(value))
    ]
    slope_activity = (
        float(sum(valid_slopes)) / float(len(valid_slopes))
        if valid_slopes
        else 0.0
    )
    clamped_sensitivity = min(max(float(slope_sensitivity), 0.0), 1.0)
    span = max(0, max_band_count - min_band_count)
    normalized_activity = min(
        1.0,
        (slope_activity / 8.0) * (0.5 + (0.5 * clamped_sensitivity)),
    )
    target_band_count = min_band_count + int(round(span * normalized_activity))
    target_band_count = max(min_band_count, min(max_band_count, target_band_count))
    split_count = max(0, target_band_count - 1)
    if split_count <= 0:
        return [], slope_activity

    candidate_rows: list[tuple[float, int]] = []
    for index, slope_value in enumerate(slopes_db_per_oct):
        if slope_value is None or not math.isfinite(float(slope_value)):
            continue
        score = abs(float(slope_value)) * (0.5 + (0.5 * clamped_sensitivity))
        if score <= 0.0:
            continue
        candidate_rows.append((score, index))
    candidate_rows.sort(key=lambda item: (-item[0], item[1]))

    selected: list[int] = []
    min_spacing = 2
    for _, index in candidate_rows:
        if any(abs(index - other_index) < min_spacing for other_index in selected):
            continue
        selected.append(index)
        if len(selected) >= split_count:
            break

    if len(selected) < split_count:
        total_boundaries = len(SPECTRAL_BAND_CENTERS_HZ) - 1
        for boundary_rank in range(1, split_count + 1):
            candidate = int(
                round((boundary_rank * total_boundaries) / float(split_count + 1)),
            )
            candidate = max(0, min(total_boundaries - 1, candidate))
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= split_count:
                break

    selected = sorted(set(selected))
    if len(selected) > split_count:
        selected = selected[:split_count]
    return selected, slope_activity


def _build_multiband_ranges(
    *,
    split_indices: Sequence[int],
    levels_db: Sequence[float | None],
    slopes_db_per_oct: Sequence[float | None],
    slope_sensitivity: float,
    operation_mode: str,
) -> list[dict[str, Any]]:
    edges = _spectral_band_edges(SPECTRAL_BAND_CENTERS_HZ)
    bucket_last_index = len(SPECTRAL_BAND_CENTERS_HZ) - 1
    boundaries = sorted(
        {
            int(index)
            for index in split_indices
            if 0 <= int(index) < bucket_last_index
        },
    )

    median_levels = sorted(
        float(level)
        for level in levels_db
        if level is not None and math.isfinite(float(level))
    )
    level_median = median_levels[len(median_levels) // 2] if median_levels else -24.0
    clamped_sensitivity = min(max(float(slope_sensitivity), 0.0), 1.0)
    auto_slope_threshold = 0.75 + ((1.0 - clamped_sensitivity) * 1.25)

    band_rows: list[dict[str, Any]] = []
    start_bucket = 0
    for boundary in boundaries + [bucket_last_index]:
        end_bucket = int(boundary)
        if end_bucket < start_bucket:
            continue
        low_hz = float(edges[start_bucket][0])
        high_hz = float(edges[end_bucket][1])

        local_slopes = [
            float(value)
            for value in slopes_db_per_oct[start_bucket:end_bucket]
            if value is not None and math.isfinite(float(value))
        ]
        local_levels = [
            float(value)
            for value in levels_db[start_bucket : end_bucket + 1]
            if value is not None and math.isfinite(float(value))
        ]
        band_slope = (
            float(sum(local_slopes)) / float(len(local_slopes))
            if local_slopes
            else 0.0
        )
        band_level = (
            float(sum(local_levels)) / float(len(local_levels))
            if local_levels
            else level_median
        )

        if operation_mode == OPERATION_AUTO:
            if band_slope >= auto_slope_threshold:
                band_operation = OPERATION_COMPRESS
            elif band_slope <= -auto_slope_threshold:
                band_operation = OPERATION_EXPAND
            elif band_level >= level_median:
                band_operation = OPERATION_COMPRESS
            else:
                band_operation = OPERATION_EXPAND
        else:
            band_operation = operation_mode

        band_rows.append(
            {
                "low_hz": low_hz,
                "high_hz": high_hz,
                "slope_db_per_oct": band_slope,
                "mean_level_db": band_level,
                "operation": band_operation,
            },
        )
        start_bucket = end_bucket + 1

    if not band_rows:
        band_rows.append(
            {
                "low_hz": float(edges[0][0]),
                "high_hz": float(edges[-1][1]),
                "slope_db_per_oct": 0.0,
                "mean_level_db": level_median,
                "operation": operation_mode,
            },
        )
    return band_rows


def _apply_multiband_dynamics_v0(
    *,
    signal: Any,
    sample_rate_hz: int,
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    makeup_db: float,
    lookahead_ms: float,
    detector_mode: str,
    slope_sensitivity: float,
    min_band_count: int,
    max_band_count: int,
    operation_mode: str,
    oversampling: int,
    max_theoretical_quality: bool,
    output_dtype: Any,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    if oversampling > 1 and not max_theoretical_quality:
        raise PluginValidationError(
            "Multiband oversampling > 1 requires options.max_theoretical_quality=true.",
        )

    dry64 = signal.astype(np.float64, copy=False)
    if dry64.size == 0:
        return dry64.astype(output_dtype, copy=False), {
            "band_count": 1.0,
            "slope_activity_db_per_oct": 0.0,
            "gr_approx_db": 0.0,
            "band_gr_approx_db": [0.0],
            "lookahead_samples": 0.0,
            "oversampling": float(oversampling),
            "operation_counts": {
                OPERATION_COMPRESS: 0.0,
                OPERATION_EXPAND: 0.0,
            },
        }

    analysis_window = WINDOW_SIZE * max(1, int(oversampling))
    analysis_hop = HOP_SIZE * max(1, int(oversampling))
    levels_db, slopes_db_per_oct = _compute_multiband_levels_and_slopes(
        signal=dry64,
        sample_rate_hz=sample_rate_hz,
        window_size=analysis_window,
        hop_size=analysis_hop,
    )
    split_indices, slope_activity = _derive_multiband_split_indices(
        slopes_db_per_oct=slopes_db_per_oct,
        min_band_count=min_band_count,
        max_band_count=max_band_count,
        slope_sensitivity=slope_sensitivity,
    )
    band_rows = _build_multiband_ranges(
        split_indices=split_indices,
        levels_db=levels_db,
        slopes_db_per_oct=slopes_db_per_oct,
        slope_sensitivity=slope_sensitivity,
        operation_mode=operation_mode,
    )

    sample_count = int(dry64.shape[0])
    channel_count = int(dry64.shape[1])
    window_size = min(max(analysis_window, 256), max(sample_count, 256))
    hop_size = max(1, min(analysis_hop, window_size // 2))
    if sample_count <= window_size:
        frame_total = 1
    else:
        frame_total = 1 + (sample_count - window_size) // hop_size

    window = np.hanning(window_size).astype(np.float64)
    freq_bins_hz = np.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
    nyquist_hz = float(sample_rate_hz) * 0.5
    band_masks = []
    for band in band_rows:
        low_hz = max(0.0, float(band["low_hz"]))
        high_hz = min(nyquist_hz, float(band["high_hz"]))
        if high_hz <= low_hz:
            mask = np.zeros(freq_bins_hz.shape[0], dtype=bool)
        else:
            mask = (freq_bins_hz >= low_hz) & (freq_bins_hz < high_hz)
        band_masks.append(mask)

    detector_db = np.full((frame_total, len(band_rows)), -120.0, dtype=np.float64)
    for frame_index in range(frame_total):
        start = frame_index * hop_size
        frame_channels = np.zeros((channel_count, window_size), dtype=np.float64)
        available = max(0, min(window_size, sample_count - start))
        if available > 0:
            frame_channels[:, :available] = dry64[start : start + available, :].T
        spectrum = np.fft.rfft(frame_channels * window[np.newaxis, :], axis=1)
        magnitude = np.abs(spectrum)
        power = magnitude * magnitude
        for band_index, mask in enumerate(band_masks):
            if not np.any(mask):
                continue
            if detector_mode == DETECTOR_MODE_PEAK:
                channel_values = np.max(magnitude[:, mask], axis=1)
                linked_linear = float(np.max(channel_values))
            else:
                channel_values = np.sqrt(np.mean(power[:, mask], axis=1))
                linked_linear = float(np.max(channel_values))
            band_db = _db_from_linear_level(linked_linear)
            if detector_mode == DETECTOR_MODE_LUFS_SHORTTERM:
                band_db -= 0.691
            detector_db[frame_index, band_index] = band_db

    lookahead_samples = int(
        round(
            min(max(lookahead_ms, 0.0), MAX_LOOKAHEAD_MS)
            * float(sample_rate_hz)
            / 1000.0,
        ),
    )
    lookahead_frames = (
        int(round(float(lookahead_samples) / float(hop_size)))
        if hop_size > 0
        else 0
    )

    safe_ratio = max(float(ratio), 1.0)
    safe_attack_seconds = max(float(attack_ms) / 1000.0, 1.0 / float(sample_rate_hz))
    safe_release_seconds = max(float(release_ms) / 1000.0, 1.0 / float(sample_rate_hz))
    frame_seconds = float(hop_size) / float(sample_rate_hz)
    attack_coeff = math.exp(-frame_seconds / safe_attack_seconds)
    release_coeff = math.exp(-frame_seconds / safe_release_seconds)

    band_envelope_db = np.full(len(band_rows), -120.0, dtype=np.float64)
    band_gain_linear = np.ones((frame_total, len(band_rows)), dtype=np.float64)
    band_gr_sum = np.zeros(len(band_rows), dtype=np.float64)
    band_gr_count = np.zeros(len(band_rows), dtype=np.int64)
    operation_counts = {
        OPERATION_COMPRESS: 0.0,
        OPERATION_EXPAND: 0.0,
    }
    for frame_index in range(frame_total):
        detector_index = min(frame_total - 1, frame_index + lookahead_frames)
        for band_index, band in enumerate(band_rows):
            detector_value = float(detector_db[detector_index, band_index])
            previous_env = float(band_envelope_db[band_index])
            coeff = attack_coeff if detector_value > previous_env else release_coeff
            envelope_db = (coeff * previous_env) + ((1.0 - coeff) * detector_value)
            band_envelope_db[band_index] = envelope_db

            band_slope = float(band.get("slope_db_per_oct", 0.0))
            slope_strength = min(
                1.0,
                (abs(band_slope) / 8.0) * max(0.0, slope_sensitivity),
            )
            band_threshold_db = float(threshold_db) - (6.0 * slope_strength)
            band_ratio = min(20.0, max(1.0, safe_ratio * (1.0 + (0.5 * slope_strength))))
            band_operation = str(band.get("operation", "")).strip().lower()
            attenuation_db = 0.0
            if band_operation == OPERATION_COMPRESS:
                over_db = envelope_db - band_threshold_db
                if over_db > 0.0 and band_ratio > 1.0:
                    attenuation_db = over_db * (1.0 - (1.0 / band_ratio))
                operation_counts[OPERATION_COMPRESS] += 1.0
            elif band_operation == OPERATION_EXPAND:
                below_db = band_threshold_db - envelope_db
                if below_db > 0.0 and band_ratio > 1.0:
                    attenuation_db = below_db * (1.0 - (1.0 / band_ratio))
                operation_counts[OPERATION_EXPAND] += 1.0

            if attenuation_db > 0.0:
                band_gr_sum[band_index] += attenuation_db
                band_gr_count[band_index] += 1
            gain_db = float(makeup_db) - attenuation_db
            band_gain_linear[frame_index, band_index] = float(
                math.pow(10.0, gain_db / 20.0),
            )

    rendered = np.zeros((channel_count, sample_count + window_size), dtype=np.float64)
    norm = np.zeros(sample_count + window_size, dtype=np.float64)
    for frame_index in range(frame_total):
        start = frame_index * hop_size
        frame_channels = np.zeros((channel_count, window_size), dtype=np.float64)
        available = max(0, min(window_size, sample_count - start))
        if available > 0:
            frame_channels[:, :available] = dry64[start : start + available, :].T
        spectrum = np.fft.rfft(frame_channels * window[np.newaxis, :], axis=1)
        for band_index, mask in enumerate(band_masks):
            if not np.any(mask):
                continue
            spectrum[:, mask] *= band_gain_linear[frame_index, band_index]
        frame_output = np.fft.irfft(spectrum, n=window_size, axis=1)
        rendered[:, start : start + window_size] += frame_output * window[np.newaxis, :]
        norm[start : start + window_size] += window * window

    norm_safe = np.where(norm > 1e-12, norm, 1.0)
    wet = (rendered[:, :sample_count] / norm_safe[:sample_count]).T
    wet = np.clip(wet, -1.0, 1.0).astype(output_dtype, copy=False)

    band_gr_approx_db: list[float] = []
    for band_index in range(len(band_rows)):
        count = int(band_gr_count[band_index])
        if count <= 0:
            band_gr_approx_db.append(0.0)
        else:
            band_gr_approx_db.append(float(band_gr_sum[band_index] / float(count)))
    if band_gr_approx_db:
        gr_approx_db = float(sum(band_gr_approx_db) / float(len(band_gr_approx_db)))
    else:
        gr_approx_db = 0.0

    summary: dict[str, Any] = {
        "band_count": float(len(band_rows)),
        "slope_activity_db_per_oct": float(slope_activity),
        "gr_approx_db": float(gr_approx_db),
        "band_gr_approx_db": [float(value) for value in band_gr_approx_db],
        "lookahead_samples": float(lookahead_samples),
        "oversampling": float(oversampling),
        "operation_counts": operation_counts,
        "bands": band_rows,
    }
    return wet, summary


def process_multiband_plugin(
    *,
    plugin_id: str,
    operation_mode: str,
    audio_buffer: AudioBufferF64,
    sample_rate: int,
    params: dict[str, Any],
    ctx: PluginContext,
    process_ctx: ProcessContext | None = None,
) -> AudioBufferF64:
    import numpy as np

    if process_ctx is None:
        raise PluginValidationError(f"{plugin_id} requires ProcessContext.")

    source_buffer = coerce_audio_buffer_for_process_context(
        value=audio_buffer,
        plugin_id=plugin_id,
        sample_rate_hz=sample_rate,
        process_ctx=process_ctx,
    )

    threshold_db = require_finite_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="threshold_db",
    )
    ratio = require_finite_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="ratio",
    )
    attack_ms = require_finite_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="attack_ms",
    )
    release_ms = require_finite_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="release_ms",
    )
    makeup_db = require_finite_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="makeup_db",
    )
    lookahead_ms = optional_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="lookahead_ms",
        default_value=0.0,
        minimum_value=0.0,
        maximum_value=MAX_LOOKAHEAD_MS,
    )
    slope_sensitivity = optional_float_param(
        plugin_id=plugin_id,
        params=params,
        param_name="slope_sensitivity",
        default_value=0.7,
        minimum_value=0.0,
        maximum_value=1.0,
    )
    min_band_count = optional_int_param(
        plugin_id=plugin_id,
        params=params,
        param_name="min_band_count",
        default_value=3,
        minimum_value=MIN_BANDS,
        maximum_value=MAX_BANDS,
    )
    max_band_count = optional_int_param(
        plugin_id=plugin_id,
        params=params,
        param_name="max_band_count",
        default_value=6,
        minimum_value=MIN_BANDS,
        maximum_value=MAX_BANDS,
    )
    if max_band_count < min_band_count:
        raise PluginValidationError(
            f"{plugin_id} requires params.max_band_count >= params.min_band_count.",
        )
    oversampling = optional_int_param(
        plugin_id=plugin_id,
        params=params,
        param_name="oversampling",
        default_value=1,
        minimum_value=1,
        maximum_value=MAX_OVERSAMPLING,
    )
    detector_mode = parse_detector_mode(plugin_id=plugin_id, params=params)
    bypass = parse_bypass_for_stage(plugin_id=plugin_id, params=params)
    macro_mix, macro_mix_input = parse_macro_mix_for_stage(
        plugin_id=plugin_id,
        params=params,
    )

    processing_dtype = precision_mode_numpy_dtype(
        np=np,
        precision_mode=ctx.precision_mode,
    )
    rendered = source_buffer.to_frame_matrix(np=np, dtype=processing_dtype)
    multiband_summary: dict[str, Any] = {
        "band_count": 1.0,
        "slope_activity_db_per_oct": 0.0,
        "gr_approx_db": 0.0,
        "band_gr_approx_db": [0.0],
        "lookahead_samples": 0.0,
        "oversampling": float(oversampling),
        "operation_counts": {
            OPERATION_COMPRESS: 0.0,
            OPERATION_EXPAND: 0.0,
        },
        "bands": [],
    }
    if bypass:
        stage_what = "plugin stage bypassed"
        stage_why = (
            "Bypass enabled; preserved dry stereo "
            f"{ctx.precision_mode} buffer without multiband dynamics."
        )
    else:
        stage_what = "plugin stage applied"
        wet, multiband_summary = _apply_multiband_dynamics_v0(
            signal=rendered,
            sample_rate_hz=sample_rate,
            threshold_db=threshold_db,
            ratio=ratio,
            attack_ms=attack_ms,
            release_ms=release_ms,
            makeup_db=makeup_db,
            lookahead_ms=lookahead_ms,
            detector_mode=detector_mode,
            slope_sensitivity=slope_sensitivity,
            min_band_count=min_band_count,
            max_band_count=max_band_count,
            operation_mode=operation_mode,
            oversampling=oversampling,
            max_theoretical_quality=ctx.max_theoretical_quality,
            output_dtype=processing_dtype,
        )
        if macro_mix <= 0.0:
            stage_why = "macro_mix=0 selected dry signal path after multiband analysis."
        elif macro_mix >= 1.0:
            rendered = wet
            stage_why = (
                "Applied multiband dynamics with full wet mix using slope-driven bands."
            )
        else:
            dry = rendered
            rendered = np.add(
                np.multiply(
                    dry,
                    processing_dtype(1.0 - macro_mix),
                    dtype=processing_dtype,
                ),
                np.multiply(
                    wet,
                    processing_dtype(macro_mix),
                    dtype=processing_dtype,
                ),
                dtype=processing_dtype,
            )
            rendered = np.clip(rendered, -1.0, 1.0).astype(
                processing_dtype,
                copy=False,
            )
            stage_why = (
                "Applied multiband dynamics wet path and macro_mix as a "
                "linear dry/wet blend."
            )

    stage_metrics = [
        {"name": "stage_index", "value": ctx.stage_index},
        {"name": "threshold_db", "value": threshold_db},
        {"name": "ratio", "value": ratio},
        {"name": "attack_ms", "value": attack_ms},
        {"name": "release_ms", "value": release_ms},
        {"name": "makeup_db", "value": makeup_db},
        {"name": "lookahead_ms", "value": lookahead_ms},
        {"name": "slope_sensitivity", "value": slope_sensitivity},
        {"name": "min_band_count", "value": float(min_band_count)},
        {"name": "max_band_count", "value": float(max_band_count)},
        {"name": "band_count", "value": float(multiband_summary.get("band_count", 1.0))},
        {
            "name": "slope_activity_db_per_oct",
            "value": float(multiband_summary.get("slope_activity_db_per_oct", 0.0)),
        },
        {"name": "gr_approx_db", "value": float(multiband_summary.get("gr_approx_db", 0.0))},
        {"name": "lookahead_samples", "value": float(multiband_summary.get("lookahead_samples", 0.0))},
        {
            "name": "oversampling",
            "value": float(multiband_summary.get("oversampling", float(oversampling))),
        },
        {"name": "macro_mix", "value": macro_mix},
        {"name": "macro_mix_input", "value": macro_mix_input},
        {"name": "bypass", "value": 1.0 if bypass else 0.0},
    ]
    band_gr_metrics = multiband_summary.get("band_gr_approx_db")
    if isinstance(band_gr_metrics, list):
        for band_index, band_value in enumerate(band_gr_metrics, start=1):
            if not isinstance(band_value, (int, float)):
                continue
            stage_metrics.append(
                {
                    "name": f"band_{band_index:02d}_gr_approx_db",
                    "value": float(band_value),
                },
            )

    ctx.evidence_collector.set(
        stage_what=stage_what,
        stage_why=stage_why,
        metrics=stage_metrics,
        notes=[
            f"detector_mode={detector_mode}",
            f"operation_mode={operation_mode}",
            (
                "operation_counts="
                f"compress:{float(multiband_summary.get('operation_counts', {}).get(OPERATION_COMPRESS, 0.0)):.0f},"
                f"expand:{float(multiband_summary.get('operation_counts', {}).get(OPERATION_EXPAND, 0.0)):.0f}"
            ),
        ],
    )
    return AudioBufferF64.from_frame_matrix(
        rendered,
        channel_order=source_buffer.channel_order,
        sample_rate_hz=source_buffer.sample_rate_hz,
    )
