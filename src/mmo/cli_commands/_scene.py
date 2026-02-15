from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mmo.cli_commands._helpers import (
    _BASELINE_RENDER_TARGET_ID,
    _coerce_str,
    _load_json_object,
    _load_report,
    _load_timeline_payload,
    _validate_json_payload,
    _write_json_file,
)
from mmo.core.intent_params import load_intent_params, validate_scene_intent
from mmo.core.render_plan import build_render_plan
from mmo.core.render_plan_bridge import render_plan_to_variant_plan
from mmo.core.render_planner import build_render_plan as build_render_plan_from_request
from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    resolve_render_target_id,
)
from mmo.core.run_config import merge_run_config, normalize_run_config
from mmo.core.scene_editor import (
    INTENT_PARAM_KEY_TO_ID,
    add_lock as edit_scene_add_lock,
    remove_lock as edit_scene_remove_lock,
    set_intent as edit_scene_set_intent,
)
from mmo.core.scene_locks import get_scene_lock, list_scene_locks
from mmo.core.scene_templates import (
    apply_scene_templates,
    get_scene_template,
    list_scene_templates,
    preview_scene_templates,
)
from mmo.core.variants import run_variant_plan

__all__ = [
    "_render_scene_text",
    "_render_render_plan_text",
    "_build_validated_scene_payload",
    "_run_scene_build_command",
    "_validate_scene_schema",
    "_scene_intent_failure_payload",
    "_validate_scene_intent_rules",
    "_parse_scene_intent_cli_value",
    "_run_scene_locks_edit_command",
    "_run_scene_intent_set_command",
    "_apply_scene_templates_to_payload",
    "_run_scene_template_apply_command",
    "_sorted_preview_paths",
    "_format_preview_paths",
    "_render_scene_template_preview_text",
    "_run_scene_template_preview_command",
    "_build_scene_intent_show_payload",
    "_render_scene_intent_text",
    "_build_validated_render_plan_payload",
    "_run_render_plan_build_command",
    "_run_render_plan_from_request_command",
    "_run_render_plan_to_variants_command",
    "_apply_run_config_to_render_many_variant_plan",
    "_build_scene_lock_list_payload",
    "_build_scene_lock_show_payload",
    "_render_scene_lock_text",
    "_build_scene_template_list_payload",
    "_build_scene_template_show_payload",
    "_render_scene_template_text",
    "_parse_scene_template_ids_csv",
    "_parse_target_ids_csv",
    "_build_selected_render_targets_payload",
    "_default_render_plan_targets_payload",
    "_render_plan_policies_from_report",
]


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


def _run_render_plan_from_request_command(
    *,
    repo_root: Path,
    request_path: Path,
    scene_path: Path,
    routing_plan_path: Path | None,
    out_path: Path,
    force: bool,
) -> int:
    if out_path.exists() and not force:
        print(
            f"File exists (use --force to overwrite): {out_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    request_payload = _load_json_object(request_path, label="Render request")
    _validate_json_payload(
        request_payload,
        schema_path=repo_root / "schemas" / "render_request.schema.json",
        payload_name="Render request",
    )

    scene_payload = _load_json_object(scene_path, label="Scene")
    _validate_json_payload(
        scene_payload,
        schema_path=repo_root / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )
    scene_for_plan = json.loads(json.dumps(scene_payload))
    scene_for_plan["scene_path"] = scene_path.resolve().as_posix()

    routing_plan_payload: dict[str, Any] | None = None
    if routing_plan_path is not None:
        routing_plan_payload = _load_json_object(
            routing_plan_path, label="Routing plan",
        )
        _validate_json_payload(
            routing_plan_payload,
            schema_path=repo_root / "schemas" / "routing_plan.schema.json",
            payload_name="Routing plan",
        )
        routing_plan_payload = json.loads(json.dumps(routing_plan_payload))
        routing_plan_payload["routing_plan_path"] = (
            routing_plan_path.resolve().as_posix()
        )

    layouts: dict[str, Any] | None = None
    layouts_path = repo_root / "ontology" / "layouts.yaml"
    if layouts_path.is_file():
        from mmo.dsp.downmix import load_layouts  # noqa: WPS433

        layouts = load_layouts(layouts_path)

    render_targets_payload: dict[str, Any] | None = None
    render_targets_path = repo_root / "ontology" / "render_targets.yaml"
    if render_targets_path.is_file():
        from mmo.core.render_targets import load_render_targets  # noqa: WPS433

        render_targets_payload = load_render_targets(render_targets_path)

    render_plan_payload = build_render_plan_from_request(
        request_payload,
        scene_for_plan,
        routing_plan=routing_plan_payload,
        layouts=layouts,
        render_targets=render_targets_payload,
    )
    _validate_json_payload(
        render_plan_payload,
        schema_path=repo_root / "schemas" / "render_plan.schema.json",
        payload_name="Render plan",
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
