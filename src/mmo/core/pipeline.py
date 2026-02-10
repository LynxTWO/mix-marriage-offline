from __future__ import annotations

from dataclasses import dataclass
import importlib
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from mmo.core.deliverables import (
    build_deliverables_from_outputs,
    collect_outputs_from_renderer_manifests,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import sha256_file
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS, supported_output_formats, transcode_wav_to_format
from mmo.plugins.interfaces import (
    PLUGIN_SUPPORTED_CONTEXTS,
    PluginCapabilities,
    PluginSceneCapabilities,
)

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_CODEC_BY_FORMAT = {
    "wav": "pcm",
    "flac": "flac",
    "wv": "wavpack",
    "aiff": "pcm_s24be",
    "alac": "alac",
}
_FILE_SUFFIX_BY_FORMAT = {
    "wav": "wav",
    "flac": "flac",
    "wv": "wv",
    "aiff": "aiff",
    "alac": "m4a",
}


@dataclass(frozen=True)
class PluginEntry:
    plugin_id: str
    plugin_type: str
    version: str | None
    capabilities: PluginCapabilities | None
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


def _coerce_plugin_capabilities(value: Any) -> PluginCapabilities | None:
    if not isinstance(value, dict):
        return None

    max_channels: int | None = None
    raw_max_channels = value.get("max_channels")
    if (
        isinstance(raw_max_channels, int)
        and not isinstance(raw_max_channels, bool)
        and raw_max_channels >= 1
    ):
        max_channels = raw_max_channels

    def _coerce_string_tuple(raw_value: Any) -> tuple[str, ...] | None:
        if not isinstance(raw_value, list):
            return None
        return tuple(item for item in raw_value if isinstance(item, str))

    def _coerce_bool(raw_value: Any) -> bool | None:
        if isinstance(raw_value, bool):
            return raw_value
        return None

    supported_layout_ids = _coerce_string_tuple(value.get("supported_layout_ids"))

    supported_contexts_raw = _coerce_string_tuple(value.get("supported_contexts"))
    supported_contexts: tuple[str, ...] | None = None
    if supported_contexts_raw is not None:
        supported_contexts = tuple(
            context
            for context in supported_contexts_raw
            if context in PLUGIN_SUPPORTED_CONTEXTS
        )

    scene_value = value.get("scene")
    scene: PluginSceneCapabilities | None = None
    if isinstance(scene_value, dict):
        scene = PluginSceneCapabilities(
            supports_objects=_coerce_bool(scene_value.get("supports_objects")),
            supports_beds=_coerce_bool(scene_value.get("supports_beds")),
            supports_locks=_coerce_bool(scene_value.get("supports_locks")),
            requires_speaker_positions=_coerce_bool(
                scene_value.get("requires_speaker_positions")
            ),
            supported_target_ids=_coerce_string_tuple(
                scene_value.get("supported_target_ids")
            ),
        )

    notes = _coerce_string_tuple(value.get("notes"))
    return PluginCapabilities(
        max_channels=max_channels,
        supported_layout_ids=supported_layout_ids,
        supported_contexts=supported_contexts,
        scene=scene,
        notes=notes,
    )


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
        capabilities = _coerce_plugin_capabilities(data.get("capabilities"))
        instance = _load_entrypoint(entrypoint)
        if capabilities is not None:
            try:
                setattr(instance, "plugin_capabilities", capabilities)
            except Exception:
                pass
        entries.append(
            PluginEntry(
                plugin_id=plugin_id,
                plugin_type=plugin_type,
                version=data.get("version"),
                capabilities=capabilities,
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


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


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


def _gate_summary(gate_results: Any, *, context: str | None = None) -> str:
    if not isinstance(gate_results, list):
        return ""
    context_order = {"suggest": 0, "auto_apply": 1, "render": 2}
    rows: List[tuple[int, str, str, str, str]] = []
    for result in gate_results:
        if not isinstance(result, dict):
            continue
        result_context = _coerce_str(result.get("context"))
        if context is not None and result_context != context:
            continue
        outcome = _coerce_str(result.get("outcome"))
        gate_id = _coerce_str(result.get("gate_id"))
        reason_id = _coerce_str(result.get("reason_id"))
        rows.append(
            (
                context_order.get(result_context, 99),
                gate_id,
                reason_id,
                result_context,
                outcome,
            )
        )
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    parts = [f"{context}:{outcome}({gate_id}|{reason_id})" for _, gate_id, reason_id, context, outcome in rows]
    return ";".join(parts)


def _normalize_skipped_entry(entry: Any) -> Dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    normalized = {
        "recommendation_id": _coerce_str(entry.get("recommendation_id")),
        "action_id": _coerce_str(entry.get("action_id")),
        "reason": _coerce_str(entry.get("reason")),
        "gate_summary": _coerce_str(entry.get("gate_summary")),
    }
    details = entry.get("details")
    if isinstance(details, dict):
        normalized["details"] = dict(details)
    return normalized


def _skipped_sort_key(entry: Dict[str, Any]) -> tuple[str, str, str, int, str, str]:
    gate_summary = _coerce_str(entry.get("gate_summary"))
    details = entry.get("details")
    details_token = ""
    if isinstance(details, dict):
        details_token = ";".join(
            f"{_coerce_str(key)}={details[key]!r}" for key in sorted(details)
        )
    return (
        _coerce_str(entry.get("recommendation_id")),
        _coerce_str(entry.get("action_id")),
        _coerce_str(entry.get("reason")),
        0 if gate_summary else 1,
        gate_summary,
        details_token,
    )


def _merge_skipped_entries(*skipped_groups: Iterable[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for group in skipped_groups:
        for item in group:
            normalized_item = _normalize_skipped_entry(item)
            if normalized_item is not None:
                normalized.append(normalized_item)

    normalized.sort(key=_skipped_sort_key)
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in normalized:
        key = (
            _coerce_str(item.get("recommendation_id")),
            _coerce_str(item.get("action_id")),
            _coerce_str(item.get("reason")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def _stem_channel_count_index(session: Dict[str, Any]) -> Dict[str, int]:
    stems = session.get("stems")
    if not isinstance(stems, list):
        return {}

    channels_by_stem_id: Dict[str, int] = {}
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if not stem_id or stem_id in channels_by_stem_id:
            continue
        channel_count = _coerce_int(stem.get("channel_count"))
        if channel_count is None or channel_count < 1:
            continue
        channels_by_stem_id[stem_id] = channel_count
    return channels_by_stem_id


def _required_channels_for_recommendations(
    session: Dict[str, Any],
    recommendations: Sequence[Dict[str, Any]],
) -> int:
    channels_by_stem_id = _stem_channel_count_index(session)
    if not channels_by_stem_id:
        return 0

    required_channels = 0
    for rec in recommendations:
        target = rec.get("target")
        if not isinstance(target, dict):
            continue
        if target.get("scope") != "stem":
            continue
        stem_id = _coerce_str(target.get("stem_id"))
        if not stem_id:
            continue
        stem_channels = channels_by_stem_id.get(stem_id)
        if stem_channels is None:
            continue
        required_channels = max(required_channels, stem_channels)
    return required_channels


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


def _normalize_output_formats(output_formats: Sequence[str] | None) -> tuple[str, ...]:
    if output_formats is None:
        return ("wav",)
    if isinstance(output_formats, str) or not isinstance(output_formats, Sequence):
        raise ValueError("output_formats must be a sequence.")

    supported = supported_output_formats()
    selected: set[str] = set()
    for raw in output_formats:
        if not isinstance(raw, str):
            raise ValueError("output_formats values must be strings.")
        normalized = raw.strip().lower()
        if not normalized:
            raise ValueError("output_formats values must be non-empty strings.")
        if normalized not in supported:
            allowed = ", ".join(_OUTPUT_FORMAT_ORDER)
            raise ValueError(
                f"Unsupported output format {normalized!r}. Allowed: {allowed}."
            )
        selected.add(normalized)

    if not selected:
        raise ValueError("output_formats must include at least one format.")
    return tuple(fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected)


def _resolve_output_artifact_path(file_path: str, output_dir: Path | None) -> Path | None:
    if not file_path:
        return None
    path = Path(file_path)
    if path.is_absolute():
        return path
    if output_dir is None:
        return None
    return output_dir / path


def _replace_output_extension(file_path: str, output_format: str) -> str:
    new_suffix = _FILE_SUFFIX_BY_FORMAT.get(output_format, output_format)
    replaced = Path(file_path).with_suffix(f".{new_suffix}")
    if replaced.is_absolute():
        return str(replaced)
    return replaced.as_posix()


def _transcode_output_id(source_output: Dict[str, Any], fmt: str, sha256: str) -> str:
    stem_token = _coerce_str(source_output.get("target_stem_id"))
    if not stem_token:
        stem_token = _coerce_str(source_output.get("target_bus_id"))
    if not stem_token:
        stem_token = "artifact"
    return f"OUTPUT.TRANSCODE.{stem_token}.{fmt}.{sha256[:8]}"


def _output_sort_key(output: Dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _coerce_str(output.get("target_stem_id")),
        _coerce_str(output.get("format")),
        _coerce_str(output.get("file_path")),
        _coerce_str(output.get("output_id")),
    )


def _make_transcoded_output(
    source_output: Dict[str, Any],
    *,
    output_format: str,
    file_path: str,
    sha256: str,
) -> Dict[str, Any]:
    transcoded: Dict[str, Any] = {
        "output_id": _transcode_output_id(source_output, output_format, sha256),
        "file_path": file_path,
        "format": output_format,
        "sha256": sha256,
    }

    for key in (
        "action_id",
        "recommendation_id",
        "target_stem_id",
        "target_bus_id",
        "layout_id",
        "sample_rate_hz",
        "bit_depth",
        "channel_count",
        "notes",
    ):
        if key in source_output:
            transcoded[key] = source_output[key]

    codec = _CODEC_BY_FORMAT.get(output_format)
    if codec:
        transcoded["codec"] = codec

    metadata = source_output.get("metadata")
    transcoded_metadata: Dict[str, Any] = {}
    if isinstance(metadata, dict):
        transcoded_metadata.update(metadata)
    transcoded_metadata["transcode_from_output_id"] = _coerce_str(
        source_output.get("output_id")
    )
    transcoded_metadata["transcode_from_format"] = _coerce_str(
        source_output.get("format")
    ) or "wav"
    transcoded["metadata"] = transcoded_metadata
    return transcoded


def _append_transcode_skip(
    skipped: List[Dict[str, Any]],
    output: Dict[str, Any],
    *,
    reason: str,
) -> None:
    skipped.append(
        {
            "recommendation_id": _coerce_str(output.get("recommendation_id")),
            "action_id": _coerce_str(output.get("action_id")),
            "reason": reason,
            "gate_summary": "",
        }
    )


def _apply_output_formats_to_manifest(
    manifest: Dict[str, Any],
    *,
    output_dir: Path | None,
    desired_formats: tuple[str, ...],
    ffmpeg_cmd: Sequence[str] | None,
) -> List[Dict[str, Any]]:
    outputs = _coerce_list(manifest.get("outputs"))
    non_wav_formats = tuple(fmt for fmt in desired_formats if fmt != "wav")
    keep_wav = "wav" in desired_formats

    rewritten_outputs: List[Dict[str, Any]] = []
    transcode_skipped: List[Dict[str, Any]] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        source_format = _coerce_str(output.get("format")).strip().lower()
        if source_format == "wav":
            if keep_wav:
                rewritten_outputs.append(output)

            if not non_wav_formats:
                continue

            source_file_path = _coerce_str(output.get("file_path"))
            source_path = _resolve_output_artifact_path(source_file_path, output_dir)
            if source_path is None or not source_path.exists():
                _append_transcode_skip(
                    transcode_skipped,
                    output,
                    reason="missing_source_artifact",
                )
                continue

            if ffmpeg_cmd is None:
                _append_transcode_skip(
                    transcode_skipped,
                    output,
                    reason="missing_ffmpeg_for_encode",
                )
                continue

            for target_format in non_wav_formats:
                target_file_path = _replace_output_extension(
                    source_file_path,
                    target_format,
                )
                target_path = _resolve_output_artifact_path(target_file_path, output_dir)
                if target_path is None:
                    _append_transcode_skip(
                        transcode_skipped,
                        output,
                        reason="missing_source_artifact",
                    )
                    continue
                try:
                    transcode_wav_to_format(
                        ffmpeg_cmd,
                        source_path,
                        target_path,
                        target_format,
                    )
                except (OSError, ValueError):
                    _append_transcode_skip(
                        transcode_skipped,
                        output,
                        reason="encode_failed",
                    )
                    continue
                output_sha256 = sha256_file(target_path)
                rewritten_outputs.append(
                    _make_transcoded_output(
                        output,
                        output_format=target_format,
                        file_path=target_file_path,
                        sha256=output_sha256,
                    )
                )
            continue

        if source_format in desired_formats:
            rewritten_outputs.append(output)
            continue

        if source_format not in supported_output_formats():
            rewritten_outputs.append(output)

    rewritten_outputs.sort(key=_output_sort_key)
    manifest["outputs"] = rewritten_outputs
    return transcode_skipped


def build_deliverables_for_renderer_manifests(
    renderer_manifests: Sequence[dict[str, Any]],
) -> List[Dict[str, Any]]:
    outputs = collect_outputs_from_renderer_manifests(renderer_manifests)
    return build_deliverables_from_outputs(outputs)


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
    output_dir: Path | None = None,
    *,
    eligibility_field: str = "eligible_render",
    context: str = "render",
    output_formats: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    session = report.get("session") if isinstance(report, dict) else {}
    if not isinstance(session, dict):
        session = {}
    session_for_plugins = session
    routing_plan = report.get("routing_plan") if isinstance(report, dict) else None
    if isinstance(routing_plan, dict):
        session_for_plugins = dict(session)
        session_for_plugins["routing_plan"] = routing_plan
    recommendations = report.get("recommendations") if isinstance(report, dict) else []
    recs = _coerce_list(recommendations)
    recs = [rec for rec in recs if isinstance(rec, dict)]
    recs_by_id = _recommendation_index(recs)
    eligible = [rec for rec in recs if rec.get(eligibility_field) is True]
    blocked = [rec for rec in recs if rec.get(eligibility_field) is not True]

    blocked_skipped: List[Dict[str, Any]] = []
    for rec in blocked:
        blocked_skipped.append(
            {
                "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                "action_id": _coerce_str(rec.get("action_id")),
                "reason": "blocked_by_gates",
                "gate_summary": _gate_summary(rec.get("gate_results"), context=context),
            }
        )
    blocked_skipped = _merge_skipped_entries(blocked_skipped)
    required_channels = _required_channels_for_recommendations(session, eligible)
    desired_formats = _normalize_output_formats(output_formats)
    needs_encode = any(fmt != "wav" for fmt in desired_formats)
    ffmpeg_cmd = resolve_ffmpeg_cmd() if needs_encode else None

    manifests: List[Dict[str, Any]] = []
    for plugin in plugins:
        if plugin.plugin_type != "renderer":
            continue

        plugin_max_channels = None
        if plugin.capabilities is not None:
            plugin_max_channels = plugin.capabilities.max_channels
        if (
            isinstance(plugin_max_channels, int)
            and not isinstance(plugin_max_channels, bool)
            and plugin_max_channels >= 1
            and required_channels > plugin_max_channels
        ):
            channel_limit_skipped = [
                {
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "plugin_channel_limit",
                    "gate_summary": "",
                    "details": {
                        "plugin_id": plugin.plugin_id,
                        "required_channels": required_channels,
                        "max_channels": plugin_max_channels,
                    },
                }
                for rec in eligible
            ]
            manifests.append(
                {
                    "renderer_id": plugin.plugin_id,
                    "outputs": [],
                    "skipped": _merge_skipped_entries(
                        blocked_skipped,
                        channel_limit_skipped,
                    ),
                }
            )
            continue

        manifest = _call_renderer(plugin.instance, session_for_plugins, eligible, output_dir)
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
        transcode_skipped = _apply_output_formats_to_manifest(
            manifest,
            output_dir=output_dir,
            desired_formats=desired_formats,
            ffmpeg_cmd=ffmpeg_cmd,
        )
        manifest["skipped"] = _merge_skipped_entries(
            blocked_skipped,
            plugin_skipped,
            transcode_skipped,
        )
        manifests.append(manifest)

    return manifests
