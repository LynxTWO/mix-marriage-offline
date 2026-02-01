from __future__ import annotations

import math
import struct
from typing import Sequence


def pcm_int_to_float64(samples: Sequence[int], bits_per_sample: int) -> list[float]:
    """Convert signed PCM integers to float64 in [-1.0, 1.0)."""
    if bits_per_sample <= 0:
        raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")

    divisor = float(2 ** (bits_per_sample - 1))
    max_value = (divisor - 1.0) / divisor
    floats: list[float] = []

    for sample in samples:
        value = sample / divisor
        if value < -1.0:
            value = -1.0
        elif value >= 1.0:
            value = max_value
        floats.append(value)

    return floats


def bytes_to_int_samples_pcm(
    frames: bytes, bits_per_sample: int, channels: int
) -> list[int]:
    """Decode PCM bytes to signed integers for 16-bit, 24-bit, or 32-bit WAV."""
    if channels <= 0:
        raise ValueError(f"Invalid channel count: {channels}")

    if bits_per_sample == 16:
        bytes_per_sample = 2
        bytes_per_frame = bytes_per_sample * channels
        total_bytes = len(frames) - (len(frames) % bytes_per_frame)
        if total_bytes <= 0:
            return []
        if total_bytes != len(frames):
            frames = frames[:total_bytes]
        count = total_bytes // bytes_per_sample
        return list(struct.unpack(f"<{count}h", frames))

    if bits_per_sample == 24:
        bytes_per_sample = 3
        bytes_per_frame = bytes_per_sample * channels
        total_bytes = len(frames) - (len(frames) % bytes_per_frame)
        if total_bytes <= 0:
            return []
        view = memoryview(frames)[:total_bytes]
        samples: list[int] = []
        for offset in range(0, total_bytes, bytes_per_sample):
            word = view[offset] | (view[offset + 1] << 8) | (view[offset + 2] << 16)
            if word & 0x800000:
                word -= 1 << 24
            samples.append(int(word))
        return samples

    if bits_per_sample == 32:
        bytes_per_sample = 4
        bytes_per_frame = bytes_per_sample * channels
        total_bytes = len(frames) - (len(frames) % bytes_per_frame)
        if total_bytes <= 0:
            return []
        if total_bytes != len(frames):
            frames = frames[:total_bytes]
        count = total_bytes // bytes_per_sample
        return list(struct.unpack(f"<{count}i", frames))

    raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")


def bytes_to_float_samples_ieee(
    frames: bytes, bits_per_sample: int, channels: int
) -> list[float]:
    """Decode IEEE float bytes to float64 samples."""
    if channels <= 0:
        raise ValueError(f"Invalid channel count: {channels}")

    if bits_per_sample == 32:
        bytes_per_sample = 4
        fmt = "f"
    elif bits_per_sample == 64:
        bytes_per_sample = 8
        fmt = "d"
    else:
        raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")

    bytes_per_frame = bytes_per_sample * channels
    total_bytes = len(frames) - (len(frames) % bytes_per_frame)
    if total_bytes <= 0:
        return []
    if total_bytes != len(frames):
        frames = frames[:total_bytes]
    count = total_bytes // bytes_per_sample
    samples = struct.unpack(f"<{count}{fmt}", frames)

    max_value = math.nextafter(1.0, 0.0)
    floats: list[float] = []
    for sample in samples:
        value = float(sample)
        if value < -1.0:
            value = -1.0
        elif value >= 1.0:
            value = max_value
        floats.append(value)
    return floats


def interleaved_to_mono_peak(samples_float64: list[float], channels: int) -> float:
    """Return the peak absolute sample across all channels."""
    if channels <= 0:
        raise ValueError(f"Invalid channel count: {channels}")

    peak = 0.0
    for sample in samples_float64:
        value = abs(sample)
        if value > peak:
            peak = value
    return peak
