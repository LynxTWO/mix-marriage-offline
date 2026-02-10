from __future__ import annotations

import hashlib
import json
from typing import Any

from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS


RENDER_PLAN_SCHEMA_VERSION = "0.1.0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_CONTEXT_ORDER = ("render", "auto_apply")
_STEREO_TARGET_ID = "TARGET.STEREO.2_0"
_STEREO_LAYOUT_ID = "LAYOUT.2_0"


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


def _normalize_contexts(value: Any) -> list[str]:
    selected: set[str] = set()
    if isinstance(value, list):
        for item in value:
            normalized = _coerce_str(item).strip().lower()
            if normalized in _CONTEXT_ORDER:
                selected.add(normalized)
    if not selected:
        return ["render"]
    return [ctx for ctx in _CONTEXT_ORDER if ctx in selected]


def _target_rows(render_targets: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(render_targets, dict):
        return []

    targets = render_targets.get("targets")
    if isinstance(targets, list):
        return [item for item in targets if isinstance(item, dict)]

    if "target_id" in render_targets and "layout_id" in render_targets:
        return [render_targets]

    rows: list[dict[str, Any]] = []
    for key, value in render_targets.items():
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row.setdefault("target_id", key)
        rows.append(row)
    return rows


def _target_layout_id(row: dict[str, Any]) -> str:
    return _coerce_str(row.get("layout_id")).strip() or _coerce_str(
        row.get("target_layout_id")
    ).strip()


def _policy_from_targets(rows: list[dict[str, Any]], key: str) -> str | None:
    values: set[str] = set()
    for row in rows:
        normalized = _coerce_str(row.get(key)).strip()
        if normalized:
            values.add(normalized)
    if len(values) == 1:
        return next(iter(values))
    return None


def _scene_path(scene: dict[str, Any]) -> str:
    direct = _coerce_str(scene.get("scene_path")).strip()
    if direct:
        return direct
    source = scene.get("source")
    if isinstance(source, dict):
        stems_dir = _coerce_str(source.get("stems_dir")).strip()
        if stems_dir:
            return stems_dir
    return "scene.json"


def _scene_id(scene: dict[str, Any]) -> str:
    normalized = _coerce_str(scene.get("scene_id")).strip()
    if normalized:
        return normalized
    return "SCENE.UNKNOWN"


def _scene_source_layout_id(scene: dict[str, Any]) -> str | None:
    source = scene.get("source")
    if isinstance(source, dict):
        candidate = _coerce_str(source.get("layout_id")).strip()
        if candidate:
            return candidate
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        candidate = _coerce_str(metadata.get("source_layout_id")).strip()
        if candidate:
            return candidate
    return None


def _job_notes(
    *,
    target_id: str,
    target_layout_id: str,
    has_routing_plan: bool,
) -> list[str]:
    notes: list[str] = []
    if target_id == _STEREO_TARGET_ID or target_layout_id == _STEREO_LAYOUT_ID:
        notes.append("Stereo is a deliverable target for stereo")
    if has_routing_plan:
        notes.append("Routing applied")
    return notes


def _hash8(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def build_render_plan(
    scene: dict,
    render_targets: dict,
    *,
    routing_plan_path: str | None,
    output_formats: list[str],
    contexts: list[str],
    policies: dict | None,
) -> dict:
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")
    if not isinstance(render_targets, dict):
        raise ValueError("render_targets must be an object.")

    rows = _target_rows(render_targets)
    if not rows:
        raise ValueError("render_targets must include at least one target.")

    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        target_id = _coerce_str(row.get("target_id")).strip()
        target_layout_id = _target_layout_id(row)
        if not target_id or not target_layout_id:
            raise ValueError("Each render target must include target_id and layout_id.")
        normalized_rows.append(
            {
                "target_id": target_id,
                "target_layout_id": target_layout_id,
            }
        )
    normalized_rows.sort(key=lambda item: item["target_id"])

    output_formats_payload = _normalize_output_formats(output_formats)
    contexts_payload = _normalize_contexts(contexts)
    source_layout_id = _scene_source_layout_id(scene)
    normalized_routing_plan_path = _coerce_str(routing_plan_path).strip()

    jobs: list[dict[str, Any]] = []
    for index, row in enumerate(normalized_rows, start=1):
        target_id = row["target_id"]
        target_layout_id = row["target_layout_id"]
        routing_needed = (
            isinstance(source_layout_id, str)
            and bool(source_layout_id)
            and source_layout_id != target_layout_id
        )
        resolved_routing_plan_path = normalized_routing_plan_path
        if routing_needed and not resolved_routing_plan_path:
            resolved_routing_plan_path = "routing_plan.json"
        include_routing_plan = bool(resolved_routing_plan_path)

        job: dict[str, Any] = {
            "job_id": f"JOB.{index:03d}",
            "target_id": target_id,
            "target_layout_id": target_layout_id,
            "output_formats": list(output_formats_payload),
            "contexts": list(contexts_payload),
            "notes": _job_notes(
                target_id=target_id,
                target_layout_id=target_layout_id,
                has_routing_plan=include_routing_plan,
            ),
        }
        if include_routing_plan:
            job["routing_plan_path"] = resolved_routing_plan_path
        jobs.append(job)

    policies_payload: dict[str, str] = {}
    policy_source = policies if isinstance(policies, dict) else {}
    gates_policy_id = _coerce_str(policy_source.get("gates_policy_id")).strip()
    if not gates_policy_id:
        gates_policy_id = _coerce_str(policy_source.get("safety_policy_id")).strip()
    if not gates_policy_id:
        inferred = _policy_from_targets(rows, "safety_policy_id")
        if isinstance(inferred, str):
            gates_policy_id = inferred
    if gates_policy_id:
        policies_payload["gates_policy_id"] = gates_policy_id

    downmix_policy_id = _coerce_str(policy_source.get("downmix_policy_id")).strip()
    if not downmix_policy_id:
        downmix_policy_id = _coerce_str(policy_source.get("policy_id")).strip()
    if not downmix_policy_id:
        inferred = _policy_from_targets(rows, "downmix_policy_id")
        if isinstance(inferred, str):
            downmix_policy_id = inferred
    if downmix_policy_id:
        policies_payload["downmix_policy_id"] = downmix_policy_id

    scene_path = _scene_path(scene)
    targets_payload = [row["target_id"] for row in normalized_rows]

    plan_without_id = {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "scene_path": scene_path,
        "targets": targets_payload,
        "policies": policies_payload,
        "jobs": jobs,
    }
    plan_id = f"PLAN.{_scene_id(scene)}.{_hash8(plan_without_id)}"

    return {
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "scene_path": scene_path,
        "targets": targets_payload,
        "policies": policies_payload,
        "jobs": jobs,
    }
