from __future__ import annotations

import re
from pathlib import Path

from mmo.dsp.decoders import detect_format_from_path, read_metadata
from mmo.dsp.io import sha256_file

_STEM_ID_RE = re.compile(r"[^a-z0-9_]+")


def _stem_id_from_filename(path: Path) -> str:
    stem = path.stem.lower()
    stem = stem.replace(" ", "_")
    stem = _STEM_ID_RE.sub("_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    return stem or "stem"


def discover_stem_files(stems_dir: Path) -> list[Path]:
    """Discover known-audio stems under a directory (case-insensitive extension)."""
    extensions = {
        ".wav",
        ".wave",
        ".flac",
        ".wv",
        ".aiff",
        ".aif",
        ".mp3",
        ".aac",
        ".ogg",
        ".opus",
        ".m4a",
    }
    stems = [
        path
        for path in stems_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ]
    stems.sort(key=lambda p: p.as_posix().lower())
    return stems


def build_session_from_stems_dir(stems_dir: Path) -> dict:
    stems = discover_stem_files(stems_dir)
    stem_entries = []

    for path in stems:
        try:
            rel_path = path.relative_to(stems_dir)
            file_path = rel_path.as_posix()
        except ValueError:
            file_path = path.resolve().as_posix()

        stem_entry = {
            "stem_id": _stem_id_from_filename(path),
            "file_path": file_path,
            "sha256": sha256_file(path),
        }
        format_id = detect_format_from_path(path)
        try:
            metadata = read_metadata(path)
        except (ValueError, NotImplementedError):
            metadata = None
        if metadata:
            stem_entry.update(
                {
                    "channel_count": metadata["channels"],
                    "sample_rate_hz": metadata["sample_rate_hz"],
                    "duration_s": metadata["duration_s"],
                }
            )
            bits_per_sample = metadata.get("bits_per_sample")
            if isinstance(bits_per_sample, int):
                stem_entry["bits_per_sample"] = bits_per_sample
            codec_name = metadata.get("codec_name")
            if isinstance(codec_name, str) and codec_name:
                stem_entry["codec_name"] = codec_name
            channel_layout = metadata.get("channel_layout")
            if isinstance(channel_layout, str) and channel_layout:
                stem_entry["channel_layout"] = channel_layout
            if format_id == "wav":
                stem_entry.update(
                    {
                        "wav_audio_format": metadata["audio_format"],
                        "wav_audio_format_resolved": metadata.get(
                            "audio_format_resolved", metadata["audio_format"]
                        ),
                    }
                )
                channel_mask = metadata.get("channel_mask")
                if channel_mask is not None:
                    stem_entry["wav_channel_mask"] = channel_mask
        stem_entries.append(stem_entry)

    return {"stems": stem_entries}
