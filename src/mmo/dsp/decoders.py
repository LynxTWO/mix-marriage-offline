from __future__ import annotations

from pathlib import Path

from mmo.dsp.io import read_wav_metadata


class DecoderError(Exception):
    """Raised when a decoder backend cannot process an input."""


_EXTENSION_FORMATS = {
    ".wav": "wav",
    ".wave": "wav",
    ".flac": "flac",
    ".wv": "wavpack",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".mp3": "mp3",
    ".aac": "aac",
    ".ogg": "ogg",
    ".opus": "opus",
    ".m4a": "m4a",
}


def detect_format_from_path(path: Path) -> str:
    """Return a format id based on the file extension."""
    return _EXTENSION_FORMATS.get(path.suffix.lower(), "unknown")


def read_metadata(path: Path) -> dict:
    format_id = detect_format_from_path(path)
    if format_id == "wav":
        return read_wav_metadata(path)
    raise NotImplementedError(f"No decoder backend for format '{format_id}'")
