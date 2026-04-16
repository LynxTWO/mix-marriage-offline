from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.core.plugin_loader import load_plugin_root_entries
from mmo.core.plugin_registry import PluginRegistryError
from mmo.resources import plugins_dir as packaged_plugins_dir

PLUGIN_VALIDATION_SCHEMA_VERSION = "0.1.0"


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _normalize_path_text(value: Path | str | None) -> str:
    if value is None:
        return ""
    try:
        return _path_to_posix(Path(value))
    except (OSError, RuntimeError, ValueError, TypeError):
        return str(value).replace("\\", "/")


def _resolve_plugins_dir(*, plugins_dir: Path | None, bundled_only: bool) -> Path:
    if bundled_only:
        # Release and smoke checks use bundled_only so ambient user plugins do
        # not make packaged validation look healthier than the shipped bundle.
        bundled_plugins_dir = packaged_plugins_dir()
        if bundled_plugins_dir is None:
            raise RuntimeError("Bundled plugins directory is unavailable.")
        return bundled_plugins_dir.resolve()
    if plugins_dir is None:
        raise ValueError("plugins_dir is required unless bundled_only is set.")
    return plugins_dir.expanduser().resolve()


def _plugin_row(entry: Any) -> dict[str, Any]:
    return {
        "plugin_id": entry.plugin_id,
        "plugin_type": entry.plugin_type,
        "version": entry.version or "",
        "manifest_path": _path_to_posix(entry.manifest_path),
    }


def _plugin_issue(*, path: str, message: str) -> dict[str, str]:
    return {
        "severity": "error",
        "path": path,
        "message": message,
    }


def _issues_from_registry_error(exc: PluginRegistryError) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for manifest_path in sorted(exc.errors_by_path):
        normalized_manifest_path = _normalize_path_text(manifest_path)
        for message in sorted(exc.errors_by_path[manifest_path]):
            issues.append(
                _plugin_issue(
                    path=normalized_manifest_path,
                    message=message,
                )
            )
    return issues


def build_plugin_validation_payload(
    *,
    plugins_dir: Path | None = None,
    bundled_only: bool = False,
) -> dict[str, Any]:
    resolved_plugins_dir_text = ""
    plugins: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    try:
        resolved_plugins_dir = _resolve_plugins_dir(
            plugins_dir=plugins_dir,
            bundled_only=bundled_only,
        )
        resolved_plugins_dir_text = _path_to_posix(resolved_plugins_dir)
        entries = load_plugin_root_entries(resolved_plugins_dir)
        plugins = [_plugin_row(entry) for entry in entries]
    except PluginRegistryError as exc:
        # Keep registry issues structured so CLI and GUI can render the same
        # failure set without reparsing exception text.
        issues.extend(_issues_from_registry_error(exc))
        if not resolved_plugins_dir_text:
            fallback_path = packaged_plugins_dir() if bundled_only else plugins_dir
            resolved_plugins_dir_text = _normalize_path_text(fallback_path)
    except (RuntimeError, ValueError, AttributeError, ImportError, OSError) as exc:
        fallback_path = packaged_plugins_dir() if bundled_only else plugins_dir
        resolved_plugins_dir_text = _normalize_path_text(fallback_path)
        issues.append(
            _plugin_issue(
                path=resolved_plugins_dir_text,
                message=str(exc),
            )
        )

    if not plugins and not issues:
        # An empty root is still a failed validation outcome for install and CI
        # flows. Treating it as success would hide missing packaged content.
        issues.append(
            _plugin_issue(
                path=resolved_plugins_dir_text,
                message="No plugins were discovered.",
            )
        )

    return {
        "schema_version": PLUGIN_VALIDATION_SCHEMA_VERSION,
        "bundled_only": bundled_only,
        "plugins_dir": resolved_plugins_dir_text,
        "plugin_count": len(plugins),
        "issue_counts": {
            "error": len(issues),
        },
        "ok": len(issues) == 0,
        "plugins": plugins,
        "issues": issues,
    }


def plugin_validation_has_errors(payload: dict[str, Any]) -> bool:
    issue_counts = payload.get("issue_counts")
    if not isinstance(issue_counts, dict):
        return False
    error_count = issue_counts.get("error")
    return isinstance(error_count, int) and error_count > 0


__all__ = [
    "PLUGIN_VALIDATION_SCHEMA_VERSION",
    "build_plugin_validation_payload",
    "plugin_validation_has_errors",
]
