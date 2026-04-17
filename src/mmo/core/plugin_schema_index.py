from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.core.pipeline import load_plugins
from mmo.resources import schemas_dir

_CONFIG_SCHEMA_JSON_POINTER = "/config_schema"
_UI_LAYOUT_MANIFEST_FIELD = "ui_layout"
_DEFAULT_SNAPSHOT_VIEWPORT_WIDTH_PX = 1280
_DEFAULT_SNAPSHOT_VIEWPORT_HEIGHT_PX = 720
_DEFAULT_SNAPSHOT_SCALE = 1.0


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _validate_plugins_dir(plugins_dir: Path) -> Path:
    resolved_plugins_dir = plugins_dir.resolve()
    if not resolved_plugins_dir.exists():
        raise ValueError(f"Plugins directory does not exist: {resolved_plugins_dir.as_posix()}")
    if not resolved_plugins_dir.is_dir():
        raise ValueError(f"Plugins path is not a directory: {resolved_plugins_dir.as_posix()}")
    return resolved_plugins_dir


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _canonical_json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _clone_json_object(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _validate_json_payload(
    payload: dict[str, Any],
    *,
    schema_basename: str,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate plugin UI layout payloads.")

    from mmo.core.schema_registry import (  # noqa: WPS433
        build_draft202012_validator,
        build_schema_registry,
        load_json_schema,
    )

    schema_path = schemas_dir() / schema_basename
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    validator = build_draft202012_validator(
        schema,
        registry=registry,
        schemas_dir=schema_path.parent,
    )
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _resolve_manifest_relative_file(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    field_name: str,
) -> Path | None:
    raw_value = manifest.get(field_name)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError(
            f"Manifest field '{field_name}' must be a string: {manifest_path.as_posix()}"
        )
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError(
            f"Manifest field '{field_name}' must be a non-empty relative path: {manifest_path.as_posix()}"
        )
    candidate_rel = Path(normalized)
    if candidate_rel.is_absolute():
        raise ValueError(
            f"Manifest field '{field_name}' must be a relative path: {manifest_path.as_posix()}"
        )

    plugin_dir = manifest_path.resolve().parent
    candidate = (plugin_dir / candidate_rel).resolve()
    # UI metadata files stay inside the plugin directory so one manifest cannot
    # point the browser tooling at arbitrary local files.
    try:
        candidate.relative_to(plugin_dir)
    except ValueError as exc:
        raise ValueError(
            (
                f"Manifest field '{field_name}' must resolve inside the plugin directory: "
                f"{manifest_path.as_posix()}"
            )
        ) from exc
    if not candidate.exists():
        raise ValueError(
            (
                f"Manifest field '{field_name}' references a missing file: "
                f"{candidate.as_posix()}"
            )
        )
    if not candidate.is_file():
        raise ValueError(
            (
                f"Manifest field '{field_name}' must reference a file: "
                f"{candidate.as_posix()}"
            )
        )
    return candidate


def _config_schema_payload(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    include_schema: bool,
) -> dict[str, Any]:
    resolved_manifest_path = manifest_path.resolve()
    manifest_sha256 = _sha256_file(resolved_manifest_path)
    raw_schema = manifest.get("config_schema")
    schema_present = isinstance(raw_schema, dict)
    schema_sha256 = _canonical_json_sha256(raw_schema) if schema_present else None

    payload: dict[str, Any] = {
        "present": schema_present,
        # The pointer receipt lets UI tooling prove which manifest bytes owned
        # the schema instead of treating a copied schema blob as authority.
        "pointer": {
            "manifest_path": resolved_manifest_path.as_posix(),
            "manifest_sha256": manifest_sha256,
            "json_pointer": _CONFIG_SCHEMA_JSON_POINTER,
        },
        "sha256": schema_sha256,
    }
    if include_schema:
        payload["schema"] = _clone_json_object(raw_schema) if schema_present else None
    return payload


def _ui_hints_payload(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    from mmo.core.ui_hints import extract_ui_hints_rows  # noqa: WPS433

    resolved_manifest_path = manifest_path.resolve()
    manifest_sha256 = _sha256_file(resolved_manifest_path)
    raw_schema = manifest.get("config_schema")
    schema_present = isinstance(raw_schema, dict)
    # UI hints are derived from config_schema so the schema stays authoritative
    # and hint payloads change only when the manifest changes.
    hint_rows = extract_ui_hints_rows(raw_schema) if schema_present else []
    hints_sha256 = _canonical_json_sha256(hint_rows) if schema_present else None
    return {
        "present": schema_present,
        "pointer": {
            "manifest_path": resolved_manifest_path.as_posix(),
            "manifest_sha256": manifest_sha256,
            "json_pointer": _CONFIG_SCHEMA_JSON_POINTER,
        },
        "sha256": hints_sha256,
        "hint_count": len(hint_rows),
        "hints": hint_rows,
    }


def _ui_layout_payload(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], Path | None]:
    layout_path = _resolve_manifest_relative_file(
        manifest_path=manifest_path,
        manifest=manifest,
        field_name=_UI_LAYOUT_MANIFEST_FIELD,
    )
    if layout_path is None:
        return {
            "present": False,
            "path": None,
            "sha256": None,
        }, None
    return {
        "present": True,
        "path": _path_to_posix(layout_path),
        "sha256": _sha256_file(layout_path),
    }, layout_path


def _ui_layout_snapshot_payload(
    *,
    layout_path: Path,
) -> dict[str, Any]:
    from mmo.core.ui_layout import build_ui_layout_snapshot  # noqa: WPS433

    layout_payload = _load_json_object(layout_path, label="UI layout")
    _validate_json_payload(
        layout_payload,
        schema_basename="ui_layout.schema.json",
        payload_name="UI layout",
    )
    snapshot_payload = build_ui_layout_snapshot(
        layout_payload,
        layout_path=layout_path,
        viewport_width_px=_DEFAULT_SNAPSHOT_VIEWPORT_WIDTH_PX,
        viewport_height_px=_DEFAULT_SNAPSHOT_VIEWPORT_HEIGHT_PX,
        scale=_DEFAULT_SNAPSHOT_SCALE,
    )
    _validate_json_payload(
        snapshot_payload,
        schema_basename="ui_layout_snapshot.schema.json",
        payload_name="UI layout snapshot",
    )
    violations = snapshot_payload.get("violations")
    violations_count = len(violations) if isinstance(violations, list) else 0
    return {
        "present": True,
        "path": _path_to_posix(layout_path),
        "sha256": _canonical_json_sha256(snapshot_payload),
        "violations_count": violations_count,
    }


def build_plugins_config_schema_index(
    *,
    plugins_dir: Path,
    include_schema: bool = False,
    include_ui_layout: bool = False,
    include_ui_layout_snapshot: bool = False,
    include_ui_hints: bool = False,
) -> dict[str, Any]:
    resolved_plugins_dir = _validate_plugins_dir(plugins_dir)
    # Snapshot callers that ask for UI layout snapshots also need the base
    # layout payload so they can trace the snapshot back to its source file.
    include_ui_layout_effective = include_ui_layout or include_ui_layout_snapshot
    rows: list[dict[str, Any]] = []
    for plugin in load_plugins(resolved_plugins_dir):
        row: dict[str, Any] = {
            "plugin_id": plugin.plugin_id,
            "plugin_type": plugin.plugin_type,
            "version": plugin.version or "",
            "config_schema": _config_schema_payload(
                manifest_path=plugin.manifest_path,
                manifest=plugin.manifest,
                include_schema=include_schema,
            ),
        }
        ui_layout_path: Path | None = None
        if include_ui_layout_effective:
            ui_layout, ui_layout_path = _ui_layout_payload(
                manifest_path=plugin.manifest_path,
                manifest=plugin.manifest,
            )
            row["ui_layout"] = ui_layout
        if include_ui_layout_snapshot and ui_layout_path is not None:
            row["ui_layout_snapshot"] = _ui_layout_snapshot_payload(
                layout_path=ui_layout_path,
            )
        if include_ui_hints:
            row["ui_hints"] = _ui_hints_payload(
                manifest_path=plugin.manifest_path,
                manifest=plugin.manifest,
            )
        rows.append(row)

    # Keep row order stable for CLI snapshots, fixtures, and GUI diff views.
    rows.sort(
        key=lambda row: (
            str(row.get("plugin_id", "")),
            str(row.get("plugin_type", "")),
            str(row.get("version", "")),
        )
    )
    return {
        "plugins_dir": _path_to_posix(resolved_plugins_dir),
        "entries": rows,
    }


def build_plugin_show_payload(
    *,
    plugins_dir: Path,
    plugin_id: str | None = None,
    include_ui_layout_snapshot: bool = False,
    include_ui_hints: bool = False,
) -> dict[str, Any]:
    resolved_plugins_dir = _validate_plugins_dir(plugins_dir)
    plugins = load_plugins(resolved_plugins_dir)
    normalized_plugin_id = plugin_id.strip() if isinstance(plugin_id, str) else ""
    target_plugin: Any | None = None
    if normalized_plugin_id:
        target_plugin = next(
            (item for item in plugins if item.plugin_id == normalized_plugin_id),
            None,
        )
        if target_plugin is None:
            available_plugin_ids = ", ".join(
                item.plugin_id
                for item in plugins
                if isinstance(item.plugin_id, str) and item.plugin_id
            )
            if available_plugin_ids:
                raise ValueError(
                    f"Unknown plugin_id: {normalized_plugin_id}. "
                    f"Available plugins: {available_plugin_ids}"
                )
            raise ValueError(
                f"Unknown plugin_id: {normalized_plugin_id}. No plugins were discovered."
            )
    else:
        def _is_examples_manifest_path(manifest_path: Path) -> bool:
            try:
                relative_path = manifest_path.resolve().relative_to(resolved_plugins_dir)
            except ValueError:
                return False
            return bool(relative_path.parts) and relative_path.parts[0].lower() == "examples"

        plugins_with_ui_metadata = [
            item
            for item in plugins
            if isinstance(item.manifest, dict)
            and isinstance(item.manifest.get("config_schema"), dict)
            and isinstance(item.manifest.get("ui_layout"), str)
            and item.manifest.get("ui_layout", "").strip()
        ]
        if plugins_with_ui_metadata:
            # When callers omit plugin_id, prefer an example plugin with real UI
            # metadata so docs and smoke flows render a representative payload.
            plugins_with_ui_metadata.sort(
                key=lambda item: (
                    0 if _is_examples_manifest_path(item.manifest_path) else 1,
                    str(item.plugin_id),
                )
            )
            target_plugin = plugins_with_ui_metadata[0]
        elif plugins:
            target_plugin = plugins[0]
        else:
            raise ValueError("No plugins were discovered.")

    plugin_capabilities: dict[str, Any] = {}
    if target_plugin.capabilities is not None:
        plugin_capabilities = target_plugin.capabilities.to_dict()

    plugin_payload: dict[str, Any] = {
        "plugin_id": target_plugin.plugin_id,
        "plugin_type": target_plugin.plugin_type,
        "version": target_plugin.version or "",
        "manifest_path": _path_to_posix(target_plugin.manifest_path),
        "manifest_sha256": _sha256_file(target_plugin.manifest_path.resolve()),
        "capabilities": plugin_capabilities,
        "manifest": _clone_json_object(target_plugin.manifest),
    }
    ui_layout_payload, ui_layout_path = _ui_layout_payload(
        manifest_path=target_plugin.manifest_path,
        manifest=target_plugin.manifest,
    )
    payload: dict[str, Any] = {
        "plugins_dir": _path_to_posix(resolved_plugins_dir),
        "plugin": plugin_payload,
        "config_schema": _config_schema_payload(
            manifest_path=target_plugin.manifest_path,
            manifest=target_plugin.manifest,
            include_schema=True,
        ),
        "ui_layout": ui_layout_payload,
    }
    if include_ui_layout_snapshot and ui_layout_path is not None:
        payload["ui_layout_snapshot"] = _ui_layout_snapshot_payload(
            layout_path=ui_layout_path,
        )
    if include_ui_hints:
        payload["ui_hints"] = _ui_hints_payload(
            manifest_path=target_plugin.manifest_path,
            manifest=target_plugin.manifest,
        )
    return payload
