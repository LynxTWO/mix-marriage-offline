from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mmo.core.pipeline import load_plugins

_CONFIG_SCHEMA_JSON_POINTER = "/config_schema"


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


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _clone_json_object(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


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


def build_plugins_config_schema_index(
    *,
    plugins_dir: Path,
    include_schema: bool = False,
) -> dict[str, Any]:
    resolved_plugins_dir = _validate_plugins_dir(plugins_dir)
    rows: list[dict[str, Any]] = []
    for plugin in load_plugins(resolved_plugins_dir):
        rows.append(
            {
                "plugin_id": plugin.plugin_id,
                "plugin_type": plugin.plugin_type,
                "version": plugin.version or "",
                "config_schema": _config_schema_payload(
                    manifest_path=plugin.manifest_path,
                    manifest=plugin.manifest,
                    include_schema=include_schema,
                ),
            }
        )

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
    plugin_id: str,
) -> dict[str, Any]:
    resolved_plugins_dir = _validate_plugins_dir(plugins_dir)
    normalized_plugin_id = plugin_id.strip() if isinstance(plugin_id, str) else ""
    if not normalized_plugin_id:
        raise ValueError("plugin_id must be a non-empty string.")

    plugins = load_plugins(resolved_plugins_dir)
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
    return {
        "plugins_dir": _path_to_posix(resolved_plugins_dir),
        "plugin": plugin_payload,
        "config_schema": _config_schema_payload(
            manifest_path=target_plugin.manifest_path,
            manifest=target_plugin.manifest,
            include_schema=True,
        ),
    }
