from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from mmo.core.recommendations import normalize_recommendation_scope
from mmo.core.scene_locks import load_scene_locks

PRECEDENCE_RECEIPT_VERSION = "0.1.0"
PRECEDENCE_GATE_ID = "GATE.SCENE_LOCK_PRECEDENCE"

SOURCE_LOCKED = "locked"
SOURCE_EXPLICIT = "explicit"
SOURCE_SUGGESTED = "suggested"
SOURCE_INFERRED = "inferred"

_SCENE_SCOPE = "scene"
_OBJECT_SCOPE = "object"
_BED_SCOPE = "bed"
_SUPPORTED_RECEIPT_SOURCES = {
    SOURCE_LOCKED,
    SOURCE_EXPLICIT,
    SOURCE_SUGGESTED,
    SOURCE_INFERRED,
}


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


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


def _normalize_string(value: Any) -> str | None:
    normalized = _coerce_str(value).strip()
    if normalized:
        return normalized
    return None


def _normalize_unit(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    return round(min(1.0, max(0.0, numeric)), 3)


def _normalize_azimuth(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    return round(min(180.0, max(-180.0, numeric)), 3)


def _normalize_surround_send_caps(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, float] = {}
    side_max_gain = _normalize_unit(value.get("side_max_gain"))
    if side_max_gain is not None:
        normalized["side_max_gain"] = side_max_gain
    rear_max_gain = _normalize_unit(value.get("rear_max_gain"))
    if rear_max_gain is not None:
        normalized["rear_max_gain"] = rear_max_gain
    return normalized or None


def _normalize_height_send_caps(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, float] = {}
    top_max_gain = _normalize_unit(value.get("top_max_gain"))
    if top_max_gain is not None:
        normalized["top_max_gain"] = top_max_gain
    top_front_max_gain = _normalize_unit(value.get("top_front_max_gain"))
    if top_front_max_gain is not None:
        normalized["top_front_max_gain"] = top_front_max_gain
    top_rear_max_gain = _normalize_unit(value.get("top_rear_max_gain"))
    if top_rear_max_gain is not None:
        normalized["top_rear_max_gain"] = top_rear_max_gain
    return normalized or None


def _resolve_group_bus(bus_id: str | None) -> str | None:
    normalized = _normalize_string(bus_id)
    if normalized is None:
        return None
    parts = [part for part in normalized.upper().split(".") if part]
    if len(parts) >= 2 and parts[0] == "BUS":
        return f"BUS.{parts[1]}"
    if len(parts) == 1 and parts[0].startswith("BUS"):
        return normalized.upper()
    return normalized.upper()


def _ensure_scene_intent(scene: dict[str, Any]) -> dict[str, Any]:
    intent = scene.get("intent")
    if isinstance(intent, dict):
        return intent
    created = {"confidence": 0.0, "locks": []}
    scene["intent"] = created
    return created


def _ensure_object_intent(obj: dict[str, Any]) -> dict[str, Any]:
    intent = obj.get("intent")
    if isinstance(intent, dict):
        if not isinstance(intent.get("locks"), list):
            intent["locks"] = []
        confidence = _coerce_float(intent.get("confidence"))
        if confidence is None:
            intent["confidence"] = 0.0
        return intent
    created = {"confidence": 0.0, "locks": []}
    obj["intent"] = created
    return created


def _ensure_bed_intent(bed: dict[str, Any]) -> dict[str, Any]:
    intent = bed.get("intent")
    if isinstance(intent, dict):
        if not isinstance(intent.get("locks"), list):
            intent["locks"] = []
        confidence = _coerce_float(intent.get("confidence"))
        if confidence is None:
            intent["confidence"] = 0.0
        return intent
    created = {"confidence": 0.0, "locks": []}
    bed["intent"] = created
    return created


def _ensure_hint_locks(obj: dict[str, Any]) -> dict[str, bool]:
    raw_locks = obj.get("locks")
    locks = raw_locks if isinstance(raw_locks, dict) else {}
    normalized = {
        "azimuth_hint": bool(locks.get("azimuth_hint")),
        "width_hint": bool(locks.get("width_hint")),
        "depth_hint": bool(locks.get("depth_hint")),
    }
    obj["locks"] = normalized
    return normalized


def _lock_id_list(intent_payload: Any) -> list[str]:
    if not isinstance(intent_payload, dict):
        return []
    lock_ids = intent_payload.get("locks")
    if not isinstance(lock_ids, list):
        return []
    normalized = sorted(
        {
            lock_id.strip()
            for lock_id in lock_ids
            if isinstance(lock_id, str) and lock_id.strip()
        }
    )
    return normalized


@lru_cache(maxsize=1)
def _scene_lock_specs() -> dict[str, dict[str, Any]]:
    registry = load_scene_locks()
    locks = registry.get("locks")
    if not isinstance(locks, dict):
        return {}
    return {
        lock_id: dict(payload)
        for lock_id, payload in locks.items()
        if isinstance(lock_id, str) and isinstance(payload, dict)
    }


@lru_cache(maxsize=1)
def _hard_lock_ids() -> frozenset[str]:
    specs = _scene_lock_specs()
    return frozenset(
        lock_id
        for lock_id, payload in specs.items()
        if _coerce_str(payload.get("severity")).strip().lower() == "hard"
    )


def _hard_lock_id_for_scope(
    *,
    scene_intent: Any,
    target_intent: Any = None,
) -> str | None:
    hard_ids = _hard_lock_ids()
    if not hard_ids:
        return None
    in_effect = set(_lock_id_list(scene_intent)) | set(_lock_id_list(target_intent))
    matched = sorted(lock_id for lock_id in in_effect if lock_id in hard_ids)
    if matched:
        return matched[0]
    return None


def _normalize_layers(inferred: Any) -> dict[str, dict[str, Any] | None]:
    layers: dict[str, dict[str, Any] | None] = {
        "cli": None,
        "suggested": None,
        "inferred": None,
    }
    if not isinstance(inferred, dict):
        return layers
    if any(key in inferred for key in layers):
        for key in layers:
            payload = inferred.get(key)
            if isinstance(payload, dict):
                layers[key] = _json_clone(payload)
        return layers
    layers["inferred"] = _json_clone(inferred)
    return layers


def _object_index(scene: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(scene, dict):
        return {}
    raw_objects = scene.get("objects")
    if not isinstance(raw_objects, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in raw_objects:
        if not isinstance(row, dict):
            continue
        stem_id = _normalize_string(row.get("stem_id"))
        if stem_id:
            index[stem_id] = row
    return index


def _bed_index(scene: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(scene, dict):
        return {}
    raw_beds = scene.get("beds")
    if not isinstance(raw_beds, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in raw_beds:
        if not isinstance(row, dict):
            continue
        bed_id = _normalize_string(row.get("bed_id"))
        if bed_id:
            index[bed_id] = row
    return index


def _entry_intent(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    intent = entry.get("intent")
    if isinstance(intent, dict):
        return intent
    return {}


def _scene_perspective_value(scene: Any) -> str | None:
    return _normalize_string(_entry_intent(scene).get("perspective"))


def _object_role_value(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    return _normalize_string(obj.get("role_id"))


def _object_bus_value(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = _normalize_string(obj.get("bus_id"))
    if value is None:
        return None
    return value.upper()


def _object_group_bus_value(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = _normalize_string(obj.get("group_bus"))
    if value is None:
        return None
    return value.upper()


def _object_width_explicit(obj: Any) -> float | None:
    return _normalize_unit(_entry_intent(obj).get("width"))


def _object_width_inferred(obj: Any) -> float | None:
    if not isinstance(obj, dict):
        return None
    return _normalize_unit(obj.get("width_hint"))


def _object_depth_explicit(obj: Any) -> float | None:
    return _normalize_unit(_entry_intent(obj).get("depth"))


def _object_depth_inferred(obj: Any) -> float | None:
    if not isinstance(obj, dict):
        return None
    return _normalize_unit(obj.get("depth_hint"))


def _object_azimuth_explicit(obj: Any) -> float | None:
    intent = _entry_intent(obj)
    position = intent.get("position")
    if isinstance(position, dict):
        azimuth = _normalize_azimuth(position.get("azimuth_deg"))
        if azimuth is not None:
            return azimuth
    return _normalize_azimuth(intent.get("azimuth_hint"))


def _object_azimuth_inferred(obj: Any) -> float | None:
    if not isinstance(obj, dict):
        return None
    return _normalize_azimuth(obj.get("azimuth_hint"))


def _object_surround_caps_value(obj: Any) -> dict[str, float] | None:
    return _normalize_surround_send_caps(_entry_intent(obj).get("surround_send_caps"))


def _object_height_caps_value(obj: Any) -> dict[str, float] | None:
    return _normalize_height_send_caps(_entry_intent(obj).get("height_send_caps"))


def _bed_diffuse_explicit(bed: Any) -> float | None:
    return _normalize_unit(_entry_intent(bed).get("diffuse"))


def _bed_diffuse_inferred(bed: Any) -> float | None:
    if not isinstance(bed, dict):
        return None
    return _normalize_unit(bed.get("width_hint"))


def _bed_height_caps_value(bed: Any) -> dict[str, float] | None:
    return _normalize_height_send_caps(_entry_intent(bed).get("height_send_caps"))


def _override_lock_id(stem_id: str, field_id: str) -> str:
    return f"scene_build_override:{stem_id}:{field_id}"


def _scene_override_lock_id(field_id: str) -> str:
    return f"scene_build_override:scene:{field_id}"


def _candidate_row(
    *,
    source: str,
    value: Any,
    lock_id: str | None = None,
) -> dict[str, Any] | None:
    if source not in _SUPPORTED_RECEIPT_SOURCES:
        return None
    if value is None:
        return None
    row = {
        "source": source,
        "value": _json_clone(value),
    }
    if lock_id:
        row["lock_id"] = lock_id
    return row


def _resolve_precedence(
    *,
    locked_value: Any = None,
    locked_lock_id: str | None = None,
    explicit_value: Any = None,
    explicit_lock_id: str | None = None,
    cli_value: Any = None,
    suggested_value: Any = None,
    inferred_value: Any = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    locked_candidate = _candidate_row(
        source=SOURCE_LOCKED,
        value=locked_value,
        lock_id=locked_lock_id,
    )
    if locked_candidate is not None:
        candidates.append(locked_candidate)

    explicit_source = SOURCE_LOCKED if explicit_lock_id else SOURCE_EXPLICIT
    explicit_candidate = _candidate_row(
        source=explicit_source,
        value=explicit_value,
        lock_id=explicit_lock_id,
    )
    if explicit_candidate is not None:
        candidates.append(explicit_candidate)

    cli_candidate = _candidate_row(source=SOURCE_EXPLICIT, value=cli_value)
    if cli_candidate is not None:
        candidates.append(cli_candidate)

    suggested_candidate = _candidate_row(source=SOURCE_SUGGESTED, value=suggested_value)
    if suggested_candidate is not None:
        candidates.append(suggested_candidate)

    inferred_candidate = _candidate_row(source=SOURCE_INFERRED, value=inferred_value)
    if inferred_candidate is not None:
        candidates.append(inferred_candidate)

    if not candidates:
        return {
            "source": SOURCE_INFERRED,
            "applied_value": None,
            "original_value": None,
            "lock_id": None,
        }

    winner = candidates[0]
    original_value = None
    if len(candidates) > 1:
        original_value = _json_clone(candidates[1]["value"])
    return {
        "source": winner["source"],
        "applied_value": _json_clone(winner["value"]),
        "original_value": original_value,
        "lock_id": winner.get("lock_id"),
    }


def _build_precedence_entry(
    *,
    scope: str,
    field: str,
    source: str,
    applied_value: Any,
    original_value: Any,
    lock_id: str | None,
    scene_id: str | None = None,
    object_id: str | None = None,
    stem_id: str | None = None,
    bed_id: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "scope": scope,
        "field": field,
        "source": source,
        "original_value": _json_clone(original_value),
        "applied_value": _json_clone(applied_value),
    }
    if scene_id:
        row["scene_id"] = scene_id
    if object_id:
        row["object_id"] = object_id
    if stem_id:
        row["stem_id"] = stem_id
    if bed_id:
        row["bed_id"] = bed_id
    if lock_id:
        row["lock_id"] = lock_id
    return row


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _coerce_str(entry.get("scope")).strip(),
        _coerce_str(entry.get("scene_id")).strip()
        or _coerce_str(entry.get("object_id")).strip()
        or _coerce_str(entry.get("bed_id")).strip()
        or _coerce_str(entry.get("stem_id")).strip(),
        _coerce_str(entry.get("stem_id")).strip(),
        _coerce_str(entry.get("field")).strip(),
    )


def _set_scene_perspective(scene: dict[str, Any], value: str | None) -> None:
    intent = _ensure_scene_intent(scene)
    if value is None:
        intent.pop("perspective", None)
        return
    intent["perspective"] = value


def _set_object_role(obj: dict[str, Any], value: str | None) -> None:
    if value is None:
        obj.pop("role_id", None)
        return
    obj["role_id"] = value


def _set_object_bus(
    obj: dict[str, Any],
    *,
    bus_id: str | None,
    fallback_group_bus: str | None,
) -> None:
    if bus_id is not None:
        obj["bus_id"] = bus_id
        resolved_group_bus = _resolve_group_bus(bus_id)
        if resolved_group_bus is not None:
            obj["group_bus"] = resolved_group_bus
        return
    obj.pop("bus_id", None)
    if fallback_group_bus is not None:
        obj["group_bus"] = fallback_group_bus
        return
    obj.pop("group_bus", None)


def _set_object_width(
    obj: dict[str, Any],
    *,
    value: float | None,
    locked: bool,
) -> None:
    intent = _ensure_object_intent(obj)
    if value is None:
        intent.pop("width", None)
        obj.pop("width_hint", None)
    else:
        intent["width"] = value
        obj["width_hint"] = value
    if locked:
        _ensure_hint_locks(obj)["width_hint"] = True


def _set_object_depth(
    obj: dict[str, Any],
    *,
    value: float | None,
    locked: bool,
) -> None:
    intent = _ensure_object_intent(obj)
    if value is None:
        intent.pop("depth", None)
        obj.pop("depth_hint", None)
    else:
        intent["depth"] = value
        obj["depth_hint"] = value
    if locked:
        _ensure_hint_locks(obj)["depth_hint"] = True


def _set_object_azimuth(
    obj: dict[str, Any],
    *,
    value: float | None,
    locked: bool,
) -> None:
    intent = _ensure_object_intent(obj)
    if value is None:
        obj.pop("azimuth_hint", None)
        position = intent.get("position")
        if isinstance(position, dict):
            position.pop("azimuth_deg", None)
            if not position:
                intent.pop("position", None)
        intent.pop("azimuth_hint", None)
    else:
        obj["azimuth_hint"] = value
        position = intent.get("position")
        if not isinstance(position, dict):
            position = {}
        position["azimuth_deg"] = value
        intent["position"] = position
    if locked:
        _ensure_hint_locks(obj)["azimuth_hint"] = True


def _set_object_surround_caps(obj: dict[str, Any], value: dict[str, float] | None) -> None:
    intent = _ensure_object_intent(obj)
    if value is None:
        intent.pop("surround_send_caps", None)
        return
    intent["surround_send_caps"] = _json_clone(value)


def _set_object_height_caps(obj: dict[str, Any], value: dict[str, float] | None) -> None:
    intent = _ensure_object_intent(obj)
    if value is None:
        intent.pop("height_send_caps", None)
        return
    intent["height_send_caps"] = _json_clone(value)


def _set_bed_diffuse(bed: dict[str, Any], value: float | None) -> None:
    intent = _ensure_bed_intent(bed)
    if value is None:
        intent.pop("diffuse", None)
        bed.pop("width_hint", None)
        return
    intent["diffuse"] = value
    bed["width_hint"] = value


def _set_bed_height_caps(bed: dict[str, Any], value: dict[str, float] | None) -> None:
    intent = _ensure_bed_intent(bed)
    if value is None:
        intent.pop("height_send_caps", None)
        return
    intent["height_send_caps"] = _json_clone(value)


def has_precedence_receipt(scene_payload: dict[str, Any]) -> bool:
    metadata = scene_payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    receipt = metadata.get("precedence_receipt")
    return isinstance(receipt, dict)


def apply_precedence(
    scene: dict[str, Any],
    locks: dict[str, Any] | None,
    inferred: dict[str, Any] | None,
    *,
    locks_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    merged_scene = _json_clone(scene)
    scene_id = _normalize_string(merged_scene.get("scene_id"))
    scene_intent = _ensure_scene_intent(merged_scene)
    scene_hard_lock_id = _hard_lock_id_for_scope(scene_intent=scene_intent)
    layers = _normalize_layers(inferred)
    layer_objects = {
        key: _object_index(payload)
        for key, payload in layers.items()
    }
    layer_beds = {
        key: _bed_index(payload)
        for key, payload in layers.items()
    }
    locks_payload = locks if isinstance(locks, dict) else {}
    scene_override = (
        locks_payload.get("scene")
        if isinstance(locks_payload.get("scene"), dict)
        else {}
    )
    overrides = locks_payload.get("overrides")
    overrides = overrides if isinstance(overrides, dict) else {}

    precedence_entries: list[dict[str, Any]] = []
    matched_stem_ids: set[str] = set()

    scene_perspective = _resolve_precedence(
        locked_value=_normalize_string(scene_override.get("perspective")),
        locked_lock_id=(
            _scene_override_lock_id("perspective")
            if _normalize_string(scene_override.get("perspective")) is not None
            else None
        ),
        explicit_value=_scene_perspective_value(merged_scene),
        explicit_lock_id=scene_hard_lock_id,
        cli_value=_scene_perspective_value(layers["cli"]),
        suggested_value=_scene_perspective_value(layers["suggested"]),
        inferred_value=_scene_perspective_value(layers["inferred"]),
    )
    if scene_perspective["applied_value"] is not None or scene_perspective["source"] == SOURCE_LOCKED:
        _set_scene_perspective(merged_scene, scene_perspective["applied_value"])
        precedence_entries.append(
            _build_precedence_entry(
                scope=_SCENE_SCOPE,
                scene_id=scene_id,
                field="perspective",
                source=scene_perspective["source"],
                original_value=scene_perspective["original_value"],
                applied_value=scene_perspective["applied_value"],
                lock_id=scene_perspective.get("lock_id"),
            )
        )

    objects = merged_scene.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            object_id = _normalize_string(obj.get("object_id")) or ""
            stem_id = _normalize_string(obj.get("stem_id")) or ""
            if not stem_id:
                continue
            intent = _ensure_object_intent(obj)
            object_hard_lock_id = _hard_lock_id_for_scope(
                scene_intent=scene_intent,
                target_intent=intent,
            )
            override = overrides.get(stem_id)
            override_payload = override if isinstance(override, dict) else {}
            if override_payload:
                matched_stem_ids.add(stem_id)
            placement_override = (
                override_payload.get("placement")
                if isinstance(override_payload.get("placement"), dict)
                else {}
            )
            layer_cli_obj = layer_objects["cli"].get(stem_id)
            layer_suggested_obj = layer_objects["suggested"].get(stem_id)
            layer_inferred_obj = layer_objects["inferred"].get(stem_id)

            role_result = _resolve_precedence(
                locked_value=_normalize_string(override_payload.get("role_id")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "role_id")
                    if _normalize_string(override_payload.get("role_id")) is not None
                    else None
                ),
                explicit_value=_object_role_value(obj),
                cli_value=_object_role_value(layer_cli_obj),
                suggested_value=_object_role_value(layer_suggested_obj),
                inferred_value=_object_role_value(layer_inferred_obj),
            )
            _set_object_role(obj, role_result["applied_value"])

            bus_result = _resolve_precedence(
                locked_value=_object_bus_value(override_payload),
                locked_lock_id=(
                    _override_lock_id(stem_id, "bus_id")
                    if _object_bus_value(override_payload) is not None
                    else None
                ),
                explicit_value=_object_bus_value(obj),
                cli_value=_object_bus_value(layer_cli_obj),
                suggested_value=_object_bus_value(layer_suggested_obj),
                inferred_value=_object_bus_value(layer_inferred_obj),
            )
            resolved_group_bus = _resolve_group_bus(bus_result["applied_value"])
            if resolved_group_bus is None:
                resolved_group_bus = (
                    _object_group_bus_value(obj)
                    or _object_group_bus_value(layer_cli_obj)
                    or _object_group_bus_value(layer_suggested_obj)
                    or _object_group_bus_value(layer_inferred_obj)
                )
            _set_object_bus(
                obj,
                bus_id=bus_result["applied_value"],
                fallback_group_bus=resolved_group_bus,
            )

            width_result = _resolve_precedence(
                locked_value=_normalize_unit(placement_override.get("width")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "placement.width")
                    if _normalize_unit(placement_override.get("width")) is not None
                    else None
                ),
                explicit_value=_object_width_explicit(obj),
                explicit_lock_id=object_hard_lock_id,
                cli_value=_object_width_explicit(layer_cli_obj),
                suggested_value=_object_width_explicit(layer_suggested_obj),
                inferred_value=(
                    _object_width_inferred(obj)
                    if _object_width_explicit(obj) is not None or layer_inferred_obj is None
                    else None
                )
                if _object_width_inferred(obj) is not None
                else (
                    _object_width_explicit(layer_inferred_obj)
                    or _object_width_inferred(layer_inferred_obj)
                ),
            )
            _set_object_width(
                obj,
                value=width_result["applied_value"],
                locked=width_result["source"] == SOURCE_LOCKED,
            )

            azimuth_result = _resolve_precedence(
                locked_value=_normalize_azimuth(placement_override.get("azimuth_deg")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "placement.azimuth_deg")
                    if _normalize_azimuth(placement_override.get("azimuth_deg")) is not None
                    else None
                ),
                explicit_value=_object_azimuth_explicit(obj),
                explicit_lock_id=object_hard_lock_id,
                cli_value=_object_azimuth_explicit(layer_cli_obj),
                suggested_value=_object_azimuth_explicit(layer_suggested_obj),
                inferred_value=(
                    _object_azimuth_inferred(obj)
                    if _object_azimuth_inferred(obj) is not None
                    else (
                        _object_azimuth_explicit(layer_inferred_obj)
                        or _object_azimuth_inferred(layer_inferred_obj)
                    )
                ),
            )
            _set_object_azimuth(
                obj,
                value=azimuth_result["applied_value"],
                locked=azimuth_result["source"] == SOURCE_LOCKED,
            )

            depth_result = _resolve_precedence(
                locked_value=_normalize_unit(placement_override.get("depth")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "placement.depth")
                    if _normalize_unit(placement_override.get("depth")) is not None
                    else None
                ),
                explicit_value=_object_depth_explicit(obj),
                explicit_lock_id=object_hard_lock_id,
                cli_value=_object_depth_explicit(layer_cli_obj),
                suggested_value=_object_depth_explicit(layer_suggested_obj),
                inferred_value=(
                    _object_depth_inferred(obj)
                    if _object_depth_inferred(obj) is not None
                    else (
                        _object_depth_explicit(layer_inferred_obj)
                        or _object_depth_inferred(layer_inferred_obj)
                    )
                ),
            )
            _set_object_depth(
                obj,
                value=depth_result["applied_value"],
                locked=depth_result["source"] == SOURCE_LOCKED,
            )

            surround_result = _resolve_precedence(
                locked_value=_normalize_surround_send_caps(override_payload.get("surround_send_caps")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "surround_send_caps")
                    if _normalize_surround_send_caps(override_payload.get("surround_send_caps"))
                    is not None
                    else None
                ),
                explicit_value=_object_surround_caps_value(obj),
                explicit_lock_id=object_hard_lock_id,
                cli_value=_object_surround_caps_value(layer_cli_obj),
                suggested_value=_object_surround_caps_value(layer_suggested_obj),
                inferred_value=_object_surround_caps_value(layer_inferred_obj),
            )
            _set_object_surround_caps(obj, surround_result["applied_value"])

            height_result = _resolve_precedence(
                locked_value=_normalize_height_send_caps(override_payload.get("height_send_caps")),
                locked_lock_id=(
                    _override_lock_id(stem_id, "height_send_caps")
                    if _normalize_height_send_caps(override_payload.get("height_send_caps"))
                    is not None
                    else None
                ),
                explicit_value=_object_height_caps_value(obj),
                explicit_lock_id=object_hard_lock_id,
                cli_value=_object_height_caps_value(layer_cli_obj),
                suggested_value=_object_height_caps_value(layer_suggested_obj),
                inferred_value=_object_height_caps_value(layer_inferred_obj),
            )
            _set_object_height_caps(obj, height_result["applied_value"])

            for field_id, result in (
                ("role_id", role_result),
                ("bus_id", bus_result),
                ("azimuth_deg", azimuth_result),
                ("width", width_result),
                ("depth", depth_result),
                ("surround_send_caps", surround_result),
                ("height_send_caps", height_result),
            ):
                precedence_entries.append(
                    _build_precedence_entry(
                        scope=_OBJECT_SCOPE,
                        scene_id=scene_id,
                        object_id=object_id or f"OBJ.{stem_id}",
                        stem_id=stem_id,
                        field=field_id,
                        source=result["source"],
                        original_value=result["original_value"],
                        applied_value=result["applied_value"],
                        lock_id=result.get("lock_id"),
                    )
                )

    beds = merged_scene.get("beds")
    if isinstance(beds, list):
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            bed_id = _normalize_string(bed.get("bed_id")) or ""
            if not bed_id:
                continue
            intent = _ensure_bed_intent(bed)
            bed_hard_lock_id = _hard_lock_id_for_scope(
                scene_intent=scene_intent,
                target_intent=intent,
            )
            layer_cli_bed = layer_beds["cli"].get(bed_id)
            layer_suggested_bed = layer_beds["suggested"].get(bed_id)
            layer_inferred_bed = layer_beds["inferred"].get(bed_id)

            diffuse_result = _resolve_precedence(
                explicit_value=_bed_diffuse_explicit(bed),
                explicit_lock_id=bed_hard_lock_id,
                cli_value=_bed_diffuse_explicit(layer_cli_bed),
                suggested_value=_bed_diffuse_explicit(layer_suggested_bed),
                inferred_value=(
                    _bed_diffuse_inferred(bed)
                    if _bed_diffuse_inferred(bed) is not None
                    else (
                        _bed_diffuse_explicit(layer_inferred_bed)
                        or _bed_diffuse_inferred(layer_inferred_bed)
                    )
                ),
            )
            _set_bed_diffuse(bed, diffuse_result["applied_value"])
            precedence_entries.append(
                _build_precedence_entry(
                    scope=_BED_SCOPE,
                    scene_id=scene_id,
                    bed_id=bed_id,
                    field="diffuse",
                    source=diffuse_result["source"],
                    original_value=diffuse_result["original_value"],
                    applied_value=diffuse_result["applied_value"],
                    lock_id=diffuse_result.get("lock_id"),
                )
            )

            bed_height_result = _resolve_precedence(
                explicit_value=_bed_height_caps_value(bed),
                explicit_lock_id=bed_hard_lock_id,
                cli_value=_bed_height_caps_value(layer_cli_bed),
                suggested_value=_bed_height_caps_value(layer_suggested_bed),
                inferred_value=_bed_height_caps_value(layer_inferred_bed),
            )
            _set_bed_height_caps(bed, bed_height_result["applied_value"])
            precedence_entries.append(
                _build_precedence_entry(
                    scope=_BED_SCOPE,
                    scene_id=scene_id,
                    bed_id=bed_id,
                    field="height_send_caps",
                    source=bed_height_result["source"],
                    original_value=bed_height_result["original_value"],
                    applied_value=bed_height_result["applied_value"],
                    lock_id=bed_height_result.get("lock_id"),
                )
            )

    precedence_entries.sort(key=_entry_sort_key)
    unmatched_stem_ids = sorted(
        stem_id
        for stem_id in overrides.keys()
        if isinstance(stem_id, str) and stem_id not in matched_stem_ids
    )

    metadata = merged_scene.get("metadata")
    metadata_payload = metadata if isinstance(metadata, dict) else {}
    precedence_receipt: dict[str, Any] = {
        "version": PRECEDENCE_RECEIPT_VERSION,
        "entries": precedence_entries,
        "unmatched_stem_ids": unmatched_stem_ids,
    }
    if isinstance(locks_path, Path):
        precedence_receipt["locks_path"] = locks_path.resolve().as_posix()
    metadata_payload["precedence_receipt"] = precedence_receipt

    merged_scene["metadata"] = metadata_payload
    return merged_scene


def _recommendation_action_id(recommendation: dict[str, Any]) -> str:
    return _coerce_str(recommendation.get("action_id")).strip()


def _action_matches_affected_actions(action_id: str, affected_actions: list[str]) -> bool:
    if not action_id or not affected_actions:
        return False
    return any(
        action_id == candidate or action_id.startswith(candidate)
        for candidate in affected_actions
        if isinstance(candidate, str) and candidate.strip()
    )


def _objects_by_stem_id(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _object_index(scene)


def _beds_by_bed_id(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _bed_index(scene)


def _recommendation_target_scope(recommendation: dict[str, Any]) -> dict[str, str]:
    scope = normalize_recommendation_scope(recommendation)
    stem_id = _normalize_string(scope.get("stem_id"))
    if stem_id is not None:
        return {"scope": "stem", "stem_id": stem_id}
    bed_id = _normalize_string(scope.get("bed_id"))
    if bed_id is not None:
        return {"scope": "bed", "bed_id": bed_id}
    bus_id = _normalize_string(scope.get("bus_id"))
    if bus_id is not None:
        return {"scope": "bed", "bed_id": bus_id}
    if scope.get("global") is True:
        return {"scope": "scene"}
    return {}


def _lock_conflicts_for_recommendation(
    recommendation: dict[str, Any],
    *,
    scene: dict[str, Any],
) -> list[dict[str, Any]]:
    action_id = _recommendation_action_id(recommendation)
    if not action_id:
        return []

    scene_intent = _entry_intent(scene)
    lock_ids: set[str] = set(_lock_id_list(scene_intent))
    target_scope = _recommendation_target_scope(recommendation)
    objects_by_stem_id = _objects_by_stem_id(scene)
    beds_by_bed_id = _beds_by_bed_id(scene)
    stem_id = target_scope.get("stem_id")
    bed_id = target_scope.get("bed_id")
    if stem_id is not None:
        object_payload = objects_by_stem_id.get(stem_id)
        if isinstance(object_payload, dict):
            lock_ids.update(_lock_id_list(_entry_intent(object_payload)))
    if bed_id is not None:
        bed_payload = beds_by_bed_id.get(bed_id)
        if isinstance(bed_payload, dict):
            lock_ids.update(_lock_id_list(_entry_intent(bed_payload)))

    scene_lock_specs = _scene_lock_specs()
    conflicts: list[dict[str, Any]] = []
    for lock_id in sorted(lock_ids):
        lock_spec = scene_lock_specs.get(lock_id)
        if not isinstance(lock_spec, dict):
            continue
        affected_actions = lock_spec.get("affected_actions")
        affected_actions = affected_actions if isinstance(affected_actions, list) else []
        if not _action_matches_affected_actions(action_id, affected_actions):
            continue
        severity = _coerce_str(lock_spec.get("severity")).strip().lower() or "taste"
        conflict: dict[str, Any] = {
            "lock_id": lock_id,
            "severity": severity,
            "action_id": action_id,
        }
        if stem_id is not None:
            conflict["stem_id"] = stem_id
        if bed_id is not None:
            conflict["bed_id"] = bed_id
        conflicts.append(conflict)
    return conflicts


def apply_recommendation_precedence(
    scene: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> None:
    if not isinstance(scene, dict):
        return
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        conflicts = _lock_conflicts_for_recommendation(recommendation, scene=scene)
        if not conflicts:
            continue
        recommendation["precedence_conflicts"] = conflicts
        hard_conflicts = [
            conflict
            for conflict in conflicts
            if _coerce_str(conflict.get("severity")).strip().lower() == "hard"
        ]
        if not hard_conflicts:
            continue
        gate_results = recommendation.get("gate_results")
        gate_results = gate_results if isinstance(gate_results, list) else []
        for context in ("auto_apply", "render"):
            gate_results.append(
                {
                    "gate_id": PRECEDENCE_GATE_ID,
                    "context": context,
                    "outcome": "reject",
                    "reason": f"scene_lock_conflict:{hard_conflicts[0]['lock_id']}",
                    "details": {
                        "conflicts": _json_clone(hard_conflicts),
                    },
                }
            )
        recommendation["gate_results"] = gate_results
        recommendation["eligible_auto_apply"] = False
        recommendation["eligible_render"] = False
