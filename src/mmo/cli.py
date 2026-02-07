from __future__ import annotations

import argparse
import json
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
from mmo.core.listen_pack import build_listen_pack
from mmo.core.project_file import (
    load_project,
    new_project,
    update_project_last_run,
    write_project,
)
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
        project_path=project_path,
        deliverables_index_path=deliverables_index_path,
        listen_pack_path=listen_pack_path,
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
        lines.append(f"{plugin_id} (max_channels={max_channels}) contexts={contexts}")
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
    profile: str | None,
    meters: str | None,
    max_seconds: float | None,
    truncate_values: int | None,
    export_pdf: bool,
    export_csv: bool,
    apply: bool,
    render: bool,
    bundle: bool,
    deliverables_index: bool,
    output_formats: str | None,
    cache_enabled: bool,
    cache_dir: Path | None,
) -> int:
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
    deliverables_index_path = out_dir / "deliverables_index.json"
    render_out_dir = out_dir / "render"
    apply_out_dir = out_dir / "apply"

    report_schema_path = repo_root / "schemas" / "report.schema.json"
    plugins_dir = str(repo_root / "plugins")
    lock_payload: dict[str, Any] | None = None
    cache_key_value: str | None = None
    report_payload: dict[str, Any] | None = None

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
    if deliverables_index:
        summary.append(("deliverables_index", deliverables_index_path))

    print("run complete:")
    for label, path in summary:
        print(f"- {label}: {path.resolve().as_posix()}")
    return 0


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
            deliverables_index=args.deliverables_index,
            project_path=project_path,
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
        profile=args.profile,
        meters=args.meters,
        max_seconds=args.max_seconds,
        truncate_values=args.truncate_values,
        export_pdf=args.export_pdf,
        export_csv=args.export_csv,
        apply=args.apply,
        render=args.render,
        bundle=args.bundle,
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
            profile=None,
            meters=None,
            max_seconds=None,
            truncate_values=None,
            export_pdf=export_pdf,
            export_csv=export_csv,
            apply=apply,
            render=render,
            bundle=True,
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
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
    )
    run_parser.add_argument(
        "--deliverables-index",
        action="store_true",
        help="Also write deliverables_index.json summarizing file deliverables.",
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
        "--bundle",
        action="store_true",
        help="Build a UI bundle JSON.",
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
        apply_overrides: dict[str, Any] = {}
        if _flag_present(raw_argv, "--profile"):
            apply_overrides["profile_id"] = args.profile
        if _flag_present(raw_argv, "--source-layout"):
            _set_nested(
                ["downmix", "source_layout_id"],
                apply_overrides,
                args.source_layout,
            )
        if _flag_present(raw_argv, "--target-layout"):
            _set_nested(
                ["downmix", "target_layout_id"],
                apply_overrides,
                args.target_layout,
            )
        if _flag_present(raw_argv, "--out-dir"):
            _set_nested(["render", "out_dir"], apply_overrides, args.out_dir)
        if _flag_present(raw_argv, "--output-formats"):
            try:
                apply_output_formats = _parse_output_formats_csv(args.output_formats)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _set_nested(
                ["apply", "output_formats"],
                apply_overrides,
                apply_output_formats,
            )
        try:
            merged_run_config = _load_and_merge_run_config(
                args.config,
                apply_overrides,
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
