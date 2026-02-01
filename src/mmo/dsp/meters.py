from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Iterator

from mmo.dsp.float64 import (
    bytes_to_int_samples_pcm,
    interleaved_to_mono_peak,
    pcm_int_to_float64,
)

_EPSILON = 1e-12
_CHUNK_FRAMES = 4096


def _iter_wav_float64_samples(
    path: Path, *, error_context: str
) -> Iterator[list[float]]:
    try:
        with wave.open(str(path), "rb") as handle:
            sample_width = handle.getsampwidth()
            bits_per_sample = sample_width * 8
            if bits_per_sample not in (16, 24):
                raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
            channels = handle.getnchannels()
            while True:
                frames = handle.readframes(_CHUNK_FRAMES)
                if not frames:
                    break
                int_samples = bytes_to_int_samples_pcm(frames, bits_per_sample, channels)
                if not int_samples:
                    continue
                float_samples = pcm_int_to_float64(int_samples, bits_per_sample)
                yield float_samples
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for {error_context}: {path}") from exc


def compute_sample_peak_dbfs_wav(path: Path) -> float:
    """Compute the sample peak (dBFS) for a PCM WAV file."""
    peak = 0.0
    for float_samples in _iter_wav_float64_samples(path, error_context="peak meter"):
        chunk_peak = interleaved_to_mono_peak(float_samples, channels=1)
        if chunk_peak > peak:
            peak = chunk_peak

    if peak == 0.0:
        return float("-inf")

    return 20.0 * math.log10(peak)


def compute_clip_sample_count_wav(path: Path) -> int:
    """Count the number of clipped samples in a PCM WAV file."""
    threshold = 1.0 - _EPSILON
    count = 0
    for float_samples in _iter_wav_float64_samples(path, error_context="clip meter"):
        for sample in float_samples:
            if abs(sample) >= threshold:
                count += 1
    return count


def compute_dc_offset_wav(path: Path) -> float:
    """Compute DC offset (mean) across all interleaved samples."""
    total = 0.0
    count = 0
    for float_samples in _iter_wav_float64_samples(path, error_context="dc offset meter"):
        for sample in float_samples:
            total += sample
        count += len(float_samples)
    if count == 0:
        return 0.0
    return total / count


def compute_rms_dbfs_wav(path: Path) -> float:
    """Compute RMS level in dBFS for a PCM WAV file."""
    total = 0.0
    count = 0
    for float_samples in _iter_wav_float64_samples(path, error_context="rms meter"):
        for sample in float_samples:
            total += sample * sample
        count += len(float_samples)
    if count == 0:
        return float("-inf")
    mean_square = total / count
    if mean_square == 0.0:
        return float("-inf")
    rms = math.sqrt(mean_square)
    if rms == 0.0:
        return float("-inf")
    return 20.0 * math.log10(rms)


def compute_crest_factor_db_wav(path: Path) -> float:
    """Compute crest factor (peak/rms) in dB for a PCM WAV file."""
    peak = 0.0
    total = 0.0
    count = 0
    for float_samples in _iter_wav_float64_samples(path, error_context="crest factor meter"):
        chunk_peak = interleaved_to_mono_peak(float_samples, channels=1)
        if chunk_peak > peak:
            peak = chunk_peak
        for sample in float_samples:
            total += sample * sample
        count += len(float_samples)
    if count == 0:
        return float("-inf")
    mean_square = total / count
    if mean_square == 0.0:
        return float("-inf")
    rms = math.sqrt(mean_square)
    if rms == 0.0:
        return float("-inf")
    ratio = peak / rms
    if ratio <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(ratio)
