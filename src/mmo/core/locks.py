from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from mmo.core.precedence import apply_precedence
from mmo.resources import schemas_dir

SCENE_BUILD_LOCKS_VERSION = "0.1.0"


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _normalize_bus_id(value: Any) -> str:
    return _coerce_str(value).strip().upper()


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _round_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return round(value, 3)


def _round_azimuth(value: float) -> float:
    if value < -180.0:
        return -180.0
    if value > 180.0:
        return 180.0
    return round(value, 3)


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load scene locks.")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(f"Failed to read {label} YAML from {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} YAML is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} YAML root must be a mapping: {path}")
    return payload


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON root must be an object: {path}")
    return payload


def _load_locks_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return _load_json_object(path, label=label)
    return _load_yaml_object(path, label=label)


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _validate_payload_against_schema(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate scene lock payloads.")

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: (list(err.path), err.message),
    )
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "root"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _validate_sorted_stem_ids(overrides: dict[str, Any], *, path: Path) -> None:
    stem_ids = [stem_id for stem_id in overrides.keys() if isinstance(stem_id, str)]
    if stem_ids != sorted(stem_ids):
        raise ValueError(f"Scene build locks overrides must be sorted by stem_id: {path}")


def _normalize_surround_send_caps(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, float] = {}
    side_max_gain = _coerce_float(value.get("side_max_gain"))
    if side_max_gain is not None:
        normalized["side_max_gain"] = _round_unit(side_max_gain)
    rear_max_gain = _coerce_float(value.get("rear_max_gain"))
    if rear_max_gain is not None:
        normalized["rear_max_gain"] = _round_unit(rear_max_gain)
    return normalized or None


def _normalize_height_send_caps(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, float] = {}
    top_max_gain = _coerce_float(value.get("top_max_gain"))
    if top_max_gain is not None:
        normalized["top_max_gain"] = _round_unit(top_max_gain)
    top_front_max_gain = _coerce_float(value.get("top_front_max_gain"))
    if top_front_max_gain is not None:
        normalized["top_front_max_gain"] = _round_unit(top_front_max_gain)
    top_rear_max_gain = _coerce_float(value.get("top_rear_max_gain"))
    if top_rear_max_gain is not None:
        normalized["top_rear_max_gain"] = _round_unit(top_rear_max_gain)
    return normalized or None


def _normalize_override(stem_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}

    role_id = _coerce_str(payload.get("role_id")).strip()
    if role_id:
        normalized["role_id"] = role_id

    bus_id = _normalize_bus_id(payload.get("bus_id"))
    if bus_id:
        normalized["bus_id"] = bus_id

    placement = payload.get("placement")
    if isinstance(placement, dict):
        normalized_placement: dict[str, float] = {}
        azimuth_deg = _coerce_float(placement.get("azimuth_deg"))
        if azimuth_deg is not None:
            normalized_placement["azimuth_deg"] = _round_azimuth(azimuth_deg)
        width = _coerce_float(placement.get("width"))
        if width is not None:
            normalized_placement["width"] = _round_unit(width)
        depth = _coerce_float(placement.get("depth"))
        if depth is not None:
            normalized_placement["depth"] = _round_unit(depth)
        if normalized_placement:
            normalized["placement"] = normalized_placement

    surround_send_caps = _normalize_surround_send_caps(payload.get("surround_send_caps"))
    if surround_send_caps is not None:
        normalized["surround_send_caps"] = surround_send_caps

    height_send_caps = _normalize_height_send_caps(payload.get("height_send_caps"))
    if height_send_caps is not None:
        normalized["height_send_caps"] = height_send_caps

    note = _coerce_str(payload.get("note")).strip()
    if note:
        normalized["note"] = note

    if not normalized:
        raise ValueError(f"Scene build lock override for {stem_id} is empty.")
    return normalized


def _normalize_scene_override(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}

    perspective = _coerce_str(payload.get("perspective")).strip().lower()
    if perspective:
        normalized["perspective"] = perspective

    return normalized


def load_scene_build_locks(path: Path) -> dict[str, Any]:
    payload = _load_locks_object(path, label="Scene build locks")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "scene_locks.schema.json",
        payload_name="Scene build locks",
    )

    version = _coerce_str(payload.get("version")).strip()
    scene_payload = _normalize_scene_override(payload.get("scene"))
    overrides = payload.get("overrides")
    if not version:
        raise ValueError(
            "Scene build locks must include a supported top-level version."
        )
    if version != SCENE_BUILD_LOCKS_VERSION:
        raise ValueError(
            f"Unsupported scene build locks version {version!r}; expected {SCENE_BUILD_LOCKS_VERSION}."
        )
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError(
            "Scene build locks overrides must be an object when provided."
        )
    if not scene_payload and not overrides:
        raise ValueError(
            "Scene build locks must include at least one scene override or stem override."
        )

    _validate_sorted_stem_ids(overrides, path=path)

    normalized_overrides: dict[str, dict[str, Any]] = {}
    for stem_id in sorted(overrides.keys()):
        stem_id_value = stem_id.strip() if isinstance(stem_id, str) else ""
        entry = overrides.get(stem_id)
        if not stem_id_value or not isinstance(entry, dict):
            continue
        normalized_overrides[stem_id_value] = _normalize_override(stem_id_value, entry)

    normalized_payload = {
        "version": SCENE_BUILD_LOCKS_VERSION,
        "overrides": normalized_overrides,
    }
    if scene_payload:
        normalized_payload["scene"] = scene_payload
    return normalized_payload


def _resolve_group_bus(bus_id: str) -> str:
    normalized = _coerce_str(bus_id).strip().upper()
    if not normalized:
        return ""
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 2 and parts[0] == "BUS":
        return f"BUS.{parts[1]}"
    if len(parts) == 1 and parts[0].startswith("BUS"):
        return normalized
    return normalized


def _ensure_intent_payload(obj: dict[str, Any]) -> dict[str, Any]:
    intent = obj.get("intent")
    if not isinstance(intent, dict):
        intent = {}
        obj["intent"] = intent
    if not isinstance(intent.get("locks"), list):
        intent["locks"] = []
    confidence = _coerce_float(intent.get("confidence"))
    if confidence is None:
        intent["confidence"] = 0.0
    return intent


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


def apply_scene_build_locks(
    scene_payload: dict[str, Any],
    locks_payload: dict[str, Any],
    *,
    locks_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(scene_payload, dict):
        raise ValueError("scene_payload must be an object.")
    if not isinstance(locks_payload, dict):
        raise ValueError("locks_payload must be an object.")

    overrides = locks_payload.get("overrides")
    if not isinstance(overrides, dict):
        raise ValueError("locks_payload.overrides must be an object.")
    return apply_precedence(
        scene_payload,
        locks_payload,
        None,
        locks_path=locks_path,
    )


def load_and_apply_scene_build_locks(
    scene_payload: dict[str, Any],
    *,
    locks_path: Path,
) -> dict[str, Any]:
    locks_payload = load_scene_build_locks(locks_path)
    return apply_scene_build_locks(
        scene_payload,
        locks_payload,
        locks_path=locks_path,
    )
