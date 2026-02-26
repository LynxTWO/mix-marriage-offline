from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from mmo.resources import schemas_dir

PLUGIN_DIR_ENV_VAR = "MMO_PLUGIN_DIR"


def default_user_plugins_dir() -> Path:
    """Return the default per-user external plugin directory."""
    raw_home = os.environ.get("HOME", "").strip()
    if raw_home:
        return Path(raw_home).expanduser() / ".mmo" / "plugins"
    return Path(os.path.expanduser("~")) / ".mmo" / "plugins"


def _resolved_external_plugin_dir(
    plugin_dir: Path | None,
) -> tuple[Path, bool]:
    if plugin_dir is not None:
        return plugin_dir.expanduser().resolve(), True

    raw_env = os.environ.get(PLUGIN_DIR_ENV_VAR)
    if isinstance(raw_env, str) and raw_env.strip():
        return Path(raw_env.strip()).expanduser().resolve(), True

    return default_user_plugins_dir().expanduser().resolve(), False


def resolve_plugin_roots(
    plugins_dir: Path,
    plugin_dir: Path | None = None,
) -> tuple[Path, ...]:
    """Resolve the ordered plugin roots to scan.

    Order:
      1) Primary plugin directory (``--plugins`` style path)
      2) External plugin directory (``--plugin-dir`` / ``MMO_PLUGIN_DIR`` / default)
    """
    primary = plugins_dir.expanduser().resolve()
    roots: List[Path] = []

    if primary.exists() and not primary.is_dir():
        raise ValueError(f"Plugins path is not a directory: {primary.as_posix()}")
    if primary.exists():
        roots.append(primary)

    external, external_is_explicit = _resolved_external_plugin_dir(plugin_dir)
    if external.exists() and not external.is_dir():
        raise ValueError(f"External plugin path is not a directory: {external.as_posix()}")
    if external.exists():
        if external not in roots:
            roots.append(external)
    elif external_is_explicit:
        raise ValueError(f"External plugin directory does not exist: {external.as_posix()}")

    return tuple(roots)


@contextmanager
def _plugin_import_paths(plugin_root: Path) -> Iterator[None]:
    """Temporarily add plugin root search paths for dynamic entrypoint imports."""
    candidates = (plugin_root, plugin_root.parent)
    inserted: list[str] = []
    for candidate in candidates:
        candidate_text = str(candidate)
        if candidate_text in sys.path:
            continue
        sys.path.insert(0, candidate_text)
        inserted.append(candidate_text)
    try:
        yield
    finally:
        for candidate_text in inserted:
            try:
                sys.path.remove(candidate_text)
            except ValueError:
                continue


def _validate_plugin_root(
    plugin_root: Path,
) -> None:
    from mmo.core.pipeline import _collect_manifests, _load_yaml  # noqa: WPS433
    from mmo.core.plugin_registry import (  # noqa: WPS433
        PluginRegistryError,
        load_semantics,
        validate_manifest,
    )

    semantics = load_semantics()
    schema_path = schemas_dir() / "plugin.schema.json"
    errors_by_path: dict[str, list[str]] = {}

    for manifest_path in _collect_manifests(plugin_root):
        try:
            manifest = _load_yaml(manifest_path)
        except Exception as exc:
            errors_by_path[str(manifest_path)] = [f"[parse] {exc}"]
            continue

        errors = validate_manifest(
            manifest,
            schema_path=schema_path,
            semantics=semantics,
        )
        if errors:
            errors_by_path[str(manifest_path)] = errors

    if errors_by_path:
        raise PluginRegistryError(errors_by_path)


def _register_plugin_entries(
    loaded_by_root: list[tuple[Path, list["PluginEntry"]]],
) -> list["PluginEntry"]:
    registered: dict[str, PluginEntry] = {}
    source_by_id: dict[str, str] = {}

    for plugin_root, entries in loaded_by_root:
        source = plugin_root.as_posix()
        for entry in entries:
            existing_source = source_by_id.get(entry.plugin_id)
            if existing_source is not None:
                raise ValueError(
                    "Duplicate plugin_id detected across plugin roots: "
                    f"{entry.plugin_id!r} in {existing_source} and {source}"
                )
            source_by_id[entry.plugin_id] = source
            registered[entry.plugin_id] = entry

    return [registered[plugin_id] for plugin_id in sorted(registered)]


def load_registered_plugins(
    plugins_dir: Path,
    plugin_dir: Path | None = None,
) -> list["PluginEntry"]:
    """Load plugins from primary + external roots with validation and registration.

    Validation is strict (schema + semantics) before entrypoint imports.
    Registration enforces unique ``plugin_id`` across all resolved roots.
    """
    from mmo.core.pipeline import PluginEntry, _load_plugins_from_dir  # noqa: WPS433

    roots = resolve_plugin_roots(plugins_dir, plugin_dir=plugin_dir)
    loaded_by_root: list[tuple[Path, list[PluginEntry]]] = []

    for plugin_root in roots:
        _validate_plugin_root(plugin_root)
        with _plugin_import_paths(plugin_root):
            loaded_by_root.append((plugin_root, _load_plugins_from_dir(plugin_root)))

    return _register_plugin_entries(loaded_by_root)
