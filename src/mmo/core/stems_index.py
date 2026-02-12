from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from mmo.core.session import discover_stem_files

STEMS_INDEX_VERSION = "0.1.0"
_SET_ID_PREFIX = "STEMSET."
_FILE_ID_PREFIX = "STEMFILE."
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
    resolved = root.resolve()
    if not resolved.exists():
        raise ValueError(f"Root directory does not exist: {root}")
    if not resolved.is_dir():
        raise ValueError(f"Root path must be a directory: {root}")
    return resolved


def discover_audio_files(root: Path) -> list[Path]:
    """Discover known-audio files using the existing core extension allowlist."""
    return discover_stem_files(_validated_root(root))


def find_stem_sets(root: Path) -> list[Path]:
    """Discover candidate stem-set directories under root."""
    resolved_root = _validated_root(root)
    audio_files = discover_audio_files(resolved_root)
    if not audio_files:
        return []

    if any(path.parent.resolve() == resolved_root for path in audio_files):
        return [resolved_root]

    audio_dirs = sorted({path.parent.resolve() for path in audio_files}, key=lambda p: p.as_posix())
    leaf_dirs: list[Path] = []
    for candidate in audio_dirs:
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
    for stem_set in stem_sets:
        set_id = stem_set["set_id"]
        folder_tokens = list(stem_set["_folder_tokens"])
        for file_path in stem_set["_files"]:
            rel_path = _relative_posix(file_path, root=resolved_root)
            basename = file_path.stem
            files.append(
                {
                    "file_id": f"{_FILE_ID_PREFIX}{_sha1_token(rel_path)}",
                    "set_id": set_id,
                    "rel_path": rel_path,
                    "basename": basename,
                    "ext": file_path.suffix.lower(),
                    "tokens": _tokenize_value(basename),
                    "folder_tokens": folder_tokens,
                }
            )
    files.sort(
        key=lambda item: (
            item["set_id"],
            item["rel_path"],
        )
    )

    root_dir_value = root_dir if isinstance(root_dir, str) else _to_posix(str(root))
    return {
        "version": STEMS_INDEX_VERSION,
        "root_dir": root_dir_value,
        "stem_sets": public_sets,
        "files": files,
    }
