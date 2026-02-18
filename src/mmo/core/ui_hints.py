"""Deterministic extraction and linting for config-schema x_mmo_ui hints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.core.schema_registry import build_schema_registry, load_json_schema
from mmo.resources import schemas_dir

UI_HINTS_SCHEMA_VERSION = "0.1.0"


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _json_pointer_join(pointer: str, token: str) -> str:
    escaped = _escape_json_pointer_token(token)
    if pointer:
        return f"{pointer}/{escaped}"
    return f"/{escaped}"


def _hint_sort_key(row: dict[str, Any]) -> tuple[str]:
    return (_coerce_str(row.get("json_pointer")).strip(),)


def _collect_hint_rows(
    value: Any,
    *,
    pointer: str,
    rows: list[dict[str, Any]],
) -> None:
    if isinstance(value, dict):
        if "x_mmo_ui" in value:
            rows.append(
                {
                    "json_pointer": _json_pointer_join(pointer, "x_mmo_ui"),
                    "hint": _json_clone(value.get("x_mmo_ui")),
                }
            )
        for key in sorted(value.keys()):
            if key == "x_mmo_ui":
                continue
            child_pointer = _json_pointer_join(pointer, key)
            _collect_hint_rows(
                value.get(key),
                pointer=child_pointer,
                rows=rows,
            )
        return

    if isinstance(value, list):
        for index, nested in enumerate(value):
            child_pointer = _json_pointer_join(pointer, str(index))
            _collect_hint_rows(
                nested,
                pointer=child_pointer,
                rows=rows,
            )


def extract_ui_hints_rows(config_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all x_mmo_ui blocks from a config schema in deterministic order."""
    if not isinstance(config_schema, dict):
        raise ValueError("Config schema JSON must be an object.")
    rows: list[dict[str, Any]] = []
    _collect_hint_rows(config_schema, pointer="", rows=rows)
    return sorted(rows, key=_hint_sort_key)


def _build_ui_hints_validator() -> Any:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to lint UI hints.")
    schema_path = schemas_dir() / "ui_hints.schema.json"
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _relative_error_path(path: Iterable[Any]) -> str:
    parts = [_escape_json_pointer_token(str(item)) for item in path]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _lint_error_sort_key(error: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(error.get("json_pointer")).strip(),
        _coerce_str(error.get("path")).strip(),
        _coerce_str(error.get("message")).strip(),
    )


def _lint_hint_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    validator = _build_ui_hints_validator()
    errors: list[dict[str, str]] = []
    for row in rows:
        pointer = _coerce_str(row.get("json_pointer")).strip()
        hint_value = row.get("hint")
        for err in validator.iter_errors(hint_value):
            errors.append(
                {
                    "json_pointer": pointer,
                    "path": _relative_error_path(err.path),
                    "message": err.message,
                }
            )
    return sorted(errors, key=_lint_error_sort_key)


def build_ui_hints_extract_payload(
    *,
    config_schema: dict[str, Any],
    schema_path: Path,
) -> dict[str, Any]:
    rows = extract_ui_hints_rows(config_schema)
    return {
        "schema_version": UI_HINTS_SCHEMA_VERSION,
        "schema_path": _path_to_posix(schema_path),
        "hint_count": len(rows),
        "hints": rows,
    }


def build_ui_hints_lint_payload(
    *,
    config_schema: dict[str, Any],
    schema_path: Path,
) -> dict[str, Any]:
    rows = extract_ui_hints_rows(config_schema)
    errors = _lint_hint_rows(rows)
    return {
        "schema_version": UI_HINTS_SCHEMA_VERSION,
        "schema_path": _path_to_posix(schema_path),
        "hint_count": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "ok": len(errors) == 0,
    }


def ui_hints_has_errors(lint_payload: dict[str, Any]) -> bool:
    raw_errors = lint_payload.get("errors")
    return isinstance(raw_errors, list) and len(raw_errors) > 0


__all__ = [
    "UI_HINTS_SCHEMA_VERSION",
    "extract_ui_hints_rows",
    "build_ui_hints_extract_payload",
    "build_ui_hints_lint_payload",
    "ui_hints_has_errors",
]
