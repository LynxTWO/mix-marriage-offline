from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Iterator

from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata

_CHUNK_FRAMES = 4096


def _iter_wav_float64_samples(
    path: Path, *, error_context: str
) -> Iterator[list[float]]:
    metadata = read_wav_metadata(path)
    audio_format = metadata["audio_format_resolved"]
    bits_per_sample = metadata["bits_per_sample"]
    channels = metadata["channels"]

    if audio_format == 1:
        if bits_per_sample not in (16, 24, 32):
            raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
    elif audio_format == 3:
        if bits_per_sample not in (32, 64):
            raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
    else:
        raise ValueError(f"Unsupported WAV format: {audio_format}")

    try:
        with wave.open(str(path), "rb") as handle:
            while True:
                frames = handle.readframes(_CHUNK_FRAMES)
                if not frames:
                    break
                if audio_format == 1:
                    int_samples = bytes_to_int_samples_pcm(
                        frames, bits_per_sample, channels
                    )
                    if not int_samples:
                        continue
                    float_samples = pcm_int_to_float64(int_samples, bits_per_sample)
                    yield float_samples
                elif audio_format == 3:
                    float_samples = bytes_to_float_samples_ieee(
                        frames, bits_per_sample, channels
                    )
                    if not float_samples:
                        continue
                    yield float_samples
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for {error_context}: {path}") from exc


def compute_stereo_correlation_wav(path: Path) -> float:
    """Compute Pearson correlation across interleaved stereo samples."""
    metadata = read_wav_metadata(path)
    channels = metadata["channels"]
    if channels != 2:
        raise ValueError(f"Stereo correlation requires 2 channels, got {channels}")

    count = 0
    mean_l = 0.0
    mean_r = 0.0
    sum_l = 0.0
    sum_r = 0.0
    sum_lr = 0.0

    for float_samples in _iter_wav_float64_samples(
        path, error_context="stereo correlation meter"
    ):
        total = len(float_samples) - (len(float_samples) % 2)
        for index in range(0, total, 2):
            left = float_samples[index]
            right = float_samples[index + 1]
            count += 1
            delta_l = left - mean_l
            mean_l += delta_l / count
            delta_r = right - mean_r
            mean_r += delta_r / count
            sum_l += delta_l * (left - mean_l)
            sum_r += delta_r * (right - mean_r)
            sum_lr += delta_l * (right - mean_r)

    if count < 2:
        return 0.0
    if sum_l <= 0.0 or sum_r <= 0.0:
        return 0.0

    correlation = sum_lr / math.sqrt(sum_l * sum_r)
    if correlation > 1.0:
        return 1.0
    if correlation < -1.0:
        return -1.0
    return correlation
