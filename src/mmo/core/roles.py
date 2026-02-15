import json
import re
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.resources import data_root, ontology_dir, schemas_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "roles.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load roles registry.")
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
        raise RuntimeError("jsonschema is required to validate roles registry.")

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
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _roles_map(payload: dict[str, Any]) -> dict[str, Any]:
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        return {}
    return roles


def _role_entries(roles: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        role_id: dict(entry)
        for role_id, entry in roles.items()
        if (
            isinstance(role_id, str)
            and role_id != "_meta"
            and isinstance(entry, dict)
        )
    }


def _validate_role_order(roles: dict[str, Any], *, path: Path) -> None:
    role_ids = [
        role_id
        for role_id in roles.keys()
        if isinstance(role_id, str) and role_id != "_meta"
    ]
    sorted_role_ids = sorted(role_ids)
    if role_ids != sorted_role_ids:
        raise ValueError(f"Roles registry entries must be sorted by role_id: {path}")


def _validate_role_regex_patterns(roles: dict[str, dict[str, Any]]) -> None:
    invalid_patterns: list[str] = []
    for role_id in sorted(roles.keys()):
        entry = roles.get(role_id)
        if not isinstance(entry, dict):
            continue
        inference = entry.get("inference")
        if not isinstance(inference, dict):
            continue
        regex_values = inference.get("regex")
        if not isinstance(regex_values, list):
            continue
        for pattern in regex_values:
            if not isinstance(pattern, str):
                continue
            try:
                re.compile(pattern)
            except re.error:
                invalid_patterns.append(f"{role_id}: {pattern}")
    if invalid_patterns:
        raise ValueError(
            "Roles registry inference regex patterns failed to compile: "
            + ", ".join(invalid_patterns)
        )


def load_roles(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Roles registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "roles.schema.json",
        payload_name="Roles registry",
    )

    roles = _roles_map(payload)
    _validate_role_order(roles, path=resolved_path)
    entries = _role_entries(roles)
    _validate_role_regex_patterns(entries)

    normalized_roles: dict[str, Any] = {}
    meta_payload = roles.get("_meta")
    if isinstance(meta_payload, dict):
        normalized_roles["_meta"] = dict(meta_payload)
    for role_id in sorted(entries.keys()):
        normalized_roles[role_id] = dict(entries[role_id])

    normalized_payload = dict(payload)
    normalized_payload["roles"] = normalized_roles
    return normalized_payload


def list_roles(path: Path | None = None) -> list[str]:
    payload = load_roles(path)
    roles = _roles_map(payload)
    return sorted(
        role_id
        for role_id, entry in roles.items()
        if (
            isinstance(role_id, str)
            and role_id != "_meta"
            and isinstance(entry, dict)
        )
    )


def resolve_role(role_id: str, path: Path | None = None) -> dict[str, Any]:
    normalized_role_id = role_id.strip() if isinstance(role_id, str) else ""
    if not normalized_role_id:
        raise ValueError("role_id must be a non-empty string.")

    payload = load_roles(path)
    roles = _roles_map(payload)
    role = roles.get(normalized_role_id)
    if isinstance(role, dict) and normalized_role_id != "_meta":
        return dict(role)

    known_ids = sorted(
        candidate
        for candidate, value in roles.items()
        if (
            isinstance(candidate, str)
            and candidate != "_meta"
            and isinstance(value, dict)
        )
    )
    if known_ids:
        raise ValueError(
            f"Unknown role_id: {normalized_role_id}. "
            f"Known role_ids: {', '.join(known_ids)}"
        )
    raise ValueError(f"Unknown role_id: {normalized_role_id}. No roles are available.")
