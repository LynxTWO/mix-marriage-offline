from __future__ import annotations

from dataclasses import dataclass
import importlib
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


@dataclass(frozen=True)
class PluginEntry:
    plugin_id: str
    plugin_type: str
    version: str | None
    instance: Any
    manifest_path: Path
    manifest: Dict[str, Any]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_repo_on_path() -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load plugin manifests.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Plugin manifest is not a mapping: {path}")
    return data


def _collect_manifests(plugins_dir: Path) -> List[Path]:
    patterns = ["plugin.yaml", "plugin.yml", "*.plugin.yaml"]
    paths: set[Path] = set()
    for pattern in patterns:
        for match in plugins_dir.rglob(pattern):
            if match.is_file():
                paths.add(match)
    return sorted(paths, key=lambda p: str(p))


def _load_entrypoint(entrypoint: str) -> Any:
    if ":" not in entrypoint:
        raise ValueError(f"Entrypoint must be module:Symbol, got {entrypoint!r}")
    module_name, symbol_name = entrypoint.split(":", 1)
    _ensure_repo_on_path()
    module = importlib.import_module(module_name)
    symbol = getattr(module, symbol_name, None)
    if symbol is None:
        raise AttributeError(f"Entrypoint symbol not found: {entrypoint}")
    return symbol() if callable(symbol) else symbol


def load_plugins(plugins_dir: Path) -> List[PluginEntry]:
    entries: List[PluginEntry] = []
    for manifest_path in _collect_manifests(plugins_dir):
        data = _load_yaml(manifest_path)
        plugin_id = data.get("plugin_id")
        plugin_type = data.get("plugin_type")
        entrypoint = data.get("entrypoint")
        if not isinstance(plugin_id, str) or not isinstance(plugin_type, str):
            raise ValueError(f"Manifest missing plugin_id/plugin_type: {manifest_path}")
        if not isinstance(entrypoint, str):
            raise ValueError(f"Manifest missing entrypoint: {manifest_path}")
        instance = _load_entrypoint(entrypoint)
        entries.append(
            PluginEntry(
                plugin_id=plugin_id,
                plugin_type=plugin_type,
                version=data.get("version"),
                instance=instance,
                manifest_path=manifest_path,
                manifest=data,
            )
        )
    entries.sort(key=lambda entry: entry.plugin_id)
    return entries


def _coerce_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _call_detector(detector: Any, session: Dict[str, Any], features: Dict[str, Any]) -> List[Dict[str, Any]]:
    if hasattr(detector, "detect"):
        return detector.detect(session, features) or []
    if callable(detector):
        return detector(session, features) or []
    raise TypeError("Detector plugin is not callable and has no detect().")


def _call_resolver(
    resolver: Any,
    session: Dict[str, Any],
    features: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if hasattr(resolver, "resolve"):
        return resolver.resolve(session, features, issues) or []
    if callable(resolver):
        return resolver(session, features, issues) or []
    raise TypeError("Resolver plugin is not callable and has no resolve().")


def run_detectors(session_report: Dict[str, Any], plugins: Sequence[PluginEntry]) -> None:
    session = session_report.get("session") or {}
    features = session_report.get("features") or {}
    issues = _coerce_list(session_report.get("issues"))
    for plugin in plugins:
        if plugin.plugin_type != "detector":
            continue
        plugin_issues = _call_detector(plugin.instance, session, features)
        if plugin_issues:
            issues.extend(plugin_issues)
    session_report["issues"] = issues


def run_resolvers(session_report: Dict[str, Any], plugins: Sequence[PluginEntry]) -> None:
    session = session_report.get("session") or {}
    features = session_report.get("features") or {}
    issues = _coerce_list(session_report.get("issues"))
    recommendations = _coerce_list(session_report.get("recommendations"))
    for plugin in plugins:
        if plugin.plugin_type != "resolver":
            continue
        plugin_recs = _call_resolver(plugin.instance, session, features, issues)
        if plugin_recs:
            recommendations.extend(plugin_recs)
    session_report["recommendations"] = recommendations
