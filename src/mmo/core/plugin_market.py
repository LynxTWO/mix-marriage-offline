from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mmo.core.plugin_loader import load_registered_plugins
from mmo.resources import data_root, default_cache_dir, ontology_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

PLUGIN_MARKET_SCHEMA_VERSION = "0.1.0"
PLUGIN_MARKET_INDEX_BASENAME = "plugin_index.yaml"
PLUGIN_MARKET_CACHE_BASENAME = "plugin_index.snapshot.json"
_DEFAULT_MARKET_ID = "MARKET.PLUGIN.OFFLINE.V0"

_PLUGIN_ID_PATTERN = re.compile(r"^[A-Z0-9_.]+$")
_PLUGIN_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _resolve_index_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / PLUGIN_MARKET_INDEX_BASENAME
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load plugin marketplace indexes.")
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


def _normalize_text_field(
    value: Any,
    *,
    field_name: str,
    plugin_id: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string for {plugin_id}.")
    return value.strip()


def _normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            tag.strip()
            for tag in value
            if isinstance(tag, str) and tag.strip()
        }
    )


def _normalize_manifest_path(value: Any, *, plugin_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest_path must be a non-empty string for {plugin_id}.")
    normalized = value.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError(f"manifest_path must be relative for {plugin_id}.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"manifest_path cannot escape root for {plugin_id}.")
    return candidate.as_posix()


def _normalize_index_entries(
    rows: Any,
    *,
    source_path: Path,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(
            f"Plugin marketplace index entries must be a list: {source_path.as_posix()}"
        )

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError(
                f"Plugin marketplace entries must be objects: {source_path.as_posix()}"
            )

        plugin_id = _normalize_text_field(
            raw_row.get("plugin_id"),
            field_name="plugin_id",
            plugin_id="<unknown>",
        )
        if not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise ValueError(f"Invalid plugin_id format in marketplace index: {plugin_id}")
        if plugin_id in seen_ids:
            raise ValueError(f"Duplicate plugin_id in marketplace index: {plugin_id}")
        seen_ids.add(plugin_id)

        plugin_type = _normalize_text_field(
            raw_row.get("plugin_type"),
            field_name="plugin_type",
            plugin_id=plugin_id,
        )
        if not _PLUGIN_TYPE_PATTERN.fullmatch(plugin_type):
            raise ValueError(
                f"Invalid plugin_type format for {plugin_id}: {plugin_type}"
            )

        entry: dict[str, Any] = {
            "plugin_id": plugin_id,
            "plugin_type": plugin_type,
            "name": _normalize_text_field(
                raw_row.get("name"),
                field_name="name",
                plugin_id=plugin_id,
            ),
            "summary": _normalize_text_field(
                raw_row.get("summary"),
                field_name="summary",
                plugin_id=plugin_id,
            ),
            "version": _normalize_text_field(
                raw_row.get("version"),
                field_name="version",
                plugin_id=plugin_id,
            ),
            "tags": _normalize_tags(raw_row.get("tags")),
            "manifest_path": _normalize_manifest_path(
                raw_row.get("manifest_path"),
                plugin_id=plugin_id,
            ),
        }

        homepage = raw_row.get("homepage")
        if homepage is not None:
            entry["homepage"] = _normalize_text_field(
                homepage,
                field_name="homepage",
                plugin_id=plugin_id,
            )

        entries.append(entry)

    entries.sort(
        key=lambda row: (
            str(row.get("plugin_id", "")),
            str(row.get("plugin_type", "")),
            str(row.get("version", "")),
        )
    )
    return entries


def load_plugin_market_index(index_path: Path | None = None) -> dict[str, Any]:
    resolved_index_path = _resolve_index_path(index_path)
    payload = _load_yaml_object(
        resolved_index_path,
        label="Plugin marketplace index",
    )

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValueError(
            "Plugin marketplace index schema_version must be a non-empty string."
        )

    market_id = payload.get("market_id")
    if not isinstance(market_id, str) or not market_id.strip():
        market_id = _DEFAULT_MARKET_ID

    entries = _normalize_index_entries(
        payload.get("entries"),
        source_path=resolved_index_path,
    )
    return {
        "schema_version": schema_version.strip(),
        "market_id": market_id.strip(),
        "source_path": resolved_index_path.resolve().as_posix(),
        "entries": entries,
    }


def _discover_installed_plugin_ids(
    *,
    plugins_dir: Path,
    plugin_dir: Path | None,
) -> tuple[set[str], str | None]:
    try:
        installed = load_registered_plugins(
            plugins_dir=plugins_dir,
            plugin_dir=plugin_dir,
        )
    except (RuntimeError, ValueError, AttributeError, OSError) as exc:
        return (set(), str(exc))

    installed_ids = {
        entry.plugin_id
        for entry in installed
        if isinstance(entry.plugin_id, str) and entry.plugin_id
    }
    return (installed_ids, None)


def build_plugin_market_list_payload(
    *,
    plugins_dir: Path = Path("plugins"),
    plugin_dir: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    market_index = load_plugin_market_index(index_path=index_path)
    resolved_plugins_dir = plugins_dir.expanduser().resolve()
    resolved_plugin_dir = (
        plugin_dir.expanduser().resolve()
        if plugin_dir is not None
        else None
    )
    installed_ids, scan_error = _discover_installed_plugin_ids(
        plugins_dir=resolved_plugins_dir,
        plugin_dir=resolved_plugin_dir,
    )

    entries: list[dict[str, Any]] = []
    for entry in market_index["entries"]:
        plugin_id = str(entry.get("plugin_id", ""))
        is_installed = plugin_id in installed_ids
        row = dict(entry)
        row["install_state"] = "installed" if is_installed else "available"
        row["installed"] = is_installed
        entries.append(row)

    payload: dict[str, Any] = {
        "schema_version": PLUGIN_MARKET_SCHEMA_VERSION,
        "market_id": market_index["market_id"],
        "index_schema_version": market_index["schema_version"],
        "index_path": market_index["source_path"],
        "plugins_dir": resolved_plugins_dir.as_posix(),
        "plugin_dir": resolved_plugin_dir.as_posix() if resolved_plugin_dir is not None else None,
        "entry_count": len(entries),
        "installed_count": sum(1 for entry in entries if entry["installed"] is True),
        "entries": entries,
    }
    if scan_error:
        payload["installed_scan_error"] = scan_error
    return payload


def default_plugin_market_snapshot_path(cache_dir: Path | None = None) -> Path:
    root = cache_dir.expanduser().resolve() if cache_dir is not None else default_cache_dir()
    return root / "plugin_market" / PLUGIN_MARKET_CACHE_BASENAME


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def update_plugin_market_snapshot(
    *,
    out_path: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    market_index = load_plugin_market_index(index_path=index_path)
    resolved_out_path = (
        out_path.expanduser().resolve()
        if out_path is not None
        else default_plugin_market_snapshot_path()
    )

    snapshot_payload = {
        "schema_version": PLUGIN_MARKET_SCHEMA_VERSION,
        "market_id": market_index["market_id"],
        "index_schema_version": market_index["schema_version"],
        "entries": market_index["entries"],
    }
    serialized = json.dumps(snapshot_payload, indent=2, sort_keys=True) + "\n"
    resolved_out_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_out_path.write_text(serialized, encoding="utf-8")

    return {
        "schema_version": PLUGIN_MARKET_SCHEMA_VERSION,
        "market_id": market_index["market_id"],
        "index_path": market_index["source_path"],
        "out_path": resolved_out_path.as_posix(),
        "entry_count": len(market_index["entries"]),
        "sha256": _sha256_text(serialized),
    }
