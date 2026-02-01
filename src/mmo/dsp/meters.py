from __future__ import annotations

import math
import wave
from pathlib import Path

from mmo.dsp.float64 import (
    bytes_to_int_samples_pcm,
    interleaved_to_mono_peak,
    pcm_int_to_float64,
)


def compute_sample_peak_dbfs_wav(path: Path) -> float:
    """Compute the sample peak (dBFS) for a PCM WAV file."""
    try:
        with wave.open(str(path), "rb") as handle:
            sample_width = handle.getsampwidth()
            bits_per_sample = sample_width * 8
            if bits_per_sample not in (16, 24):
                raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
            channels = handle.getnchannels()
            peak = 0.0
            while True:
                frames = handle.readframes(4096)
                if not frames:
                    break
                int_samples = bytes_to_int_samples_pcm(frames, bits_per_sample, channels)
                float_samples = pcm_int_to_float64(int_samples, bits_per_sample)
                chunk_peak = interleaved_to_mono_peak(float_samples, channels)
                if chunk_peak > peak:
                    peak = chunk_peak
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for peak meter: {path}") from exc

    if peak == 0.0:
        return float("-inf")

    return 20.0 * math.log10(peak)
