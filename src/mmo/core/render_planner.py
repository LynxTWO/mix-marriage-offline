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

from mmo.core.lfe_derivation_profiles import (
    DEFAULT_LFE_DERIVATION_PROFILE_ID,
    get_lfe_derivation_profile,
)
from mmo.core.loudness_profiles import get_loudness_profile
from mmo.core.placement_policy import build_render_intent
from mmo.core.registries.render_targets_registry import RenderTargetsRegistry
from mmo.dsp.lfe_derive import PHASE_DELTA_THRESHOLD_DB, derive_missing_lfe
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS

RENDER_PLAN_SCHEMA_VERSION = "0.1.0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_DEFAULT_DOWNMIX_POLICY_ID = "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"
_DEFAULT_LFE_MODE = "mono"
_LFE_SPEAKER_IDS: frozenset[str] = frozenset({"SPK.LFE", "SPK.LFE1", "SPK.LFE2"})


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


def _normalize_lfe_mode(value: Any) -> str:
    normalized = _coerce_str(value).strip().lower()
    if normalized in {"mono", "stereo"}:
        return normalized
    return _DEFAULT_LFE_MODE


def _is_lfe_speaker_id(speaker_id: str) -> bool:
    token = _coerce_str(speaker_id).strip().upper()
    if token in _LFE_SPEAKER_IDS:
        return True
    return token.startswith("SPK.LFE")


def _lfe_speakers(channel_order: list[str]) -> list[str]:
    return [speaker_id for speaker_id in channel_order if _is_lfe_speaker_id(speaker_id)]


def _layout_has_lfe(layout_id: str, layouts: dict[str, Any] | None) -> bool | None:
    if not layout_id or not isinstance(layouts, dict):
        return None
    layout = layouts.get(layout_id)
    if not isinstance(layout, dict):
        return None

    has_lfe = layout.get("has_lfe")
    if isinstance(has_lfe, bool):
        return has_lfe

    lfe_policy = layout.get("lfe_policy")
    if isinstance(lfe_policy, dict):
        lfe_channels = lfe_policy.get("lfe_channels")
        if isinstance(lfe_channels, list):
            return bool(lfe_channels)

    channel_order = layout.get("channel_order")
    if isinstance(channel_order, list):
        return any(_is_lfe_speaker_id(str(speaker_id)) for speaker_id in channel_order)
    return None


def _scene_source_layout_id(scene: dict[str, Any]) -> str | None:
    source = scene.get("source")
    if isinstance(source, dict):
        candidate = _coerce_str(source.get("layout_id")).strip()
        if candidate:
            return candidate
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        for key in ("source_layout_id", "layout_id"):
            candidate = _coerce_str(metadata.get(key)).strip()
            if candidate:
                return candidate
    return None


def _scene_has_explicit_lfe_content(scene: dict[str, Any]) -> bool | None:
    metadata = scene.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("source_has_lfe_program_content", "has_lfe_program_content"):
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
    return None


def _source_has_lfe_program_content(
    *,
    scene: dict[str, Any],
    layouts: dict[str, Any] | None,
) -> tuple[bool, str]:
    explicit = _scene_has_explicit_lfe_content(scene)
    if isinstance(explicit, bool):
        if explicit:
            return True, "scene_metadata_declares_lfe_program_content"
        return False, "scene_metadata_declares_missing_lfe_program_content"

    source_layout_id = _scene_source_layout_id(scene)
    if source_layout_id:
        layout_has_lfe = _layout_has_lfe(source_layout_id, layouts)
        if layout_has_lfe is True:
            return True, f"source_layout_has_lfe:{source_layout_id}"
        if layout_has_lfe is False:
            return False, f"source_layout_has_no_lfe:{source_layout_id}"

    return False, "source_lfe_program_content_unknown_assumed_missing"


def _passthrough_lfe_receipt(
    *,
    profile_id: str,
    lfe_mode: str,
    target_lfe_channel_count: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "passthrough",
        "derivation_applied": False,
        "derivation_ran": False,
        "derivation_reason": reason,
        "profile_id": profile_id,
        "profile_lowpass_hz": None,
        "profile_slope_db_per_oct": None,
        "profile_trim_db": None,
        "lfe_mode": lfe_mode,
        "target_lfe_channel_count": target_lfe_channel_count,
        "chosen_sum_mode": "passthrough",
        "delta_db": 0.0,
        "delta_threshold_db": float(PHASE_DELTA_THRESHOLD_DB),
    }


def _build_lfe_receipt_for_target(
    *,
    target_layout_id: str,
    channel_order: list[str],
    scene: dict[str, Any],
    layouts: dict[str, Any] | None,
    lfe_derivation_profile_id: str,
    lfe_mode: str,
) -> dict[str, Any] | None:
    lfe_speakers = _lfe_speakers(channel_order)
    if not lfe_speakers:
        return None

    normalized_mode = _normalize_lfe_mode(lfe_mode)
    profile = get_lfe_derivation_profile(lfe_derivation_profile_id)
    source_has_lfe, source_reason = _source_has_lfe_program_content(
        scene=scene,
        layouts=layouts,
    )
    if source_has_lfe:
        return _passthrough_lfe_receipt(
            profile_id=profile["lfe_derivation_profile_id"],
            lfe_mode=normalized_mode,
            target_lfe_channel_count=len(lfe_speakers),
            reason=f"target_has_lfe_and_{source_reason}",
        )

    _, receipt = derive_missing_lfe(
        left=[],
        right=[],
        sample_rate_hz=48000,
        target_lfe_channel_count=len(lfe_speakers),
        profile=profile,
        lfe_mode=normalized_mode,
        delta_threshold_db=PHASE_DELTA_THRESHOLD_DB,
    )
    receipt["derivation_reason"] = f"target_has_lfe_and_{source_reason}"
    return receipt


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
    else:
        resolved["has_lfe"] = bool(_lfe_speakers(list(channel_order)))

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
            if key == "loudness_profile_id":
                normalized = _coerce_str(options.get(key)).strip()
                if normalized:
                    echo_options[key] = normalized
                continue
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
    *,
    filename_template: str | None = None,
) -> list[dict[str, str]]:
    scene_dir = str(PurePosixPath(_to_posix(scene_path)).parent)
    if scene_dir == ".":
        scene_dir = ""

    normalized_template = _coerce_str(filename_template).strip()
    outputs: list[dict[str, str]] = []
    if normalized_template:
        template = _to_posix(normalized_template).lstrip("/")
        for fmt in output_formats:
            output_rel_path = template.replace("{container}", fmt)
            if scene_dir:
                path = f"{scene_dir}/{output_rel_path}"
            else:
                path = output_rel_path
            outputs.append({"path": path, "format": fmt})
        outputs.sort(key=lambda item: item["path"])
        return outputs

    layout_slug = target_layout_id.replace("LAYOUT.", "").lower()
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


def _target_filename_template(
    *,
    target_id: str | None,
    render_targets_registry: RenderTargetsRegistry | None,
) -> str | None:
    normalized_target_id = _coerce_str(target_id).strip()
    if not normalized_target_id or render_targets_registry is None:
        return None
    try:
        target = render_targets_registry.get_target(normalized_target_id)
    except ValueError:
        return None
    template = _coerce_str(target.get("filename_template")).strip()
    if not template:
        return None
    return template


def _requested_target_specs(
    *,
    layout_ids: list[str],
    requested_target_ids: list[str],
    render_targets_registry: RenderTargetsRegistry,
) -> list[tuple[str, str]]:
    allowed_layout_ids = set(layout_ids)
    specs: list[tuple[str, str]] = []
    for target_id in requested_target_ids:
        target = render_targets_registry.get_target(target_id)
        layout_id = _coerce_str(target.get("layout_id")).strip()
        if not layout_id:
            continue
        if layout_id not in allowed_layout_ids:
            raise ValueError(
                f"Requested target_id {target_id} resolved to unsupported layout_id: {layout_id}. "
                f"Allowed layout_ids: {', '.join(layout_ids)}"
            )
        specs.append((target_id, layout_id))
    if not specs:
        raise ValueError(
            "No requested target_ids resolved to allowed layout_ids."
        )
    return specs


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
) -> tuple[str | None, str | None, str | None, str, str]:
    """Extract and validate policy/profile IDs.

    Returns ``(downmix_policy_id, gates_policy_id, loudness_profile_id, lfe_derivation_profile_id, lfe_mode)``.
    """
    downmix_policy_id = _coerce_str(options_dict.get("downmix_policy_id")).strip() or None
    gates_policy_id = _coerce_str(options_dict.get("gates_policy_id")).strip() or None
    loudness_profile_id = _coerce_str(options_dict.get("loudness_profile_id")).strip() or None
    lfe_derivation_profile_id = (
        _coerce_str(options_dict.get("lfe_derivation_profile_id")).strip()
        or DEFAULT_LFE_DERIVATION_PROFILE_ID
    )
    lfe_mode = _normalize_lfe_mode(options_dict.get("lfe_mode"))

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

    if loudness_profile_id:
        get_loudness_profile(loudness_profile_id)

    # Always validate selected LFE derivation profile for deterministic errors.
    get_lfe_derivation_profile(lfe_derivation_profile_id)

    return (
        downmix_policy_id,
        gates_policy_id,
        loudness_profile_id,
        lfe_derivation_profile_id,
        lfe_mode,
    )


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
    (
        downmix_policy_id,
        gates_policy_id,
        loudness_profile_id,
        lfe_derivation_profile_id,
        lfe_mode,
    ) = _validate_policies(
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
            loudness_profile_id=loudness_profile_id,
            lfe_derivation_profile_id=lfe_derivation_profile_id,
            lfe_mode=lfe_mode,
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
        requested_target_ids=requested_target_ids,
        scene_path=scene_path,
        output_formats=output_formats,
        downmix_policy_id=downmix_policy_id,
        gates_policy_id=gates_policy_id,
        loudness_profile_id=loudness_profile_id,
        lfe_derivation_profile_id=lfe_derivation_profile_id,
        lfe_mode=lfe_mode,
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
    loudness_profile_id: str | None,
    lfe_derivation_profile_id: str,
    lfe_mode: str,
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
    resolved["lfe_derivation_profile_id"] = lfe_derivation_profile_id
    resolved["lfe_mode"] = _normalize_lfe_mode(lfe_mode)

    # Build the single job.
    job_inputs = _build_job_inputs(scene, routing_plan)
    job_outputs = _build_job_outputs(output_formats, layout_id, scene_path)
    notes = _build_job_notes(layout_id, routing_plan_path, downmix_policy_id)
    render_intent = build_render_intent(scene, layout_id, layouts=layouts)

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
    if isinstance(render_intent, dict):
        job["render_intent"] = render_intent
    lfe_receipt = _build_lfe_receipt_for_target(
        target_layout_id=layout_id,
        channel_order=list(resolved.get("channel_order") or []),
        scene=scene,
        layouts=layouts,
        lfe_derivation_profile_id=lfe_derivation_profile_id,
        lfe_mode=lfe_mode,
    )
    if isinstance(lfe_receipt, dict):
        job["lfe_receipt"] = lfe_receipt
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
    if loudness_profile_id:
        policies["loudness_profile_id"] = loudness_profile_id
    policies["lfe_derivation_profile_id"] = lfe_derivation_profile_id

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
    requested_target_ids: list[str],
    scene_path: str,
    output_formats: list[str],
    downmix_policy_id: str | None,
    gates_policy_id: str | None,
    loudness_profile_id: str | None,
    lfe_derivation_profile_id: str,
    lfe_mode: str,
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
    resolved_layouts_by_id: dict[str, dict[str, Any]] = {}
    render_intent_by_layout: dict[str, dict[str, Any]] = {}

    target_specs: list[tuple[str, str, str | None]] = []
    if requested_target_ids:
        if render_targets_registry is None:
            raise ValueError(
                "request.options.target_ids was provided, but no render targets registry is available."
            )
        target_specs = [
            (target_id, layout_id, target_id)
            for target_id, layout_id in _requested_target_specs(
                layout_ids=layout_ids,
                requested_target_ids=requested_target_ids,
                render_targets_registry=render_targets_registry,
            )
        ]
    else:
        for layout_id in layout_ids:
            resolved_target_id = _resolve_target_for_layout(
                layout_id=layout_id,
                render_targets_registry=render_targets_registry,
                requested_targets_by_layout=requested_targets_by_layout,
            )
            target_id = resolved_target_id or _synthetic_target_id_for_layout(layout_id)
            target_specs.append((target_id, layout_id, resolved_target_id))

    for idx, (target_id, layout_id, resolved_target_id) in enumerate(target_specs):
        all_target_ids.append(target_id)

        # Resolve layout metadata.
        if layout_id not in resolved_layouts_by_id:
            if isinstance(layouts, dict) and layouts:
                resolved = _resolve_layout(layout_id, layouts)
            else:
                resolved = {
                    "target_layout_id": layout_id,
                    "channel_order": [f"SPK.CH{i}" for i in range(2)],
                }
            resolved["downmix_policy_id"] = downmix_policy_id
            resolved["gates_policy_id"] = gates_policy_id
            resolved["lfe_derivation_profile_id"] = lfe_derivation_profile_id
            resolved["lfe_mode"] = _normalize_lfe_mode(lfe_mode)
            resolved_layouts_by_id[layout_id] = resolved

        # Build job.
        job_outputs = _build_job_outputs(
            output_formats,
            layout_id,
            scene_path,
            filename_template=_target_filename_template(
                target_id=target_id,
                render_targets_registry=render_targets_registry,
            ),
        )
        notes = _build_job_notes(layout_id, routing_plan_path, downmix_policy_id)
        if layout_id not in render_intent_by_layout:
            render_intent = build_render_intent(scene, layout_id, layouts=layouts)
            if isinstance(render_intent, dict):
                render_intent_by_layout[layout_id] = render_intent

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
        if layout_id in render_intent_by_layout:
            job["render_intent"] = dict(render_intent_by_layout[layout_id])
        lfe_receipt = _build_lfe_receipt_for_target(
            target_layout_id=layout_id,
            channel_order=list(resolved_layouts_by_id[layout_id].get("channel_order") or []),
            scene=scene,
            layouts=layouts,
            lfe_derivation_profile_id=lfe_derivation_profile_id,
            lfe_mode=lfe_mode,
        )
        if isinstance(lfe_receipt, dict):
            job["lfe_receipt"] = lfe_receipt
        if resolved_target_id is not None and _coerce_str(resolved_target_id).strip():
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
    if loudness_profile_id:
        policies["loudness_profile_id"] = loudness_profile_id
    policies["lfe_derivation_profile_id"] = lfe_derivation_profile_id

    # Targets list sorted.
    all_target_ids = sorted(set(all_target_ids))
    resolved_layouts = [
        resolved_layouts_by_id[layout_id]
        for layout_id in sorted(resolved_layouts_by_id.keys())
    ]

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
