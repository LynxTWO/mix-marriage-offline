from __future__ import annotations

import json
from typing import Any

from mmo.core.intent_params import load_intent_params
from mmo.core.scene_locks import load_scene_locks

_SCOPES = {"scene", "object", "bed"}
INTENT_PARAM_KEY_TO_ID: dict[str, str] = {
    "azimuth_deg": "INTENT.POSITION.AZIMUTH_DEG",
    "width": "INTENT.WIDTH",
    "depth": "INTENT.DEPTH",
    "loudness_bias": "INTENT.LOUDNESS_BIAS",
    "confidence": "INTENT.CONFIDENCE",
}
_SCOPE_ALLOWED_INTENT_KEYS: dict[str, set[str]] = {
    "scene": set(INTENT_PARAM_KEY_TO_ID.keys()),
    "object": set(INTENT_PARAM_KEY_TO_ID.keys()),
    "bed": {"confidence"},
}


def _clone_scene(scene: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")
    return json.loads(json.dumps(scene))


def _normalize_scope(scope: str) -> str:
    normalized = scope.strip().lower() if isinstance(scope, str) else ""
    if normalized not in _SCOPES:
        raise ValueError("scope must be one of: scene, object, bed.")
    return normalized


def _normalize_target_id(scope: str, target_id: str | None) -> str:
    if scope == "scene":
        return ""
    normalized = target_id.strip() if isinstance(target_id, str) else ""
    if not normalized:
        raise ValueError("target_id is required for scope object or bed.")
    return normalized


def _normalize_lock_id(lock_id: str) -> str:
    normalized = lock_id.strip() if isinstance(lock_id, str) else ""
    if not normalized:
        raise ValueError("lock_id must be a non-empty string.")
    return normalized


def _normalize_param_key(param_key: str) -> str:
    normalized = param_key.strip() if isinstance(param_key, str) else ""
    if normalized not in INTENT_PARAM_KEY_TO_ID:
        keys = ", ".join(sorted(INTENT_PARAM_KEY_TO_ID.keys()))
        raise ValueError(f"Unsupported intent key: {normalized!r}. Expected one of: {keys}")
    return normalized


def _sorted_unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized = [item.strip() for item in values if isinstance(item, str) and item.strip()]
    return sorted(set(normalized))


def _scene_locks_map() -> dict[str, dict[str, Any]]:
    registry = load_scene_locks()
    locks = registry.get("locks")
    if not isinstance(locks, dict):
        return {}
    return {
        lock_id: dict(payload)
        for lock_id, payload in locks.items()
        if isinstance(lock_id, str) and isinstance(payload, dict)
    }


def _intent_params_map() -> dict[str, dict[str, Any]]:
    registry = load_intent_params()
    params = registry.get("params")
    if not isinstance(params, dict):
        return {}
    return {
        param_id: dict(payload)
        for param_id, payload in params.items()
        if isinstance(param_id, str) and isinstance(payload, dict)
    }


def _validate_lock_for_scope(
    *,
    lock_id: str,
    scope: str,
    locks: dict[str, dict[str, Any]],
) -> None:
    lock_payload = locks.get(lock_id)
    if not isinstance(lock_payload, dict):
        available = ", ".join(sorted(locks.keys()))
        if available:
            raise ValueError(f"Unknown lock_id: {lock_id}. Available locks: {available}")
        raise ValueError(f"Unknown lock_id: {lock_id}. No scene locks are available.")

    applies_to = _sorted_unique_strings(lock_payload.get("applies_to"))
    if applies_to and scope not in applies_to:
        joined = ", ".join(applies_to)
        raise ValueError(f"lock_id {lock_id} does not apply to scope {scope}. Allowed: {joined}")


def _validate_param_key_for_scope(*, scope: str, param_key: str) -> None:
    allowed = _SCOPE_ALLOWED_INTENT_KEYS.get(scope, set())
    if param_key in allowed:
        return
    allowed_label = ", ".join(sorted(allowed))
    raise ValueError(
        f"intent key {param_key!r} is not supported for scope {scope}. Allowed: {allowed_label}"
    )


def _resolve_target_entry(
    *,
    scene: dict[str, Any],
    scope: str,
    target_id: str,
) -> dict[str, Any]:
    if scope == "scene":
        return scene

    list_key = "objects" if scope == "object" else "beds"
    id_key = "object_id" if scope == "object" else "bed_id"
    entries = scene.get(list_key)
    if not isinstance(entries, list):
        raise ValueError(f"scene.{list_key} must be an array.")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get(id_key)
        if isinstance(entry_id, str) and entry_id == target_id:
            return entry
    raise ValueError(f"Unknown {id_key}: {target_id}")


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _ensure_intent_payload(target: dict[str, Any]) -> dict[str, Any]:
    intent = target.get("intent")
    if not isinstance(intent, dict):
        intent = {}
        target["intent"] = intent
    if "confidence" not in intent:
        intent["confidence"] = 0.0
    else:
        intent["confidence"] = _coerce_confidence(intent.get("confidence"))
    intent["locks"] = _sorted_unique_strings(intent.get("locks"))
    return intent


def _sorted_entry_rows(rows: Any, *, id_key: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = [dict(item) for item in rows if isinstance(item, dict)]
    normalized.sort(key=lambda item: str(item.get(id_key, "")))
    return normalized


def _normalize_scene_order(scene: dict[str, Any]) -> None:
    scene["objects"] = _sorted_entry_rows(scene.get("objects"), id_key="object_id")
    scene["beds"] = _sorted_entry_rows(scene.get("beds"), id_key="bed_id")


def _normalized_intent_value(*, param_spec: dict[str, Any], value: Any) -> Any:
    param_type = param_spec.get("type")
    if param_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Intent value must be numeric for number params.")
        return float(value)
    if param_type == "enum":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Intent value must be a non-empty string for enum params.")
        return value.strip()
    raise ValueError(f"Unsupported intent param type: {param_type!r}.")


def intent_param_id_for_key(param_key: str) -> str:
    normalized = _normalize_param_key(param_key=param_key)
    return INTENT_PARAM_KEY_TO_ID[normalized]


def add_lock(
    scene: dict[str, Any],
    scope: str,
    target_id: str | None,
    lock_id: str,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    normalized_target_id = _normalize_target_id(normalized_scope, target_id)
    normalized_lock_id = _normalize_lock_id(lock_id)

    locks = _scene_locks_map()
    _validate_lock_for_scope(
        lock_id=normalized_lock_id,
        scope=normalized_scope,
        locks=locks,
    )

    edited = _clone_scene(scene)
    target = _resolve_target_entry(
        scene=edited,
        scope=normalized_scope,
        target_id=normalized_target_id,
    )
    intent = _ensure_intent_payload(target)
    lock_ids = set(_sorted_unique_strings(intent.get("locks")))
    lock_ids.add(normalized_lock_id)
    intent["locks"] = sorted(lock_ids)

    _normalize_scene_order(edited)
    return edited


def remove_lock(
    scene: dict[str, Any],
    scope: str,
    target_id: str | None,
    lock_id: str,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    normalized_target_id = _normalize_target_id(normalized_scope, target_id)
    normalized_lock_id = _normalize_lock_id(lock_id)

    locks = _scene_locks_map()
    _validate_lock_for_scope(
        lock_id=normalized_lock_id,
        scope=normalized_scope,
        locks=locks,
    )

    edited = _clone_scene(scene)
    target = _resolve_target_entry(
        scene=edited,
        scope=normalized_scope,
        target_id=normalized_target_id,
    )
    intent = _ensure_intent_payload(target)
    lock_ids = set(_sorted_unique_strings(intent.get("locks")))
    lock_ids.discard(normalized_lock_id)
    intent["locks"] = sorted(lock_ids)

    _normalize_scene_order(edited)
    return edited


def set_intent(
    scene: dict[str, Any],
    scope: str,
    target_id: str | None,
    param_key: str,
    value: Any,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    normalized_target_id = _normalize_target_id(normalized_scope, target_id)
    normalized_param_key = _normalize_param_key(param_key)
    _validate_param_key_for_scope(scope=normalized_scope, param_key=normalized_param_key)

    param_id = INTENT_PARAM_KEY_TO_ID[normalized_param_key]
    params = _intent_params_map()
    param_spec = params.get(param_id)
    if not isinstance(param_spec, dict):
        raise ValueError(f"Intent param registry entry is missing: {param_id}")
    normalized_value = _normalized_intent_value(param_spec=param_spec, value=value)

    edited = _clone_scene(scene)
    target = _resolve_target_entry(
        scene=edited,
        scope=normalized_scope,
        target_id=normalized_target_id,
    )
    intent = _ensure_intent_payload(target)
    if normalized_param_key == "azimuth_deg":
        position = intent.get("position")
        if not isinstance(position, dict):
            position = {}
            intent["position"] = position
        position["azimuth_deg"] = normalized_value
    else:
        intent[normalized_param_key] = normalized_value

    _normalize_scene_order(edited)
    return edited
