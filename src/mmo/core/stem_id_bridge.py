from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mmo.core.portable_refs import normalize_posix_ref
from mmo.core.source_locator import preferred_stem_relative_path, resolve_session_stems


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _rel_path_key(value: Any) -> str:
    normalized = normalize_posix_ref(value)
    return normalized.casefold() if normalized else ""


def report_stem_ids_by_relative_path(
    report: Mapping[str, Any],
) -> dict[str, str]:
    session = report.get("session")
    if not isinstance(session, Mapping):
        return {}

    stem_id_by_rel_path: dict[str, str] = {}
    for stem in resolve_session_stems(session):
        stem_id = _coerce_str(stem.get("stem_id")).strip()
        if not stem_id:
            continue
        relative_path = preferred_stem_relative_path(stem)
        if relative_path is None:
            continue
        key = _rel_path_key(relative_path.as_posix())
        if key and key not in stem_id_by_rel_path:
            stem_id_by_rel_path[key] = stem_id
    return stem_id_by_rel_path


def scene_stem_id_aliases_from_stems_map(
    *,
    stems_map: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, str]:
    assignments = stems_map.get("assignments")
    if not isinstance(assignments, list):
        return {}

    report_stem_ids = report_stem_ids_by_relative_path(report)
    aliases: dict[str, str] = {}
    for row in assignments:
        if not isinstance(row, Mapping):
            continue
        file_id = _coerce_str(row.get("file_id")).strip()
        rel_path_key = _rel_path_key(row.get("rel_path"))
        if not file_id or not rel_path_key:
            continue
        report_stem_id = report_stem_ids.get(rel_path_key)
        if report_stem_id and report_stem_id != file_id:
            aliases[file_id] = report_stem_id
    return aliases


def rewrite_scene_stem_ids(
    scene_payload: Mapping[str, Any],
    stem_id_aliases: Mapping[str, str],
) -> dict[str, Any]:
    rewritten_scene = _json_clone(scene_payload)
    if not stem_id_aliases:
        return rewritten_scene

    objects = rewritten_scene.get("objects")
    if isinstance(objects, list):
        for row in objects:
            if not isinstance(row, dict):
                continue
            stem_id = _coerce_str(row.get("stem_id")).strip()
            rewritten_stem_id = stem_id_aliases.get(stem_id)
            if not rewritten_stem_id or rewritten_stem_id == stem_id:
                continue
            row["stem_id"] = rewritten_stem_id
            object_id = _coerce_str(row.get("object_id")).strip()
            if object_id == f"OBJ.{stem_id}":
                row["object_id"] = f"OBJ.{rewritten_stem_id}"
        objects.sort(
            key=lambda row: (
                _coerce_str(row.get("group_bus")).strip(),
                _coerce_str(row.get("stem_id")).strip(),
                _coerce_str(row.get("role_id")).strip(),
                _coerce_str(row.get("object_id")).strip(),
            )
        )

    beds = rewritten_scene.get("beds")
    if isinstance(beds, list):
        for row in beds:
            if not isinstance(row, dict):
                continue
            stem_ids = row.get("stem_ids")
            if not isinstance(stem_ids, list):
                continue
            rewritten_stem_ids = [
                stem_id_aliases.get(_coerce_str(stem_id).strip(), _coerce_str(stem_id).strip())
                for stem_id in stem_ids
                if _coerce_str(stem_id).strip()
            ]
            row["stem_ids"] = sorted(dict.fromkeys(rewritten_stem_ids))

    metadata = rewritten_scene.get("metadata")
    if isinstance(metadata, dict):
        stereo_hints = metadata.get("stereo_hints")
        if isinstance(stereo_hints, list):
            for row in stereo_hints:
                if not isinstance(row, dict):
                    continue
                stem_id = _coerce_str(row.get("stem_id")).strip()
                rewritten_stem_id = stem_id_aliases.get(stem_id)
                if not rewritten_stem_id or rewritten_stem_id == stem_id:
                    continue
                row["stem_id"] = rewritten_stem_id
                object_id = _coerce_str(row.get("object_id")).strip()
                if object_id == f"OBJ.{stem_id}":
                    row["object_id"] = f"OBJ.{rewritten_stem_id}"
            stereo_hints.sort(
                key=lambda row: (
                    _coerce_str(row.get("stem_id")).strip(),
                    _coerce_str(row.get("object_id")).strip(),
                )
            )

    return rewritten_scene


def rewrite_scene_build_locks_stem_ids(
    locks_payload: Mapping[str, Any],
    stem_id_aliases: Mapping[str, str],
) -> dict[str, Any]:
    rewritten_payload = _json_clone(locks_payload)
    if not stem_id_aliases:
        return rewritten_payload

    overrides = rewritten_payload.get("overrides")
    if not isinstance(overrides, dict):
        return rewritten_payload

    rewritten_overrides: dict[str, dict[str, Any]] = {}
    for stem_id in sorted(overrides.keys()):
        normalized_stem_id = _coerce_str(stem_id).strip()
        row = overrides.get(stem_id)
        if not normalized_stem_id or not isinstance(row, dict):
            continue
        rewritten_stem_id = stem_id_aliases.get(normalized_stem_id, normalized_stem_id)
        if rewritten_stem_id in rewritten_overrides and rewritten_stem_id != normalized_stem_id:
            continue
        rewritten_overrides[rewritten_stem_id] = dict(row)

    rewritten_payload["overrides"] = {
        stem_id: rewritten_overrides[stem_id]
        for stem_id in sorted(rewritten_overrides.keys())
    }
    return rewritten_payload
