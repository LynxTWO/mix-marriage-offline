from __future__ import annotations

import importlib.util
import json
import re
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
from mmo.core.downmix_qa import run_downmix_qa
from mmo.core.gates import apply_gates_to_report
from mmo.core.lockfile import build_lockfile
from mmo.core.pipeline import (
    build_deliverables_for_renderer_manifests,
    load_plugins,
    run_detectors,
    run_renderers,
    run_resolvers,
)
from mmo.core.preset_recommendations import derive_preset_recommendations
from mmo.core.presets import list_presets, load_preset_run_config
from mmo.core.report_builders import (
    enrich_blocked_downmix_render_diagnostics,
    merge_downmix_qa_issues_into_report,
)
from mmo.core.routing import apply_routing_plan_to_report
from mmo.core.run_config import (
    RUN_CONFIG_SCHEMA_VERSION,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.ui_bundle import build_ui_bundle
from mmo.core.vibe_signals import derive_vibe_signals
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS
from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf

VARIANT_SCHEMA_VERSION = "0.1.0"
_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_DEFAULT_GENERATED_AT = "2000-01-01T00:00:00Z"
_DEFAULT_TRUNCATE_VALUES = 200
_DEFAULT_QA_METERS = "truth"
_DEFAULT_QA_MAX_SECONDS = 120.0
_VARIANT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_VARIANT_STEP_KEYS = (
    "analyze",
    "routing",
    "downmix_qa",
    "export_pdf",
    "export_csv",
    "apply",
    "render",
    "bundle",
)
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_SCAN_SESSION_BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _analysis_cache_key(lock: dict[str, Any], cfg: dict[str, Any]) -> str:
    lock_hash = hash_lockfile(lock)
    cfg_hash = hash_run_config(cfg)
    return cache_key(lock_hash, cfg_hash)


def _should_skip_analysis_cache_save(report: dict[str, Any], run_config: dict[str, Any]) -> bool:
    meters = run_config.get("meters")
    if meters != "truth":
        return False
    return report_has_time_cap_stop_condition(report)


def _normalize_steps(steps: dict[str, Any] | None) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    source = steps or {}
    for key in _VARIANT_STEP_KEYS:
        normalized[key] = source.get(key) is True if isinstance(source, dict) else False
    normalized["analyze"] = True
    return normalized


def _layout_ids_from_variant_and_run_config(
    variant: dict[str, Any],
    run_config: dict[str, Any],
) -> tuple[str | None, str | None]:
    downmix_cfg = _coerce_dict(run_config.get("downmix"))
    source_layout_id = _coerce_str(variant.get("source_layout_id")).strip()
    target_layout_id = _coerce_str(variant.get("target_layout_id")).strip()
    if not source_layout_id:
        source_layout_id = _coerce_str(downmix_cfg.get("source_layout_id")).strip()
    if not target_layout_id:
        target_layout_id = _coerce_str(downmix_cfg.get("target_layout_id")).strip()
    return (
        source_layout_id or None,
        target_layout_id or None,
    )


def _with_variant_layout_overrides(
    run_config: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_run_config(run_config)
    source_layout_id, target_layout_id = _layout_ids_from_variant_and_run_config(
        variant,
        normalized,
    )
    if source_layout_id is None and target_layout_id is None:
        return normalized

    payload = _json_clone(normalized)
    downmix_cfg = _coerce_dict(payload.get("downmix"))
    if source_layout_id is not None:
        downmix_cfg["source_layout_id"] = source_layout_id
    if target_layout_id is not None:
        downmix_cfg["target_layout_id"] = target_layout_id
    payload["downmix"] = downmix_cfg
    return normalize_run_config(payload)


def _qa_meters_for_variant(variant: dict[str, Any], run_config: dict[str, Any]) -> str:
    candidate = _coerce_str(variant.get("qa_meters")).strip().lower()
    if candidate in {"basic", "truth"}:
        return candidate
    candidate = _coerce_str(run_config.get("meters")).strip().lower()
    if candidate in {"basic", "truth"}:
        return candidate
    return _DEFAULT_QA_METERS


def _qa_max_seconds_for_variant(variant: dict[str, Any], run_config: dict[str, Any]) -> float:
    variant_value = _coerce_float(variant.get("qa_max_seconds"))
    if variant_value is not None and variant_value >= 0.0:
        return variant_value
    run_config_value = _coerce_float(run_config.get("max_seconds"))
    if run_config_value is not None and run_config_value >= 0.0:
        return run_config_value
    return _DEFAULT_QA_MAX_SECONDS


def _qa_ref_path_for_variant(variant: dict[str, Any]) -> Path | None:
    qa_ref_raw = _coerce_str(variant.get("qa_ref_path")).strip()
    if not qa_ref_raw:
        return None
    return Path(qa_ref_raw)


def _source_path_for_downmix_qa(report: dict[str, Any], stems_dir: Path) -> Path | None:
    session = _coerce_dict(report.get("session"))
    stems = session.get("stems")
    if not isinstance(stems, list):
        return None

    rows: list[tuple[str, str, int]] = []
    for index, stem in enumerate(stems):
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id")).strip() or f"stem_{index:04d}"
        file_path = _coerce_str(stem.get("file_path")).strip()
        if not file_path:
            continue
        rows.append((stem_id, file_path, index))

    if not rows:
        return None
    rows.sort(key=lambda row: (row[0], row[1], row[2]))

    first_candidate: Path | None = None
    for _, file_path, _ in rows:
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = stems_dir / candidate
        if first_candidate is None:
            first_candidate = candidate
        if candidate.exists():
            return candidate
    return first_candidate


def _run_variant_downmix_qa(
    *,
    report: dict[str, Any],
    variant: dict[str, Any],
    stems_dir: Path,
    run_config: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    qa_ref_path = _qa_ref_path_for_variant(variant)
    if qa_ref_path is None:
        raise ValueError("qa_ref_path is required when steps.downmix_qa is true.")

    source_layout_id, target_layout_id = _layout_ids_from_variant_and_run_config(
        variant,
        run_config,
    )
    if not source_layout_id:
        raise ValueError("source_layout_id is required when steps.downmix_qa is true.")
    if not target_layout_id:
        target_layout_id = "LAYOUT.2_0"

    src_path = _source_path_for_downmix_qa(report, stems_dir)
    if src_path is None:
        raise ValueError("No session stem file_path available for downmix QA source.")

    downmix_cfg = _coerce_dict(run_config.get("downmix"))
    policy_id = _coerce_str(downmix_cfg.get("policy_id")).strip() or None
    qa_meters = _qa_meters_for_variant(variant, run_config)
    qa_max_seconds = _qa_max_seconds_for_variant(variant, run_config)

    return run_downmix_qa(
        src_path,
        qa_ref_path,
        source_layout_id=source_layout_id,
        target_layout_id=target_layout_id,
        policy_id=policy_id,
        repo_root=repo_root,
        meters=qa_meters,
        max_seconds=qa_max_seconds,
    )


def _apply_variant_routing_step(
    *,
    report: dict[str, Any],
    variant: dict[str, Any],
    run_config: dict[str, Any],
    enabled: bool,
) -> None:
    if not enabled:
        report.pop("routing_plan", None)
        return

    source_layout_id, target_layout_id = _layout_ids_from_variant_and_run_config(
        variant,
        run_config,
    )
    if not source_layout_id or not target_layout_id:
        raise ValueError(
            "source_layout_id and target_layout_id are required when steps.routing is true."
        )

    routing_run_config = _json_clone(run_config)
    downmix_cfg = _coerce_dict(routing_run_config.get("downmix"))
    downmix_cfg["source_layout_id"] = source_layout_id
    downmix_cfg["target_layout_id"] = target_layout_id
    routing_run_config["downmix"] = downmix_cfg
    apply_routing_plan_to_report(report, normalize_run_config(routing_run_config))


def _refresh_report_after_downmix_qa(
    *,
    report: dict[str, Any],
    repo_root: Path,
    profile_id: str,
) -> None:
    apply_gates_to_report(
        report,
        policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
    )
    enrich_blocked_downmix_render_diagnostics(report)
    if isinstance(report.get("mix_complexity"), dict):
        report["vibe_signals"] = derive_vibe_signals(report)
        report["preset_recommendations"] = derive_preset_recommendations(
            report,
            repo_root / "presets",
        )


def _normalize_run_config_patch(patch: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return {}
    payload = dict(patch)
    normalized = normalize_run_config(
        {
            **payload,
            "schema_version": payload.get("schema_version", RUN_CONFIG_SCHEMA_VERSION),
        }
    )
    normalized.pop("schema_version", None)
    return normalized


def _default_base_run_config() -> dict[str, Any]:
    return normalize_run_config(
        {
            "schema_version": RUN_CONFIG_SCHEMA_VERSION,
            "profile_id": _DEFAULT_PROFILE_ID,
        }
    )


def _normalize_preset_ids(preset_ids: list[str] | None) -> list[str]:
    if not isinstance(preset_ids, list):
        return []
    normalized: list[str] = []
    for raw in preset_ids:
        value = _coerce_str(raw).strip()
        if value:
            normalized.append(value)
    return normalized


def _normalize_config_paths(config_paths: list[Path] | None) -> list[Path]:
    if not isinstance(config_paths, list):
        return []
    normalized: list[Path] = []
    for raw in config_paths:
        if isinstance(raw, Path):
            normalized.append(raw.resolve())
            continue
        value = _coerce_str(raw).strip()
        if value:
            normalized.append(Path(value).resolve())
    return normalized


def _prefixless_preset_id(preset_id: str) -> str:
    if preset_id.startswith("PRESET."):
        return preset_id[len("PRESET.") :]
    return preset_id


def _sanitize_slug(value: str) -> str:
    lowered = value.strip().lower()
    lowered = _VARIANT_SLUG_RE.sub("_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered or "variant"


def _suffix_from_index(index: int) -> str:
    if index < 0:
        raise ValueError("index must be >= 0")
    chars: list[str] = []
    current = index
    while True:
        chars.append(chr(ord("a") + (current % 26)))
        current = (current // 26) - 1
        if current < 0:
            break
    return "".join(reversed(chars))


def _preset_overlay_map(presets_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in list_presets(presets_dir):
        if not isinstance(item, dict):
            continue
        preset_id = item.get("preset_id")
        if not isinstance(preset_id, str) or not preset_id:
            continue
        overlay = item.get("overlay")
        if isinstance(overlay, str) and overlay.strip():
            mapping[preset_id] = overlay.strip()
    return mapping


def _slug_seed(
    *,
    preset_id: str | None,
    config_path: Path | None,
    overlay_map: dict[str, str],
) -> str:
    if isinstance(preset_id, str) and preset_id:
        overlay = overlay_map.get(preset_id)
        if isinstance(overlay, str) and overlay.strip():
            return _sanitize_slug(overlay)
        return _sanitize_slug(_prefixless_preset_id(preset_id))
    if isinstance(config_path, Path):
        return _sanitize_slug(config_path.stem)
    return "default"


def _variant_label(*, preset_id: str | None, config_path: Path | None) -> str:
    if isinstance(preset_id, str) and preset_id and isinstance(config_path, Path):
        return f"{preset_id} + {config_path.name}"
    if isinstance(preset_id, str) and preset_id:
        return preset_id
    if isinstance(config_path, Path):
        return config_path.name
    return "default"


def _with_variant_out_dir(
    cli_patch: dict[str, Any],
    *,
    variant_out_dir: Path,
) -> dict[str, Any]:
    merged = _json_clone(cli_patch)
    render_cfg = merged.get("render")
    if not isinstance(render_cfg, dict):
        render_cfg = {}
        merged["render"] = render_cfg
    render_cfg["out_dir"] = _path_to_posix(variant_out_dir)
    return _normalize_run_config_patch(merged)


def _load_scan_builder(repo_root: Path) -> Callable[..., dict[str, Any]]:
    module_path = (repo_root / "tools" / "scan_session.py").resolve()
    cache_key = module_path.as_posix()
    cached = _SCAN_SESSION_BUILDERS.get(cache_key)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location("mmo_tools_scan_session", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Failed to load scan_session module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build_report = getattr(module, "build_report", None)
    if not callable(build_report):
        raise ValueError(f"scan_session module missing build_report(): {module_path}")
    _SCAN_SESSION_BUILDERS[cache_key] = build_report
    return build_report


def _profile_id_from_config(run_config: dict[str, Any]) -> str:
    value = run_config.get("profile_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _DEFAULT_PROFILE_ID


def _meters_from_config(run_config: dict[str, Any]) -> str | None:
    value = run_config.get("meters")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _truncate_values_from_config(run_config: dict[str, Any]) -> int:
    value = run_config.get("truncate_values")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _DEFAULT_TRUNCATE_VALUES


def _normalize_output_formats(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    selected: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if normalized in _OUTPUT_FORMAT_ORDER:
            selected.add(normalized)
    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _output_formats_from_config(run_config: dict[str, Any], section: str) -> list[str]:
    section_config = _coerce_dict(run_config.get(section))
    selected = _normalize_output_formats(section_config.get("output_formats"))
    if selected:
        return selected
    return ["wav"]


def _output_formats_from_steps(steps: dict[str, Any], key: str) -> list[str]:
    return _normalize_output_formats(steps.get(key))


def _effective_output_formats(
    *,
    steps: dict[str, Any],
    run_config: dict[str, Any],
    step_key: str,
    section: str,
) -> list[str]:
    selected = _output_formats_from_steps(steps, step_key)
    if selected:
        return selected
    return _output_formats_from_config(run_config, section)


def _analysis_run_config(run_config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_run_config(run_config)
    analysis_cfg = _json_clone(normalized)

    render_cfg = _coerce_dict(analysis_cfg.get("render"))
    render_cfg.pop("out_dir", None)
    render_cfg.pop("output_formats", None)
    if render_cfg:
        analysis_cfg["render"] = render_cfg
    else:
        analysis_cfg.pop("render", None)

    apply_cfg = _coerce_dict(analysis_cfg.get("apply"))
    apply_cfg.pop("output_formats", None)
    if apply_cfg:
        analysis_cfg["apply"] = apply_cfg
    else:
        analysis_cfg.pop("apply", None)

    return normalize_run_config(analysis_cfg)


def _normalize_format_sets(
    format_sets: list[tuple[str, list[str]]] | None,
) -> list[tuple[str, list[str]]]:
    if not isinstance(format_sets, list):
        return []
    normalized: list[tuple[str, list[str]]] = []
    for item in format_sets:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        name = _sanitize_slug(_coerce_str(item[0]))
        output_formats = _normalize_output_formats(item[1])
        if not name or not output_formats:
            continue
        normalized.append((name, output_formats))
    return normalized


def _label_with_format_set(label: str, format_set_name: str | None) -> str:
    if not isinstance(format_set_name, str) or not format_set_name:
        return label
    return f"{label} [{format_set_name}]"


def _slug_with_format_set(slug_seed: str, format_set_name: str | None) -> str:
    if not isinstance(format_set_name, str) or not format_set_name:
        return slug_seed
    return f"{slug_seed}__{format_set_name}"


def _step_formats_for_format_set(
    *,
    output_formats: list[str] | None,
    normalized_steps: dict[str, bool],
) -> tuple[list[str], list[str]]:
    if not output_formats:
        return ([], [])
    render_formats = list(output_formats) if normalized_steps.get("render") else []
    apply_formats = list(output_formats) if normalized_steps.get("apply") else []
    return (render_formats, apply_formats)


def _variant_steps_payload(
    *,
    normalized_steps: dict[str, bool],
    render_output_formats: list[str],
    apply_output_formats: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(normalized_steps)
    if render_output_formats:
        payload["render_output_formats"] = render_output_formats
    if apply_output_formats:
        payload["apply_output_formats"] = apply_output_formats
    return payload


def _variant_out_dir_from_overrides(variant: dict[str, Any]) -> Path:
    overrides = _coerce_dict(variant.get("run_config_overrides"))
    render_cfg = _coerce_dict(overrides.get("render"))
    out_dir = _coerce_str(render_cfg.get("out_dir")).strip()
    if not out_dir:
        raise ValueError("Variant run_config_overrides.render.out_dir is required.")
    return Path(out_dir)


def _merge_effective_run_config(
    *,
    base_run_config: dict[str, Any],
    variant: dict[str, Any],
    presets_dir: Path,
) -> dict[str, Any]:
    merged = normalize_run_config(base_run_config)

    preset_id = _coerce_str(variant.get("preset_id")).strip()
    if preset_id:
        merged = merge_run_config(merged, load_preset_run_config(presets_dir, preset_id))

    config_path = _coerce_str(variant.get("config_path")).strip()
    if config_path:
        merged = merge_run_config(merged, load_run_config(Path(config_path)))

    overrides = _coerce_dict(variant.get("run_config_overrides"))
    if overrides:
        merged = merge_run_config(merged, overrides)
    return normalize_run_config(merged)


def _collect_stem_artifacts(
    renderer_manifests: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    selected: dict[str, tuple[tuple[str, str, str, str], dict[str, str]]] = {}
    for manifest in renderer_manifests:
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
    applied_report = _json_clone(report)
    session = applied_report.get("session")
    if not isinstance(session, dict):
        session = {}
        applied_report["session"] = session
    session["stems_dir"] = _path_to_posix(out_dir)

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


def build_variant_plan(
    *,
    stems_dir: Path,
    out_dir: Path,
    preset_ids: list[str] | None = None,
    config_paths: list[Path] | None = None,
    cli_run_config_overrides: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
    format_sets: list[tuple[str, list[str]]] | None = None,
    presets_dir: Path,
    source_layout_id: str | None = None,
    target_layout_id: str | None = None,
    qa_ref_path: Path | None = None,
    qa_meters: str | None = None,
    qa_max_seconds: float | None = None,
) -> dict[str, Any]:
    resolved_stems_dir = stems_dir.resolve()
    resolved_out_dir = out_dir.resolve()
    base_run_config = _default_base_run_config()
    normalized_steps = _normalize_steps(steps)
    normalized_cli_overrides = _normalize_run_config_patch(cli_run_config_overrides)
    normalized_source_layout_id = _coerce_str(source_layout_id).strip()
    normalized_target_layout_id = _coerce_str(target_layout_id).strip()
    normalized_qa_ref_path = ""
    if isinstance(qa_ref_path, Path):
        normalized_qa_ref_path = _path_to_posix(qa_ref_path.resolve())
    elif isinstance(qa_ref_path, str):
        qa_ref_candidate = qa_ref_path.strip()
        if qa_ref_candidate:
            normalized_qa_ref_path = _path_to_posix(Path(qa_ref_candidate).resolve())

    normalized_qa_meters = _coerce_str(qa_meters).strip().lower()
    if normalized_qa_meters and normalized_qa_meters not in {"basic", "truth"}:
        raise ValueError("qa_meters must be one of: basic, truth.")

    normalized_qa_max_seconds: float | None = None
    if qa_max_seconds is not None:
        qa_max_seconds_value = _coerce_float(qa_max_seconds)
        if qa_max_seconds_value is None or qa_max_seconds_value < 0.0:
            raise ValueError("qa_max_seconds must be >= 0.")
        normalized_qa_max_seconds = qa_max_seconds_value

    normalized_format_sets = sorted(
        _normalize_format_sets(format_sets),
        key=lambda item: item[0],
    )
    overlays = _preset_overlay_map(presets_dir)

    presets = _normalize_preset_ids(preset_ids)
    configs = _normalize_config_paths(config_paths)
    preset_axis: list[str | None] = presets if presets else [None]
    config_axis: list[Path | None] = configs if configs else [None]

    raw_variants: list[dict[str, Any]] = []
    for preset_id in preset_axis:
        for config_path in config_axis:
            base_label = _variant_label(preset_id=preset_id, config_path=config_path)
            base_slug_seed = _slug_seed(
                preset_id=preset_id,
                config_path=config_path,
                overlay_map=overlays,
            )
            if not normalized_format_sets:
                raw_variants.append(
                    {
                        "preset_id": preset_id,
                        "config_path": config_path,
                        "label": base_label,
                        "slug_seed": base_slug_seed,
                        "render_output_formats": [],
                        "apply_output_formats": [],
                    }
                )
                continue

            for format_set_name, format_set_formats in normalized_format_sets:
                render_output_formats, apply_output_formats = _step_formats_for_format_set(
                    output_formats=format_set_formats,
                    normalized_steps=normalized_steps,
                )
                raw_variants.append(
                    {
                        "preset_id": preset_id,
                        "config_path": config_path,
                        "label": _label_with_format_set(base_label, format_set_name),
                        "slug_seed": _slug_with_format_set(base_slug_seed, format_set_name),
                        "render_output_formats": render_output_formats,
                        "apply_output_formats": apply_output_formats,
                    }
                )

    variants: list[dict[str, Any]] = []
    slug_counts: dict[str, int] = {}
    for index, item in enumerate(raw_variants, start=1):
        base_slug = _coerce_str(item.get("slug_seed")).strip() or "variant"
        seen_count = slug_counts.get(base_slug, 0)
        slug_counts[base_slug] = seen_count + 1
        if seen_count == 0:
            variant_slug = base_slug
        else:
            variant_slug = f"{base_slug}__{_suffix_from_index(seen_count - 1)}"

        variant_id = f"VARIANT.{index:03d}"
        variant_out_dir = resolved_out_dir / f"{variant_id}__{variant_slug}"
        step_payload = _variant_steps_payload(
            normalized_steps=normalized_steps,
            render_output_formats=_normalize_output_formats(item.get("render_output_formats")),
            apply_output_formats=_normalize_output_formats(item.get("apply_output_formats")),
        )
        variant_entry: dict[str, Any] = {
            "variant_id": variant_id,
            "variant_slug": variant_slug,
            "label": _coerce_str(item.get("label")) or "default",
            "steps": step_payload,
            "run_config_overrides": _with_variant_out_dir(
                normalized_cli_overrides,
                variant_out_dir=variant_out_dir,
            ),
        }

        preset_id = item.get("preset_id")
        if isinstance(preset_id, str) and preset_id:
            variant_entry["preset_id"] = preset_id

        config_path = item.get("config_path")
        if isinstance(config_path, Path):
            variant_entry["config_path"] = _path_to_posix(config_path)

        if normalized_source_layout_id:
            variant_entry["source_layout_id"] = normalized_source_layout_id
        if normalized_target_layout_id:
            variant_entry["target_layout_id"] = normalized_target_layout_id
        if normalized_qa_ref_path:
            variant_entry["qa_ref_path"] = normalized_qa_ref_path
        if normalized_qa_meters:
            variant_entry["qa_meters"] = normalized_qa_meters
        if normalized_qa_max_seconds is not None:
            variant_entry["qa_max_seconds"] = normalized_qa_max_seconds

        variants.append(variant_entry)

    return {
        "schema_version": VARIANT_SCHEMA_VERSION,
        "stems_dir": _path_to_posix(resolved_stems_dir),
        "base_run_config": base_run_config,
        "variants": variants,
    }


def run_variant_plan(
    plan: dict[str, Any],
    repo_root: Path,
    *,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object.")

    stems_dir_value = _coerce_str(plan.get("stems_dir")).strip()
    if not stems_dir_value:
        raise ValueError("plan.stems_dir is required.")
    stems_dir = Path(stems_dir_value)

    base_run_config = _coerce_dict(plan.get("base_run_config"))
    if not base_run_config:
        raise ValueError("plan.base_run_config is required.")
    base_run_config = normalize_run_config(base_run_config)

    variant_entries = _coerce_dict_list(plan.get("variants"))
    presets_dir = repo_root / "presets"
    report_schema_path = repo_root / "schemas" / "report.schema.json"
    plugins = load_plugins(repo_root / "plugins")
    scan_builder = _load_scan_builder(repo_root)
    analysis_lock: dict[str, Any] | None = None
    if cache_enabled:
        try:
            analysis_lock = build_lockfile(stems_dir)
        except ValueError:
            analysis_lock = None

    results: list[dict[str, Any]] = []
    for variant in variant_entries:
        variant_id = _coerce_str(variant.get("variant_id")).strip() or "VARIANT.000"
        variant_slug = _coerce_str(variant.get("variant_slug")).strip() or "variant"
        raw_steps = _coerce_dict(variant.get("steps"))
        steps = _normalize_steps(raw_steps)
        errors: list[str] = []

        try:
            variant_out_dir = _variant_out_dir_from_overrides(variant)
        except ValueError as exc:
            errors.append(f"run_config: {exc}")
            variant_out_dir = Path.cwd() / f"{variant_id}__{variant_slug}"
        report_path = variant_out_dir / "report.json"
        variant_result: dict[str, Any] = {
            "variant_id": variant_id,
            "out_dir": _path_to_posix(variant_out_dir),
            "report_path": _path_to_posix(report_path),
            "ok": False,
            "errors": errors,
        }

        effective_run_config: dict[str, Any] | None = None
        report: dict[str, Any] | None = None
        render_manifest: dict[str, Any] | None = None
        apply_manifest: dict[str, Any] | None = None
        applied_report: dict[str, Any] | None = None
        analysis_cache_key: str | None = None
        analysis_cache_run_config: dict[str, Any] | None = None

        try:
            effective_run_config = _merge_effective_run_config(
                base_run_config=base_run_config,
                variant=variant,
                presets_dir=presets_dir,
            )
            effective_run_config = _with_variant_layout_overrides(
                effective_run_config,
                variant,
            )
            analysis_cache_run_config = _analysis_run_config(effective_run_config)
        except Exception as exc:  # pragma: no cover - defensive surface
            errors.append(f"run_config: {exc}")

        if effective_run_config is not None and steps["analyze"]:
            meters = _meters_from_config(effective_run_config)
            profile_id = _profile_id_from_config(effective_run_config)
            if cache_enabled and analysis_lock is not None:
                try:
                    cache_run_config = analysis_cache_run_config or effective_run_config
                    analysis_cache_key = _analysis_cache_key(
                        analysis_lock,
                        cache_run_config,
                    )
                except ValueError as exc:
                    errors.append(f"cache: {exc}")
                else:
                    cached_report = try_load_cached_report(
                        cache_dir,
                        analysis_lock,
                        cache_run_config,
                    )
                    if (
                        isinstance(cached_report, dict)
                        and report_schema_is_valid(cached_report, report_schema_path)
                    ):
                        rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                        rewritten_report["run_config"] = normalize_run_config(
                            effective_run_config
                        )
                        if report_schema_is_valid(rewritten_report, report_schema_path):
                            report = rewritten_report
                            _write_json(report_path, report)
                            print(f"analysis cache: hit {analysis_cache_key} ({variant_id})")
                    if report is None and analysis_cache_key is not None:
                        print(f"analysis cache: miss {analysis_cache_key} ({variant_id})")

            if report is None:
                try:
                    report = scan_builder(
                        stems_dir,
                        _DEFAULT_GENERATED_AT,
                        strict=False,
                        include_peak=False,
                        meters=meters,
                    )
                    if not isinstance(report, dict):
                        raise ValueError("scan builder returned a non-object report.")

                    run_detectors(report, plugins)
                    run_resolvers(report, plugins)
                    apply_gates_to_report(
                        report,
                        policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
                        profile_id=profile_id,
                        profiles_path=repo_root
                        / "ontology"
                        / "policies"
                        / "authority_profiles.yaml",
                    )
                    if isinstance(report.get("mix_complexity"), dict):
                        report["vibe_signals"] = derive_vibe_signals(report)
                        report["preset_recommendations"] = derive_preset_recommendations(
                            report,
                            repo_root / "presets",
                        )
                    report["run_config"] = normalize_run_config(effective_run_config)
                    _write_json(report_path, report)

                    if (
                        cache_enabled
                        and analysis_lock is not None
                        and analysis_cache_key is not None
                        and report_schema_is_valid(report, report_schema_path)
                    ):
                        if _should_skip_analysis_cache_save(report, effective_run_config):
                            print(
                                "analysis cache: skip-save "
                                f"{analysis_cache_key} ({variant_id}) (time-cap stop)"
                            )
                        else:
                            try:
                                save_cached_report(
                                    cache_dir,
                                    analysis_lock,
                                    analysis_cache_run_config or effective_run_config,
                                    report,
                                )
                            except OSError:
                                pass
                except Exception as exc:  # pragma: no cover - defensive surface
                    errors.append(f"analyze: {exc}")

        if report is not None and effective_run_config is not None:
            try:
                _apply_variant_routing_step(
                    report=report,
                    variant=variant,
                    run_config=effective_run_config,
                    enabled=steps["routing"],
                )
            except ValueError as exc:
                errors.append(f"routing: {exc}")

        if report is not None and effective_run_config is not None and steps["downmix_qa"]:
            try:
                qa_payload = _run_variant_downmix_qa(
                    report=report,
                    variant=variant,
                    stems_dir=stems_dir,
                    run_config=effective_run_config,
                    repo_root=repo_root,
                )
                report["downmix_qa"] = _coerce_dict(qa_payload.get("downmix_qa"))
                merge_downmix_qa_issues_into_report(report)
                _refresh_report_after_downmix_qa(
                    report=report,
                    repo_root=repo_root,
                    profile_id=_profile_id_from_config(effective_run_config),
                )
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"downmix_qa: {exc}")

        if report is not None:
            try:
                _write_json(report_path, report)
            except OSError as exc:  # pragma: no cover - defensive surface
                errors.append(f"report: {exc}")

        if report is not None and steps["export_csv"]:
            try:
                csv_path = variant_out_dir / "report.csv"
                export_recall_csv(report, csv_path, include_gates=True)
                variant_result["csv_path"] = _path_to_posix(csv_path)
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"export_csv: {exc}")

        if report is not None and steps["export_pdf"]:
            try:
                truncate_values = _truncate_values_from_config(
                    _coerce_dict(report.get("run_config"))
                )
                pdf_path = variant_out_dir / "report.pdf"
                export_report_pdf(
                    report,
                    pdf_path,
                    include_measurements=True,
                    include_gates=True,
                    truncate_values=truncate_values,
                )
                variant_result["pdf_path"] = _path_to_posix(pdf_path)
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"export_pdf: {exc}")

        render_root = variant_out_dir / "render"
        apply_root = variant_out_dir / "apply"
        profile_id = _profile_id_from_config(effective_run_config or {})
        render_output_formats = _effective_output_formats(
            steps=raw_steps,
            run_config=effective_run_config or {},
            step_key="render_output_formats",
            section="render",
        )
        apply_output_formats = _effective_output_formats(
            steps=raw_steps,
            run_config=effective_run_config or {},
            step_key="apply_output_formats",
            section="apply",
        )

        if report is not None and steps["render"]:
            try:
                render_report = _json_clone(report)
                apply_gates_to_report(
                    render_report,
                    policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
                    profile_id=profile_id,
                    profiles_path=repo_root
                    / "ontology"
                    / "policies"
                    / "authority_profiles.yaml",
                )
                renderer_manifests = run_renderers(
                    render_report,
                    plugins,
                    output_dir=render_root,
                    eligibility_field="eligible_render",
                    context="render",
                    output_formats=render_output_formats,
                )
                render_deliverables = build_deliverables_for_renderer_manifests(
                    renderer_manifests
                )
                render_manifest = {
                    "schema_version": VARIANT_SCHEMA_VERSION,
                    "report_id": _coerce_str(render_report.get("report_id")),
                    "renderer_manifests": renderer_manifests,
                }
                if render_deliverables:
                    render_manifest["deliverables"] = render_deliverables
                render_manifest_path = variant_out_dir / "render_manifest.json"
                _write_json(render_manifest_path, render_manifest)
                variant_result["render_manifest_path"] = _path_to_posix(render_manifest_path)
                variant_result["render_output_formats"] = list(render_output_formats)
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"render: {exc}")

        if report is not None and steps["apply"]:
            try:
                apply_report = _json_clone(report)
                apply_gates_to_report(
                    apply_report,
                    policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
                    profile_id=profile_id,
                    profiles_path=repo_root
                    / "ontology"
                    / "policies"
                    / "authority_profiles.yaml",
                )
                renderer_manifests = run_renderers(
                    apply_report,
                    plugins,
                    output_dir=apply_root,
                    eligibility_field="eligible_auto_apply",
                    context="auto_apply",
                    output_formats=apply_output_formats,
                )
                apply_deliverables = build_deliverables_for_renderer_manifests(
                    renderer_manifests
                )
                apply_manifest = {
                    "schema_version": VARIANT_SCHEMA_VERSION,
                    "context": "auto_apply",
                    "report_id": _coerce_str(apply_report.get("report_id")),
                    "renderer_manifests": renderer_manifests,
                }
                if apply_deliverables:
                    apply_manifest["deliverables"] = apply_deliverables
                apply_manifest_path = variant_out_dir / "apply_manifest.json"
                _write_json(apply_manifest_path, apply_manifest)
                applied_report = _build_applied_report(
                    apply_report,
                    out_dir=apply_root,
                    renderer_manifests=renderer_manifests,
                )
                applied_report_path = variant_out_dir / "applied_report.json"
                _write_json(applied_report_path, applied_report)
                variant_result["apply_manifest_path"] = _path_to_posix(apply_manifest_path)
                variant_result["applied_report_path"] = _path_to_posix(applied_report_path)
                variant_result["apply_output_formats"] = list(apply_output_formats)
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"apply: {exc}")

        if report is not None and steps["bundle"]:
            try:
                bundle = build_ui_bundle(
                    report,
                    render_manifest,
                    apply_manifest=apply_manifest,
                    applied_report=applied_report,
                    help_registry_path=repo_root / "ontology" / "help.yaml",
                )
                bundle_path = variant_out_dir / "ui_bundle.json"
                _write_json(bundle_path, bundle)
                variant_result["bundle_path"] = _path_to_posix(bundle_path)
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"bundle: {exc}")

        variant_result["ok"] = len(errors) == 0
        variant_result["errors"] = errors
        results.append(variant_result)

    return {
        "schema_version": VARIANT_SCHEMA_VERSION,
        "plan": plan,
        "results": results,
    }
