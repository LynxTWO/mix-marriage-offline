from __future__ import annotations

import hashlib
import io
import struct
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest for a file."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"Failed to read file '{path}': {exc}") from exc
    return digest.hexdigest()


def read_wav_metadata(path: Path) -> dict:
    """Parse RIFF/WAVE headers and return basic WAV metadata."""
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Failed to stat file '{path}': {exc}") from exc

    if file_size < 12:
        raise ValueError(f"WAV file too small to contain RIFF header: '{path}'")

    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) != 12:
                raise ValueError(f"Truncated RIFF header in '{path}'")

            riff_id, riff_size, wave_id = struct.unpack("<4sI4s", header)
            if riff_id != b"RIFF":
                raise ValueError(f"Unsupported RIFF id {riff_id!r} in '{path}'")
            if wave_id != b"WAVE":
                raise ValueError(f"Missing WAVE identifier in '{path}'")
            if riff_size + 8 > file_size:
                raise ValueError(f"RIFF size exceeds file size in '{path}'")

            fmt_fields = None
            data_bytes = None

            while handle.tell() + 8 <= file_size:
                chunk_header = handle.read(8)
                if len(chunk_header) != 8:
                    raise ValueError(f"Truncated chunk header in '{path}'")

                chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
                chunk_start = handle.tell()
                chunk_end = chunk_start + chunk_size

                if chunk_end > file_size:
                    raise ValueError(
                        f"Truncated chunk {chunk_id!r} (size {chunk_size}) in '{path}'"
                    )

                if chunk_id == b"fmt ":
                    chunk_data = handle.read(chunk_size)
                    if len(chunk_data) != chunk_size:
                        raise ValueError(f"Truncated fmt chunk in '{path}'")
                    if chunk_size < 16:
                        raise ValueError(f"fmt chunk too small in '{path}'")
                    fmt_fields = struct.unpack("<HHIIHH", chunk_data[:16])
                elif chunk_id == b"data":
                    data_bytes = chunk_size
                    handle.seek(chunk_size, io.SEEK_CUR)
                else:
                    handle.seek(chunk_size, io.SEEK_CUR)

                if chunk_size % 2 == 1:
                    if handle.tell() + 1 > file_size:
                        raise ValueError(f"Truncated padding byte after {chunk_id!r}")
                    handle.seek(1, io.SEEK_CUR)

                if fmt_fields is not None and data_bytes is not None:
                    break
    except OSError as exc:
        raise ValueError(f"Failed to read WAV file '{path}': {exc}") from exc

    if fmt_fields is None:
        raise ValueError(f"Missing fmt chunk in '{path}'")
    if data_bytes is None:
        raise ValueError(f"Missing data chunk in '{path}'")

    (
        audio_format,
        channels,
        sample_rate_hz,
        byte_rate,
        block_align,
        bits_per_sample,
    ) = fmt_fields

    if channels <= 0:
        raise ValueError(f"Invalid channel count {channels} in '{path}'")
    if sample_rate_hz <= 0:
        raise ValueError(f"Invalid sample rate {sample_rate_hz} in '{path}'")
    if bits_per_sample <= 0:
        raise ValueError(f"Invalid bits per sample {bits_per_sample} in '{path}'")
    if block_align <= 0:
        raise ValueError(f"Invalid block alignment {block_align} in '{path}'")

    num_frames = data_bytes // block_align
    duration_s = num_frames / sample_rate_hz

    return {
        "audio_format": audio_format,
        "channels": channels,
        "sample_rate_hz": sample_rate_hz,
        "bits_per_sample": bits_per_sample,
        "num_frames": num_frames,
        "duration_s": duration_s,
        "data_bytes": data_bytes,
        "byte_rate": byte_rate,
        "block_align": block_align,
    }
