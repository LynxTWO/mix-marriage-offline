from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict


def find_ffprobe() -> Path | None:
    env_path = os.environ.get("MMO_FFPROBE_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate
        return None

    found = shutil.which("ffprobe")
    if not found:
        return None
    return Path(found)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def read_metadata_ffprobe(path: Path) -> Dict[str, Any]:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise ValueError("ffprobe not available")

    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"ffprobe failed: {exc}") from exc

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid JSON: {exc}") from exc

    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ValueError("ffprobe JSON missing streams")

    audio_stream = None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            audio_stream = stream
            break
    if audio_stream is None:
        raise ValueError("ffprobe JSON missing audio stream")

    channels = _parse_int(audio_stream.get("channels"))
    sample_rate = _parse_int(audio_stream.get("sample_rate"))
    if channels is None or channels <= 0:
        raise ValueError("ffprobe JSON missing channels")
    if sample_rate is None or sample_rate <= 0:
        raise ValueError("ffprobe JSON missing sample_rate")

    duration = _parse_float(audio_stream.get("duration"))
    if duration is None:
        fmt = payload.get("format")
        if isinstance(fmt, dict):
            duration = _parse_float(fmt.get("duration"))
    if duration is None:
        raise ValueError("ffprobe JSON missing duration")

    bits_per_sample = _parse_int(audio_stream.get("bits_per_raw_sample"))
    codec_name = audio_stream.get("codec_name")

    metadata: Dict[str, Any] = {
        "channels": channels,
        "sample_rate_hz": sample_rate,
        "duration_s": duration,
    }
    if bits_per_sample is not None and bits_per_sample > 0:
        metadata["bits_per_sample"] = bits_per_sample
    if isinstance(codec_name, str) and codec_name:
        metadata["codec_name"] = codec_name

    return metadata
