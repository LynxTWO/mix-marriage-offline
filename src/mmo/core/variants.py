from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable

from mmo.core.gates import apply_gates_to_report
from mmo.core.pipeline import load_plugins, run_detectors, run_renderers, run_resolvers
from mmo.core.preset_recommendations import derive_preset_recommendations
from mmo.core.presets import list_presets, load_preset_run_config
from mmo.core.run_config import (
    RUN_CONFIG_SCHEMA_VERSION,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.ui_bundle import build_ui_bundle
from mmo.core.vibe_signals import derive_vibe_signals
from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf

VARIANT_SCHEMA_VERSION = "0.1.0"
_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_DEFAULT_GENERATED_AT = "2000-01-01T00:00:00Z"
_DEFAULT_TRUNCATE_VALUES = 200
_VARIANT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_VARIANT_STEP_KEYS = ("analyze", "export_pdf", "export_csv", "apply", "render", "bundle")
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


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_steps(steps: dict[str, Any] | None) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    source = steps or {}
    for key in _VARIANT_STEP_KEYS:
        normalized[key] = source.get(key) is True if isinstance(source, dict) else False
    normalized["analyze"] = True
    return normalized


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
    presets_dir: Path,
) -> dict[str, Any]:
    resolved_stems_dir = stems_dir.resolve()
    resolved_out_dir = out_dir.resolve()
    base_run_config = _default_base_run_config()
    normalized_steps = _normalize_steps(steps)
    normalized_cli_overrides = _normalize_run_config_patch(cli_run_config_overrides)
    overlays = _preset_overlay_map(presets_dir)

    presets = _normalize_preset_ids(preset_ids)
    configs = _normalize_config_paths(config_paths)
    preset_axis: list[str | None] = presets if presets else [None]
    config_axis: list[Path | None] = configs if configs else [None]

    raw_variants: list[dict[str, Any]] = []
    for preset_id in preset_axis:
        for config_path in config_axis:
            raw_variants.append(
                {
                    "preset_id": preset_id,
                    "config_path": config_path,
                    "label": _variant_label(preset_id=preset_id, config_path=config_path),
                    "slug_seed": _slug_seed(
                        preset_id=preset_id,
                        config_path=config_path,
                        overlay_map=overlays,
                    ),
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
        variant_entry: dict[str, Any] = {
            "variant_id": variant_id,
            "variant_slug": variant_slug,
            "label": _coerce_str(item.get("label")) or "default",
            "steps": dict(normalized_steps),
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

        variants.append(variant_entry)

    return {
        "schema_version": VARIANT_SCHEMA_VERSION,
        "stems_dir": _path_to_posix(resolved_stems_dir),
        "base_run_config": base_run_config,
        "variants": variants,
    }


def run_variant_plan(plan: dict[str, Any], repo_root: Path) -> dict[str, Any]:
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
    plugins = load_plugins(repo_root / "plugins")
    scan_builder = _load_scan_builder(repo_root)

    results: list[dict[str, Any]] = []
    for variant in variant_entries:
        variant_id = _coerce_str(variant.get("variant_id")).strip() or "VARIANT.000"
        variant_slug = _coerce_str(variant.get("variant_slug")).strip() or "variant"
        steps = _normalize_steps(_coerce_dict(variant.get("steps")))
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

        try:
            effective_run_config = _merge_effective_run_config(
                base_run_config=base_run_config,
                variant=variant,
                presets_dir=presets_dir,
            )
        except Exception as exc:  # pragma: no cover - defensive surface
            errors.append(f"run_config: {exc}")

        if effective_run_config is not None and steps["analyze"]:
            try:
                meters = _meters_from_config(effective_run_config)
                profile_id = _profile_id_from_config(effective_run_config)
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
            except Exception as exc:  # pragma: no cover - defensive surface
                errors.append(f"analyze: {exc}")

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
                )
                render_manifest = {
                    "schema_version": VARIANT_SCHEMA_VERSION,
                    "report_id": _coerce_str(render_report.get("report_id")),
                    "renderer_manifests": renderer_manifests,
                }
                render_manifest_path = variant_out_dir / "render_manifest.json"
                _write_json(render_manifest_path, render_manifest)
                variant_result["render_manifest_path"] = _path_to_posix(render_manifest_path)
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
                )
                apply_manifest = {
                    "schema_version": VARIANT_SCHEMA_VERSION,
                    "context": "auto_apply",
                    "report_id": _coerce_str(apply_report.get("report_id")),
                    "renderer_manifests": renderer_manifests,
                }
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
