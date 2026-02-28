from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterator, Sequence

from mmo.core.loudness_methods import DEFAULT_LOUDNESS_METHOD_ID
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.decoders import read_metadata
from mmo.dsp.meters import compute_basic_stats_from_float64, iter_wav_float64_samples

_WAV_EXTENSIONS = frozenset({".wav", ".wave"})


def _dbfs_or_none(value: float) -> float | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(float(value), 4)


def _peak_dbfs_or_none(peak_linear: float) -> float | None:
    if (
        not isinstance(peak_linear, (int, float))
        or not math.isfinite(peak_linear)
        or peak_linear <= 0.0
    ):
        return None
    return round(20.0 * math.log10(float(peak_linear)), 4)


def _iter_ffmpeg_frame_chunks(
    *,
    path: Path,
    ffmpeg_cmd: Sequence[str],
    channels: int,
    np_module: Any,
) -> Iterator[Any]:
    carry: list[float] = []
    for float_samples in iter_ffmpeg_float64_samples(path, ffmpeg_cmd):
        data = carry + float_samples
        remainder = len(data) % channels
        if remainder:
            carry = data[-remainder:]
            data = data[:-remainder]
        else:
            carry = []
        if not data:
            continue
        frames = np_module.asarray(data, dtype=np_module.float64).reshape(-1, channels)
        if frames.size > 0:
            yield frames


def _integrated_lufs_or_none(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
) -> float | None:
    suffix = path.suffix.lower()
    if suffix in _WAV_EXTENSIONS:
        try:
            from mmo.dsp.meters_truth import compute_lufs_integrated_wav
        except (ImportError, ValueError):
            return None
        try:
            return _dbfs_or_none(
                compute_lufs_integrated_wav(
                    path,
                    method_id=DEFAULT_LOUDNESS_METHOD_ID,
                )
            )
        except ValueError:
            return None

    if not ffmpeg_cmd:
        return None

    try:
        import numpy as np
        from mmo.dsp.meters_truth import compute_lufs_integrated_from_chunks
    except (ImportError, ValueError):
        return None

    try:
        metadata = read_metadata(path)
    except (NotImplementedError, ValueError):
        return None
    channels = int(metadata.get("channels") or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz") or 0)
    if channels <= 0 or sample_rate_hz <= 0:
        return None

    try:
        lufs = compute_lufs_integrated_from_chunks(
            _iter_ffmpeg_frame_chunks(
                path=path,
                ffmpeg_cmd=ffmpeg_cmd,
                channels=channels,
                np_module=np,
            ),
            sample_rate_hz,
            channels,
            channel_mask=metadata.get("channel_mask"),
            channel_layout=(
                str(metadata.get("channel_layout", "")).strip().lower() or None
            ),
            method_id=DEFAULT_LOUDNESS_METHOD_ID,
        )
    except ValueError:
        return None
    return _dbfs_or_none(lufs)


def compute_stream_meters(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
) -> dict[str, float | None]:
    samples_iter: Iterator[list[float]]
    suffix = path.suffix.lower()
    try:
        if suffix in _WAV_EXTENSIONS:
            samples_iter = iter_wav_float64_samples(
                path,
                error_context="render_execute meters",
            )
        elif ffmpeg_cmd:
            samples_iter = iter_ffmpeg_float64_samples(path, ffmpeg_cmd)
        else:
            return {"peak_dbfs": None, "rms_dbfs": None, "integrated_lufs": None}
        peak_linear, _, _, rms_dbfs, _ = compute_basic_stats_from_float64(samples_iter)
    except ValueError:
        return {"peak_dbfs": None, "rms_dbfs": None, "integrated_lufs": None}

    return {
        "peak_dbfs": _peak_dbfs_or_none(peak_linear),
        "rms_dbfs": _dbfs_or_none(rms_dbfs),
        "integrated_lufs": _integrated_lufs_or_none(path, ffmpeg_cmd=ffmpeg_cmd),
    }
