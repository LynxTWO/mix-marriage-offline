from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from mmo.core.plugin_loader import default_user_plugins_dir, load_registered_plugins
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
_PREVIEW_GRADIENT_PATTERN = re.compile(r"^[a-z0-9_]+$")


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


def _normalize_preview_card(value: Any, *, plugin_id: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"preview must be an object for {plugin_id}.")

    tagline_raw = value.get("tagline")
    gradient_raw = value.get("gradient")
    chips_raw = value.get("chips")

    tagline = _normalize_text_field(
        tagline_raw,
        field_name="preview.tagline",
        plugin_id=plugin_id,
    )
    gradient = _normalize_text_field(
        gradient_raw,
        field_name="preview.gradient",
        plugin_id=plugin_id,
    ).casefold()
    if not _PREVIEW_GRADIENT_PATTERN.fullmatch(gradient):
        raise ValueError(
            f"preview.gradient has invalid format for {plugin_id}: {gradient_raw}"
        )

    chips: list[str] = []
    seen: set[str] = set()
    if isinstance(chips_raw, list):
        for raw_chip in chips_raw:
            if not isinstance(raw_chip, str):
                continue
            chip = raw_chip.strip()
            if not chip:
                continue
            dedupe_key = chip.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chips.append(chip)

    return {
        "tagline": tagline,
        "gradient": gradient,
        "chips": chips,
    }


def _normalize_relative_root(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided.")
    normalized = value.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative (got absolute path).")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field_name} cannot escape root.")
    return candidate.as_posix()


def _relative_path_without_plugins_prefix(path_text: str, *, field_name: str) -> Path:
    normalized = path_text.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative: {path_text}")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field_name} cannot escape root: {path_text}")
    parts = candidate.parts
    if len(parts) < 2 or parts[0] != "plugins":
        raise ValueError(f"{field_name} must begin with 'plugins/': {path_text}")
    return Path(*parts[1:])


def _relative_module_path_for_entrypoint(path_text: str, *, field_name: str) -> Path:
    normalized = path_text.strip().replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative: {path_text}")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field_name} cannot escape root: {path_text}")
    parts = candidate.parts
    if len(parts) >= 2 and parts[0] == "plugins":
        return Path(*parts[1:])
    if len(parts) >= 3 and parts[0] == "mmo" and parts[1] == "plugins":
        return Path(*parts[2:])
    raise ValueError(
        f"{field_name} must begin with 'plugins/' or 'mmo/plugins/': {path_text}"
    )


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
        preview = _normalize_preview_card(raw_row.get("preview"), plugin_id=plugin_id)
        if preview is not None:
            entry["preview"] = preview

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

    install_asset_root = _normalize_relative_root(
        payload.get("install_asset_root"),
        field_name="install_asset_root",
    )

    entries = _normalize_index_entries(
        payload.get("entries"),
        source_path=resolved_index_path,
    )
    result = {
        "schema_version": schema_version.strip(),
        "market_id": market_id.strip(),
        "source_path": resolved_index_path.resolve().as_posix(),
        "entries": entries,
    }
    if install_asset_root is not None:
        result["install_asset_root"] = install_asset_root
    return result


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


def _resolve_install_asset_base(market_index: dict[str, Any]) -> Path:
    install_asset_root = market_index.get("install_asset_root")
    if isinstance(install_asset_root, str) and install_asset_root.strip():
        relative_root = Path(install_asset_root.strip().replace("\\", "/"))
        if relative_root.is_absolute():
            return relative_root.resolve()
        return (data_root() / relative_root).resolve()
    return data_root().resolve()


def _resolve_install_source_path(
    *,
    market_index: dict[str, Any],
    relative_path: Path,
) -> Path:
    normalized_relative = Path(relative_path.as_posix())
    if normalized_relative.is_absolute():
        raise ValueError(f"Install source path must be relative: {relative_path}")
    if any(part == ".." for part in normalized_relative.parts):
        raise ValueError(f"Install source path cannot escape root: {relative_path}")

    # Marketplace entries stay inside trusted MMO data roots.
    # Relative-only lookup keeps the offline index from widening install scope.
    candidates: list[Path] = []
    candidates.append(_resolve_install_asset_base(market_index) / normalized_relative)

    source_path_raw = market_index.get("source_path")
    if isinstance(source_path_raw, str) and source_path_raw.strip():
        source_path = Path(source_path_raw).resolve()
        candidates.append(source_path.parent / normalized_relative)
        candidates.append(source_path.parent.parent / normalized_relative)

    candidates.append(data_root().resolve() / normalized_relative)

    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.resolve().as_posix() if candidate.exists() else candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()

    raise ValueError(
        "Install assets missing for marketplace entry: "
        f"{normalized_relative.as_posix()}"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_asset_if_changed(*, source: Path, destination: Path) -> bool:
    if destination.exists():
        try:
            # Reinstall must be idempotent.
            # Byte-for-byte equality means callers can report no state change.
            if source.read_bytes() == destination.read_bytes():
                return False
        except OSError:
            pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return True


def _entrypoint_module_path(entrypoint: str, *, plugin_id: str) -> Path:
    module_name, _, symbol = entrypoint.partition(":")
    if not module_name or not symbol:
        raise ValueError(
            f"Manifest entrypoint must be module:symbol for {plugin_id}: {entrypoint}"
        )
    module_candidate = Path(module_name.replace(".", "/") + ".py")
    return _relative_module_path_for_entrypoint(
        module_candidate.as_posix(),
        field_name="entrypoint module",
    )


def _is_entry_installable(
    *,
    market_index: dict[str, Any],
    entry: dict[str, Any],
) -> bool:
    manifest_path = entry.get("manifest_path")
    plugin_id = str(entry.get("plugin_id", "")).strip()
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        return False

    try:
        manifest_rel = _relative_path_without_plugins_prefix(
            manifest_path,
            field_name="manifest_path",
        )
        source_manifest = _resolve_install_source_path(
            market_index=market_index,
            relative_path=Path("plugins") / manifest_rel,
        )
        manifest_payload = _load_yaml_object(
            source_manifest,
            label=f"Plugin install manifest for {plugin_id or '(unknown)'}",
        )
        entrypoint = manifest_payload.get("entrypoint")
        if not isinstance(entrypoint, str) or not entrypoint.strip():
            return False
        module_rel = _entrypoint_module_path(
            entrypoint.strip(),
            plugin_id=plugin_id or "(unknown)",
        )
        _resolve_install_source_path(
            market_index=market_index,
            relative_path=Path("plugins") / module_rel,
        )
        return True
    except (RuntimeError, ValueError):
        return False


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
        row["installable"] = _is_entry_installable(
            market_index=market_index,
            entry=entry,
        )
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
    install_asset_root = market_index.get("install_asset_root")
    if isinstance(install_asset_root, str) and install_asset_root.strip():
        payload["install_asset_root"] = install_asset_root
    if scan_error:
        payload["installed_scan_error"] = scan_error
    return payload


def install_plugin_market_entry(
    *,
    plugin_id: str,
    plugins_dir: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    normalized_plugin_id = (
        plugin_id.strip()
        if isinstance(plugin_id, str)
        else ""
    )
    if not normalized_plugin_id:
        raise ValueError("plugin_id must be a non-empty string.")

    market_index = load_plugin_market_index(index_path=index_path)
    selected_entry = next(
        (
            row
            for row in market_index["entries"]
            if isinstance(row, dict)
            and row.get("plugin_id") == normalized_plugin_id
        ),
        None,
    )
    if not isinstance(selected_entry, dict):
        raise ValueError(f"Unknown plugin_id in marketplace index: {normalized_plugin_id}")

    manifest_path = selected_entry.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise ValueError(
            f"Marketplace entry has no installable manifest_path: {normalized_plugin_id}"
        )

    manifest_rel = _relative_path_without_plugins_prefix(
        manifest_path,
        field_name="manifest_path",
    )
    source_manifest = _resolve_install_source_path(
        market_index=market_index,
        relative_path=Path("plugins") / manifest_rel,
    )
    manifest_payload = _load_yaml_object(
        source_manifest,
        label=f"Plugin install manifest for {normalized_plugin_id}",
    )

    # The index is only a locator. The manifest on disk is the authority for
    # plugin identity and type before anything is copied into a writable root.
    manifest_plugin_id = manifest_payload.get("plugin_id")
    if manifest_plugin_id != normalized_plugin_id:
        raise ValueError(
            "Plugin install manifest plugin_id mismatch: "
            f"index={normalized_plugin_id}, manifest={manifest_plugin_id!r}"
        )
    manifest_plugin_type = manifest_payload.get("plugin_type")
    expected_type = selected_entry.get("plugin_type")
    if isinstance(expected_type, str) and expected_type.strip():
        if manifest_plugin_type != expected_type:
            raise ValueError(
                "Plugin install manifest plugin_type mismatch: "
                f"index={expected_type!r}, manifest={manifest_plugin_type!r}"
            )

    # Resolve the module before writing files so a broken entrypoint does not
    # leave half-installed code in the target plugin root.
    entrypoint = manifest_payload.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise ValueError(
            f"Plugin install manifest missing entrypoint: {normalized_plugin_id}"
        )
    module_rel = _entrypoint_module_path(
        entrypoint.strip(),
        plugin_id=normalized_plugin_id,
    )
    source_module = _resolve_install_source_path(
        market_index=market_index,
        relative_path=Path("plugins") / module_rel,
    )

    target_root = (
        plugins_dir.expanduser().resolve()
        if plugins_dir is not None
        else default_user_plugins_dir().expanduser().resolve()
    )
    target_manifest = target_root / manifest_rel
    target_module = target_root / module_rel

    manifest_changed = _copy_asset_if_changed(
        source=source_manifest,
        destination=target_manifest,
    )
    module_changed = _copy_asset_if_changed(
        source=source_module,
        destination=target_module,
    )

    copied_files: list[str] = []
    if manifest_changed:
        copied_files.append(target_manifest.as_posix())
    if module_changed:
        copied_files.append(target_module.as_posix())

    return {
        "schema_version": PLUGIN_MARKET_SCHEMA_VERSION,
        "market_id": market_index["market_id"],
        "index_path": market_index["source_path"],
        "plugin_id": normalized_plugin_id,
        "plugin_type": str(manifest_plugin_type or ""),
        "plugins_dir": target_root.as_posix(),
        "manifest_path": target_manifest.as_posix(),
        "module_path": target_module.as_posix(),
        "copied_files": sorted(copied_files),
        "changed": bool(manifest_changed or module_changed),
        "already_installed": not bool(manifest_changed or module_changed),
        "manifest_sha256": _sha256_file(target_manifest),
        "module_sha256": _sha256_file(target_module),
    }


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

    # The cached snapshot is a normalized offline view for UI consumers.
    # Keep it stable even if the source index lives at a different path.
    snapshot_payload = {
        "schema_version": PLUGIN_MARKET_SCHEMA_VERSION,
        "market_id": market_index["market_id"],
        "index_schema_version": market_index["schema_version"],
        "entries": market_index["entries"],
    }
    install_asset_root = market_index.get("install_asset_root")
    if isinstance(install_asset_root, str) and install_asset_root.strip():
        snapshot_payload["install_asset_root"] = install_asset_root
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
