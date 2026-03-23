from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any


def coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def normalize_posix_ref(value: Any) -> str:
    return coerce_str(value).strip().replace("\\", "/")


def is_absolute_posix_path(path_text: str) -> bool:
    normalized = normalize_posix_ref(path_text)
    if not normalized:
        return False
    if normalized.startswith("/"):
        return True
    if normalized.startswith("//"):
        return True
    return len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/" and normalized[0].isalpha()


def path_from_posix_ref(path_text: str) -> Path:
    pure = PurePosixPath(normalize_posix_ref(path_text))
    return Path(*pure.parts) if pure.parts else Path()


def relative_posix_ref(
    *,
    anchor_dir: Path,
    target_path: Path,
) -> str | None:
    try:
        relative = os.path.relpath(
            target_path.resolve(),
            start=anchor_dir.resolve(),
        )
    except (OSError, ValueError):
        return None
    return normalize_posix_ref(relative) or "."


def resolve_posix_ref(
    path_text: str,
    *,
    anchor_dir: Path,
) -> Path:
    normalized = normalize_posix_ref(path_text)
    if is_absolute_posix_path(normalized):
        return Path(normalized)
    return (anchor_dir / path_from_posix_ref(normalized)).resolve()


def portable_path_ref(
    value: Any,
    *,
    anchor_dir: Path | None,
    fallback: str | None = None,
) -> str | None:
    normalized = normalize_posix_ref(value)
    if not normalized:
        return None
    if not is_absolute_posix_path(normalized):
        return normalized
    if anchor_dir is not None:
        relative = relative_posix_ref(
            anchor_dir=anchor_dir,
            target_path=Path(normalized),
        )
        if relative:
            return relative
    fallback_normalized = normalize_posix_ref(fallback)
    if fallback_normalized and not is_absolute_posix_path(fallback_normalized):
        return fallback_normalized
    return Path(normalized).name or None
