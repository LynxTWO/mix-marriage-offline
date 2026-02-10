from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


def load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "jsonschema referencing support is unavailable; cannot validate schema refs."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def collect_schema_refs(schema: Any) -> list[str]:
    refs: set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.strip():
                refs.add(ref.strip())
            for nested in value.values():
                _walk(nested)
            return
        if isinstance(value, list):
            for nested in value:
                _walk(nested)

    _walk(schema)
    return sorted(refs)


def unresolved_schema_refs(
    schema: dict[str, Any],
    *,
    registry: Any,
    default_base_uri: str,
) -> list[str]:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to probe schema references.")

    base_uri = default_base_uri
    schema_id = schema.get("$id")
    if isinstance(schema_id, str) and schema_id:
        base_uri = schema_id

    unresolved: list[str] = []
    for ref in collect_schema_refs(schema):
        probe_schema = json.loads(json.dumps(schema))
        if base_uri and not isinstance(probe_schema.get("$id"), str):
            probe_schema["$id"] = base_uri
        all_of = probe_schema.get("allOf")
        if isinstance(all_of, list):
            probe_schema["allOf"] = [*all_of, {"$ref": ref}]
        else:
            probe_schema["allOf"] = [{"$ref": ref}]
        validator = jsonschema.Draft202012Validator(probe_schema, registry=registry)
        try:
            list(validator.iter_errors(None))
        except Exception as exc:  # pragma: no cover - class differs by jsonschema version
            unresolved.append(f"{ref}: {exc}")
    return unresolved
