from __future__ import annotations

import json
from collections.abc import Mapping
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
    except ImportError:  # pragma: no cover - optional dependency
        # Fallback for environments that ship jsonschema without `referencing`.
        # Callers can still validate local $ref values via RefResolver+store.
        return build_schema_store(schemas_dir)

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        # Register both the file URI and the schema's own $id so packaged,
        # repo-local, and copied validation callers resolve the same schema.
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def build_schema_store(schemas_dir: Path) -> dict[str, dict[str, Any]]:
    store: dict[str, dict[str, Any]] = {}
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = load_json_schema(schema_file)
        store[schema_file.resolve().as_uri()] = schema
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            store[schema_id] = schema
    return store


def _store_from_registry(registry: Any) -> dict[str, dict[str, Any]]:
    if isinstance(registry, Mapping):
        items = registry.items()
    else:
        resources = getattr(registry, "_resources", None)
        if not isinstance(resources, Mapping):
            return {}
        items = resources.items()

    store: dict[str, dict[str, Any]] = {}
    for uri, resource in items:
        if not isinstance(uri, str):
            continue
        contents: Any
        if isinstance(resource, dict):
            contents = resource
        else:
            contents = getattr(resource, "contents", None)
        if not isinstance(contents, dict):
            continue
        store[uri] = contents
        schema_id = contents.get("$id")
        if isinstance(schema_id, str) and schema_id:
            store[schema_id] = contents
    return store


def build_draft202012_validator(
    schema: dict[str, Any],
    *,
    registry: Any | None = None,
    schemas_dir: Path | None = None,
) -> Any:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate schemas.")

    if registry is not None:
        try:
            return jsonschema.Draft202012Validator(schema, registry=registry)
        except TypeError:
            # jsonschema<4.22 does not accept a registry kwarg.
            pass

    store: dict[str, dict[str, Any]] = {}
    # Older jsonschema builds still need a store or RefResolver path. Rebuild a
    # local store rather than dropping $ref support when registry support lags.
    if isinstance(schemas_dir, Path):
        try:
            store.update(build_schema_store(schemas_dir))
        except ValueError:
            pass
    if not store and registry is not None:
        store.update(_store_from_registry(registry))

    resolver_cls = getattr(jsonschema, "RefResolver", None)
    if resolver_cls is not None and store:
        resolver = resolver_cls.from_schema(schema, store=store)
        return jsonschema.Draft202012Validator(schema, resolver=resolver)

    return jsonschema.Draft202012Validator(schema)


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
        # Probe one ref at a time by grafting it into allOf. That keeps the
        # failure receipt tied to the missing reference instead of instance data.
        all_of = probe_schema.get("allOf")
        if isinstance(all_of, list):
            probe_schema["allOf"] = [*all_of, {"$ref": ref}]
        else:
            probe_schema["allOf"] = [{"$ref": ref}]
        validator = build_draft202012_validator(
            probe_schema,
            registry=registry,
        )
        try:
            list(validator.iter_errors(None))
        except Exception as exc:  # pragma: no cover - class differs by jsonschema version
            unresolved.append(f"{ref}: {exc}")
    return unresolved
