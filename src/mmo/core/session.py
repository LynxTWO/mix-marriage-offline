from __future__ import annotations

from pathlib import Path

from mmo.core.media_tags import source_metadata_from_probe
from mmo.core.stem_identity import (
    canonical_stem_ids_for_rel_paths,
    source_file_id_from_rel_path,
)
from mmo.core.source_locator import resolve_session_stems
from mmo.dsp.decoders import detect_format_from_path, read_metadata
from mmo.dsp.io import sha256_file


def discover_stem_files(stems_dir: Path) -> list[Path]:
    """Discover known-audio stems under a directory (case-insensitive extension)."""
    # Keep the intake allowlist explicit so session builds ignore unrelated
    # workspace files and produce the same stem set on repeated scans.
    extensions = {
        ".wav",
        ".wave",
        ".flac",
        ".wv",
        ".aiff",
        ".aif",
        ".ape",
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
    # Sort before hashing and id assignment so session assembly does not depend
    # on filesystem walk order.
    stems.sort(key=lambda p: p.as_posix().lower())
    return stems


def build_session_from_stems_dir(stems_dir: Path) -> dict:
    resolved_stems_dir = stems_dir.resolve()
    stems = discover_stem_files(resolved_stems_dir)
    rel_paths_by_source: list[tuple[Path, str]] = []
    for path in stems:
        try:
            # Relative paths keep sessions portable. Fall back to an absolute
            # path only when the source is already outside the chosen stems root.
            rel_path = path.relative_to(resolved_stems_dir).as_posix()
        except ValueError:
            rel_path = path.resolve().as_posix()
        rel_paths_by_source.append((path, rel_path))

    stem_ids_by_rel_path = canonical_stem_ids_for_rel_paths(
        rel_path for _, rel_path in rel_paths_by_source
    )
    stem_entries = []

    for path, file_path in rel_paths_by_source:
        stem_entry = {
            "stem_id": stem_ids_by_rel_path.get(file_path, "stem"),
            "file_path": file_path,
            "source_file_id": source_file_id_from_rel_path(file_path),
            "sha256": sha256_file(path),
        }
        format_id = detect_format_from_path(path)
        try:
            metadata = read_metadata(path)
        except (ValueError, NotImplementedError):
            # Metadata gaps should not block session creation. Later validation
            # and locator passes can still work from ids, hashes, and file paths.
            metadata = None
        if metadata:
            source_metadata = source_metadata_from_probe(metadata)
            stem_entry.update(
                {
                    "channel_count": metadata["channels"],
                    "sample_rate_hz": metadata["sample_rate_hz"],
                    "duration_s": metadata["duration_s"],
                }
            )
            stem_entry["source_metadata"] = source_metadata
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

    session = {
        "stems_dir": resolved_stems_dir.as_posix(),
        "stems": stem_entries,
    }
    # Every freshly built session goes through the shared locator policy so
    # analysis, scene, and render code all see the same canonical stem fields.
    resolve_session_stems(session, mutate=True)
    return session
