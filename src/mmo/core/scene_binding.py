from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from mmo.core.portable_refs import is_absolute_posix_path, normalize_posix_ref
from mmo.core.source_locator import resolve_session_stems
from mmo.core.stem_identity import normalize_relative_source_path
from mmo.core.statuses import (
    SCENE_BINDING_STATUS_CLEAN,
    SCENE_BINDING_STATUS_FAILED,
    SCENE_BINDING_STATUS_NOT_APPLICABLE,
    SCENE_BINDING_STATUS_PARTIAL,
    SCENE_BINDING_STATUS_REWRITTEN,
)

SCENE_BINDING_MODE_STEM_ID = "stem_id"
SCENE_BINDING_MODE_SOURCE_REF = "source_ref"
SCENE_BINDING_MODE_WORKSPACE_RELATIVE_PATH = "workspace_relative_path"
SCENE_BINDING_MODE_FILE_PATH = "file_path"
SCENE_BINDING_MODE_BASENAME = "basename"

SCENE_BINDING_WARNING_UNBOUND = "SCENE_BINDING.UNBOUND_STEM_REF"
SCENE_BINDING_WARNING_AMBIGUOUS_BASENAME = "SCENE_BINDING.AMBIGUOUS_BASENAME"
SCENE_BINDING_WARNING_DUPLICATE_LOCK_OVERRIDE = "SCENE_BINDING.DUPLICATE_LOCK_OVERRIDE"


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _normalize_exact_ref(value: Any) -> str:
    normalized = normalize_posix_ref(value)
    if not normalized:
        return ""
    if is_absolute_posix_path(normalized):
        return normalized
    return normalize_relative_source_path(normalized)


def _basename_candidates(value: Any) -> list[str]:
    normalized = _normalize_exact_ref(value)
    if not normalized:
        return []
    basename = Path(normalized).name.strip()
    if not basename:
        return []
    stem = Path(basename).stem.strip()
    candidates: list[str] = []
    for candidate in (basename.lower(), stem.lower()):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _unique_index(
    stems: list[dict[str, Any]],
    *,
    field_name: str,
    normalizer: Any,
) -> dict[str, str]:
    bucket: dict[str, set[str]] = {}
    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip()
        key = normalizer(stem.get(field_name))
        if not stem_id or not key:
            continue
        bucket.setdefault(key, set()).add(stem_id)
    return {
        key: next(iter(stem_ids))
        for key, stem_ids in sorted(bucket.items())
        if len(stem_ids) == 1
    }


def _basename_index(stems: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    bucket: dict[str, set[str]] = {}
    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip()
        if not stem_id:
            continue
        for field_name in ("source_ref", "workspace_relative_path", "file_path"):
            for candidate in _basename_candidates(stem.get(field_name)):
                bucket.setdefault(candidate, set()).add(stem_id)
    unique = {
        key: next(iter(stem_ids))
        for key, stem_ids in sorted(bucket.items())
        if len(stem_ids) == 1
    }
    ambiguous = {
        key: sorted(stem_ids)
        for key, stem_ids in sorted(bucket.items())
        if len(stem_ids) > 1
    }
    return unique, ambiguous


def _session_lookup(session_payload: Mapping[str, Any]) -> dict[str, Any]:
    stems = resolve_session_stems(session_payload, mutate=False)
    stem_id_index = _unique_index(
        stems,
        field_name="stem_id",
        normalizer=lambda value: _coerce_str(value).strip(),
    )
    return {
        "stems": stems,
        "stem_id": stem_id_index,
        "source_ref": _unique_index(
            stems,
            field_name="source_ref",
            normalizer=_normalize_exact_ref,
        ),
        "workspace_relative_path": _unique_index(
            stems,
            field_name="workspace_relative_path",
            normalizer=_normalize_exact_ref,
        ),
        "file_path": _unique_index(
            stems,
            field_name="file_path",
            normalizer=_normalize_exact_ref,
        ),
        "basename": _basename_index(stems),
    }


def default_scene_binding_summary() -> dict[str, Any]:
    return {
        "status": SCENE_BINDING_STATUS_NOT_APPLICABLE,
        "reference_count": 0,
        "bound_count": 0,
        "unbound_count": 0,
        "rewritten_count": 0,
        "rewritten_refs": [],
        "binding_warnings": [],
        "failure_reason": None,
    }


def _bind_ref(raw_ref: str, lookup: Mapping[str, Any]) -> dict[str, Any]:
    exact_ref = _coerce_str(raw_ref).strip()
    if not exact_ref:
        return {
            "bound": False,
            "binding_mode": None,
            "stem_id": None,
            "warning_code": SCENE_BINDING_WARNING_UNBOUND,
            "detail": "Scene stem reference is empty.",
            "candidates": [],
        }

    for binding_mode in (
        SCENE_BINDING_MODE_STEM_ID,
        SCENE_BINDING_MODE_SOURCE_REF,
        SCENE_BINDING_MODE_WORKSPACE_RELATIVE_PATH,
        SCENE_BINDING_MODE_FILE_PATH,
    ):
        if binding_mode == SCENE_BINDING_MODE_STEM_ID:
            key = exact_ref
        else:
            key = _normalize_exact_ref(exact_ref)
        if not key:
            continue
        stem_id = lookup.get(binding_mode, {}).get(key)
        if isinstance(stem_id, str) and stem_id:
            return {
                "bound": True,
                "binding_mode": binding_mode,
                "stem_id": stem_id,
                "warning_code": None,
                "detail": None,
                "candidates": [],
            }

    basename_unique, basename_ambiguous = lookup.get("basename", ({}, {}))
    basename_matches: set[str] = set()
    ambiguous_candidates: set[str] = set()
    for candidate in _basename_candidates(exact_ref):
        stem_id = basename_unique.get(candidate)
        if isinstance(stem_id, str) and stem_id:
            basename_matches.add(stem_id)
        ambiguous_candidates.update(basename_ambiguous.get(candidate, []))

    if len(basename_matches) == 1 and not ambiguous_candidates:
        return {
            "bound": True,
            "binding_mode": SCENE_BINDING_MODE_BASENAME,
            "stem_id": next(iter(basename_matches)),
            "warning_code": None,
            "detail": None,
            "candidates": [],
        }

    if basename_matches or ambiguous_candidates:
        candidates = sorted(basename_matches.union(ambiguous_candidates))
        return {
            "bound": False,
            "binding_mode": None,
            "stem_id": None,
            "warning_code": SCENE_BINDING_WARNING_AMBIGUOUS_BASENAME,
            "detail": (
                "Basename fallback matched multiple analyzed session stems; "
                "binding was refused to avoid guessing."
            ),
            "candidates": candidates,
        }

    return {
        "bound": False,
        "binding_mode": None,
        "stem_id": None,
        "warning_code": SCENE_BINDING_WARNING_UNBOUND,
        "detail": "Scene stem reference did not match any analyzed session stem.",
        "candidates": [],
    }


def _rewritten_ref_entry(
    *,
    target_type: str,
    target_id: str,
    field: str,
    from_ref: str,
    to_stem_id: str,
    binding_mode: str,
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "target_id": target_id,
        "field": field,
        "from_ref": from_ref,
        "to_stem_id": to_stem_id,
        "binding_mode": binding_mode,
    }


def _binding_warning_entry(
    *,
    target_type: str,
    target_id: str,
    field: str,
    stem_ref: str,
    warning_code: str,
    detail: str,
    candidates: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "field": field,
        "stem_ref": stem_ref,
        "warning_code": warning_code,
        "detail": detail,
    }
    if candidates:
        payload["candidates"] = list(candidates)
    return payload


def bind_scene_inputs_to_session(
    *,
    scene_payload: Mapping[str, Any] | None,
    session_payload: Mapping[str, Any],
    locks_payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(scene_payload, Mapping):
        return None, _json_clone(locks_payload), default_scene_binding_summary()

    lookup = _session_lookup(session_payload)
    bound_scene = _json_clone(scene_payload)
    bound_locks = _json_clone(locks_payload)
    summary = default_scene_binding_summary()
    rewritten_refs: list[dict[str, Any]] = []
    binding_warnings: list[dict[str, Any]] = []
    reference_count = 0
    bound_count = 0

    objects = bound_scene.get("objects")
    if isinstance(objects, list):
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue
            raw_ref = _coerce_str(obj.get("stem_id")).strip()
            if not raw_ref:
                continue
            reference_count += 1
            target_id = _coerce_str(obj.get("object_id")).strip() or f"objects[{index}]"
            binding = _bind_ref(raw_ref, lookup)
            if binding["bound"] is True:
                bound_count += 1
                stem_id = _coerce_str(binding.get("stem_id")).strip()
                if stem_id and stem_id != raw_ref:
                    obj["stem_id"] = stem_id
                    rewritten_refs.append(
                        _rewritten_ref_entry(
                            target_type="object",
                            target_id=target_id,
                            field="stem_id",
                            from_ref=raw_ref,
                            to_stem_id=stem_id,
                            binding_mode=_coerce_str(binding.get("binding_mode")).strip(),
                        )
                    )
                continue
            binding_warnings.append(
                _binding_warning_entry(
                    target_type="object",
                    target_id=target_id,
                    field="stem_id",
                    stem_ref=raw_ref,
                    warning_code=_coerce_str(binding.get("warning_code")).strip(),
                    detail=_coerce_str(binding.get("detail")).strip(),
                    candidates=list(binding.get("candidates") or []),
                )
            )

    beds = bound_scene.get("beds")
    if isinstance(beds, list):
        for bed_index, bed in enumerate(beds):
            if not isinstance(bed, dict):
                continue
            raw_stem_ids = bed.get("stem_ids")
            if not isinstance(raw_stem_ids, list):
                continue
            target_id = _coerce_str(bed.get("bed_id")).strip() or f"beds[{bed_index}]"
            rewritten_stem_ids: list[str] = []
            for stem_index, raw_item in enumerate(raw_stem_ids):
                raw_ref = _coerce_str(raw_item).strip()
                rewritten_stem_ids.append(raw_ref)
                if not raw_ref:
                    continue
                reference_count += 1
                binding = _bind_ref(raw_ref, lookup)
                if binding["bound"] is True:
                    bound_count += 1
                    stem_id = _coerce_str(binding.get("stem_id")).strip()
                    if stem_id:
                        rewritten_stem_ids[-1] = stem_id
                        if stem_id != raw_ref:
                            rewritten_refs.append(
                                _rewritten_ref_entry(
                                    target_type="bed",
                                    target_id=target_id,
                                    field=f"stem_ids[{stem_index}]",
                                    from_ref=raw_ref,
                                    to_stem_id=stem_id,
                                    binding_mode=_coerce_str(binding.get("binding_mode")).strip(),
                                )
                            )
                    continue
                binding_warnings.append(
                    _binding_warning_entry(
                        target_type="bed",
                        target_id=target_id,
                        field=f"stem_ids[{stem_index}]",
                        stem_ref=raw_ref,
                        warning_code=_coerce_str(binding.get("warning_code")).strip(),
                        detail=_coerce_str(binding.get("detail")).strip(),
                        candidates=list(binding.get("candidates") or []),
                    )
                )
            bed["stem_ids"] = rewritten_stem_ids

    overrides = (
        bound_locks.get("overrides")
        if isinstance(bound_locks, dict) and isinstance(bound_locks.get("overrides"), dict)
        else None
    )
    if isinstance(overrides, dict):
        rewritten_overrides: dict[str, Any] = {}
        for raw_key, payload in overrides.items():
            normalized_key = _coerce_str(raw_key).strip()
            target_id = normalized_key or "lock_override"
            if not normalized_key:
                continue
            reference_count += 1
            binding = _bind_ref(normalized_key, lookup)
            if binding["bound"] is not True:
                binding_warnings.append(
                    _binding_warning_entry(
                        target_type="lock_override",
                        target_id=target_id,
                        field="overrides",
                        stem_ref=normalized_key,
                        warning_code=_coerce_str(binding.get("warning_code")).strip(),
                        detail=_coerce_str(binding.get("detail")).strip(),
                        candidates=list(binding.get("candidates") or []),
                    )
                )
                rewritten_overrides[normalized_key] = payload
                continue

            bound_count += 1
            canonical_key = _coerce_str(binding.get("stem_id")).strip() or normalized_key
            if canonical_key != normalized_key:
                rewritten_refs.append(
                    _rewritten_ref_entry(
                        target_type="lock_override",
                        target_id=target_id,
                        field="overrides",
                        from_ref=normalized_key,
                        to_stem_id=canonical_key,
                        binding_mode=_coerce_str(binding.get("binding_mode")).strip(),
                    )
                )

            if canonical_key in rewritten_overrides:
                if json.dumps(rewritten_overrides[canonical_key], sort_keys=True) != json.dumps(
                    payload,
                    sort_keys=True,
                ):
                    binding_warnings.append(
                        _binding_warning_entry(
                            target_type="lock_override",
                            target_id=canonical_key,
                            field="overrides",
                            stem_ref=normalized_key,
                            warning_code=SCENE_BINDING_WARNING_DUPLICATE_LOCK_OVERRIDE,
                            detail=(
                                "Multiple lock overrides resolved to the same canonical stem_id; "
                                "the first override was kept."
                            ),
                        )
                    )
                continue
            rewritten_overrides[canonical_key] = payload
        bound_locks["overrides"] = rewritten_overrides

    unbound_count = max(0, reference_count - bound_count)
    rewritten_count = len(rewritten_refs)
    status = SCENE_BINDING_STATUS_NOT_APPLICABLE
    failure_reason: str | None = None
    if reference_count > 0:
        if unbound_count == 0 and rewritten_count == 0:
            status = SCENE_BINDING_STATUS_CLEAN
        elif unbound_count == 0:
            status = SCENE_BINDING_STATUS_REWRITTEN
        elif bound_count == 0:
            status = SCENE_BINDING_STATUS_FAILED
            failure_reason = (
                "No scene stem references matched the analyzed session stems."
            )
        else:
            status = SCENE_BINDING_STATUS_PARTIAL
            failure_reason = (
                "Some scene stem references could not be matched to analyzed session stems."
            )

    summary.update(
        {
            "status": status,
            "reference_count": reference_count,
            "bound_count": bound_count,
            "unbound_count": unbound_count,
            "rewritten_count": rewritten_count,
            "rewritten_refs": rewritten_refs,
            "binding_warnings": binding_warnings,
            "failure_reason": failure_reason,
        }
    )
    return bound_scene, bound_locks, summary


__all__ = [
    "SCENE_BINDING_MODE_BASENAME",
    "SCENE_BINDING_MODE_FILE_PATH",
    "SCENE_BINDING_MODE_SOURCE_REF",
    "SCENE_BINDING_MODE_STEM_ID",
    "SCENE_BINDING_MODE_WORKSPACE_RELATIVE_PATH",
    "SCENE_BINDING_WARNING_AMBIGUOUS_BASENAME",
    "SCENE_BINDING_WARNING_DUPLICATE_LOCK_OVERRIDE",
    "SCENE_BINDING_WARNING_UNBOUND",
    "bind_scene_inputs_to_session",
    "default_scene_binding_summary",
]
