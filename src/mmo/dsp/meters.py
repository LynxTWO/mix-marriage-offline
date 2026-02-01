from __future__ import annotations

import math
import sys
import wave
from array import array
from pathlib import Path


_SILENCE_FLOOR_DBFS = -120.0


def _peak_from_frames(frames: bytes, sample_width: int) -> int:
    if not frames:
        return 0

    if sample_width == 2:
        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder != "little":
            samples.byteswap()
        return max(abs(sample) for sample in samples) if samples else 0

    if sample_width == 3:
        peak = 0
        view = memoryview(frames)
        total = len(view) - (len(view) % 3)
        for offset in range(0, total, 3):
            sample = int.from_bytes(view[offset : offset + 3], "little", signed=True)
            value = abs(sample)
            if value > peak:
                peak = value
        return peak

    raise ValueError(f"Unsupported sample width: {sample_width}")


def compute_sample_peak_dbfs_wav(path: Path) -> float:
    """Compute the sample peak (dBFS) for a PCM WAV file."""
    try:
        with wave.open(str(path), "rb") as handle:
            sample_width = handle.getsampwidth()
            if sample_width not in (2, 3):
                raise ValueError(f"Unsupported bits per sample: {sample_width * 8}")
            max_sample = 0
            while True:
                frames = handle.readframes(4096)
                if not frames:
                    break
                chunk_peak = _peak_from_frames(frames, sample_width)
                if chunk_peak > max_sample:
                    max_sample = chunk_peak
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for peak meter: {path}") from exc

    if max_sample == 0:
        return _SILENCE_FLOOR_DBFS

    full_scale = (1 << (sample_width * 8 - 1)) - 1
    ratio = min(max_sample / full_scale, 1.0)
    return 20.0 * math.log10(ratio)
