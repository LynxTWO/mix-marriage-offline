from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from mmo.core.cache_keys import cache_key, hash_lockfile, hash_run_config
from mmo.core.cache_store import (
    report_has_time_cap_stop_condition,
    report_schema_is_valid,
    rewrite_report_stems_dir,
    save_cached_report,
    try_load_cached_report,
)
from mmo.core.compare import (
    build_compare_report,
    default_label_for_compare_input,
    load_report_from_path_or_dir,
)
from mmo.core.deliverables_index import (
    build_deliverables_index_single,
    build_deliverables_index_variants,
)
from mmo.core.presets import (
    list_preset_packs,
    list_presets,
    load_preset_pack,
    load_preset_run_config,
)
from mmo.core.render_plan import build_render_plan
from mmo.core.render_plan_bridge import render_plan_to_variant_plan
from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    resolve_render_target_id,
)
from mmo.core.role_lexicon import load_role_lexicon
from mmo.core.roles import list_roles, load_roles, resolve_role
from mmo.core.stems_classifier import classify_stems, classify_stems_with_evidence
from mmo.core.translation_profiles import (
    get_translation_profile,
    list_translation_profiles,
    load_translation_profiles,
)
from mmo.core.translation_summary import build_translation_summary
from mmo.core.translation_checks import run_translation_checks
from mmo.core.translation_audition import render_translation_auditions
from mmo.core.translation_reference import (
    TranslationReferenceResolutionError,
    resolve_translation_reference_audio,
)
from mmo.core.target_recommendations import recommend_render_targets
from mmo.core.scene_templates import (
    apply_scene_templates,
    get_scene_template,
    list_scene_templates,
    preview_scene_templates,
)
from mmo.core.scene_locks import get_scene_lock, list_scene_locks
from mmo.core.intent_params import load_intent_params, validate_scene_intent
from mmo.core.stems_index import build_stems_index, resolve_stem_sets
from mmo.core.stems_overrides import apply_overrides, load_stems_overrides
from mmo.core.scene_editor import (
    INTENT_PARAM_KEY_TO_ID,
    add_lock as edit_scene_add_lock,
    remove_lock as edit_scene_remove_lock,
    set_intent as edit_scene_set_intent,
)
from mmo.core.listen_pack import build_listen_pack
from mmo.core.project_file import (
    load_project,
    new_project,
    update_project_last_run,
    write_project,
)
from mmo.core.gui_state import default_gui_state, validate_gui_state
from mmo.core.routing import (
    apply_routing_plan_to_report,
    build_routing_plan,
    render_routing_plan,
    routing_layout_ids_from_run_config,
)
from mmo.core.run_config import (
    RUN_CONFIG_SCHEMA_VERSION,
    diff_run_config,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.timeline import load_timeline
from mmo.core.variants import build_variant_plan, run_variant_plan
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS
from mmo.ui.tui import choose_from_list, multi_toggle, render_header, yes_no

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

_PRESET_PREVIEW_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_PRESET_PREVIEW_DEFAULT_METERS = "truth"
_PRESET_PREVIEW_DEFAULT_MAX_SECONDS = 120.0
_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID = "LAYOUT.2_0"
_BASELINE_RENDER_TARGET_ID = "TARGET.STEREO.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_FORMAT_SET_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_RUN_COMMAND_EPILOG = (
    "One button for musicians: analyze your stems, then optionally export notes, "
    "apply safe fixes, render lossless files, and build a UI bundle in one pass."
)
_UI_OVERLAY_CHIPS: tuple[str, ...] = (
    "Warm",
    "Air",
    "Punch",
    "Glue",
    "Wide",
    "Safe",
    "Live",
    "Vocal",
)
_SCENE_INTENT_KEYS: tuple[str, ...] = (
    "width",
    "depth",
    "azimuth_deg",
    "loudness_bias",
    "confidence",
)
_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS: tuple[str, ...] = (
    "TRANS.MONO.COLLAPSE",
    "TRANS.DEVICE.PHONE",
    "TRANS.DEVICE.SMALL_SPEAKER",
)
_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S = 30.0


def _run_command(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _run_scan(
    tools_dir: Path,
    stems_dir: Path,
    out_path: Path,
    meters: str | None,
    include_peak: bool,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "scan_session.py"),
        str(stems_dir),
        "--out",
        str(out_path),
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    return _run_command(command)


def _run_analyze(
    tools_dir: Path,
    stems_dir: Path,
    out_report: Path,
    meters: str | None,
    include_peak: bool,
    plugins_dir: str,
    keep_scan: bool,
    profile_id: str,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "analyze_stems.py"),
        str(stems_dir),
        "--out-report",
        str(out_report),
        "--plugins",
        plugins_dir,
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    if keep_scan:
        command.append("--keep-scan")
    if profile_id:
        command.extend(["--profile", profile_id])
    return _run_command(command)


def _run_export(
    tools_dir: Path,
    report_path: Path,
    csv_path: str | None,
    pdf_path: str | None,
    *,
    no_measurements: bool,
    no_gates: bool,
    truncate_values: int,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "export_report.py"),
        "--report",
        str(report_path),
    ]
    if csv_path:
        command.extend(["--csv", csv_path])
    if pdf_path:
        command.extend(["--pdf", pdf_path])
    if no_measurements:
        command.append("--no-measurements")
    if no_gates:
        command.append("--no-gates")
    if truncate_values != 200:
        command.extend(["--truncate-values", str(truncate_values)])
    if len(command) == 4:
        return 0
    return _run_command(command)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return data


def _load_report(report_path: Path) -> dict[str, Any]:
    return _load_json_object(report_path, label="Report")


def _load_timeline_payload(timeline_path: Path | None) -> dict[str, Any] | None:
    if timeline_path is None:
        return None
    return load_timeline(timeline_path)


def _render_timeline_text(timeline: dict[str, Any]) -> str:
    lines = [f"schema_version: {timeline.get('schema_version', '')}", "sections:"]
    raw_sections = timeline.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        lines.append("- (none)")
        return "\n".join(lines)

    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id", "")
        label = section.get("label", "")
        start_s = section.get("start_s", "")
        end_s = section.get("end_s", "")
        lines.append(f"- {section_id}  {label}  {start_s}..{end_s}")
    return "\n".join(lines)


def _render_scene_text(scene: dict[str, Any]) -> str:
    source = scene.get("source")
    source_payload = source if isinstance(source, dict) else {}
    lines = [
        f"schema_version: {scene.get('schema_version', '')}",
        f"scene_id: {scene.get('scene_id', '')}",
        f"created_from: {source_payload.get('created_from', '')}",
        f"stems_dir: {source_payload.get('stems_dir', '')}",
    ]

    objects = scene.get("objects")
    object_count = len(objects) if isinstance(objects, list) else 0
    beds = scene.get("beds")
    bed_count = len(beds) if isinstance(beds, list) else 0
    lines.append(f"objects: {object_count}")
    lines.append(f"beds: {bed_count}")
    return "\n".join(lines)


def _render_render_plan_text(render_plan: dict[str, Any]) -> str:
    lines = [
        f"schema_version: {render_plan.get('schema_version', '')}",
        f"plan_id: {render_plan.get('plan_id', '')}",
        f"scene_path: {render_plan.get('scene_path', '')}",
    ]
    targets = render_plan.get("targets")
    target_count = len(targets) if isinstance(targets, list) else 0
    jobs = render_plan.get("jobs")
    job_count = len(jobs) if isinstance(jobs, list) else 0
    lines.append(f"targets: {target_count}")
    lines.append(f"jobs: {job_count}")
    return "\n".join(lines)


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - environment issue
        raise ValueError(
            "jsonschema referencing support is unavailable; cannot validate schema refs."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = _load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _flag_present(raw_argv: list[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in raw_argv)


def _set_nested(path: list[str], payload: dict[str, Any], value: Any) -> None:
    target = payload
    for part in path[:-1]:
        existing = target.get(part)
        if not isinstance(existing, dict):
            existing = {}
            target[part] = existing
        target = existing
    target[path[-1]] = value


def _rel_path_if_under_root(root_dir: Path, target_path: Path) -> str | None:
    resolved_root = root_dir.resolve()
    resolved_target = target_path.resolve()
    try:
        rel_path = resolved_target.relative_to(resolved_root)
    except ValueError:
        return None
    return rel_path.as_posix()


def _load_and_merge_run_config(
    config_path: str | None,
    cli_overrides: dict[str, Any],
    *,
    preset_id: str | None = None,
    presets_dir: Path | None = None,
) -> dict[str, Any]:
    merged_cfg: dict[str, Any] = {}
    if preset_id:
        if presets_dir is None:
            raise ValueError("presets_dir is required when preset_id is provided.")
        preset_cfg = load_preset_run_config(presets_dir, preset_id)
        merged_cfg = merge_run_config(merged_cfg, preset_cfg)
    if config_path:
        file_cfg = load_run_config(Path(config_path))
        merged_cfg = merge_run_config(merged_cfg, file_cfg)
    merged_cfg = merge_run_config(merged_cfg, cli_overrides)
    if preset_id:
        merged_cfg["preset_id"] = preset_id.strip()
        return normalize_run_config(merged_cfg)
    return merged_cfg


def _config_string(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key)
    if isinstance(value, str) and value:
        return value
    return default


def _config_optional_string(
    config: dict[str, Any],
    key: str,
    default: str | None,
) -> str | None:
    value = config.get(key)
    if isinstance(value, str):
        return value
    return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    value = config.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _config_nested_optional_string(
    config: dict[str, Any],
    section: str,
    key: str,
    default: str | None,
) -> str | None:
    section_data = config.get(section)
    if isinstance(section_data, dict):
        value = section_data.get(key)
        if isinstance(value, str):
            return value
    return default


def _parse_output_formats_csv(raw_value: str) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("output formats must be a comma-separated string.")

    selected: set[str] = set()
    for item in raw_value.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if normalized not in _OUTPUT_FORMAT_ORDER:
            allowed = ",".join(_OUTPUT_FORMAT_ORDER)
            raise ValueError(
                f"Unsupported output format {normalized!r}. Allowed: {allowed}."
            )
        selected.add(normalized)

    if not selected:
        raise ValueError("output formats must include at least one value.")

    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _parse_output_format_set(raw_value: str) -> tuple[str, list[str]]:
    if not isinstance(raw_value, str):
        raise ValueError("format-set must use <name>:<csv> syntax.")

    name_raw, separator, formats_raw = raw_value.partition(":")
    if separator != ":":
        raise ValueError("format-set must use <name>:<csv> syntax.")

    name = name_raw.strip().lower()
    if not name:
        raise ValueError("format-set name is required.")
    if _FORMAT_SET_NAME_RE.fullmatch(name) is None:
        raise ValueError("format-set name must match ^[a-z0-9_]+$.")

    return (name, _parse_output_formats_csv(formats_raw))


def _parse_output_format_sets(values: list[str]) -> list[tuple[str, list[str]]]:
    normalized: list[tuple[str, list[str]]] = []
    seen_names: set[str] = set()
    for raw in values:
        name, output_formats = _parse_output_format_set(raw)
        if name in seen_names:
            raise ValueError(f"Duplicate format-set name {name!r}.")
        seen_names.add(name)
        normalized.append((name, output_formats))
    return normalized


def _config_nested_output_formats(
    config: dict[str, Any],
    section: str,
    default: list[str] | None = None,
) -> list[str]:
    fallback = list(default) if isinstance(default, list) and default else ["wav"]
    section_data = config.get(section)
    if not isinstance(section_data, dict):
        return fallback
    value = section_data.get("output_formats")
    if not isinstance(value, list):
        return fallback
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            normalized.append(item)
    if not normalized:
        return fallback
    return normalized


def _stamp_report_run_config(report_path: Path, run_config: dict[str, Any]) -> None:
    report = _load_report(report_path)
    normalized_run_config = normalize_run_config(run_config)
    report["run_config"] = normalized_run_config
    apply_routing_plan_to_report(report, normalized_run_config)
    _write_json_file(report_path, report)


def _analyze_run_config(
    *,
    profile_id: str,
    meters: str | None,
    preset_id: str | None = None,
    base_run_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(base_run_config or {})
    payload["schema_version"] = RUN_CONFIG_SCHEMA_VERSION
    payload["profile_id"] = profile_id
    if meters is not None:
        payload["meters"] = meters
    if preset_id is not None:
        payload["preset_id"] = preset_id
    return normalize_run_config(payload)


def _downmix_qa_run_config(
    *,
    profile_id: str,
    meters: str,
    max_seconds: float,
    truncate_values: int,
    source_layout_id: str,
    target_layout_id: str,
    policy_id: str | None,
    preset_id: str | None = None,
    base_run_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(base_run_config or {})
    downmix_payload: dict[str, Any] = {
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
    }
    if policy_id is not None:
        downmix_payload["policy_id"] = policy_id
    payload["schema_version"] = RUN_CONFIG_SCHEMA_VERSION
    payload["profile_id"] = profile_id
    payload["meters"] = meters
    payload["max_seconds"] = max_seconds
    payload["truncate_values"] = truncate_values
    payload["downmix"] = downmix_payload
    if preset_id is not None:
        payload["preset_id"] = preset_id
    return normalize_run_config(payload)


def _analysis_cache_key(lock: dict[str, Any], cfg: dict[str, Any]) -> str:
    lock_hash = hash_lockfile(lock)
    cfg_hash = hash_run_config(cfg)
    return cache_key(lock_hash, cfg_hash)


def _analysis_run_config_for_variant_cache(run_config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_run_config(run_config)
    analysis_cfg = json.loads(json.dumps(normalized))

    render_cfg = analysis_cfg.get("render")
    if isinstance(render_cfg, dict):
        render_cfg = dict(render_cfg)
        render_cfg.pop("out_dir", None)
        render_cfg.pop("output_formats", None)
        if render_cfg:
            analysis_cfg["render"] = render_cfg
        else:
            analysis_cfg.pop("render", None)
    else:
        analysis_cfg.pop("render", None)

    apply_cfg = analysis_cfg.get("apply")
    if isinstance(apply_cfg, dict):
        apply_cfg = dict(apply_cfg)
        apply_cfg.pop("output_formats", None)
        if apply_cfg:
            analysis_cfg["apply"] = apply_cfg
        else:
            analysis_cfg.pop("apply", None)
    else:
        analysis_cfg.pop("apply", None)

    downmix_cfg = analysis_cfg.get("downmix")
    if isinstance(downmix_cfg, dict):
        downmix_cfg = dict(downmix_cfg)
        downmix_cfg.pop("source_layout_id", None)
        downmix_cfg.pop("target_layout_id", None)
        if downmix_cfg:
            analysis_cfg["downmix"] = downmix_cfg
        else:
            analysis_cfg.pop("downmix", None)
    else:
        analysis_cfg.pop("downmix", None)

    return normalize_run_config(analysis_cfg)


def _should_skip_analysis_cache_save(report: dict[str, Any], run_config: dict[str, Any]) -> bool:
    meters = run_config.get("meters")
    if meters != "truth":
        return False
    return report_has_time_cap_stop_condition(report)


def _validate_json_payload(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        print(
            f"jsonschema is not installed; cannot validate {payload_name}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        schema = _load_json_schema(schema_path)
        registry = _build_schema_registry(schema_path.parent)
    except ValueError as exc:
        print(
            str(exc),
            file=sys.stderr,
        )
        raise SystemExit(1)

    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    print(f"{payload_name} schema validation failed:", file=sys.stderr)
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        print(f"- {path}: {err.message}", file=sys.stderr)
    raise SystemExit(1)


def _validate_render_manifest(render_manifest: dict[str, Any], schema_path: Path) -> None:
    _validate_json_payload(
        render_manifest,
        schema_path=schema_path,
        payload_name="Render manifest",
    )


def _validate_apply_manifest(apply_manifest: dict[str, Any], schema_path: Path) -> None:
    _validate_json_payload(
        apply_manifest,
        schema_path=schema_path,
        payload_name="Apply manifest",
    )


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _collect_stem_artifacts(
    renderer_manifests: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    selected: dict[str, tuple[tuple[str, str, str, str], dict[str, str]]] = {}
    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        renderer_id = _coerce_str(manifest.get("renderer_id"))
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            stem_id = _coerce_str(output.get("target_stem_id"))
            file_path = _coerce_str(output.get("file_path"))
            sha256 = _coerce_str(output.get("sha256"))
            if not stem_id or not file_path or not sha256:
                continue
            sort_key = (
                renderer_id,
                _coerce_str(output.get("output_id")),
                file_path,
                sha256,
            )
            artifact = {"file_path": file_path, "sha256": sha256}
            existing = selected.get(stem_id)
            if existing is None or sort_key < existing[0]:
                selected[stem_id] = (sort_key, artifact)
    return {
        stem_id: payload[1]
        for stem_id, payload in sorted(selected.items(), key=lambda item: item[0])
    }


def _build_applied_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    renderer_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    applied_report = json.loads(json.dumps(report))
    session = applied_report.get("session")
    if not isinstance(session, dict):
        session = {}
        applied_report["session"] = session
    session["stems_dir"] = out_dir.resolve().as_posix()

    stems = session.get("stems")
    if not isinstance(stems, list):
        return applied_report

    artifacts = _collect_stem_artifacts(renderer_manifests)
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if not stem_id:
            continue
        artifact = artifacts.get(stem_id)
        if artifact is None:
            continue
        stem["file_path"] = artifact["file_path"]
        stem["sha256"] = artifact["sha256"]
    return applied_report


def _run_render_command(
    *,
    repo_root: Path,
    report_path: Path,
    plugins_dir: Path,
    out_manifest_path: Path,
    out_dir: Path | None,
    profile_id: str,
    command_label: str,
    output_formats: list[str] | None = None,
    run_config: dict[str, Any] | None = None,
) -> int:
    from mmo.core.gates import apply_gates_to_report  # noqa: WPS433
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_renderers,
    )

    report = _load_report(report_path)
    if run_config is not None:
        normalized_run_config = normalize_run_config(run_config)
        report["run_config"] = normalized_run_config
        if routing_layout_ids_from_run_config(normalized_run_config) is not None:
            apply_routing_plan_to_report(report, normalized_run_config)
    apply_gates_to_report(
        report,
        policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
    )

    recommendations = report.get("recommendations")
    recs: list[dict[str, Any]] = []
    if isinstance(recommendations, list):
        recs = [rec for rec in recommendations if isinstance(rec, dict)]

    eligible = [rec for rec in recs if rec.get("eligible_render") is True]
    blocked = [rec for rec in recs if rec.get("eligible_render") is not True]
    print(
        f"{command_label}:"
        f" total_recommendations={len(recs)}"
        f" eligible_render={len(eligible)}"
        f" blocked={len(blocked)}",
        file=sys.stderr,
    )

    plugins = load_plugins(plugins_dir)
    renderer_plugin_ids = [
        plugin.plugin_id for plugin in plugins if plugin.plugin_type == "renderer"
    ]
    renderer_ids_text = ",".join(renderer_plugin_ids) if renderer_plugin_ids else "<none>"
    print(
        f"{command_label}: renderer_plugin_ids={renderer_ids_text}",
        file=sys.stderr,
    )

    manifests = run_renderers(
        report,
        plugins,
        output_dir=out_dir,
        output_formats=output_formats,
    )
    deliverables = build_deliverables_for_renderer_manifests(manifests)
    render_manifest = {
        "schema_version": "0.1.0",
        "report_id": report.get("report_id", ""),
        "renderer_manifests": manifests,
    }
    if deliverables:
        render_manifest["deliverables"] = deliverables
    _validate_render_manifest(
        render_manifest,
        repo_root / "schemas" / "render_manifest.schema.json",
    )

    out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_manifest_path.write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _run_downmix_render(
    *,
    repo_root: Path,
    report_path: Path,
    plugins_dir: Path,
    out_manifest_path: Path,
    out_dir: Path | None,
    profile_id: str,
) -> int:
    return _run_render_command(
        repo_root=repo_root,
        report_path=report_path,
        plugins_dir=plugins_dir,
        out_manifest_path=out_manifest_path,
        out_dir=out_dir,
        profile_id=profile_id,
        command_label="downmix render",
    )


def _run_apply_command(
    *,
    repo_root: Path,
    report_path: Path,
    plugins_dir: Path,
    out_manifest_path: Path,
    out_dir: Path,
    out_report_path: Path | None,
    profile_id: str,
    output_formats: list[str] | None = None,
    run_config: dict[str, Any] | None = None,
) -> int:
    from mmo.core.gates import apply_gates_to_report  # noqa: WPS433
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_renderers,
    )

    report = _load_report(report_path)
    if run_config is not None:
        normalized_run_config = normalize_run_config(run_config)
        report["run_config"] = normalized_run_config
        if routing_layout_ids_from_run_config(normalized_run_config) is not None:
            apply_routing_plan_to_report(report, normalized_run_config)
    apply_gates_to_report(
        report,
        policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
    )

    recommendations = report.get("recommendations")
    recs: list[dict[str, Any]] = []
    if isinstance(recommendations, list):
        recs = [rec for rec in recommendations if isinstance(rec, dict)]

    eligible = [rec for rec in recs if rec.get("eligible_auto_apply") is True]
    blocked = [rec for rec in recs if rec.get("eligible_auto_apply") is not True]
    print(
        "apply:"
        f" total_recommendations={len(recs)}"
        f" eligible_auto_apply={len(eligible)}"
        f" blocked={len(blocked)}",
        file=sys.stderr,
    )

    plugins = load_plugins(plugins_dir)
    renderer_plugin_ids = [
        plugin.plugin_id for plugin in plugins if plugin.plugin_type == "renderer"
    ]
    renderer_ids_text = ",".join(renderer_plugin_ids) if renderer_plugin_ids else "<none>"
    print(
        f"apply: renderer_plugin_ids={renderer_ids_text}",
        file=sys.stderr,
    )

    renderer_manifests = run_renderers(
        report,
        plugins,
        output_dir=out_dir,
        eligibility_field="eligible_auto_apply",
        context="auto_apply",
        output_formats=output_formats,
    )
    deliverables = build_deliverables_for_renderer_manifests(renderer_manifests)
    apply_manifest = {
        "schema_version": "0.1.0",
        "context": "auto_apply",
        "report_id": report.get("report_id", ""),
        "renderer_manifests": renderer_manifests,
    }
    if deliverables:
        apply_manifest["deliverables"] = deliverables
    _validate_apply_manifest(
        apply_manifest,
        repo_root / "schemas" / "apply_manifest.schema.json",
    )

    out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_manifest_path.write_text(
        json.dumps(apply_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if out_report_path is not None:
        applied_report = _build_applied_report(
            report,
            out_dir=out_dir,
            renderer_manifests=renderer_manifests,
        )
        _write_json_file(out_report_path, applied_report)

    return 0


def _build_validated_scene_payload(
    *,
    repo_root: Path,
    report: dict[str, Any],
    timeline_payload: dict[str, Any] | None,
    lock_hash: str | None,
    created_from: str,
) -> dict[str, Any]:
    from mmo.core.scene import build_scene_from_report  # noqa: WPS433

    scene_payload = build_scene_from_report(
        report,
        timeline=timeline_payload,
        lock_hash=lock_hash,
    )
    source_payload = scene_payload.get("source")
    if isinstance(source_payload, dict):
        source_payload["created_from"] = created_from
    _validate_json_payload(
        scene_payload,
        schema_path=repo_root / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )
    return scene_payload


def _run_scene_build_command(
    *,
    repo_root: Path,
    report_path: Path,
    out_path: Path,
    timeline_path: Path | None,
    template_ids: list[str] | None = None,
    force_templates: bool = False,
) -> int:
    report = _load_report(report_path)
    _validate_json_payload(
        report,
        schema_path=repo_root / "schemas" / "report.schema.json",
        payload_name="Report",
    )
    timeline_payload = _load_timeline_payload(timeline_path)
    scene_payload = _build_validated_scene_payload(
        repo_root=repo_root,
        report=report,
        timeline_payload=timeline_payload,
        lock_hash=None,
        created_from="analyze",
    )
    scene_payload = _apply_scene_templates_to_payload(
        repo_root=repo_root,
        scene_payload=scene_payload,
        template_ids=template_ids or [],
        force=force_templates,
    )
    _write_json_file(out_path, scene_payload)
    return 0


def _validate_scene_schema(*, repo_root: Path, scene_payload: dict[str, Any]) -> None:
    _validate_json_payload(
        scene_payload,
        schema_path=repo_root / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )


def _scene_intent_failure_payload(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": False,
        "issues": issues,
    }


def _validate_scene_intent_rules(
    *,
    repo_root: Path,
    scene_payload: dict[str, Any],
) -> None:
    intent_params = load_intent_params(repo_root / "ontology" / "intent_params.yaml")
    issues = validate_scene_intent(scene_payload, intent_params)
    if not issues:
        return
    print(
        json.dumps(
            _scene_intent_failure_payload(issues),
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


def _parse_scene_intent_cli_value(
    *,
    repo_root: Path,
    key: str,
    raw_value: str,
) -> Any:
    normalized_key = _coerce_str(key).strip()
    param_id = INTENT_PARAM_KEY_TO_ID.get(normalized_key)
    if param_id is None:
        keys = ", ".join(sorted(INTENT_PARAM_KEY_TO_ID.keys()))
        raise ValueError(f"Unsupported scene intent key: {normalized_key!r}. Expected one of: {keys}")

    intent_registry = load_intent_params(repo_root / "ontology" / "intent_params.yaml")
    params = intent_registry.get("params")
    if not isinstance(params, dict):
        raise ValueError("Intent params registry is invalid: params must be an object.")
    param_spec = params.get(param_id)
    if not isinstance(param_spec, dict):
        raise ValueError(f"Intent params registry is missing entry: {param_id}")

    param_type = _coerce_str(param_spec.get("type")).strip()
    if param_type == "number":
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"--value must be numeric for key {normalized_key}."
            ) from exc
        return numeric
    if param_type == "enum":
        normalized = _coerce_str(raw_value).strip()
        if not normalized:
            raise ValueError(f"--value must be a non-empty string for key {normalized_key}.")
        return normalized
    raise ValueError(f"Unsupported intent param type for {param_id}: {param_type!r}")


def _run_scene_locks_edit_command(
    *,
    repo_root: Path,
    scene_path: Path,
    out_path: Path,
    operation: str,
    scope: str,
    target_id: str | None,
    lock_id: str,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)

    if operation == "add":
        edited = edit_scene_add_lock(scene_payload, scope, target_id, lock_id)
    elif operation == "remove":
        edited = edit_scene_remove_lock(scene_payload, scope, target_id, lock_id)
    else:
        raise ValueError(f"Unsupported scene lock operation: {operation}")

    _validate_scene_schema(repo_root=repo_root, scene_payload=edited)
    _validate_scene_intent_rules(repo_root=repo_root, scene_payload=edited)
    _write_json_file(out_path, edited)
    return 0


def _run_scene_intent_set_command(
    *,
    repo_root: Path,
    scene_path: Path,
    out_path: Path,
    scope: str,
    target_id: str | None,
    key: str,
    value: str,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
    normalized_value = _parse_scene_intent_cli_value(
        repo_root=repo_root,
        key=key,
        raw_value=value,
    )

    edited = edit_scene_set_intent(
        scene_payload,
        scope,
        target_id,
        key,
        normalized_value,
    )
    _validate_scene_schema(repo_root=repo_root, scene_payload=edited)
    _validate_scene_intent_rules(repo_root=repo_root, scene_payload=edited)
    _write_json_file(out_path, edited)
    return 0


def _apply_scene_templates_to_payload(
    *,
    repo_root: Path,
    scene_payload: dict[str, Any],
    template_ids: list[str],
    force: bool,
) -> dict[str, Any]:
    normalized_template_ids = [
        template_id.strip()
        for template_id in template_ids
        if isinstance(template_id, str) and template_id.strip()
    ]
    if not normalized_template_ids:
        return scene_payload

    edited = apply_scene_templates(
        scene_payload,
        normalized_template_ids,
        force=force,
        scene_templates_path=repo_root / "ontology" / "scene_templates.yaml",
        scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
    )
    _validate_scene_schema(repo_root=repo_root, scene_payload=edited)
    _validate_scene_intent_rules(repo_root=repo_root, scene_payload=edited)
    return edited


def _run_scene_template_apply_command(
    *,
    repo_root: Path,
    scene_path: Path,
    out_path: Path,
    template_ids: list[str],
    force: bool,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
    edited = _apply_scene_templates_to_payload(
        repo_root=repo_root,
        scene_payload=scene_payload,
        template_ids=template_ids,
        force=force,
    )
    _write_json_file(out_path, edited)
    return 0


def _sorted_preview_paths(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return []
    return sorted(
        {
            _coerce_str(item.get("path")).strip()
            for item in rows
            if isinstance(item, dict) and _coerce_str(item.get("path")).strip()
        }
    )


def _format_preview_paths(rows: Any, *, limit: int = 5) -> str:
    paths = _sorted_preview_paths(rows)
    if not paths:
        return "(none)"
    if len(paths) <= limit:
        return ", ".join(paths)
    return f"{', '.join(paths[:limit])}, +{len(paths) - limit} more"


def _render_scene_template_preview_text(payload: dict[str, Any]) -> str:
    template_ids = [
        _coerce_str(template_id).strip()
        for template_id in payload.get("template_ids", [])
        if _coerce_str(template_id).strip()
    ]
    template_label = ", ".join(template_ids) if template_ids else "(none)"
    lines = [
        f"templates: {template_label}",
        f"force: {str(bool(payload.get('force'))).lower()}",
    ]

    scene_payload = payload.get("scene")
    if not isinstance(scene_payload, dict):
        scene_payload = {}
    scene_changes = scene_payload.get("changes")
    scene_skipped = scene_payload.get("skipped")
    lines.append(
        "scene: "
        f"hard_locked={str(bool(scene_payload.get('hard_locked'))).lower()} "
        f"changes={len(scene_changes) if isinstance(scene_changes, list) else 0} "
        f"skipped={len(scene_skipped) if isinstance(scene_skipped, list) else 0}"
    )
    lines.append(
        "  paths: "
        f"changes=[{_format_preview_paths(scene_changes)}] "
        f"skipped=[{_format_preview_paths(scene_skipped)}]"
    )

    lines.append("objects:")
    objects = payload.get("objects")
    if not isinstance(objects, list) or not objects:
        lines.append("- (none)")
    else:
        for object_payload in objects:
            if not isinstance(object_payload, dict):
                continue
            object_id = _coerce_str(object_payload.get("object_id")).strip()
            label = _coerce_str(object_payload.get("label")).strip()
            changes = object_payload.get("changes")
            skipped = object_payload.get("skipped")
            lines.append(
                f"- {object_id}: "
                f"label={label or '(none)'} "
                f"hard_locked={str(bool(object_payload.get('hard_locked'))).lower()} "
                f"changes={len(changes) if isinstance(changes, list) else 0} "
                f"skipped={len(skipped) if isinstance(skipped, list) else 0}"
            )
            lines.append(
                "  paths: "
                f"changes=[{_format_preview_paths(changes)}] "
                f"skipped=[{_format_preview_paths(skipped)}]"
            )

    lines.append("beds:")
    beds = payload.get("beds")
    if not isinstance(beds, list) or not beds:
        lines.append("- (none)")
    else:
        for bed_payload in beds:
            if not isinstance(bed_payload, dict):
                continue
            bed_id = _coerce_str(bed_payload.get("bed_id")).strip()
            kind = _coerce_str(bed_payload.get("kind")).strip()
            changes = bed_payload.get("changes")
            skipped = bed_payload.get("skipped")
            lines.append(
                f"- {bed_id}: "
                f"kind={kind or '(none)'} "
                f"hard_locked={str(bool(bed_payload.get('hard_locked'))).lower()} "
                f"changes={len(changes) if isinstance(changes, list) else 0} "
                f"skipped={len(skipped) if isinstance(skipped, list) else 0}"
            )
            lines.append(
                "  paths: "
                f"changes=[{_format_preview_paths(changes)}] "
                f"skipped=[{_format_preview_paths(skipped)}]"
            )

    return "\n".join(lines)


def _run_scene_template_preview_command(
    *,
    repo_root: Path,
    scene_path: Path,
    template_ids: list[str],
    force: bool,
    output_format: str,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    preview_payload = preview_scene_templates(
        scene_payload,
        template_ids,
        force=force,
        scene_templates_path=repo_root / "ontology" / "scene_templates.yaml",
        scene_locks_path=repo_root / "ontology" / "scene_locks.yaml",
    )
    if output_format == "json":
        print(json.dumps(preview_payload, indent=2, sort_keys=True))
    else:
        print(_render_scene_template_preview_text(preview_payload))
    return 0


def _build_scene_intent_show_payload(scene_payload: dict[str, Any]) -> dict[str, Any]:
    scene_intent = scene_payload.get("intent")
    normalized_scene_intent = dict(scene_intent) if isinstance(scene_intent, dict) else {}

    objects: list[dict[str, Any]] = []
    for entry in scene_payload.get("objects", []):
        if not isinstance(entry, dict):
            continue
        object_id = _coerce_str(entry.get("object_id")).strip()
        if not object_id:
            continue
        intent = entry.get("intent")
        objects.append(
            {
                "object_id": object_id,
                "intent": dict(intent) if isinstance(intent, dict) else {},
            }
        )
    objects.sort(key=lambda item: item["object_id"])

    beds: list[dict[str, Any]] = []
    for entry in scene_payload.get("beds", []):
        if not isinstance(entry, dict):
            continue
        bed_id = _coerce_str(entry.get("bed_id")).strip()
        if not bed_id:
            continue
        intent = entry.get("intent")
        beds.append(
            {
                "bed_id": bed_id,
                "intent": dict(intent) if isinstance(intent, dict) else {},
            }
        )
    beds.sort(key=lambda item: item["bed_id"])

    return {
        "scene": normalized_scene_intent,
        "objects": objects,
        "beds": beds,
    }


def _render_scene_intent_text(payload: dict[str, Any]) -> str:
    lines = ["scene:"]
    lines.append(json.dumps(payload.get("scene", {}), sort_keys=True))

    lines.append("objects:")
    for item in payload.get("objects", []):
        if not isinstance(item, dict):
            continue
        object_id = _coerce_str(item.get("object_id")).strip()
        intent = item.get("intent")
        lines.append(
            f"- {object_id}: {json.dumps(intent if isinstance(intent, dict) else {}, sort_keys=True)}"
        )

    lines.append("beds:")
    for item in payload.get("beds", []):
        if not isinstance(item, dict):
            continue
        bed_id = _coerce_str(item.get("bed_id")).strip()
        intent = item.get("intent")
        lines.append(
            f"- {bed_id}: {json.dumps(intent if isinstance(intent, dict) else {}, sort_keys=True)}"
        )
    return "\n".join(lines)


def _build_validated_render_plan_payload(
    *,
    repo_root: Path,
    scene_payload: dict[str, Any],
    scene_path: Path,
    render_targets_payload: dict[str, Any],
    routing_plan_path: Path | None,
    output_formats: list[str],
    contexts: list[str],
    policies: dict[str, Any] | None,
) -> dict[str, Any]:
    scene_for_plan = json.loads(json.dumps(scene_payload))
    scene_for_plan["scene_path"] = scene_path.resolve().as_posix()
    render_plan_payload = build_render_plan(
        scene_for_plan,
        render_targets_payload,
        routing_plan_path=(
            routing_plan_path.resolve().as_posix()
            if isinstance(routing_plan_path, Path)
            else None
        ),
        output_formats=output_formats,
        contexts=contexts,
        policies=policies,
    )
    _validate_json_payload(
        render_plan_payload,
        schema_path=repo_root / "schemas" / "render_plan.schema.json",
        payload_name="Render plan",
    )
    return render_plan_payload


def _run_render_plan_build_command(
    *,
    repo_root: Path,
    scene_path: Path,
    target_ids: list[str],
    out_path: Path,
    routing_plan_path: Path | None,
    output_formats: list[str],
    contexts: list[str],
    policy_id: str | None,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_json_payload(
        scene_payload,
        schema_path=repo_root / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )

    resolved_routing_plan_path: Path | None = None
    if routing_plan_path is not None:
        routing_plan_payload = _load_json_object(routing_plan_path, label="Routing plan")
        _validate_json_payload(
            routing_plan_payload,
            schema_path=repo_root / "schemas" / "routing_plan.schema.json",
            payload_name="Routing plan",
        )
        resolved_routing_plan_path = routing_plan_path

    render_targets_payload = _build_selected_render_targets_payload(
        target_ids=target_ids,
        render_targets_path=repo_root / "ontology" / "render_targets.yaml",
    )
    policies: dict[str, str] = {}
    normalized_policy_id = _coerce_str(policy_id).strip()
    if normalized_policy_id:
        policies["downmix_policy_id"] = normalized_policy_id
    render_plan_payload = _build_validated_render_plan_payload(
        repo_root=repo_root,
        scene_payload=scene_payload,
        scene_path=scene_path,
        render_targets_payload=render_targets_payload,
        routing_plan_path=resolved_routing_plan_path,
        output_formats=output_formats,
        contexts=contexts,
        policies=policies,
    )
    _write_json_file(out_path, render_plan_payload)
    return 0


def _run_render_plan_to_variants_command(
    *,
    repo_root: Path,
    presets_dir: Path,
    render_plan_path: Path,
    scene_path: Path,
    out_path: Path,
    out_dir: Path,
    run: bool,
    listen_pack: bool,
    deliverables_index: bool,
    cache_enabled: bool,
    cache_dir: Path | None,
    default_steps: dict[str, Any] | None = None,
) -> int:
    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_json_payload(
        scene_payload,
        schema_path=repo_root / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )

    render_plan_payload = _load_json_object(render_plan_path, label="Render plan")
    _validate_json_payload(
        render_plan_payload,
        schema_path=repo_root / "schemas" / "render_plan.schema.json",
        payload_name="Render plan",
    )

    scene_for_bridge = json.loads(json.dumps(scene_payload))
    scene_for_bridge["scene_path"] = scene_path.resolve().as_posix()
    render_plan_for_bridge = json.loads(json.dumps(render_plan_payload))
    render_plan_for_bridge["render_plan_path"] = render_plan_path.resolve().as_posix()

    variant_plan = render_plan_to_variant_plan(
        render_plan_for_bridge,
        scene_for_bridge,
        base_out_dir=out_dir.resolve().as_posix(),
        default_steps=default_steps,
    )
    _validate_json_payload(
        variant_plan,
        schema_path=repo_root / "schemas" / "variant_plan.schema.json",
        payload_name="Variant plan",
    )
    _write_json_file(out_path, variant_plan)

    if not run:
        return 0

    resolved_out_dir = out_dir.resolve()
    variant_result_path = resolved_out_dir / "variant_result.json"
    listen_pack_path = resolved_out_dir / "listen_pack.json"
    deliverables_index_path = resolved_out_dir / "deliverables_index.json"

    run_variant_plan_kwargs: dict[str, Any] = {
        "cache_enabled": cache_enabled,
        "cache_dir": cache_dir,
    }
    if deliverables_index:
        run_variant_plan_kwargs["deliverables_index_path"] = deliverables_index_path
    if listen_pack:
        run_variant_plan_kwargs["listen_pack_path"] = listen_pack_path

    variant_result = run_variant_plan(
        variant_plan,
        repo_root=repo_root,
        **run_variant_plan_kwargs,
    )
    _validate_json_payload(
        variant_result,
        schema_path=repo_root / "schemas" / "variant_result.schema.json",
        payload_name="Variant result",
    )
    _write_json_file(variant_result_path, variant_result)

    if listen_pack:
        listen_pack_payload = _build_validated_listen_pack(
            repo_root=repo_root,
            presets_dir=presets_dir,
            variant_result=variant_result,
        )
        _write_json_file(listen_pack_path, listen_pack_payload)

    if deliverables_index:
        deliverables_index_payload = _build_validated_deliverables_index_variants(
            repo_root=repo_root,
            root_out_dir=resolved_out_dir,
            variant_result=variant_result,
        )
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    results = variant_result.get("results")
    if not isinstance(results, list):
        return 1
    has_failure = any(
        isinstance(item, dict) and item.get("ok") is not True
        for item in results
    )
    return 1 if has_failure else 0


def _apply_run_config_to_render_many_variant_plan(
    *,
    variant_plan: dict[str, Any],
    run_config: dict[str, Any],
    preset_id: str | None,
    config_path: Path | None,
) -> dict[str, Any]:
    variants = variant_plan.get("variants")
    if not isinstance(variants, list):
        return variant_plan

    base_patch = normalize_run_config(run_config)
    normalized_preset_id = _coerce_str(preset_id).strip()
    resolved_config_path = (
        config_path.resolve().as_posix()
        if isinstance(config_path, Path)
        else None
    )
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_overrides = variant.get("run_config_overrides")
        if isinstance(variant_overrides, dict):
            merged_overrides = merge_run_config(base_patch, variant_overrides)
        else:
            merged_overrides = normalize_run_config(base_patch)
        variant["run_config_overrides"] = merged_overrides

        if normalized_preset_id and not _coerce_str(variant.get("preset_id")).strip():
            variant["preset_id"] = normalized_preset_id
        if isinstance(resolved_config_path, str):
            variant["config_path"] = resolved_config_path

    return variant_plan


def _write_routing_plan_artifact(
    *,
    repo_root: Path,
    report_payload: dict[str, Any],
    out_path: Path,
) -> Path | None:
    routing_plan_payload = report_payload.get("routing_plan")
    if not isinstance(routing_plan_payload, dict):
        return None
    _validate_json_payload(
        routing_plan_payload,
        schema_path=repo_root / "schemas" / "routing_plan.schema.json",
        payload_name="Routing plan",
    )
    _write_json_file(out_path, routing_plan_payload)
    return out_path


def _run_bundle(
    *,
    repo_root: Path,
    report_path: Path,
    out_path: Path,
    render_manifest_path: Path | None,
    apply_manifest_path: Path | None,
    applied_report_path: Path | None,
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    scene_path: Path | None,
    render_plan_path: Path | None,
    stems_index_path: Path | None,
    stems_map_path: Path | None,
    timeline_path: Path | None,
    gui_state_path: Path | None = None,
    ui_locale: str | None = None,
) -> int:
    from mmo.core.ui_bundle import build_ui_bundle  # noqa: WPS433

    report = _load_report(report_path)
    render_manifest: dict[str, Any] | None = None
    apply_manifest: dict[str, Any] | None = None
    applied_report: dict[str, Any] | None = None
    if render_manifest_path is not None:
        render_manifest = _load_json_object(render_manifest_path, label="Render manifest")
    if apply_manifest_path is not None:
        apply_manifest = _load_json_object(apply_manifest_path, label="Apply manifest")
    if applied_report_path is not None:
        applied_report = _load_json_object(applied_report_path, label="Applied report")

    bundle = build_ui_bundle(
        report,
        render_manifest,
        apply_manifest=apply_manifest,
        applied_report=applied_report,
        help_registry_path=repo_root / "ontology" / "help.yaml",
        ui_copy_path=repo_root / "ontology" / "ui_copy.yaml",
        ui_locale=ui_locale,
        project_path=project_path,
        deliverables_index_path=deliverables_index_path,
        listen_pack_path=listen_pack_path,
        scene_path=scene_path,
        render_plan_path=render_plan_path,
        stems_index_path=stems_index_path,
        stems_map_path=stems_map_path,
        timeline_path=timeline_path,
        gui_state_path=gui_state_path,
    )
    _validate_json_payload(
        bundle,
        schema_path=repo_root / "schemas" / "ui_bundle.schema.json",
        payload_name="UI bundle",
    )
    _write_json_file(out_path, bundle)
    return 0


def _build_preset_show_payload(*, presets_dir: Path, preset_id: str) -> dict[str, Any]:
    normalized_preset_id = preset_id.strip() if isinstance(preset_id, str) else ""
    if not normalized_preset_id:
        raise ValueError("preset_id must be a non-empty string.")

    presets = list_presets(presets_dir)
    preset_entry = next(
        (
            item
            for item in presets
            if isinstance(item, dict) and item.get("preset_id") == normalized_preset_id
        ),
        None,
    )
    if preset_entry is None:
        available = ", ".join(
            item["preset_id"]
            for item in presets
            if isinstance(item, dict) and isinstance(item.get("preset_id"), str)
        )
        if available:
            raise ValueError(
                f"Unknown preset_id: {normalized_preset_id}. Available presets: {available}"
            )
        raise ValueError(
            f"Unknown preset_id: {normalized_preset_id}. No presets are available."
        )

    payload = dict(preset_entry)
    payload["run_config"] = load_preset_run_config(
        presets_dir,
        normalized_preset_id,
    )
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _preset_preview_placeholder_help() -> dict[str, Any]:
    return {
        "title": "Preset help unavailable",
        "short": "No musician-language help text is available for this preset yet.",
        "cues": [
            "Use this preset as a workflow lens and confirm by ear in context.",
        ],
        "watch_out_for": [
            "Double-check translation on your main playback systems.",
        ],
    }


def _build_preset_preview_help(
    *,
    help_registry_path: Path,
    help_id: str | None,
) -> dict[str, Any]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    placeholder = _preset_preview_placeholder_help()
    normalized_help_id = help_id.strip() if isinstance(help_id, str) else ""
    if not normalized_help_id:
        return placeholder

    registry = load_help_registry(help_registry_path)
    resolved = resolve_help_entries([normalized_help_id], registry)
    entry = resolved.get(normalized_help_id)
    if not isinstance(entry, dict):
        return placeholder

    entry_title = entry.get("title")
    entry_short = entry.get("short")
    if not isinstance(entry_short, str) or not entry_short.strip():
        return placeholder
    if (
        entry_short == "Missing help entry"
        and isinstance(entry_title, str)
        and entry_title == normalized_help_id
    ):
        return placeholder

    payload: dict[str, Any] = {
        "title": entry_title if isinstance(entry_title, str) and entry_title else "",
        "short": entry_short,
    }
    long_text = entry.get("long")
    if isinstance(long_text, str) and long_text:
        payload["long"] = long_text

    cues = _string_list(entry.get("cues"))
    watch_out_for = _string_list(entry.get("watch_out_for"))
    payload["cues"] = cues if cues else list(placeholder["cues"])
    payload["watch_out_for"] = (
        watch_out_for if watch_out_for else list(placeholder["watch_out_for"])
    )
    return payload


def _build_preset_preview_default_run_config() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "profile_id": _PRESET_PREVIEW_DEFAULT_PROFILE_ID,
        "meters": _PRESET_PREVIEW_DEFAULT_METERS,
        "max_seconds": _PRESET_PREVIEW_DEFAULT_MAX_SECONDS,
        "downmix": {
            "target_layout_id": _PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID,
        },
    }
    return normalize_run_config(payload)


def _build_preset_preview_cli_overrides(
    *,
    args: argparse.Namespace,
    raw_argv: list[str],
) -> dict[str, Any]:
    cli_overrides: dict[str, Any] = {}
    if _flag_present(raw_argv, "--profile"):
        cli_overrides["profile_id"] = args.profile
    if _flag_present(raw_argv, "--meters"):
        cli_overrides["meters"] = args.meters
    if _flag_present(raw_argv, "--max-seconds"):
        cli_overrides["max_seconds"] = args.max_seconds
    if _flag_present(raw_argv, "--source-layout"):
        _set_nested(["downmix", "source_layout_id"], cli_overrides, args.source_layout)
    if _flag_present(raw_argv, "--target-layout"):
        _set_nested(["downmix", "target_layout_id"], cli_overrides, args.target_layout)
    if _flag_present(raw_argv, "--policy-id"):
        _set_nested(["downmix", "policy_id"], cli_overrides, args.policy_id)
    return cli_overrides


def _build_preset_preview_payload(
    *,
    repo_root: Path,
    presets_dir: Path,
    preset_id: str,
    config_path: str | None,
    cli_overrides: dict[str, Any],
) -> dict[str, Any]:
    preset_payload = _build_preset_show_payload(presets_dir=presets_dir, preset_id=preset_id)
    normalized_preset_id = (
        preset_payload.get("preset_id", "").strip()
        if isinstance(preset_payload.get("preset_id"), str)
        else ""
    )
    if not normalized_preset_id:
        raise ValueError("preset_id must be a non-empty string.")

    preset_cfg = preset_payload.get("run_config")
    if not isinstance(preset_cfg, dict):
        raise ValueError("Preset run_config must be an object.")

    base_cfg = _build_preset_preview_default_run_config()
    config_cfg: dict[str, Any] = {}
    if config_path:
        config_cfg = load_run_config(Path(config_path))

    effective_cfg = merge_run_config(base_cfg, preset_cfg)
    effective_cfg = merge_run_config(effective_cfg, config_cfg)
    pre_cli_cfg = dict(effective_cfg)
    effective_cfg = merge_run_config(effective_cfg, cli_overrides)
    effective_cfg["preset_id"] = normalized_preset_id
    effective_cfg = normalize_run_config(effective_cfg)

    _validate_json_payload(
        effective_cfg,
        schema_path=repo_root / "schemas" / "run_config.schema.json",
        payload_name="Preset preview effective_run_config",
    )

    help_payload = _build_preset_preview_help(
        help_registry_path=repo_root / "ontology" / "help.yaml",
        help_id=preset_payload.get("help_id")
        if isinstance(preset_payload.get("help_id"), str)
        else None,
    )
    changes_by_key_path = {
        item["key_path"]: item
        for item in diff_run_config(base_cfg, effective_cfg)
        if isinstance(item.get("key_path"), str)
    }
    cli_override_key_paths = {
        item["key_path"]
        for item in diff_run_config({}, cli_overrides)
        if isinstance(item.get("key_path"), str)
    }
    for item in diff_run_config(pre_cli_cfg, effective_cfg):
        key_path = item.get("key_path")
        if not isinstance(key_path, str):
            continue
        if key_path not in cli_override_key_paths:
            continue
        if key_path in changes_by_key_path:
            continue
        changes_by_key_path[key_path] = item
    changes_by_key_path.pop("preset_id", None)
    changes_from_defaults = [
        changes_by_key_path[key_path]
        for key_path in sorted(changes_by_key_path.keys())
    ]

    label = preset_payload.get("label")
    overlay = preset_payload.get("overlay")
    category = preset_payload.get("category")
    payload: dict[str, Any] = {
        "preset_id": normalized_preset_id,
        "label": label if isinstance(label, str) else "",
        "overlay": overlay if isinstance(overlay, str) else "",
        "category": category if isinstance(category, str) else "",
        "tags": _string_list(preset_payload.get("tags")),
        "goals": _string_list(preset_payload.get("goals")),
        "warnings": _string_list(preset_payload.get("warnings")),
        "help": help_payload,
        "effective_run_config": effective_cfg,
        "changes_from_defaults": changes_from_defaults,
    }
    return payload


def _render_preset_preview_text(payload: dict[str, Any]) -> str:
    preset_id = payload.get("preset_id")
    label = payload.get("label")
    category = payload.get("category")
    overlay = payload.get("overlay")
    help_payload = payload.get("help")
    changes = payload.get("changes_from_defaults")

    normalized_preset_id = preset_id if isinstance(preset_id, str) else ""
    normalized_label = label if isinstance(label, str) else ""
    normalized_category = category if isinstance(category, str) and category else "UNCATEGORIZED"
    normalized_overlay = overlay if isinstance(overlay, str) and overlay else "none"

    short_text = ""
    cues: list[str] = []
    watch_out_for: list[str] = []
    if isinstance(help_payload, dict):
        short = help_payload.get("short")
        if isinstance(short, str):
            short_text = short
        cues = _string_list(help_payload.get("cues"))
        watch_out_for = _string_list(help_payload.get("watch_out_for"))

    lines = [
        f"{normalized_label} ({normalized_preset_id}) [{normalized_category}]",
        f"Overlay: {normalized_overlay}",
        f"Short: {short_text}",
        "When to use:",
    ]
    for cue in cues:
        lines.append(f"  - {cue}")

    lines.append("Watch out for:")
    for item in watch_out_for:
        lines.append(f"  - {item}")

    lines.append("What changes if you use this preset:")
    if isinstance(changes, list) and changes:
        for item in changes:
            if not isinstance(item, dict):
                continue
            key_path = item.get("key_path")
            if not isinstance(key_path, str) or not key_path:
                continue
            before_value = json.dumps(item.get("before"), sort_keys=True)
            after_value = json.dumps(item.get("after"), sort_keys=True)
            lines.append(f"  - {key_path}: {before_value} -> {after_value}")
    else:
        lines.append(
            "This preset is a workflow lens. It doesnt change settings, it changes what you focus on."
        )
    return "\n".join(lines)


def _build_preset_label_map(*, presets_dir: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in list_presets(presets_dir):
        if not isinstance(item, dict):
            continue
        preset_id = item.get("preset_id")
        label = item.get("label")
        if isinstance(preset_id, str) and isinstance(label, str):
            labels[preset_id] = label
    return labels


def _build_preset_pack_payload(*, presets_dir: Path, pack_id: str) -> dict[str, Any]:
    payload = load_preset_pack(presets_dir, pack_id)
    label_map = _build_preset_label_map(presets_dir=presets_dir)
    presets: list[dict[str, str]] = []
    for preset_id in payload.get("preset_ids", []):
        if not isinstance(preset_id, str):
            continue
        presets.append(
            {
                "preset_id": preset_id,
                "label": label_map.get(preset_id, ""),
            }
        )
    payload["presets"] = presets
    return payload


def _build_preset_pack_list_payload(*, presets_dir: Path) -> list[dict[str, Any]]:
    label_map = _build_preset_label_map(presets_dir=presets_dir)
    payload: list[dict[str, Any]] = []
    for item in list_preset_packs(presets_dir):
        if not isinstance(item, dict):
            continue
        pack_payload = dict(item)
        presets: list[dict[str, str]] = []
        for preset_id in pack_payload.get("preset_ids", []):
            if not isinstance(preset_id, str):
                continue
            presets.append(
                {
                    "preset_id": preset_id,
                    "label": label_map.get(preset_id, ""),
                }
            )
        pack_payload["presets"] = presets
        payload.append(pack_payload)
    return payload


def _build_preset_recommendations_payload(
    *,
    report_path: Path,
    presets_dir: Path,
    n: int,
) -> list[dict[str, Any]]:
    from mmo.core.preset_recommendations import derive_preset_recommendations  # noqa: WPS433

    if n <= 0:
        raise ValueError("--n must be greater than 0.")
    report = _load_report(report_path)
    return derive_preset_recommendations(report, presets_dir, n=n)


def _build_render_target_list_payload(*, render_targets_path: Path) -> list[dict[str, Any]]:
    return list_render_targets(render_targets_path)


def _build_render_target_show_payload(
    *,
    render_targets_path: Path,
    target_id: str,
) -> dict[str, Any]:
    resolved_target_id = resolve_render_target_id(target_id, render_targets_path)
    payload = get_render_target(resolved_target_id, render_targets_path)
    if payload is None:
        raise ValueError(f"Resolved target is missing from registry: {resolved_target_id}")
    return payload


def _build_role_list_payload(*, roles_path: Path) -> list[str]:
    return list_roles(roles_path)


def _build_role_show_payload(*, roles_path: Path, role_id: str) -> dict[str, Any]:
    normalized_role_id = role_id.strip() if isinstance(role_id, str) else ""
    if not normalized_role_id:
        raise ValueError("role_id must be a non-empty string.")
    payload = resolve_role(normalized_role_id, roles_path)
    row = {"role_id": normalized_role_id}
    row.update(dict(payload))
    return row


def _render_role_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("role_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"kind: {_coerce_str(payload.get('kind')).strip()}",
    ]

    default_bus_group = payload.get("default_bus_group")
    if isinstance(default_bus_group, str) and default_bus_group.strip():
        lines.append(f"default_bus_group: {default_bus_group.strip()}")

    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        lines.append(f"description: {description.strip()}")

    inference = payload.get("inference")
    if isinstance(inference, dict):
        keywords = inference.get("keywords")
        if isinstance(keywords, list):
            normalized_keywords = [
                keyword.strip()
                for keyword in keywords
                if isinstance(keyword, str) and keyword.strip()
            ]
            if normalized_keywords:
                lines.append(f"keywords: {', '.join(normalized_keywords)}")

        regex_values = inference.get("regex")
        if isinstance(regex_values, list):
            normalized_regex_values = [
                pattern.strip()
                for pattern in regex_values
                if isinstance(pattern, str) and pattern.strip()
            ]
            if normalized_regex_values:
                lines.append("regex:")
                for pattern in normalized_regex_values:
                    lines.append(f"- {pattern}")

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        normalized_notes = [item.strip() for item in notes if isinstance(item, str) and item.strip()]
        if normalized_notes:
            lines.append("notes:")
            for item in normalized_notes:
                lines.append(f"- {item}")

    return "\n".join(lines)


def _build_translation_profile_list_payload(
    *,
    translation_profiles_path: Path,
) -> list[dict[str, Any]]:
    return list_translation_profiles(translation_profiles_path)


def _build_translation_profile_show_payload(
    *,
    translation_profiles_path: Path,
    profile_id: str,
) -> dict[str, Any]:
    return get_translation_profile(profile_id, translation_profiles_path)


def _render_translation_profile_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("profile_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"description: {_coerce_str(payload.get('description')).strip()}",
        f"intent: {_coerce_str(payload.get('intent')).strip()}",
    ]

    thresholds = payload.get("default_thresholds")
    if isinstance(thresholds, dict):
        lines.append("default_thresholds:")
        for key in sorted(thresholds.keys()):
            value = thresholds.get(key)
            lines.append(f"- {key}: {value}")

    scoring = payload.get("scoring")
    if isinstance(scoring, dict):
        lines.append("scoring:")
        for key in sorted(scoring.keys()):
            value = scoring.get(key)
            lines.append(f"- {key}: {value}")

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes:")
        for item in notes:
            if isinstance(item, str):
                lines.append(f"- {item}")

    return "\n".join(lines)


def _parse_translation_profile_ids_csv(
    raw_value: str,
    *,
    translation_profiles_path: Path,
) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("translation profiles must be a comma-separated string.")

    requested = [
        profile_id.strip()
        for profile_id in raw_value.split(",")
        if isinstance(profile_id, str) and profile_id.strip()
    ]
    if not requested:
        raise ValueError("translation profiles must include at least one profile ID.")

    profiles = load_translation_profiles(translation_profiles_path)
    known_ids = sorted(profile_id for profile_id in profiles.keys() if isinstance(profile_id, str))
    known_set = set(known_ids)
    unknown_ids = sorted(
        {
            profile_id
            for profile_id in requested
            if profile_id not in known_set
        }
    )
    if unknown_ids:
        unknown_label = ", ".join(unknown_ids)
        known_label = ", ".join(known_ids)
        if known_label:
            raise ValueError(
                f"Unknown translation profile_id: {unknown_label}. Known profile_ids: {known_label}"
            )
        raise ValueError(
            f"Unknown translation profile_id: {unknown_label}. No translation profiles are available."
        )

    selected: list[str] = []
    seen: set[str] = set()
    for profile_id in requested:
        if profile_id not in seen:
            selected.append(profile_id)
            seen.add(profile_id)
    return selected


def _parse_translation_audio_csv(raw_value: str) -> list[Path]:
    if not isinstance(raw_value, str):
        raise ValueError("audio must be a comma-separated string.")

    selected: list[Path] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        normalized = item.strip()
        if not normalized:
            continue
        key = Path(normalized).as_posix().strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(Path(normalized))

    if not selected:
        raise ValueError("audio must include at least one WAV path.")
    return selected


def _translation_audio_sort_key(path: Path) -> tuple[str, str, str, str]:
    filename = path.name
    normalized_filename = filename.casefold()
    normalized_path = path.as_posix().casefold()
    return (normalized_filename, filename, normalized_path, path.as_posix())


def _discover_translation_audio_paths(
    *,
    in_dir: Path,
    glob_pattern: str,
) -> list[Path]:
    if not in_dir.exists():
        raise ValueError(f"Audio directory does not exist: {in_dir}")
    if not in_dir.is_dir():
        raise ValueError(f"Audio directory is not a directory: {in_dir}")
    if not isinstance(glob_pattern, str) or not glob_pattern.strip():
        raise ValueError("glob pattern must be a non-empty string.")

    pattern = glob_pattern.strip()
    candidates = [path for path in in_dir.glob(pattern) if path.is_file()]
    wav_paths = [
        path
        for path in candidates
        if path.suffix.lower() in {".wav", ".wave"}
    ]
    if not wav_paths:
        raise ValueError(f"No WAV files matched {pattern!r} under directory: {in_dir}")
    return sorted(wav_paths, key=_translation_audio_sort_key)


def _resolve_translation_compare_audio_paths(
    *,
    raw_audio: str | None,
    in_dir_value: str | None,
    glob_pattern: str | None,
) -> list[Path]:
    audio_value = raw_audio.strip() if isinstance(raw_audio, str) else ""
    in_dir_raw = in_dir_value.strip() if isinstance(in_dir_value, str) else ""
    if audio_value and in_dir_raw:
        raise ValueError("translation compare accepts either --audio or --in-dir, not both.")

    if audio_value:
        audio_paths = _parse_translation_audio_csv(audio_value)
        return sorted(audio_paths, key=_translation_audio_sort_key)

    if in_dir_raw:
        pattern = glob_pattern.strip() if isinstance(glob_pattern, str) else "*.wav"
        return _discover_translation_audio_paths(
            in_dir=Path(in_dir_raw),
            glob_pattern=pattern or "*.wav",
        )

    raise ValueError("translation compare requires either --audio or --in-dir.")


def _coerce_translation_compare_score(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    return 0


def _build_translation_compare_payload(
    *,
    translation_profiles_path: Path,
    audio_paths: list[Path],
    profile_ids: list[str],
    max_issues_per_profile: int = 3,
) -> list[dict[str, Any]]:
    if not isinstance(audio_paths, list):
        raise ValueError("audio paths must be provided as a list.")
    if not audio_paths:
        raise ValueError("At least one WAV audio input is required.")

    sorted_profile_ids = sorted(
        {
            profile_id.strip()
            for profile_id in profile_ids
            if isinstance(profile_id, str) and profile_id.strip()
        }
    )
    if not sorted_profile_ids:
        raise ValueError("At least one translation profile_id is required.")

    profiles = load_translation_profiles(translation_profiles_path)
    rows: list[dict[str, Any]] = []

    for audio_path in sorted(audio_paths, key=_translation_audio_sort_key):
        translation_results = run_translation_checks(
            audio_path=audio_path,
            profiles=profiles,
            profile_ids=sorted_profile_ids,
            max_issues_per_profile=max_issues_per_profile,
        )
        summary_rows = build_translation_summary(translation_results, profiles)
        status_by_profile = {
            _coerce_str(item.get("profile_id")).strip(): _coerce_str(item.get("status")).strip()
            for item in summary_rows
            if isinstance(item, dict)
        }

        for result in _sorted_translation_results(translation_results):
            profile_id = _coerce_str(result.get("profile_id")).strip()
            if not profile_id:
                continue
            issues_raw = result.get("issues")
            issues_count = len(
                [item for item in issues_raw if isinstance(item, dict)]
            ) if isinstance(issues_raw, list) else 0
            rows.append(
                {
                    "audio": audio_path.name,
                    "profile_id": profile_id,
                    "score": _coerce_translation_compare_score(result.get("score")),
                    "status": status_by_profile.get(profile_id, ""),
                    "issues_count": issues_count,
                }
            )

    rows.sort(
        key=lambda item: (
            _coerce_str(item.get("audio")).strip().casefold(),
            _coerce_str(item.get("audio")).strip(),
            _coerce_str(item.get("profile_id")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )
    return rows


def _render_translation_compare_text(payload: list[dict[str, Any]]) -> str:
    lines = ["audio | profile_id | score | status"]
    for row in payload:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{_coerce_str(row.get('audio')).strip()} | "
            f"{_coerce_str(row.get('profile_id')).strip()} | "
            f"{_coerce_translation_compare_score(row.get('score'))} | "
            f"{_coerce_str(row.get('status')).strip()}"
        )
    return "\n".join(lines)


def _build_translation_run_payload(
    *,
    translation_profiles_path: Path,
    audio_path: Path,
    profile_ids: list[str],
    max_issues_per_profile: int = 3,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    profiles = load_translation_profiles(translation_profiles_path)
    return run_translation_checks(
        audio_path=audio_path,
        profiles=profiles,
        profile_ids=profile_ids,
        max_issues_per_profile=max_issues_per_profile,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )


def _build_translation_audition_payload(
    *,
    translation_profiles_path: Path,
    audio_path: Path,
    out_dir: Path,
    profile_ids: list[str],
    segment_s: float | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    profiles = load_translation_profiles(translation_profiles_path)
    return render_translation_auditions(
        audio_path=audio_path,
        out_dir=out_dir,
        profiles=profiles,
        profile_ids=profile_ids,
        segment_s=segment_s,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )


def _render_translation_results_text(payload: list[dict[str, Any]]) -> str:
    if not payload:
        return "translation_results: (none)"

    lines = ["translation_results:"]
    for row in payload:
        if not isinstance(row, dict):
            continue
        profile_id = _coerce_str(row.get("profile_id")).strip()
        score = row.get("score")
        issues = row.get("issues")
        issue_count = len(issues) if isinstance(issues, list) else 0
        lines.append(f"- {profile_id} score={score} issues={issue_count}")
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = _coerce_str(issue.get("issue_id")).strip()
            message = _coerce_str(issue.get("message")).strip()
            lines.append(f"  {issue_id}: {message}")
    return "\n".join(lines)


def _write_translation_results_json(
    path: Path,
    payload: list[dict[str, Any]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(f"Failed to write translation results JSON: {path}: {exc}") from exc


def _write_translation_audition_manifest(
    path: Path,
    payload: dict[str, Any],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(
            f"Failed to write translation audition manifest JSON: {path}: {exc}"
        ) from exc


def _write_report_with_translation_results(
    *,
    report_in_path: Path,
    report_out_path: Path,
    translation_results: list[dict[str, Any]],
    repo_root: Path,
    profiles: dict[str, dict[str, Any]] | None = None,
    translation_reference: dict[str, Any] | None = None,
) -> None:
    report_payload = _load_report(report_in_path)
    profile_map = (
        profiles
        if isinstance(profiles, dict)
        else load_translation_profiles(repo_root / "ontology" / "translation_profiles.yaml")
    )
    report_payload["translation_results"] = translation_results
    report_payload["translation_summary"] = build_translation_summary(
        translation_results,
        profile_map,
    )
    if isinstance(translation_reference, dict):
        report_payload["translation_reference"] = dict(translation_reference)
    _validate_json_payload(
        report_payload,
        schema_path=repo_root / "schemas" / "report.schema.json",
        payload_name="Report",
    )
    try:
        report_out_path.parent.mkdir(parents=True, exist_ok=True)
        report_out_path.write_text(
            json.dumps(report_payload, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(f"Failed to write report JSON: {report_out_path}: {exc}") from exc


def _sorted_translation_results(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(item) for item in payload if isinstance(item, dict)]
    rows.sort(
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )
    return rows


def _render_translation_audition_text(
    *,
    payload: dict[str, Any],
    root_out_dir: Path,
    audition_out_dir: Path,
) -> str:
    renders = payload.get("renders")
    rows = [item for item in renders if isinstance(item, dict)] if isinstance(renders, list) else []
    rows = sorted(
        rows,
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            _coerce_str(item.get("path")).strip(),
        ),
    )

    lines = [f"Wrote {len(rows)} audition files to {audition_out_dir.resolve().as_posix()}"]
    for row in rows:
        profile_id = _coerce_str(row.get("profile_id")).strip()
        path_value = _coerce_str(row.get("path")).strip()
        rendered_path = Path(path_value) if path_value else Path()
        relative = _rel_path_if_under_root(root_out_dir, rendered_path) if path_value else None
        target_path = relative if relative else path_value
        lines.append(f"- {profile_id} -> {target_path}")
    return "\n".join(lines)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _path_from_result_value(
    value: Any,
    *,
    root_out_dir: Path,
    variant_out_dir: Path | None = None,
) -> Path | None:
    raw = _coerce_str(value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    if variant_out_dir is not None:
        return (variant_out_dir / candidate).resolve()
    return (root_out_dir / candidate).resolve()


def _render_output_sort_key(output: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _render_many_variant_artifacts(
    *,
    variant_result: dict[str, Any],
    root_out_dir: Path,
) -> list[dict[str, Any]]:
    plan = variant_result.get("plan")
    plan_variants = (
        _dict_list(plan.get("variants"))
        if isinstance(plan, dict)
        else []
    )
    by_variant_id: dict[str, dict[str, Any]] = {}
    for variant in plan_variants:
        variant_id = _coerce_str(variant.get("variant_id")).strip()
        if variant_id and variant_id not in by_variant_id:
            by_variant_id[variant_id] = variant

    artifacts: list[dict[str, Any]] = []
    results = sorted(
        _dict_list(variant_result.get("results")),
        key=lambda item: _coerce_str(item.get("variant_id")).strip(),
    )
    for result in results:
        variant_id = _coerce_str(result.get("variant_id")).strip()
        plan_variant = by_variant_id.get(variant_id, {})
        variant_out_dir = _path_from_result_value(
            result.get("out_dir"),
            root_out_dir=root_out_dir,
        )
        artifact = {
            "variant_id": variant_id,
            "target_id": (
                _coerce_str(plan_variant.get("label")).strip()
                if _coerce_str(plan_variant.get("label")).strip().startswith("TARGET.")
                else ""
            ),
            "target_layout_id": _coerce_str(plan_variant.get("target_layout_id")).strip(),
            "out_dir": variant_out_dir,
            "report_path": _path_from_result_value(
                result.get("report_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "bundle_path": _path_from_result_value(
                result.get("bundle_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "render_manifest_path": _path_from_result_value(
                result.get("render_manifest_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "apply_manifest_path": _path_from_result_value(
                result.get("apply_manifest_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "applied_report_path": _path_from_result_value(
                result.get("applied_report_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
        }
        artifacts.append(artifact)
    return artifacts


def _resolve_wav_output_path(
    *,
    output: dict[str, Any],
    candidate_roots: list[Path],
) -> Path | None:
    output_format = _coerce_str(output.get("format")).strip().lower()
    file_path = _coerce_str(output.get("file_path")).strip()
    if not file_path:
        return None
    if output_format and output_format != "wav":
        return None
    if not output_format and Path(file_path).suffix.lower() not in {".wav", ".wave"}:
        return None

    channel_count = output.get("channel_count")
    if (
        isinstance(channel_count, int)
        and not isinstance(channel_count, bool)
        and channel_count != 2
    ):
        return None

    file_candidate = Path(file_path)
    if file_candidate.is_absolute():
        if file_candidate.exists() and file_candidate.is_file():
            return file_candidate.resolve()
        return None

    for root in candidate_roots:
        candidate = (root / file_candidate).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _wav_output_path_from_manifest(
    *,
    render_manifest: dict[str, Any],
    target_layout_id: str,
    candidate_roots: list[Path],
    allow_fallback: bool,
) -> Path | None:
    outputs_by_id: dict[str, list[dict[str, Any]]] = {}
    outputs_all: list[dict[str, Any]] = []
    for renderer_manifest in _dict_list(render_manifest.get("renderer_manifests")):
        for output in _dict_list(renderer_manifest.get("outputs")):
            output_id = _coerce_str(output.get("output_id")).strip()
            if output_id:
                outputs_by_id.setdefault(output_id, []).append(output)
            outputs_all.append(output)

    for output_id in list(outputs_by_id.keys()):
        outputs_by_id[output_id] = sorted(
            outputs_by_id[output_id],
            key=_render_output_sort_key,
        )
    outputs_all = sorted(outputs_all, key=_render_output_sort_key)

    preferred_output_ids: list[str] = []
    for deliverable in sorted(
        _dict_list(render_manifest.get("deliverables")),
        key=lambda item: _coerce_str(item.get("deliverable_id")).strip(),
    ):
        deliverable_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip()
        if deliverable_layout_id != target_layout_id:
            continue
        for output_id in sorted(
            {
                _coerce_str(output_id).strip()
                for output_id in deliverable.get("output_ids", [])
                if isinstance(output_id, str) and _coerce_str(output_id).strip()
            }
        ):
            preferred_output_ids.append(output_id)

    for output_id in preferred_output_ids:
        for output in outputs_by_id.get(output_id, []):
            resolved = _resolve_wav_output_path(
                output=output,
                candidate_roots=candidate_roots,
            )
            if resolved is not None:
                return resolved

    if not allow_fallback:
        return None

    for output in outputs_all:
        resolved = _resolve_wav_output_path(
            output=output,
            candidate_roots=candidate_roots,
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_render_many_stereo_audio_path(
    *,
    variant_artifacts: list[dict[str, Any]],
    stereo_layout_id: str,
) -> Path | None:
    for artifact in variant_artifacts:
        target_id = _coerce_str(artifact.get("target_id")).strip()
        target_layout_id = _coerce_str(artifact.get("target_layout_id")).strip()
        if target_id != _BASELINE_RENDER_TARGET_ID and target_layout_id != stereo_layout_id:
            continue

        render_manifest_path = artifact.get("render_manifest_path")
        if not isinstance(render_manifest_path, Path) or not render_manifest_path.exists():
            continue
        if render_manifest_path.is_dir():
            continue

        try:
            render_manifest = _load_json_object(
                render_manifest_path,
                label=f"Render manifest ({artifact.get('variant_id')})",
            )
        except ValueError:
            continue

        candidate_roots: list[Path] = []
        out_dir = artifact.get("out_dir")
        if isinstance(out_dir, Path):
            candidate_roots.append((out_dir / "render").resolve())
            candidate_roots.append(out_dir.resolve())
        candidate_roots.append((render_manifest_path.parent / "render").resolve())
        candidate_roots.append(render_manifest_path.parent.resolve())

        deduped_roots: list[Path] = []
        seen_roots: set[str] = set()
        for root in candidate_roots:
            token = root.as_posix()
            if token in seen_roots:
                continue
            seen_roots.add(token)
            deduped_roots.append(root)

        resolved = _wav_output_path_from_manifest(
            render_manifest=render_manifest,
            target_layout_id=stereo_layout_id,
            candidate_roots=deduped_roots,
            allow_fallback=(target_id == _BASELINE_RENDER_TARGET_ID),
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_render_many_translation_cache_dir(
    *,
    root_out_dir: Path,
    cache_dir: Path | None,
) -> Path:
    if isinstance(cache_dir, Path):
        return cache_dir
    return root_out_dir / ".mmo_cache"


def _run_render_many_translation_checks(
    *,
    repo_root: Path,
    root_out_dir: Path,
    report_path: Path,
    variant_result: dict[str, Any],
    profile_ids: list[str],
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    timeline_path: Path | None,
    cache_dir: Path | None,
    use_cache: bool,
) -> None:
    if not profile_ids:
        return

    variant_artifacts = _render_many_variant_artifacts(
        variant_result=variant_result,
        root_out_dir=root_out_dir,
    )
    fallback_render_manifest_path: Path | None = None
    for artifact in variant_artifacts:
        manifest_path = artifact.get("render_manifest_path")
        if isinstance(manifest_path, Path) and manifest_path.exists() and not manifest_path.is_dir():
            fallback_render_manifest_path = manifest_path
            break

    resolved_deliverables_index_path = (
        deliverables_index_path
        if isinstance(deliverables_index_path, Path)
        else root_out_dir / "deliverables_index.json"
    )
    try:
        translation_audio_path, translation_reference_meta = resolve_translation_reference_audio(
            out_dir=root_out_dir,
            deliverables_index_path=resolved_deliverables_index_path,
            render_manifest_path=fallback_render_manifest_path,
        )
    except (TranslationReferenceResolutionError, ValueError):
        return

    translation_profiles_path = repo_root / "ontology" / "translation_profiles.yaml"
    translation_profiles: dict[str, dict[str, Any]]
    translation_reference_payload: dict[str, Any] = dict(translation_reference_meta)
    audio_rel_path = _rel_path_if_under_root(root_out_dir, translation_audio_path)
    translation_reference_payload["audio_path"] = (
        audio_rel_path
        if isinstance(audio_rel_path, str) and audio_rel_path
        else translation_audio_path.resolve().as_posix()
    )
    try:
        translation_results = _build_translation_run_payload(
            translation_profiles_path=translation_profiles_path,
            audio_path=translation_audio_path,
            profile_ids=profile_ids,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        translation_results = _sorted_translation_results(translation_results)
        translation_profiles = load_translation_profiles(translation_profiles_path)
    except ValueError:
        return

    try:
        _write_report_with_translation_results(
            report_in_path=report_path,
            report_out_path=report_path,
            translation_results=translation_results,
            repo_root=repo_root,
            profiles=translation_profiles,
            translation_reference=translation_reference_payload,
        )
    except (SystemExit, ValueError):
        return

    for artifact in variant_artifacts:
        variant_report_path = artifact.get("report_path")
        if isinstance(variant_report_path, Path) and variant_report_path.exists():
            try:
                _write_report_with_translation_results(
                    report_in_path=variant_report_path,
                    report_out_path=variant_report_path,
                    translation_results=translation_results,
                    repo_root=repo_root,
                    profiles=translation_profiles,
                    translation_reference=translation_reference_payload,
                )
            except (SystemExit, ValueError):
                continue

        variant_bundle_path = artifact.get("bundle_path")
        if not isinstance(variant_bundle_path, Path):
            continue
        if not isinstance(variant_report_path, Path) or not variant_report_path.exists():
            continue

        try:
            _run_bundle(
                repo_root=repo_root,
                report_path=variant_report_path,
                out_path=variant_bundle_path,
                render_manifest_path=artifact.get("render_manifest_path"),
                apply_manifest_path=artifact.get("apply_manifest_path"),
                applied_report_path=artifact.get("applied_report_path"),
                project_path=project_path,
                deliverables_index_path=deliverables_index_path,
                listen_pack_path=listen_pack_path,
                scene_path=None,
                render_plan_path=None,
                stems_index_path=None,
                stems_map_path=None,
                timeline_path=timeline_path,
            )
        except ValueError:
            continue


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _render_many_rel_posix(path: Path, *, root_out_dir: Path) -> str | None:
    rel_path = _rel_path_if_under_root(root_out_dir, path)
    if isinstance(rel_path, str) and rel_path:
        return rel_path
    return None


def _render_many_rel_posix_from_value(
    path_value: Any,
    *,
    root_out_dir: Path,
) -> str | None:
    raw = _coerce_str(path_value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root_out_dir / candidate).resolve()
    return _render_many_rel_posix(resolved, root_out_dir=root_out_dir)


def _translation_audition_summary_from_manifest(
    *,
    root_out_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    manifest_rel_path = _render_many_rel_posix(
        manifest_path.resolve(),
        root_out_dir=root_out_dir,
    )
    if manifest_rel_path is None:
        raise ValueError(f"Translation audition manifest path is outside root_out_dir: {manifest_path}")

    renders: list[dict[str, Any]] = []
    for row in _dict_list(manifest.get("renders")):
        profile_id = _coerce_str(row.get("profile_id")).strip()
        rel_render_path = _render_many_rel_posix_from_value(
            row.get("path"),
            root_out_dir=root_out_dir,
        )
        if not profile_id or rel_render_path is None:
            continue

        notes_raw = row.get("notes")
        notes = [
            item.strip()
            for item in notes_raw
            if isinstance(item, str) and item.strip()
        ] if isinstance(notes_raw, list) else []
        renders.append(
            {
                "profile_id": profile_id,
                "path": rel_render_path,
                "notes": notes,
            }
        )

    if not renders:
        return None
    renders.sort(
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            _coerce_str(item.get("path")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )

    segment_raw = manifest.get("segment")
    segment_payload: dict[str, float] | None = None
    if isinstance(segment_raw, dict):
        start_s = _coerce_float(segment_raw.get("start_s"))
        end_s = _coerce_float(segment_raw.get("end_s"))
        if start_s is not None and end_s is not None:
            segment_payload = {
                "start_s": start_s,
                "end_s": end_s,
            }

    return {
        "manifest_path": manifest_rel_path,
        "renders": renders,
        "segment": segment_payload,
    }


def _write_render_many_listen_pack_translation_auditions(
    *,
    root_out_dir: Path,
    listen_pack_path: Path | None,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    if not isinstance(listen_pack_path, Path):
        return
    if not listen_pack_path.exists() or listen_pack_path.is_dir():
        return

    resolved_root = root_out_dir.resolve()
    listen_pack_payload = _load_json_object(listen_pack_path, label="Listen pack")
    summary = _translation_audition_summary_from_manifest(
        root_out_dir=resolved_root,
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if summary is None:
        listen_pack_payload.pop("translation_auditions", None)
    else:
        listen_pack_payload["translation_auditions"] = summary

    _write_json_file(listen_pack_path, listen_pack_payload)


def _run_render_many_translation_auditions(
    *,
    repo_root: Path,
    root_out_dir: Path,
    variant_result: dict[str, Any],
    profile_ids: list[str],
    segment_s: float | None,
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    timeline_path: Path | None,
    cache_dir: Path | None,
    use_cache: bool,
) -> None:
    if not profile_ids:
        return

    stereo_target = get_render_target(
        _BASELINE_RENDER_TARGET_ID,
        repo_root / "ontology" / "render_targets.yaml",
    )
    if not isinstance(stereo_target, dict):
        return
    stereo_layout_id = _coerce_str(stereo_target.get("layout_id")).strip()
    if not stereo_layout_id:
        return

    variant_artifacts = _render_many_variant_artifacts(
        variant_result=variant_result,
        root_out_dir=root_out_dir,
    )
    stereo_audio_path = _resolve_render_many_stereo_audio_path(
        variant_artifacts=variant_artifacts,
        stereo_layout_id=stereo_layout_id,
    )
    if stereo_audio_path is None:
        return

    translation_profiles_path = repo_root / "ontology" / "translation_profiles.yaml"
    auditions_out_dir = root_out_dir / "listen_pack" / "translation_auditions"
    manifest_path = auditions_out_dir / "manifest.json"
    try:
        manifest = _build_translation_audition_payload(
            translation_profiles_path=translation_profiles_path,
            audio_path=stereo_audio_path,
            out_dir=auditions_out_dir,
            profile_ids=profile_ids,
            segment_s=segment_s,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        _write_translation_audition_manifest(manifest_path, manifest)
        _write_render_many_listen_pack_translation_auditions(
            root_out_dir=root_out_dir,
            listen_pack_path=listen_pack_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

        if not isinstance(listen_pack_path, Path):
            return
        if not listen_pack_path.exists() or listen_pack_path.is_dir():
            return

        for artifact in variant_artifacts:
            variant_report_path = artifact.get("report_path")
            variant_bundle_path = artifact.get("bundle_path")
            if not isinstance(variant_bundle_path, Path):
                continue
            if not isinstance(variant_report_path, Path) or not variant_report_path.exists():
                continue
            if variant_report_path.is_dir():
                continue

            try:
                _run_bundle(
                    repo_root=repo_root,
                    report_path=variant_report_path,
                    out_path=variant_bundle_path,
                    render_manifest_path=artifact.get("render_manifest_path"),
                    apply_manifest_path=artifact.get("apply_manifest_path"),
                    applied_report_path=artifact.get("applied_report_path"),
                    project_path=project_path,
                    deliverables_index_path=deliverables_index_path,
                    listen_pack_path=listen_pack_path,
                    scene_path=None,
                    render_plan_path=None,
                    stems_index_path=None,
                    stems_map_path=None,
                    timeline_path=timeline_path,
                )
            except ValueError:
                continue
    except Exception as exc:
        print(
            f"warning: translation audition skipped: {exc}",
            file=sys.stderr,
        )


def _load_report_from_path_or_dir(path: Path) -> tuple[dict[str, Any], Path | None]:
    if path.is_dir():
        report_path = path / "report.json"
        if not report_path.exists():
            raise ValueError(f"Missing report.json in directory: {path}")
        if report_path.is_dir():
            raise ValueError(f"Expected report JSON file path, got directory: {report_path}")
        return _load_report(report_path), path

    if not path.exists():
        raise ValueError(f"Report path does not exist: {path}")
    if path.is_dir():
        raise ValueError(f"Expected report JSON file path, got directory: {path}")
    return _load_report(path), None


def _format_confidence(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "0.00"
    clamped = max(0.0, min(1.0, float(value)))
    return f"{clamped:.2f}"


def _build_render_target_recommendations_payload(
    *,
    repo_root: Path,
    render_targets_path: Path,
    report_input: str | None,
    scene_input: str | None,
    max_results: int,
) -> list[dict[str, Any]]:
    if max_results <= 0:
        raise ValueError("--max must be greater than 0.")

    report_payload: dict[str, Any] | None = None
    report_dir: Path | None = None
    if isinstance(report_input, str) and report_input.strip():
        report_payload, report_dir = _load_report_from_path_or_dir(Path(report_input))

    scene_payload: dict[str, Any] | None = None
    if isinstance(scene_input, str) and scene_input.strip():
        scene_path = Path(scene_input)
        if scene_path.is_dir():
            raise ValueError(f"Expected scene JSON file path, got directory: {scene_path}")
        scene_payload = _load_json_object(scene_path, label="Scene")
    elif report_dir is not None:
        auto_scene_path = report_dir / "scene.json"
        if auto_scene_path.exists():
            if auto_scene_path.is_dir():
                raise ValueError(
                    f"Expected scene JSON file path, got directory: {auto_scene_path}"
                )
            scene_payload = _load_json_object(auto_scene_path, label="Scene")

    return recommend_render_targets(
        repo_root=repo_root,
        render_targets_path=render_targets_path,
        report=report_payload,
        scene=scene_payload,
        max_results=max_results,
    )


def _render_target_recommendations_text(payload: list[dict[str, Any]]) -> str:
    lines = ["Recommended targets:"]
    if not payload:
        lines.append("  (none)")
        return "\n".join(lines)

    for row in payload:
        rank = row.get("rank")
        target_id = _coerce_str(row.get("target_id")).strip()
        lines.append(
            f"  {rank}) {target_id} (conf={_format_confidence(row.get('confidence'))})"
        )
        reasons = row.get("reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                if isinstance(reason, str):
                    lines.append(f"     - {reason}")
    return "\n".join(lines)


def _render_target_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("target_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"layout_id: {_coerce_str(payload.get('layout_id')).strip()}",
        f"channel_order_ref: {_coerce_str(payload.get('channel_order_ref')).strip()}",
    ]

    aliases = payload.get("aliases")
    normalized_aliases = (
        [item for item in aliases if isinstance(item, str) and item.strip()]
        if isinstance(aliases, list)
        else []
    )
    if normalized_aliases:
        lines.append("aliases:")
        for alias in normalized_aliases:
            lines.append(f"- {alias}")

    downmix_policy_id = _coerce_str(payload.get("downmix_policy_id")).strip()
    safety_policy_id = _coerce_str(payload.get("safety_policy_id")).strip()
    lines.append(f"downmix_policy_id: {downmix_policy_id or '(none)'}")
    lines.append(f"safety_policy_id: {safety_policy_id or '(none)'}")

    speaker_positions = payload.get("speaker_positions")
    if isinstance(speaker_positions, list) and speaker_positions:
        lines.append("speaker_positions:")
        for position in speaker_positions:
            if not isinstance(position, dict):
                continue
            ch = position.get("ch")
            azimuth_deg = position.get("azimuth_deg")
            elevation_deg = position.get("elevation_deg")
            lines.append(
                f"- ch={ch} azimuth_deg={azimuth_deg} elevation_deg={elevation_deg}"
            )

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes:")
        for item in notes:
            if isinstance(item, str):
                lines.append(f"- {item}")
    return "\n".join(lines)


def _build_scene_lock_list_payload(*, scene_locks_path: Path) -> list[dict[str, Any]]:
    return list_scene_locks(scene_locks_path)


def _build_scene_lock_show_payload(
    *,
    scene_locks_path: Path,
    lock_id: str,
) -> dict[str, Any]:
    normalized_lock_id = lock_id.strip() if isinstance(lock_id, str) else ""
    if not normalized_lock_id:
        raise ValueError("lock_id must be a non-empty string.")

    payload = get_scene_lock(normalized_lock_id, scene_locks_path)
    if payload is None:
        locks = list_scene_locks(scene_locks_path)
        available = ", ".join(
            item["lock_id"] for item in locks if isinstance(item.get("lock_id"), str)
        )
        if available:
            raise ValueError(
                f"Unknown lock_id: {normalized_lock_id}. Available locks: {available}"
            )
        raise ValueError(
            f"Unknown lock_id: {normalized_lock_id}. No scene locks are available."
        )
    return payload


def _render_scene_lock_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("lock_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"description: {_coerce_str(payload.get('description')).strip()}",
        f"severity: {_coerce_str(payload.get('severity')).strip()}",
    ]
    applies_to = payload.get("applies_to")
    normalized_applies_to = (
        [
            item.strip()
            for item in applies_to
            if isinstance(item, str) and item.strip()
        ]
        if isinstance(applies_to, list)
        else []
    )
    lines.append(f"applies_to: {', '.join(normalized_applies_to)}")
    help_id = _coerce_str(payload.get("help_id")).strip()
    lines.append(f"help_id: {help_id or '(none)'}")
    return "\n".join(lines)


def _build_scene_template_list_payload(
    *,
    scene_templates_path: Path,
) -> list[dict[str, Any]]:
    return list_scene_templates(scene_templates_path)


def _build_scene_template_show_payload(
    *,
    scene_templates_path: Path,
    template_ids: list[str],
) -> list[dict[str, Any]]:
    normalized_template_ids = [
        template_id.strip()
        for template_id in template_ids
        if isinstance(template_id, str) and template_id.strip()
    ]
    if not normalized_template_ids:
        raise ValueError("At least one template_id is required.")

    available_templates = list_scene_templates(scene_templates_path)
    available_ids = [
        item.get("template_id")
        for item in available_templates
        if isinstance(item, dict) and isinstance(item.get("template_id"), str)
    ]
    available_ids_set = set(available_ids)
    unknown_ids = sorted(
        {
            template_id
            for template_id in normalized_template_ids
            if template_id not in available_ids_set
        }
    )
    if unknown_ids:
        unknown_label = ", ".join(unknown_ids)
        available_label = ", ".join(sorted(available_ids))
        if available_label:
            raise ValueError(
                f"Unknown template_id: {unknown_label}. Available templates: {available_label}"
            )
        raise ValueError(
            f"Unknown template_id: {unknown_label}. No scene templates are available."
        )

    payload: list[dict[str, Any]] = []
    for template_id in normalized_template_ids:
        template_payload = get_scene_template(template_id, scene_templates_path)
        if isinstance(template_payload, dict):
            payload.append(template_payload)
    return payload


def _render_scene_template_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("template_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"description: {_coerce_str(payload.get('description')).strip()}",
    ]
    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes:")
        for item in notes:
            if isinstance(item, str):
                lines.append(f"- {item}")
    patches = payload.get("patches")
    if isinstance(patches, list) and patches:
        lines.append("patches:")
        for patch in patches:
            if isinstance(patch, dict):
                lines.append(f"- {json.dumps(patch, sort_keys=True)}")
    return "\n".join(lines)


def _parse_scene_template_ids_csv(raw_value: str) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("scene templates must be a comma-separated string.")

    template_ids = [
        template_id.strip()
        for template_id in raw_value.split(",")
        if isinstance(template_id, str) and template_id.strip()
    ]
    if not template_ids:
        raise ValueError("scene templates must include at least one template ID.")
    return template_ids


def _parse_target_ids_csv(raw_value: str, *, render_targets_path: Path) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("targets must be a comma-separated string.")

    selected: set[str] = set()
    for item in raw_value.split(","):
        normalized = item.strip()
        if normalized:
            selected.add(resolve_render_target_id(normalized, render_targets_path))

    if not selected:
        raise ValueError("targets must include at least one target ID or alias.")
    return sorted(selected)


def _build_selected_render_targets_payload(
    *,
    target_ids: list[str],
    render_targets_path: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    resolved_target_ids = sorted(
        {
            resolve_render_target_id(target_id, render_targets_path)
            for target_id in target_ids
        }
    )
    for target_id in resolved_target_ids:
        payload = get_render_target(target_id, render_targets_path)
        if payload is None:
            raise ValueError(f"Resolved target is missing from registry: {target_id}")
        rows.append(dict(payload))
    return {"targets": rows}


def _default_render_plan_targets_payload(
    *,
    report: dict[str, Any],
    render_targets_path: Path,
) -> dict[str, Any]:
    targets = list_render_targets(render_targets_path)
    by_target_id: dict[str, dict[str, Any]] = {}
    by_layout_id: dict[str, str] = {}
    for target in targets:
        target_id = _coerce_str(target.get("target_id")).strip()
        layout_id = _coerce_str(target.get("layout_id")).strip()
        if not target_id:
            continue
        by_target_id[target_id] = dict(target)
        if layout_id and layout_id not in by_layout_id:
            by_layout_id[layout_id] = target_id

    selected_ids: set[str] = set()
    if _BASELINE_RENDER_TARGET_ID in by_target_id:
        selected_ids.add(_BASELINE_RENDER_TARGET_ID)

    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        downmix_cfg = run_config.get("downmix")
        if isinstance(downmix_cfg, dict):
            layout_id = _coerce_str(downmix_cfg.get("target_layout_id")).strip()
            target_id = by_layout_id.get(layout_id)
            if target_id:
                selected_ids.add(target_id)

    routing_plan = report.get("routing_plan")
    if isinstance(routing_plan, dict):
        layout_id = _coerce_str(routing_plan.get("target_layout_id")).strip()
        target_id = by_layout_id.get(layout_id)
        if target_id:
            selected_ids.add(target_id)

    if not selected_ids and by_target_id:
        selected_ids.add(sorted(by_target_id.keys())[0])

    return {
        "targets": [
            by_target_id[target_id]
            for target_id in sorted(selected_ids)
            if target_id in by_target_id
        ]
    }


def _render_plan_policies_from_report(report: dict[str, Any]) -> dict[str, str]:
    policies: dict[str, str] = {}
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        downmix_cfg = run_config.get("downmix")
        if isinstance(downmix_cfg, dict):
            policy_id = _coerce_str(downmix_cfg.get("policy_id")).strip()
            if policy_id:
                policies["downmix_policy_id"] = policy_id
    return policies


def _build_help_list_payload(*, help_registry_path: Path) -> list[dict[str, str]]:
    from mmo.core.help_registry import load_help_registry  # noqa: WPS433

    registry = load_help_registry(help_registry_path)
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        return []

    payload: list[dict[str, str]] = []
    for help_id in sorted(
        key for key in entries.keys() if isinstance(key, str) and key.strip()
    ):
        entry = entries.get(help_id)
        title = ""
        if isinstance(entry, dict):
            title_value = entry.get("title")
            if isinstance(title_value, str):
                title = title_value
        payload.append({"help_id": help_id, "title": title})
    return payload


def _build_help_show_payload(*, help_registry_path: Path, help_id: str) -> dict[str, Any]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    normalized_help_id = help_id.strip() if isinstance(help_id, str) else ""
    if not normalized_help_id:
        raise ValueError("help_id must be a non-empty string.")

    registry = load_help_registry(help_registry_path)
    resolved = resolve_help_entries([normalized_help_id], registry)
    entry = resolved.get(normalized_help_id)
    payload: dict[str, Any] = {"help_id": normalized_help_id}
    if isinstance(entry, dict):
        payload.update(entry)
    return payload


def _ui_copy_locale_ids(registry: dict[str, Any]) -> list[str]:
    locales = registry.get("locales")
    if not isinstance(locales, dict):
        return []
    return sorted(
        locale_id.strip()
        for locale_id in locales.keys()
        if isinstance(locale_id, str) and locale_id.strip()
    )


def _resolve_ui_copy_locale(*, registry: dict[str, Any], locale: str | None) -> str:
    locale_ids = _ui_copy_locale_ids(registry)
    requested_locale = locale.strip() if isinstance(locale, str) else ""
    if requested_locale:
        if locale_ids and requested_locale not in locale_ids:
            joined_locales = ", ".join(locale_ids)
            raise ValueError(
                f"Unknown locale: {requested_locale}. Available locales: {joined_locales}"
            )
        return requested_locale

    default_locale = registry.get("default_locale")
    normalized_default = default_locale.strip() if isinstance(default_locale, str) else ""
    if normalized_default:
        return normalized_default
    if locale_ids:
        return locale_ids[0]
    raise ValueError("UI copy registry does not define any locales.")


def _build_ui_copy_list_payload(
    *,
    ui_copy_registry_path: Path,
    locale: str | None,
) -> dict[str, Any]:
    from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy  # noqa: WPS433

    registry = load_ui_copy(ui_copy_registry_path)
    resolved_locale = _resolve_ui_copy_locale(registry=registry, locale=locale)
    locales = registry.get("locales")
    locale_payload = (
        locales.get(resolved_locale) if isinstance(locales, dict) else None
    )
    entries = (
        locale_payload.get("entries")
        if isinstance(locale_payload, dict)
        else None
    )
    copy_keys = (
        [copy_id for copy_id in entries.keys() if isinstance(copy_id, str)]
        if isinstance(entries, dict)
        else []
    )
    resolved_entries = resolve_ui_copy(
        copy_keys,
        registry,
        locale=resolved_locale,
    )

    items: list[dict[str, Any]] = []
    for copy_id in sorted(resolved_entries.keys()):
        entry = resolved_entries.get(copy_id)
        row: dict[str, Any] = {"copy_id": copy_id}
        if isinstance(entry, dict):
            row.update(entry)
        items.append(row)
    return {"locale": resolved_locale, "entries": items}


def _build_ui_copy_show_payload(
    *,
    ui_copy_registry_path: Path,
    locale: str | None,
    copy_id: str,
) -> dict[str, Any]:
    from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy  # noqa: WPS433

    normalized_copy_id = copy_id.strip() if isinstance(copy_id, str) else ""
    if not normalized_copy_id:
        raise ValueError("copy_id must be a non-empty string.")

    registry = load_ui_copy(ui_copy_registry_path)
    resolved_locale = _resolve_ui_copy_locale(registry=registry, locale=locale)
    entry = resolve_ui_copy([normalized_copy_id], registry, locale=resolved_locale).get(
        normalized_copy_id
    )
    payload: dict[str, Any] = {
        "locale": resolved_locale,
        "copy_id": normalized_copy_id,
    }
    if isinstance(entry, dict):
        payload.update(entry)
    return payload


def _ui_examples_paths(*, ui_examples_dir: Path) -> list[Path]:
    if not ui_examples_dir.exists():
        raise ValueError(f"UI examples directory does not exist: {ui_examples_dir}")
    if not ui_examples_dir.is_dir():
        raise ValueError(f"UI examples path is not a directory: {ui_examples_dir}")
    return sorted(ui_examples_dir.glob("*.json"), key=lambda path: path.name)


def _build_ui_examples_list_payload(*, ui_examples_dir: Path) -> list[dict[str, Any]]:
    from mmo.core.ui_screen_examples import load_ui_screen_example  # noqa: WPS433

    rows: list[dict[str, Any]] = []
    for path in _ui_examples_paths(ui_examples_dir=ui_examples_dir):
        payload = load_ui_screen_example(path)
        rows.append(
            {
                "filename": path.name,
                "screen_id": payload.get("screen_id", ""),
                "mode": payload.get("mode", ""),
                "title": payload.get("title", ""),
                "description": payload.get("description", ""),
            }
        )
    return rows


def _build_ui_examples_show_payload(
    *,
    ui_examples_dir: Path,
    filename: str,
) -> dict[str, Any]:
    from mmo.core.ui_screen_examples import load_ui_screen_example  # noqa: WPS433

    normalized_filename = filename.strip() if isinstance(filename, str) else ""
    if not normalized_filename:
        raise ValueError("filename must be a non-empty string.")
    if normalized_filename != Path(normalized_filename).name:
        raise ValueError("filename must not include a directory path.")
    if not normalized_filename.endswith(".json"):
        raise ValueError("filename must end with .json.")

    candidate = ui_examples_dir / normalized_filename
    if not candidate.exists():
        available = ", ".join(
            path.name for path in _ui_examples_paths(ui_examples_dir=ui_examples_dir)
        )
        raise ValueError(
            f"Unknown ui example filename: {normalized_filename}. "
            f"Available files: {available}"
        )

    payload = load_ui_screen_example(candidate)
    result = dict(payload)
    result["filename"] = normalized_filename
    return result


def _build_plugins_list_payload(*, plugins_dir: Path) -> list[dict[str, Any]]:
    from mmo.core.pipeline import load_plugins  # noqa: WPS433

    plugins = load_plugins(plugins_dir)
    payload: list[dict[str, Any]] = []
    for plugin in plugins:
        row: dict[str, Any] = {
            "plugin_id": plugin.plugin_id,
            "plugin_type": plugin.plugin_type,
            "version": plugin.version or "",
            "capabilities": {},
        }
        if plugin.capabilities is not None:
            row["capabilities"] = plugin.capabilities.to_dict()
        payload.append(row)
    return payload


def _render_plugins_list_text(payload: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in payload:
        plugin_id = row.get("plugin_id", "")
        capabilities = row.get("capabilities")
        max_channels = "-"
        contexts = "-"
        scene = "-"
        if isinstance(capabilities, dict):
            max_channels_value = capabilities.get("max_channels")
            if isinstance(max_channels_value, int):
                max_channels = str(max_channels_value)
            supported_contexts = capabilities.get("supported_contexts")
            if isinstance(supported_contexts, list):
                contexts_list = [
                    item for item in supported_contexts if isinstance(item, str) and item
                ]
                if contexts_list:
                    contexts = ",".join(contexts_list)
            scene_payload = capabilities.get("scene")
            if isinstance(scene_payload, dict):
                scene_parts: list[str] = []
                if scene_payload.get("supports_objects") is True:
                    scene_parts.append("objects")
                if scene_payload.get("supports_beds") is True:
                    scene_parts.append("beds")
                if scene_payload.get("supports_locks") is True:
                    scene_parts.append("locks")
                if scene_payload.get("requires_speaker_positions") is True:
                    scene_parts.append("requires_speaker_positions")
                supported_target_ids = scene_payload.get("supported_target_ids")
                if isinstance(supported_target_ids, list):
                    target_ids = [
                        item
                        for item in supported_target_ids
                        if isinstance(item, str) and item
                    ]
                    if target_ids:
                        scene_parts.append(f"targets={','.join(target_ids)}")
                if scene_parts:
                    scene = ",".join(scene_parts)
        lines.append(
            f"{plugin_id} (max_channels={max_channels}) contexts={contexts} scene={scene}"
        )
    return "\n".join(lines)


def _print_lock_verify_summary(verify_result: dict[str, Any]) -> None:
    missing = verify_result.get("missing", [])
    extra = verify_result.get("extra", [])
    changed = verify_result.get("changed", [])
    ok = bool(verify_result.get("ok"))

    status = "ok" if ok else "drift detected"
    print(f"lock verify: {status}")
    print(
        "summary:"
        f" missing={len(missing)}"
        f" extra={len(extra)}"
        f" changed={len(changed)}"
    )

    for rel in missing:
        print(f"- missing: {rel}")
    for rel in extra:
        print(f"- extra: {rel}")
    for item in changed:
        if not isinstance(item, dict):
            continue
        rel = item.get("rel", "")
        expected_sha = item.get("expected_sha", "")
        actual_sha = item.get("actual_sha", "")
        print(
            f"- changed: {rel}"
            f" expected_sha={expected_sha}"
            f" actual_sha={actual_sha}"
        )


def _build_validated_listen_pack(
    *,
    repo_root: Path,
    presets_dir: Path,
    variant_result: dict[str, Any],
) -> dict[str, Any]:
    listen_pack = build_listen_pack(variant_result, presets_dir)
    _validate_json_payload(
        listen_pack,
        schema_path=repo_root / "schemas" / "listen_pack.schema.json",
        payload_name="Listen pack",
    )
    return listen_pack


def _build_validated_deliverables_index_single(
    *,
    repo_root: Path,
    out_dir: Path,
    report_path: Path,
    apply_manifest_path: Path | None,
    render_manifest_path: Path | None,
    bundle_path: Path | None,
    pdf_path: Path | None,
    csv_path: Path | None,
) -> dict[str, Any]:
    deliverables_index = build_deliverables_index_single(
        out_dir=out_dir,
        report_path=report_path,
        apply_manifest_path=apply_manifest_path,
        render_manifest_path=render_manifest_path,
        bundle_path=bundle_path,
        pdf_path=pdf_path,
        csv_path=csv_path,
    )
    _validate_json_payload(
        deliverables_index,
        schema_path=repo_root / "schemas" / "deliverables_index.schema.json",
        payload_name="Deliverables index",
    )
    return deliverables_index


def _build_validated_deliverables_index_variants(
    *,
    repo_root: Path,
    root_out_dir: Path,
    variant_result: dict[str, Any],
) -> dict[str, Any]:
    deliverables_index = build_deliverables_index_variants(
        root_out_dir=root_out_dir,
        variant_result=variant_result,
    )
    _validate_json_payload(
        deliverables_index,
        schema_path=repo_root / "schemas" / "deliverables_index.schema.json",
        payload_name="Deliverables index",
    )
    return deliverables_index


def _existing_file(path: Path) -> Path | None:
    if path.exists():
        return path
    return None


def _run_deliverables_index_command(
    *,
    repo_root: Path,
    out_dir: Path,
    out_path: Path,
    variant_result_path: Path | None,
) -> int:
    resolved_out_dir = out_dir.resolve()
    try:
        if variant_result_path is not None:
            variant_result = _load_json_object(variant_result_path, label="Variant result")
            payload = _build_validated_deliverables_index_variants(
                repo_root=repo_root,
                root_out_dir=resolved_out_dir,
                variant_result=variant_result,
            )
        else:
            report_path = _existing_file(resolved_out_dir / "report.json")
            if report_path is None:
                print(
                    "Missing report.json in --out-dir. Cannot build single deliverables index.",
                    file=sys.stderr,
                )
                return 1
            payload = _build_validated_deliverables_index_single(
                repo_root=repo_root,
                out_dir=resolved_out_dir,
                report_path=report_path,
                apply_manifest_path=_existing_file(resolved_out_dir / "apply_manifest.json"),
                render_manifest_path=_existing_file(resolved_out_dir / "render_manifest.json"),
                bundle_path=_existing_file(resolved_out_dir / "ui_bundle.json"),
                pdf_path=_existing_file(resolved_out_dir / "report.pdf"),
                csv_path=_existing_file(resolved_out_dir / "recall.csv"),
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(out_path, payload)
    return 0


def _run_variants_listen_pack_command(
    *,
    repo_root: Path,
    presets_dir: Path,
    variant_result_path: Path,
    out_path: Path,
) -> int:
    try:
        variant_result = _load_json_object(variant_result_path, label="Variant result")
        listen_pack = _build_validated_listen_pack(
            repo_root=repo_root,
            presets_dir=presets_dir,
            variant_result=variant_result,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(out_path, listen_pack)
    return 0


def _run_variants_workflow(
    *,
    repo_root: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_values: list[str] | None,
    config_values: list[str] | None,
    apply: bool,
    render: bool,
    export_pdf: bool,
    export_csv: bool,
    bundle: bool,
    scene: bool,
    render_plan: bool = False,
    profile: str | None = None,
    meters: str | None = None,
    max_seconds: float | None = None,
    routing: bool = False,
    source_layout: str | None = None,
    target_layout: str | None = None,
    downmix_qa: bool = False,
    qa_ref: str | None = None,
    qa_meters: str | None = None,
    qa_max_seconds: float | None = None,
    policy_id: str | None = None,
    truncate_values: int | None = None,
    output_formats: str | None = None,
    render_output_formats: str | None = None,
    apply_output_formats: str | None = None,
    format_set_values: list[str] | None = None,
    listen_pack: bool = False,
    deliverables_index: bool = False,
    project_path: Path | None = None,
    timeline_path: Path | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    run_config_overrides: dict[str, Any] = {}
    if profile is not None:
        run_config_overrides["profile_id"] = profile
    if meters is not None:
        run_config_overrides["meters"] = meters
    if max_seconds is not None:
        run_config_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_config_overrides["truncate_values"] = truncate_values
    if source_layout is not None:
        _set_nested(
            ["downmix", "source_layout_id"],
            run_config_overrides,
            source_layout,
        )
    if target_layout is not None:
        _set_nested(
            ["downmix", "target_layout_id"],
            run_config_overrides,
            target_layout,
        )
    if policy_id is not None:
        _set_nested(
            ["downmix", "policy_id"],
            run_config_overrides,
            policy_id,
        )
    if downmix_qa and not qa_ref:
        print(
            "Missing --qa-ref. Provide a stereo reference path when --downmix-qa is enabled.",
            file=sys.stderr,
        )
        return 1
    if qa_max_seconds is not None and qa_max_seconds < 0:
        print("--qa-max-seconds must be >= 0.", file=sys.stderr)
        return 1

    resolved_timeline_path: Path | None = None
    normalized_timeline: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            normalized_timeline = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    shared_output_formats: list[str] | None = None
    if output_formats is not None:
        try:
            shared_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    resolved_render_output_formats = (
        list(shared_output_formats) if isinstance(shared_output_formats, list) else None
    )
    if render_output_formats is not None:
        try:
            resolved_render_output_formats = _parse_output_formats_csv(
                render_output_formats
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    resolved_apply_output_formats = (
        list(shared_output_formats) if isinstance(shared_output_formats, list) else None
    )
    if apply_output_formats is not None:
        try:
            resolved_apply_output_formats = _parse_output_formats_csv(apply_output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if resolved_render_output_formats is not None:
        _set_nested(
            ["render", "output_formats"],
            run_config_overrides,
            resolved_render_output_formats,
        )
    if resolved_apply_output_formats is not None:
        _set_nested(
            ["apply", "output_formats"],
            run_config_overrides,
            resolved_apply_output_formats,
        )

    format_sets: list[tuple[str, list[str]]] | None = None
    if isinstance(format_set_values, list) and format_set_values:
        try:
            format_sets = _parse_output_format_sets(format_set_values)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    steps = {
        "analyze": True,
        "routing": routing,
        "downmix_qa": downmix_qa,
        "export_pdf": export_pdf,
        "export_csv": export_csv,
        "apply": apply,
        "render": render,
        "bundle": bundle,
    }
    try:
        plan = build_variant_plan(
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_ids=list(preset_values) if isinstance(preset_values, list) else None,
            config_paths=(
                [Path(item) for item in config_values]
                if isinstance(config_values, list)
                else None
            ),
            cli_run_config_overrides=run_config_overrides,
            steps=steps,
            format_sets=format_sets,
            presets_dir=presets_dir,
            source_layout_id=source_layout,
            target_layout_id=target_layout,
            qa_ref_path=Path(qa_ref) if qa_ref else None,
            qa_meters=qa_meters,
            qa_max_seconds=qa_max_seconds,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    plan_path = out_dir / "variant_plan.json"
    result_path = out_dir / "variant_result.json"
    listen_pack_path = out_dir / "listen_pack.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    try:
        _validate_json_payload(
            plan,
            schema_path=repo_root / "schemas" / "variant_plan.schema.json",
            payload_name="Variant plan",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(plan_path, plan)
    variants = plan.get("variants")
    if isinstance(variants, list) and len(variants) > 1:
        print("Youll get one folder per variant.")

    try:
        run_variant_plan_kwargs: dict[str, Any] = {
            "cache_enabled": cache_enabled,
            "cache_dir": cache_dir,
        }
        if project_path is not None:
            run_variant_plan_kwargs["project_path"] = project_path
        if deliverables_index:
            run_variant_plan_kwargs["deliverables_index_path"] = deliverables_index_path
        if listen_pack:
            run_variant_plan_kwargs["listen_pack_path"] = listen_pack_path
        if normalized_timeline is not None:
            run_variant_plan_kwargs["timeline"] = normalized_timeline
        if resolved_timeline_path is not None:
            run_variant_plan_kwargs["timeline_path"] = resolved_timeline_path
        run_variant_plan_kwargs["scene"] = scene
        run_variant_plan_kwargs["render_plan"] = render_plan

        result = run_variant_plan(
            plan,
            repo_root=repo_root,
            **run_variant_plan_kwargs,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _validate_json_payload(
            result,
            schema_path=repo_root / "schemas" / "variant_result.schema.json",
            payload_name="Variant result",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(result_path, result)
    if listen_pack:
        try:
            listen_pack_payload = _build_validated_listen_pack(
                repo_root=repo_root,
                presets_dir=presets_dir,
                variant_result=result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(listen_pack_path, listen_pack_payload)
    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_variants(
                repo_root=repo_root,
                root_out_dir=out_dir,
                variant_result=result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    results = result.get("results")
    if not isinstance(results, list):
        return 1
    has_failure = any(
        isinstance(item, dict) and item.get("ok") is not True
        for item in results
    )
    return 1 if has_failure else 0


def _run_one_shot_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_id: str | None,
    config_path: str | None,
    project_path: Path | None,
    timeline_path: Path | None,
    profile: str | None,
    meters: str | None,
    max_seconds: float | None,
    truncate_values: int | None,
    export_pdf: bool,
    export_csv: bool,
    apply: bool,
    render: bool,
    bundle: bool,
    scene: bool,
    render_plan: bool = False,
    deliverables_index: bool = False,
    output_formats: str | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    resolved_timeline_path: Path | None = None
    timeline_payload: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            timeline_payload = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    run_overrides: dict[str, Any] = {}
    if profile is not None:
        run_overrides["profile_id"] = profile
    if meters is not None:
        run_overrides["meters"] = meters
    if max_seconds is not None:
        run_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_overrides["truncate_values"] = truncate_values
    if output_formats is not None:
        try:
            parsed_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _set_nested(["render", "output_formats"], run_overrides, parsed_output_formats)
        _set_nested(["apply", "output_formats"], run_overrides, parsed_output_formats)

    try:
        merged_run_config = _load_and_merge_run_config(
            config_path,
            run_overrides,
            preset_id=preset_id,
            presets_dir=presets_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    effective_profile = _config_string(merged_run_config, "profile_id", "PROFILE.ASSIST")
    effective_meters = _config_optional_string(merged_run_config, "meters", None)
    effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
    effective_run_config = _analyze_run_config(
        profile_id=effective_profile,
        meters=effective_meters,
        preset_id=effective_preset_id,
        base_run_config=merged_run_config,
    )
    effective_truncate_values = _config_int(merged_run_config, "truncate_values", 200)
    render_output_formats = _config_nested_output_formats(
        merged_run_config,
        "render",
        ["wav"],
    )
    apply_output_formats = _config_nested_output_formats(
        merged_run_config,
        "apply",
        ["wav"],
    )

    report_path = out_dir / "report.json"
    pdf_path = out_dir / "report.pdf"
    csv_path = out_dir / "recall.csv"
    apply_manifest_path = out_dir / "apply_manifest.json"
    applied_report_path = out_dir / "applied_report.json"
    render_manifest_path = out_dir / "render_manifest.json"
    bundle_path = out_dir / "ui_bundle.json"
    scene_path = out_dir / "scene.json"
    render_plan_path = out_dir / "render_plan.json"
    routing_plan_path = out_dir / "routing_plan.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    render_out_dir = out_dir / "render"
    apply_out_dir = out_dir / "apply"

    report_schema_path = repo_root / "schemas" / "report.schema.json"
    plugins_dir = str(repo_root / "plugins")
    lock_payload: dict[str, Any] | None = None
    cache_key_value: str | None = None
    report_payload: dict[str, Any] | None = None
    scene_payload: dict[str, Any] | None = None

    out_dir.mkdir(parents=True, exist_ok=True)
    if cache_enabled:
        from mmo.core.lockfile import build_lockfile  # noqa: WPS433

        try:
            lock_payload = build_lockfile(stems_dir)
            cache_key_value = _analysis_cache_key(lock_payload, effective_run_config)
        except ValueError:
            cache_enabled = False
            lock_payload = None
            cache_key_value = None

        if lock_payload is not None:
            cached_report = try_load_cached_report(
                cache_dir,
                lock_payload,
                effective_run_config,
            )
            if (
                isinstance(cached_report, dict)
                and report_schema_is_valid(cached_report, report_schema_path)
            ):
                rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                rewritten_report["run_config"] = normalize_run_config(effective_run_config)
                apply_routing_plan_to_report(rewritten_report, rewritten_report["run_config"])
                if report_schema_is_valid(rewritten_report, report_schema_path):
                    try:
                        _validate_json_payload(
                            rewritten_report,
                            schema_path=report_schema_path,
                            payload_name="Report",
                        )
                    except SystemExit as exc:
                        return int(exc.code) if isinstance(exc.code, int) else 1
                    _write_json_file(report_path, rewritten_report)
                    report_payload = rewritten_report
                    print(f"analysis cache: hit {cache_key_value}")
            if report_payload is None:
                print(f"analysis cache: miss {cache_key_value}")

    if report_payload is None:
        exit_code = _run_analyze(
            tools_dir,
            stems_dir,
            report_path,
            effective_meters,
            False,
            plugins_dir,
            False,
            effective_profile,
        )
        if exit_code != 0:
            return exit_code
        try:
            report_payload = _load_report(report_path)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        report_payload["run_config"] = normalize_run_config(effective_run_config)
        apply_routing_plan_to_report(report_payload, report_payload["run_config"])
        try:
            _validate_json_payload(
                report_payload,
                schema_path=report_schema_path,
                payload_name="Report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(report_path, report_payload)

    if cache_enabled and lock_payload is not None and report_payload is not None:
        if report_schema_is_valid(report_payload, report_schema_path):
            if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
            else:
                try:
                    save_cached_report(
                        cache_dir,
                        lock_payload,
                        effective_run_config,
                        report_payload,
                    )
                except OSError:
                    pass

    if timeline_payload is not None and report_payload is not None:
        report_payload["timeline"] = timeline_payload
        try:
            _validate_json_payload(
                report_payload,
                schema_path=report_schema_path,
                payload_name="Report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(report_path, report_payload)

    if scene or render_plan:
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        try:
            scene_payload = _build_validated_scene_payload(
                repo_root=repo_root,
                report=report_payload,
                timeline_payload=timeline_payload,
                lock_hash=(
                    hash_lockfile(lock_payload)
                    if isinstance(lock_payload, dict)
                    else None
                ),
                created_from="analyze",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)

    if render_plan:
        if report_payload is None or scene_payload is None:
            print("Scene/report payload is unavailable for render plan.", file=sys.stderr)
            return 1
        try:
            render_targets_payload = _default_render_plan_targets_payload(
                report=report_payload,
                render_targets_path=repo_root / "ontology" / "render_targets.yaml",
            )
            routing_plan_artifact_path = _write_routing_plan_artifact(
                repo_root=repo_root,
                report_payload=report_payload,
                out_path=routing_plan_path,
            )

            render_plan_contexts: list[str] = []
            if render:
                render_plan_contexts.append("render")
            if apply:
                render_plan_contexts.append("auto_apply")
            if not render_plan_contexts:
                render_plan_contexts = ["render"]

            render_plan_format_set: set[str] = set()
            if render:
                render_plan_format_set.update(render_output_formats)
            if apply:
                render_plan_format_set.update(apply_output_formats)
            if not render_plan_format_set:
                render_plan_format_set.update(render_output_formats)
            render_plan_output_formats = [
                fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in render_plan_format_set
            ]

            render_plan_payload = _build_validated_render_plan_payload(
                repo_root=repo_root,
                scene_payload=scene_payload,
                scene_path=scene_path,
                render_targets_payload=render_targets_payload,
                routing_plan_path=routing_plan_artifact_path,
                output_formats=render_plan_output_formats,
                contexts=render_plan_contexts,
                policies=_render_plan_policies_from_report(report_payload),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(render_plan_path, render_plan_payload)

    exit_code = _run_export(
        tools_dir,
        report_path,
        str(csv_path) if export_csv else None,
        str(pdf_path) if export_pdf else None,
        no_measurements=False,
        no_gates=False,
        truncate_values=effective_truncate_values,
    )
    if exit_code != 0:
        return exit_code

    if apply:
        try:
            exit_code = _run_apply_command(
                repo_root=repo_root,
                report_path=report_path,
                plugins_dir=Path(plugins_dir),
                out_manifest_path=apply_manifest_path,
                out_dir=apply_out_dir,
                out_report_path=None,
                profile_id=effective_profile,
                output_formats=apply_output_formats,
                run_config=effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

        try:
            apply_manifest = _load_json_object(apply_manifest_path, label="Apply manifest")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        renderer_manifests_raw = apply_manifest.get("renderer_manifests")
        if not isinstance(renderer_manifests_raw, list):
            print("Apply manifest renderer_manifests must be a list.", file=sys.stderr)
            return 1
        renderer_manifests = [
            item for item in renderer_manifests_raw if isinstance(item, dict)
        ]
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        applied_report = _build_applied_report(
            report_payload,
            out_dir=apply_out_dir,
            renderer_manifests=renderer_manifests,
        )
        try:
            _validate_json_payload(
                applied_report,
                schema_path=report_schema_path,
                payload_name="Applied report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(applied_report_path, applied_report)

    if render:
        try:
            exit_code = _run_render_command(
                repo_root=repo_root,
                report_path=report_path,
                plugins_dir=Path(plugins_dir),
                out_manifest_path=render_manifest_path,
                out_dir=render_out_dir,
                profile_id=effective_profile,
                command_label="render",
                output_formats=render_output_formats,
                run_config=effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

    if bundle:
        try:
            exit_code = _run_bundle(
                repo_root=repo_root,
                report_path=report_path,
                out_path=bundle_path,
                render_manifest_path=render_manifest_path if render else None,
                apply_manifest_path=apply_manifest_path if apply else None,
                applied_report_path=applied_report_path if apply else None,
                project_path=project_path,
                deliverables_index_path=(
                    deliverables_index_path if deliverables_index else None
                ),
                listen_pack_path=None,
                scene_path=scene_path if scene_payload is not None else None,
                render_plan_path=render_plan_path if render_plan else None,
                stems_index_path=None,
                stems_map_path=None,
                timeline_path=resolved_timeline_path,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_single(
                repo_root=repo_root,
                out_dir=out_dir,
                report_path=report_path,
                apply_manifest_path=apply_manifest_path if apply else None,
                render_manifest_path=render_manifest_path if render else None,
                bundle_path=bundle_path if bundle else None,
                pdf_path=pdf_path if export_pdf else None,
                csv_path=csv_path if export_csv else None,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    summary: list[tuple[str, Path]] = [("report", report_path)]
    if export_pdf:
        summary.append(("report_pdf", pdf_path))
    if export_csv:
        summary.append(("recall_csv", csv_path))
    if apply:
        summary.append(("apply_manifest", apply_manifest_path))
        summary.append(("applied_report", applied_report_path))
    if render:
        summary.append(("render_manifest", render_manifest_path))
    if bundle:
        summary.append(("ui_bundle", bundle_path))
    if scene_payload is not None:
        summary.append(("scene", scene_path))
    if render_plan:
        summary.append(("render_plan", render_plan_path))
    if deliverables_index:
        summary.append(("deliverables_index", deliverables_index_path))

    print("run complete:")
    for label, path in summary:
        print(f"- {label}: {path.resolve().as_posix()}")
    return 0


def _run_render_many_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_id: str | None,
    config_path: str | None,
    project_path: Path | None,
    timeline_path: Path | None,
    profile: str | None,
    meters: str | None,
    max_seconds: float | None,
    truncate_values: int | None,
    export_pdf: bool,
    export_csv: bool,
    scene_requested: bool,
    render_plan_requested: bool,
    scene_template_ids: list[str] | None,
    target_ids: list[str],
    contexts: list[str],
    deliverables_index: bool,
    listen_pack: bool = False,
    translation_profile_ids: list[str] | None = None,
    translation_audition: bool = False,
    translation_audition_segment_s: float | None = _DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
    output_formats: str | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    resolved_timeline_path: Path | None = None
    timeline_payload: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            timeline_payload = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    run_overrides: dict[str, Any] = {}
    if profile is not None:
        run_overrides["profile_id"] = profile
    if meters is not None:
        run_overrides["meters"] = meters
    if max_seconds is not None:
        run_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_overrides["truncate_values"] = truncate_values
    if output_formats is not None:
        try:
            parsed_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _set_nested(["render", "output_formats"], run_overrides, parsed_output_formats)
        _set_nested(["apply", "output_formats"], run_overrides, parsed_output_formats)

    try:
        merged_run_config = _load_and_merge_run_config(
            config_path,
            run_overrides,
            preset_id=preset_id,
            presets_dir=presets_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    effective_profile = _config_string(merged_run_config, "profile_id", "PROFILE.ASSIST")
    effective_meters = _config_optional_string(merged_run_config, "meters", None)
    effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
    effective_run_config = _analyze_run_config(
        profile_id=effective_profile,
        meters=effective_meters,
        preset_id=effective_preset_id,
        base_run_config=merged_run_config,
    )
    analysis_cache_run_config = _analysis_run_config_for_variant_cache(effective_run_config)
    render_output_formats = _config_nested_output_formats(
        merged_run_config,
        "render",
        ["wav"],
    )
    apply_output_formats = _config_nested_output_formats(
        merged_run_config,
        "apply",
        ["wav"],
    )

    report_path = out_dir / "report.json"
    scene_path = out_dir / "scene.json"
    render_plan_path = out_dir / "render_plan.json"
    routing_plan_path = out_dir / "routing_plan.json"
    variant_plan_path = out_dir / "variant_plan.json"
    variant_result_path = out_dir / "variant_result.json"
    listen_pack_path = out_dir / "listen_pack.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    report_schema_path = repo_root / "schemas" / "report.schema.json"
    plugins_dir = str(repo_root / "plugins")

    out_dir.mkdir(parents=True, exist_ok=True)

    should_build_scene = scene_requested or not scene_path.exists()
    should_build_render_plan = render_plan_requested or not render_plan_path.exists()
    needs_report = should_build_scene or should_build_render_plan

    lock_payload: dict[str, Any] | None = None
    cache_key_value: str | None = None
    report_payload: dict[str, Any] | None = None
    scene_payload: dict[str, Any] | None = None
    render_plan_payload: dict[str, Any] | None = None

    if needs_report:
        if cache_enabled:
            from mmo.core.lockfile import build_lockfile  # noqa: WPS433

            try:
                lock_payload = build_lockfile(stems_dir)
                cache_key_value = _analysis_cache_key(lock_payload, analysis_cache_run_config)
            except ValueError:
                cache_enabled = False
                lock_payload = None
                cache_key_value = None

            if lock_payload is not None:
                cached_report = try_load_cached_report(
                    cache_dir,
                    lock_payload,
                    analysis_cache_run_config,
                )
                if (
                    isinstance(cached_report, dict)
                    and report_schema_is_valid(cached_report, report_schema_path)
                ):
                    rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                    rewritten_report["run_config"] = normalize_run_config(effective_run_config)
                    apply_routing_plan_to_report(rewritten_report, rewritten_report["run_config"])
                    if report_schema_is_valid(rewritten_report, report_schema_path):
                        try:
                            _validate_json_payload(
                                rewritten_report,
                                schema_path=report_schema_path,
                                payload_name="Report",
                            )
                        except SystemExit as exc:
                            return int(exc.code) if isinstance(exc.code, int) else 1
                        _write_json_file(report_path, rewritten_report)
                        report_payload = rewritten_report
                        print(f"analysis cache: hit {cache_key_value}")
                if report_payload is None:
                    print(f"analysis cache: miss {cache_key_value}")

        if report_payload is None:
            exit_code = _run_analyze(
                tools_dir,
                stems_dir,
                report_path,
                effective_meters,
                False,
                plugins_dir,
                False,
                effective_profile,
            )
            if exit_code != 0:
                return exit_code
            try:
                report_payload = _load_report(report_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            report_payload["run_config"] = normalize_run_config(effective_run_config)
            apply_routing_plan_to_report(report_payload, report_payload["run_config"])
            try:
                _validate_json_payload(
                    report_payload,
                    schema_path=report_schema_path,
                    payload_name="Report",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(report_path, report_payload)

        if cache_enabled and lock_payload is not None and report_payload is not None:
            if report_schema_is_valid(report_payload, report_schema_path):
                if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                    print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
                else:
                    try:
                        save_cached_report(
                            cache_dir,
                            lock_payload,
                            analysis_cache_run_config,
                            report_payload,
                        )
                    except OSError:
                        pass

        if timeline_payload is not None and report_payload is not None:
            report_payload["timeline"] = timeline_payload
            try:
                _validate_json_payload(
                    report_payload,
                    schema_path=report_schema_path,
                    payload_name="Report",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(report_path, report_payload)

    if should_build_scene:
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        try:
            scene_payload = _build_validated_scene_payload(
                repo_root=repo_root,
                report=report_payload,
                timeline_payload=timeline_payload,
                lock_hash=(
                    hash_lockfile(lock_payload)
                    if isinstance(lock_payload, dict)
                    else None
                ),
                created_from="analyze",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)
    else:
        try:
            scene_payload = _load_json_object(scene_path, label="Scene")
            _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    if scene_payload is not None and isinstance(scene_template_ids, list) and scene_template_ids:
        try:
            scene_payload = _apply_scene_templates_to_payload(
                repo_root=repo_root,
                scene_payload=scene_payload,
                template_ids=scene_template_ids,
                force=False,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)

    if should_build_render_plan:
        if scene_payload is None:
            print("Scene payload is unavailable for render plan.", file=sys.stderr)
            return 1
        if report_payload is None:
            print("Report payload is unavailable for render plan.", file=sys.stderr)
            return 1
        try:
            render_targets_payload = _build_selected_render_targets_payload(
                target_ids=target_ids,
                render_targets_path=repo_root / "ontology" / "render_targets.yaml",
            )
            routing_plan_artifact_path = _write_routing_plan_artifact(
                repo_root=repo_root,
                report_payload=report_payload,
                out_path=routing_plan_path,
            )
            render_plan_format_set: set[str] = set()
            if "render" in contexts:
                render_plan_format_set.update(render_output_formats)
            if "auto_apply" in contexts:
                render_plan_format_set.update(apply_output_formats)
            if not render_plan_format_set:
                render_plan_format_set.update(render_output_formats)
            render_plan_output_formats = [
                fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in render_plan_format_set
            ]
            render_plan_payload = _build_validated_render_plan_payload(
                repo_root=repo_root,
                scene_payload=scene_payload,
                scene_path=scene_path,
                render_targets_payload=render_targets_payload,
                routing_plan_path=routing_plan_artifact_path,
                output_formats=render_plan_output_formats,
                contexts=contexts,
                policies=_render_plan_policies_from_report(report_payload),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(render_plan_path, render_plan_payload)
    else:
        try:
            render_plan_payload = _load_json_object(render_plan_path, label="Render plan")
            _validate_json_payload(
                render_plan_payload,
                schema_path=repo_root / "schemas" / "render_plan.schema.json",
                payload_name="Render plan",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    if scene_payload is None:
        try:
            scene_payload = _load_json_object(scene_path, label="Scene")
            _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if render_plan_payload is None:
        print("Render plan payload is unavailable.", file=sys.stderr)
        return 1

    scene_for_bridge = json.loads(json.dumps(scene_payload))
    scene_for_bridge["scene_path"] = scene_path.resolve().as_posix()
    render_plan_for_bridge = json.loads(json.dumps(render_plan_payload))
    render_plan_for_bridge["render_plan_path"] = render_plan_path.resolve().as_posix()
    bridge_default_steps = {
        "routing": False,
        "export_pdf": export_pdf,
        "export_csv": export_csv,
        "render": "render" in contexts,
        "apply": "auto_apply" in contexts,
        "bundle": True,
    }
    try:
        variant_plan = render_plan_to_variant_plan(
            render_plan_for_bridge,
            scene_for_bridge,
            base_out_dir=out_dir.resolve().as_posix(),
            default_steps=bridge_default_steps,
        )
        variant_plan = _apply_run_config_to_render_many_variant_plan(
            variant_plan=variant_plan,
            run_config=effective_run_config,
            preset_id=effective_preset_id,
            config_path=Path(config_path) if config_path else None,
        )
        _validate_json_payload(
            variant_plan,
            schema_path=repo_root / "schemas" / "variant_plan.schema.json",
            payload_name="Variant plan",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(variant_plan_path, variant_plan)
    variants = variant_plan.get("variants")
    if isinstance(variants, list) and len(variants) > 1:
        print("Youll get one folder per variant.")

    run_variant_plan_kwargs: dict[str, Any] = {
        "cache_enabled": cache_enabled,
        "cache_dir": cache_dir,
    }
    if project_path is not None:
        run_variant_plan_kwargs["project_path"] = project_path
    if deliverables_index:
        run_variant_plan_kwargs["deliverables_index_path"] = deliverables_index_path
    if listen_pack:
        run_variant_plan_kwargs["listen_pack_path"] = listen_pack_path
    if timeline_payload is not None:
        run_variant_plan_kwargs["timeline"] = timeline_payload
    if resolved_timeline_path is not None:
        run_variant_plan_kwargs["timeline_path"] = resolved_timeline_path

    try:
        variant_result = run_variant_plan(
            variant_plan,
            repo_root=repo_root,
            **run_variant_plan_kwargs,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _validate_json_payload(
            variant_result,
            schema_path=repo_root / "schemas" / "variant_result.schema.json",
            payload_name="Variant result",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    _write_json_file(variant_result_path, variant_result)

    if listen_pack:
        try:
            listen_pack_payload = _build_validated_listen_pack(
                repo_root=repo_root,
                presets_dir=presets_dir,
                variant_result=variant_result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(listen_pack_path, listen_pack_payload)
    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_variants(
                repo_root=repo_root,
                root_out_dir=out_dir,
                variant_result=variant_result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    if isinstance(translation_profile_ids, list) and translation_profile_ids:
        translation_cache_dir = _resolve_render_many_translation_cache_dir(
            root_out_dir=out_dir,
            cache_dir=cache_dir,
        )
        _run_render_many_translation_checks(
            repo_root=repo_root,
            root_out_dir=out_dir,
            report_path=report_path,
            variant_result=variant_result,
            profile_ids=list(translation_profile_ids),
            project_path=project_path,
            deliverables_index_path=(
                deliverables_index_path if deliverables_index else None
            ),
            listen_pack_path=listen_pack_path if listen_pack else None,
            timeline_path=resolved_timeline_path,
            cache_dir=translation_cache_dir,
            use_cache=cache_enabled,
        )
    if translation_audition:
        audition_profile_ids = (
            list(translation_profile_ids)
            if isinstance(translation_profile_ids, list) and translation_profile_ids
            else list(_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS)
        )
        translation_cache_dir = _resolve_render_many_translation_cache_dir(
            root_out_dir=out_dir,
            cache_dir=cache_dir,
        )
        _run_render_many_translation_auditions(
            repo_root=repo_root,
            root_out_dir=out_dir,
            variant_result=variant_result,
            profile_ids=audition_profile_ids,
            segment_s=translation_audition_segment_s,
            project_path=project_path,
            deliverables_index_path=(
                deliverables_index_path if deliverables_index else None
            ),
            listen_pack_path=listen_pack_path if listen_pack else None,
            timeline_path=resolved_timeline_path,
            cache_dir=translation_cache_dir,
            use_cache=cache_enabled,
        )

    results = variant_result.get("results")
    if not isinstance(results, list):
        return 1

    summary: list[tuple[str, Path]] = [
        ("scene", scene_path),
        ("render_plan", render_plan_path),
        ("variant_plan", variant_plan_path),
        ("variant_result", variant_result_path),
    ]
    if listen_pack:
        summary.append(("listen_pack", listen_pack_path))
    if deliverables_index:
        summary.append(("deliverables_index", deliverables_index_path))
    print("render-many complete:")
    for label, path in summary:
        print(f"- {label}: {path.resolve().as_posix()}")

    has_failure = any(
        isinstance(item, dict) and item.get("ok") is not True
        for item in results
    )
    return 1 if has_failure else 0


def _run_workflow_from_run_args(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    args: argparse.Namespace,
) -> tuple[int, str]:
    preset_values = list(args.preset) if isinstance(args.preset, list) else []
    config_values = list(args.config) if isinstance(args.config, list) else []
    format_set_values = list(args.format_set) if isinstance(args.format_set, list) else []
    project_path: Path | None = None
    project_path_value = getattr(args, "project", None)
    if isinstance(project_path_value, str) and project_path_value.strip():
        project_path = Path(project_path_value)
    timeline_path: Path | None = None
    timeline_path_value = getattr(args, "timeline", None)
    if isinstance(timeline_path_value, str) and timeline_path_value.strip():
        timeline_path = Path(timeline_path_value)
    if getattr(args, "render_many", False):
        if len(preset_values) > 1 or len(config_values) > 1 or bool(format_set_values):
            print(
                (
                    "--render-many supports at most one --preset, at most one --config, "
                    "and does not support --format-set."
                ),
                file=sys.stderr,
            )
            return 1, "variants"
        try:
            target_ids = _parse_target_ids_csv(
                getattr(args, "targets", _BASELINE_RENDER_TARGET_ID),
                render_targets_path=repo_root / "ontology" / "render_targets.yaml",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1, "variants"

        context_values = (
            list(args.context)
            if isinstance(getattr(args, "context", None), list)
            else []
        )
        context_set = {
            _coerce_str(item).strip().lower()
            for item in context_values
            if _coerce_str(item).strip()
        }
        contexts = [
            item
            for item in ("render", "auto_apply")
            if item in context_set
        ]
        if not contexts:
            contexts = ["render"]
        scene_template_ids: list[str] = []
        scene_templates_value = getattr(args, "scene_templates", None)
        if isinstance(scene_templates_value, str) and scene_templates_value.strip():
            try:
                scene_template_ids = _parse_scene_template_ids_csv(scene_templates_value)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1, "variants"

        translation_profiles_path = repo_root / "ontology" / "translation_profiles.yaml"
        translation_profiles_value = getattr(args, "translation_profiles", None)
        translation_enabled = bool(getattr(args, "translation", False))
        translation_profile_ids: list[str] | None = None
        if isinstance(translation_profiles_value, str) and translation_profiles_value.strip():
            try:
                translation_profile_ids = _parse_translation_profile_ids_csv(
                    translation_profiles_value,
                    translation_profiles_path=translation_profiles_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1, "variants"
            translation_enabled = True
        if translation_enabled and translation_profile_ids is None:
            translation_profile_ids = list(_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS)
        translation_audition_enabled = bool(getattr(args, "translation_audition", False))
        translation_audition_segment_s: float | None = None
        if translation_audition_enabled:
            raw_segment = getattr(
                args,
                "translation_audition_segment",
                _DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
            )
            if (
                isinstance(raw_segment, bool)
                or not isinstance(raw_segment, (int, float))
                or not math.isfinite(float(raw_segment))
                or float(raw_segment) <= 0.0
            ):
                print(
                    "--translation-audition-segment must be a positive number of seconds.",
                    file=sys.stderr,
                )
                return 1, "variants"
            translation_audition_segment_s = float(raw_segment)

        exit_code = _run_render_many_workflow(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_id=preset_values[0] if preset_values else None,
            config_path=config_values[0] if config_values else None,
            project_path=project_path,
            timeline_path=timeline_path,
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            truncate_values=args.truncate_values,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            scene_requested=getattr(args, "scene", False),
            render_plan_requested=getattr(args, "render_plan", False),
            scene_template_ids=scene_template_ids,
            target_ids=target_ids,
            contexts=contexts,
            deliverables_index=args.deliverables_index,
            listen_pack=getattr(args, "listen_pack", False),
            translation_profile_ids=translation_profile_ids,
            translation_audition=translation_audition_enabled,
            translation_audition_segment_s=translation_audition_segment_s,
            output_formats=args.output_formats,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
        return exit_code, "variants"

    should_delegate_to_variants = (
        args.variants
        or len(preset_values) > 1
        or len(config_values) > 1
        or bool(format_set_values)
    )
    if should_delegate_to_variants:
        exit_code = _run_variants_workflow(
            repo_root=repo_root,
            presets_dir=presets_dir,
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_values=preset_values if preset_values else None,
            config_values=config_values if config_values else None,
            apply=args.apply,
            render=args.render,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            bundle=args.bundle,
            scene=getattr(args, "scene", False),
            render_plan=getattr(args, "render_plan", False),
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            routing=False,
            downmix_qa=False,
            qa_ref=None,
            qa_meters=None,
            qa_max_seconds=None,
            truncate_values=args.truncate_values,
            output_formats=args.output_formats,
            format_set_values=format_set_values if format_set_values else None,
            listen_pack=getattr(args, "listen_pack", False),
            deliverables_index=args.deliverables_index,
            project_path=project_path,
            timeline_path=timeline_path,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
        return exit_code, "variants"

    exit_code = _run_one_shot_workflow(
        repo_root=repo_root,
        tools_dir=tools_dir,
        presets_dir=presets_dir,
        stems_dir=stems_dir,
        out_dir=out_dir,
        preset_id=preset_values[0] if preset_values else None,
        config_path=config_values[0] if config_values else None,
        project_path=project_path,
        timeline_path=timeline_path,
        profile=args.profile,
        meters=args.meters,
        max_seconds=args.max_seconds,
        truncate_values=args.truncate_values,
        export_pdf=args.export_pdf,
        export_csv=args.export_csv,
        apply=args.apply,
        render=args.render,
        bundle=args.bundle,
        scene=getattr(args, "scene", False),
        render_plan=getattr(args, "render_plan", False),
        deliverables_index=args.deliverables_index,
        output_formats=args.output_formats,
        cache_enabled=args.cache == "on",
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
    )
    return exit_code, "single"


def _project_last_run_payload(*, mode: str, out_dir: Path) -> dict[str, Any]:
    resolved_out_dir = out_dir.resolve()
    payload: dict[str, Any] = {
        "mode": mode,
        "out_dir": resolved_out_dir.as_posix(),
    }

    deliverables_index_path = resolved_out_dir / "deliverables_index.json"
    if deliverables_index_path.exists():
        payload["deliverables_index_path"] = deliverables_index_path.as_posix()

    listen_pack_path = resolved_out_dir / "listen_pack.json"
    if listen_pack_path.exists():
        payload["listen_pack_path"] = listen_pack_path.as_posix()

    if mode == "variants":
        variant_plan_path = resolved_out_dir / "variant_plan.json"
        variant_result_path = resolved_out_dir / "variant_result.json"
        if variant_plan_path.exists():
            payload["variant_plan_path"] = variant_plan_path.as_posix()
        if variant_result_path.exists():
            payload["variant_result_path"] = variant_result_path.as_posix()
    return payload


def _project_run_config_defaults(
    *,
    mode: str,
    out_dir: Path,
) -> dict[str, Any] | None:
    resolved_out_dir = out_dir.resolve()
    try:
        if mode == "single":
            report_path = resolved_out_dir / "report.json"
            if not report_path.exists():
                return None
            report = _load_json_object(report_path, label="Report")
            run_config = report.get("run_config")
            if isinstance(run_config, dict):
                return normalize_run_config(run_config)
            return None

        if mode == "variants":
            plan_path = resolved_out_dir / "variant_plan.json"
            if not plan_path.exists():
                return None
            variant_plan = _load_json_object(plan_path, label="Variant plan")
            base_run_config = variant_plan.get("base_run_config")
            if isinstance(base_run_config, dict):
                return normalize_run_config(base_run_config)
            return None
    except ValueError:
        return None
    return None


def _render_project_text(project: dict[str, Any]) -> str:
    lines = [
        f"project_id: {project.get('project_id', '')}",
        f"stems_dir: {project.get('stems_dir', '')}",
        f"created_at_utc: {project.get('created_at_utc', '')}",
        f"updated_at_utc: {project.get('updated_at_utc', '')}",
    ]

    timeline_path = project.get("timeline_path")
    if isinstance(timeline_path, str):
        lines.append(f"timeline_path: {timeline_path}")

    lockfile_path = project.get("lockfile_path")
    if isinstance(lockfile_path, str):
        lines.append(f"lockfile_path: {lockfile_path}")

    lock_hash = project.get("lock_hash")
    if isinstance(lock_hash, str):
        lines.append(f"lock_hash: {lock_hash}")

    last_run = project.get("last_run")
    if isinstance(last_run, dict):
        lines.append("last_run:")
        lines.append(json.dumps(last_run, indent=2, sort_keys=True))

    run_config_defaults = project.get("run_config_defaults")
    if isinstance(run_config_defaults, dict):
        lines.append("run_config_defaults:")
        lines.append(json.dumps(run_config_defaults, indent=2, sort_keys=True))

    notes = project.get("notes")
    if isinstance(notes, str):
        lines.append(f"notes: {notes}")

    return "\n".join(lines)


def _render_stem_sets_text(stem_sets: list[dict[str, Any]]) -> str:
    lines = [f"found {len(stem_sets)} sets"]
    for item in stem_sets:
        rel_dir = item.get("rel_dir") if isinstance(item.get("rel_dir"), str) else ""
        file_count = item.get("file_count") if isinstance(item.get("file_count"), int) else 0
        why = item.get("why") if isinstance(item.get("why"), str) else ""
        lines.append(
            f"- {rel_dir or '.'}  file_count={file_count}  why={why or 'n/a'}"
        )
    return "\n".join(lines)


def _path_ref(path_value: str) -> str:
    return Path(path_value).as_posix()


def _load_stems_index_for_classification(
    *,
    repo_root: Path,
    index_path: str | None,
    root_path: str | None,
) -> tuple[dict[str, Any], str]:
    if isinstance(index_path, str) and index_path.strip():
        path = Path(index_path)
        payload = _load_json_object(path, label="Stems index")
        _validate_json_payload(
            payload,
            schema_path=repo_root / "schemas" / "stems_index.schema.json",
            payload_name="Stems index",
        )
        return payload, _path_ref(index_path)

    if isinstance(root_path, str) and root_path.strip():
        payload = build_stems_index(Path(root_path), root_dir=root_path)
        _validate_json_payload(
            payload,
            schema_path=repo_root / "schemas" / "stems_index.schema.json",
            payload_name="Stems index",
        )
        return payload, _path_ref(root_path)

    raise ValueError("Provide either --index or --root.")


def _default_stems_overrides_template() -> str:
    return (
        "# Stem assignment overrides.\n"
        "# Keep overrides sorted by override_id for deterministic behavior.\n"
        "# If multiple overrides match one file, the first sorted override_id wins.\n"
        "version: \"0.1.0\"\n"
        "overrides:\n"
        "  - override_id: \"OVERRIDE.001\"\n"
        "    match:\n"
        "      rel_path: \"stems/kick.wav\"\n"
        "    role_id: \"ROLE.DRUM.KICK\"\n"
        "    note: \"Optional note for reviewers\"\n"
        "  - override_id: \"OVERRIDE.010\"\n"
        "    match:\n"
        "      regex: \"^stems/vox.*\\\\.wav$\"\n"
        "    role_id: \"ROLE.VOCAL.LEAD\"\n"
    )


def _load_stems_map(*, repo_root: Path, map_path: Path) -> dict[str, Any]:
    payload = _load_json_object(map_path, label="Stems map")
    _validate_json_payload(
        payload,
        schema_path=repo_root / "schemas" / "stems_map.schema.json",
        payload_name="Stems map",
    )
    return payload


def _render_stems_map_text(stems_map: dict[str, Any]) -> str:
    assignments = stems_map.get("assignments")
    rows = [("rel_path", "role_id", "conf", "bus_group")]

    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            rel_path = item.get("rel_path") if isinstance(item.get("rel_path"), str) else ""
            role_id = item.get("role_id") if isinstance(item.get("role_id"), str) else ""
            confidence = (
                item.get("confidence")
                if isinstance(item.get("confidence"), (int, float))
                else 0.0
            )
            bus_group = (
                item.get("bus_group")
                if isinstance(item.get("bus_group"), str) and item.get("bus_group")
                else "-"
            )
            rows.append((rel_path, role_id, f"{float(confidence):.3f}", bus_group))

    widths = [max(len(row[idx]) for row in rows) for idx in range(4)]
    lines = [
        (
            f"{rows[0][0]:<{widths[0]}} | {rows[0][1]:<{widths[1]}} | "
            f"{rows[0][2]:<{widths[2]}} | {rows[0][3]:<{widths[3]}}"
        ),
        (
            f"{'-' * widths[0]}-+-{'-' * widths[1]}-+-"
            f"{'-' * widths[2]}-+-{'-' * widths[3]}"
        ),
    ]
    for row in rows[1:]:
        lines.append(
            f"{row[0]:<{widths[0]}} | {row[1]:<{widths[1]}} | "
            f"{row[2]:<{widths[2]}} | {row[3]:<{widths[3]}}"
        )

    summary = stems_map.get("summary")
    if isinstance(summary, dict):
        unknown_files = (
            summary.get("unknown_files")
            if isinstance(summary.get("unknown_files"), int)
            else 0
        )
        lines.append(f"unknown_files={unknown_files}")
    return "\n".join(lines)


def _build_stem_explain_payload(
    *,
    stems_map: dict[str, Any],
    explanations: dict[str, dict[str, Any]],
    file_selector: str,
) -> dict[str, Any]:
    selector = file_selector.strip()
    if not selector:
        raise ValueError("Stem selector must be a non-empty string.")

    explanation = explanations.get(selector)
    if explanation is None:
        by_rel = sorted(
            (
                payload
                for payload in explanations.values()
                if isinstance(payload, dict) and payload.get("rel_path") == selector
            ),
            key=lambda item: (
                item.get("file_id") if isinstance(item.get("file_id"), str) else "",
                item.get("rel_path") if isinstance(item.get("rel_path"), str) else "",
            ),
        )
        if by_rel:
            explanation = by_rel[0]

    if explanation is None:
        known = sorted(
            {
                value
                for payload in explanations.values()
                if isinstance(payload, dict)
                for value in (payload.get("file_id"), payload.get("rel_path"))
                if isinstance(value, str) and value
            }
        )
        if known:
            raise ValueError(
                f"Unknown stem file selector: {selector}. "
                f"Known selectors: {', '.join(known)}"
            )
        raise ValueError(f"Unknown stem file selector: {selector}. No stems are available.")

    file_id = explanation.get("file_id") if isinstance(explanation.get("file_id"), str) else ""
    rel_path = (
        explanation.get("rel_path")
        if isinstance(explanation.get("rel_path"), str)
        else ""
    )

    selected_assignment: dict[str, Any] | None = None
    assignments = stems_map.get("assignments")
    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            assignment_file_id = item.get("file_id")
            assignment_rel_path = item.get("rel_path")
            if assignment_file_id == file_id or assignment_rel_path == rel_path:
                selected_assignment = item
                break

    if selected_assignment is None:
        selected_assignment = {}

    reasons = (
        selected_assignment.get("reasons")
        if isinstance(selected_assignment.get("reasons"), list)
        else explanation.get("selected_reasons", [])
    )
    derived_evidence: list[str] = []
    if isinstance(reasons, list):
        for reason in reasons:
            if not isinstance(reason, str):
                continue
            if not (
                reason.startswith("token_norm:")
                or reason.startswith("token_split:")
            ):
                continue
            if reason not in derived_evidence:
                derived_evidence.append(reason)

    return {
        "file_id": file_id,
        "rel_path": rel_path,
        "tokens": (
            explanation.get("tokens")
            if isinstance(explanation.get("tokens"), list)
            else []
        ),
        "folder_tokens": (
            explanation.get("folder_tokens")
            if isinstance(explanation.get("folder_tokens"), list)
            else []
        ),
        "role_id": (
            selected_assignment.get("role_id")
            if isinstance(selected_assignment.get("role_id"), str)
            else explanation.get("selected_role_id", "")
        ),
        "confidence": (
            selected_assignment.get("confidence")
            if isinstance(selected_assignment.get("confidence"), (int, float))
            else 0.0
        ),
        "bus_group": (
            selected_assignment.get("bus_group")
            if isinstance(selected_assignment.get("bus_group"), str)
            else None
        ),
        "link_group_id": (
            selected_assignment.get("link_group_id")
            if isinstance(selected_assignment.get("link_group_id"), str)
            else None
        ),
        "reasons": reasons if isinstance(reasons, list) else [],
        "derived_evidence": derived_evidence,
        "candidates": (
            explanation.get("candidates")
            if isinstance(explanation.get("candidates"), list)
            else []
        ),
    }


def _render_stem_explain_text(payload: dict[str, Any]) -> str:
    confidence = payload.get("confidence") if isinstance(payload.get("confidence"), (int, float)) else 0.0
    bus_group = payload.get("bus_group") if isinstance(payload.get("bus_group"), str) else "-"
    link_group_id = (
        payload.get("link_group_id")
        if isinstance(payload.get("link_group_id"), str)
        else "-"
    )
    reasons = payload.get("reasons") if isinstance(payload.get("reasons"), list) else []
    derived_evidence = (
        payload.get("derived_evidence")
        if isinstance(payload.get("derived_evidence"), list)
        else []
    )

    lines = [
        f"file_id: {payload.get('file_id', '')}",
        f"rel_path: {payload.get('rel_path', '')}",
        f"role_id: {payload.get('role_id', '')}",
        f"confidence: {float(confidence):.3f}",
        f"bus_group: {bus_group}",
        f"link_group_id: {link_group_id}",
        f"tokens: {', '.join(str(item) for item in payload.get('tokens', []))}",
        f"folder_tokens: {', '.join(str(item) for item in payload.get('folder_tokens', []))}",
        "reasons:",
    ]
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- (none)")

    lines.append("derived_evidence:")
    if derived_evidence:
        for reason in derived_evidence:
            lines.append(f"- {reason}")
    else:
        lines.append("- (none)")

    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    lines.append("candidates:")
    if not candidates:
        lines.append("- (none)")
        return "\n".join(lines)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        role_id = candidate.get("role_id") if isinstance(candidate.get("role_id"), str) else ""
        kind = candidate.get("kind") if isinstance(candidate.get("kind"), str) else ""
        score = candidate.get("score") if isinstance(candidate.get("score"), int) else 0
        bus_label = candidate.get("bus_group") if isinstance(candidate.get("bus_group"), str) else "-"
        candidate_reasons = (
            candidate.get("reasons")
            if isinstance(candidate.get("reasons"), list)
            else []
        )
        reason_label = "; ".join(str(reason) for reason in candidate_reasons) if candidate_reasons else "none"
        lines.append(
            f"- {role_id}  score={score}  kind={kind}  bus_group={bus_label}  reasons={reason_label}"
        )
    return "\n".join(lines)


_UIInputProvider = Callable[[str], str]
_UIOutputWriter = Callable[[str], None]


def _ui_count_list(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _ui_lockfile_status(
    *,
    stems_dir: Path,
    project_payload: dict[str, Any],
    nerd: bool,
) -> str:
    from mmo.core.lockfile import verify_lockfile  # noqa: WPS433

    lockfile_path_value = project_payload.get("lockfile_path")
    if not isinstance(lockfile_path_value, str) or not lockfile_path_value.strip():
        return "missing"

    lockfile_path = Path(lockfile_path_value)
    if not lockfile_path.exists():
        if nerd:
            return f"missing ({lockfile_path.resolve().as_posix()})"
        return "missing"

    try:
        lock_payload = _load_json_object(lockfile_path, label="Lockfile")
        verify_result = verify_lockfile(stems_dir, lock_payload)
    except ValueError as exc:
        if nerd:
            return f"invalid ({exc})"
        return "invalid"

    if verify_result.get("ok") is True:
        return "in sync"

    missing_count = _ui_count_list(verify_result.get("missing"))
    extra_count = _ui_count_list(verify_result.get("extra"))
    changed_count = _ui_count_list(verify_result.get("changed"))
    return (
        "drift"
        f" (missing={missing_count}, extra={extra_count}, changed={changed_count})"
    )


def _ui_last_run_pointer_rows(project_payload: dict[str, Any]) -> list[tuple[str, str]]:
    last_run = project_payload.get("last_run")
    if not isinstance(last_run, dict):
        return []

    rows: list[tuple[str, str]] = []
    key_map = [
        ("mode", "mode"),
        ("out_dir", "out_dir"),
        ("deliverables_index_path", "deliverables_index"),
        ("listen_pack_path", "listen_pack"),
        ("variant_plan_path", "variant_plan"),
        ("variant_result_path", "variant_result"),
    ]
    for key, label in key_map:
        value = last_run.get(key)
        if isinstance(value, str) and value.strip():
            rows.append((label, value.strip()))
    return rows


def _ui_report_path_from_variant_result(variant_result_path: Path) -> Path | None:
    try:
        payload = _load_json_object(variant_result_path, label="Variant result")
    except ValueError:
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        return None

    normalized_results = sorted(
        [item for item in results if isinstance(item, dict)],
        key=lambda item: str(item.get("variant_id", "")),
    )
    for item in normalized_results:
        report_path_value = item.get("report_path")
        if not isinstance(report_path_value, str) or not report_path_value.strip():
            continue
        report_path = Path(report_path_value.strip())
        if not report_path.is_absolute():
            out_dir_value = item.get("out_dir")
            if isinstance(out_dir_value, str) and out_dir_value.strip():
                report_path = Path(out_dir_value.strip()) / report_path
            else:
                report_path = variant_result_path.parent / report_path
        if report_path.exists():
            return report_path.resolve()
    return None


def _ui_report_path_from_project(project_payload: dict[str, Any]) -> Path | None:
    last_run = project_payload.get("last_run")
    if not isinstance(last_run, dict):
        return None

    mode = last_run.get("mode")
    out_dir_value = last_run.get("out_dir")
    if mode == "single" and isinstance(out_dir_value, str) and out_dir_value.strip():
        candidate = Path(out_dir_value.strip()) / "report.json"
        if candidate.exists():
            return candidate.resolve()

    variant_result_candidates: list[Path] = []
    variant_result_path_value = last_run.get("variant_result_path")
    if isinstance(variant_result_path_value, str) and variant_result_path_value.strip():
        variant_result_candidates.append(Path(variant_result_path_value.strip()))
    if isinstance(out_dir_value, str) and out_dir_value.strip():
        variant_result_candidates.append(Path(out_dir_value.strip()) / "variant_result.json")

    for candidate in variant_result_candidates:
        if not candidate.exists():
            continue
        report_path = _ui_report_path_from_variant_result(candidate)
        if report_path is not None:
            return report_path
    return None


def _ui_workflow_help_short_map(repo_root: Path) -> dict[str, str]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    help_ids = ["HELP.WORKFLOW.RUN", "HELP.WORKFLOW.VARIANTS_RUN"]
    try:
        registry = load_help_registry(repo_root / "ontology" / "help.yaml")
        resolved = resolve_help_entries(help_ids, registry)
    except (RuntimeError, ValueError):
        return {}

    payload: dict[str, str] = {}
    for help_id in help_ids:
        entry = resolved.get(help_id)
        if not isinstance(entry, dict):
            continue
        short = entry.get("short")
        if not isinstance(short, str):
            continue
        normalized_short = short.strip()
        if not normalized_short or normalized_short == "Missing help entry":
            continue
        payload[help_id] = normalized_short
    return payload


def _ui_render_preview_text(payload: dict[str, Any], *, nerd: bool) -> str:
    if nerd:
        lines = [_render_preset_preview_text(payload)]
        effective_run_config = payload.get("effective_run_config")
        if isinstance(effective_run_config, dict):
            profile_id = effective_run_config.get("profile_id")
            meters = effective_run_config.get("meters")
            max_seconds = effective_run_config.get("max_seconds")
            lines.append("")
            lines.append(f"profile_id: {profile_id}")
            lines.append(f"meters: {meters}")
            lines.append(f"max_seconds: {max_seconds}")
            lines.append("effective_run_config:")
            lines.append(json.dumps(effective_run_config, indent=2, sort_keys=True))
        return "\n".join(lines)

    label = payload.get("label")
    overlay = payload.get("overlay")
    help_payload = payload.get("help")
    warnings = payload.get("warnings")

    normalized_label = label if isinstance(label, str) and label.strip() else "Preset"
    normalized_overlay = overlay if isinstance(overlay, str) and overlay.strip() else "None"
    short = ""
    cues: list[str] = []
    watch_out_for: list[str] = []
    if isinstance(help_payload, dict):
        short_value = help_payload.get("short")
        if isinstance(short_value, str):
            short = short_value
        cues = _string_list(help_payload.get("cues"))
        watch_out_for = _string_list(help_payload.get("watch_out_for"))
    warning_rows = _string_list(warnings)
    for warning in warning_rows:
        if warning not in watch_out_for:
            watch_out_for.append(warning)

    lines = [
        f"{normalized_label}  [{normalized_overlay}]",
        f"What it does: {short}",
        "Try it when:",
    ]
    for cue in cues[:4]:
        lines.append(f"  - {cue}")
    lines.append("Watch out for:")
    for item in watch_out_for[:4]:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def _ui_first_variant_bundle_path(out_dir: Path) -> Path | None:
    variant_result_path = out_dir / "variant_result.json"
    if variant_result_path.exists():
        try:
            payload = _load_json_object(variant_result_path, label="Variant result")
        except ValueError:
            payload = {}
        results = payload.get("results")
        if isinstance(results, list):
            normalized_results = sorted(
                [item for item in results if isinstance(item, dict)],
                key=lambda item: str(item.get("variant_id", "")),
            )
            for item in normalized_results:
                bundle_path_value = item.get("bundle_path")
                if not isinstance(bundle_path_value, str) or not bundle_path_value.strip():
                    continue
                candidate = Path(bundle_path_value.strip())
                if candidate.exists():
                    return candidate.resolve()
    for candidate in sorted(out_dir.glob("VARIANT.*__*/ui_bundle.json")):
        if candidate.exists():
            return candidate.resolve()
    return None


def _run_ui_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    project_path: Path | None,
    nerd: bool,
    input_provider: _UIInputProvider = input,
    output: _UIOutputWriter = print,
) -> int:
    resolved_stems_dir = stems_dir.resolve()
    resolved_out_dir = out_dir.resolve()
    resolved_project_path = project_path.resolve() if project_path is not None else None

    project_payload: dict[str, Any] | None = None
    if resolved_project_path is not None:
        try:
            project_payload = load_project(resolved_project_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    render_header(
        "MMO UI Launcher",
        subtitle="Preset picker -> preview -> run",
        output=output,
    )
    output(f"Stems dir: {resolved_stems_dir.as_posix()}")
    output(f"Output dir: {resolved_out_dir.as_posix()}")
    if project_payload is not None and resolved_project_path is not None:
        output(f"Project: {resolved_project_path.as_posix()}")
        output(
            "Lockfile status: "
            + _ui_lockfile_status(
                stems_dir=resolved_stems_dir,
                project_payload=project_payload,
                nerd=nerd,
            )
        )
        pointer_rows = _ui_last_run_pointer_rows(project_payload)
        if pointer_rows:
            output("Last run pointers:")
            for label, value in pointer_rows:
                output(f"- {label}: {value}")
        else:
            output("Last run pointers: none")
    else:
        output("Project: none")

    try:
        all_presets = list_presets(presets_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not all_presets:
        print("No presets are available.", file=sys.stderr)
        return 1

    render_header("Choose a vibe preset", output=output)
    overlay_values = {
        item.get("overlay").strip()
        for item in all_presets
        if isinstance(item, dict)
        and isinstance(item.get("overlay"), str)
        and item.get("overlay", "").strip()
    }
    chips = [chip for chip in _UI_OVERLAY_CHIPS if chip in overlay_values]
    if chips:
        output("Overlay chips: " + " ".join(f"[{chip}]" for chip in chips))

    recommendation_report_path: Path | None = None
    if project_payload is not None:
        recommendation_report_path = _ui_report_path_from_project(project_payload)
    if recommendation_report_path is None:
        out_report_path = resolved_out_dir / "report.json"
        if out_report_path.exists():
            recommendation_report_path = out_report_path
    if recommendation_report_path is None:
        quick_report_path = resolved_out_dir / ".ui_recommend_report.json"
        output("No prior report found. Running a quick scan for recommendations...")
        quick_report_path.parent.mkdir(parents=True, exist_ok=True)
        exit_code = _run_analyze(
            tools_dir,
            resolved_stems_dir,
            quick_report_path,
            None,
            False,
            str(repo_root / "plugins"),
            False,
            "PROFILE.ASSIST",
        )
        if exit_code == 0 and quick_report_path.exists():
            recommendation_report_path = quick_report_path

    recommendations: list[dict[str, Any]] = []
    if recommendation_report_path is not None:
        try:
            recommendations = _build_preset_recommendations_payload(
                report_path=recommendation_report_path,
                presets_dir=presets_dir,
                n=3,
            )
        except ValueError:
            recommendations = []

    preset_by_id: dict[str, dict[str, Any]] = {}
    for item in all_presets:
        if not isinstance(item, dict):
            continue
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str):
            preset_by_id[preset_id] = item

    recommended_ids: list[str] = []
    for item in recommendations:
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str) and preset_id in preset_by_id:
            recommended_ids.append(preset_id)
    if recommended_ids:
        output("Recommended:")
        for preset_id in recommended_ids:
            preset = preset_by_id[preset_id]
            label = preset.get("label", "")
            overlay = preset.get("overlay", "")
            recommendation = next(
                (
                    row
                    for row in recommendations
                    if isinstance(row, dict) and row.get("preset_id") == preset_id
                ),
                {},
            )
            reasons = (
                recommendation.get("reasons")
                if isinstance(recommendation, dict)
                else []
            )
            first_reason = ""
            if isinstance(reasons, list):
                for reason in reasons:
                    if isinstance(reason, str) and reason.strip():
                        first_reason = reason.strip()
                        break
            if nerd:
                output(f"- {preset_id} | {label} | overlay={overlay}")
            else:
                overlay_suffix = f" [{overlay}]" if isinstance(overlay, str) and overlay else ""
                output(f"- {label}{overlay_suffix}")
            if first_reason:
                output(f"  reason: {first_reason}")

    filter_mode_index = choose_from_list(
        "Filter presets",
        ["No filter", "By tag", "By category"],
        default_index=0,
        input_provider=input_provider,
        output=output,
    )
    filter_tag: str | None = None
    filter_category: str | None = None

    if filter_mode_index == 1:
        tags = sorted(
            {
                tag
                for item in all_presets
                if isinstance(item, dict)
                for tag in _string_list(item.get("tags"))
            }
        )
        if tags:
            selected_tag_index = choose_from_list(
                "Choose tag",
                tags,
                default_index=0,
                input_provider=input_provider,
                output=output,
            )
            filter_tag = tags[selected_tag_index]
    elif filter_mode_index == 2:
        categories = sorted(
            {
                item.get("category").strip()
                for item in all_presets
                if isinstance(item, dict)
                and isinstance(item.get("category"), str)
                and item.get("category", "").strip()
            }
        )
        if categories:
            selected_category_index = choose_from_list(
                "Choose category",
                categories,
                default_index=0,
                input_provider=input_provider,
                output=output,
            )
            filter_category = categories[selected_category_index]

    filtered_presets = list_presets(
        presets_dir,
        tag=filter_tag,
        category=filter_category,
    )
    if not filtered_presets:
        output("No presets matched that filter. Showing all presets instead.")
        filtered_presets = list(all_presets)

    option_labels: list[str] = []
    for item in filtered_presets:
        preset_id = item.get("preset_id")
        label = item.get("label", "")
        overlay = item.get("overlay", "")
        category = item.get("category", "")
        recommended_suffix = (
            " (Recommended)"
            if isinstance(preset_id, str) and preset_id in recommended_ids
            else ""
        )
        if nerd:
            option_labels.append(
                f"{label} ({preset_id}) [{category}] overlay={overlay}{recommended_suffix}"
            )
        else:
            overlay_suffix = (
                f" [{overlay}]"
                if isinstance(overlay, str) and overlay.strip()
                else ""
            )
            option_labels.append(f"{label}{overlay_suffix}{recommended_suffix}")

    default_preset_index = 0
    for index, item in enumerate(filtered_presets):
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str) and preset_id in recommended_ids:
            default_preset_index = index
            break

    selected_preset_index = choose_from_list(
        "Choose preset",
        option_labels,
        default_index=default_preset_index,
        input_provider=input_provider,
        output=output,
    )
    selected_preset = filtered_presets[selected_preset_index]
    selected_preset_id = selected_preset.get("preset_id", "")
    if not isinstance(selected_preset_id, str) or not selected_preset_id.strip():
        print("Selected preset is missing preset_id.", file=sys.stderr)
        return 1

    try:
        preview_payload = _build_preset_preview_payload(
            repo_root=repo_root,
            presets_dir=presets_dir,
            preset_id=selected_preset_id,
            config_path=None,
            cli_overrides={},
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    render_header("Preset preview", output=output)
    output(_ui_render_preview_text(preview_payload, nerd=nerd))

    help_short_map = _ui_workflow_help_short_map(repo_root)
    run_help_text = help_short_map.get("HELP.WORKFLOW.RUN")
    if isinstance(run_help_text, str) and run_help_text:
        output("")
        output(f"Run workflow: {run_help_text}")

    use_variants = yes_no(
        "Use variants mode (needed for listen pack)?",
        default=False,
        input_provider=input_provider,
        output=output,
    )
    if use_variants:
        variants_help_text = help_short_map.get("HELP.WORKFLOW.VARIANTS_RUN")
        if isinstance(variants_help_text, str) and variants_help_text:
            output(f"Variants workflow: {variants_help_text}")

    step_options: list[dict[str, Any]] = [
        {"key": "analyze", "label": "Analyze", "enabled": True, "locked": True},
        {"key": "export_pdf", "label": "Export PDF", "enabled": False},
        {"key": "export_csv", "label": "Export CSV", "enabled": False},
        {"key": "apply", "label": "Apply (auto-apply)", "enabled": False},
        {"key": "render", "label": "Render (render suggestions)", "enabled": False},
        {"key": "bundle", "label": "Bundle", "enabled": True, "locked": True},
        {"key": "deliverables_index", "label": "Deliverables index", "enabled": True},
    ]
    if use_variants:
        step_options.append(
            {"key": "listen_pack", "label": "Listen pack", "enabled": False}
        )
    step_state = multi_toggle(
        "Choose steps",
        step_options,
        input_provider=input_provider,
        output=output,
    )

    export_pdf = step_state.get("export_pdf") is True
    export_csv = step_state.get("export_csv") is True
    apply = step_state.get("apply") is True
    render = step_state.get("render") is True
    deliverables_index = step_state.get("deliverables_index") is True
    listen_pack = use_variants and step_state.get("listen_pack") is True

    render_header("Run", output=output)
    if use_variants:
        exit_code = _run_variants_workflow(
            repo_root=repo_root,
            presets_dir=presets_dir,
            stems_dir=resolved_stems_dir,
            out_dir=resolved_out_dir,
            preset_values=[selected_preset_id],
            config_values=None,
            apply=apply,
            render=render,
            export_pdf=export_pdf,
            export_csv=export_csv,
            bundle=True,
            scene=False,
            profile=None,
            meters=None,
            max_seconds=None,
            routing=False,
            source_layout=None,
            target_layout=None,
            downmix_qa=False,
            qa_ref=None,
            qa_meters=None,
            qa_max_seconds=None,
            policy_id=None,
            truncate_values=None,
            output_formats=None,
            render_output_formats=None,
            apply_output_formats=None,
            format_set_values=None,
            listen_pack=listen_pack,
            deliverables_index=deliverables_index,
            project_path=resolved_project_path,
            cache_enabled=True,
            cache_dir=None,
        )
        run_mode = "variants"
    else:
        exit_code = _run_one_shot_workflow(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=resolved_stems_dir,
            out_dir=resolved_out_dir,
            preset_id=selected_preset_id,
            config_path=None,
            project_path=resolved_project_path,
            timeline_path=None,
            profile=None,
            meters=None,
            max_seconds=None,
            truncate_values=None,
            export_pdf=export_pdf,
            export_csv=export_csv,
            apply=apply,
            render=render,
            bundle=True,
            scene=False,
            deliverables_index=deliverables_index,
            output_formats=None,
            cache_enabled=True,
            cache_dir=None,
        )
        run_mode = "single"
    if exit_code != 0:
        return exit_code

    if resolved_project_path is not None and project_payload is not None:
        try:
            project_payload = update_project_last_run(
                project_payload,
                _project_last_run_payload(mode=run_mode, out_dir=resolved_out_dir),
            )
            run_config_defaults = _project_run_config_defaults(
                mode=run_mode,
                out_dir=resolved_out_dir,
            )
            if isinstance(run_config_defaults, dict):
                project_payload["run_config_defaults"] = run_config_defaults

            try:
                from mmo.core.lockfile import build_lockfile  # noqa: WPS433

                lock_payload = build_lockfile(resolved_stems_dir)
            except ValueError:
                lock_payload = None
            if isinstance(lock_payload, dict):
                lockfile_path = resolved_out_dir / "lockfile.json"
                _write_json_file(lockfile_path, lock_payload)
                project_payload["lockfile_path"] = lockfile_path.as_posix()
                project_payload["lock_hash"] = hash_lockfile(lock_payload)

            write_project(resolved_project_path, project_payload)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    render_header("Finish", output=output)
    if use_variants:
        bundle_path = _ui_first_variant_bundle_path(resolved_out_dir)
    else:
        bundle_path = resolved_out_dir / "ui_bundle.json"
        if not bundle_path.exists():
            bundle_path = None

    if bundle_path is not None:
        output(f"ui_bundle.json: {bundle_path.resolve().as_posix()}")
    else:
        output("ui_bundle.json: not generated")

    deliverables_index_path = resolved_out_dir / "deliverables_index.json"
    if deliverables_index_path.exists():
        output(
            "deliverables_index.json: "
            + deliverables_index_path.resolve().as_posix()
        )
    else:
        output("deliverables_index.json: not generated")

    if listen_pack:
        listen_pack_path = resolved_out_dir / "listen_pack.json"
        if listen_pack_path.exists():
            output(f"listen_pack.json: {listen_pack_path.resolve().as_posix()}")

    if use_variants:
        output("Tip: open deliverables_index.json, then the first variant ui_bundle.json.")
    else:
        output("Tip: open ui_bundle.json first, then check report.json for details.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MMO command-line tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan stems and write a report JSON.")
    scan_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    scan_parser.add_argument("--out", required=True, help="Path to output report JSON.")
    scan_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    scan_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run scan + pipeline + exports for a stems directory."
    )
    analyze_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    analyze_parser.add_argument(
        "--out-report",
        required=True,
        help="Path to the output report JSON after running the pipeline.",
    )
    analyze_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    analyze_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    analyze_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    analyze_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )
    analyze_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to the plugins directory.",
    )
    analyze_parser.add_argument(
        "--keep-scan",
        action="store_true",
        help="Keep the intermediate scan report JSON instead of deleting it.",
    )
    analyze_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for gate eligibility (default: PROFILE.ASSIST).",
    )
    analyze_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    analyze_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )

    stems_parser = subparsers.add_parser("stems", help="Stem-set resolver tools.")
    stems_subparsers = stems_parser.add_subparsers(dest="stems_command", required=True)
    stems_scan_parser = stems_subparsers.add_parser(
        "scan",
        help="Resolve stem sets and write a stems_index artifact JSON.",
    )
    stems_scan_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_scan_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems_index JSON.",
    )
    stems_scan_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_sets_parser = stems_subparsers.add_parser(
        "sets",
        help="List stem-set candidates for a root directory.",
    )
    stems_sets_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_sets_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stem-set listing.",
    )
    stems_classify_parser = stems_subparsers.add_parser(
        "classify",
        help="Classify stems by role and write a stems_map artifact JSON.",
    )
    stems_classify_input = stems_classify_parser.add_mutually_exclusive_group(required=True)
    stems_classify_input.add_argument(
        "--index",
        help="Path to an existing stems_index JSON.",
    )
    stems_classify_input.add_argument(
        "--root",
        help="Root directory to scan for stems before classification.",
    )
    stems_classify_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems_map JSON.",
    )
    stems_classify_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_classify_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_classify_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_explain_parser = stems_subparsers.add_parser(
        "explain",
        help="Explain role-matching evidence for one stem file.",
    )
    stems_explain_input = stems_explain_parser.add_mutually_exclusive_group(required=True)
    stems_explain_input.add_argument(
        "--index",
        help="Path to an existing stems_index JSON.",
    )
    stems_explain_input.add_argument(
        "--root",
        help="Root directory to scan for stems before explanation.",
    )
    stems_explain_parser.add_argument(
        "--file",
        required=True,
        help="Stem rel_path or file_id to explain.",
    )
    stems_explain_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_explain_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_explain_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for explanation output.",
    )
    stems_apply_overrides_parser = stems_subparsers.add_parser(
        "apply-overrides",
        help="Apply stems overrides to an existing stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--map",
        required=True,
        help="Path to an existing stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--overrides",
        required=True,
        help="Path to stems overrides YAML.",
    )
    stems_apply_overrides_parser.add_argument(
        "--out",
        required=True,
        help="Path to output patched stems_map JSON.",
    )
    stems_apply_overrides_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for stdout summary.",
    )
    stems_review_parser = stems_subparsers.add_parser(
        "review",
        help="Review assignments from an existing stems_map JSON.",
    )
    stems_review_parser.add_argument(
        "--map",
        required=True,
        help="Path to an existing stems_map JSON.",
    )
    stems_review_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for review output.",
    )
    stems_overrides_parser = stems_subparsers.add_parser(
        "overrides",
        help="Stems override artifact tools.",
    )
    stems_overrides_subparsers = stems_overrides_parser.add_subparsers(
        dest="stems_overrides_command",
        required=True,
    )
    stems_overrides_default_parser = stems_overrides_subparsers.add_parser(
        "default",
        help="Write a default stems overrides YAML template.",
    )
    stems_overrides_default_parser.add_argument(
        "--out",
        required=True,
        help="Path to output stems overrides YAML.",
    )
    stems_overrides_validate_parser = stems_overrides_subparsers.add_parser(
        "validate",
        help="Validate a stems overrides YAML file.",
    )
    stems_overrides_validate_parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to stems overrides YAML.",
    )
    stems_pipeline_parser = stems_subparsers.add_parser(
        "pipeline",
        help="One-command scan + classify + default overrides.",
    )
    stems_pipeline_parser.add_argument(
        "--root",
        required=True,
        help="Root directory to scan for stem sets.",
    )
    stems_pipeline_parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory for stems_index.json, stems_map.json, and stems_overrides.yaml.",
    )
    stems_pipeline_parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role lexicon extension YAML.",
    )
    stems_pipeline_parser.add_argument(
        "--no-common-lexicon",
        action="store_true",
        help="Disable built-in common role lexicon baseline.",
    )
    stems_pipeline_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing stems_overrides.yaml.",
    )
    stems_pipeline_parser.add_argument(
        "--bundle",
        default=None,
        help="Optional path to write a ui_bundle.json pointer set.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "One-shot workflow: analyze plus optional export/apply/render/bundle "
            "artifacts in one deterministic output folder."
        ),
        epilog=_RUN_COMMAND_EPILOG,
    )
    run_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID from presets/index.json. May be provided multiple times.",
    )
    run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path. May be provided multiple times.",
    )
    run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override.",
    )
    run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config.",
    )
    run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF.",
    )
    run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export recall CSV.",
    )
    run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config.",
    )
    run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow.",
    )
    run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow.",
    )
    run_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
    )
    run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact.",
    )
    run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact (auto-builds scene.json if needed).",
    )
    run_parser.add_argument(
        "--scene-templates",
        default=None,
        help="Comma-separated scene template IDs applied in --render-many before render-plan/variants.",
    )
    run_parser.add_argument(
        "--render-many",
        action="store_true",
        help="Mix once, then render many targets via scene/render_plan -> variants.",
    )
    run_parser.add_argument(
        "--targets",
        default=_BASELINE_RENDER_TARGET_ID,
        help=(
            "Comma-separated target IDs or aliases for --render-many "
            "(default: TARGET.STEREO.2_0)."
        ),
    )
    run_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable context for --render-many render_plan jobs.",
    )
    run_parser.add_argument(
        "--translation",
        action="store_true",
        help=(
            "For --render-many, run translation checks when a TARGET.STEREO.2_0 "
            "deliverable exists."
        ),
    )
    run_parser.add_argument(
        "--translation-profiles",
        default=None,
        help=(
            "Comma-separated translation profile IDs for --render-many. "
            "Implies --translation."
        ),
    )
    run_parser.add_argument(
        "--translation-audition",
        action="store_true",
        help=(
            "For --render-many, write optional translation audition WAVs when a "
            "TARGET.STEREO.2_0 deliverable exists."
        ),
    )
    run_parser.add_argument(
        "--translation-audition-segment",
        type=float,
        default=_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
        help="Segment duration in seconds for --translation-audition (default: 30).",
    )
    run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json summarizing file deliverables.",
    )
    run_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="Also write listen_pack.json for musician audition guidance.",
    )
    run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "When present, run delegates to variants mode."
        ),
    )
    run_parser.add_argument(
        "--variants",
        action="store_true",
        help="Force delegation to variants mode, even for a single preset/config.",
    )

    ui_parser = subparsers.add_parser(
        "ui",
        help="Interactive terminal launcher for musicians.",
    )
    ui_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    ui_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    ui_parser.add_argument(
        "--project",
        default=None,
        help="Optional project JSON path for lockfile and last-run context.",
    )
    ui_parser.add_argument(
        "--nerd",
        action="store_true",
        help="Show IDs, meter details, and full internal paths.",
    )

    export_parser = subparsers.add_parser(
        "export", help="Export CSV/PDF artifacts from a report JSON."
    )
    export_parser.add_argument("--report", required=True, help="Path to report JSON.")
    export_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    export_parser.add_argument("--csv", default=None, help="Optional output CSV path.")
    export_parser.add_argument("--pdf", default=None, help="Optional output PDF path.")
    export_parser.add_argument(
        "--no-measurements",
        action="store_true",
        help="Omit Measurements section from PDF output.",
    )
    export_parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Omit gate fields/sections from exports.",
    )
    export_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF cell values to this length.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare two reports (or report folders) and summarize what changed.",
    )
    compare_parser.add_argument(
        "--a",
        required=True,
        help="Path to side A report JSON, or a directory containing report.json.",
    )
    compare_parser.add_argument(
        "--b",
        required=True,
        help="Path to side B report JSON, or a directory containing report.json.",
    )
    compare_parser.add_argument(
        "--out",
        required=True,
        help="Path to output compare_report JSON.",
    )
    compare_parser.add_argument(
        "--pdf",
        default=None,
        help="Optional output compare_report PDF path.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Run renderer plugins for render-eligible recommendations.",
    )
    render_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    render_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    render_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    render_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output render manifest JSON.",
    )
    render_parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Optional output directory for renderer artifacts. "
            "Required for plugins that produce real render files."
        ),
    )
    render_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    render_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render gating (default: PROFILE.ASSIST).",
    )
    render_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config.",
    )
    render_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config.",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Run renderer plugins for auto-apply eligible recommendations.",
    )
    apply_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    apply_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    apply_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    apply_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    apply_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output apply manifest JSON.",
    )
    apply_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for applied renderer artifacts.",
    )
    apply_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    apply_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for auto-apply gating (default: PROFILE.ASSIST).",
    )
    apply_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config.",
    )
    apply_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config.",
    )
    apply_parser.add_argument(
        "--out-report",
        default=None,
        help=(
            "Optional output path for a report JSON rewritten to point stems to "
            "applied artifacts."
        ),
    )

    bundle_parser = subparsers.add_parser(
        "bundle",
        help=(
            "Build a single UI bundle JSON from report + optional render/apply manifests "
            "and optional applied report."
        ),
    )
    bundle_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    bundle_parser.add_argument(
        "--render-manifest",
        default=None,
        help="Optional path to render manifest JSON.",
    )
    bundle_parser.add_argument(
        "--apply-manifest",
        default=None,
        help="Optional path to apply manifest JSON.",
    )
    bundle_parser.add_argument(
        "--applied-report",
        default=None,
        help="Optional path to applied report JSON.",
    )
    bundle_parser.add_argument(
        "--project",
        default=None,
        help="Optional path to project JSON for embedding project summary metadata.",
    )
    bundle_parser.add_argument(
        "--deliverables-index",
        default=None,
        help="Optional path to deliverables_index JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--listen-pack",
        default=None,
        help="Optional path to listen_pack JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--scene",
        default=None,
        help="Optional path to scene JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--render-plan",
        default=None,
        help="Optional path to render_plan JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--stems-index",
        default=None,
        help="Optional path to stems_index JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--stems-map",
        default=None,
        help="Optional path to stems_map JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--gui-state",
        default=None,
        help="Optional path to gui_state JSON for GUI pointer metadata.",
    )
    bundle_parser.add_argument(
        "--ui-locale",
        default=None,
        help="Optional UI copy locale (default: registry default_locale).",
    )
    bundle_parser.add_argument(
        "--out",
        required=True,
        help="Path to output UI bundle JSON.",
    )

    variants_parser = subparsers.add_parser(
        "variants",
        help="Run multiple deterministic variants in one command.",
    )
    variants_subparsers = variants_parser.add_subparsers(
        dest="variants_command",
        required=True,
    )
    variants_run_parser = variants_subparsers.add_parser(
        "run",
        help="Run one or more preset/config variants and write deterministic artifacts.",
    )
    variants_run_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    variants_run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the output directory for all variant artifacts.",
    )
    variants_run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID; may be provided multiple times.",
    )
    variants_run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path; may be provided multiple times.",
    )
    variants_run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow for each variant.",
    )
    variants_run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow for each variant.",
    )
    variants_run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF for each variant.",
    )
    variants_run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export report CSV for each variant.",
    )
    variants_run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle for each variant.",
    )
    variants_run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact for each variant.",
    )
    variants_run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact for each variant (auto-builds scene.json).",
    )
    variants_run_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="Also write listen_pack.json for musician audition guidance.",
    )
    variants_run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json for all variant outputs.",
    )
    variants_run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override for each variant.",
    )
    variants_run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    variants_run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--routing",
        action="store_true",
        help="Build and persist routing_plan for each variant.",
    )
    variants_run_parser.add_argument(
        "--target-layout",
        default=None,
        help="downmix.target_layout_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--policy-id",
        default=None,
        help="downmix.policy_id override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--downmix-qa",
        action="store_true",
        help="Run downmix QA for each variant after analyze and merge into report.",
    )
    variants_run_parser.add_argument(
        "--qa-ref",
        default=None,
        help="Path to stereo QA reference used when --downmix-qa is enabled.",
    )
    variants_run_parser.add_argument(
        "--qa-meters",
        choices=["basic", "truth"],
        default=None,
        help="Meter pack for downmix QA (basic or truth).",
    )
    variants_run_parser.add_argument(
        "--qa-max-seconds",
        type=float,
        default=None,
        help="max_seconds override for downmix QA only.",
    )
    variants_run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config for each variant.",
    )
    variants_run_parser.add_argument(
        "--output-formats",
        default=None,
        help=(
            "Comma-separated lossless output formats (wav,flac,wv,aiff,alac) "
            "for both render and apply variant steps."
        ),
    )
    variants_run_parser.add_argument(
        "--render-output-formats",
        default=None,
        help="Comma-separated lossless output formats for render variant steps.",
    )
    variants_run_parser.add_argument(
        "--apply-output-formats",
        default=None,
        help="Comma-separated lossless output formats for apply variant steps.",
    )
    variants_run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "Each set expands every base variant into a deterministic sub-variant."
        ),
    )
    variants_run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    variants_run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    variants_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    variants_listen_pack_parser = variants_subparsers.add_parser(
        "listen-pack",
        help="Build a deterministic listen pack index from a variant_result JSON.",
    )
    variants_listen_pack_parser.add_argument(
        "--variant-result",
        required=True,
        help="Path to variant_result JSON.",
    )
    variants_listen_pack_parser.add_argument(
        "--out",
        required=True,
        help="Path to output listen_pack JSON.",
    )

    deliverables_parser = subparsers.add_parser(
        "deliverables",
        help="Deliverables index tools.",
    )
    deliverables_subparsers = deliverables_parser.add_subparsers(
        dest="deliverables_command",
        required=True,
    )
    deliverables_index_parser = deliverables_subparsers.add_parser(
        "index",
        help="Build a deterministic deliverables index JSON.",
    )
    deliverables_index_parser.add_argument(
        "--out-dir",
        required=True,
        help="Path to output directory that contains run artifacts.",
    )
    deliverables_index_parser.add_argument(
        "--out",
        required=True,
        help="Path to output deliverables_index JSON.",
    )
    deliverables_index_parser.add_argument(
        "--variant-result",
        default=None,
        help="Optional variant_result JSON path (switches to variants mode).",
    )

    plugins_parser = subparsers.add_parser("plugins", help="Plugin registry tools.")
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_list_parser = plugins_subparsers.add_parser(
        "list",
        help="List discovered plugins and capability metadata.",
    )
    plugins_list_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    plugins_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the plugin list.",
    )

    presets_parser = subparsers.add_parser("presets", help="Run config preset tools.")
    presets_subparsers = presets_parser.add_subparsers(dest="presets_command", required=True)
    presets_list_parser = presets_subparsers.add_parser("list", help="List available presets.")
    presets_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the preset list.",
    )
    presets_list_parser.add_argument(
        "--tag",
        default=None,
        help="Optional tag filter (matches entries in tags).",
    )
    presets_list_parser.add_argument(
        "--category",
        default=None,
        help="Optional category filter (e.g., VIBE, WORKFLOW).",
    )
    presets_show_parser = presets_subparsers.add_parser("show", help="Show one preset.")
    presets_show_parser.add_argument(
        "preset_id",
        help="Preset ID (e.g., PRESET.SAFE_CLEANUP).",
    )
    presets_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preset details.",
    )
    presets_preview_parser = presets_subparsers.add_parser(
        "preview",
        help="Preview musician guidance and merged run_config changes for a preset.",
    )
    presets_preview_parser.add_argument(
        "preset_id",
        help="Preset ID (e.g., PRESET.SAFE_CLEANUP).",
    )
    presets_preview_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    presets_preview_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preview details.",
    )
    presets_preview_parser.add_argument(
        "--profile",
        default=_PRESET_PREVIEW_DEFAULT_PROFILE_ID,
        help=(
            "Profile override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_PROFILE_ID})."
        ),
    )
    presets_preview_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=_PRESET_PREVIEW_DEFAULT_METERS,
        help=(
            "Meters override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_METERS})."
        ),
    )
    presets_preview_parser.add_argument(
        "--max-seconds",
        type=float,
        default=_PRESET_PREVIEW_DEFAULT_MAX_SECONDS,
        help=(
            "max_seconds override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_MAX_SECONDS})."
        ),
    )
    presets_preview_parser.add_argument(
        "--source-layout",
        default=None,
        help="downmix.source_layout_id override for previewed merge results.",
    )
    presets_preview_parser.add_argument(
        "--target-layout",
        default=_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID,
        help=(
            "downmix.target_layout_id override for previewed merge results "
            f"(default: {_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID})."
        ),
    )
    presets_preview_parser.add_argument(
        "--policy-id",
        default=None,
        help="downmix.policy_id override for previewed merge results.",
    )
    presets_recommend_parser = presets_subparsers.add_parser(
        "recommend",
        help="Recommend presets from report vibe and safety signals.",
    )
    presets_recommend_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON used for deriving recommendations.",
    )
    presets_recommend_parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Number of presets to suggest (default: 3).",
    )
    presets_recommend_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for recommendation details.",
    )
    presets_packs_parser = presets_subparsers.add_parser(
        "packs",
        help="List and inspect preset packs.",
    )
    presets_packs_subparsers = presets_packs_parser.add_subparsers(
        dest="presets_packs_command",
        required=True,
    )
    presets_packs_list_parser = presets_packs_subparsers.add_parser(
        "list",
        help="List preset packs.",
    )
    presets_packs_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the preset pack list.",
    )
    presets_packs_show_parser = presets_packs_subparsers.add_parser(
        "show",
        help="Show one preset pack.",
    )
    presets_packs_show_parser.add_argument(
        "pack_id",
        help="Pack ID (e.g., PACK.VIBE_STARTER).",
    )
    presets_packs_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for preset pack details.",
    )

    help_parser = subparsers.add_parser("help", help="Registry help tools.")
    help_subparsers = help_parser.add_subparsers(dest="help_command", required=True)
    help_list_parser = help_subparsers.add_parser("list", help="List help entries.")
    help_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the help list.",
    )
    help_show_parser = help_subparsers.add_parser("show", help="Show one help entry.")
    help_show_parser.add_argument(
        "help_id",
        help="Help ID (e.g., HELP.PRESET.SAFE_CLEANUP).",
    )
    help_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for help details.",
    )

    targets_parser = subparsers.add_parser("targets", help="Render target registry tools.")
    targets_subparsers = targets_parser.add_subparsers(dest="targets_command", required=True)
    targets_list_parser = targets_subparsers.add_parser("list", help="List render targets.")
    targets_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the render target list.",
    )
    targets_list_parser.add_argument(
        "--long",
        action="store_true",
        help="Show notes and aliases in text output.",
    )
    targets_show_parser = targets_subparsers.add_parser("show", help="Show one render target.")
    targets_show_parser.add_argument(
        "target_id",
        help="Render target ID or alias (e.g., TARGET.STEREO.2_0, Stereo (streaming)).",
    )
    targets_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for render target details.",
    )
    targets_recommend_parser = targets_subparsers.add_parser(
        "recommend",
        help="Recommend conservative render targets from report and scene signals.",
    )
    targets_recommend_parser.add_argument(
        "--report",
        default=None,
        help="Path to report JSON, or a directory containing report.json.",
    )
    targets_recommend_parser.add_argument(
        "--scene",
        default=None,
        help="Optional path to scene JSON.",
    )
    targets_recommend_parser.add_argument(
        "--max",
        dest="max_results",
        type=int,
        default=3,
        help="Maximum number of target recommendations to return (default: 3).",
    )
    targets_recommend_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for recommended targets.",
    )

    roles_parser = subparsers.add_parser("roles", help="Role registry tools.")
    roles_subparsers = roles_parser.add_subparsers(dest="roles_command", required=True)
    roles_list_parser = roles_subparsers.add_parser("list", help="List role IDs.")
    roles_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for role list.",
    )
    roles_show_parser = roles_subparsers.add_parser("show", help="Show one role entry.")
    roles_show_parser.add_argument(
        "role_id",
        help="Role ID (e.g., ROLE.BASS.AMP).",
    )
    roles_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for role details.",
    )

    translation_parser = subparsers.add_parser(
        "translation",
        help="Translation profile registry tools.",
    )
    translation_subparsers = translation_parser.add_subparsers(
        dest="translation_command",
        required=True,
    )
    translation_list_parser = translation_subparsers.add_parser(
        "list",
        help="List translation profiles.",
    )
    translation_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation profile list.",
    )
    translation_show_parser = translation_subparsers.add_parser(
        "show",
        help="Show one translation profile.",
    )
    translation_show_parser.add_argument(
        "profile_id",
        help="Translation profile ID (e.g., TRANS.MONO.COLLAPSE).",
    )
    translation_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation profile details.",
    )
    translation_run_parser = translation_subparsers.add_parser(
        "run",
        help="Run deterministic meter-only translation checks from a WAV file.",
    )
    translation_run_parser.add_argument(
        "--audio",
        required=True,
        help="Path to mono/stereo WAV input.",
    )
    translation_run_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_run_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation check results.",
    )
    translation_run_parser.add_argument(
        "--out",
        default=None,
        help="Optional output JSON path for translation_results list.",
    )
    translation_run_parser.add_argument(
        "--report-in",
        default=None,
        help="Optional input report JSON path to patch translation_results.",
    )
    translation_run_parser.add_argument(
        "--report-out",
        default=None,
        help="Output report JSON path for patched translation_results.",
    )
    translation_run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable deterministic translation check caching.",
    )
    translation_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    translation_compare_parser = translation_subparsers.add_parser(
        "compare",
        help="Run deterministic translation checks across multiple WAV inputs.",
    )
    translation_compare_audio_group = translation_compare_parser.add_mutually_exclusive_group(
        required=True
    )
    translation_compare_audio_group.add_argument(
        "--audio",
        default=None,
        help="Comma-separated WAV paths to compare.",
    )
    translation_compare_audio_group.add_argument(
        "--in-dir",
        default=None,
        help="Directory containing WAV files for comparison.",
    )
    translation_compare_parser.add_argument(
        "--glob",
        default="*.wav",
        help="Optional glob pattern for --in-dir discovery (default: *.wav).",
    )
    translation_compare_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_compare_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for translation compare rows.",
    )
    translation_audition_parser = translation_subparsers.add_parser(
        "audition",
        help="Render deterministic translation audition WAVs from a WAV file.",
    )
    translation_audition_parser.add_argument(
        "--audio",
        required=True,
        help="Path to mono/stereo WAV input.",
    )
    translation_audition_parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated translation profile IDs.",
    )
    translation_audition_parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory root for translation_auditions artifacts.",
    )
    translation_audition_parser.add_argument(
        "--segment",
        type=float,
        default=None,
        help="Optional segment duration in seconds (from start).",
    )
    translation_audition_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable deterministic translation audition caching.",
    )
    translation_audition_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )

    locks_parser = subparsers.add_parser("locks", help="Scene lock registry tools.")
    locks_subparsers = locks_parser.add_subparsers(dest="locks_command", required=True)
    locks_list_parser = locks_subparsers.add_parser("list", help="List scene locks.")
    locks_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the scene lock list.",
    )
    locks_show_parser = locks_subparsers.add_parser("show", help="Show one scene lock.")
    locks_show_parser.add_argument(
        "lock_id",
        help="Scene lock ID (e.g., LOCK.PRESERVE_DYNAMICS).",
    )
    locks_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene lock details.",
    )

    ui_copy_parser = subparsers.add_parser("ui-copy", help="UI copy registry tools.")
    ui_copy_subparsers = ui_copy_parser.add_subparsers(
        dest="ui_copy_command",
        required=True,
    )
    ui_copy_list_parser = ui_copy_subparsers.add_parser(
        "list",
        help="List UI copy entries.",
    )
    ui_copy_list_parser.add_argument(
        "--locale",
        default=None,
        help="Optional locale (default: registry default_locale).",
    )
    ui_copy_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI copy list.",
    )
    ui_copy_show_parser = ui_copy_subparsers.add_parser(
        "show",
        help="Show one UI copy entry.",
    )
    ui_copy_show_parser.add_argument(
        "copy_id",
        help="Copy key (e.g., COPY.NAV.DASHBOARD).",
    )
    ui_copy_show_parser.add_argument(
        "--locale",
        default=None,
        help="Optional locale (default: registry default_locale).",
    )
    ui_copy_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI copy details.",
    )

    ui_examples_parser = subparsers.add_parser(
        "ui-examples",
        help="Mock UI screen example tools.",
    )
    ui_examples_subparsers = ui_examples_parser.add_subparsers(
        dest="ui_examples_command",
        required=True,
    )
    ui_examples_list_parser = ui_examples_subparsers.add_parser(
        "list",
        help="List available UI screen examples.",
    )
    ui_examples_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI example list.",
    )
    ui_examples_show_parser = ui_examples_subparsers.add_parser(
        "show",
        help="Show one UI screen example.",
    )
    ui_examples_show_parser.add_argument(
        "filename",
        help="Example filename (for example dashboard_default_safe.json).",
    )
    ui_examples_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for UI example details.",
    )

    lock_parser = subparsers.add_parser("lock", help="Project lockfile tools.")
    lock_subparsers = lock_parser.add_subparsers(dest="lock_command", required=True)
    lock_write_parser = lock_subparsers.add_parser(
        "write", help="Write a deterministic lockfile for a stems directory."
    )
    lock_write_parser.add_argument("stems_dir", help="Path to a directory of input files.")
    lock_write_parser.add_argument(
        "--out",
        required=True,
        help="Path to output lockfile JSON.",
    )
    lock_verify_parser = lock_subparsers.add_parser(
        "verify", help="Verify a stems directory against a lockfile."
    )
    lock_verify_parser.add_argument("stems_dir", help="Path to a directory of input files.")
    lock_verify_parser.add_argument(
        "--lock",
        required=True,
        help="Path to lockfile JSON.",
    )
    lock_verify_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for verification result JSON.",
    )

    project_parser = subparsers.add_parser("project", help="Project file tools.")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_new_parser = project_subparsers.add_parser(
        "new",
        help="Create a new MMO project file.",
    )
    project_new_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    project_new_parser.add_argument(
        "--out",
        required=True,
        help="Path to output project JSON.",
    )
    project_new_parser.add_argument(
        "--notes",
        default=None,
        help="Optional project notes string.",
    )

    project_show_parser = project_subparsers.add_parser(
        "show",
        help="Display one project file.",
    )
    project_show_parser.add_argument(
        "--project",
        required=True,
        help="Path to a project JSON file.",
    )
    project_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for project display.",
    )

    project_run_parser = project_subparsers.add_parser(
        "run",
        help="Run workflow from a project file and update the project in place.",
    )
    project_run_parser.add_argument(
        "--project",
        required=True,
        help="Path to a project JSON file.",
    )
    project_run_parser.add_argument(
        "--out",
        required=True,
        help="Path to the deterministic output directory.",
    )
    project_run_parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Optional preset ID from presets/index.json. May be provided multiple times.",
    )
    project_run_parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Optional run config JSON path. May be provided multiple times.",
    )
    project_run_parser.add_argument(
        "--profile",
        default=None,
        help="Authority profile ID override.",
    )
    project_run_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    project_run_parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="max_seconds override in run_config.",
    )
    project_run_parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Export report PDF.",
    )
    project_run_parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export recall CSV.",
    )
    project_run_parser.add_argument(
        "--truncate-values",
        type=int,
        default=None,
        help="truncate_values override in run_config.",
    )
    project_run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Run auto-apply renderer flow.",
    )
    project_run_parser.add_argument(
        "--render",
        action="store_true",
        help="Run render-eligible renderer flow.",
    )
    project_run_parser.add_argument(
        "--output-formats",
        default=None,
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    project_run_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to a timeline JSON with section markers.",
    )
    project_run_parser.add_argument(
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
    )
    project_run_parser.add_argument(
        "--scene",
        action="store_true",
        help="Build a scene.json intent artifact.",
    )
    project_run_parser.add_argument(
        "--render-plan",
        action="store_true",
        help="Build a render_plan.json artifact (auto-builds scene.json if needed).",
    )
    project_run_parser.add_argument(
        "--scene-templates",
        default=None,
        help="Comma-separated scene template IDs applied in --render-many before render-plan/variants.",
    )
    project_run_parser.add_argument(
        "--render-many",
        action="store_true",
        help="Mix once, then render many targets via scene/render_plan -> variants.",
    )
    project_run_parser.add_argument(
        "--targets",
        default=_BASELINE_RENDER_TARGET_ID,
        help=(
            "Comma-separated target IDs or aliases for --render-many "
            "(default: TARGET.STEREO.2_0)."
        ),
    )
    project_run_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable context for --render-many render_plan jobs.",
    )
    project_run_parser.add_argument(
        "--translation",
        action="store_true",
        help=(
            "For --render-many, run translation checks when a TARGET.STEREO.2_0 "
            "deliverable exists."
        ),
    )
    project_run_parser.add_argument(
        "--translation-profiles",
        default=None,
        help=(
            "Comma-separated translation profile IDs for --render-many. "
            "Implies --translation."
        ),
    )
    project_run_parser.add_argument(
        "--translation-audition",
        action="store_true",
        help=(
            "For --render-many, write optional translation audition WAVs when a "
            "TARGET.STEREO.2_0 deliverable exists."
        ),
    )
    project_run_parser.add_argument(
        "--translation-audition-segment",
        type=float,
        default=_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
        help="Segment duration in seconds for --translation-audition (default: 30).",
    )
    project_run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json summarizing file deliverables.",
    )
    project_run_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="Reuse cached analysis by lockfile + run_config hash (default: on).",
    )
    project_run_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    project_run_parser.add_argument(
        "--format-set",
        action="append",
        default=[],
        help=(
            "Repeatable output format set in <name>:<csv> form. "
            "When present, run delegates to variants mode."
        ),
    )
    project_run_parser.add_argument(
        "--variants",
        action="store_true",
        help="Force delegation to variants mode, even for a single preset/config.",
    )

    downmix_parser = subparsers.add_parser("downmix", help="Downmix policy tools.")
    downmix_subparsers = downmix_parser.add_subparsers(dest="downmix_command", required=True)
    downmix_show_parser = downmix_subparsers.add_parser(
        "show", help="Resolve and display a downmix matrix."
    )
    downmix_show_parser.add_argument(
        "--source",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_show_parser.add_argument(
        "--target",
        required=True,
        help="Target layout ID (e.g., LAYOUT.2_0).",
    )
    downmix_show_parser.add_argument(
        "--policy",
        default=None,
        help=(
            "Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0). "
            "See `mmo downmix list --policies` for available IDs."
        ),
    )
    downmix_show_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format for the resolved matrix.",
    )
    downmix_show_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout.",
    )
    downmix_qa_parser = downmix_subparsers.add_parser(
        "qa", help="Compare folded downmix against a stereo reference."
    )
    downmix_qa_parser.add_argument(
        "--src",
        required=True,
        help="Path to the multichannel source file.",
    )
    downmix_qa_parser.add_argument(
        "--ref",
        required=True,
        help="Path to the stereo reference file.",
    )
    downmix_qa_parser.add_argument(
        "--source-layout",
        default=None,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_qa_parser.add_argument(
        "--target-layout",
        default="LAYOUT.2_0",
        help="Target layout ID for the fold-down (default: LAYOUT.2_0).",
    )
    downmix_qa_parser.add_argument(
        "--policy",
        default=None,
        help=(
            "Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0). "
            "See `mmo downmix list --policies` for available IDs."
        ),
    )
    downmix_qa_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default="truth",
        help="Meter pack to use (basic or truth).",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-lufs",
        type=float,
        default=1.0,
        help="LUFS delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-true-peak",
        type=float,
        default=1.0,
        help="True peak delta tolerance (dBTP) for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-corr",
        type=float,
        default=0.15,
        help="Correlation delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="Maximum overlap seconds to compare (<= 0 disables the cap).",
    )
    downmix_qa_parser.add_argument(
        "--format",
        choices=["json", "csv", "pdf"],
        default="json",
        help="Output format for downmix QA results.",
    )
    downmix_qa_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout for json/csv.",
    )
    downmix_qa_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF values to this length.",
    )
    downmix_qa_parser.add_argument(
        "--emit-report",
        default=None,
        help="Optional output path for a full MMO report JSON embedding downmix QA.",
    )
    downmix_qa_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help=(
            "Authority profile ID used for gate eligibility when --emit-report is set "
            "(default: PROFILE.ASSIST)."
        ),
    )
    downmix_qa_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    downmix_qa_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    downmix_list_parser = downmix_subparsers.add_parser(
        "list", help="List available downmix layouts, policies, and conversions."
    )
    downmix_list_parser.add_argument(
        "--layouts",
        action="store_true",
        help="Show available layout IDs.",
    )
    downmix_list_parser.add_argument(
        "--policies",
        action="store_true",
        help="Show available policy IDs.",
    )
    downmix_list_parser.add_argument(
        "--conversions",
        action="store_true",
        help="Show available conversions and policy coverage.",
    )
    downmix_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the list.",
    )
    downmix_render_parser = downmix_subparsers.add_parser(
        "render", help="Run renderer plugins for render-eligible recommendations."
    )
    downmix_render_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    downmix_render_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a run config JSON file.",
    )
    downmix_render_parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset ID from presets/index.json.",
    )
    downmix_render_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory.",
    )
    downmix_render_parser.add_argument(
        "--out-manifest",
        required=True,
        help="Path to output render manifest JSON.",
    )
    downmix_render_parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for renderer artifacts.",
    )
    downmix_render_parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for render gating (default: PROFILE.ASSIST).",
    )

    routing_parser = subparsers.add_parser("routing", help="Layout-aware routing tools.")
    routing_subparsers = routing_parser.add_subparsers(dest="routing_command", required=True)
    routing_show_parser = routing_subparsers.add_parser(
        "show", help="Build and display a deterministic stem routing plan."
    )
    routing_show_parser.add_argument(
        "--stems",
        required=True,
        help="Path to a directory of audio stems.",
    )
    routing_show_parser.add_argument(
        "--source-layout",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    routing_show_parser.add_argument(
        "--target-layout",
        required=True,
        help="Target layout ID (e.g., LAYOUT.2_0).",
    )
    routing_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format for routing plan.",
    )

    scene_parser = subparsers.add_parser("scene", help="Scene intent artifact tools.")
    scene_subparsers = scene_parser.add_subparsers(
        dest="scene_command",
        required=True,
    )
    scene_build_parser = scene_subparsers.add_parser(
        "build",
        help="Build a deterministic scene JSON from a report and optional timeline.",
    )
    scene_build_parser.add_argument(
        "--report",
        required=True,
        help="Path to report JSON.",
    )
    scene_build_parser.add_argument(
        "--timeline",
        default=None,
        help="Optional path to timeline JSON.",
    )
    scene_build_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_build_parser.add_argument(
        "--templates",
        default=None,
        help="Optional comma-separated scene template IDs to apply in order.",
    )
    scene_build_parser.add_argument(
        "--force-templates",
        action="store_true",
        help="When used with --templates, overwrite existing intent fields (hard locks still apply).",
    )
    scene_show_parser = scene_subparsers.add_parser(
        "show",
        help="Display a scene JSON.",
    )
    scene_show_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene display.",
    )
    scene_validate_parser = scene_subparsers.add_parser(
        "validate",
        help="Validate a scene JSON against schema.",
    )
    scene_validate_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_parser = scene_subparsers.add_parser(
        "locks",
        help="Edit scene locks.",
    )
    scene_locks_subparsers = scene_locks_parser.add_subparsers(
        dest="scene_locks_command",
        required=True,
    )
    scene_locks_add_parser = scene_locks_subparsers.add_parser(
        "add",
        help="Add a lock to scene/object/bed intent.",
    )
    scene_locks_add_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_add_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Lock scope.",
    )
    scene_locks_add_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_locks_add_parser.add_argument(
        "--lock",
        required=True,
        help="Lock ID from ontology/scene_locks.yaml.",
    )
    scene_locks_add_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_locks_remove_parser = scene_locks_subparsers.add_parser(
        "remove",
        help="Remove a lock from scene/object/bed intent.",
    )
    scene_locks_remove_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_locks_remove_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Lock scope.",
    )
    scene_locks_remove_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_locks_remove_parser.add_argument(
        "--lock",
        required=True,
        help="Lock ID from ontology/scene_locks.yaml.",
    )
    scene_locks_remove_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )

    scene_intent_parser = scene_subparsers.add_parser(
        "intent",
        help="View and edit scene intent fields.",
    )
    scene_intent_subparsers = scene_intent_parser.add_subparsers(
        dest="scene_intent_command",
        required=True,
    )
    scene_intent_set_parser = scene_intent_subparsers.add_parser(
        "set",
        help="Set one scene intent field for scene/object/bed.",
    )
    scene_intent_set_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_intent_set_parser.add_argument(
        "--scope",
        choices=["scene", "object", "bed"],
        required=True,
        help="Intent scope.",
    )
    scene_intent_set_parser.add_argument(
        "--id",
        default=None,
        help="object_id or bed_id for non-scene scopes.",
    )
    scene_intent_set_parser.add_argument(
        "--key",
        choices=list(_SCENE_INTENT_KEYS),
        required=True,
        help="Intent field key.",
    )
    scene_intent_set_parser.add_argument(
        "--value",
        required=True,
        help="Intent field value.",
    )
    scene_intent_set_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_intent_show_parser = scene_intent_subparsers.add_parser(
        "show",
        help="Show scene/object/bed intent sections.",
    )
    scene_intent_show_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_intent_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene intent display.",
    )
    scene_template_parser = scene_subparsers.add_parser(
        "template",
        help="Scene template registry and apply tools.",
    )
    scene_template_subparsers = scene_template_parser.add_subparsers(
        dest="scene_template_command",
        required=True,
    )
    scene_template_list_parser = scene_template_subparsers.add_parser(
        "list",
        help="List scene templates.",
    )
    scene_template_list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene template list.",
    )
    scene_template_show_parser = scene_template_subparsers.add_parser(
        "show",
        help="Show one or more scene templates.",
    )
    scene_template_show_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) (e.g., TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER).",
    )
    scene_template_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for scene template details.",
    )
    scene_template_apply_parser = scene_template_subparsers.add_parser(
        "apply",
        help="Apply one or more templates to a scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) to apply in order.",
    )
    scene_template_apply_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "--out",
        required=True,
        help="Path to output scene JSON.",
    )
    scene_template_apply_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing intent fields (hard locks are still respected).",
    )
    scene_template_preview_parser = scene_template_subparsers.add_parser(
        "preview",
        help="Preview template changes without writing files.",
    )
    scene_template_preview_parser.add_argument(
        "template_ids",
        nargs="+",
        help="Scene template ID(s) to preview in order.",
    )
    scene_template_preview_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    scene_template_preview_parser.add_argument(
        "--force",
        action="store_true",
        help="Preview overwriting existing intent fields (hard locks are still respected).",
    )
    scene_template_preview_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for template preview.",
    )

    render_plan_parser = subparsers.add_parser(
        "render-plan",
        help="Render plan artifact tools.",
    )
    render_plan_subparsers = render_plan_parser.add_subparsers(
        dest="render_plan_command",
        required=True,
    )
    render_plan_build_parser = render_plan_subparsers.add_parser(
        "build",
        help="Build a deterministic render_plan JSON from scene + targets.",
    )
    render_plan_build_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_plan_build_parser.add_argument(
        "--targets",
        required=True,
        help=(
            "Comma-separated target IDs or aliases "
            "(e.g., TARGET.STEREO.2_0,5.1 (home theater))."
        ),
    )
    render_plan_build_parser.add_argument(
        "--out",
        required=True,
        help="Path to output render_plan JSON.",
    )
    render_plan_build_parser.add_argument(
        "--routing-plan",
        default=None,
        help="Optional path to routing_plan JSON.",
    )
    render_plan_build_parser.add_argument(
        "--output-formats",
        default="wav",
        help="Comma-separated lossless output formats (wav,flac,wv,aiff,alac).",
    )
    render_plan_build_parser.add_argument(
        "--context",
        action="append",
        choices=["render", "auto_apply"],
        default=[],
        help="Repeatable render context.",
    )
    render_plan_build_parser.add_argument(
        "--policy-id",
        default=None,
        help="Optional downmix policy ID override.",
    )
    render_plan_to_variants_parser = render_plan_subparsers.add_parser(
        "to-variants",
        help="Convert scene + render_plan into a schema-valid executable variant_plan.",
    )
    render_plan_to_variants_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--scene",
        required=True,
        help="Path to scene JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--out",
        required=True,
        help="Path to output variant_plan JSON.",
    )
    render_plan_to_variants_parser.add_argument(
        "--out-dir",
        required=True,
        help="Root output directory used for per-variant artifact folders.",
    )
    render_plan_to_variants_parser.add_argument(
        "--run",
        action="store_true",
        help="Immediately execute the generated variant plan.",
    )
    render_plan_to_variants_parser.add_argument(
        "--listen-pack",
        action="store_true",
        help="When --run is set, also write listen_pack.json.",
    )
    render_plan_to_variants_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="When --run is set, also write deliverables_index.json.",
    )
    render_plan_to_variants_parser.add_argument(
        "--cache",
        choices=["on", "off"],
        default="on",
        help="When --run is set, reuse cached analysis by lockfile + run_config hash.",
    )
    render_plan_to_variants_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional cache directory (default: <repo_root>/.mmo_cache).",
    )
    render_plan_show_parser = render_plan_subparsers.add_parser(
        "show",
        help="Display a render_plan JSON.",
    )
    render_plan_show_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )
    render_plan_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for render_plan display.",
    )
    render_plan_validate_parser = render_plan_subparsers.add_parser(
        "validate",
        help="Validate a render_plan JSON against schema.",
    )
    render_plan_validate_parser.add_argument(
        "--render-plan",
        required=True,
        help="Path to render_plan JSON.",
    )

    timeline_parser = subparsers.add_parser("timeline", help="Timeline marker tools.")
    timeline_subparsers = timeline_parser.add_subparsers(
        dest="timeline_command",
        required=True,
    )
    timeline_validate_parser = timeline_subparsers.add_parser(
        "validate",
        help="Validate and normalize a timeline JSON.",
    )
    timeline_validate_parser.add_argument(
        "--timeline",
        required=True,
        help="Path to timeline JSON.",
    )
    timeline_show_parser = timeline_subparsers.add_parser(
        "show",
        help="Show a normalized timeline JSON.",
    )
    timeline_show_parser.add_argument(
        "--timeline",
        required=True,
        help="Path to timeline JSON.",
    )
    timeline_show_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for timeline display.",
    )
    gui_state_parser = subparsers.add_parser("gui-state", help="GUI state artifact tools.")
    gui_state_subparsers = gui_state_parser.add_subparsers(
        dest="gui_state_command",
        required=True,
    )
    gui_state_validate_parser = gui_state_subparsers.add_parser(
        "validate",
        help="Validate a gui_state JSON file.",
    )
    gui_state_validate_parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to gui_state JSON.",
    )
    gui_state_default_parser = gui_state_subparsers.add_parser(
        "default",
        help="Write a default gui_state JSON file.",
    )
    gui_state_default_parser.add_argument(
        "--out",
        required=True,
        help="Path to output gui_state JSON.",
    )

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw_argv)
    repo_root = Path(__file__).resolve().parents[2]
    tools_dir = repo_root / "tools"
    presets_dir = repo_root / "presets"

    if args.command == "scan":
        return _run_scan(
            tools_dir,
            Path(args.stems_dir),
            Path(args.out),
            args.meters,
            args.peak,
        )
    if args.command == "stems":
        if args.stems_command == "scan":
            try:
                payload = build_stems_index(
                    Path(args.root),
                    root_dir=args.root,
                )
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                stem_sets = (
                    payload.get("stem_sets")
                    if isinstance(payload.get("stem_sets"), list)
                    else []
                )
                print(_render_stem_sets_text(stem_sets))
            return 0

        if args.stems_command == "sets":
            try:
                payload = resolve_stem_sets(Path(args.root))
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stem_sets_text(payload))
            return 0

        if args.stems_command == "classify":
            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=repo_root,
                    index_path=getattr(args, "index", None),
                    root_path=getattr(args, "root", None),
                )
                roles_payload = load_roles(roles_path)

                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(args.role_lexicon, str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(args.no_common_lexicon),
                    stems_index_ref=stems_index_ref,
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "explain":
            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload, stems_index_ref = _load_stems_index_for_classification(
                    repo_root=repo_root,
                    index_path=getattr(args, "index", None),
                    root_path=getattr(args, "root", None),
                )
                roles_payload = load_roles(roles_path)

                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(args.role_lexicon, str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map, explanations = classify_stems_with_evidence(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(args.no_common_lexicon),
                    stems_index_ref=stems_index_ref,
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                payload = _build_stem_explain_payload(
                    stems_map=stems_map,
                    explanations=explanations,
                    file_selector=args.file,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stem_explain_text(payload))
            return 0

        if args.stems_command == "apply-overrides":
            try:
                stems_map_payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.map),
                )
                overrides_payload = load_stems_overrides(Path(args.overrides))
                payload = apply_overrides(stems_map_payload, overrides_payload)
                _validate_json_payload(
                    payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            _write_json_file(Path(args.out), payload)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "review":
            try:
                payload = _load_stems_map(
                    repo_root=repo_root,
                    map_path=Path(args.map),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_stems_map_text(payload))
            return 0

        if args.stems_command == "pipeline":
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            index_path = out_dir / "stems_index.json"
            map_path = out_dir / "stems_map.json"
            overrides_path = out_dir / "stems_overrides.yaml"

            roles_path = repo_root / "ontology" / "roles.yaml"
            try:
                stems_index_payload = build_stems_index(
                    Path(args.root),
                    root_dir=args.root,
                )
                _validate_json_payload(
                    stems_index_payload,
                    schema_path=repo_root / "schemas" / "stems_index.schema.json",
                    payload_name="Stems index",
                )
                _write_json_file(index_path, stems_index_payload)

                roles_payload = load_roles(roles_path)
                role_lexicon_payload: dict[str, Any] | None = None
                role_lexicon_ref: str | None = None
                if isinstance(getattr(args, "role_lexicon", None), str) and args.role_lexicon.strip():
                    role_lexicon_ref = _path_ref(args.role_lexicon)
                    role_lexicon_payload = load_role_lexicon(
                        Path(args.role_lexicon),
                        roles_payload=roles_payload,
                    )

                stems_map_payload = classify_stems(
                    stems_index_payload,
                    roles_payload,
                    role_lexicon=role_lexicon_payload,
                    use_common_role_lexicon=not bool(getattr(args, "no_common_lexicon", False)),
                    stems_index_ref="stems_index.json",
                    roles_ref="ontology/roles.yaml",
                    role_lexicon_ref=role_lexicon_ref,
                )
                _validate_json_payload(
                    stems_map_payload,
                    schema_path=repo_root / "schemas" / "stems_map.schema.json",
                    payload_name="Stems map",
                )
                _write_json_file(map_path, stems_map_payload)

                overrides_written = False
                overrides_skipped = False
                if overrides_path.exists() and not getattr(args, "force", False):
                    overrides_skipped = True
                else:
                    template = _default_stems_overrides_template()
                    if not template.endswith("\n"):
                        template += "\n"
                    overrides_path.write_text(template, encoding="utf-8")
                    overrides_written = True

                bundle_path_str: str | None = None
                if isinstance(getattr(args, "bundle", None), str) and args.bundle.strip():
                    bundle_path = Path(args.bundle)
                    summary = stems_map_payload.get("summary")
                    if not isinstance(summary, dict):
                        summary = {}
                    bundle_payload: dict[str, Any] = {
                        "stems_index_path": index_path.resolve().as_posix(),
                        "stems_map_path": map_path.resolve().as_posix(),
                        "stems_summary": {
                            "counts_by_bus_group": summary.get("counts_by_bus_group", {}),
                            "unknown_files": summary.get("unknown_files", 0),
                        },
                    }
                    _write_json_file(bundle_path, bundle_payload)
                    bundle_path_str = str(bundle_path)

            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            files = stems_index_payload.get("files")
            file_count = len(files) if isinstance(files, list) else 0
            assignments = stems_map_payload.get("assignments")
            assignment_count = len(assignments) if isinstance(assignments, list) else 0

            result: dict[str, Any] = {
                "stems_index": str(index_path),
                "stems_map": str(map_path),
                "stems_overrides": str(overrides_path),
                "overrides_written": overrides_written,
                "overrides_skipped": overrides_skipped,
                "file_count": file_count,
                "assignment_count": assignment_count,
            }
            if bundle_path_str is not None:
                result["bundle"] = bundle_path_str

            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        if args.stems_command == "overrides":
            if args.stems_overrides_command == "default":
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                template = _default_stems_overrides_template()
                if not template.endswith("\n"):
                    template += "\n"
                out_path.write_text(template, encoding="utf-8")
                return 0

            if args.stems_overrides_command == "validate":
                try:
                    load_stems_overrides(Path(args.in_path))
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                print("Stems overrides are valid.")
                return 0

            print("Unknown stems overrides command.", file=sys.stderr)
            return 2

        print("Unknown stems command.", file=sys.stderr)
        return 2
    if args.command == "project":
        if args.project_command == "new":
            try:
                project_payload = new_project(
                    Path(args.stems),
                    notes=args.notes,
                )
                write_project(Path(args.out), project_payload)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return 0

        if args.project_command == "show":
            try:
                project_payload = load_project(Path(args.project))
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(project_payload, indent=2, sort_keys=True))
            else:
                print(_render_project_text(project_payload))
            return 0

        if args.project_command == "run":
            project_path = Path(args.project)
            out_dir = Path(args.out)
            try:
                project_payload = load_project(project_path)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            stems_dir_value = project_payload.get("stems_dir")
            if not isinstance(stems_dir_value, str) or not stems_dir_value:
                print("Project stems_dir must be a non-empty string.", file=sys.stderr)
                return 1
            stems_dir = Path(stems_dir_value)
            project_timeline_path = project_payload.get("timeline_path")
            if (
                getattr(args, "timeline", None) in {None, ""}
                and isinstance(project_timeline_path, str)
                and project_timeline_path.strip()
            ):
                args.timeline = project_timeline_path

            exit_code, run_mode = _run_workflow_from_run_args(
                repo_root=repo_root,
                tools_dir=tools_dir,
                presets_dir=presets_dir,
                stems_dir=stems_dir,
                out_dir=out_dir,
                args=args,
            )
            if exit_code != 0:
                return exit_code

            try:
                project_payload = update_project_last_run(
                    project_payload,
                    _project_last_run_payload(mode=run_mode, out_dir=out_dir),
                )
                run_config_defaults = _project_run_config_defaults(
                    mode=run_mode,
                    out_dir=out_dir,
                )
                if isinstance(run_config_defaults, dict):
                    project_payload["run_config_defaults"] = run_config_defaults

                timeline_value = getattr(args, "timeline", None)
                if isinstance(timeline_value, str) and timeline_value.strip():
                    project_payload["timeline_path"] = Path(timeline_value).resolve().as_posix()

                try:
                    from mmo.core.lockfile import build_lockfile  # noqa: WPS433

                    lock_payload = build_lockfile(stems_dir)
                except ValueError:
                    lock_payload = None
                if isinstance(lock_payload, dict):
                    lockfile_path = out_dir.resolve() / "lockfile.json"
                    _write_json_file(lockfile_path, lock_payload)
                    project_payload["lockfile_path"] = lockfile_path.as_posix()
                    project_payload["lock_hash"] = hash_lockfile(lock_payload)

                write_project(project_path, project_payload)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return 0

        print("Unknown project command.", file=sys.stderr)
        return 2
    if args.command == "ui":
        return _run_ui_workflow(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            project_path=Path(args.project) if args.project else None,
            nerd=args.nerd,
        )
    if args.command == "run":
        exit_code, _ = _run_workflow_from_run_args(
            repo_root=repo_root,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            args=args,
        )
        return exit_code
    if args.command == "analyze":
        analyze_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            analyze_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--meters"):
            analyze_overrides["meters"] = args.meters
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                analyze_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        effective_profile = _config_string(merged_run_config, "profile_id", args.profile)
        effective_meters = _config_optional_string(merged_run_config, "meters", args.meters)
        effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
        stems_dir = Path(args.stems_dir)
        out_report_path = Path(args.out_report)
        effective_run_config = _analyze_run_config(
            profile_id=effective_profile,
            meters=effective_meters,
            preset_id=effective_preset_id,
            base_run_config=merged_run_config,
        )
        cache_enabled = args.cache == "on"
        cache_dir = Path(args.cache_dir) if args.cache_dir else None
        report_schema_path = repo_root / "schemas" / "report.schema.json"
        lock_payload: dict[str, Any] | None = None
        cache_key_value: str | None = None

        if cache_enabled:
            from mmo.core.lockfile import build_lockfile  # noqa: WPS433

            try:
                lock_payload = build_lockfile(stems_dir)
                cache_key_value = _analysis_cache_key(lock_payload, effective_run_config)
            except ValueError:
                cache_enabled = False
                lock_payload = None
                cache_key_value = None

            if lock_payload is not None:
                cached_report = try_load_cached_report(
                    cache_dir,
                    lock_payload,
                    effective_run_config,
                )
                if (
                    isinstance(cached_report, dict)
                    and report_schema_is_valid(cached_report, report_schema_path)
                ):
                    rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                    if report_schema_is_valid(rewritten_report, report_schema_path):
                        _write_json_file(out_report_path, rewritten_report)
                        print(f"analysis cache: hit {cache_key_value}")
                        return 0
                print(f"analysis cache: miss {cache_key_value}")

        exit_code = _run_analyze(
            tools_dir,
            stems_dir,
            out_report_path,
            effective_meters,
            args.peak,
            args.plugins,
            args.keep_scan,
            effective_profile,
        )
        if exit_code != 0:
            return exit_code
        try:
            _stamp_report_run_config(
                out_report_path,
                effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if cache_enabled and lock_payload is not None:
            try:
                report_payload = _load_report(out_report_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if report_schema_is_valid(report_payload, report_schema_path):
                if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                    print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
                else:
                    try:
                        save_cached_report(
                            cache_dir,
                            lock_payload,
                            effective_run_config,
                            report_payload,
                        )
                    except OSError:
                        pass
        return 0
    if args.command == "export":
        export_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--truncate-values"):
            export_overrides["truncate_values"] = args.truncate_values
        try:
            merged_run_config = _load_and_merge_run_config(args.config, export_overrides)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        truncate_values = _config_int(
            merged_run_config,
            "truncate_values",
            args.truncate_values,
        )
        return _run_export(
            tools_dir,
            Path(args.report),
            args.csv,
            args.pdf,
            no_measurements=args.no_measurements,
            no_gates=args.no_gates,
            truncate_values=truncate_values,
        )
    if args.command == "compare":
        try:
            report_a, report_path_a = load_report_from_path_or_dir(Path(args.a))
            report_b, report_path_b = load_report_from_path_or_dir(Path(args.b))
            compare_report = build_compare_report(
                report_a,
                report_b,
                label_a=default_label_for_compare_input(args.a, report_path=report_path_a),
                label_b=default_label_for_compare_input(args.b, report_path=report_path_b),
                report_path_a=report_path_a,
                report_path_b=report_path_b,
            )
            _validate_json_payload(
                compare_report,
                schema_path=repo_root / "schemas" / "compare_report.schema.json",
                payload_name="Compare report",
            )
            _write_json_file(Path(args.out), compare_report)
            if args.pdf:
                from mmo.exporters.pdf_report import (  # noqa: WPS433
                    export_compare_report_pdf,
                )

                try:
                    export_compare_report_pdf(
                        compare_report,
                        Path(args.pdf),
                    )
                except RuntimeError:
                    print(
                        "PDF export requires reportlab. Install extras: pip install .[pdf]",
                        file=sys.stderr,
                    )
                    return 2
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        return 0
    if args.command == "render":
        render_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            render_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--source-layout"):
            _set_nested(
                ["downmix", "source_layout_id"],
                render_overrides,
                args.source_layout,
            )
        if _flag_present(raw_argv, "--target-layout"):
            _set_nested(
                ["downmix", "target_layout_id"],
                render_overrides,
                args.target_layout,
            )
        if _flag_present(raw_argv, "--out-dir"):
            _set_nested(["render", "out_dir"], render_overrides, args.out_dir)
        if _flag_present(raw_argv, "--output-formats"):
            try:
                render_output_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["render", "output_formats"],
                render_overrides,
                render_output_formats,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                render_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        profile_id = _config_string(merged_run_config, "profile_id", args.profile)
        out_dir = _config_nested_optional_string(
            merged_run_config,
            "render",
            "out_dir",
            args.out_dir,
        )
        output_formats = _config_nested_output_formats(
            merged_run_config,
            "render",
            ["wav"],
        )
        try:
            return _run_render_command(
                repo_root=repo_root,
                report_path=Path(args.report),
                plugins_dir=Path(args.plugins),
                out_manifest_path=Path(args.out_manifest),
                out_dir=Path(out_dir) if out_dir else None,
                profile_id=profile_id,
                command_label="render",
                output_formats=output_formats,
                run_config=merged_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "apply":
        apply_config_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            apply_config_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--source-layout"):
            _set_nested(
                ["downmix", "source_layout_id"],
                apply_config_overrides,
                args.source_layout,
            )
        if _flag_present(raw_argv, "--target-layout"):
            _set_nested(
                ["downmix", "target_layout_id"],
                apply_config_overrides,
                args.target_layout,
            )
        if _flag_present(raw_argv, "--out-dir"):
            _set_nested(["render", "out_dir"], apply_config_overrides, args.out_dir)
        if _flag_present(raw_argv, "--output-formats"):
            try:
                apply_output_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["apply", "output_formats"],
                apply_config_overrides,
                apply_output_formats,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                apply_config_overrides,
                preset_id=args.preset,
                presets_dir=presets_dir,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        profile_id = _config_string(merged_run_config, "profile_id", args.profile)
        out_dir = _config_nested_optional_string(
            merged_run_config,
            "render",
            "out_dir",
            args.out_dir,
        )
        output_formats = _config_nested_output_formats(
            merged_run_config,
            "apply",
            ["wav"],
        )
        if not out_dir:
            print(
                "Missing output directory. Provide --out-dir or set render.out_dir in --config/--preset.",
                file=sys.stderr,
            )
            return 1
        try:
            return _run_apply_command(
                repo_root=repo_root,
                report_path=Path(args.report),
                plugins_dir=Path(args.plugins),
                out_manifest_path=Path(args.out_manifest),
                out_dir=Path(out_dir),
                out_report_path=Path(args.out_report) if args.out_report else None,
                profile_id=profile_id,
                output_formats=output_formats,
                run_config=merged_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "bundle":
        try:
            return _run_bundle(
                repo_root=repo_root,
                report_path=Path(args.report),
                out_path=Path(args.out),
                render_manifest_path=(
                    Path(args.render_manifest) if args.render_manifest else None
                ),
                apply_manifest_path=Path(args.apply_manifest) if args.apply_manifest else None,
                applied_report_path=Path(args.applied_report) if args.applied_report else None,
                project_path=Path(args.project) if args.project else None,
                deliverables_index_path=(
                    Path(args.deliverables_index) if args.deliverables_index else None
                ),
                listen_pack_path=Path(args.listen_pack) if args.listen_pack else None,
                scene_path=Path(args.scene) if args.scene else None,
                render_plan_path=(
                    Path(args.render_plan) if getattr(args, "render_plan", None) else None
                ),
                stems_index_path=(
                    Path(args.stems_index) if getattr(args, "stems_index", None) else None
                ),
                stems_map_path=(
                    Path(args.stems_map) if getattr(args, "stems_map", None) else None
                ),
                timeline_path=None,
                gui_state_path=Path(args.gui_state) if args.gui_state else None,
                ui_locale=args.ui_locale,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "deliverables":
        if args.deliverables_command != "index":
            print("Unknown deliverables command.", file=sys.stderr)
            return 2
        return _run_deliverables_index_command(
            repo_root=repo_root,
            out_dir=Path(args.out_dir),
            out_path=Path(args.out),
            variant_result_path=(
                Path(args.variant_result) if args.variant_result else None
            ),
        )
    if args.command == "variants":
        if args.variants_command == "listen-pack":
            return _run_variants_listen_pack_command(
                repo_root=repo_root,
                presets_dir=presets_dir,
                variant_result_path=Path(args.variant_result),
                out_path=Path(args.out),
            )
        if args.variants_command != "run":
            print("Unknown variants command.", file=sys.stderr)
            return 2

        return _run_variants_workflow(
            repo_root=repo_root,
            presets_dir=presets_dir,
            stems_dir=Path(args.stems),
            out_dir=Path(args.out),
            preset_values=list(args.preset) if isinstance(args.preset, list) else None,
            config_values=list(args.config) if isinstance(args.config, list) else None,
            apply=args.apply,
            render=args.render,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            bundle=args.bundle,
            scene=args.scene,
            render_plan=getattr(args, "render_plan", False),
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            routing=args.routing,
            source_layout=args.source_layout,
            target_layout=args.target_layout,
            downmix_qa=args.downmix_qa,
            qa_ref=args.qa_ref,
            qa_meters=args.qa_meters,
            qa_max_seconds=args.qa_max_seconds,
            policy_id=args.policy_id,
            truncate_values=args.truncate_values,
            output_formats=args.output_formats,
            render_output_formats=args.render_output_formats,
            apply_output_formats=args.apply_output_formats,
            format_set_values=list(args.format_set) if isinstance(args.format_set, list) else None,
            listen_pack=args.listen_pack,
            deliverables_index=args.deliverables_index,
            timeline_path=Path(args.timeline) if args.timeline else None,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
    if args.command == "plugins":
        if args.plugins_command == "list":
            try:
                payload = _build_plugins_list_payload(plugins_dir=Path(args.plugins))
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps({"plugins": payload}, indent=2, sort_keys=True))
            else:
                print(_render_plugins_list_text(payload))
            return 0

        print("Unknown plugins command.", file=sys.stderr)
        return 2
    if args.command == "presets":
        if args.presets_command == "list":
            try:
                presets = list_presets(
                    presets_dir,
                    tag=args.tag,
                    category=args.category,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(presets, indent=2, sort_keys=True))
            else:
                for item in presets:
                    preset_id = item.get("preset_id", "")
                    label = item.get("label", "")
                    category = item.get("category")
                    category_suffix = f" [{category}]" if isinstance(category, str) else ""
                    print(f"{preset_id}  {label}{category_suffix}")
            return 0
        if args.presets_command == "show":
            try:
                payload = _build_preset_show_payload(
                    presets_dir=presets_dir,
                    preset_id=args.preset_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"{payload.get('preset_id', '')}  {payload.get('label', '')}")
                print(payload.get("description", ""))
                run_config = payload.get("run_config")
                if isinstance(run_config, dict):
                    print(json.dumps(run_config, indent=2, sort_keys=True))
            return 0
        if args.presets_command == "preview":
            cli_overrides = _build_preset_preview_cli_overrides(
                args=args,
                raw_argv=raw_argv,
            )
            try:
                payload = _build_preset_preview_payload(
                    repo_root=repo_root,
                    presets_dir=presets_dir,
                    preset_id=args.preset_id,
                    config_path=args.config,
                    cli_overrides=cli_overrides,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_preset_preview_text(payload))
            return 0
        if args.presets_command == "recommend":
            try:
                payload = _build_preset_recommendations_payload(
                    report_path=Path(args.report),
                    presets_dir=presets_dir,
                    n=args.n,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                label_map = _build_preset_label_map(presets_dir=presets_dir)
                for idx, item in enumerate(payload):
                    if idx > 0:
                        print("")
                    preset_id = item.get("preset_id", "")
                    label = label_map.get(preset_id, "")
                    overlay = item.get("overlay")
                    overlay_suffix = (
                        f" ({overlay})"
                        if isinstance(overlay, str) and overlay.strip()
                        else ""
                    )
                    print(f"{preset_id}  {label}{overlay_suffix}")
                    reasons = item.get("reasons", [])
                    if isinstance(reasons, list):
                        for reason in reasons:
                            if isinstance(reason, str):
                                print(f"  - {reason}")
            return 0
        if args.presets_command == "packs":
            if args.presets_packs_command == "list":
                try:
                    payload = _build_preset_pack_list_payload(
                        presets_dir=presets_dir,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for idx, item in enumerate(payload):
                        if idx > 0:
                            print("")
                        print(f"{item.get('pack_id', '')}  {item.get('label', '')}")
                        for preset in item.get("presets", []):
                            if not isinstance(preset, dict):
                                continue
                            print(
                                f"{preset.get('preset_id', '')}"
                                f"  {preset.get('label', '')}"
                            )
                return 0
            if args.presets_packs_command == "show":
                try:
                    payload = _build_preset_pack_payload(
                        presets_dir=presets_dir,
                        pack_id=args.pack_id,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(f"{payload.get('pack_id', '')}  {payload.get('label', '')}")
                    print(payload.get("description", ""))
                    for preset in payload.get("presets", []):
                        if not isinstance(preset, dict):
                            continue
                        print(
                            f"{preset.get('preset_id', '')}"
                            f"  {preset.get('label', '')}"
                        )
                return 0
            print("Unknown presets packs command.", file=sys.stderr)
            return 2
        print("Unknown presets command.", file=sys.stderr)
        return 2
    if args.command == "help":
        help_registry_path = repo_root / "ontology" / "help.yaml"
        if args.help_command == "list":
            try:
                payload = _build_help_list_payload(
                    help_registry_path=help_registry_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(f"{item.get('help_id', '')}  {item.get('title', '')}")
            return 0
        if args.help_command == "show":
            try:
                payload = _build_help_show_payload(
                    help_registry_path=help_registry_path,
                    help_id=args.help_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload.get("title", ""))
                print(payload.get("short", ""))
                long_text = payload.get("long")
                if isinstance(long_text, str) and long_text:
                    print("")
                    print(long_text)

                cues = payload.get("cues")
                if isinstance(cues, list) and cues:
                    print("")
                    print("Cues:")
                    for cue in cues:
                        if isinstance(cue, str):
                            print(f"- {cue}")

                watch_out_for = payload.get("watch_out_for")
                if isinstance(watch_out_for, list) and watch_out_for:
                    print("")
                    print("Watch out for:")
                    for item in watch_out_for:
                        if isinstance(item, str):
                            print(f"- {item}")
            return 0
        print("Unknown help command.", file=sys.stderr)
        return 2
    if args.command == "targets":
        render_targets_path = repo_root / "ontology" / "render_targets.yaml"
        if args.targets_command == "list":
            try:
                payload = _build_render_target_list_payload(
                    render_targets_path=render_targets_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                if not args.long:
                    for item in payload:
                        print(
                            f"{item.get('target_id', '')}"
                            f"  {item.get('label', '')}"
                            f"  {item.get('layout_id', '')}"
                        )
                else:
                    for index, item in enumerate(payload):
                        if index > 0:
                            print("")
                        print(
                            f"{item.get('target_id', '')}"
                            f"  {item.get('label', '')}"
                            f"  {item.get('layout_id', '')}"
                        )
                        aliases = item.get("aliases")
                        normalized_aliases = (
                            [
                                alias
                                for alias in aliases
                                if isinstance(alias, str) and alias.strip()
                            ]
                            if isinstance(aliases, list)
                            else []
                        )
                        if normalized_aliases:
                            print(f"aliases: {', '.join(normalized_aliases)}")
                        notes = item.get("notes")
                        normalized_notes = (
                            [note for note in notes if isinstance(note, str) and note.strip()]
                            if isinstance(notes, list)
                            else []
                        )
                        if normalized_notes:
                            print("notes:")
                            for note in normalized_notes:
                                print(f"- {note}")
            return 0
        if args.targets_command == "show":
            try:
                payload = _build_render_target_show_payload(
                    render_targets_path=render_targets_path,
                    target_id=args.target_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_target_text(payload))
            return 0
        if args.targets_command == "recommend":
            try:
                payload = _build_render_target_recommendations_payload(
                    repo_root=repo_root,
                    render_targets_path=render_targets_path,
                    report_input=args.report,
                    scene_input=args.scene,
                    max_results=args.max_results,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_target_recommendations_text(payload))
            return 0
        print("Unknown targets command.", file=sys.stderr)
        return 2
    if args.command == "roles":
        roles_path = repo_root / "ontology" / "roles.yaml"
        if args.roles_command == "list":
            try:
                payload = _build_role_list_payload(roles_path=roles_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for role_id in payload:
                    print(role_id)
            return 0
        if args.roles_command == "show":
            try:
                payload = _build_role_show_payload(
                    roles_path=roles_path,
                    role_id=args.role_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_role_text(payload))
            return 0
        print("Unknown roles command.", file=sys.stderr)
        return 2
    if args.command == "translation":
        translation_profiles_path = repo_root / "ontology" / "translation_profiles.yaml"
        if args.translation_command == "list":
            try:
                payload = _build_translation_profile_list_payload(
                    translation_profiles_path=translation_profiles_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item.get('profile_id', '')}"
                        f"  {item.get('label', '')}"
                        f"  {item.get('intent', '')}"
                    )
            return 0
        if args.translation_command == "show":
            try:
                payload = _build_translation_profile_show_payload(
                    translation_profiles_path=translation_profiles_path,
                    profile_id=args.profile_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_profile_text(payload))
            return 0
        if args.translation_command == "run":
            report_in_raw = args.report_in if isinstance(args.report_in, str) else ""
            report_out_raw = args.report_out if isinstance(args.report_out, str) else ""
            report_in_value = report_in_raw.strip()
            report_out_value = report_out_raw.strip()
            if bool(report_in_value) != bool(report_out_value):
                print(
                    "translation run requires both --report-in and --report-out when patching a report.",
                    file=sys.stderr,
                )
                return 1
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                payload = _build_translation_run_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_path=Path(args.audio),
                    profile_ids=profile_ids,
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                    use_cache=not bool(getattr(args, "no_cache", False)),
                )
                profiles = load_translation_profiles(translation_profiles_path)
                if isinstance(args.out, str) and args.out.strip():
                    _write_translation_results_json(Path(args.out), payload)
                if report_in_value and report_out_value:
                    _write_report_with_translation_results(
                        report_in_path=Path(report_in_value),
                        report_out_path=Path(report_out_value),
                        translation_results=payload,
                        repo_root=repo_root,
                        profiles=profiles,
                    )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_results_text(payload))
            return 0
        if args.translation_command == "compare":
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                audio_paths = _resolve_translation_compare_audio_paths(
                    raw_audio=getattr(args, "audio", None),
                    in_dir_value=getattr(args, "in_dir", None),
                    glob_pattern=getattr(args, "glob", None),
                )
                payload = _build_translation_compare_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_paths=audio_paths,
                    profile_ids=profile_ids,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_translation_compare_text(payload))
            return 0
        if args.translation_command == "audition":
            try:
                profile_ids = _parse_translation_profile_ids_csv(
                    args.profiles,
                    translation_profiles_path=translation_profiles_path,
                )
                out_root_dir = Path(args.out_dir)
                audition_out_dir = out_root_dir / "translation_auditions"
                payload = _build_translation_audition_payload(
                    translation_profiles_path=translation_profiles_path,
                    audio_path=Path(args.audio),
                    out_dir=audition_out_dir,
                    profile_ids=profile_ids,
                    segment_s=args.segment,
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                    use_cache=not bool(getattr(args, "no_cache", False)),
                )
                _write_translation_audition_manifest(
                    audition_out_dir / "manifest.json",
                    payload,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(
                _render_translation_audition_text(
                    payload=payload,
                    root_out_dir=out_root_dir,
                    audition_out_dir=audition_out_dir,
                )
            )
            return 0
        print("Unknown translation command.", file=sys.stderr)
        return 2
    if args.command == "locks":
        scene_locks_path = repo_root / "ontology" / "scene_locks.yaml"
        if args.locks_command == "list":
            try:
                payload = _build_scene_lock_list_payload(
                    scene_locks_path=scene_locks_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    print(
                        f"{item.get('lock_id', '')}"
                        f"  {item.get('label', '')}"
                        f"  {item.get('severity', '')}"
                    )
            return 0
        if args.locks_command == "show":
            try:
                payload = _build_scene_lock_show_payload(
                    scene_locks_path=scene_locks_path,
                    lock_id=args.lock_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(_render_scene_lock_text(payload))
            return 0
        print("Unknown locks command.", file=sys.stderr)
        return 2
    if args.command == "ui-copy":
        ui_copy_registry_path = repo_root / "ontology" / "ui_copy.yaml"
        if args.ui_copy_command == "list":
            try:
                payload = _build_ui_copy_list_payload(
                    ui_copy_registry_path=ui_copy_registry_path,
                    locale=args.locale,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"locale: {payload.get('locale', '')}")
                for item in payload.get("entries", []):
                    if not isinstance(item, dict):
                        continue
                    print(f"{item.get('copy_id', '')}  {item.get('text', '')}")
            return 0
        if args.ui_copy_command == "show":
            try:
                payload = _build_ui_copy_show_payload(
                    ui_copy_registry_path=ui_copy_registry_path,
                    locale=args.locale,
                    copy_id=args.copy_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload.get("copy_id", ""))
                print(payload.get("text", ""))
                tooltip = payload.get("tooltip")
                if isinstance(tooltip, str) and tooltip:
                    print("")
                    print(f"Tooltip: {tooltip}")
                long_text = payload.get("long")
                if isinstance(long_text, str) and long_text:
                    print("")
                    print(long_text)
                kind = payload.get("kind")
                if isinstance(kind, str) and kind:
                    print("")
                    print(f"Kind: {kind}")
                locale_value = payload.get("locale")
                if isinstance(locale_value, str) and locale_value:
                    print("")
                    print(f"Locale: {locale_value}")
            return 0
        print("Unknown ui-copy command.", file=sys.stderr)
        return 2
    if args.command == "ui-examples":
        ui_examples_dir = repo_root / "examples" / "ui_screens"
        if args.ui_examples_command == "list":
            try:
                payload = _build_ui_examples_list_payload(
                    ui_examples_dir=ui_examples_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    print(
                        f"{item.get('filename', '')}"
                        f"  {item.get('screen_id', '')}"
                        f"  {item.get('mode', '')}"
                        f"  {item.get('title', '')}"
                    )
            return 0
        if args.ui_examples_command == "show":
            try:
                payload = _build_ui_examples_show_payload(
                    ui_examples_dir=ui_examples_dir,
                    filename=args.filename,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"screen_id: {payload.get('screen_id', '')}")
                print(f"mode: {payload.get('mode', '')}")
                print(f"title: {payload.get('title', '')}")
                print(f"description: {payload.get('description', '')}")
            return 0
        print("Unknown ui-examples command.", file=sys.stderr)
        return 2
    if args.command == "lock":
        from mmo.core.lockfile import build_lockfile, verify_lockfile  # noqa: WPS433

        schema_path = repo_root / "schemas" / "lockfile.schema.json"
        stems_dir = Path(args.stems_dir)

        if args.lock_command == "write":
            exclude_rel_paths: set[str] = set()
            out_rel_path = _rel_path_if_under_root(stems_dir, Path(args.out))
            if out_rel_path:
                exclude_rel_paths.add(out_rel_path)
            try:
                lock_payload = build_lockfile(
                    stems_dir,
                    exclude_rel_paths=exclude_rel_paths,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            try:
                _validate_json_payload(
                    lock_payload,
                    schema_path=schema_path,
                    payload_name="Lockfile",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(Path(args.out), lock_payload)
            return 0

        if args.lock_command == "verify":
            exclude_rel_paths: set[str] = set()
            lock_rel_path = _rel_path_if_under_root(stems_dir, Path(args.lock))
            if lock_rel_path:
                exclude_rel_paths.add(lock_rel_path)
            if args.out:
                out_rel_path = _rel_path_if_under_root(stems_dir, Path(args.out))
                if out_rel_path:
                    exclude_rel_paths.add(out_rel_path)
            try:
                lock_payload = _load_json_object(Path(args.lock), label="Lockfile")
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            try:
                _validate_json_payload(
                    lock_payload,
                    schema_path=schema_path,
                    payload_name="Lockfile",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            try:
                verify_result = verify_lockfile(
                    stems_dir,
                    lock_payload,
                    exclude_rel_paths=exclude_rel_paths,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            _print_lock_verify_summary(verify_result)
            if args.out:
                _write_json_file(Path(args.out), verify_result)
            return 0 if verify_result.get("ok") else 1

        print("Unknown lock command.", file=sys.stderr)
        return 2
    if args.command == "scene":
        if args.scene_command == "build":
            try:
                template_ids: list[str] = []
                if isinstance(args.templates, str) and args.templates.strip():
                    template_ids = _parse_scene_template_ids_csv(args.templates)
                return _run_scene_build_command(
                    repo_root=repo_root,
                    report_path=Path(args.report),
                    out_path=Path(args.out),
                    timeline_path=Path(args.timeline) if args.timeline else None,
                    template_ids=template_ids,
                    force_templates=bool(args.force_templates),
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "locks":
            try:
                return _run_scene_locks_edit_command(
                    repo_root=repo_root,
                    scene_path=Path(args.scene),
                    out_path=Path(args.out),
                    operation=args.scene_locks_command,
                    scope=args.scope,
                    target_id=args.id,
                    lock_id=args.lock,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.scene_command == "intent":
            if args.scene_intent_command == "set":
                try:
                    return _run_scene_intent_set_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        out_path=Path(args.out),
                        scope=args.scope,
                        target_id=args.id,
                        key=args.key,
                        value=args.value,
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            if args.scene_intent_command == "show":
                try:
                    scene_payload = _load_json_object(Path(args.scene), label="Scene")
                    _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1

                payload = _build_scene_intent_show_payload(scene_payload)
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(_render_scene_intent_text(payload))
                return 0
            print("Unknown scene intent command.", file=sys.stderr)
            return 2

        if args.scene_command == "template":
            scene_templates_path = repo_root / "ontology" / "scene_templates.yaml"
            if args.scene_template_command == "list":
                try:
                    payload = _build_scene_template_list_payload(
                        scene_templates_path=scene_templates_path,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for item in payload:
                        print(
                            f"{item.get('template_id', '')}"
                            f"  {item.get('label', '')}"
                        )
                return 0
            if args.scene_template_command == "show":
                try:
                    payload = _build_scene_template_show_payload(
                        scene_templates_path=scene_templates_path,
                        template_ids=args.template_ids,
                    )
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if args.format == "json":
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    for index, item in enumerate(payload):
                        if index > 0:
                            print("")
                        print(_render_scene_template_text(item))
                return 0
            if args.scene_template_command == "apply":
                try:
                    return _run_scene_template_apply_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        out_path=Path(args.out),
                        template_ids=args.template_ids,
                        force=bool(args.force),
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            if args.scene_template_command == "preview":
                try:
                    return _run_scene_template_preview_command(
                        repo_root=repo_root,
                        scene_path=Path(args.scene),
                        template_ids=args.template_ids,
                        force=bool(args.force),
                        output_format=args.format,
                    )
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                except SystemExit as exc:
                    return int(exc.code) if isinstance(exc.code, int) else 1
            print("Unknown scene template command.", file=sys.stderr)
            return 2

        if args.scene_command in {"validate", "show"}:
            try:
                scene_payload = _load_json_object(Path(args.scene), label="Scene")
                _validate_scene_schema(repo_root=repo_root, scene_payload=scene_payload)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

            if args.scene_command == "validate":
                print("Scene is valid.")
                return 0
            if args.format == "json":
                print(json.dumps(scene_payload, indent=2, sort_keys=True))
            else:
                print(_render_scene_text(scene_payload))
            return 0

        print("Unknown scene command.", file=sys.stderr)
        return 2
    if args.command == "render-plan":
        if args.render_plan_command == "build":
            try:
                target_ids = _parse_target_ids_csv(
                    args.targets,
                    render_targets_path=repo_root / "ontology" / "render_targets.yaml",
                )
                output_formats = _parse_output_formats_csv(args.output_formats)
                contexts = (
                    list(args.context)
                    if isinstance(args.context, list) and args.context
                    else ["render"]
                )
                return _run_render_plan_build_command(
                    repo_root=repo_root,
                    scene_path=Path(args.scene),
                    target_ids=target_ids,
                    out_path=Path(args.out),
                    routing_plan_path=(
                        Path(args.routing_plan) if args.routing_plan else None
                    ),
                    output_formats=output_formats,
                    contexts=contexts,
                    policy_id=args.policy_id,
                )
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command == "to-variants":
            try:
                return _run_render_plan_to_variants_command(
                    repo_root=repo_root,
                    presets_dir=presets_dir,
                    render_plan_path=Path(args.render_plan),
                    scene_path=Path(args.scene),
                    out_path=Path(args.out),
                    out_dir=Path(args.out_dir),
                    run=args.run,
                    listen_pack=args.listen_pack,
                    deliverables_index=args.deliverables_index,
                    cache_enabled=args.cache == "on",
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command not in {"validate", "show"}:
            print("Unknown render-plan command.", file=sys.stderr)
            return 2

        try:
            render_plan_payload = _load_json_object(
                Path(args.render_plan),
                label="Render plan",
            )
            _validate_json_payload(
                render_plan_payload,
                schema_path=repo_root / "schemas" / "render_plan.schema.json",
                payload_name="Render plan",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

        if args.render_plan_command == "validate":
            print("Render plan is valid.")
            return 0
        if args.format == "json":
            print(json.dumps(render_plan_payload, indent=2, sort_keys=True))
        else:
            print(_render_render_plan_text(render_plan_payload))
        return 0
    if args.command == "timeline":
        if args.timeline_command not in {"validate", "show"}:
            print("Unknown timeline command.", file=sys.stderr)
            return 2
        try:
            timeline_payload = load_timeline(Path(args.timeline))
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.timeline_command == "validate":
            print("Timeline is valid.")
            return 0

        if args.format == "json":
            print(json.dumps(timeline_payload, indent=2, sort_keys=True))
        else:
            print(_render_timeline_text(timeline_payload))
        return 0
    if args.command == "gui-state":
        if args.gui_state_command == "validate":
            try:
                validate_gui_state(Path(args.in_path))
            except (RuntimeError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print("GUI state is valid.")
            return 0
        if args.gui_state_command == "default":
            _write_json_file(Path(args.out), default_gui_state())
            return 0
        print("Unknown gui-state command.", file=sys.stderr)
        return 2
    if args.command == "routing":
        from mmo.core.session import build_session_from_stems_dir  # noqa: WPS433

        if args.routing_command != "show":
            print("Unknown routing command.", file=sys.stderr)
            return 2

        try:
            session = build_session_from_stems_dir(Path(args.stems))
            routing_plan = build_routing_plan(
                session,
                source_layout_id=args.source_layout,
                target_layout_id=args.target_layout,
            )
            _validate_json_payload(
                routing_plan,
                schema_path=repo_root / "schemas" / "routing_plan.schema.json",
                payload_name="Routing plan",
            )
            output = render_routing_plan(routing_plan, output_format=args.format)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

        print(output, end="")
        return 0
    if args.command == "downmix":
        from mmo.dsp.downmix import (  # noqa: WPS433
            load_layouts,
            render_matrix,
            resolve_downmix_matrix,
        )
        from mmo.core.downmix_qa import run_downmix_qa  # noqa: WPS433
        from mmo.core.downmix_inventory import build_downmix_list_payload  # noqa: WPS433
        from mmo.exporters.downmix_qa_csv import (  # noqa: WPS433
            export_downmix_qa_csv,
            render_downmix_qa_csv,
        )
        from mmo.exporters.downmix_qa_pdf import export_downmix_qa_pdf  # noqa: WPS433

        if args.downmix_command == "qa":
            downmix_qa_overrides: dict[str, Any] = {}
            if _flag_present(raw_argv, "--profile"):
                downmix_qa_overrides["profile_id"] = args.profile
            if _flag_present(raw_argv, "--meters"):
                downmix_qa_overrides["meters"] = args.meters
            if _flag_present(raw_argv, "--max-seconds"):
                downmix_qa_overrides["max_seconds"] = args.max_seconds
            if _flag_present(raw_argv, "--truncate-values"):
                downmix_qa_overrides["truncate_values"] = args.truncate_values
            if _flag_present(raw_argv, "--source-layout"):
                _set_nested(
                    ["downmix", "source_layout_id"],
                    downmix_qa_overrides,
                    args.source_layout,
                )
            if _flag_present(raw_argv, "--target-layout"):
                _set_nested(
                    ["downmix", "target_layout_id"],
                    downmix_qa_overrides,
                    args.target_layout,
                )
            if _flag_present(raw_argv, "--policy"):
                _set_nested(
                    ["downmix", "policy_id"],
                    downmix_qa_overrides,
                    args.policy,
                )
            try:
                merged_run_config = _load_and_merge_run_config(
                    args.config,
                    downmix_qa_overrides,
                    preset_id=args.preset,
                    presets_dir=presets_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            effective_profile = _config_string(merged_run_config, "profile_id", args.profile)
            effective_meters = _config_string(merged_run_config, "meters", args.meters)
            effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
            effective_max_seconds = _config_float(
                merged_run_config,
                "max_seconds",
                args.max_seconds,
            )
            effective_truncate_values = _config_int(
                merged_run_config,
                "truncate_values",
                args.truncate_values,
            )
            effective_source_layout = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "source_layout_id",
                args.source_layout,
            )
            effective_target_layout = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "target_layout_id",
                args.target_layout,
            )
            if not effective_target_layout:
                effective_target_layout = args.target_layout
            effective_policy = _config_nested_optional_string(
                merged_run_config,
                "downmix",
                "policy_id",
                args.policy,
            )

            if not effective_source_layout:
                print(
                    "Missing source layout. Provide --source-layout or set downmix.source_layout_id in --config.",
                    file=sys.stderr,
                )
                return 1
            layouts_path = repo_root / "ontology" / "layouts.yaml"
            try:
                layouts = load_layouts(layouts_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if effective_source_layout not in layouts:
                print(f"Unknown source layout: {effective_source_layout}", file=sys.stderr)
                return 1
            if effective_target_layout not in layouts:
                print(f"Unknown target layout: {effective_target_layout}", file=sys.stderr)
                return 1
            try:
                report = run_downmix_qa(
                    Path(args.src),
                    Path(args.ref),
                    source_layout_id=effective_source_layout,
                    target_layout_id=effective_target_layout,
                    policy_id=effective_policy,
                    tolerance_lufs=args.tolerance_lufs,
                    tolerance_true_peak_db=args.tolerance_true_peak,
                    tolerance_corr=args.tolerance_corr,
                    repo_root=repo_root,
                    meters=effective_meters,
                    max_seconds=effective_max_seconds,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.emit_report:
                from mmo.core.report_builders import (  # noqa: WPS433
                    build_minimal_report_for_downmix_qa,
                )

                report_payload = build_minimal_report_for_downmix_qa(
                    repo_root=repo_root,
                    qa_payload=report,
                    profile_id=effective_profile,
                    profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
                )
                report_payload["run_config"] = _downmix_qa_run_config(
                    profile_id=effective_profile,
                    meters=effective_meters,
                    max_seconds=effective_max_seconds,
                    truncate_values=effective_truncate_values,
                    source_layout_id=effective_source_layout,
                    target_layout_id=effective_target_layout,
                    policy_id=effective_policy,
                    preset_id=effective_preset_id,
                    base_run_config=merged_run_config,
                )
                apply_routing_plan_to_report(report_payload, report_payload["run_config"])
                out_path = Path(args.emit_report)
                _write_json_file(out_path, report_payload)

            if args.format == "json":
                output = json.dumps(report, indent=2, sort_keys=True) + "\n"
                if args.out:
                    out_path = Path(args.out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(output, encoding="utf-8")
                else:
                    print(output, end="")
            elif args.format == "csv":
                if args.out:
                    export_downmix_qa_csv(report, Path(args.out))
                else:
                    print(render_downmix_qa_csv(report), end="")
            elif args.format == "pdf":
                out_path = Path(args.out) if args.out else Path.cwd() / "downmix_qa.pdf"
                export_downmix_qa_pdf(
                    report,
                    out_path,
                    truncate_values=effective_truncate_values,
                )
            else:
                print(f"Unsupported format: {args.format}", file=sys.stderr)
                return 2

            issues = report.get("downmix_qa", {}).get("issues", [])
            has_error = any(
                isinstance(issue, dict) and issue.get("severity", 0) >= 80
                for issue in issues
            )
            return 1 if has_error else 0

        if args.downmix_command == "list":
            want_layouts = args.layouts
            want_policies = args.policies
            want_conversions = args.conversions
            if not (want_layouts or want_policies or want_conversions):
                want_layouts = True
                want_policies = True
                want_conversions = True

            try:
                payload = build_downmix_list_payload(
                    repo_root=repo_root,
                    include_layouts=want_layouts,
                    include_policies=want_policies,
                    include_conversions=want_conversions,
                )
            except (ValueError, RuntimeError) as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
                print(output, end="")
            else:
                lines: list[str] = []
                if want_layouts:
                    lines.append("Layouts")
                    for row in payload.get("layouts", []):
                        line = f"{row.get('id')}"
                        name = row.get("name")
                        if isinstance(name, str) and name:
                            line += f"  {name}"
                        channels = row.get("channels")
                        if isinstance(channels, int):
                            line += f"  channels={channels}"
                        speakers = row.get("speakers")
                        if isinstance(speakers, list) and speakers:
                            line += f"  speakers={','.join(str(item) for item in speakers)}"
                        lines.append(line)
                    if want_policies or want_conversions:
                        lines.append("")
                if want_policies:
                    lines.append("Policies")
                    for row in payload.get("policies", []):
                        line = f"{row.get('id')}"
                        description = row.get("description")
                        if isinstance(description, str) and description:
                            line += f"  {description}"
                        lines.append(line)
                    if want_conversions:
                        lines.append("")
                if want_conversions:
                    lines.append("Conversions")
                    for row in payload.get("conversions", []):
                        source = row.get("source_layout_id")
                        target = row.get("target_layout_id")
                        policy_ids = row.get("policy_ids_available") or []
                        policy_text = ",".join(str(item) for item in policy_ids)
                        lines.append(f"{source} -> {target}  policies={policy_text}")
                print("\n".join(lines))
            return 0

        if args.downmix_command == "render":
            downmix_render_overrides: dict[str, Any] = {}
            if _flag_present(raw_argv, "--profile"):
                downmix_render_overrides["profile_id"] = args.profile
            if _flag_present(raw_argv, "--out-dir"):
                _set_nested(["render", "out_dir"], downmix_render_overrides, args.out_dir)
            try:
                merged_run_config = _load_and_merge_run_config(
                    args.config,
                    downmix_render_overrides,
                    preset_id=args.preset,
                    presets_dir=presets_dir,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            profile_id = _config_string(merged_run_config, "profile_id", args.profile)
            out_dir = _config_nested_optional_string(
                merged_run_config,
                "render",
                "out_dir",
                args.out_dir,
            )
            try:
                return _run_downmix_render(
                    repo_root=repo_root,
                    report_path=Path(args.report),
                    plugins_dir=Path(args.plugins),
                    out_manifest_path=Path(args.out_manifest),
                    out_dir=Path(out_dir) if out_dir else None,
                    profile_id=profile_id,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

        if args.downmix_command != "show":
            print("Unknown downmix command.", file=sys.stderr)
            return 2

        layouts_path = repo_root / "ontology" / "layouts.yaml"
        registry_path = repo_root / "ontology" / "policies" / "downmix.yaml"
        try:
            matrix = resolve_downmix_matrix(
                repo_root=repo_root,
                source_layout_id=args.source,
                target_layout_id=args.target,
                policy_id=args.policy,
                layouts_path=layouts_path,
                registry_path=registry_path,
            )
            output = render_matrix(matrix, output_format=args.format)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0

    return 0
