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


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


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


def _call_renderer(
    renderer: Any,
    session: Dict[str, Any],
    recommendations: List[Dict[str, Any]],
    output_dir: Path | None,
) -> Dict[str, Any]:
    def _invoke(fn: Any) -> Dict[str, Any]:
        try:
            return fn(session, recommendations, output_dir) or {}
        except TypeError:
            return fn(session, recommendations) or {}

    if hasattr(renderer, "render"):
        return _invoke(renderer.render)
    if callable(renderer):
        return _invoke(renderer)
    raise TypeError("Renderer plugin is not callable and has no render().")


def _gate_summary(gate_results: Any) -> str:
    if not isinstance(gate_results, list):
        return ""
    context_order = {"suggest": 0, "auto_apply": 1, "render": 2}
    rows: List[tuple[int, str, str, str, str]] = []
    for result in gate_results:
        if not isinstance(result, dict):
            continue
        context = _coerce_str(result.get("context"))
        outcome = _coerce_str(result.get("outcome"))
        gate_id = _coerce_str(result.get("gate_id"))
        reason_id = _coerce_str(result.get("reason_id"))
        rows.append(
            (
                context_order.get(context, 99),
                gate_id,
                reason_id,
                context,
                outcome,
            )
        )
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    parts = [f"{context}:{outcome}({gate_id}|{reason_id})" for _, gate_id, reason_id, context, outcome in rows]
    return ";".join(parts)


def _normalize_skipped_entry(entry: Any) -> Dict[str, str] | None:
    if not isinstance(entry, dict):
        return None
    return {
        "recommendation_id": _coerce_str(entry.get("recommendation_id")),
        "action_id": _coerce_str(entry.get("action_id")),
        "reason": _coerce_str(entry.get("reason")),
        "gate_summary": _coerce_str(entry.get("gate_summary")),
    }


def _skipped_sort_key(entry: Dict[str, str]) -> tuple[str, str, str, int, str]:
    gate_summary = entry["gate_summary"]
    return (
        entry["recommendation_id"],
        entry["action_id"],
        entry["reason"],
        0 if gate_summary else 1,
        gate_summary,
    )


def _merge_skipped_entries(*skipped_groups: Iterable[Any]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for group in skipped_groups:
        for item in group:
            normalized_item = _normalize_skipped_entry(item)
            if normalized_item is not None:
                normalized.append(normalized_item)

    normalized.sort(key=_skipped_sort_key)
    merged: List[Dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in normalized:
        key = (item["recommendation_id"], item["action_id"], item["reason"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def _recommendation_index(
    recommendations: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for rec in recommendations:
        rec_id = _coerce_str(rec.get("recommendation_id"))
        if not rec_id or rec_id in index:
            continue
        index[rec_id] = rec
    return index


def _output_contributing_recommendation_ids(output: Dict[str, Any]) -> List[str]:
    ids: set[str] = set()
    recommendation_id = _coerce_str(output.get("recommendation_id"))
    if recommendation_id:
        ids.add(recommendation_id)

    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        raw_ids = metadata.get("contributing_recommendation_ids")
        if isinstance(raw_ids, list):
            for item in raw_ids:
                rec_id = _coerce_str(item)
                if rec_id:
                    ids.add(rec_id)

    return sorted(ids)


def _annotate_manifest_output_extremes(
    manifest: Dict[str, Any],
    recommendations_by_id: Dict[str, Dict[str, Any]],
) -> None:
    outputs = _coerce_list(manifest.get("outputs"))
    for output in outputs:
        if not isinstance(output, dict):
            continue
        contributing_ids = _output_contributing_recommendation_ids(output)
        is_extreme = any(
            recommendations_by_id.get(rec_id, {}).get("extreme") is True
            for rec_id in contributing_ids
        )
        metadata = output.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            output["metadata"] = metadata
        metadata["extreme"] = is_extreme


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


def run_renderers(
    report: Dict[str, Any],
    plugins: Sequence[PluginEntry],
    *,
    output_dir: Path | None = None,
) -> List[Dict[str, Any]]:
    session = report.get("session") if isinstance(report, dict) else {}
    if not isinstance(session, dict):
        session = {}
    recommendations = report.get("recommendations") if isinstance(report, dict) else []
    recs = _coerce_list(recommendations)
    recs = [rec for rec in recs if isinstance(rec, dict)]
    recs_by_id = _recommendation_index(recs)
    eligible = [rec for rec in recs if rec.get("eligible_render") is True]
    blocked = [rec for rec in recs if rec.get("eligible_render") is not True]

    blocked_skipped: List[Dict[str, Any]] = []
    for rec in blocked:
        blocked_skipped.append(
            {
                "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                "action_id": _coerce_str(rec.get("action_id")),
                "reason": "blocked_by_gates",
                "gate_summary": _gate_summary(rec.get("gate_results")),
            }
        )
    blocked_skipped = _merge_skipped_entries(blocked_skipped)

    manifests: List[Dict[str, Any]] = []
    for plugin in plugins:
        if plugin.plugin_type != "renderer":
            continue
        manifest = _call_renderer(plugin.instance, session, eligible, output_dir)
        if not isinstance(manifest, dict):
            manifest = {
                "renderer_id": plugin.plugin_id,
                "outputs": [],
                "notes": "Renderer returned non-dict manifest.",
            }
        if "renderer_id" not in manifest:
            manifest["renderer_id"] = plugin.plugin_id
        _annotate_manifest_output_extremes(manifest, recs_by_id)
        plugin_skipped = _coerce_list(manifest.get("skipped"))
        manifest["skipped"] = _merge_skipped_entries(blocked_skipped, plugin_skipped)
        manifests.append(manifest)

    return manifests
