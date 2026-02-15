from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


TIMELINE_SCHEMA_VERSION = "0.1.0"


def _timeline_schema_path() -> Path:
    from mmo.resources import schemas_dir
    return schemas_dir() / "timeline.schema.json"


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "jsonschema referencing support is unavailable; cannot validate timeline files."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = _load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _validate_timeline_schema(payload: dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate timeline files.")

    schema_path = _timeline_schema_path()
    schema = _load_json_schema(schema_path)
    registry = _build_schema_registry(schema_path.parent)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.path) or "$"
        lines.append(f"- {path}: {error.message}")
    raise ValueError("Timeline schema validation failed:\n" + "\n".join(lines))


def _coerce_seconds(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number.")
    return float(value)


def normalize_timeline(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Timeline payload must be an object.")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError("timeline.schema_version must be a non-empty string.")
    if schema_version != TIMELINE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported timeline schema_version: "
            f"{schema_version!r} (expected {TIMELINE_SCHEMA_VERSION!r})."
        )

    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("timeline.sections must be an array.")

    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            raise ValueError(f"timeline.sections[{index}] must be an object.")

        section_id = raw_section.get("id")
        if not isinstance(section_id, str) or not section_id.strip():
            raise ValueError(f"timeline.sections[{index}].id must be a non-empty string.")

        label = raw_section.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"timeline.sections[{index}].label must be a non-empty string.")

        start_s = _coerce_seconds(
            raw_section.get("start_s"),
            field_name=f"timeline.sections[{index}].start_s",
        )
        end_s = _coerce_seconds(
            raw_section.get("end_s"),
            field_name=f"timeline.sections[{index}].end_s",
        )
        sections.append(
            {
                "id": section_id.strip(),
                "label": label.strip(),
                "start_s": start_s,
                "end_s": end_s,
            }
        )

    sections.sort(
        key=lambda item: (
            float(item["start_s"]),
            float(item["end_s"]),
            str(item["id"]),
            str(item["label"]),
        )
    )
    normalized = {
        "schema_version": schema_version,
        "sections": sections,
    }
    _validate_section_intervals(normalized)
    return normalized


def _validate_section_intervals(timeline: dict[str, Any]) -> None:
    raw_sections = timeline.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("timeline.sections must be an array.")

    previous_id: str | None = None
    previous_start: float | None = None
    previous_end: float | None = None
    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            raise ValueError(f"timeline.sections[{index}] must be an object.")

        section_id = raw_section.get("id")
        if not isinstance(section_id, str) or not section_id.strip():
            raise ValueError(f"timeline.sections[{index}].id must be a non-empty string.")
        start_s = _coerce_seconds(
            raw_section.get("start_s"),
            field_name=f"timeline.sections[{index}].start_s",
        )
        end_s = _coerce_seconds(
            raw_section.get("end_s"),
            field_name=f"timeline.sections[{index}].end_s",
        )

        if not start_s < end_s:
            raise ValueError(
                f"timeline.sections[{index}] start_s must be < end_s (got {start_s} and {end_s})."
            )

        if previous_start is not None and start_s < previous_start:
            raise ValueError("timeline.sections must be sorted by start_s.")

        if previous_end is not None and start_s < previous_end:
            raise ValueError(
                "Timeline sections overlap: "
                f"{previous_id} ({previous_start}..{previous_end}) and "
                f"{section_id} ({start_s}..{end_s})."
            )

        previous_id = section_id
        previous_start = start_s
        previous_end = end_s


def load_timeline(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="Timeline")
    _validate_timeline_schema(payload)
    return normalize_timeline(payload)
