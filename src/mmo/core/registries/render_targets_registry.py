"""Render targets registry loader for ontology/render_targets.yaml."""

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

from mmo.core.registries.layout_registry import load_layout_registry
from mmo.resources import data_root, ontology_dir, schemas_dir


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "render_targets.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _validate_payload_against_schema(payload: dict[str, Any], *, schema_path: Path) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate render targets.")
    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return
    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    raise ValueError("Render targets registry schema validation failed:\n" + "\n".join(lines))


class RenderTargetsRegistry:
    """Immutable, deterministic render-target registry."""

    def __init__(
        self,
        *,
        schema_version: str,
        targets_by_id: dict[str, dict[str, Any]],
        targets_by_layout: dict[str, list[str]],
    ) -> None:
        self._schema_version = schema_version
        self._targets_by_id = targets_by_id
        self._targets_by_layout = targets_by_layout

    @property
    def schema_version(self) -> str:
        return self._schema_version

    def list_target_ids(self) -> list[str]:
        return list(self._targets_by_id.keys())

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self._schema_version,
            "targets": [
                dict(self._targets_by_id[target_id])
                for target_id in self.list_target_ids()
            ],
        }

    def get_target(self, target_id: str) -> dict[str, Any]:
        normalized = target_id.strip() if isinstance(target_id, str) else ""
        if not normalized:
            raise ValueError("target_id must be a non-empty string.")
        payload = self._targets_by_id.get(normalized)
        if payload is not None:
            return dict(payload)
        known_ids = self.list_target_ids()
        if known_ids:
            raise ValueError(
                f"Unknown target_id: {normalized}. Known target_ids: {', '.join(known_ids)}"
            )
        raise ValueError(
            f"Unknown target_id: {normalized}. No render targets are available."
        )

    def find_targets_for_layout(self, layout_id: str) -> list[dict[str, Any]]:
        normalized_layout_id = layout_id.strip() if isinstance(layout_id, str) else ""
        if not normalized_layout_id:
            raise ValueError("layout_id must be a non-empty string.")
        return [
            dict(self._targets_by_id[target_id])
            for target_id in self._targets_by_layout.get(normalized_layout_id, [])
        ]


def load_render_targets_registry(path: Path | None = None) -> RenderTargetsRegistry:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load render targets.")

    resolved_path = _resolve_registry_path(path)
    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(
            f"Failed to read render targets YAML from {resolved_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Render targets YAML is not valid: {resolved_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Render targets YAML root must be a mapping: {resolved_path}")

    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "render_targets.schema.json",
    )

    targets_raw = payload.get("targets")
    if not isinstance(targets_raw, list):
        raise ValueError(f"Render targets registry missing 'targets' list: {resolved_path}")

    target_ids = [
        item.get("target_id")
        for item in targets_raw
        if isinstance(item, dict)
    ]
    if any(not isinstance(target_id, str) for target_id in target_ids):
        raise ValueError("Render targets registry has non-string target_id values.")

    sorted_target_ids = sorted(target_ids)
    if target_ids != sorted_target_ids:
        raise ValueError(f"Render targets must be sorted by target_id: {resolved_path}")
    if len(sorted_target_ids) != len(set(sorted_target_ids)):
        raise ValueError(f"Render targets must be unique by target_id: {resolved_path}")

    layout_registry = load_layout_registry(ontology_dir() / "layouts.yaml")
    known_layouts = set(layout_registry.list_layout_ids())

    targets_by_id: dict[str, dict[str, Any]] = {}
    targets_by_layout: dict[str, list[str]] = {}
    for row in targets_raw:
        if not isinstance(row, dict):
            continue

        target_id = row["target_id"]
        layout_id = row["layout_id"]
        if layout_id not in known_layouts:
            known_ids = layout_registry.list_layout_ids()
            raise ValueError(
                f"Unknown layout_id for target {target_id}: {layout_id}. "
                f"Known layout_ids: {', '.join(known_ids)}"
            )

        channel_order: list[str]
        if isinstance(row.get("channel_order"), list):
            channel_order = [str(item) for item in row["channel_order"]]
        else:
            channel_order_layout_id = row["channel_order_layout_id"]
            if channel_order_layout_id not in known_layouts:
                known_ids = layout_registry.list_layout_ids()
                raise ValueError(
                    "Unknown channel_order_layout_id for target "
                    f"{target_id}: {channel_order_layout_id}. "
                    f"Known layout_ids: {', '.join(known_ids)}"
                )
            channel_order = list(
                layout_registry.get_layout(channel_order_layout_id).get("channel_order", [])
            )

        if not channel_order:
            raise ValueError(f"Target {target_id} resolved an empty channel_order.")

        notes = row.get("notes")
        normalized_notes = (
            [item for item in notes if isinstance(item, str) and item.strip()]
            if isinstance(notes, list)
            else []
        )

        normalized_row: dict[str, Any] = {
            "target_id": target_id,
            "layout_id": layout_id,
            "container": row["container"],
            "channel_order": list(channel_order),
            "filename_template": row["filename_template"],
        }
        if "channel_order_layout_id" in row:
            normalized_row["channel_order_layout_id"] = row["channel_order_layout_id"]
        if normalized_notes:
            normalized_row["notes"] = normalized_notes

        targets_by_id[target_id] = normalized_row
        targets_by_layout.setdefault(layout_id, []).append(target_id)

    for layout_id in sorted(targets_by_layout.keys()):
        targets_by_layout[layout_id] = sorted(targets_by_layout[layout_id])

    schema_version = payload.get("schema_version")
    normalized_schema_version = schema_version if isinstance(schema_version, str) else ""

    return RenderTargetsRegistry(
        schema_version=normalized_schema_version,
        targets_by_id=targets_by_id,
        targets_by_layout=targets_by_layout,
    )
