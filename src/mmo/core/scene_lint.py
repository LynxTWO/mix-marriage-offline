from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.core.portable_refs import is_absolute_posix_path, resolve_posix_ref

from mmo.core.roles import list_roles
from mmo.core.scene_locks import load_scene_locks

SCENE_LINT_SCHEMA_VERSION = "0.1.0"

_ISSUE_MISSING_STEM_ID = "ISSUE.SCENE_LINT.MISSING_STEM_ID"
_ISSUE_MISSING_STEM_REFERENCE = "ISSUE.SCENE_LINT.MISSING_STEM_REFERENCE"
_ISSUE_MISSING_STEM_FILE = "ISSUE.SCENE_LINT.MISSING_STEM_FILE"
_ISSUE_DUPLICATE_OBJECT_REFERENCE = "ISSUE.SCENE_LINT.DUPLICATE_OBJECT_REFERENCE"
_ISSUE_DUPLICATE_BUS_REFERENCE = "ISSUE.SCENE_LINT.DUPLICATE_BUS_REFERENCE"
_ISSUE_OUT_OF_RANGE_AZIMUTH = "ISSUE.SCENE_LINT.OUT_OF_RANGE_AZIMUTH"
_ISSUE_OUT_OF_RANGE_WIDTH = "ISSUE.SCENE_LINT.OUT_OF_RANGE_WIDTH"
_ISSUE_OUT_OF_RANGE_DEPTH = "ISSUE.SCENE_LINT.OUT_OF_RANGE_DEPTH"
_ISSUE_LOCK_UNKNOWN = "ISSUE.SCENE_LINT.LOCK_UNKNOWN"
_ISSUE_LOCK_SCOPE_CONFLICT = "ISSUE.SCENE_LINT.LOCK_SCOPE_CONFLICT"
_ISSUE_LOCK_CONTEXT_MISSING = "ISSUE.SCENE_LINT.LOCK_CONTEXT_MISSING"
_ISSUE_LOCK_CONFLICT = "ISSUE.SCENE_LINT.LOCK_CONFLICT"
_ISSUE_LOCK_OVERRIDE_ROLE_UNKNOWN = "ISSUE.SCENE_LINT.LOCK_OVERRIDE_ROLE_UNKNOWN"
_ISSUE_LOCK_OVERRIDE_BUS_ASSUMPTION_MISSING = (
    "ISSUE.SCENE_LINT.LOCK_OVERRIDE_BUS_ASSUMPTION_MISSING"
)
_ISSUE_CRITICAL_ANCHOR_LOW_CONFIDENCE = (
    "ISSUE.SCENE_LINT.CRITICAL_ANCHOR_LOW_CONFIDENCE"
)
_ISSUE_IMMERSIVE_NO_BED_OR_AMBIENT = (
    "ISSUE.SCENE_LINT.IMMERSIVE_NO_BED_OR_AMBIENT"
)
_ISSUE_IMMERSIVE_TEMPLATE_MISSING = "ISSUE.SCENE_LINT.IMMERSIVE_TEMPLATE_MISSING"
_ISSUE_IMMERSIVE_LOW_CONFIDENCE = "ISSUE.SCENE_LINT.IMMERSIVE_LOW_CONFIDENCE"
_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO = "ISSUE.SCENE_LINT.HEIGHT_SEND_CAPPED_TO_ZERO"

_SEVERITY_ERROR = "error"
_SEVERITY_WARN = "warn"

_LOCK_NO_HEIGHT_SEND = "LOCK.NO_HEIGHT_SEND"
_IMMERSIVE_PERSPECTIVES: frozenset[str] = frozenset({"in_band", "in_orchestra"})
_CRITICAL_ANCHOR_CONFIDENCE_WARN_BELOW = 0.5
_IMMERSIVE_CONFIDENCE_WARN_BELOW = 0.5

_AMBIENT_TOKENS: tuple[str, ...] = (
    "ambient",
    "ambience",
    "audience",
    "crowd",
    "hall",
    "reverb",
    "room",
)
_DEFAULT_BUS_ROOTS: frozenset[str] = frozenset(
    {
        "BUS.BASS",
        "BUS.DRUMS",
        "BUS.FX",
        "BUS.MASTER",
        "BUS.MUSIC",
        "BUS.OTHER",
        "BUS.VOX",
    }
)
_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".wave", ".flac", ".wv", ".aiff", ".aif", ".ape", ".alac", ".m4a"}
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalize_lock_ids(value: Any) -> list[str]:
    return sorted(
        {
            item.strip()
            for item in _string_list(value)
            if isinstance(item, str) and item.strip()
        }
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _normalize_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_evidence(value[key])
            for key in sorted(value.keys())
        }
    if isinstance(value, list):
        return [_normalize_evidence(item) for item in value]
    return value


def _issue(
    *,
    severity: str,
    issue_id: str,
    message: str,
    path: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "severity": severity,
        "issue_id": issue_id,
        "path": path,
        "message": message,
    }
    if isinstance(evidence, dict) and evidence:
        row["evidence"] = _normalize_evidence(evidence)
    return row


def _issue_sort_key(issue: dict[str, Any]) -> tuple[int, str, str, str, str]:
    severity = _coerce_str(issue.get("severity")).strip().lower()
    severity_rank = 0 if severity == _SEVERITY_ERROR else 1
    return (
        severity_rank,
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("path")).strip(),
        _coerce_str(issue.get("message")).strip(),
        _json_text(issue.get("evidence", {})),
    )


def _sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=_issue_sort_key)


def _summary_from_issues(issues: list[dict[str, Any]]) -> dict[str, Any]:
    error_count = sum(
        1
        for issue in issues
        if _coerce_str(issue.get("severity")).strip().lower() == _SEVERITY_ERROR
    )
    warn_count = sum(
        1
        for issue in issues
        if _coerce_str(issue.get("severity")).strip().lower() == _SEVERITY_WARN
    )
    return {
        "ok": error_count == 0,
        "error_count": error_count,
        "warn_count": warn_count,
        "issue_count": len(issues),
    }


def _path_text(path: Path | None) -> str | None:
    if not isinstance(path, Path):
        return None
    return path.resolve().as_posix()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _resolve_scene_ref_path(
    scene_payload: dict[str, Any],
    *,
    scene_path: Path,
    key: str,
) -> Path | None:
    source_refs = scene_payload.get("source_refs")
    if not isinstance(source_refs, dict):
        return None
    raw_path = _coerce_str(source_refs.get(key)).strip()
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (scene_path.parent / candidate).resolve()


def _known_source_stem_ids(
    scene_payload: dict[str, Any],
    *,
    scene_path: Path,
) -> set[str]:
    stems_map_path = _resolve_scene_ref_path(
        scene_payload,
        scene_path=scene_path,
        key="stems_map_ref",
    )
    if stems_map_path is None or not stems_map_path.is_file():
        return set()

    stems_map_payload = _load_json_object(stems_map_path)
    assignments = stems_map_payload.get("assignments")
    if not isinstance(assignments, list):
        return set()

    known_ids: set[str] = set()
    for row in assignments:
        if not isinstance(row, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if stem_id:
            known_ids.add(stem_id)
    return known_ids


def _scene_locks_map() -> dict[str, dict[str, Any]]:
    payload = load_scene_locks()
    locks = payload.get("locks")
    if not isinstance(locks, dict):
        return {}
    return {
        lock_id: dict(lock_payload)
        for lock_id, lock_payload in locks.items()
        if isinstance(lock_id, str) and isinstance(lock_payload, dict)
    }


def _known_role_ids() -> set[str]:
    return set(list_roles())


def _bus_root(bus_id: str) -> str:
    normalized = _coerce_str(bus_id).strip().upper()
    if not normalized:
        return ""
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 2 and parts[0] == "BUS":
        return f"BUS.{parts[1]}"
    return normalized


def _known_bus_roots(scene_payload: dict[str, Any]) -> set[str]:
    roots: set[str] = set(_DEFAULT_BUS_ROOTS)

    objects = scene_payload.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            bus_id = _coerce_str(obj.get("bus_id")).strip().upper()
            group_bus = _coerce_str(obj.get("group_bus")).strip().upper()
            if bus_id:
                roots.add(_bus_root(bus_id))
            if group_bus:
                roots.add(_bus_root(group_bus))

    beds = scene_payload.get("beds")
    if isinstance(beds, list):
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            bus_id = _coerce_str(bed.get("bus_id")).strip().upper()
            if bus_id:
                roots.add(_bus_root(bus_id))
    return {item for item in roots if item}


def _has_positive_height_send_caps(intent_payload: Any) -> bool:
    if not isinstance(intent_payload, dict):
        return False
    raw_caps = intent_payload.get("height_send_caps")
    if not isinstance(raw_caps, dict):
        return False
    for key in ("top_max_gain", "top_front_max_gain", "top_rear_max_gain"):
        value = _coerce_float(raw_caps.get(key))
        if value is not None and value > 0.0:
            return True
    return False


def _text_has_ambient_token(text: str) -> bool:
    lowered = _coerce_str(text).strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in _AMBIENT_TOKENS)


def _is_ambient_bed_candidate(bed: dict[str, Any]) -> bool:
    stem_ids = [
        _coerce_str(stem_id).strip()
        for stem_id in bed.get("stem_ids", [])
        if _coerce_str(stem_id).strip()
    ]
    if not stem_ids:
        return False

    kind = _coerce_str(bed.get("kind")).strip().lower()
    if kind in {"bed", "field"}:
        return True

    content_hint = _coerce_str(bed.get("content_hint")).strip()
    if _text_has_ambient_token(content_hint):
        return True
    if _text_has_ambient_token(_coerce_str(bed.get("label"))):
        return True
    for note in _string_list(bed.get("notes")):
        if _text_has_ambient_token(note):
            return True
    return False


def _scene_stems_dir(
    scene_payload: dict[str, Any],
    *,
    scene_path: Path | None = None,
) -> Path | None:
    source = scene_payload.get("source")
    if not isinstance(source, dict):
        return None
    stems_dir = _coerce_str(source.get("stems_dir")).strip()
    if not stems_dir:
        return None
    if is_absolute_posix_path(stems_dir):
        return Path(stems_dir)
    if scene_path is None:
        return None
    return resolve_posix_ref(stems_dir, anchor_dir=scene_path.resolve().parent)


def _available_scene_stem_tokens(stems_dir: Path | None) -> set[str]:
    if not isinstance(stems_dir, Path) or not stems_dir.is_dir():
        return set()
    tokens: set[str] = set()
    for file_path in sorted(stems_dir.rglob("*")):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix not in _AUDIO_EXTENSIONS:
            continue
        tokens.add(file_path.stem.lower())
        tokens.add(file_path.name.lower())
    return tokens


def _has_template_note(value: Any) -> bool:
    for note in _string_list(value):
        normalized = note.strip().lower()
        if "template" in normalized or normalized.startswith("seating:"):
            return True
    return False


def _scene_has_template_evidence(
    *,
    scene_payload: dict[str, Any],
    object_rows: list[tuple[int, dict[str, Any]]],
) -> bool:
    scene_intent = scene_payload.get("intent")
    if isinstance(scene_intent, dict):
        if _has_template_note(scene_intent.get("notes")):
            return True
    metadata = scene_payload.get("metadata")
    if isinstance(metadata, dict) and _has_template_note(metadata.get("notes")):
        return True

    for _, obj in object_rows:
        if _has_template_note(obj.get("notes")):
            return True
        intent = obj.get("intent")
        if not isinstance(intent, dict):
            continue
        if _has_template_note(intent.get("notes")):
            return True
        position = intent.get("position")
        if isinstance(position, dict) and _coerce_float(position.get("azimuth_deg")) is not None:
            return True
        if _coerce_float(obj.get("azimuth_hint")) is not None:
            return True
    return False


def _height_send_caps_all_zero(intent_payload: Any) -> bool:
    if not isinstance(intent_payload, dict):
        return False
    raw_caps = intent_payload.get("height_send_caps")
    if not isinstance(raw_caps, dict) or not raw_caps:
        return False
    saw_numeric = False
    for key in ("top_max_gain", "top_front_max_gain", "top_rear_max_gain"):
        value = _coerce_float(raw_caps.get(key))
        if value is None:
            continue
        saw_numeric = True
        if value > 0.0:
            return False
    return saw_numeric


def _is_ambient_object_candidate(obj: dict[str, Any]) -> bool:
    role_id = _coerce_str(obj.get("role_id")).strip().upper()
    if role_id.startswith(("ROLE.FX.", "ROLE.SFX.", "ROLE.AMB")):
        return True

    bus_id = _coerce_str(obj.get("bus_id")).strip().upper()
    group_bus = _coerce_str(obj.get("group_bus")).strip().upper()
    if _bus_root(bus_id) == "BUS.FX" or _bus_root(group_bus) == "BUS.FX":
        return True

    if _text_has_ambient_token(_coerce_str(obj.get("label"))):
        return True
    for note in _string_list(obj.get("notes")):
        if _text_has_ambient_token(note):
            return True
    return False


def _is_critical_anchor_role(role_id: str) -> bool:
    normalized = _coerce_str(role_id).strip().upper()
    return (
        normalized.startswith("ROLE.DRUM.KICK")
        or normalized.startswith("ROLE.DRUM.SNARE")
        or normalized.startswith("ROLE.BASS.")
        or normalized.startswith("ROLE.VOCAL.LEAD")
        or normalized.startswith("ROLE.DIALOGUE.LEAD")
    )


def _validate_range(
    *,
    issues: list[dict[str, Any]],
    value: Any,
    minimum: float,
    maximum: float,
    issue_id: str,
    label: str,
    path: str,
) -> None:
    if value is None:
        return
    numeric = _coerce_float(value)
    if numeric is None:
        issues.append(
            _issue(
                severity=_SEVERITY_ERROR,
                issue_id=issue_id,
                message=f"{label} must be numeric.",
                path=path,
                evidence={"value": value},
            )
        )
        return
    if minimum <= numeric <= maximum:
        return
    issues.append(
        _issue(
            severity=_SEVERITY_ERROR,
            issue_id=issue_id,
            message=f"{label} must be between {minimum} and {maximum}.",
            path=path,
            evidence={"value": numeric, "minimum": minimum, "maximum": maximum},
        )
    )


def _validate_lock_ids(
    *,
    issues: list[dict[str, Any]],
    scope: str,
    path: str,
    lock_ids: list[str],
    locks_map: dict[str, dict[str, Any]],
) -> None:
    for lock_id in lock_ids:
        lock_payload = locks_map.get(lock_id)
        if not isinstance(lock_payload, dict):
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_LOCK_UNKNOWN,
                    message=f"Unknown lock ID: {lock_id}.",
                    path=path,
                    evidence={"lock_id": lock_id, "scope": scope},
                )
            )
            continue

        applies_to = {
            _coerce_str(value).strip().lower()
            for value in _string_list(lock_payload.get("applies_to"))
            if _coerce_str(value).strip()
        }
        if applies_to and scope not in applies_to:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_LOCK_SCOPE_CONFLICT,
                    message=(
                        f"Lock {lock_id} does not apply to scope {scope}."
                    ),
                    path=path,
                    evidence={
                        "lock_id": lock_id,
                        "scope": scope,
                        "applies_to": sorted(applies_to),
                    },
                )
            )


def build_scene_lint_payload(
    *,
    scene_payload: dict[str, Any],
    scene_path: Path,
    locks_payload: dict[str, Any] | None = None,
    locks_path: Path | None = None,
    extra_source_stem_ids: set[str] | None = None,
    critical_anchor_confidence_warn_below: float = _CRITICAL_ANCHOR_CONFIDENCE_WARN_BELOW,
) -> dict[str, Any]:
    if not isinstance(scene_payload, dict):
        raise ValueError("scene_payload must be an object.")

    issues: list[dict[str, Any]] = []
    locks_map = _scene_locks_map()
    known_roles = _known_role_ids()
    known_bus_roots = _known_bus_roots(scene_payload)
    scene_stems_dir = _scene_stems_dir(scene_payload, scene_path=scene_path)
    available_stem_tokens = _available_scene_stem_tokens(scene_stems_dir)
    known_source_stem_ids = _known_source_stem_ids(
        scene_payload,
        scene_path=scene_path,
    )
    if isinstance(extra_source_stem_ids, set):
        known_source_stem_ids.update(
            {
                item.strip()
                for item in extra_source_stem_ids
                if isinstance(item, str) and item.strip()
            }
        )

    objects = scene_payload.get("objects")
    object_rows = (
        [(index, row) for index, row in enumerate(objects) if isinstance(row, dict)]
        if isinstance(objects, list)
        else []
    )
    beds = scene_payload.get("beds")
    bed_rows = (
        [(index, row) for index, row in enumerate(beds) if isinstance(row, dict)]
        if isinstance(beds, list)
        else []
    )
    stem_bus_assignments: dict[str, list[dict[str, str]]] = {}

    def _add_stem_bus_assignment(*, stem_id: str, bus_id: str, path: str, source: str) -> None:
        normalized_stem_id = _coerce_str(stem_id).strip()
        normalized_bus_id = _coerce_str(bus_id).strip().upper()
        if not normalized_stem_id or not normalized_bus_id:
            return
        stem_bus_assignments.setdefault(normalized_stem_id, []).append(
            {
                "bus_id": normalized_bus_id,
                "path": path,
                "source": source,
            }
        )

    object_ids: dict[str, list[int]] = {}
    object_stem_ids: dict[str, list[int]] = {}
    for index, obj in object_rows:
        object_id = _coerce_str(obj.get("object_id")).strip()
        if object_id:
            object_ids.setdefault(object_id, []).append(index)
        stem_id = _coerce_str(obj.get("stem_id")).strip()
        if stem_id:
            object_stem_ids.setdefault(stem_id, []).append(index)

    for object_id, indexes in sorted(object_ids.items()):
        if len(indexes) <= 1:
            continue
        for dup_index in indexes[1:]:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_DUPLICATE_OBJECT_REFERENCE,
                    message=f"Duplicate object_id reference: {object_id}.",
                    path=f"objects[{dup_index}].object_id",
                    evidence={
                        "object_id": object_id,
                        "first_index": indexes[0],
                        "duplicate_index": dup_index,
                    },
                )
            )

    for stem_id, indexes in sorted(object_stem_ids.items()):
        if len(indexes) <= 1:
            continue
        for dup_index in indexes[1:]:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_DUPLICATE_OBJECT_REFERENCE,
                    message=f"Duplicate object stem reference: {stem_id}.",
                    path=f"objects[{dup_index}].stem_id",
                    evidence={
                        "stem_id": stem_id,
                        "first_index": indexes[0],
                        "duplicate_index": dup_index,
                    },
                )
            )

    bed_ids: dict[str, list[int]] = {}
    bed_bus_ids: dict[str, list[int]] = {}
    for index, bed in bed_rows:
        bed_id = _coerce_str(bed.get("bed_id")).strip()
        if bed_id:
            bed_ids.setdefault(bed_id, []).append(index)

        bus_id = _coerce_str(bed.get("bus_id")).strip().upper()
        if bus_id:
            bed_bus_ids.setdefault(bus_id, []).append(index)

        raw_bed_stem_ids = bed.get("stem_ids")
        stem_ids: list[str] = []
        if isinstance(raw_bed_stem_ids, list):
            for stem_offset, raw_stem_id in enumerate(raw_bed_stem_ids):
                normalized_stem_id = _coerce_str(raw_stem_id).strip()
                if not normalized_stem_id:
                    issues.append(
                        _issue(
                            severity=_SEVERITY_ERROR,
                            issue_id=_ISSUE_MISSING_STEM_ID,
                            message="Bed stem reference is missing a stem_id.",
                            path=f"beds[{index}].stem_ids[{stem_offset}]",
                            evidence={"bed_id": bed_id},
                        )
                    )
                    continue
                stem_ids.append(normalized_stem_id)
                _add_stem_bus_assignment(
                    stem_id=normalized_stem_id,
                    bus_id=bus_id,
                    path=f"beds[{index}].bus_id",
                    source="bed_bus",
                )
                if (
                    available_stem_tokens
                    and normalized_stem_id.lower() not in available_stem_tokens
                    and normalized_stem_id not in known_source_stem_ids
                ):
                    issues.append(
                        _issue(
                            severity=_SEVERITY_ERROR,
                            issue_id=_ISSUE_MISSING_STEM_FILE,
                            message=(
                                "Bed stem reference does not match any source file "
                                "in scene.source.stems_dir."
                            ),
                            path=f"beds[{index}].stem_ids[{stem_offset}]",
                            evidence={
                                "bed_id": bed_id,
                                "stem_id": normalized_stem_id,
                                "stems_dir": _path_text(scene_stems_dir),
                            },
                        )
                    )
        stem_counts: dict[str, int] = {}
        for stem_id in stem_ids:
            stem_counts[stem_id] = stem_counts.get(stem_id, 0) + 1
        for stem_id, count in sorted(stem_counts.items()):
            if count <= 1:
                continue
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_DUPLICATE_OBJECT_REFERENCE,
                    message=f"Duplicate bed stem reference: {stem_id}.",
                    path=f"beds[{index}].stem_ids",
                    evidence={"bed_id": bed_id, "stem_id": stem_id, "count": count},
                )
            )

    for bed_id, indexes in sorted(bed_ids.items()):
        if len(indexes) <= 1:
            continue
        for dup_index in indexes[1:]:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_DUPLICATE_OBJECT_REFERENCE,
                    message=f"Duplicate bed_id reference: {bed_id}.",
                    path=f"beds[{dup_index}].bed_id",
                    evidence={
                        "bed_id": bed_id,
                        "first_index": indexes[0],
                        "duplicate_index": dup_index,
                    },
                )
            )

    for bus_id, indexes in sorted(bed_bus_ids.items()):
        if len(indexes) <= 1:
            continue
        for dup_index in indexes[1:]:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_DUPLICATE_BUS_REFERENCE,
                    message=f"Duplicate bed bus reference: {bus_id}.",
                    path=f"beds[{dup_index}].bus_id",
                    evidence={
                        "bus_id": bus_id,
                        "first_index": indexes[0],
                        "duplicate_index": dup_index,
                    },
                )
            )

    known_object_stems = set(object_stem_ids.keys())
    for index, bed in bed_rows:
        bed_id = _coerce_str(bed.get("bed_id")).strip()
        stem_ids = [
            _coerce_str(stem_id).strip()
            for stem_id in bed.get("stem_ids", [])
            if _coerce_str(stem_id).strip()
        ]
        for stem_offset, stem_id in enumerate(stem_ids):
            if stem_id in known_object_stems:
                continue
            if stem_id in known_source_stem_ids:
                continue
            if available_stem_tokens and stem_id.lower() in available_stem_tokens:
                continue
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_MISSING_STEM_REFERENCE,
                    message=(
                        f"Bed stem reference {stem_id} is missing from scene objects."
                    ),
                    path=f"beds[{index}].stem_ids[{stem_offset}]",
                    evidence={"bed_id": bed_id, "stem_id": stem_id},
                )
            )

    scene_intent = scene_payload.get("intent")
    normalized_scene_intent = scene_intent if isinstance(scene_intent, dict) else {}
    scene_lock_ids = _normalize_lock_ids(normalized_scene_intent.get("locks"))
    _validate_lock_ids(
        issues=issues,
        scope="scene",
        path="intent.locks",
        lock_ids=scene_lock_ids,
        locks_map=locks_map,
    )
    scene_has_no_height_lock = _LOCK_NO_HEIGHT_SEND in set(scene_lock_ids)

    _validate_range(
        issues=issues,
        value=(
            normalized_scene_intent.get("position", {}).get("azimuth_deg")
            if isinstance(normalized_scene_intent.get("position"), dict)
            else None
        ),
        minimum=-180.0,
        maximum=180.0,
        issue_id=_ISSUE_OUT_OF_RANGE_AZIMUTH,
        label="Scene azimuth",
        path="intent.position.azimuth_deg",
    )
    _validate_range(
        issues=issues,
        value=normalized_scene_intent.get("width"),
        minimum=0.0,
        maximum=1.0,
        issue_id=_ISSUE_OUT_OF_RANGE_WIDTH,
        label="Scene width",
        path="intent.width",
    )
    _validate_range(
        issues=issues,
        value=normalized_scene_intent.get("depth"),
        minimum=0.0,
        maximum=1.0,
        issue_id=_ISSUE_OUT_OF_RANGE_DEPTH,
        label="Scene depth",
        path="intent.depth",
    )

    object_stems_with_no_height_lock: set[str] = set()
    bed_stems_with_no_height_lock: set[str] = set()

    for index, obj in object_rows:
        object_id = _coerce_str(obj.get("object_id")).strip()
        stem_id = _coerce_str(obj.get("stem_id")).strip()
        role_id = _coerce_str(obj.get("role_id")).strip().upper()
        bus_id = _coerce_str(obj.get("bus_id")).strip().upper()
        group_bus = _coerce_str(obj.get("group_bus")).strip().upper()
        intent = obj.get("intent")
        normalized_intent = intent if isinstance(intent, dict) else {}
        object_lock_ids = _normalize_lock_ids(normalized_intent.get("locks"))

        if not stem_id:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_MISSING_STEM_ID,
                    message="Object is missing stem_id.",
                    path=f"objects[{index}].stem_id",
                    evidence={"object_id": object_id},
                )
            )
        elif (
            available_stem_tokens
            and stem_id.lower() not in available_stem_tokens
            and stem_id not in known_source_stem_ids
        ):
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_MISSING_STEM_FILE,
                    message=(
                        "Object stem_id does not match any source file in "
                        "scene.source.stems_dir."
                    ),
                    path=f"objects[{index}].stem_id",
                    evidence={
                        "object_id": object_id,
                        "stem_id": stem_id,
                        "stems_dir": _path_text(scene_stems_dir),
                    },
                )
            )
        if bus_id:
            _add_stem_bus_assignment(
                stem_id=stem_id,
                bus_id=bus_id,
                path=f"objects[{index}].bus_id",
                source="object_bus",
            )
        elif group_bus:
            _add_stem_bus_assignment(
                stem_id=stem_id,
                bus_id=group_bus,
                path=f"objects[{index}].group_bus",
                source="object_group_bus",
            )

        _validate_lock_ids(
            issues=issues,
            scope="object",
            path=f"objects[{index}].intent.locks",
            lock_ids=object_lock_ids,
            locks_map=locks_map,
        )
        if _LOCK_NO_HEIGHT_SEND in set(object_lock_ids) and stem_id:
            object_stems_with_no_height_lock.add(stem_id)

        if object_lock_ids and not role_id:
            issues.append(
                _issue(
                    severity=_SEVERITY_WARN,
                    issue_id=_ISSUE_LOCK_CONTEXT_MISSING,
                    message=(
                        "Object lock scope is present but role_id is missing."
                    ),
                    path=f"objects[{index}].role_id",
                    evidence={"object_id": object_id, "stem_id": stem_id},
                )
            )
        if object_lock_ids and not (bus_id or group_bus):
            issues.append(
                _issue(
                    severity=_SEVERITY_WARN,
                    issue_id=_ISSUE_LOCK_CONTEXT_MISSING,
                    message=(
                        "Object lock scope is present but bus_id/group_bus is missing."
                    ),
                    path=f"objects[{index}]",
                    evidence={"object_id": object_id, "stem_id": stem_id},
                )
            )

        _validate_range(
            issues=issues,
            value=obj.get("azimuth_hint"),
            minimum=-180.0,
            maximum=180.0,
            issue_id=_ISSUE_OUT_OF_RANGE_AZIMUTH,
            label="Object azimuth hint",
            path=f"objects[{index}].azimuth_hint",
        )
        _validate_range(
            issues=issues,
            value=obj.get("width_hint"),
            minimum=0.0,
            maximum=1.0,
            issue_id=_ISSUE_OUT_OF_RANGE_WIDTH,
            label="Object width hint",
            path=f"objects[{index}].width_hint",
        )
        _validate_range(
            issues=issues,
            value=obj.get("depth_hint"),
            minimum=0.0,
            maximum=1.0,
            issue_id=_ISSUE_OUT_OF_RANGE_DEPTH,
            label="Object depth hint",
            path=f"objects[{index}].depth_hint",
        )
        _validate_range(
            issues=issues,
            value=(
                normalized_intent.get("position", {}).get("azimuth_deg")
                if isinstance(normalized_intent.get("position"), dict)
                else None
            ),
            minimum=-180.0,
            maximum=180.0,
            issue_id=_ISSUE_OUT_OF_RANGE_AZIMUTH,
            label="Object intent azimuth",
            path=f"objects[{index}].intent.position.azimuth_deg",
        )
        _validate_range(
            issues=issues,
            value=normalized_intent.get("width"),
            minimum=0.0,
            maximum=1.0,
            issue_id=_ISSUE_OUT_OF_RANGE_WIDTH,
            label="Object intent width",
            path=f"objects[{index}].intent.width",
        )
        _validate_range(
            issues=issues,
            value=normalized_intent.get("depth"),
            minimum=0.0,
            maximum=1.0,
            issue_id=_ISSUE_OUT_OF_RANGE_DEPTH,
            label="Object intent depth",
            path=f"objects[{index}].intent.depth",
        )

        if _is_critical_anchor_role(role_id):
            confidence = _coerce_float(normalized_intent.get("confidence"))
            effective_confidence = confidence if confidence is not None else 0.0
            if effective_confidence < critical_anchor_confidence_warn_below:
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_CRITICAL_ANCHOR_LOW_CONFIDENCE,
                        message=(
                            "Critical anchor placement confidence is low."
                        ),
                        path=f"objects[{index}].intent.confidence",
                        evidence={
                            "object_id": object_id,
                            "stem_id": stem_id,
                            "role_id": role_id,
                            "confidence": round(effective_confidence, 6),
                            "warn_below": critical_anchor_confidence_warn_below,
                        },
                    )
                )

        if _has_positive_height_send_caps(normalized_intent):
            if scene_has_no_height_lock:
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_CONFLICT,
                        message=(
                            "Scene lock LOCK.NO_HEIGHT_SEND conflicts with object "
                            "height_send_caps > 0."
                        ),
                        path=f"objects[{index}].intent.height_send_caps",
                        evidence={"object_id": object_id, "stem_id": stem_id},
                    )
                )
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested but LOCK.NO_HEIGHT_SEND "
                            "caps height sends to zero."
                        ),
                        path=f"objects[{index}].intent.height_send_caps",
                        evidence={"object_id": object_id, "stem_id": stem_id},
                    )
                )
            if _LOCK_NO_HEIGHT_SEND in set(object_lock_ids):
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_CONFLICT,
                        message=(
                            "Object lock LOCK.NO_HEIGHT_SEND conflicts with object "
                            "height_send_caps > 0."
                        ),
                        path=f"objects[{index}].intent.height_send_caps",
                        evidence={"object_id": object_id, "stem_id": stem_id},
                    )
                )
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested but object LOCK.NO_HEIGHT_SEND "
                            "caps height sends to zero."
                        ),
                        path=f"objects[{index}].intent.height_send_caps",
                        evidence={"object_id": object_id, "stem_id": stem_id},
                    )
                )

    for index, bed in bed_rows:
        bed_id = _coerce_str(bed.get("bed_id")).strip()
        intent = bed.get("intent")
        normalized_intent = intent if isinstance(intent, dict) else {}
        bed_lock_ids = _normalize_lock_ids(normalized_intent.get("locks"))

        _validate_lock_ids(
            issues=issues,
            scope="bed",
            path=f"beds[{index}].intent.locks",
            lock_ids=bed_lock_ids,
            locks_map=locks_map,
        )
        if _LOCK_NO_HEIGHT_SEND in set(bed_lock_ids):
            for stem_id in [
                _coerce_str(value).strip()
                for value in bed.get("stem_ids", [])
                if _coerce_str(value).strip()
            ]:
                bed_stems_with_no_height_lock.add(stem_id)

        _validate_range(
            issues=issues,
            value=bed.get("width_hint"),
            minimum=0.0,
            maximum=1.0,
            issue_id=_ISSUE_OUT_OF_RANGE_WIDTH,
            label="Bed width hint",
            path=f"beds[{index}].width_hint",
        )

        if _has_positive_height_send_caps(normalized_intent):
            if scene_has_no_height_lock:
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_CONFLICT,
                        message=(
                            "Scene lock LOCK.NO_HEIGHT_SEND conflicts with bed "
                            "height_send_caps > 0."
                        ),
                        path=f"beds[{index}].intent.height_send_caps",
                        evidence={"bed_id": bed_id},
                    )
                )
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested but LOCK.NO_HEIGHT_SEND "
                            "caps height sends to zero."
                        ),
                        path=f"beds[{index}].intent.height_send_caps",
                        evidence={"bed_id": bed_id},
                    )
                )
            if _LOCK_NO_HEIGHT_SEND in set(bed_lock_ids):
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_CONFLICT,
                        message=(
                            "Bed lock LOCK.NO_HEIGHT_SEND conflicts with bed "
                            "height_send_caps > 0."
                        ),
                        path=f"beds[{index}].intent.height_send_caps",
                        evidence={"bed_id": bed_id},
                    )
                )
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested but bed LOCK.NO_HEIGHT_SEND "
                            "caps height sends to zero."
                        ),
                        path=f"beds[{index}].intent.height_send_caps",
                        evidence={"bed_id": bed_id},
                    )
                )

    overrides = (
        locks_payload.get("overrides")
        if isinstance(locks_payload, dict)
        and isinstance(locks_payload.get("overrides"), dict)
        else {}
    )
    for stem_id in sorted(overrides.keys()):
        override = overrides.get(stem_id)
        if not isinstance(stem_id, str) or not stem_id.strip():
            continue
        if not isinstance(override, dict):
            continue
        normalized_stem_id = stem_id.strip()
        override_path = f"locks.overrides.{normalized_stem_id}"

        if normalized_stem_id not in known_object_stems:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_MISSING_STEM_REFERENCE,
                    message=(
                        "Lock override references a stem that is missing from "
                        "scene objects."
                    ),
                    path=override_path,
                    evidence={"stem_id": normalized_stem_id},
                )
            )

        role_id = _coerce_str(override.get("role_id")).strip().upper()
        if role_id and role_id not in known_roles:
            issues.append(
                _issue(
                    severity=_SEVERITY_ERROR,
                    issue_id=_ISSUE_LOCK_OVERRIDE_ROLE_UNKNOWN,
                    message=f"Lock override role_id is unknown: {role_id}.",
                    path=f"{override_path}.role_id",
                    evidence={"stem_id": normalized_stem_id, "role_id": role_id},
                )
            )

        bus_id = _coerce_str(override.get("bus_id")).strip().upper()
        if bus_id:
            _add_stem_bus_assignment(
                stem_id=normalized_stem_id,
                bus_id=bus_id,
                path=f"{override_path}.bus_id",
                source="lock_override",
            )
            bus_root = _bus_root(bus_id)
            if bus_root and bus_root not in known_bus_roots:
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_OVERRIDE_BUS_ASSUMPTION_MISSING,
                        message=(
                            f"Lock override bus root {bus_root} is unknown for this scene."
                        ),
                        path=f"{override_path}.bus_id",
                        evidence={
                            "stem_id": normalized_stem_id,
                            "bus_id": bus_id,
                            "bus_root": bus_root,
                        },
                    )
                )

        if _has_positive_height_send_caps(override):
            if (
                scene_has_no_height_lock
                or normalized_stem_id in object_stems_with_no_height_lock
                or normalized_stem_id in bed_stems_with_no_height_lock
            ):
                issues.append(
                    _issue(
                        severity=_SEVERITY_ERROR,
                        issue_id=_ISSUE_LOCK_CONFLICT,
                        message=(
                            "LOCK.NO_HEIGHT_SEND conflicts with lock override "
                            "height_send_caps > 0."
                        ),
                        path=f"{override_path}.height_send_caps",
                        evidence={"stem_id": normalized_stem_id},
                    )
                )
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested but LOCK.NO_HEIGHT_SEND "
                            "caps height sends to zero."
                        ),
                        path=f"{override_path}.height_send_caps",
                        evidence={"stem_id": normalized_stem_id},
                    )
                )
        if _height_send_caps_all_zero(override):
            object_intent_match = next(
                (
                    obj.get("intent")
                    for _, obj in object_rows
                    if _coerce_str(obj.get("stem_id")).strip() == normalized_stem_id
                ),
                None,
            )
            if _has_positive_height_send_caps(object_intent_match):
                issues.append(
                    _issue(
                        severity=_SEVERITY_WARN,
                        issue_id=_ISSUE_HEIGHT_SEND_CAPPED_TO_ZERO,
                        message=(
                            "Height sends are requested in scene intent but lock "
                            "override caps height sends to zero."
                        ),
                        path=f"{override_path}.height_send_caps",
                        evidence={"stem_id": normalized_stem_id},
                    )
                )

    for stem_id in sorted(stem_bus_assignments.keys()):
        assignments = stem_bus_assignments.get(stem_id, [])
        if not assignments:
            continue
        bus_ids = sorted(
            {
                _coerce_str(item.get("bus_id")).strip().upper()
                for item in assignments
                if isinstance(item, dict) and _coerce_str(item.get("bus_id")).strip()
            }
        )
        bus_roots = sorted({_bus_root(bus_id) for bus_id in bus_ids if _bus_root(bus_id)})
        if len(bus_roots) <= 1:
            continue
        normalized_assignments = sorted(
            [
                {
                    "bus_id": _coerce_str(item.get("bus_id")).strip().upper(),
                    "path": _coerce_str(item.get("path")).strip(),
                    "source": _coerce_str(item.get("source")).strip(),
                }
                for item in assignments
                if isinstance(item, dict)
            ],
            key=lambda item: (item["bus_id"], item["path"], item["source"]),
        )
        first_path = normalized_assignments[0]["path"] if normalized_assignments else "objects"
        issues.append(
            _issue(
                severity=_SEVERITY_ERROR,
                issue_id=_ISSUE_LOCK_CONFLICT,
                message="Same stem is assigned to multiple buses.",
                path=first_path,
                evidence={
                    "stem_id": stem_id,
                    "bus_ids": bus_ids,
                    "bus_roots": bus_roots,
                    "assignments": normalized_assignments,
                },
            )
        )

    perspective = _coerce_str(normalized_scene_intent.get("perspective")).strip().lower()
    if perspective in _IMMERSIVE_PERSPECTIVES:
        has_bed_candidate = any(_is_ambient_bed_candidate(bed) for _, bed in bed_rows)
        has_ambient_candidate = any(
            _is_ambient_object_candidate(obj)
            for _, obj in object_rows
        )
        if not has_bed_candidate and not has_ambient_candidate:
            issues.append(
                _issue(
                    severity=_SEVERITY_WARN,
                    issue_id=_ISSUE_IMMERSIVE_NO_BED_OR_AMBIENT,
                    message=(
                        "Immersive perspective is requested but no bed/ambient "
                        "candidates were found."
                    ),
                    path="intent.perspective",
                    evidence={"perspective": perspective},
                )
            )
        has_template_evidence = _scene_has_template_evidence(
            scene_payload=scene_payload,
            object_rows=object_rows,
        )
        if not has_template_evidence:
            issues.append(
                _issue(
                    severity=_SEVERITY_WARN,
                    issue_id=_ISSUE_IMMERSIVE_TEMPLATE_MISSING,
                    message=(
                        "Immersive perspective is requested but no scene-template "
                        "evidence was found."
                    ),
                    path="intent.perspective",
                    evidence={"perspective": perspective},
                )
            )
        perspective_confidence = _coerce_float(normalized_scene_intent.get("confidence"))
        if (
            perspective_confidence is not None
            and perspective_confidence < _IMMERSIVE_CONFIDENCE_WARN_BELOW
        ):
            issues.append(
                _issue(
                    severity=_SEVERITY_WARN,
                    issue_id=_ISSUE_IMMERSIVE_LOW_CONFIDENCE,
                    message=(
                        "Immersive perspective is requested with low scene confidence."
                    ),
                    path="intent.confidence",
                    evidence={
                        "perspective": perspective,
                        "confidence": round(perspective_confidence, 6),
                        "warn_below": _IMMERSIVE_CONFIDENCE_WARN_BELOW,
                    },
                )
            )

    sorted_issues = _sort_issues(issues)
    return {
        "schema_version": SCENE_LINT_SCHEMA_VERSION,
        "scene_id": _coerce_str(scene_payload.get("scene_id")).strip(),
        "scene_path": _path_text(scene_path),
        "locks_path": _path_text(locks_path),
        "summary": _summary_from_issues(sorted_issues),
        "issues": sorted_issues,
    }


def scene_lint_has_errors(payload: dict[str, Any]) -> bool:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return False
    error_count = summary.get("error_count")
    return isinstance(error_count, int) and error_count > 0


def render_scene_lint_text(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    issues = payload.get("issues")
    if not isinstance(summary, dict) or not isinstance(issues, list):
        return "(invalid payload)"

    error_count = summary.get("error_count", 0)
    warn_count = summary.get("warn_count", 0)
    ok = summary.get("ok") is True

    if ok:
        lines = [
            (
                "Scene lint OK "
                f"({error_count} error(s), {warn_count} warning(s))."
            )
        ]
    else:
        lines = [
            (
                "Scene lint failed "
                f"({error_count} error(s), {warn_count} warning(s))."
            )
        ]

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        severity = _coerce_str(issue.get("severity")).strip()
        issue_id = _coerce_str(issue.get("issue_id")).strip()
        path = _coerce_str(issue.get("path")).strip()
        message = _coerce_str(issue.get("message")).strip()
        lines.append(f"- [{severity}] {issue_id} {path}: {message}")
    return "\n".join(lines)


__all__ = [
    "SCENE_LINT_SCHEMA_VERSION",
    "build_scene_lint_payload",
    "scene_lint_has_errors",
    "render_scene_lint_text",
]
