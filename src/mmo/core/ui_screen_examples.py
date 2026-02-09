from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def _build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - environment issue
        raise RuntimeError(
            "jsonschema referencing support is unavailable; cannot validate schema refs."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = _load_json_object(schema_file, label=f"Schema {schema_file.name}")
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


@lru_cache(maxsize=1)
def _ui_screen_example_validator() -> Any:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate UI screen examples.")

    schema_path = _repo_root() / "schemas" / "ui_screen_example.schema.json"
    schema = _load_json_object(schema_path, label="UI screen example schema")
    registry = _build_schema_registry(schema_path.parent)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def load_ui_screen_example(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="UI screen example")

    validator = _ui_screen_example_validator()
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: list(err.absolute_path),
    )
    if errors:
        lines: list[str] = []
        for err in errors:
            error_path = ".".join(str(item) for item in err.absolute_path) or "$"
            lines.append(f"- {error_path}: {err.message}")
        details = "\n".join(lines)
        raise ValueError(f"UI screen example schema validation failed ({path}):\n{details}")

    return payload


def load_ui_screen_examples(dir: Path) -> list[dict[str, Any]]:
    if not dir.exists():
        raise ValueError(f"UI examples directory does not exist: {dir}")
    if not dir.is_dir():
        raise ValueError(f"UI examples path is not a directory: {dir}")

    payloads: list[dict[str, Any]] = []
    for path in sorted(dir.glob("*.json"), key=lambda candidate: candidate.name):
        payloads.append(load_ui_screen_example(path))
    return payloads
