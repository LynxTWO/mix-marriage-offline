from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.backends.ffprobe_meta import find_ffprobe, read_metadata_ffprobe
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.sample_rate import iter_resampled_float64_samples


class DecoderError(Exception):
    """Raised when a decoder backend cannot process an input."""


_EXTENSION_FORMATS = {
    ".wav": "wav",
    ".wave": "wav",
    ".flac": "flac",
    ".wv": "wavpack",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".ape": "ape",
    ".mp3": "mp3",
    ".aac": "aac",
    ".ogg": "ogg",
    ".opus": "opus",
    ".m4a": "m4a",
}
_WAV_FORMAT_ID = "wav"
_FFMPEG_ONLY_FORMAT_IDS = frozenset(
    {
        "flac",
        "wavpack",
        "aiff",
        "ape",
        "mp3",
        "aac",
        "ogg",
        "opus",
        "m4a",
    }
)
_LOSSLESS_FORMAT_IDS = frozenset({"wav", "flac", "wavpack", "aiff", "ape"})
_LOSSY_FORMAT_IDS = frozenset({"mp3", "aac", "ogg", "opus"})


def detect_format_from_path(path: Path) -> str:
    """Return a format id based on the file extension."""
    return _EXTENSION_FORMATS.get(path.suffix.lower(), "unknown")


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        candidate = int(value)
        return candidate if candidate > 0 else None
    if isinstance(value, str) and value.strip():
        try:
            candidate = int(value.strip())
        except ValueError:
            return None
        return candidate if candidate > 0 else None
    return None


def is_lossless_format_id(format_id: str, *, codec_name: str | None = None) -> bool:
    normalized = format_id.strip().lower()
    if normalized in _LOSSLESS_FORMAT_IDS:
        return True
    if normalized in _LOSSY_FORMAT_IDS:
        return False
    if normalized == "m4a":
        normalized_codec = codec_name.lower().strip() if isinstance(codec_name, str) else ""
        return normalized_codec == "alac"
    return False


def read_audio_metadata(path: Path) -> dict:
    format_id = detect_format_from_path(path)
    if format_id == _WAV_FORMAT_ID:
        return read_wav_metadata(path)
    if format_id == "unknown":
        raise NotImplementedError(f"No decoder backend for format '{format_id}'")
    if find_ffprobe() is not None:
        metadata = read_metadata_ffprobe(path)
        if format_id == "m4a":
            codec_name = metadata.get("codec_name")
            if isinstance(codec_name, str):
                metadata["codec_name"] = codec_name.lower()
        return metadata
    raise NotImplementedError(f"No decoder backend for format '{format_id}'")


def read_metadata(path: Path) -> dict:
    """Compatibility alias for existing callers."""
    return read_audio_metadata(path)


def _iter_frame_aligned_samples(
    float_samples_iter: Iterator[list[float]],
    *,
    channels: int,
) -> Iterator[list[float]]:
    for chunk in float_samples_iter:
        if not chunk:
            continue
        if len(chunk) % channels != 0:
            raise ValueError("decoder returned non-frame-aligned sample data")
        yield [float(sample) for sample in chunk]


def iter_audio_float64_samples(
    path: Path,
    *,
    error_context: str,
    chunk_frames: int = 4096,
    metadata: Mapping[str, Any] | None = None,
    ffmpeg_cmd: Sequence[str] | None = None,
    target_sample_rate_hz: int | None = None,
) -> Iterator[list[float]]:
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")

    format_id = detect_format_from_path(path)
    if format_id == "unknown":
        raise NotImplementedError(f"No decoder backend for format '{format_id}'")

    resolved_metadata: Mapping[str, Any]
    if isinstance(metadata, Mapping):
        resolved_metadata = metadata
    else:
        resolved_metadata = read_audio_metadata(path)

    channels = _coerce_positive_int(resolved_metadata.get("channels"))
    source_sample_rate_hz = _coerce_positive_int(resolved_metadata.get("sample_rate_hz"))
    if channels is None:
        raise ValueError(f"invalid channel count in metadata for {path}")
    if source_sample_rate_hz is None:
        raise ValueError(f"invalid sample rate in metadata for {path}")

    if format_id == _WAV_FORMAT_ID:
        source_iter = iter_wav_float64_samples(path, error_context=error_context)
    elif format_id in _FFMPEG_ONLY_FORMAT_IDS:
        decoder_cmd = list(ffmpeg_cmd) if ffmpeg_cmd is not None else resolve_ffmpeg_cmd()
        if decoder_cmd is None:
            raise ValueError(
                "ffmpeg not available for non-WAV decode; install ffmpeg or set MMO_FFMPEG_PATH"
            )
        source_iter = iter_ffmpeg_float64_samples(
            path,
            decoder_cmd,
            chunk_frames=chunk_frames,
        )
    else:
        raise NotImplementedError(f"No decoder backend for format '{format_id}'")

    aligned_iter = _iter_frame_aligned_samples(source_iter, channels=channels)
    if target_sample_rate_hz is None or int(target_sample_rate_hz) == source_sample_rate_hz:
        yield from aligned_iter
        return

    target_rate = _coerce_positive_int(target_sample_rate_hz)
    if target_rate is None:
        raise ValueError("target_sample_rate_hz must be a positive integer")

    yield from iter_resampled_float64_samples(
        aligned_iter,
        channels=channels,
        source_sample_rate_hz=source_sample_rate_hz,
        target_sample_rate_hz=target_rate,
        chunk_frames=chunk_frames,
    )
