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

from mmo.resources import data_root, ontology_dir, schemas_dir

SCENE_LOCKS_SCHEMA_VERSION = "0.1.0"


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "scene_locks.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load scene locks registries.")
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
        raise RuntimeError("jsonschema is required to validate scene locks registries.")

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _locks_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locks = payload.get("locks")
    if not isinstance(locks, dict):
        return {}
    return {
        lock_id: dict(lock_payload)
        for lock_id, lock_payload in locks.items()
        if isinstance(lock_id, str) and isinstance(lock_payload, dict)
    }


def _validate_lock_order(locks: dict[str, dict[str, Any]], *, path: Path) -> None:
    lock_ids = [lock_id for lock_id in locks.keys() if isinstance(lock_id, str)]
    sorted_lock_ids = sorted(lock_ids)
    if lock_ids != sorted_lock_ids:
        raise ValueError(f"Scene locks must be sorted by lock_id: {path}")


def load_scene_locks(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Scene locks registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "scene_locks.schema.json",
        payload_name="Scene locks registry",
    )

    locks = _locks_map(payload)
    _validate_lock_order(locks, path=resolved_path)
    normalized_payload = dict(payload)
    normalized_payload["locks"] = {
        lock_id: dict(locks[lock_id]) for lock_id in sorted(locks.keys())
    }
    return normalized_payload


def list_scene_locks(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_scene_locks(path)
    locks = _locks_map(payload)
    rows: list[dict[str, Any]] = []
    for lock_id in sorted(locks.keys()):
        row = {"lock_id": lock_id}
        row.update(dict(locks[lock_id]))
        rows.append(row)
    return rows


def get_scene_lock(lock_id: str, path: Path | None = None) -> dict[str, Any] | None:
    normalized_lock_id = lock_id.strip() if isinstance(lock_id, str) else ""
    if not normalized_lock_id:
        return None
    for lock in list_scene_locks(path):
        if lock.get("lock_id") == normalized_lock_id:
            return dict(lock)
    return None
