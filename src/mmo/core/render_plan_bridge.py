from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS


_VARIANT_SCHEMA_VERSION = "0.1.0"
_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_VARIANT_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _normalize_output_formats(value: Any) -> list[str]:
    selected: set[str] = set()
    if isinstance(value, list):
        for item in value:
            normalized = _coerce_str(item).strip().lower()
            if normalized in _OUTPUT_FORMAT_ORDER:
                selected.add(normalized)
    if not selected:
        return ["wav"]
    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


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


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _normalize_run_config_patch(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_run_config(
        {
            **payload,
            "schema_version": payload.get("schema_version", RUN_CONFIG_SCHEMA_VERSION),
        }
    )
    normalized.pop("schema_version", None)
    return normalized


def _source_layout_id_from_scene(scene: dict[str, Any]) -> str | None:
    source = _coerce_dict(scene.get("source"))
    metadata = _coerce_dict(scene.get("metadata"))

    metadata_source_layout_id = _coerce_str(metadata.get("source_layout_id")).strip()
    if metadata_source_layout_id:
        return metadata_source_layout_id

    run_config_candidates = [
        _coerce_dict(source.get("run_config")),
        _coerce_dict(_coerce_dict(source.get("report")).get("run_config")),
        _coerce_dict(_coerce_dict(source.get("report_payload")).get("run_config")),
    ]
    for run_config in run_config_candidates:
        downmix_cfg = _coerce_dict(run_config.get("downmix"))
        source_layout_id = _coerce_str(downmix_cfg.get("source_layout_id")).strip()
        if source_layout_id:
            return source_layout_id
    return None


def _profile_id_from_scene(scene: dict[str, Any]) -> str:
    metadata = _coerce_dict(scene.get("metadata"))
    profile_id = _coerce_str(metadata.get("profile_id")).strip()
    if profile_id:
        return profile_id
    return _DEFAULT_PROFILE_ID


def _preset_id_from_scene(scene: dict[str, Any]) -> str | None:
    metadata = _coerce_dict(scene.get("metadata"))
    preset_id = _coerce_str(metadata.get("preset_id")).strip()
    if preset_id:
        return preset_id
    return None


def _stems_dir_from_scene(scene: dict[str, Any]) -> str:
    source = _coerce_dict(scene.get("source"))
    stems_dir = _coerce_str(source.get("stems_dir")).strip()
    if not stems_dir:
        raise ValueError("scene.source.stems_dir is required.")
    stems_path = Path(stems_dir)
    if not stems_path.is_absolute():
        raise ValueError("scene.source.stems_dir must be an absolute path.")
    return _path_to_posix(stems_path)


def _pointer_path(value: Any) -> str | None:
    candidate = _coerce_str(value).strip()
    if not candidate:
        return None
    return _path_to_posix(Path(candidate))


def _steps_for_job(
    *,
    job: dict[str, Any],
    default_steps: dict[str, Any],
) -> dict[str, Any]:
    def _step_bool(key: str, fallback: bool) -> bool:
        raw = default_steps.get(key)
        if isinstance(raw, bool):
            return raw
        return fallback

    target_layout_id = _coerce_str(job.get("target_layout_id")).strip()
    routing_plan_path = _coerce_str(job.get("routing_plan_path")).strip()

    contexts: set[str] = set()
    for item in job.get("contexts", []):
        normalized = _coerce_str(item).strip().lower()
        if normalized:
            contexts.add(normalized)

    return {
        "analyze": True,
        "routing": _step_bool(
            "routing",
            bool(routing_plan_path) or bool(target_layout_id),
        ),
        "downmix_qa": _step_bool("downmix_qa", False),
        "export_pdf": _step_bool("export_pdf", False),
        "export_csv": _step_bool("export_csv", False),
        "apply": _step_bool("apply", "auto_apply" in contexts),
        "render": _step_bool("render", True),
        "bundle": _step_bool("bundle", True),
    }


def render_plan_to_variant_plan(
    render_plan: dict,
    scene: dict,
    *,
    base_out_dir: str,
    default_steps: dict | None = None,
) -> dict:
    if not isinstance(render_plan, dict):
        raise ValueError("render_plan must be an object.")
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    jobs = render_plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("render_plan.jobs must be a non-empty list.")

    resolved_base_out_dir = _path_to_posix(Path(base_out_dir))
    stems_dir = _stems_dir_from_scene(scene)
    profile_id = _profile_id_from_scene(scene)
    preset_id = _preset_id_from_scene(scene)
    source_layout_id = _source_layout_id_from_scene(scene)
    normalized_default_steps = (
        dict(default_steps) if isinstance(default_steps, dict) else {}
    )

    policies = _coerce_dict(render_plan.get("policies"))
    downmix_policy_id = _coerce_str(policies.get("downmix_policy_id")).strip() or None

    base_run_config_raw: dict[str, Any] = {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "profile_id": profile_id,
    }
    if downmix_policy_id is not None:
        base_run_config_raw["downmix"] = {"policy_id": downmix_policy_id}
    base_run_config = normalize_run_config(base_run_config_raw)

    variants: list[dict[str, Any]] = []
    slug_counts: dict[str, int] = {}
    for index, raw_job in enumerate(jobs, start=1):
        if not isinstance(raw_job, dict):
            continue

        target_id = _coerce_str(raw_job.get("target_id")).strip()
        if not target_id:
            target_id = _coerce_str(raw_job.get("job_id")).strip() or "target"
        target_layout_id = _coerce_str(raw_job.get("target_layout_id")).strip()

        base_slug = _sanitize_slug(target_id)
        seen_count = slug_counts.get(base_slug, 0)
        slug_counts[base_slug] = seen_count + 1
        if seen_count == 0:
            variant_slug = base_slug
        else:
            variant_slug = f"{base_slug}__{_suffix_from_index(seen_count - 1)}"

        variant_id = f"VARIANT.{index:03d}"
        variant_out_dir = Path(resolved_base_out_dir) / f"{variant_id}__{variant_slug}"

        steps = _steps_for_job(
            job=raw_job,
            default_steps=normalized_default_steps,
        )
        steps["render_output_formats"] = _normalize_output_formats(
            raw_job.get("output_formats")
        )

        run_config_overrides_raw: dict[str, Any] = {
            "profile_id": profile_id,
            "render": {"out_dir": _path_to_posix(variant_out_dir)},
        }
        if downmix_policy_id is not None:
            run_config_overrides_raw["downmix"] = {"policy_id": downmix_policy_id}

        variant: dict[str, Any] = {
            "variant_id": variant_id,
            "variant_slug": variant_slug,
            "label": target_id,
            "steps": steps,
            "run_config_overrides": _normalize_run_config_patch(run_config_overrides_raw),
        }
        if preset_id is not None:
            variant["preset_id"] = preset_id
        if source_layout_id is not None:
            variant["source_layout_id"] = source_layout_id
        if target_layout_id:
            variant["target_layout_id"] = target_layout_id
        variants.append(variant)

    scene_path = _pointer_path(scene.get("scene_path")) or _pointer_path(
        render_plan.get("scene_path")
    )
    render_plan_path = _pointer_path(render_plan.get("render_plan_path"))

    metadata: dict[str, str] = {}
    if scene_path is not None:
        metadata["scene_path"] = scene_path
    if render_plan_path is not None:
        metadata["render_plan_path"] = render_plan_path

    payload: dict[str, Any] = {
        "schema_version": _VARIANT_SCHEMA_VERSION,
        "stems_dir": stems_dir,
        "base_run_config": base_run_config,
        "variants": variants,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload
