"""Canonical stem source resolution for analysis, scene building, and rendering."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mmo.core.portable_refs import (
    is_absolute_posix_path,
    normalize_posix_ref,
    path_from_posix_ref,
    portable_path_ref,
    relative_posix_ref,
)

RESOLUTION_MODE_FILE_PATH_ABSOLUTE = "file_path_absolute"
RESOLUTION_MODE_STEMS_DIR_RELATIVE = "stems_dir_relative"
RESOLUTION_MODE_WORKSPACE_SOURCE_REF = "workspace_relative_source_ref"
RESOLUTION_MODE_UNRESOLVED = "unresolved"

RESOLVE_ERROR_MISSING_PATH_FIELDS = "STEM_RESOLVE.MISSING_PATH_FIELDS"
RESOLVE_ERROR_MISSING_STEMS_DIR = "STEM_RESOLVE.MISSING_STEMS_DIR"
RESOLVE_ERROR_MISSING_WORKSPACE_DIR = "STEM_RESOLVE.MISSING_WORKSPACE_DIR"
RESOLVE_ERROR_NOT_FOUND = "STEM_RESOLVE.NOT_FOUND"

_LOCATOR_FIELD_NAMES = (
    "file_path",
    "workspace_relative_path",
    "source_ref",
    "resolution_mode",
    "resolved_path",
    "resolve_error_code",
    "resolve_error_detail",
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _normalize_path_text(value: Any) -> str:
    return normalize_posix_ref(value)


def _looks_absolute_path(path_text: str) -> bool:
    return is_absolute_posix_path(path_text)


def _relative_path_from_text(path_text: str) -> Path:
    return path_from_posix_ref(path_text)


def _normalize_workspace_relative_path(value: Any) -> str | None:
    normalized = _normalize_path_text(value)
    if not normalized or _looks_absolute_path(normalized):
        return None
    relative_path = _relative_path_from_text(normalized)
    if not relative_path.parts:
        return None
    return relative_path.as_posix()


def _session_stems_dir(session: Mapping[str, Any]) -> Path | None:
    stems_dir = _normalize_path_text(session.get("stems_dir"))
    if not stems_dir or not _looks_absolute_path(stems_dir):
        return None
    return Path(stems_dir)


def _session_workspace_dir(
    session: Mapping[str, Any],
    *,
    workspace_dir: Path | None = None,
) -> Path | None:
    if workspace_dir is not None:
        return workspace_dir
    session_workspace_dir = _normalize_path_text(session.get("workspace_dir"))
    if not session_workspace_dir or not _looks_absolute_path(session_workspace_dir):
        return None
    return Path(session_workspace_dir)


def _relative_to_workspace(path: Path, workspace_dir: Path | None) -> str | None:
    if workspace_dir is None:
        return None
    return relative_posix_ref(anchor_dir=workspace_dir, target_path=path)


def _finalize_success(
    stem_row: dict[str, Any],
    *,
    mode: str,
    resolved_path: Path,
    workspace_dir: Path | None,
) -> dict[str, Any]:
    resolved = resolved_path.resolve()
    stem_row["resolution_mode"] = mode
    stem_row["resolved_path"] = resolved.as_posix()
    stem_row["resolve_error_code"] = None
    stem_row["resolve_error_detail"] = None
    if not stem_row.get("workspace_relative_path"):
        stem_row["workspace_relative_path"] = _relative_to_workspace(
            resolved,
            workspace_dir,
        )
    if not stem_row.get("source_ref"):
        stem_row["source_ref"] = (
            stem_row.get("workspace_relative_path")
            or _normalize_path_text(stem_row.get("file_path"))
            or resolved.name
        )
    return stem_row


def _finalize_error(
    stem_row: dict[str, Any],
    *,
    error_code: str,
    detail: str,
) -> dict[str, Any]:
    stem_row["resolution_mode"] = RESOLUTION_MODE_UNRESOLVED
    stem_row["resolved_path"] = None
    stem_row["resolve_error_code"] = error_code
    stem_row["resolve_error_detail"] = detail
    return stem_row


def resolve_stem_locator(
    stem: Mapping[str, Any],
    *,
    stems_dir: Path | None = None,
    workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a stem row enriched with canonical locator fields."""
    stem_row = dict(stem)
    file_path = _normalize_path_text(stem.get("file_path"))
    workspace_relative_path = _normalize_workspace_relative_path(
        stem.get("workspace_relative_path")
    )
    explicit_source_ref = _normalize_path_text(stem.get("source_ref"))
    source_ref = explicit_source_ref or workspace_relative_path or file_path or None

    stem_row["file_path"] = file_path
    stem_row["workspace_relative_path"] = workspace_relative_path
    stem_row["source_ref"] = source_ref

    attempted_candidates: list[str] = []

    if file_path and _looks_absolute_path(file_path):
        absolute_candidate = Path(file_path)
        attempted_candidates.append(file_path)
        if absolute_candidate.is_file():
            return _finalize_success(
                stem_row,
                mode=RESOLUTION_MODE_FILE_PATH_ABSOLUTE,
                resolved_path=absolute_candidate,
                workspace_dir=workspace_dir,
            )

    if file_path and not _looks_absolute_path(file_path):
        if stems_dir is not None:
            stems_candidate = (stems_dir / _relative_path_from_text(file_path)).resolve()
            attempted_candidates.append(stems_candidate.as_posix())
            if stems_candidate.is_file():
                return _finalize_success(
                    stem_row,
                    mode=RESOLUTION_MODE_STEMS_DIR_RELATIVE,
                    resolved_path=stems_candidate,
                    workspace_dir=workspace_dir,
                )
        elif not source_ref:
            return _finalize_error(
                stem_row,
                error_code=RESOLVE_ERROR_MISSING_STEMS_DIR,
                detail=(
                    "stem.file_path is relative but session.stems_dir is missing or not absolute."
                ),
            )

    workspace_source_ref = workspace_relative_path or _normalize_workspace_relative_path(source_ref)
    if workspace_source_ref:
        if workspace_dir is not None:
            workspace_candidate = (
                workspace_dir / _relative_path_from_text(workspace_source_ref)
            ).resolve()
            attempted_candidates.append(workspace_candidate.as_posix())
            if workspace_candidate.is_file():
                stem_row["workspace_relative_path"] = workspace_source_ref
                stem_row["source_ref"] = source_ref or workspace_source_ref
                return _finalize_success(
                    stem_row,
                    mode=RESOLUTION_MODE_WORKSPACE_SOURCE_REF,
                    resolved_path=workspace_candidate,
                    workspace_dir=workspace_dir,
                )
        else:
            return _finalize_error(
                stem_row,
                error_code=RESOLVE_ERROR_MISSING_WORKSPACE_DIR,
                detail=(
                    "stem.source_ref/workspace_relative_path is relative to the workspace, "
                    "but workspace_dir is missing or not absolute."
                ),
            )

    if not file_path and not workspace_source_ref:
        return _finalize_error(
            stem_row,
            error_code=RESOLVE_ERROR_MISSING_PATH_FIELDS,
            detail=(
                "No usable stem locator fields were provided. Expected stem.file_path, "
                "stem.workspace_relative_path, or stem.source_ref."
            ),
        )

    attempted_label = ", ".join(dict.fromkeys(attempted_candidates))
    detail = (
        f"None of the deterministic source candidates existed: {attempted_label}"
        if attempted_label
        else "No deterministic source candidates were available to try."
    )
    return _finalize_error(
        stem_row,
        error_code=RESOLVE_ERROR_NOT_FOUND,
        detail=detail,
    )


def resolve_session_stems(
    session: Mapping[str, Any],
    *,
    workspace_dir: Path | None = None,
    mutate: bool = False,
) -> list[dict[str, Any]]:
    """Resolve every session stem using the shared canonical locator rules."""
    stems_payload = session.get("stems")
    if not isinstance(stems_payload, list):
        return []

    resolved_stems = [
        resolve_stem_locator(
            stem,
            stems_dir=_session_stems_dir(session),
            workspace_dir=_session_workspace_dir(session, workspace_dir=workspace_dir),
        )
        for stem in stems_payload
        if isinstance(stem, Mapping)
    ]
    if mutate and isinstance(session, dict):
        session["stems"] = resolved_stems
    return resolved_stems


def resolved_stem_path(stem: Mapping[str, Any]) -> Path | None:
    resolved_path = _normalize_path_text(stem.get("resolved_path"))
    if not resolved_path or not _looks_absolute_path(resolved_path):
        return None
    path = Path(resolved_path)
    if not path.is_file():
        return None
    return path.resolve()


def preferred_stem_relative_path(stem: Mapping[str, Any]) -> Path | None:
    for field_name in ("file_path", "workspace_relative_path", "source_ref"):
        candidate = _normalize_path_text(stem.get(field_name))
        if not candidate or _looks_absolute_path(candidate):
            continue
        return _relative_path_from_text(candidate)
    resolved_path = resolved_stem_path(stem)
    if resolved_path is not None:
        return Path(resolved_path.name)
    return None


def stem_locator_metadata(stem: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stem_id": _coerce_str(stem.get("stem_id")).strip() or None,
        "file_path": _normalize_path_text(stem.get("file_path")) or None,
        "workspace_relative_path": (
            _normalize_workspace_relative_path(stem.get("workspace_relative_path"))
        ),
        "source_ref": _normalize_path_text(stem.get("source_ref")) or None,
        "resolution_mode": _coerce_str(stem.get("resolution_mode")).strip() or None,
        "resolved_path": _normalize_path_text(stem.get("resolved_path")) or None,
        "resolve_error_code": _coerce_str(stem.get("resolve_error_code")).strip() or None,
        "resolve_error_detail": _coerce_str(stem.get("resolve_error_detail")).strip() or None,
    }


def portable_stem_locator_metadata(
    stem: Mapping[str, Any],
    *,
    workspace_dir: Path | None,
) -> dict[str, Any]:
    metadata = stem_locator_metadata(stem)
    fallback_ref = (
        metadata.get("workspace_relative_path")
        or metadata.get("source_ref")
        or metadata.get("file_path")
    )
    for field_name in (
        "file_path",
        "workspace_relative_path",
        "source_ref",
        "resolved_path",
    ):
        metadata[field_name] = portable_path_ref(
            metadata.get(field_name),
            anchor_dir=workspace_dir,
            fallback=fallback_ref,
        )
    return metadata


def stem_resolution_entries(
    stems: list[Mapping[str, Any]],
    *,
    workspace_dir: Path | None = None,
    portable: bool = False,
) -> list[dict[str, Any]]:
    if portable:
        entries = [
            portable_stem_locator_metadata(stem, workspace_dir=workspace_dir)
            for stem in stems
        ]
    else:
        entries = [stem_locator_metadata(stem) for stem in stems]
    entries.sort(
        key=lambda row: (
            _coerce_str(row.get("stem_id")),
            _coerce_str(row.get("file_path")),
            _coerce_str(row.get("source_ref")),
        )
    )
    return entries


def stem_locator_field_names() -> tuple[str, ...]:
    return _LOCATOR_FIELD_NAMES
