from __future__ import annotations

import re
from pathlib import Path

from mmo.dsp.io import read_wav_metadata, sha256_file

_STEM_ID_RE = re.compile(r"[^a-z0-9_]+")


def _stem_id_from_filename(path: Path) -> str:
    stem = path.stem.lower()
    stem = stem.replace(" ", "_")
    stem = _STEM_ID_RE.sub("_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    return stem or "stem"


def discover_stem_files(stems_dir: Path) -> list[Path]:
    """Discover WAV stems under a directory (case-insensitive extension)."""
    stems = [
        path
        for path in stems_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".wav"
    ]
    stems.sort(key=lambda p: p.as_posix().lower())
    return stems


def build_session_from_stems_dir(stems_dir: Path) -> dict:
    stems = discover_stem_files(stems_dir)
    stem_entries = []

    for path in stems:
        metadata = read_wav_metadata(path)
        try:
            rel_path = path.relative_to(stems_dir)
            file_path = rel_path.as_posix()
        except ValueError:
            file_path = path.resolve().as_posix()

        stem_entries.append(
            {
                "stem_id": _stem_id_from_filename(path),
                "file_path": file_path,
                "sha256": sha256_file(path),
                "channel_count": metadata["channels"],
                "sample_rate_hz": metadata["sample_rate_hz"],
                "duration_s": metadata["duration_s"],
            }
        )

    return {"stems": stem_entries}
