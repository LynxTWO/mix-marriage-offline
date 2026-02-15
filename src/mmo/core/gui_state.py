from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

GUI_STATE_SCHEMA_VERSION = "0.1.0"
_GUI_STATE_TABS: tuple[str, ...] = (
    "dashboard",
    "scene",
    "targets",
    "run",
    "results",
)


def _gui_state_schema_path() -> Path:
    from mmo.resources import schemas_dir
    return schemas_dir() / "gui_state.schema.json"


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


def _validate_payload_against_schema(payload: dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate GUI state files.")

    from mmo.core.schema_registry import build_schema_registry, load_json_schema  # noqa: WPS433

    schema_path = _gui_state_schema_path()
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"GUI state schema validation failed:\n{details}")


def _selected_string_list(payload: dict[str, Any], *, key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _available_target_ids() -> list[str]:
    from mmo.core.render_targets import list_render_targets  # noqa: WPS433

    return sorted(
        target_id
        for target in list_render_targets()
        for target_id in [target.get("target_id")]
        if isinstance(target_id, str) and target_id
    )


def _available_template_ids() -> list[str]:
    from mmo.core.scene_templates import list_scene_templates  # noqa: WPS433

    return sorted(
        template_id
        for template in list_scene_templates()
        for template_id in [template.get("template_id")]
        if isinstance(template_id, str) and template_id
    )


def _validate_selected_ids(
    selected_ids: list[str],
    *,
    available_ids: list[str],
    field_name: str,
    id_label: str,
) -> None:
    available_set = set(available_ids)
    unknown_ids = sorted({item for item in selected_ids if item not in available_set})
    if not unknown_ids:
        return

    unknown_label = ", ".join(unknown_ids)
    if available_ids:
        available_label = ", ".join(available_ids)
        raise ValueError(
            f"Unknown {field_name}: {unknown_label}. Available {id_label}: {available_label}"
        )
    raise ValueError(
        f"Unknown {field_name}: {unknown_label}. No {id_label} are available."
    )


def _validate_selected_tab(payload: dict[str, Any]) -> None:
    selected_tab = payload.get("selected_tab")
    if not isinstance(selected_tab, str):
        return
    if selected_tab in _GUI_STATE_TABS:
        return

    allowed = ", ".join(_GUI_STATE_TABS)
    raise ValueError(
        f"Unknown selected_tab: {selected_tab}. Allowed tabs: {allowed}"
    )


def validate_gui_state(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="GUI state")
    _validate_selected_tab(payload)
    _validate_payload_against_schema(payload)
    _validate_selected_ids(
        _selected_string_list(payload, key="selected_targets"),
        available_ids=_available_target_ids(),
        field_name="selected_targets",
        id_label="target IDs",
    )
    _validate_selected_ids(
        _selected_string_list(payload, key="selected_template_ids"),
        available_ids=_available_template_ids(),
        field_name="selected_template_ids",
        id_label="template IDs",
    )
    return payload


def default_gui_state() -> dict[str, Any]:
    return {
        "schema_version": GUI_STATE_SCHEMA_VERSION,
        "last_opened_project_path": "",
        "selected_targets": [],
        "selected_preset_id": None,
        "selected_template_ids": [],
        "nerd_mode": False,
        "selected_tab": "dashboard",
    }
