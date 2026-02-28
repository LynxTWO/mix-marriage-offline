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

from mmo.core.loudness_methods import get_loudness_method
from mmo.resources import data_root, ontology_dir, schemas_dir

DEFAULT_LOUDNESS_PROFILE_ID = "LOUD.EBU_R128_PROGRAM"
_LOUDNESS_PROFILES_SCHEMA_VERSION = "0.1.0"


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "loudness_profiles.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load loudness profile registries.")
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
        raise RuntimeError("jsonschema is required to validate loudness profile registries.")

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
        raise ValueError("Loudness profiles registry must include an object 'profiles'.")
    return {
        profile_id: dict(profile_payload)
        for profile_id, profile_payload in profiles_raw.items()
        if isinstance(profile_id, str) and isinstance(profile_payload, dict)
    }


def _validate_profile_order(profiles: dict[str, dict[str, Any]], *, path: Path) -> None:
    profile_ids = [profile_id for profile_id in profiles.keys() if isinstance(profile_id, str)]
    sorted_profile_ids = sorted(profile_ids)
    if profile_ids != sorted_profile_ids:
        raise ValueError(f"Loudness profiles must be sorted by profile_id: {path}")


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
    tolerance = payload.get("tolerance_lu")
    tolerance_lu: float | None
    if isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool):
        tolerance_lu = float(tolerance)
    else:
        tolerance_lu = None

    return {
        "label": str(payload.get("label") or "").strip(),
        "target_loudness": float(payload.get("target_loudness")),
        "target_unit": str(payload.get("target_unit") or "").strip(),
        "tolerance_lu": tolerance_lu,
        "max_true_peak_dbtp": float(payload.get("max_true_peak_dbtp")),
        "method_id": str(payload.get("method_id") or "").strip(),
        "scope": str(payload.get("scope") or "").strip(),
        "compliance_mode": str(payload.get("compliance_mode") or "").strip(),
        "best_effort": bool(payload.get("best_effort", False)),
        "notes": _normalize_notes(payload.get("notes")),
    }


def load_loudness_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Loudness profiles registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "loudness_profiles.schema.json",
        payload_name="Loudness profiles registry",
    )

    schema_version = payload.get("schema_version")
    if schema_version != _LOUDNESS_PROFILES_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported loudness profiles schema_version: "
            f"{schema_version!r}. Expected {_LOUDNESS_PROFILES_SCHEMA_VERSION!r}."
        )

    profiles = _profiles_map(payload)
    _validate_profile_order(profiles, path=resolved_path)
    return {
        profile_id: _normalize_profile(profile_id=profile_id, payload=profiles[profile_id])
        for profile_id in sorted(profiles.keys())
    }


def list_loudness_profile_ids(path: Path | None = None) -> list[str]:
    return sorted(load_loudness_profiles(path).keys())


def list_loudness_profiles(path: Path | None = None) -> list[dict[str, Any]]:
    profiles = load_loudness_profiles(path)
    rows: list[dict[str, Any]] = []
    for profile_id in sorted(profiles.keys()):
        row = {"loudness_profile_id": profile_id}
        row.update(dict(profiles[profile_id]))
        rows.append(row)
    return rows


def get_loudness_profile(profile_id: str | None, path: Path | None = None) -> dict[str, Any]:
    normalized_profile_id = str(profile_id or "").strip()
    if not normalized_profile_id:
        normalized_profile_id = DEFAULT_LOUDNESS_PROFILE_ID

    profiles = load_loudness_profiles(path)
    payload = profiles.get(normalized_profile_id)
    if isinstance(payload, dict):
        row = {"loudness_profile_id": normalized_profile_id}
        row.update(dict(payload))
        return row

    known_ids = sorted(profiles.keys())
    if known_ids:
        raise ValueError(
            "Unknown loudness_profile_id: "
            f"{normalized_profile_id}. Known loudness_profile_ids: {', '.join(known_ids)}"
        )
    raise ValueError(
        f"Unknown loudness_profile_id: {normalized_profile_id}. "
        "No loudness profiles are available."
    )


def resolve_loudness_profile_receipt(
    profile_id: str | None,
    path: Path | None = None,
) -> dict[str, Any]:
    profile = get_loudness_profile(profile_id, path)
    resolved_method_id = str(profile.get("method_id") or "").strip()
    warnings: list[str] = []
    method_implemented = False

    try:
        method = get_loudness_method(resolved_method_id)
        resolved_method_id = method.method_id
        method_implemented = bool(method.implemented)
        if not method_implemented:
            warnings.append(
                (
                    f"Loudness method {method.method_id!r} is registered but not implemented "
                    "yet; compliance enforcement is not applied."
                )
            )
    except ValueError:
        warnings.append(
            (
                f"Loudness method {resolved_method_id!r} is not registered; "
                "compliance enforcement is not applied."
            )
        )

    compliance_mode = str(profile.get("compliance_mode") or "compliance").strip().lower()
    if compliance_mode == "informational":
        warnings.append(
            "This loudness profile is informational playback normalization guidance, not a delivery spec."
        )
    if bool(profile.get("best_effort")):
        warnings.append(
            (
                "Best-effort mapping: source guidance references earlier BS.1770 revisions; "
                "MMO meters using BS.1770-5."
            )
        )

    tolerance_lu = profile.get("tolerance_lu")
    normalized_tolerance_lu = float(tolerance_lu) if isinstance(tolerance_lu, float) else None

    return {
        "loudness_profile_id": profile["loudness_profile_id"],
        "target_loudness": float(profile["target_loudness"]),
        "target_unit": str(profile["target_unit"]),
        "tolerance_lu": normalized_tolerance_lu,
        "max_true_peak_dbtp": float(profile["max_true_peak_dbtp"]),
        "method_id": resolved_method_id,
        "method_implemented": method_implemented,
        "scope": str(profile["scope"]),
        "compliance_mode": compliance_mode,
        "best_effort": bool(profile.get("best_effort", False)),
        "notes": _normalize_notes(profile.get("notes")),
        "warnings": list(warnings),
    }
