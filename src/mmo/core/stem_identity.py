from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Iterable

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GENERIC_PARENT_TOKENS = frozenset(
    {
        "audio",
        "audios",
        "file",
        "files",
        "project",
        "projects",
        "session",
        "sessions",
        "source",
        "sources",
        "stem",
        "stems",
        "track",
        "tracks",
    }
)


def _sha1_token(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _slug_token(value: str) -> str:
    lowered = value.lower().replace("\\", "/")
    normalized = _SLUG_RE.sub("_", lowered)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def normalize_relative_source_path(rel_path: str) -> str:
    normalized_input = str(rel_path or "").strip().replace("\\", "/")
    if not normalized_input:
        return ""

    parts: list[str] = []
    for raw_part in PurePosixPath(normalized_input).parts:
        if raw_part in {"", "."}:
            continue
        if raw_part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(raw_part)
    return "/".join(parts)


def canonical_stem_id_from_rel_path(rel_path: str) -> str:
    normalized_rel_path = normalize_relative_source_path(rel_path)
    if not normalized_rel_path:
        return "stem"
    base_name = PurePosixPath(normalized_rel_path).stem
    return _slug_token(base_name) or "stem"


def canonical_stem_id_from_path(path: Path, root: Path | None = None) -> str:
    if root is not None:
        try:
            rel_path = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel_path = path.resolve().as_posix()
    else:
        rel_path = path.as_posix()
    return canonical_stem_id_from_rel_path(rel_path)


def source_file_id_from_rel_path(rel_path: str) -> str:
    normalized_rel_path = normalize_relative_source_path(rel_path)
    return f"SOURCEFILE.{_sha1_token(normalized_rel_path)}"


def _parent_identity_tokens(rel_path: str) -> list[str]:
    normalized_rel_path = normalize_relative_source_path(rel_path)
    if not normalized_rel_path:
        return []
    tokens: list[str] = []
    for segment in reversed(PurePosixPath(normalized_rel_path).parent.parts):
        token = _slug_token(segment)
        if not token or token in _GENERIC_PARENT_TOKENS:
            continue
        tokens.append(token)
    return tokens


def canonical_stem_ids_for_rel_paths(rel_paths: Iterable[str]) -> dict[str, str]:
    normalized_paths = sorted(
        {
            normalize_relative_source_path(rel_path)
            for rel_path in rel_paths
            if normalize_relative_source_path(rel_path)
        }
    )
    if not normalized_paths:
        return {}

    base_ids = {
        rel_path: canonical_stem_id_from_rel_path(rel_path)
        for rel_path in normalized_paths
    }
    parents_by_path = {
        rel_path: _parent_identity_tokens(rel_path)
        for rel_path in normalized_paths
    }

    grouped_paths: dict[str, list[str]] = {}
    for rel_path in normalized_paths:
        grouped_paths.setdefault(base_ids[rel_path], []).append(rel_path)

    resolved_ids: dict[str, str] = {}
    for base_id in sorted(grouped_paths.keys()):
        group_paths = sorted(grouped_paths[base_id])
        if len(group_paths) == 1:
            resolved_ids[group_paths[0]] = base_id
            continue

        unresolved = list(group_paths)
        level = 1
        while unresolved:
            candidate_groups: dict[str, list[str]] = {}
            exhausted_paths: list[str] = []
            for rel_path in unresolved:
                parent_tokens = parents_by_path[rel_path]
                if not parent_tokens:
                    exhausted_paths.append(rel_path)
                    continue
                prefix_tokens = parent_tokens[:level]
                if not prefix_tokens:
                    exhausted_paths.append(rel_path)
                    continue
                candidate = "_".join(reversed(prefix_tokens)) + f"_{base_id}"
                candidate_groups.setdefault(candidate, []).append(rel_path)

            next_unresolved: list[str] = []
            for candidate in sorted(candidate_groups.keys()):
                candidate_paths = candidate_groups[candidate]
                if len(candidate_paths) == 1:
                    resolved_ids[candidate_paths[0]] = candidate
                else:
                    next_unresolved.extend(candidate_paths)

            next_unresolved.extend(exhausted_paths)
            if sorted(next_unresolved) == sorted(unresolved):
                for rel_path in sorted(next_unresolved):
                    resolved_ids[rel_path] = f"{base_id}_{_sha1_token(rel_path)[:6]}"
                break

            unresolved = sorted(next_unresolved)
            level += 1

    return resolved_ids
