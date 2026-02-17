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

from mmo.core.registries.render_targets_registry import RenderTargetsRegistry
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS

RENDER_PLAN_SCHEMA_VERSION = "0.1.0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_DEFAULT_DOWNMIX_POLICY_ID = "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"


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
    echo: dict[str, Any] = {}

    # Multi-target: echo target_layout_ids; single: echo target_layout_id.
    ids = request.get("target_layout_ids")
    if isinstance(ids, list) and ids:
        echo["target_layout_ids"] = sorted(set(ids))
    else:
        echo["target_layout_id"] = request["target_layout_id"]

    echo["scene_path"] = request["scene_path"]

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


def _synthetic_target_id_for_layout(layout_id: str) -> str:
    layout_suffix = layout_id.replace("LAYOUT.", "")
    return f"TARGET.RENDER.{layout_suffix}"


def _normalize_requested_target_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("request.options.target_ids must be an array of TARGET.* IDs.")

    normalized: set[str] = set()
    for item in value:
        target_id = _coerce_str(item).strip()
        if target_id:
            normalized.add(target_id)
    return sorted(normalized)


def _requested_targets_by_layout(
    requested_target_ids: list[str],
    render_targets_registry: RenderTargetsRegistry,
) -> dict[str, list[str]]:
    by_layout: dict[str, list[str]] = {}
    for target_id in requested_target_ids:
        target = render_targets_registry.get_target(target_id)
        layout_id = _coerce_str(target.get("layout_id")).strip()
        if not layout_id:
            continue
        by_layout.setdefault(layout_id, []).append(target_id)

    for layout_id in sorted(by_layout.keys()):
        by_layout[layout_id] = sorted(by_layout[layout_id])
    return by_layout


def _resolve_target_for_layout(
    *,
    layout_id: str,
    render_targets_registry: RenderTargetsRegistry | None,
    requested_targets_by_layout: dict[str, list[str]] | None,
) -> str | None:
    if requested_targets_by_layout is not None:
        selected = requested_targets_by_layout.get(layout_id, [])
        if not selected:
            requested_ids = sorted(
                {
                    target_id
                    for target_ids in requested_targets_by_layout.values()
                    for target_id in target_ids
                }
            )
            raise ValueError(
                f"No requested target_ids match layout_id: {layout_id}. "
                f"Requested target_ids: {', '.join(requested_ids)}"
            )
        return selected[0]

    if render_targets_registry is None:
        return None

    candidates = render_targets_registry.find_targets_for_layout(layout_id)
    if not candidates:
        return None

    candidate_ids = sorted(
        {
            _coerce_str(candidate.get("target_id")).strip()
            for candidate in candidates
            if isinstance(candidate, dict)
        }
    )
    candidate_ids = [target_id for target_id in candidate_ids if target_id]
    if not candidate_ids:
        return None
    return candidate_ids[0]


def _extract_layout_ids(request: dict[str, Any]) -> list[str]:
    """Return sorted, deduplicated layout IDs from request."""
    ids = request.get("target_layout_ids")
    if isinstance(ids, list) and ids:
        return sorted(set(_coerce_str(i).strip() for i in ids if _coerce_str(i).strip()))
    single = _coerce_str(request.get("target_layout_id")).strip()
    if single:
        return [single]
    raise ValueError("request must have target_layout_id or target_layout_ids.")


def _build_job_notes(
    target_layout_id: str,
    routing_plan_path: str,
    downmix_policy_id: str | None,
) -> list[str]:
    notes: list[str] = []
    if target_layout_id in ("LAYOUT.2_0", "LAYOUT.1_0"):
        notes.append(f"Target layout is {target_layout_id}")
    if routing_plan_path:
        notes.append("Routing plan applied")
    if downmix_policy_id:
        notes.append(f"Downmix policy: {downmix_policy_id}")
    notes.sort()
    return notes


def _known_layout_ids(layouts: dict[str, Any] | None) -> list[str]:
    if not isinstance(layouts, dict):
        return []
    return sorted(
        {
            layout_id
            for layout_id, entry in layouts.items()
            if layout_id != "_meta" and isinstance(entry, dict)
        }
    )


def _known_policy_ids(downmix_registry: Any | None) -> list[str]:
    if downmix_registry is None:
        return []
    return sorted(
        {
            _coerce_str(policy_id).strip()
            for policy_id in downmix_registry.list_policy_ids()
            if _coerce_str(policy_id).strip()
        }
    )


def _effective_policy_id_for_identity_route(
    *,
    downmix_policy_id: str | None,
    downmix_registry: Any | None,
    source_layout_id: str,
) -> str:
    selected = _coerce_str(downmix_policy_id).strip()
    if selected:
        return selected

    if downmix_registry is not None:
        default_for_source = _coerce_str(
            downmix_registry.default_policy_for_source(source_layout_id)
        ).strip()
        if default_for_source:
            return default_for_source
        known_policy_ids = _known_policy_ids(downmix_registry)
        if _DEFAULT_DOWNMIX_POLICY_ID in known_policy_ids:
            return _DEFAULT_DOWNMIX_POLICY_ID
        if known_policy_ids:
            return known_policy_ids[0]

    return _DEFAULT_DOWNMIX_POLICY_ID


def _no_route_error(
    *,
    from_layout_id: str,
    to_layout_id: str,
    policy_id: str | None,
    downmix_registry: Any | None,
    layouts: dict[str, Any] | None,
) -> ValueError:
    selected_policy = _coerce_str(policy_id).strip() or "(default)"
    known_policy_ids = _known_policy_ids(downmix_registry)
    known_layouts = _known_layout_ids(layouts)

    policy_label = ", ".join(known_policy_ids) if known_policy_ids else "(none)"
    layout_label = ", ".join(known_layouts) if known_layouts else "(none)"
    return ValueError(
        "No downmix route found: "
        f"{from_layout_id} -> {to_layout_id} "
        f"(policy_id={selected_policy}). "
        f"Known policy_ids: {policy_label}. "
        f"Known layout_ids: {layout_label}"
    )


def _normalize_composed_steps(
    *,
    steps_raw: Any,
    from_layout_id: str,
    to_layout_id: str,
) -> list[dict[str, str]]:
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError(
            "Composed downmix route is missing steps: "
            f"{from_layout_id} -> {to_layout_id}"
        )

    normalized_steps: list[dict[str, str]] = []
    for step in steps_raw:
        if not isinstance(step, dict):
            raise ValueError(
                "Composed downmix route has an invalid step entry: "
                f"{from_layout_id} -> {to_layout_id}"
            )
        step_from = _coerce_str(step.get("source_layout_id")).strip()
        step_to = _coerce_str(step.get("target_layout_id")).strip()
        if not step_from or not step_to:
            raise ValueError(
                "Composed downmix route step is missing source/target layout IDs: "
                f"{from_layout_id} -> {to_layout_id}"
            )
        row: dict[str, str] = {
            "from_layout_id": step_from,
            "to_layout_id": step_to,
        }
        matrix_id = _coerce_str(step.get("matrix_id")).strip()
        if matrix_id:
            row["matrix_id"] = matrix_id
        normalized_steps.append(row)
    return normalized_steps


def _build_downmix_routes(
    *,
    target_layout_id: str,
    downmix_policy_id: str | None,
    downmix_registry: Any | None,
    layouts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if downmix_registry is None:
        raise ValueError("Downmix registry is required to build downmix_routes.")

    # Identity route for stereo targets remains deterministic and explicit.
    if target_layout_id == _STEREO_LAYOUT_ID:
        return [
            {
                "from_layout_id": target_layout_id,
                "to_layout_id": _STEREO_LAYOUT_ID,
                "policy_id": _effective_policy_id_for_identity_route(
                    downmix_policy_id=downmix_policy_id,
                    downmix_registry=downmix_registry,
                    source_layout_id=target_layout_id,
                ),
                "kind": "direct",
            }
        ]

    try:
        resolved = downmix_registry.resolve(
            downmix_policy_id,
            target_layout_id,
            _STEREO_LAYOUT_ID,
        )
    except ValueError as exc:
        raise _no_route_error(
            from_layout_id=target_layout_id,
            to_layout_id=_STEREO_LAYOUT_ID,
            policy_id=downmix_policy_id,
            downmix_registry=downmix_registry,
            layouts=layouts,
        ) from exc

    resolved_policy_id = _coerce_str(resolved.get("policy_id")).strip()
    if not resolved_policy_id:
        resolved_policy_id = _effective_policy_id_for_identity_route(
            downmix_policy_id=downmix_policy_id,
            downmix_registry=downmix_registry,
            source_layout_id=target_layout_id,
        )

    route: dict[str, Any] = {
        "from_layout_id": target_layout_id,
        "to_layout_id": _STEREO_LAYOUT_ID,
        "policy_id": resolved_policy_id,
    }

    if _coerce_str(resolved.get("matrix_id")).strip():
        route["kind"] = "direct"
        return [route]

    route["kind"] = "composed"
    route["steps"] = _normalize_composed_steps(
        steps_raw=resolved.get("steps"),
        from_layout_id=target_layout_id,
        to_layout_id=_STEREO_LAYOUT_ID,
    )
    return [route]


def _validate_policies(
    options_dict: dict[str, Any],
    downmix_registry: Any | None,
    gates_policy_ids: list[str] | None,
) -> tuple[str | None, str | None]:
    """Extract and validate policy IDs. Returns (downmix_policy_id, gates_policy_id)."""
    downmix_policy_id = _coerce_str(options_dict.get("downmix_policy_id")).strip() or None
    gates_policy_id = _coerce_str(options_dict.get("gates_policy_id")).strip() or None

    if downmix_policy_id and downmix_registry is not None:
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

    return downmix_policy_id, gates_policy_id


def build_render_plan(
    request: dict[str, Any],
    scene: dict[str, Any],
    *,
    routing_plan: dict[str, Any] | None = None,
    layouts: dict[str, Any] | None = None,
    render_targets_registry: RenderTargetsRegistry | None = None,
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
        render_targets_registry: Optional render targets registry for target_id lookup.
        downmix_registry: Optional DownmixRegistry for policy ID validation.
        gates_policy_ids: Optional list of known gates policy IDs for validation.

    Returns:
        A render_plan payload conforming to render_plan.schema.json.
    """
    if not isinstance(request, dict):
        raise ValueError("request must be an object.")
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    layout_ids = _extract_layout_ids(request)
    is_multi = len(layout_ids) > 1 or isinstance(request.get("target_layout_ids"), list)

    scene_path = _coerce_str(request.get("scene_path")).strip()
    if not scene_path:
        raise ValueError("request.scene_path is required.")
    scene_path = _to_posix(scene_path)

    # Extract and validate options/policies.
    options = request.get("options")
    options_dict = options if isinstance(options, dict) else {}
    output_formats = _normalize_output_formats(options_dict.get("output_formats"))
    downmix_policy_id, gates_policy_id = _validate_policies(
        options_dict, downmix_registry, gates_policy_ids,
    )
    requested_target_ids = _normalize_requested_target_ids(options_dict.get("target_ids"))
    requested_targets_by_layout: dict[str, list[str]] | None = None
    if requested_target_ids:
        if render_targets_registry is None:
            raise ValueError(
                "request.options.target_ids was provided, but no render targets registry is available."
            )
        requested_targets_by_layout = _requested_targets_by_layout(
            requested_target_ids,
            render_targets_registry,
        )

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

    if not is_multi:
        # ── Single-target path (backward-compatible, byte-identical) ──
        return _build_single_target_plan(
            request=request,
            scene=scene,
            layout_id=layout_ids[0],
            scene_path=scene_path,
            output_formats=output_formats,
            downmix_policy_id=downmix_policy_id,
            gates_policy_id=gates_policy_id,
            routing_plan_path=routing_plan_path,
            routing_plan=routing_plan,
            layouts=layouts,
            render_targets_registry=render_targets_registry,
            requested_targets_by_layout=requested_targets_by_layout,
            downmix_registry=downmix_registry,
        )

    # ── Multi-target path ──
    return _build_multi_target_plan(
        request=request,
        scene=scene,
        layout_ids=layout_ids,
        scene_path=scene_path,
        output_formats=output_formats,
        downmix_policy_id=downmix_policy_id,
        gates_policy_id=gates_policy_id,
        routing_plan_path=routing_plan_path,
        routing_plan=routing_plan,
        layouts=layouts,
        render_targets_registry=render_targets_registry,
        requested_targets_by_layout=requested_targets_by_layout,
        downmix_registry=downmix_registry,
    )


def _build_single_target_plan(
    *,
    request: dict[str, Any],
    scene: dict[str, Any],
    layout_id: str,
    scene_path: str,
    output_formats: list[str],
    downmix_policy_id: str | None,
    gates_policy_id: str | None,
    routing_plan_path: str,
    routing_plan: dict[str, Any] | None,
    layouts: dict[str, Any] | None,
    render_targets_registry: RenderTargetsRegistry | None,
    requested_targets_by_layout: dict[str, list[str]] | None,
    downmix_registry: Any | None,
) -> dict[str, Any]:
    """Build plan for a single target_layout_id (original behavior, byte-identical)."""
    resolved_target_id = _resolve_target_for_layout(
        layout_id=layout_id,
        render_targets_registry=render_targets_registry,
        requested_targets_by_layout=requested_targets_by_layout,
    )
    target_id = resolved_target_id or _synthetic_target_id_for_layout(layout_id)

    # Resolve layout metadata.
    if isinstance(layouts, dict) and layouts:
        resolved = _resolve_layout(layout_id, layouts)
    else:
        resolved = {
            "target_layout_id": layout_id,
            "channel_order": [f"SPK.CH{i}" for i in range(2)],
        }

    resolved["downmix_policy_id"] = downmix_policy_id
    resolved["gates_policy_id"] = gates_policy_id

    # Build the single job.
    job_inputs = _build_job_inputs(scene, routing_plan)
    job_outputs = _build_job_outputs(output_formats, layout_id, scene_path)
    notes = _build_job_notes(layout_id, routing_plan_path, downmix_policy_id)

    job: dict[str, Any] = {
        "job_id": "JOB.001",
        "target_id": target_id,
        "target_layout_id": layout_id,
        "downmix_routes": _build_downmix_routes(
            target_layout_id=layout_id,
            downmix_policy_id=downmix_policy_id,
            downmix_registry=downmix_registry,
            layouts=layouts,
        ),
        "output_formats": list(output_formats),
        "contexts": ["render"],
        "status": "planned",
        "inputs": job_inputs,
        "outputs": job_outputs,
        "notes": notes,
    }
    if resolved_target_id is not None:
        job["resolved_target_id"] = resolved_target_id
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


def _build_multi_target_plan(
    *,
    request: dict[str, Any],
    scene: dict[str, Any],
    layout_ids: list[str],
    scene_path: str,
    output_formats: list[str],
    downmix_policy_id: str | None,
    gates_policy_id: str | None,
    routing_plan_path: str,
    routing_plan: dict[str, Any] | None,
    layouts: dict[str, Any] | None,
    render_targets_registry: RenderTargetsRegistry | None,
    requested_targets_by_layout: dict[str, list[str]] | None,
    downmix_registry: Any | None,
) -> dict[str, Any]:
    """Build plan for multiple target_layout_ids."""
    job_inputs = _build_job_inputs(scene, routing_plan)
    all_target_ids: list[str] = []
    jobs: list[dict[str, Any]] = []
    resolved_layouts: list[dict[str, Any]] = []

    for idx, layout_id in enumerate(layout_ids):
        resolved_target_id = _resolve_target_for_layout(
            layout_id=layout_id,
            render_targets_registry=render_targets_registry,
            requested_targets_by_layout=requested_targets_by_layout,
        )
        target_id = resolved_target_id or _synthetic_target_id_for_layout(layout_id)
        all_target_ids.append(target_id)

        # Resolve layout metadata.
        if isinstance(layouts, dict) and layouts:
            resolved = _resolve_layout(layout_id, layouts)
        else:
            resolved = {
                "target_layout_id": layout_id,
                "channel_order": [f"SPK.CH{i}" for i in range(2)],
            }
        resolved["downmix_policy_id"] = downmix_policy_id
        resolved["gates_policy_id"] = gates_policy_id
        resolved_layouts.append(resolved)

        # Build job.
        job_outputs = _build_job_outputs(output_formats, layout_id, scene_path)
        notes = _build_job_notes(layout_id, routing_plan_path, downmix_policy_id)

        job: dict[str, Any] = {
            "job_id": f"JOB.{idx + 1:03d}",
            "target_id": target_id,
            "target_layout_id": layout_id,
            "downmix_routes": _build_downmix_routes(
                target_layout_id=layout_id,
                downmix_policy_id=downmix_policy_id,
                downmix_registry=downmix_registry,
                layouts=layouts,
            ),
            "output_formats": list(output_formats),
            "contexts": ["render"],
            "status": "planned",
            "inputs": list(job_inputs),
            "outputs": job_outputs,
            "notes": notes,
        }
        if resolved_target_id is not None:
            job["resolved_target_id"] = resolved_target_id
        if routing_plan_path:
            job["routing_plan_path"] = routing_plan_path
        jobs.append(job)

    # Build policies.
    policies: dict[str, str] = {}
    if gates_policy_id:
        policies["gates_policy_id"] = gates_policy_id
    if downmix_policy_id:
        policies["downmix_policy_id"] = downmix_policy_id

    # Targets list sorted.
    all_target_ids = sorted(set(all_target_ids))

    # Use first layout's resolved for backward-compat `resolved` field.
    first_resolved = resolved_layouts[0]

    # Assemble the plan (without plan_id first for hashing).
    request_echo = _build_request_echo(request)
    plan_without_id: dict[str, Any] = {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "scene_path": scene_path,
        "targets": all_target_ids,
        "policies": policies,
        "jobs": jobs,
        "request": request_echo,
        "resolved": first_resolved,
        "resolved_layouts": resolved_layouts,
    }

    scene_id = _scene_id_from_scene(scene)
    plan_id = f"PLAN.{scene_id}.{_hash8(plan_without_id)}"

    return {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "scene_path": scene_path,
        "targets": all_target_ids,
        "policies": policies,
        "jobs": jobs,
        "request": request_echo,
        "resolved": first_resolved,
        "resolved_layouts": resolved_layouts,
    }
