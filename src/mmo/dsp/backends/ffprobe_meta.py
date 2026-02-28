from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict

from mmo.core.media_tags import RawTag, canonicalize_tag_bag, tag_bag_to_mapping


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


def _ffprobe_container(payload: Dict[str, Any], *, path: Path) -> str:
    fmt = payload.get("format")
    if isinstance(fmt, dict):
        format_name = fmt.get("format_name")
        if isinstance(format_name, str) and format_name.strip():
            first_name = format_name.split(",", 1)[0].strip().lower()
            if first_name:
                return first_name
    suffix = path.suffix.strip().lower().lstrip(".")
    return suffix or "unknown"


def _extract_ffprobe_tags(payload: Dict[str, Any], *, container: str) -> dict[str, Any]:
    raw_tags: list[RawTag] = []
    warnings: list[str] = []

    fmt = payload.get("format")
    if isinstance(fmt, dict):
        format_tags = fmt.get("tags")
        if isinstance(format_tags, dict):
            for raw_key in sorted(format_tags.keys(), key=lambda value: str(value).lower()):
                if not isinstance(raw_key, str) or not raw_key.strip():
                    continue
                raw_value = format_tags.get(raw_key)
                if raw_value is None:
                    continue
                raw_tags.append(
                    RawTag(
                        source="format",
                        container=container,
                        scope="format",
                        key=raw_key,
                        value=str(raw_value),
                        index=0,
                    )
                )
        elif format_tags is not None:
            warnings.append("ffprobe format.tags is not an object")

    streams = payload.get("streams")
    if isinstance(streams, list):
        for stream_index, stream in enumerate(streams):
            if not isinstance(stream, dict):
                continue
            stream_tags = stream.get("tags")
            if stream_tags is None:
                continue
            if not isinstance(stream_tags, dict):
                warnings.append(f"ffprobe stream[{stream_index}] tags is not an object")
                continue
            for raw_key in sorted(stream_tags.keys(), key=lambda value: str(value).lower()):
                if not isinstance(raw_key, str) or not raw_key.strip():
                    continue
                raw_value = stream_tags.get(raw_key)
                if raw_value is None:
                    continue
                raw_tags.append(
                    RawTag(
                        source="stream",
                        container=container,
                        scope=f"stream:{stream_index}",
                        key=raw_key,
                        value=str(raw_value),
                        index=stream_index,
                    )
                )

    return tag_bag_to_mapping(canonicalize_tag_bag(raw_tags, warnings))


def read_metadata_ffprobe(path: Path) -> Dict[str, Any]:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise ValueError("ffprobe not available")

    if ffprobe.suffix.lower() == ".py":
        base_cmd = [sys.executable, str(ffprobe)]
    else:
        base_cmd = [str(ffprobe)]
    cmd = base_cmd + [
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
    channel_layout = audio_stream.get("channel_layout")

    metadata: Dict[str, Any] = {
        "channels": channels,
        "sample_rate_hz": sample_rate,
        "duration_s": duration,
    }
    if bits_per_sample is not None and bits_per_sample > 0:
        metadata["bits_per_sample"] = bits_per_sample
    if isinstance(codec_name, str) and codec_name:
        metadata["codec_name"] = codec_name
    if isinstance(channel_layout, str):
        normalized = channel_layout.strip().lower()
        if normalized:
            metadata["channel_layout"] = normalized

    metadata["tags"] = _extract_ffprobe_tags(
        payload,
        container=_ffprobe_container(payload, path=path),
    )

    return metadata
