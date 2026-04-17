from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from mmo.resources import plugins_dir as packaged_plugins_dir
from mmo.resources import schemas_dir

PLUGIN_DIR_ENV_VAR = "MMO_PLUGIN_DIR"


def default_user_plugins_dir() -> Path:
    """Return the default per-user external plugin directory.

    Platform conventions:
      Windows: %LOCALAPPDATA%\\mmo\\plugins  (fallback: APPDATA, USERPROFILE, ~)
      macOS:   ~/Library/Application Support/mmo/plugins
      Linux:   $XDG_DATA_HOME/mmo/plugins  (fallback: ~/.local/share/mmo/plugins)
    """
    if sys.platform == "win32":
        base_str = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.environ.get("USERPROFILE")
            or os.path.expanduser("~")
        )
        return Path(base_str) / "mmo" / "plugins"
    if sys.platform == "darwin":
        home = os.environ.get("HOME") or os.path.expanduser("~")
        return Path(home) / "Library" / "Application Support" / "mmo" / "plugins"
    # Linux / other POSIX
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "mmo" / "plugins"
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".local" / "share" / "mmo" / "plugins"


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
      3) Built-in packaged plugin directory (``mmo.data/plugins``)
    """
    primary = plugins_dir.expanduser().resolve()
    roots: List[Path] = []

    if primary.exists() and not primary.is_dir():
        raise ValueError(f"Plugins path is not a directory: {primary.as_posix()}")
    if primary.exists():
        roots.append(primary)

    external, external_is_explicit = _resolved_external_plugin_dir(plugin_dir)
    # Explicit external roots and the implicit per-user default are not the
    # same trust signal. A missing explicit root means the operator asked for a
    # specific plugin set, so falling through to bundled fallback would load
    # the wrong authority surface.
    if external.exists() and not external.is_dir():
        raise ValueError(f"External plugin path is not a directory: {external.as_posix()}")
    if external.exists():
        if external not in roots:
            roots.append(external)
    elif external_is_explicit:
        # An explicit external root is operator intent.
        # Silent fallback here would load the wrong plugin set.
        raise ValueError(f"External plugin directory does not exist: {external.as_posix()}")

    built_in = packaged_plugins_dir()
    if built_in is not None and built_in not in roots:
        # Keep the bundled root in candidate order. Registration decides later
        # whether it stays active fallback or gets dropped.
        roots.append(built_in)

    return tuple(roots)


@contextmanager
def _plugin_import_paths(plugin_root: Path) -> Iterator[None]:
    """Temporarily add plugin root search paths for dynamic entrypoint imports."""
    # Plugin entrypoints may import as either plugins.foo or mmo.plugins.foo.
    # Keep both search roots scoped to one load call so plugin paths do not
    # leak into the rest of the process.
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

    # Validate manifests before touching sys.path or importing entrypoints.
    # Keep this boundary per root. A malformed earlier root should fail before
    # code from that root runs, but later fallback roots are not pre-validated
    # up front.
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
    *,
    built_in_root: Path | None,
) -> list["PluginEntry"]:
    registered: dict[str, PluginEntry] = {}
    source_by_id: dict[str, str] = {}
    built_in_source = built_in_root.as_posix() if built_in_root is not None else None
    # Bundled fallback is a root-level decision, not a per-plugin merge. Once a
    # repo or external root yields entries, packaged manifests stop
    # contributing entries for this load.
    has_non_built_in_entries = any(
        entries and plugin_root.as_posix() != built_in_source
        for plugin_root, entries in loaded_by_root
    )

    for plugin_root, entries in loaded_by_root:
        source = plugin_root.as_posix()
        if has_non_built_in_entries and source == built_in_source:
            # Once a repo or external root provides plugins, packaged copies stop
            # being authoritative. Mixing both would hide stale duplicate IDs.
            # Built-in packaged manifests are only a fallback when no other roots load plugins.
            continue
        for entry in entries:
            existing_source = source_by_id.get(entry.plugin_id)
            if existing_source is not None:
                if source == built_in_source:
                    # Keep earlier roots authoritative; packaged manifests are fallback.
                    continue
                # Primary and external roots are peers. Shadowing here would
                # hide split authority instead of forcing the operator to pick
                # one plugin root.
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
    """Load plugins from primary, external, and built-in roots.

    Validation is strict (schema + semantics) before entrypoint imports.
    Registration enforces unique ``plugin_id`` across primary/external roots.
    Built-in packaged manifests are used only when primary/external roots load no plugins.
    """
    from mmo.core.pipeline import PluginEntry, _load_plugins_from_dir  # noqa: WPS433

    roots = resolve_plugin_roots(plugins_dir, plugin_dir=plugin_dir)
    loaded_by_root: list[tuple[Path, list[PluginEntry]]] = []

    for plugin_root in roots:
        # Keep import trust scoped to one root at a time. Validate this root,
        # then import this root. Do not assume later fallback roots were
        # checked before earlier plugin code runs.
        _validate_plugin_root(plugin_root)
        with _plugin_import_paths(plugin_root):
            loaded_by_root.append((plugin_root, _load_plugins_from_dir(plugin_root)))

    return _register_plugin_entries(
        loaded_by_root,
        built_in_root=packaged_plugins_dir(),
    )


def load_plugin_root_entries(plugins_dir: Path) -> list["PluginEntry"]:
    """Validate and load plugins from exactly one plugin root."""
    from mmo.core.pipeline import PluginEntry, _load_plugins_from_dir  # noqa: WPS433

    resolved_plugins_dir = plugins_dir.expanduser().resolve()
    if not resolved_plugins_dir.exists():
        raise ValueError(
            f"Plugins directory does not exist: {resolved_plugins_dir.as_posix()}"
        )
    if not resolved_plugins_dir.is_dir():
        raise ValueError(
            f"Plugins path is not a directory: {resolved_plugins_dir.as_posix()}"
        )

    _validate_plugin_root(resolved_plugins_dir)
    with _plugin_import_paths(resolved_plugins_dir):
        entries: list[PluginEntry] = _load_plugins_from_dir(resolved_plugins_dir)
    return entries
