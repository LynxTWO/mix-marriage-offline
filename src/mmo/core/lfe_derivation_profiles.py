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

DEFAULT_LFE_DERIVATION_PROFILE_ID = "LFE_DERIVE.DOLBY_120_LR24_TRIM_10"
LFE_DERIVATION_PROFILES_SCHEMA_VERSION = "0.1.0"


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "lfe_derivation_profiles.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load LFE derivation profile registries.")
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
        raise RuntimeError(
            "jsonschema is required to validate LFE derivation profile registries."
        )

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
    profiles_raw = payload.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ValueError(
            "LFE derivation profile registry must include an object 'profiles'."
        )
    return {
        profile_id: dict(profile_payload)
        for profile_id, profile_payload in profiles_raw.items()
        if isinstance(profile_id, str) and isinstance(profile_payload, dict)
    }


def _validate_profile_order(profiles: dict[str, dict[str, Any]], *, path: Path) -> None:
    profile_ids = [profile_id for profile_id in profiles.keys() if isinstance(profile_id, str)]
    sorted_profile_ids = sorted(profile_ids)
    if profile_ids != sorted_profile_ids:
        raise ValueError(
            f"LFE derivation profiles must be sorted by profile_id: {path}"
        )


def _normalize_notes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _normalize_profile(
    *,
    profile_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    slope_value = payload.get("slope_db_per_oct")
    if isinstance(slope_value, bool) or not isinstance(slope_value, int):
        raise ValueError(
            f"LFE derivation profile {profile_id} must define integer slope_db_per_oct."
        )
    return {
        "label": str(payload.get("label") or "").strip(),
        "lowpass_hz": float(payload.get("lowpass_hz")),
        "slope_db_per_oct": int(slope_value),
        "gain_trim_db": float(payload.get("gain_trim_db")),
        "notes": _normalize_notes(payload.get("notes")),
    }


def load_lfe_derivation_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="LFE derivation profile registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "lfe_derivation_profiles.schema.json",
        payload_name="LFE derivation profile registry",
    )

    schema_version = payload.get("schema_version")
    if schema_version != LFE_DERIVATION_PROFILES_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported LFE derivation profiles schema_version: "
            f"{schema_version!r}. Expected {LFE_DERIVATION_PROFILES_SCHEMA_VERSION!r}."
        )

    profiles = _profiles_map(payload)
    _validate_profile_order(profiles, path=resolved_path)
    return {
        profile_id: _normalize_profile(profile_id=profile_id, payload=profiles[profile_id])
        for profile_id in sorted(profiles.keys())
    }


def list_lfe_derivation_profile_ids(path: Path | None = None) -> list[str]:
    return sorted(load_lfe_derivation_profiles(path).keys())


def get_lfe_derivation_profile(
    profile_id: str | None,
    path: Path | None = None,
) -> dict[str, Any]:
    normalized_profile_id = str(profile_id or "").strip()
    if not normalized_profile_id:
        normalized_profile_id = DEFAULT_LFE_DERIVATION_PROFILE_ID

    profiles = load_lfe_derivation_profiles(path)
    payload = profiles.get(normalized_profile_id)
    if isinstance(payload, dict):
        row = {"lfe_derivation_profile_id": normalized_profile_id}
        row.update(dict(payload))
        return row

    known_ids = sorted(profiles.keys())
    if known_ids:
        raise ValueError(
            "Unknown lfe_derivation_profile_id: "
            f"{normalized_profile_id}. Known lfe_derivation_profile_ids: {', '.join(known_ids)}"
        )
    raise ValueError(
        f"Unknown lfe_derivation_profile_id: {normalized_profile_id}. "
        "No LFE derivation profiles are available."
    )
