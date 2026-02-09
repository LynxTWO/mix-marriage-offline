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

_ENTRY_KINDS = {"label", "tooltip", "message"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load UI copy registries.")
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
        raise RuntimeError("jsonschema is required to validate UI copy registries.")

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


def load_ui_copy(path: Path) -> dict[str, Any]:
    payload = _load_yaml_object(path, label="UI copy registry")
    _validate_payload_against_schema(
        payload,
        schema_path=_repo_root() / "schemas" / "ui_copy.schema.json",
        payload_name="UI copy registry",
    )
    return payload


def _placeholder_entry(copy_id: str) -> dict[str, Any]:
    return {
        "text": copy_id,
        "tooltip": "Missing copy entry",
    }


def _schema_compatible_entry(copy_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _placeholder_entry(copy_id)

    text = value.get("text")
    if not isinstance(text, str):
        return _placeholder_entry(copy_id)

    entry: dict[str, Any] = {"text": text}
    tooltip = value.get("tooltip")
    if isinstance(tooltip, str):
        entry["tooltip"] = tooltip

    long_text = value.get("long")
    if isinstance(long_text, str):
        entry["long"] = long_text

    kind = value.get("kind")
    if isinstance(kind, str) and kind in _ENTRY_KINDS:
        entry["kind"] = kind
    return entry


def _default_locale(registry: dict[str, Any]) -> str:
    default_locale = registry.get("default_locale")
    if isinstance(default_locale, str) and default_locale.strip():
        return default_locale.strip()

    locales = registry.get("locales")
    if isinstance(locales, dict):
        locale_ids = sorted(
            locale_id.strip()
            for locale_id in locales.keys()
            if isinstance(locale_id, str) and locale_id.strip()
        )
        if locale_ids:
            return locale_ids[0]
    return "en-US"


def _locale_entries(registry: dict[str, Any], locale: str) -> dict[str, Any]:
    locales = registry.get("locales")
    if not isinstance(locales, dict):
        return {}
    locale_payload = locales.get(locale)
    if not isinstance(locale_payload, dict):
        return {}
    entries = locale_payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return entries


def resolve_ui_copy(
    keys: list[str],
    registry: dict[str, Any],
    locale: str | None = None,
) -> dict[str, Any]:
    locale_id = locale.strip() if isinstance(locale, str) and locale.strip() else _default_locale(
        registry
    )
    entry_map = _locale_entries(registry, locale_id)
    normalized_ids = sorted(
        {
            copy_id.strip()
            for copy_id in keys
            if isinstance(copy_id, str) and copy_id.strip()
        }
    )

    resolved: dict[str, Any] = {}
    for copy_id in normalized_ids:
        if copy_id in entry_map:
            resolved[copy_id] = _schema_compatible_entry(copy_id, entry_map.get(copy_id))
        else:
            resolved[copy_id] = _placeholder_entry(copy_id)
    return resolved
