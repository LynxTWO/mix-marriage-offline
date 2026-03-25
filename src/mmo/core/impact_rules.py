from __future__ import annotations

from typing import Any, Mapping

from mmo.core.recommendations import normalize_recommendation_deltas, normalize_recommendation_scope

SPATIAL_PERMISSIVE_PROFILES: frozenset[str] = frozenset(
    {
        "PROFILE.FULL_SEND",
        "PROFILE.TURBO",
    }
)

_AZIMUTH_EPSILON_DEG = 5.0
_SPATIAL_SEND_THRESHOLD = 0.05

_SPATIAL_KIND_LABELS: dict[str, str] = {
    "classification_flip": "object/bed classification",
    "azimuth_change": "azimuth change",
    "surround_send_change": "surround send change",
    "height_send_change": "height send change",
    "wide_enablement": "wide enablement",
    "perspective_change": "perspective change",
}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "disabled"}:
            return False
    return None


def _target_stem_id(rec: Mapping[str, Any]) -> str:
    scope = normalize_recommendation_scope(rec)
    return _coerce_str(scope.get("stem_id")).strip()


def _string_values(value: Any) -> set[str]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        return {normalized} if normalized else set()
    if isinstance(value, Mapping):
        values: set[str] = set()
        for nested in value.values():
            values.update(_string_values(nested))
        return values
    if isinstance(value, list):
        values: set[str] = set()
        for item in value:
            values.update(_string_values(item))
        return values
    return set()


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, Mapping):
        collected: list[float] = []
        for nested in value.values():
            collected.extend(_numeric_values(nested))
        return collected
    if isinstance(value, list):
        collected: list[float] = []
        for item in value:
            collected.extend(_numeric_values(item))
        return collected
    numeric = _coerce_float(value)
    if numeric is None:
        return []
    return [numeric]


def _max_abs_change(from_value: Any, to_value: Any) -> float:
    from_values = _numeric_values(from_value)
    to_values = _numeric_values(to_value)
    max_from = max((abs(value) for value in from_values), default=0.0)
    max_to = max((abs(value) for value in to_values), default=0.0)
    return max(max_from, max_to)


def _abs_delta(from_value: Any, to_value: Any) -> float | None:
    from_numeric = _coerce_float(from_value)
    to_numeric = _coerce_float(to_value)
    if from_numeric is not None and to_numeric is not None:
        return abs(to_numeric - from_numeric)
    if to_numeric is not None:
        return abs(to_numeric)
    if from_numeric is not None:
        return abs(from_numeric)
    return None


def _has_classification_flip(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    from_values = _string_values(delta.get("from"))
    to_values = _string_values(delta.get("to"))
    combined = from_values | to_values
    if {"object", "bed"} & combined:
        return from_values != to_values or not from_values or not to_values
    if any(token in param_id for token in ("CLASS", "BED", "OBJECT", "ROUTING_KIND")):
        return bool(combined)
    return "CLASS" in action_id or "ROUT" in action_id and bool(combined)


def _has_azimuth_change(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    if "AZIMUTH" not in param_id and "AZIMUTH" not in action_id:
        return False
    delta_value = _abs_delta(delta.get("from"), delta.get("to"))
    return delta_value is not None and delta_value > _AZIMUTH_EPSILON_DEG


def _has_surround_send_change(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    if "SURROUND" not in param_id and "SURROUND" not in action_id:
        return False
    max_change = _max_abs_change(delta.get("from"), delta.get("to"))
    return max_change > _SPATIAL_SEND_THRESHOLD


def _has_height_send_change(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    if "HEIGHT" not in param_id and "HEIGHT" not in action_id:
        return False
    max_change = _max_abs_change(delta.get("from"), delta.get("to"))
    return max_change > _SPATIAL_SEND_THRESHOLD


def _has_wide_enablement(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    if "WIDE" not in param_id and "WIDTH" not in param_id and "WIDEN" not in action_id:
        return False
    from_bool = _coerce_bool(delta.get("from"))
    to_bool = _coerce_bool(delta.get("to"))
    if from_bool is False and to_bool is True:
        return True
    if from_bool is None and to_bool is True:
        return True
    from_numeric = _coerce_float(delta.get("from"))
    to_numeric = _coerce_float(delta.get("to"))
    if to_numeric is None:
        return False
    baseline = from_numeric if from_numeric is not None else 0.0
    return baseline <= _SPATIAL_SEND_THRESHOLD and to_numeric > _SPATIAL_SEND_THRESHOLD


def _has_perspective_change(delta: Mapping[str, Any], *, action_id: str) -> bool:
    param_id = _coerce_str(delta.get("param_id")).strip().upper()
    if "PERSPECTIVE" not in param_id and "PERSPECTIVE" not in action_id:
        return False
    from_value = _coerce_str(delta.get("from")).strip().lower()
    to_value = _coerce_str(delta.get("to")).strip().lower()
    if to_value and from_value != to_value:
        return True
    return not from_value and bool(to_value)


def spatial_change_kinds(rec: Mapping[str, Any]) -> list[str]:
    action_id = _coerce_str(rec.get("action_id")).strip().upper()
    kinds: set[str] = set()
    for delta in normalize_recommendation_deltas(rec):
        if _has_classification_flip(delta, action_id=action_id):
            kinds.add("classification_flip")
        if _has_azimuth_change(delta, action_id=action_id):
            kinds.add("azimuth_change")
        if _has_surround_send_change(delta, action_id=action_id):
            kinds.add("surround_send_change")
        if _has_height_send_change(delta, action_id=action_id):
            kinds.add("height_send_change")
        if _has_wide_enablement(delta, action_id=action_id):
            kinds.add("wide_enablement")
        if _has_perspective_change(delta, action_id=action_id):
            kinds.add("perspective_change")
    return sorted(kinds)


def is_spatial_change(rec: Mapping[str, Any]) -> bool:
    return bool(spatial_change_kinds(rec))


def spatial_change_required_lock_ids(rec: Mapping[str, Any]) -> list[str]:
    stem_id = _target_stem_id(rec)
    kinds = spatial_change_kinds(rec)
    required_lock_ids: list[str] = []
    for kind in kinds:
        if kind == "classification_flip" and stem_id:
            required_lock_ids.append(f"scene_build_override:{stem_id}:bus_id")
        elif kind == "azimuth_change" and stem_id:
            required_lock_ids.append(f"scene_build_override:{stem_id}:placement.azimuth_deg")
        elif kind == "surround_send_change" and stem_id:
            required_lock_ids.append(f"scene_build_override:{stem_id}:surround_send_caps")
        elif kind == "height_send_change" and stem_id:
            required_lock_ids.append(f"scene_build_override:{stem_id}:height_send_caps")
        elif kind == "wide_enablement" and stem_id:
            required_lock_ids.append(f"scene_build_override:{stem_id}:placement.width")
        elif kind == "perspective_change":
            required_lock_ids.append("scene_build_override:scene:perspective")
    return sorted(set(required_lock_ids))


def spatial_change_lock_ids_in_effect(scene_payload: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(scene_payload, Mapping):
        return set()
    metadata = scene_payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return set()
    precedence_receipt = metadata.get("precedence_receipt")
    if not isinstance(precedence_receipt, Mapping):
        return set()
    entries = precedence_receipt.get("entries")
    if not isinstance(entries, list):
        return set()

    active_lock_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if _coerce_str(entry.get("source")).strip().lower() != "locked":
            continue
        lock_id = _coerce_str(entry.get("lock_id")).strip()
        if lock_id:
            active_lock_ids.add(lock_id)
    return active_lock_ids


def spatial_change_lock_satisfied(
    rec: Mapping[str, Any],
    *,
    scene_payload: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    required_lock_ids = spatial_change_required_lock_ids(rec)
    if not required_lock_ids:
        return False, []
    active_lock_ids = spatial_change_lock_ids_in_effect(scene_payload)
    matched_lock_ids = [
        lock_id for lock_id in required_lock_ids if lock_id in active_lock_ids
    ]
    return len(matched_lock_ids) == len(required_lock_ids), matched_lock_ids


def is_permissive_spatial_profile(profile_id: str | None) -> bool:
    normalized = _coerce_str(profile_id).strip().upper()
    return normalized in SPATIAL_PERMISSIVE_PROFILES


def spatial_change_note(
    rec: Mapping[str, Any],
    *,
    profile_id: str | None,
    lock_satisfied: bool,
    permissive_profile: bool,
) -> str:
    kinds = spatial_change_kinds(rec)
    if not kinds:
        return ""
    labels = ", ".join(_SPATIAL_KIND_LABELS[kind] for kind in kinds)
    required_lock_ids = spatial_change_required_lock_ids(rec)
    if lock_satisfied and required_lock_ids:
        return (
            f"Spatial change ({labels}) matches explicit intent lock(s): "
            f"{', '.join(required_lock_ids)}."
        )
    if permissive_profile:
        return (
            f"Spatial change ({labels}) is allowed by permissive profile "
            f"{_coerce_str(profile_id).strip() or '<unknown>'}."
        )
    if required_lock_ids:
        return (
            f"Spatial change ({labels}) is high-impact under "
            f"{_coerce_str(profile_id).strip() or 'the current profile'}; add lock(s) "
            f"{', '.join(required_lock_ids)} or approve this recommendation."
        )
    return (
        f"Spatial change ({labels}) is high-impact under "
        f"{_coerce_str(profile_id).strip() or 'the current profile'} and requires "
        "explicit approval."
    )


__all__ = [
    "SPATIAL_PERMISSIVE_PROFILES",
    "is_permissive_spatial_profile",
    "is_spatial_change",
    "spatial_change_kinds",
    "spatial_change_lock_ids_in_effect",
    "spatial_change_lock_satisfied",
    "spatial_change_note",
    "spatial_change_required_lock_ids",
]
