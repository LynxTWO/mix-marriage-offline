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


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "translation_profiles.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load translation profile registries.")
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
        raise RuntimeError("jsonschema is required to validate translation profile registries.")

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


def _profiles_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        profile_id: dict(profile_payload)
        for profile_id, profile_payload in payload.items()
        if isinstance(profile_id, str) and isinstance(profile_payload, dict)
    }


def _validate_profile_order(profiles: dict[str, dict[str, Any]], *, path: Path) -> None:
    profile_ids = [profile_id for profile_id in profiles.keys() if isinstance(profile_id, str)]
    sorted_profile_ids = sorted(profile_ids)
    if profile_ids != sorted_profile_ids:
        raise ValueError(f"Translation profiles must be sorted by profile_id: {path}")


def load_translation_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Translation profiles registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "translation_profiles.schema.json",
        payload_name="Translation profiles registry",
    )

    profiles = _profiles_map(payload)
    _validate_profile_order(profiles, path=resolved_path)
    return {
        profile_id: dict(profiles[profile_id])
        for profile_id in sorted(profiles.keys())
    }


def list_translation_profiles(path: Path | None = None) -> list[dict[str, Any]]:
    profiles = load_translation_profiles(path)
    rows: list[dict[str, Any]] = []
    for profile_id in sorted(profiles.keys()):
        row = {"profile_id": profile_id}
        row.update(dict(profiles[profile_id]))
        rows.append(row)
    return rows


def get_translation_profile(profile_id: str, path: Path | None = None) -> dict[str, Any]:
    normalized_profile_id = profile_id.strip() if isinstance(profile_id, str) else ""
    if not normalized_profile_id:
        raise ValueError("profile_id must be a non-empty string.")

    profiles = load_translation_profiles(path)
    payload = profiles.get(normalized_profile_id)
    if isinstance(payload, dict):
        row = {"profile_id": normalized_profile_id}
        row.update(dict(payload))
        return row

    known_ids = sorted(profiles.keys())
    if known_ids:
        raise ValueError(
            "Unknown translation profile_id: "
            f"{normalized_profile_id}. Known profile_ids: {', '.join(known_ids)}"
        )
    raise ValueError(
        f"Unknown translation profile_id: {normalized_profile_id}. "
        "No translation profiles are available."
    )
