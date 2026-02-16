"""Build a deterministic render plan from a render_request + scene.

This module produces render_plan payloads that conform to the extended
render_plan.schema.json with request echo, resolved layout metadata,
and jobs with status/inputs/outputs fields.

No audio rendering is performed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS

RENDER_PLAN_SCHEMA_VERSION = "0.1.0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


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


def _hash8(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _to_posix(path_str: str) -> str:
    return path_str.replace("\\", "/")


def _resolve_layout(
    layout_id: str,
    layouts: dict[str, Any],
) -> dict[str, Any]:
    entry = layouts.get(layout_id)
    if not isinstance(entry, dict):
        known = sorted(
            k for k in layouts if k != "_meta" and isinstance(layouts[k], dict)
        )
        if known:
            raise ValueError(
                f"Unknown layout_id: {layout_id}. "
                f"Known layout_ids: {', '.join(known)}"
            )
        raise ValueError(
            f"Unknown layout_id: {layout_id}. No layouts are available."
        )

    channel_order = entry.get("channel_order")
    if not isinstance(channel_order, list) or not channel_order:
        raise ValueError(f"Layout {layout_id} has no channel_order.")

    resolved: dict[str, Any] = {
        "target_layout_id": layout_id,
        "channel_order": list(channel_order),
    }

    channel_count = entry.get("channel_count")
    if isinstance(channel_count, int) and not isinstance(channel_count, bool):
        resolved["channel_count"] = channel_count

    family = _coerce_str(entry.get("family")).strip()
    if family:
        resolved["family"] = family

    has_lfe = entry.get("has_lfe")
    if isinstance(has_lfe, bool):
        resolved["has_lfe"] = has_lfe

    return resolved


def _build_request_echo(request: dict[str, Any]) -> dict[str, Any]:
    echo: dict[str, Any] = {
        "target_layout_id": request["target_layout_id"],
        "scene_path": request["scene_path"],
    }
    routing_plan_path = _coerce_str(request.get("routing_plan_path")).strip()
    if routing_plan_path:
        echo["routing_plan_path"] = routing_plan_path

    options = request.get("options")
    if isinstance(options, dict) and options:
        echo_options: dict[str, Any] = {}
        for key in sorted(options.keys()):
            echo_options[key] = options[key]
        echo["options"] = echo_options

    return echo


def _scene_id_from_scene(scene: dict[str, Any]) -> str:
    scene_id = _coerce_str(scene.get("scene_id")).strip()
    return scene_id if scene_id else "SCENE.UNKNOWN"


def _build_job_inputs(
    scene: dict[str, Any],
    routing_plan: dict[str, Any] | None,
) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []

    scene_path = _coerce_str(scene.get("scene_path")).strip()
    if scene_path:
        inputs.append({"path": _to_posix(scene_path), "role": "scene"})

    if isinstance(routing_plan, dict):
        rp_path = _coerce_str(routing_plan.get("routing_plan_path")).strip()
        if rp_path:
            inputs.append({"path": _to_posix(rp_path), "role": "routing_plan"})

    inputs.sort(key=lambda item: item["path"])
    return inputs


def _build_job_outputs(
    output_formats: list[str],
    target_layout_id: str,
    scene_path: str,
) -> list[dict[str, str]]:
    scene_dir = str(PurePosixPath(_to_posix(scene_path)).parent)
    if scene_dir == ".":
        scene_dir = ""

    layout_slug = target_layout_id.replace("LAYOUT.", "").lower()
    outputs: list[dict[str, str]] = []
    for fmt in output_formats:
        if scene_dir:
            path = f"{scene_dir}/renders/{layout_slug}/mix.{fmt}"
        else:
            path = f"renders/{layout_slug}/mix.{fmt}"
        outputs.append({"path": path, "format": fmt})

    outputs.sort(key=lambda item: item["path"])
    return outputs


def _find_render_target(
    target_layout_id: str,
    render_targets: dict[str, Any] | None,
) -> tuple[str, str]:
    if isinstance(render_targets, dict):
        targets = render_targets.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, dict):
                    continue
                layout_id = _coerce_str(target.get("layout_id")).strip()
                if layout_id == target_layout_id:
                    target_id = _coerce_str(target.get("target_id")).strip()
                    if target_id:
                        return target_id, layout_id

    layout_suffix = target_layout_id.replace("LAYOUT.", "")
    return f"TARGET.RENDER.{layout_suffix}", target_layout_id


def build_render_plan(
    request: dict[str, Any],
    scene: dict[str, Any],
    *,
    routing_plan: dict[str, Any] | None = None,
    layouts: dict[str, Any] | None = None,
    render_targets: dict[str, Any] | None = None,
    downmix_registry: Any | None = None,
    gates_policy_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic render plan from a validated render_request.

    Args:
        request: A validated render_request payload.
        scene: A validated scene payload (with scene_path injected).
        routing_plan: Optional validated routing plan payload.
        layouts: Layouts registry dict (layout_id -> entry). If None,
            resolved section will use minimal data from the request.
        render_targets: Optional render targets registry for target_id lookup.
        downmix_registry: Optional DownmixRegistry for policy ID validation.
        gates_policy_ids: Optional list of known gates policy IDs for validation.

    Returns:
        A render_plan payload conforming to render_plan.schema.json.
    """
    if not isinstance(request, dict):
        raise ValueError("request must be an object.")
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    target_layout_id = _coerce_str(request.get("target_layout_id")).strip()
    if not target_layout_id:
        raise ValueError("request.target_layout_id is required.")

    scene_path = _coerce_str(request.get("scene_path")).strip()
    if not scene_path:
        raise ValueError("request.scene_path is required.")
    scene_path = _to_posix(scene_path)

    # Resolve the target render target ID.
    target_id, resolved_layout_id = _find_render_target(
        target_layout_id, render_targets,
    )

    # Resolve layout metadata.
    if isinstance(layouts, dict) and layouts:
        resolved = _resolve_layout(target_layout_id, layouts)
    else:
        resolved = {
            "target_layout_id": target_layout_id,
            "channel_order": [f"SPK.CH{i}" for i in range(2)],
        }

    # Extract options.
    options = request.get("options")
    options_dict = options if isinstance(options, dict) else {}

    output_formats = _normalize_output_formats(options_dict.get("output_formats"))

    downmix_policy_id = _coerce_str(options_dict.get("downmix_policy_id")).strip() or None
    gates_policy_id = _coerce_str(options_dict.get("gates_policy_id")).strip() or None

    # Validate policy IDs against registries when provided.
    if downmix_policy_id and downmix_registry is not None:
        # get_policy raises ValueError with sorted known IDs on miss.
        downmix_registry.get_policy(downmix_policy_id)

    if gates_policy_id and gates_policy_ids is not None:
        if gates_policy_id not in gates_policy_ids:
            known = sorted(gates_policy_ids)
            if known:
                raise ValueError(
                    f"Unknown gates_policy_id: {gates_policy_id}. "
                    f"Known gates_policy_ids: {', '.join(known)}"
                )
            raise ValueError(
                f"Unknown gates_policy_id: {gates_policy_id}. "
                f"No gates policies are available."
            )

    resolved["downmix_policy_id"] = downmix_policy_id
    resolved["gates_policy_id"] = gates_policy_id

    # Build routing plan path.
    routing_plan_path = _coerce_str(request.get("routing_plan_path")).strip()
    if routing_plan_path:
        routing_plan_path = _to_posix(routing_plan_path)

    # Validate routing plan path / argument consistency.
    if routing_plan_path and routing_plan is None:
        raise ValueError(
            f"request.routing_plan_path is set ({routing_plan_path}) "
            f"but no routing_plan was provided."
        )

    # Build the single job.
    job_inputs = _build_job_inputs(scene, routing_plan)
    job_outputs = _build_job_outputs(output_formats, target_layout_id, scene_path)

    notes: list[str] = []
    if target_layout_id in ("LAYOUT.2_0", "LAYOUT.1_0"):
        notes.append(f"Target layout is {target_layout_id}")
    if routing_plan_path:
        notes.append("Routing plan applied")
    if downmix_policy_id:
        notes.append(f"Downmix policy: {downmix_policy_id}")
    notes.sort()

    job: dict[str, Any] = {
        "job_id": "JOB.001",
        "target_id": target_id,
        "target_layout_id": target_layout_id,
        "output_formats": list(output_formats),
        "contexts": ["render"],
        "status": "planned",
        "inputs": job_inputs,
        "outputs": job_outputs,
        "notes": notes,
    }
    if routing_plan_path:
        job["routing_plan_path"] = routing_plan_path

    # Build policies.
    policies: dict[str, str] = {}
    if gates_policy_id:
        policies["gates_policy_id"] = gates_policy_id
    if downmix_policy_id:
        policies["downmix_policy_id"] = downmix_policy_id

    # Assemble the plan (without plan_id first for hashing).
    request_echo = _build_request_echo(request)
    plan_without_id: dict[str, Any] = {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "scene_path": scene_path,
        "targets": [target_id],
        "policies": policies,
        "jobs": [job],
        "request": request_echo,
        "resolved": resolved,
    }

    scene_id = _scene_id_from_scene(scene)
    plan_id = f"PLAN.{scene_id}.{_hash8(plan_without_id)}"

    return {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "scene_path": scene_path,
        "targets": [target_id],
        "policies": policies,
        "jobs": [job],
        "request": request_echo,
        "resolved": resolved,
    }
