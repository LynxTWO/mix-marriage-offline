from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from mmo.core.deliverables import (
    build_deliverables_from_renderer_manifests as _build_deliverables_from_renderer_manifests,
    collect_outputs_from_renderer_manifests,
)
from mmo.core.layout_export import ffmpeg_layout_string_from_channel_order
from mmo.core.layout_negotiation import get_layout_channel_order
from mmo.core.media_tags import TagBag, empty_tag_bag, tag_bag_from_mapping
from mmo.core.precedence import apply_precedence, has_precedence_receipt
from mmo.core.recommendations import (
    normalize_recommendation_contract,
    normalize_recommendation_scope,
)
from mmo.core.source_locator import resolve_session_stems
from mmo.core.tag_export import build_ffmpeg_tag_export_args, metadata_receipt_mapping
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import sha256_file
from mmo.dsp.transcode import (
    LOSSLESS_OUTPUT_FORMATS,
    ffmpeg_supports_lfe2_layout_strings,
    supported_output_formats,
    transcode_wav_to_format,
)
from mmo.plugins.interfaces import (
    PLUGIN_SUPPORTED_CONTEXTS,
    PluginBehaviorContract,
    PluginCapabilities,
    PluginDeclares,
    PluginPurityContract,
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
_BASELINE_RENDERER_ID = "PLUGIN.RENDERER.MIXDOWN_BASELINE"
_SYSTEM_TRANSCODE_RECOMMENDATION_ID = "REC.SYSTEM.TRANSCODE"
_SYSTEM_TRANSCODE_ACTION_ID = "ACTION.DOWNMIX.RENDER"
_SYSTEM_PLUGIN_SAFETY_RECOMMENDATION_ID = "REC.SYSTEM.PLUGIN_SAFETY"
_SYSTEM_PLUGIN_SAFETY_ACTION_ID = "ACTION.SYSTEM.PLUGIN_SAFETY"
_SCENE_SCOPE_BED_ONLY = "bed_only"
_SCENE_SCOPE_OBJECT_CAPABLE = "object_capable"
_LAYOUT_SAFETY_AGNOSTIC = "layout_agnostic"
_LAYOUT_SAFETY_SPECIFIC = "layout_specific"


@dataclass(frozen=True)
class PluginEntry:
    plugin_id: str
    plugin_type: str
    version: str | None
    capabilities: PluginCapabilities | None
    instance: Any
    manifest_path: Path
    manifest: Dict[str, Any]
    declares: PluginDeclares | None = None
    behavior_contract: PluginBehaviorContract | None = None

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

    def _coerce_int_tuple(raw_value: Any) -> tuple[int, ...] | None:
        if not isinstance(raw_value, list):
            return None
        return tuple(
            item
            for item in raw_value
            if isinstance(item, int) and not isinstance(item, bool) and item >= 1
        )

    def _coerce_bool(raw_value: Any) -> bool | None:
        if isinstance(raw_value, bool):
            return raw_value
        return None

    def _coerce_string(raw_value: Any) -> str | None:
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
        return None

    deterministic_seed_policy = None
    raw_seed_policy = value.get("deterministic_seed_policy")
    if isinstance(raw_seed_policy, str) and raw_seed_policy.strip():
        deterministic_seed_policy = raw_seed_policy.strip()

    purity_value = value.get("purity")
    purity: PluginPurityContract | None = None
    if isinstance(purity_value, dict):
        purity = PluginPurityContract(
            audio_buffer=(
                purity_value.get("audio_buffer").strip()
                if isinstance(purity_value.get("audio_buffer"), str)
                and purity_value.get("audio_buffer").strip()
                else None
            ),
            randomness=(
                purity_value.get("randomness").strip()
                if isinstance(purity_value.get("randomness"), str)
                and purity_value.get("randomness").strip()
                else None
            ),
            wall_clock=(
                purity_value.get("wall_clock").strip()
                if isinstance(purity_value.get("wall_clock"), str)
                and purity_value.get("wall_clock").strip()
                else None
            ),
            thread_scheduling=(
                purity_value.get("thread_scheduling").strip()
                if isinstance(purity_value.get("thread_scheduling"), str)
                and purity_value.get("thread_scheduling").strip()
                else None
            ),
        )

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
        channel_mode=_coerce_string(value.get("channel_mode")),
        supported_group_sizes=_coerce_int_tuple(value.get("supported_group_sizes")),
        supported_link_groups=_coerce_string_tuple(value.get("supported_link_groups")),
        bed_only=_coerce_bool(value.get("bed_only")),
        requires_speaker_positions=_coerce_bool(value.get("requires_speaker_positions")),
        scene_scope=_coerce_string(value.get("scene_scope")),
        layout_safety=_coerce_string(value.get("layout_safety")),
        deterministic_seed_policy=deterministic_seed_policy,
        purity=purity,
        supported_layout_ids=supported_layout_ids,
        supported_contexts=supported_contexts,
        scene=scene,
        notes=notes,
    )


def _coerce_plugin_declares(value: Any) -> PluginDeclares | None:
    if not isinstance(value, dict):
        return None

    def _coerce_string_tuple(raw_value: Any) -> tuple[str, ...] | None:
        if not isinstance(raw_value, list):
            return None
        return tuple(item for item in raw_value if isinstance(item, str) and item.strip())

    return PluginDeclares(
        problem_domains=_coerce_string_tuple(value.get("problem_domains")),
        emits_issue_ids=_coerce_string_tuple(value.get("emits_issue_ids")),
        consumes_issue_ids=_coerce_string_tuple(value.get("consumes_issue_ids")),
        suggests_action_ids=_coerce_string_tuple(value.get("suggests_action_ids")),
        related_feature_ids=_coerce_string_tuple(value.get("related_feature_ids")),
        target_scopes=_coerce_string_tuple(value.get("target_scopes")),
    )


def _coerce_plugin_behavior_contract(value: Any) -> PluginBehaviorContract | None:
    if not isinstance(value, dict):
        return None

    def _coerce_string(raw_value: Any) -> str | None:
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
        return None

    def _coerce_float(raw_value: Any) -> float | None:
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            return float(raw_value)
        return None

    return PluginBehaviorContract(
        loudness_behavior=_coerce_string(value.get("loudness_behavior")),
        max_integrated_lufs_delta=_coerce_float(value.get("max_integrated_lufs_delta")),
        peak_behavior=_coerce_string(value.get("peak_behavior")),
        max_true_peak_delta_db=_coerce_float(value.get("max_true_peak_delta_db")),
        phase_behavior=_coerce_string(value.get("phase_behavior")),
        stereo_image_behavior=_coerce_string(value.get("stereo_image_behavior")),
        gain_compensation=_coerce_string(value.get("gain_compensation")),
        rationale=_coerce_string(value.get("rationale")),
    )


def _load_plugins_from_dir(plugins_dir: Path) -> List[PluginEntry]:
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
        declares = _coerce_plugin_declares(data.get("declares"))
        behavior_contract = _coerce_plugin_behavior_contract(data.get("behavior_contract"))
        instance = _load_entrypoint(entrypoint)
        if capabilities is not None:
            try:
                setattr(instance, "plugin_capabilities", capabilities)
            except Exception:
                pass
        if declares is not None:
            try:
                setattr(instance, "plugin_declares", declares)
            except Exception:
                pass
        if behavior_contract is not None:
            try:
                setattr(instance, "plugin_behavior_contract", behavior_contract)
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
                declares=declares,
                behavior_contract=behavior_contract,
            )
        )
    entries.sort(key=lambda entry: entry.plugin_id)
    return entries


def load_plugins(
    plugins_dir: Path,
    plugin_dir: Path | None = None,
) -> List[PluginEntry]:
    """Load plugins from the primary and external plugin roots."""
    from mmo.core.plugin_loader import load_registered_plugins  # noqa: WPS433

    return load_registered_plugins(
        plugins_dir=plugins_dir,
        plugin_dir=plugin_dir,
    )


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


def _report_render_seed(report: Dict[str, Any]) -> int:
    candidates: list[Any] = [
        report.get("render_seed"),
    ]
    session = report.get("session")
    if isinstance(session, dict):
        candidates.append(session.get("render_seed"))
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        render_cfg = run_config.get("render")
        if isinstance(render_cfg, dict):
            candidates.append(render_cfg.get("render_seed"))
            candidates.append(render_cfg.get("seed"))
        candidates.append(run_config.get("render_seed"))

    for candidate in candidates:
        value = _coerce_int(candidate)
        if value is not None:
            return value
    return 0


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
        scope = normalize_recommendation_scope(rec)
        stem_id = _coerce_str(scope.get("stem_id"))
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


def _recommendation_ids(
    recommendations: Iterable[Dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    for rec in recommendations:
        rec_id = _coerce_str(rec.get("recommendation_id")).strip()
        if rec_id:
            ids.append(rec_id)
    return sorted(set(ids))


def _scene_payload_for_plugin_safety(session: Dict[str, Any]) -> Dict[str, Any] | None:
    scene_payload = session.get("scene_payload")
    if isinstance(scene_payload, dict):
        return scene_payload
    scene = session.get("scene")
    if isinstance(scene, dict):
        return scene
    return None


def _scene_stem_reference_map(scene: Dict[str, Any] | None) -> Dict[str, Dict[str, list[str]]]:
    if not isinstance(scene, dict):
        return {}

    refs: Dict[str, Dict[str, set[str]]] = {}
    objects = scene.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            stem_id = _coerce_str(obj.get("stem_id")).strip()
            if not stem_id:
                continue
            object_id = _coerce_str(obj.get("object_id")).strip()
            row = refs.setdefault(stem_id, {"objects": set(), "beds": set()})
            if object_id:
                row["objects"].add(object_id)

    beds = scene.get("beds")
    if isinstance(beds, list):
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            bed_id = _coerce_str(bed.get("bed_id")).strip()
            stem_ids = bed.get("stem_ids")
            if not isinstance(stem_ids, list):
                continue
            for raw_stem_id in stem_ids:
                stem_id = _coerce_str(raw_stem_id).strip()
                if not stem_id:
                    continue
                row = refs.setdefault(stem_id, {"objects": set(), "beds": set()})
                if bed_id:
                    row["beds"].add(bed_id)

    normalized: Dict[str, Dict[str, list[str]]] = {}
    for stem_id in sorted(refs):
        normalized[stem_id] = {
            "objects": sorted(refs[stem_id]["objects"]),
            "beds": sorted(refs[stem_id]["beds"]),
        }
    return normalized


def _stem_reference_summary(refs: Dict[str, list[str]] | None) -> str:
    if not isinstance(refs, dict):
        return "scene_unmapped"
    object_ids = refs.get("objects")
    bed_ids = refs.get("beds")
    parts: list[str] = []
    if isinstance(object_ids, list) and object_ids:
        parts.append("object:" + ",".join(object_ids))
    if isinstance(bed_ids, list) and bed_ids:
        parts.append("bed:" + ",".join(bed_ids))
    return ";".join(parts) if parts else "scene_unmapped"


def _scene_has_objects(scene_refs: Dict[str, Dict[str, list[str]]]) -> bool:
    return any(row.get("objects") for row in scene_refs.values())


def _current_target_layout_id(session: Dict[str, Any]) -> str:
    target_layout_id = _coerce_str(session.get("target_layout_id")).strip()
    if target_layout_id:
        return target_layout_id
    routing_plan = session.get("routing_plan")
    if isinstance(routing_plan, dict):
        render_targets = routing_plan.get("render_targets")
        if isinstance(render_targets, dict):
            candidate = _coerce_str(render_targets.get("layout_id")).strip()
            if candidate:
                return candidate
    return ""


def _supported_layout_ids_for_plugin(capabilities: PluginCapabilities | None) -> tuple[str, ...]:
    if capabilities is None:
        return ()
    supported_layout_ids = tuple(capabilities.supported_layout_ids or ())
    if supported_layout_ids:
        return tuple(sorted(set(supported_layout_ids)))

    scene = capabilities.scene
    target_ids = tuple(scene.supported_target_ids or ()) if scene is not None else ()
    if not target_ids:
        return ()

    try:
        from mmo.core.registries.render_targets_registry import (  # noqa: WPS433
            load_render_targets_registry,
        )

        registry = load_render_targets_registry()
    except (RuntimeError, ValueError):
        return ()

    layout_ids: set[str] = set()
    for target_id in target_ids:
        try:
            target_payload = registry.get_target(target_id)
        except ValueError:
            continue
        layout_id = _coerce_str(target_payload.get("layout_id")).strip()
        if layout_id:
            layout_ids.add(layout_id)
    return tuple(sorted(layout_ids))


def _single_instance_topology_allowed(
    capabilities: PluginCapabilities | None,
    *,
    required_channels: int,
) -> bool:
    if capabilities is None or required_channels < 1:
        return True

    channel_mode = _coerce_str(capabilities.channel_mode).strip().lower()
    supported_group_sizes = tuple(capabilities.supported_group_sizes or ())
    if channel_mode in {"linked_group", "true_multichannel"} and supported_group_sizes:
        return required_channels in supported_group_sizes
    return True


def _recommendation_scope_stem_id(rec: Mapping[str, Any]) -> str:
    scope = normalize_recommendation_scope(rec)
    return _coerce_str(scope.get("stem_id")).strip()


def _plugin_safety_skip_entry(
    *,
    recommendation_id: str,
    action_id: str,
    reason: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "recommendation_id": recommendation_id,
        "action_id": action_id,
        "reason": reason,
        "gate_summary": "",
        "details": details,
    }


def _synthetic_plugin_safety_skip_entry(
    *,
    plugin_id: str,
    reason: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    synthetic_details = dict(details)
    synthetic_details.setdefault("plugin_id", plugin_id)
    return _plugin_safety_skip_entry(
        recommendation_id=_SYSTEM_PLUGIN_SAFETY_RECOMMENDATION_ID,
        action_id=_SYSTEM_PLUGIN_SAFETY_ACTION_ID,
        reason=reason,
        details=synthetic_details,
    )


def _merge_manifest_notes(*notes: Any) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in notes:
        if not isinstance(value, str):
            continue
        for item in value.split(";"):
            token = item.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
    return ";".join(normalized)


def _apply_plugin_safety_contract(
    *,
    plugin: PluginEntry,
    eligible: list[Dict[str, Any]],
    session: Dict[str, Any],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[str], bool]:
    capabilities = plugin.capabilities
    if capabilities is None:
        return list(eligible), [], [], False

    plugin_eligible = list(eligible)
    skipped: list[Dict[str, Any]] = []
    notes: list[str] = []
    bypass = False

    scene_scope = _coerce_str(capabilities.scene_scope).strip().lower()
    if scene_scope == _SCENE_SCOPE_BED_ONLY:
        scene_refs = _scene_stem_reference_map(_scene_payload_for_plugin_safety(session))
        if scene_refs:
            scene_has_objects = _scene_has_objects(scene_refs)
            restricted: list[Dict[str, Any]] = []
            for rec in plugin_eligible:
                stem_id = _recommendation_scope_stem_id(rec)
                action_id = _coerce_str(rec.get("action_id")).strip() or _SYSTEM_PLUGIN_SAFETY_ACTION_ID
                recommendation_id = (
                    _coerce_str(rec.get("recommendation_id")).strip()
                    or _SYSTEM_PLUGIN_SAFETY_RECOMMENDATION_ID
                )
                if not stem_id:
                    if scene_has_objects:
                        skipped.append(
                            _plugin_safety_skip_entry(
                                recommendation_id=recommendation_id,
                                action_id=action_id,
                                reason="plugin_scene_scope_restricted",
                                details={
                                    "plugin_id": plugin.plugin_id,
                                    "scene_scope": _SCENE_SCOPE_BED_ONLY,
                                    "restriction": "bed_only_only",
                                    "scope": dict(normalize_recommendation_scope(rec)),
                                },
                            )
                        )
                        continue
                    restricted.append(rec)
                    continue

                refs = scene_refs.get(stem_id)
                if refs is None:
                    if scene_has_objects:
                        skipped.append(
                            _plugin_safety_skip_entry(
                                recommendation_id=recommendation_id,
                                action_id=action_id,
                                reason="plugin_scene_scope_restricted",
                                details={
                                    "plugin_id": plugin.plugin_id,
                                    "scene_scope": _SCENE_SCOPE_BED_ONLY,
                                    "restriction": "bed_only_only",
                                    "stem_id": stem_id,
                                    "scene_reference": "scene_unmapped",
                                },
                            )
                        )
                        continue
                    restricted.append(rec)
                    continue

                object_refs = refs.get("objects") or []
                bed_refs = refs.get("beds") or []
                if bed_refs and not object_refs:
                    restricted.append(rec)
                    continue

                skipped.append(
                    _plugin_safety_skip_entry(
                        recommendation_id=recommendation_id,
                        action_id=action_id,
                        reason="plugin_scene_scope_restricted",
                        details={
                            "plugin_id": plugin.plugin_id,
                            "scene_scope": _SCENE_SCOPE_BED_ONLY,
                            "restriction": "bed_only_only",
                            "stem_id": stem_id,
                            "scene_reference": _stem_reference_summary(refs),
                        },
                    )
                )

            if skipped:
                notes.append(
                    "plugin_safety_restriction:"
                    f"bed_only_kept={len(restricted)}"
                    f",bed_only_skipped={len(skipped)}"
                )
            plugin_eligible = restricted
            if scene_has_objects and not plugin_eligible:
                bypass = True
                notes.append("plugin_safety_bypass:bed_only_no_safe_recommendations")
                if not skipped:
                    skipped.append(
                        _synthetic_plugin_safety_skip_entry(
                            plugin_id=plugin.plugin_id,
                            reason="plugin_scene_scope_unsupported",
                            details={
                                "scene_scope": _SCENE_SCOPE_BED_ONLY,
                                "restriction": "bed_only_only",
                            },
                        )
                    )

    layout_safety = _coerce_str(capabilities.layout_safety).strip().lower()
    if layout_safety == _LAYOUT_SAFETY_SPECIFIC:
        target_layout_id = _current_target_layout_id(session)
        supported_layout_ids = _supported_layout_ids_for_plugin(capabilities)
        if target_layout_id:
            if supported_layout_ids and target_layout_id not in supported_layout_ids:
                bypass = True
                notes.append(
                    "plugin_safety_bypass:"
                    f"layout_unsupported={target_layout_id}"
                )
                if plugin_eligible:
                    for rec in plugin_eligible:
                        recommendation_id = (
                            _coerce_str(rec.get("recommendation_id")).strip()
                            or _SYSTEM_PLUGIN_SAFETY_RECOMMENDATION_ID
                        )
                        action_id = (
                            _coerce_str(rec.get("action_id")).strip()
                            or _SYSTEM_PLUGIN_SAFETY_ACTION_ID
                        )
                        skipped.append(
                            _plugin_safety_skip_entry(
                                recommendation_id=recommendation_id,
                                action_id=action_id,
                                reason="plugin_layout_unsupported",
                                details={
                                    "plugin_id": plugin.plugin_id,
                                    "layout_safety": _LAYOUT_SAFETY_SPECIFIC,
                                    "target_layout_id": target_layout_id,
                                    "supported_layout_ids": list(supported_layout_ids),
                                },
                            )
                        )
                else:
                    skipped.append(
                        _synthetic_plugin_safety_skip_entry(
                            plugin_id=plugin.plugin_id,
                            reason="plugin_layout_unsupported",
                            details={
                                "layout_safety": _LAYOUT_SAFETY_SPECIFIC,
                                "target_layout_id": target_layout_id,
                                "supported_layout_ids": list(supported_layout_ids),
                            },
                        )
                    )
                plugin_eligible = []
            elif not supported_layout_ids:
                bypass = True
                notes.append("plugin_safety_bypass:layout_specific_without_supported_layouts")
                skipped.append(
                    _synthetic_plugin_safety_skip_entry(
                        plugin_id=plugin.plugin_id,
                        reason="plugin_layout_support_unknown",
                        details={
                            "layout_safety": _LAYOUT_SAFETY_SPECIFIC,
                            "target_layout_id": target_layout_id,
                        },
                    )
                )
                plugin_eligible = []

    return plugin_eligible, skipped, notes, bypass


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


def _output_tag_bag(output: Dict[str, Any]) -> TagBag:
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        if {"raw", "normalized", "warnings"}.issubset(metadata.keys()):
            return tag_bag_from_mapping(metadata)
        return tag_bag_from_mapping(metadata.get("tag_bag"))
    return empty_tag_bag()


def _make_transcoded_output(
    source_output: Dict[str, Any],
    *,
    output_format: str,
    file_path: str,
    sha256: str,
    metadata_receipt: Dict[str, Any] | None = None,
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
    if isinstance(metadata_receipt, dict):
        transcoded_metadata["metadata_receipt"] = metadata_receipt
    transcoded["metadata"] = transcoded_metadata
    return transcoded


def _append_transcode_skip(
    skipped: List[Dict[str, Any]],
    output: Dict[str, Any],
    *,
    reason: str,
) -> None:
    recommendation_id = _coerce_str(output.get("recommendation_id")).strip()
    action_id = _coerce_str(output.get("action_id")).strip()
    if not recommendation_id:
        metadata = output.get("metadata")
        if isinstance(metadata, dict):
            contributing = metadata.get("contributing_recommendation_ids")
            if isinstance(contributing, list):
                for item in contributing:
                    candidate = _coerce_str(item).strip()
                    if candidate:
                        recommendation_id = candidate
                        break
    if not recommendation_id:
        recommendation_id = _SYSTEM_TRANSCODE_RECOMMENDATION_ID
    if not action_id:
        action_id = _SYSTEM_TRANSCODE_ACTION_ID

    skipped.append(
        {
            "recommendation_id": recommendation_id,
            "action_id": action_id,
            "reason": reason,
            "gate_summary": "",
        }
    )


def _output_channel_order(output: Dict[str, Any]) -> list[str]:
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        channel_order = metadata.get("channel_order")
        if isinstance(channel_order, list):
            normalized = [
                item.strip()
                for item in channel_order
                if isinstance(item, str) and item.strip()
            ]
            if normalized:
                return normalized

    layout_id = _coerce_str(output.get("layout_id")).strip()
    if not layout_id and isinstance(metadata, dict):
        layout_id = _coerce_str(metadata.get("layout_id")).strip()
    if not layout_id:
        return []

    resolved = get_layout_channel_order(layout_id)
    if not isinstance(resolved, list):
        return []
    return [
        item.strip()
        for item in resolved
        if isinstance(item, str) and item.strip()
    ]


def _output_ffmpeg_layout_string(output: Dict[str, Any]) -> str | None:
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        raw_layout = _coerce_str(metadata.get("ffmpeg_channel_layout")).strip()
        if raw_layout:
            return raw_layout
    return ffmpeg_layout_string_from_channel_order(_output_channel_order(output))


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
    supports_lfe2_layout = (
        ffmpeg_supports_lfe2_layout_strings(ffmpeg_cmd)
        if ffmpeg_cmd is not None
        else False
    )

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

            source_tag_bag = _output_tag_bag(output)
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
                channel_layout = _output_ffmpeg_layout_string(output)
                if channel_layout and "LFE2" in channel_layout and not supports_lfe2_layout:
                    channel_layout = None
                (
                    metadata_args,
                    embedded_keys,
                    skipped_keys,
                    metadata_warnings,
                ) = build_ffmpeg_tag_export_args(source_tag_bag, target_format)
                metadata_receipt = metadata_receipt_mapping(
                    output_container_format_id=target_format,
                    embedded_keys=embedded_keys,
                    skipped_keys=skipped_keys,
                    warnings=metadata_warnings,
                )
                try:
                    transcode_wav_to_format(
                        ffmpeg_cmd,
                        source_path,
                        target_path,
                        target_format,
                        channel_layout=channel_layout,
                        metadata_args=metadata_args,
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
                        metadata_receipt=metadata_receipt,
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
    return _build_deliverables_from_renderer_manifests(renderer_manifests)


def _issue_identity_key(issue: Mapping[str, Any]) -> tuple[Any, ...]:
    target = issue.get("target")
    target_mapping = target if isinstance(target, Mapping) else {}
    return (
        _coerce_str(issue.get("issue_id")),
        _coerce_str(target_mapping.get("scope")),
        _coerce_str(target_mapping.get("stem_id")),
        _coerce_str(target_mapping.get("bus_id")),
        _coerce_str(target_mapping.get("layout_id")),
        _coerce_str(target_mapping.get("speaker_id")),
        _coerce_int(target_mapping.get("channel_index")),
    )


def _dedupe_issues(issues: Sequence[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_key = _issue_identity_key(issue)
        if issue_key in seen:
            continue
        seen.add(issue_key)
        deduped.append(issue)
    return deduped


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
    session_report["issues"] = _dedupe_issues(issues)


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
            recommendations.extend(
                normalize_recommendation_contract(rec)
                for rec in plugin_recs
                if isinstance(rec, dict)
            )
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
    session_for_plugins = dict(session)
    report_id = _coerce_str(report.get("report_id")) if isinstance(report, dict) else ""
    if report_id and "report_id" not in session_for_plugins:
        session_for_plugins["report_id"] = report_id
    if "render_seed" not in session_for_plugins:
        session_for_plugins["render_seed"] = _report_render_seed(report)
    scene_locks_payload = session_for_plugins.get("scene_locks_payload")
    normalized_scene_locks_payload = (
        scene_locks_payload if isinstance(scene_locks_payload, dict) else None
    )
    for scene_key in ("scene_payload", "scene"):
        payload = session_for_plugins.get(scene_key)
        if not isinstance(payload, dict):
            continue
        should_reapply = normalized_scene_locks_payload is not None
        if not should_reapply and has_precedence_receipt(payload):
            continue
        session_for_plugins[scene_key] = apply_precedence(
            payload,
            normalized_scene_locks_payload,
            None,
        )
    session_for_plugins["stems"] = resolve_session_stems(
        session_for_plugins,
        mutate=False,
    )
    routing_plan = report.get("routing_plan") if isinstance(report, dict) else None
    if isinstance(routing_plan, dict):
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
    desired_formats = _normalize_output_formats(output_formats)
    needs_encode = any(fmt != "wav" for fmt in desired_formats)
    ffmpeg_cmd = resolve_ffmpeg_cmd() if needs_encode else None

    manifests: List[Dict[str, Any]] = []
    non_baseline_outputs_written = False
    for plugin in plugins:
        if plugin.plugin_type != "renderer":
            continue

        eligible_for_plugin, plugin_safety_skipped, plugin_safety_notes, plugin_bypassed = (
            _apply_plugin_safety_contract(
                plugin=plugin,
                eligible=eligible,
                session=session_for_plugins,
            )
        )
        plugin_required_channels = _required_channels_for_recommendations(
            session,
            eligible_for_plugin,
        )

        if (
            plugin.plugin_id == _BASELINE_RENDERER_ID
            and eligible_for_plugin
            and non_baseline_outputs_written
        ):
            manifests.append(
                {
                    "renderer_id": plugin.plugin_id,
                    "outputs": [],
                    "received_recommendation_ids": sorted(
                        {
                            rec_id
                            for rec in eligible_for_plugin
                            for rec_id in [_coerce_str(rec.get("recommendation_id"))]
                            if rec_id
                        }
                    ),
                    "notes": _merge_manifest_notes(
                        "skipped_baseline_due_eligible_recommendations",
                        *plugin_safety_notes,
                    ),
                    "skipped": _merge_skipped_entries(
                        blocked_skipped,
                        plugin_safety_skipped,
                    ),
                }
            )
            continue

        plugin_max_channels = None
        if plugin.capabilities is not None:
            plugin_max_channels = plugin.capabilities.max_channels
        if (
            isinstance(plugin_max_channels, int)
            and not isinstance(plugin_max_channels, bool)
            and plugin_max_channels >= 1
            and plugin_required_channels > plugin_max_channels
        ):
            channel_limit_skipped = [
                {
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "plugin_channel_limit",
                    "gate_summary": "",
                    "details": {
                        "plugin_id": plugin.plugin_id,
                        "required_channels": plugin_required_channels,
                        "max_channels": plugin_max_channels,
                    },
                }
                for rec in eligible_for_plugin
            ]
            manifests.append(
                {
                    "renderer_id": plugin.plugin_id,
                    "outputs": [],
                    "notes": _merge_manifest_notes(*plugin_safety_notes),
                    "skipped": _merge_skipped_entries(
                        blocked_skipped,
                        plugin_safety_skipped,
                        channel_limit_skipped,
                    ),
                }
            )
            continue

        if not _single_instance_topology_allowed(
            plugin.capabilities,
            required_channels=plugin_required_channels,
        ):
            supported_group_sizes = (
                list(plugin.capabilities.supported_group_sizes)
                if plugin.capabilities is not None
                and plugin.capabilities.supported_group_sizes is not None
                else []
            )
            topology_skipped = [
                {
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "plugin_topology_unsupported",
                    "gate_summary": "",
                    "details": {
                        "plugin_id": plugin.plugin_id,
                        "required_channels": plugin_required_channels,
                        "channel_mode": (
                            plugin.capabilities.channel_mode
                            if plugin.capabilities is not None
                            else None
                        ),
                        "supported_group_sizes": supported_group_sizes,
                    },
                }
                for rec in eligible_for_plugin
            ]
            manifests.append(
                {
                    "renderer_id": plugin.plugin_id,
                    "outputs": [],
                    "notes": _merge_manifest_notes(*plugin_safety_notes),
                    "skipped": _merge_skipped_entries(
                        blocked_skipped,
                        plugin_safety_skipped,
                        topology_skipped,
                    ),
                }
            )
            continue

        if plugin_bypassed:
            manifests.append(
                {
                    "renderer_id": plugin.plugin_id,
                    "outputs": [],
                    "notes": _merge_manifest_notes(*plugin_safety_notes),
                    "skipped": _merge_skipped_entries(
                        blocked_skipped,
                        plugin_safety_skipped,
                    ),
                }
            )
            continue

        manifest = _call_renderer(
            plugin.instance,
            session_for_plugins,
            eligible_for_plugin,
            output_dir,
        )
        if not isinstance(manifest, dict):
            manifest = {
                "renderer_id": plugin.plugin_id,
                "outputs": [],
                "notes": "Renderer returned non-dict manifest.",
            }
        if "renderer_id" not in manifest:
            manifest["renderer_id"] = plugin.plugin_id
        manifest["received_recommendation_ids"] = _recommendation_ids(eligible_for_plugin)
        manifest["notes"] = _merge_manifest_notes(
            _coerce_str(manifest.get("notes")),
            *plugin_safety_notes,
        )
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
            plugin_safety_skipped,
            plugin_skipped,
            transcode_skipped,
        )
        manifests.append(manifest)

        if plugin.plugin_id != _BASELINE_RENDERER_ID:
            manifest_outputs = manifest.get("outputs")
            if isinstance(manifest_outputs, list) and any(
                isinstance(output, dict) for output in manifest_outputs
            ):
                non_baseline_outputs_written = True

    # If baseline ran before other output-producing renderers, suppress its
    # outputs to avoid duplicate deliverables in recommendation-driven runs.
    if eligible:
        has_non_baseline_outputs = any(
            isinstance(manifest, dict)
            and _coerce_str(manifest.get("renderer_id")) != _BASELINE_RENDERER_ID
            and isinstance(manifest.get("outputs"), list)
            and any(isinstance(output, dict) for output in manifest.get("outputs", []))
            for manifest in manifests
        )
        if has_non_baseline_outputs:
            for manifest in manifests:
                if not isinstance(manifest, dict):
                    continue
                if _coerce_str(manifest.get("renderer_id")) != _BASELINE_RENDERER_ID:
                    continue
                manifest_outputs = manifest.get("outputs")
                if not isinstance(manifest_outputs, list):
                    continue
                if not any(isinstance(output, dict) for output in manifest_outputs):
                    continue
                manifest["outputs"] = []
                existing_notes = _coerce_str(manifest.get("notes")).strip()
                baseline_note = "skipped_baseline_due_eligible_recommendations"
                if not existing_notes:
                    manifest["notes"] = baseline_note
                elif baseline_note not in existing_notes:
                    manifest["notes"] = f"{existing_notes};{baseline_note}"

    return manifests
