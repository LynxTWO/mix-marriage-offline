from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.resources import schemas_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load help registries.")
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
        raise RuntimeError("jsonschema is required to validate help registries.")

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


def load_help_registry(path: Path) -> dict[str, Any]:
    payload = _load_yaml_object(path, label="Help registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "help_registry.schema.json",
        payload_name="Help registry",
    )
    return payload


def _placeholder_entry(help_id: str) -> dict[str, Any]:
    return {
        "title": help_id,
        "short": "Missing help entry",
        "long": f"No help text found for {help_id}.",
    }


def _schema_compatible_entry(help_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _placeholder_entry(help_id)

    title = value.get("title")
    short = value.get("short")
    if not isinstance(title, str) or not isinstance(short, str):
        return _placeholder_entry(help_id)

    entry: dict[str, Any] = {"title": title, "short": short}
    long_text = value.get("long")
    if isinstance(long_text, str):
        entry["long"] = long_text

    cues = value.get("cues")
    if isinstance(cues, list) and all(isinstance(item, str) for item in cues):
        entry["cues"] = list(cues)

    watch_out_for = value.get("watch_out_for")
    if isinstance(watch_out_for, list) and all(
        isinstance(item, str) for item in watch_out_for
    ):
        entry["watch_out_for"] = list(watch_out_for)

    return entry


def resolve_help_entries(help_ids: list[str], registry: dict[str, Any]) -> dict[str, Any]:
    entries = registry.get("entries") if isinstance(registry, dict) else None
    entry_map = entries if isinstance(entries, dict) else {}
    normalized_ids = sorted(
        {
            help_id.strip()
            for help_id in help_ids
            if isinstance(help_id, str) and help_id.strip()
        }
    )

    resolved: dict[str, Any] = {}
    for help_id in normalized_ids:
        if help_id in entry_map:
            resolved[help_id] = _schema_compatible_entry(help_id, entry_map.get(help_id))
        else:
            resolved[help_id] = _placeholder_entry(help_id)
    return resolved
