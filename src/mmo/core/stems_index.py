from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from mmo.core.media_tags import source_metadata_from_probe
from mmo.core.session import discover_stem_files
from mmo.core.stem_identity import (
    canonical_stem_ids_for_rel_paths,
    source_file_id_from_rel_path,
)
from mmo.dsp.decoders import read_metadata

STEMS_INDEX_VERSION = "0.1.0"
_SET_ID_PREFIX = "STEMSET."
_TRACK_PREFIX_RE = re.compile(r"^\s*\d+\s*[-_.\s]+\s*")
_TOKEN_SPLIT_RE = re.compile(r"[\s_.\-\[\]\(\)\{\}]+")
_SET_HINT_TOKENS = frozenset({"stems", "multitrack", "tracks", "audio", "wav", "split"})
_LEFT_LONG_TOKENS = frozenset({"left", "lf", "lt", "lft", "lhs", "lch"})
_RIGHT_LONG_TOKENS = frozenset({"right", "rf", "rt", "rgt", "rhs", "rch"})


def _sha1_token(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _to_posix(path_value: str) -> str:
    return path_value.replace("\\", "/")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_posix(path: Path, *, root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root:
        return "."
    if _is_relative_to(resolved_path, resolved_root):
        return resolved_path.relative_to(resolved_root).as_posix()
    return resolved_path.as_posix()


def _normalize_lr_token(token: str) -> str:
    if token == "l":
        return "l"
    if token == "r":
        return "r"
    if token in _LEFT_LONG_TOKENS:
        return "left"
    if token in _RIGHT_LONG_TOKENS:
        return "right"
    return token


def _tokenize_value(value: str) -> list[str]:
    lowered = value.lower()
    normalized = _TRACK_PREFIX_RE.sub("", lowered, count=1)
    parts = [part for part in _TOKEN_SPLIT_RE.split(normalized) if part]
    return [_normalize_lr_token(part) for part in parts]


def _folder_tokens_for_rel_dir(rel_dir: str) -> list[str]:
    if rel_dir == ".":
        return []
    tokens: list[str] = []
    for segment in rel_dir.split("/"):
        tokens.extend(_tokenize_value(segment))
    return tokens


def _score_set(folder_tokens: list[str]) -> tuple[int, str]:
    matched = sorted({token for token in folder_tokens if token in _SET_HINT_TOKENS})
    score = len(matched)
    if matched:
        return score, f"folder hints: {', '.join(matched)}"
    return score, "folder hints: none"


def _set_rank_key(item: dict[str, Any]) -> tuple[int, int, str]:
    score_hint = item.get("score_hint")
    file_count = item.get("file_count")
    rel_dir = item.get("rel_dir")

    normalized_score = score_hint if isinstance(score_hint, int) else 0
    normalized_file_count = file_count if isinstance(file_count, int) else 0
    normalized_rel_dir = rel_dir if isinstance(rel_dir, str) else ""
    return (-normalized_score, -normalized_file_count, normalized_rel_dir)


def _validated_root(root: Path) -> Path:
    # Resolve once up front so every rel_path and set_id is anchored to one
    # stable root. Mixed roots would change IDs for the same files.
    resolved = root.resolve()
    if not resolved.exists():
        raise ValueError(f"Root directory does not exist: {root}")
    if not resolved.is_dir():
        raise ValueError(f"Root path must be a directory: {root}")
    return resolved


def _source_metadata_for_file(path: Path) -> dict[str, Any]:
    try:
        metadata = read_metadata(path)
    except (ValueError, NotImplementedError):
        # Leave the file in the index even when probe metadata is missing.
        # Intake needs a stable row and a warning, not a silent drop.
        return {
            "technical": {},
            "tags": {
                "raw": [],
                "normalized": {},
                "warnings": ["Source metadata unavailable."],
            },
        }
    return source_metadata_from_probe(metadata)


def discover_audio_files(root: Path) -> list[Path]:
    """Discover known-audio files using the existing core extension allowlist."""
    return discover_stem_files(_validated_root(root))


def find_stem_sets(root: Path) -> list[Path]:
    """Discover candidate stem-set directories under root."""
    resolved_root = _validated_root(root)
    audio_files = discover_audio_files(resolved_root)
    if not audio_files:
        return []

    # If audio already lives at the root, treat the root as the set. Splitting
    # it into synthetic child sets would change IDs and duplicate coverage.
    if any(path.parent.resolve() == resolved_root for path in audio_files):
        return [resolved_root]

    audio_dirs = sorted({path.parent.resolve() for path in audio_files}, key=lambda p: p.as_posix())
    leaf_dirs: list[Path] = []
    for candidate in audio_dirs:
        # When the root is only a container, prefer leaf stem-set dirs so the
        # same nested audio tree does not produce overlapping parent and child
        # candidates.
        has_audio_child = any(
            other != candidate and _is_relative_to(other, candidate)
            for other in audio_dirs
        )
        if not has_audio_child:
            leaf_dirs.append(candidate)
    return leaf_dirs


def _collect_stem_sets(root: Path) -> list[dict[str, Any]]:
    resolved_root = _validated_root(root)
    stem_sets: list[dict[str, Any]] = []
    for set_path in find_stem_sets(resolved_root):
        rel_dir = _relative_posix(set_path, root=resolved_root)
        set_files = discover_audio_files(set_path)
        folder_tokens = _folder_tokens_for_rel_dir(rel_dir)
        score_hint, why = _score_set(folder_tokens)
        stem_sets.append(
            {
                "set_id": f"{_SET_ID_PREFIX}{_sha1_token(rel_dir)}",
                "rel_dir": rel_dir,
                "file_count": len(set_files),
                "score_hint": score_hint,
                "why": why,
                "_set_path": set_path,
                "_files": set_files,
                "_folder_tokens": folder_tokens,
            }
        )
    # Deterministic ranking keeps "best set" picks stable when several folders
    # look like plausible stem roots.
    stem_sets.sort(key=_set_rank_key)
    return stem_sets


def resolve_stem_sets(root: Path) -> list[dict[str, Any]]:
    stem_sets = _collect_stem_sets(root)
    return [
        {
            "set_id": item["set_id"],
            "rel_dir": item["rel_dir"],
            "file_count": item["file_count"],
            "score_hint": item["score_hint"],
            "why": item["why"],
        }
        for item in stem_sets
    ]


def pick_best_stem_set(stem_sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in stem_sets if isinstance(item, dict)]
    if not candidates:
        return None
    ranked = sorted(candidates, key=_set_rank_key)
    return ranked[0]


def build_stems_index(root: Path, *, root_dir: str | None = None) -> dict[str, Any]:
    resolved_root = _validated_root(root)
    stem_sets = _collect_stem_sets(resolved_root)
    public_sets = [
        {
            "set_id": item["set_id"],
            "rel_dir": item["rel_dir"],
            "file_count": item["file_count"],
            "score_hint": item["score_hint"],
            "why": item["why"],
        }
        for item in stem_sets
    ]

    files: list[dict[str, Any]] = []
    # Relative paths are the portable intake contract. Stem and source IDs
    # derive from them so the same tree keeps its identity on another machine.
    rel_paths = [
        _relative_posix(file_path, root=resolved_root)
        for stem_set in stem_sets
        for file_path in stem_set["_files"]
    ]
    stem_ids_by_rel_path = canonical_stem_ids_for_rel_paths(rel_paths)
    for stem_set in stem_sets:
        set_id = stem_set["set_id"]
        folder_tokens = list(stem_set["_folder_tokens"])
        for file_path in stem_set["_files"]:
            rel_path = _relative_posix(file_path, root=resolved_root)
            basename = file_path.stem
            files.append(
                {
                    "stem_id": stem_ids_by_rel_path.get(rel_path, "stem"),
                    "source_file_id": source_file_id_from_rel_path(rel_path),
                    "set_id": set_id,
                    "rel_path": rel_path,
                    "basename": basename,
                    "ext": file_path.suffix.lower(),
                    "tokens": _tokenize_value(basename),
                    "folder_tokens": folder_tokens,
                    "source_metadata": _source_metadata_for_file(file_path),
                }
            )
    # Sort once here so later classifiers and planners inherit one file order
    # instead of whatever the filesystem returned.
    files.sort(
        key=lambda item: (
            item["set_id"],
            item["rel_path"],
            item["stem_id"],
        )
    )

    root_dir_value = root_dir if isinstance(root_dir, str) else _to_posix(str(root))
    return {
        "version": STEMS_INDEX_VERSION,
        "root_dir": root_dir_value,
        "stem_sets": public_sets,
        "files": files,
    }
