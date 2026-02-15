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

SPEAKER_POSITIONS_SCHEMA_VERSION = "0.1.0"


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "speaker_positions.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load speaker positions.")
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
        raise RuntimeError("jsonschema is required to validate speaker positions.")

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


def _layouts_map(payload: dict[str, Any]) -> dict[str, Any]:
    layouts = payload.get("layouts")
    if not isinstance(layouts, dict):
        return {}
    return layouts


def _validate_layout_order(layouts: dict[str, Any], *, path: Path) -> None:
    layout_ids = [layout_id for layout_id in layouts.keys() if isinstance(layout_id, str)]
    if layout_ids != sorted(layout_ids):
        raise ValueError(f"Speaker positions layouts must be sorted by layout_id: {path}")


def _normalize_channels(
    channels: list[dict[str, Any]],
    *,
    layout_id: str,
    path: Path,
) -> list[dict[str, Any]]:
    channel_ids: list[int] = []
    normalized: list[dict[str, Any]] = []
    for channel in channels:
        ch = channel.get("ch")
        name = channel.get("name")
        azimuth_deg = channel.get("azimuth_deg")
        elevation_deg = channel.get("elevation_deg")
        if (
            isinstance(ch, bool)
            or not isinstance(ch, int)
            or not isinstance(name, str)
            or isinstance(azimuth_deg, bool)
            or not isinstance(azimuth_deg, (int, float))
            or isinstance(elevation_deg, bool)
            or not isinstance(elevation_deg, (int, float))
        ):
            continue
        channel_ids.append(ch)
        normalized.append(
            {
                "ch": ch,
                "name": name,
                "azimuth_deg": float(azimuth_deg),
                "elevation_deg": float(elevation_deg),
            }
        )

    if channel_ids != sorted(channel_ids):
        raise ValueError(
            "Speaker positions channels must be sorted by ch: "
            f"{layout_id} ({path})"
        )
    if len(channel_ids) != len(set(channel_ids)):
        raise ValueError(
            "Speaker positions channels must be deterministic "
            f"(duplicate ch values): {layout_id} ({path})"
        )

    normalized.sort(key=lambda item: int(item["ch"]))
    return normalized


def _normalize_layouts(layouts: dict[str, Any], *, path: Path) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for layout_id in sorted(layouts.keys()):
        if not isinstance(layout_id, str):
            continue
        layout = layouts.get(layout_id)
        if not isinstance(layout, dict):
            continue
        channels = layout.get("channels")
        if not isinstance(channels, list):
            continue
        channel_rows = [item for item in channels if isinstance(item, dict)]
        normalized[layout_id] = {
            "channels": _normalize_channels(
                channel_rows,
                layout_id=layout_id,
                path=path,
            )
        }
    return normalized


def load_speaker_positions(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Speaker positions registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "speaker_positions.schema.json",
        payload_name="Speaker positions registry",
    )

    layouts = _layouts_map(payload)
    _validate_layout_order(layouts, path=resolved_path)
    normalized_layouts = _normalize_layouts(layouts, path=resolved_path)
    return {
        "schema_version": payload.get("schema_version"),
        "layouts": normalized_layouts,
    }


def get_layout_positions(
    layout_id: str,
    path: Path | None = None,
) -> list[dict[str, Any]] | None:
    normalized_layout_id = layout_id.strip() if isinstance(layout_id, str) else ""
    if not normalized_layout_id:
        return None

    payload = load_speaker_positions(path)
    layouts = payload.get("layouts")
    if not isinstance(layouts, dict):
        return None
    layout = layouts.get(normalized_layout_id)
    if not isinstance(layout, dict):
        return None
    channels = layout.get("channels")
    if not isinstance(channels, list):
        return None
    return [dict(channel) for channel in channels if isinstance(channel, dict)]
