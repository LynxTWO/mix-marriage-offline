"""Renderer, apply, bundle, and deliverables-index CLI helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mmo.core.progress import CancelToken, CancelledError, ProgressTracker, format_live_log_line
from mmo.resources import ontology_dir, schemas_dir

from mmo.core.deliverables_index import (
    build_deliverables_index_single,
    build_deliverables_index_variants,
)
from mmo.core.deliverables import summarize_deliverables
from mmo.core.deliverables import (
    RENDER_RESULT_NO_OUTPUT_ARTIFACT,
    RENDER_RESULT_NO_DECODABLE_STEMS,
    RENDER_RESULT_SILENT_OUTPUT,
)
from mmo.core.listen_pack import build_listen_pack
from mmo.core.render_clarity import (
    build_deliverable_summary_rows,
    build_result_summary,
    enrich_issue_for_user,
    enrich_issue_list_for_user,
)
from mmo.core.statuses import (
    LIFECYCLE_STATUS_BLOCKED,
    LIFECYCLE_STATUS_COMPLETED,
    LIFECYCLE_STATUS_DRY_RUN_ONLY,
)
from mmo.core.recommendations import (
    normalize_recommendation_contract,
    recommendation_requires_user_approval,
    recommendation_snapshot,
)
from mmo.core.portable_refs import (
    is_absolute_posix_path,
    portable_path_ref,
    resolve_posix_ref,
)
from mmo.core.routing import (
    apply_routing_plan_to_report,
    routing_layout_ids_from_run_config,
)
from mmo.core.run_config import normalize_run_config
from mmo.core.source_locator import resolve_session_stems
from mmo.core.target_tokens import resolve_target_token

from mmo.cli_commands._helpers import (
    _coerce_str,
    _load_json_object,
    _load_report,
    _validate_apply_manifest,
    _validate_json_payload,
    _validate_render_manifest,
    _write_json_file,
)

__all__ = [
    "_collect_stem_artifacts",
    "_build_applied_report",
    "_run_render_command",
    "_run_downmix_render",
    "_run_apply_command",
    "_run_safe_render_command",
    "_run_safe_render_demo",
    "_run_render_many_targets",
    "_RENDER_MANY_DEFAULT_TARGETS",
    "_DEMO_LAYOUT_STANDARDS",
    "_write_routing_plan_artifact",
    "_run_bundle",
    "_build_validated_listen_pack",
    "_build_validated_deliverables_index_single",
    "_build_validated_deliverables_index_variants",
    "_existing_file",
    "_run_deliverables_index_command",
]

ISSUE_RENDER_NO_OUTPUTS = "ISSUE.RENDER.NO_OUTPUTS"
ISSUE_RENDER_ALL_MASTERS_INVALID = "ISSUE.RENDER.ALL_MASTERS_INVALID"
_NO_OUTPUTS_WARNING_MESSAGE = (
    "No audio files were written. MMO finished the paperwork, but no renderer produced a bounce for this target."
)
_ALL_MASTERS_INVALID_MESSAGE = (
    "Rendered audio artifacts were written, but every master deliverable is invalid because no stems decoded or the result is effectively silent."
)
_FALLBACK_STEP_SEQUENCE = (
    "reduce_surround",
    "reduce_height",
    "reduce_decorrelation",
    "disable_wideners",
    "front_bias",
    "safety_collapse",
)
_PERSISTED_MANIFEST_PATH_FIELDS = frozenset(
    {
        "file_path",
        "resolved_path",
        "scene_source_path",
        "scene_locks_source_path",
        "source_path",
        "source_ref",
        "stereo_render_path",
        "surround_render_path",
    }
)
_PERSISTED_QA_PATH_FIELDS = frozenset({"input_path", "output_path", "path"})


def _format_list_preview(values: list[str], *, limit: int = 4) -> str:
    if not values:
        return ""
    preview = values[:limit]
    label = ", ".join(preview)
    if len(values) > limit:
        label = f"{label}, +{len(values) - limit} more"
    return label


def _plugin_safety_receipt_notes(
    manifests: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        renderer_id = _coerce_str(manifest.get("renderer_id")).strip() or "unknown_renderer"
        skipped_rows = manifest.get("skipped")
        if not isinstance(skipped_rows, list):
            continue
        for row in skipped_rows:
            if not isinstance(row, dict):
                continue
            reason = _coerce_str(row.get("reason")).strip()
            details = row.get("details")
            if not isinstance(details, dict):
                details = {}

            note = ""
            if reason == "plugin_scene_scope_restricted":
                note = (
                    f"Renderer {renderer_id} was limited to bed audio only, so MMO skipped "
                    "object-style material for safety."
                )
            elif reason == "plugin_scene_scope_unsupported":
                note = (
                    f"Renderer {renderer_id} was bypassed because this scene needs object-aware "
                    "placement and that renderer only supports bed audio."
                )
            elif reason == "plugin_layout_unsupported":
                target_layout_id = _coerce_str(details.get("target_layout_id")).strip()
                supported_layout_ids = [
                    _coerce_str(item).strip()
                    for item in details.get("supported_layout_ids", [])
                    if _coerce_str(item).strip()
                ]
                supported_label = _format_list_preview(supported_layout_ids)
                note = (
                    f"Renderer {renderer_id} was bypassed for safety because it does not support "
                    f"{target_layout_id or 'this target layout'}"
                )
                if supported_label:
                    note += f" (it declares support for {supported_label})."
                else:
                    note += "."
            elif reason == "plugin_layout_support_unknown":
                target_layout_id = _coerce_str(details.get("target_layout_id")).strip()
                note = (
                    f"Renderer {renderer_id} was bypassed because it is layout-specific and did "
                    f"not declare safe support for {target_layout_id or 'this target layout'}."
                )
            elif reason == "plugin_channel_limit":
                required_channels = details.get("required_channels")
                max_channels = details.get("max_channels")
                note = (
                    f"Renderer {renderer_id} was skipped because this scene needs "
                    f"{required_channels} channel(s), but that renderer is limited to "
                    f"{max_channels}."
                )

            if note and note not in seen:
                seen.add(note)
                notes.append(note)
    return notes


def _merged_render_export_options(
    *,
    session_payload: dict[str, Any],
    export_stems: bool,
    export_buses: bool,
    export_master: bool,
    export_layout_ids: list[str],
) -> dict[str, Any]:
    existing = session_payload.get("render_export_options")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(
        {
            "export_stems": bool(export_stems),
            "export_buses": bool(export_buses),
            "export_master": bool(export_master),
            "export_layout_ids": list(export_layout_ids),
        }
    )
    return merged


def _set_session_workspace_dir(report: dict[str, Any], *, workspace_dir: Path) -> None:
    session_payload = report.get("session")
    if not isinstance(session_payload, dict):
        return
    session_payload["workspace_dir"] = workspace_dir.resolve().as_posix()


def _portable_ref_for_workspace(
    value: Any,
    *,
    workspace_dir: Path | None,
    fallback: str | None = None,
) -> str | None:
    return portable_path_ref(
        value,
        anchor_dir=workspace_dir.resolve() if workspace_dir is not None else None,
        fallback=fallback,
    )


def _rewrite_nested_path_fields(
    value: Any,
    *,
    workspace_dir: Path | None,
    field_names: frozenset[str],
) -> Any:
    if isinstance(value, list):
        return [
            _rewrite_nested_path_fields(
                item,
                workspace_dir=workspace_dir,
                field_names=field_names,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    rewritten: dict[str, Any] = {}
    for key, item in value.items():
        if key in field_names and isinstance(item, str):
            rewritten[key] = _portable_ref_for_workspace(
                item,
                workspace_dir=workspace_dir,
                fallback=item,
            )
        else:
            rewritten[key] = _rewrite_nested_path_fields(
                item,
                workspace_dir=workspace_dir,
                field_names=field_names,
            )
    return rewritten


def _default_scene_binding_summary() -> dict[str, Any]:
    from mmo.core.scene_binding import default_scene_binding_summary  # noqa: WPS433

    return json.loads(json.dumps(default_scene_binding_summary()))


def _default_scene_stem_overlap_summary() -> dict[str, Any]:
    from mmo.core.preflight import default_scene_stem_overlap_summary  # noqa: WPS433

    return json.loads(json.dumps(default_scene_stem_overlap_summary()))


def _default_preflight_summary() -> dict[str, Any]:
    return {
        "final_decision": "not_run",
        "blocked_gates": [],
        "issues": [],
        "primary_issue_id": None,
        "primary_message": None,
        "scene_stem_overlap_summary": _default_scene_stem_overlap_summary(),
    }


def _portable_scene_binding_summary(
    scene_binding_summary: dict[str, Any] | None,
    *,
    workspace_dir: Path | None,
) -> dict[str, Any]:
    summary = (
        json.loads(json.dumps(scene_binding_summary))
        if isinstance(scene_binding_summary, dict)
        else _default_scene_binding_summary()
    )
    rewritten_refs = summary.get("rewritten_refs")
    if isinstance(rewritten_refs, list):
        for row in rewritten_refs:
            if not isinstance(row, dict):
                continue
            for key in ("from_ref",):
                value = row.get(key)
                if isinstance(value, str):
                    row[key] = _portable_ref_for_workspace(
                        value,
                        workspace_dir=workspace_dir,
                        fallback=value,
                    )
    binding_warnings = summary.get("binding_warnings")
    if isinstance(binding_warnings, list):
        for row in binding_warnings:
            if not isinstance(row, dict):
                continue
            stem_ref = row.get("stem_ref")
            if isinstance(stem_ref, str):
                row["stem_ref"] = _portable_ref_for_workspace(
                    stem_ref,
                    workspace_dir=workspace_dir,
                    fallback=stem_ref,
                )
            candidates = row.get("candidates")
            if isinstance(candidates, list):
                row["candidates"] = [
                    _portable_ref_for_workspace(
                        candidate,
                        workspace_dir=workspace_dir,
                        fallback=_coerce_str(candidate).strip() or None,
                    )
                    or _coerce_str(candidate).strip()
                    for candidate in candidates
                    if _coerce_str(candidate).strip()
                ]
    return summary


def _preflight_summary_from_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return _default_preflight_summary()

    issues = enrich_issue_list_for_user(
        [
            issue
            for issue in receipt.get("issues", [])
            if isinstance(issue, dict)
        ]
    )
    blocked_gates = sorted(
        {
            _coerce_str(gate.get("gate_id")).strip()
            for gate in receipt.get("gates_evaluated", [])
            if isinstance(gate, dict)
            and _coerce_str(gate.get("outcome")).strip() == "block"
            and _coerce_str(gate.get("gate_id")).strip()
        }
    )
    primary_issue = next(
        (
            issue
            for issue in issues
            if _coerce_str(issue.get("severity")).strip() == "error"
        ),
        issues[0] if issues else None,
    )
    scene_stem_overlap_summary = receipt.get("scene_stem_overlap_summary")
    if not isinstance(scene_stem_overlap_summary, dict):
        scene_stem_overlap_summary = _default_scene_stem_overlap_summary()

    return {
        "final_decision": _coerce_str(receipt.get("final_decision")).strip() or "not_run",
        "blocked_gates": blocked_gates,
        "issues": json.loads(json.dumps(issues)),
        "primary_issue_id": (
            _coerce_str(primary_issue.get("issue_id")).strip()
            if isinstance(primary_issue, dict)
            else None
        ) or None,
        "primary_message": (
            _coerce_str(primary_issue.get("message")).strip()
            if isinstance(primary_issue, dict)
            else None
        ) or None,
        "scene_stem_overlap_summary": json.loads(json.dumps(scene_stem_overlap_summary)),
    }


def _preflight_should_hard_stop_dry_run(preflight_summary: dict[str, Any]) -> bool:
    scene_overlap_summary = preflight_summary.get("scene_stem_overlap_summary")
    if not isinstance(scene_overlap_summary, dict):
        return False
    status = _coerce_str(scene_overlap_summary.get("status")).strip()
    return status in {"partial", "failed"}


def _portable_renderer_manifests(
    renderer_manifests: list[dict[str, Any]],
    *,
    workspace_dir: Path | None,
) -> list[dict[str, Any]]:
    return _rewrite_nested_path_fields(
        json.loads(json.dumps(renderer_manifests)),
        workspace_dir=workspace_dir,
        field_names=_PERSISTED_MANIFEST_PATH_FIELDS,
    )


def _deliverable_result_payload(
    deliverables: list[dict[str, Any]],
    *,
    fallback_status: str | None = None,
    fallback_failure_reason: str | None = None,
) -> dict[str, Any]:
    return summarize_deliverables(
        deliverables,
        fallback_status=fallback_status,
        fallback_failure_reason=fallback_failure_reason,
    )


def _deliverable_result_bucket(summary: dict[str, Any]) -> str:
    return _coerce_str(summary.get("result_bucket")).strip() or (
        _coerce_str(summary.get("overall_status")).strip() or "none"
    )


def _deliverable_top_failure_reason(summary: dict[str, Any]) -> str:
    return _coerce_str(summary.get("top_failure_reason")).strip()


def _artifact_result_details(
    *,
    renderer_manifests: list[dict[str, Any]],
    deliverables: list[dict[str, Any]],
    deliverables_summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Return both row-wise and concise summaries so manifests, receipts, smoke,
    # CLI, and desktop consumers can each load the surface they need without
    # rebuilding it from raw deliverables.
    summary_rows = build_deliverable_summary_rows(
        renderer_manifests=renderer_manifests,
        deliverables=deliverables,
    )
    result_summary = build_result_summary(
        deliverables_summary=deliverables_summary,
        deliverable_summary_rows=summary_rows,
    )
    return summary_rows, result_summary


def _master_deliverables_invalid_for_safe_render(
    deliverables: list[dict[str, Any]],
) -> bool:
    master_deliverables = [
        deliverable
        for deliverable in deliverables
        if isinstance(deliverable, dict)
        and _coerce_str(deliverable.get("artifact_role")).strip().lower() == "master"
    ]
    if not master_deliverables:
        return False

    for deliverable in master_deliverables:
        status = _coerce_str(deliverable.get("status")).strip().lower()
        if status not in {"failed", "invalid_master"}:
            return False
        failure_reason = _coerce_str(deliverable.get("failure_reason")).strip()
        warning_codes = deliverable.get("warning_codes")
        normalized_warning_codes = (
            {
                _coerce_str(item).strip()
                for item in warning_codes
                if isinstance(item, str) and _coerce_str(item).strip()
            }
            if isinstance(warning_codes, list)
            else set()
        )
        if failure_reason not in {
            RENDER_RESULT_NO_DECODABLE_STEMS,
            RENDER_RESULT_SILENT_OUTPUT,
        } and not normalized_warning_codes.intersection(
            {RENDER_RESULT_NO_DECODABLE_STEMS, RENDER_RESULT_SILENT_OUTPUT}
        ):
            return False
    return True


def _build_all_masters_invalid_issue(
    *,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    issue = {
        "issue_id": ISSUE_RENDER_ALL_MASTERS_INVALID,
        "severity": "error",
        "message": _ALL_MASTERS_INVALID_MESSAGE,
        "metric": "valid_master_count",
        "value": 0,
        "threshold": 1,
    }
    normalized_failure_reason = _coerce_str(failure_reason).strip()
    if normalized_failure_reason:
        issue["failure_reason"] = normalized_failure_reason
    return enrich_issue_for_user(issue)


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
    resolve_session_stems(session, mutate=True)
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
    from mmo.core.binaural_target import (  # noqa: WPS433
        build_binaural_target_manifests,
        choose_binaural_source_layout,
        is_binaural_layout,
    )
    from mmo.core.gates import apply_gates_to_report  # noqa: WPS433
    from mmo.core.precedence import apply_recommendation_precedence  # noqa: WPS433
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_renderers,
    )

    report = _load_report(report_path)
    workspace_dir = report_path.parent.resolve()
    _set_session_workspace_dir(report, workspace_dir=report_path.parent)
    normalized_run_config: dict[str, Any] | None = None
    if run_config is not None:
        # Normalize and stamp routing before gates run so renderer-side
        # eligibility is judged against the same layout contract that will be
        # rendered.
        normalized_run_config = normalize_run_config(run_config)
        report["run_config"] = normalized_run_config
        if routing_layout_ids_from_run_config(normalized_run_config) is not None:
            apply_routing_plan_to_report(report, normalized_run_config)
    apply_gates_to_report(
        report,
        policy_path=ontology_dir() /"policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=ontology_dir() /"policies" / "authority_profiles.yaml",
    )

    recommendations = report.get("recommendations")
    recs: list[dict[str, Any]] = []
    if isinstance(recommendations, list):
        recs = [rec for rec in recommendations if isinstance(rec, dict)]
    session = report.get("session")
    scene_payload = (
        session.get("scene_payload")
        if isinstance(session, dict)
        else None
    )
    if not isinstance(scene_payload, dict) and isinstance(session, dict):
        candidate_scene = session.get("scene")
        if isinstance(candidate_scene, dict):
            scene_payload = candidate_scene
    if isinstance(scene_payload, dict):
        # Renderers inherit the already-chosen scene authority. Precedence does
        # not rerun here; it only constrains which gated recs can still render.
        apply_recommendation_precedence(scene_payload, recs)

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

    downmix_cfg = (
        normalized_run_config.get("downmix")
        if isinstance(normalized_run_config, dict)
        else None
    )
    target_layout_id = (
        _coerce_str(downmix_cfg.get("target_layout_id")).strip()
        if isinstance(downmix_cfg, dict)
        else ""
    )
    source_layout_hint = (
        _coerce_str(downmix_cfg.get("source_layout_id")).strip()
        if isinstance(downmix_cfg, dict)
        else ""
    )
    binaural_target_requested = is_binaural_layout(target_layout_id)
    renderer_output_formats = ["wav"] if binaural_target_requested else output_formats

    manifests = run_renderers(
        report,
        plugins,
        output_dir=out_dir,
        output_formats=renderer_output_formats,
    )
    if binaural_target_requested:
        render_cfg = (
            normalized_run_config.get("render")
            if isinstance(normalized_run_config, dict)
            else None
        )
        layout_standard = (
            _coerce_str(render_cfg.get("layout_standard")).strip().upper()
            if isinstance(render_cfg, dict)
            else ""
        ) or "SMPTE"
        source_selection = choose_binaural_source_layout(
            report=report,
            source_layout_id_hint=source_layout_hint or None,
        )
        manifests, _ = build_binaural_target_manifests(
            renderer_manifests=manifests,
            output_dir=out_dir,
            layout_standard=layout_standard,
            source_layout_id=source_selection.source_layout_id,
            output_formats=output_formats,
        )
    deliverables = build_deliverables_for_renderer_manifests(manifests)
    deliverables_summary = _deliverable_result_payload(deliverables)
    persisted_manifests = _portable_renderer_manifests(
        manifests,
        workspace_dir=workspace_dir,
    )
    deliverable_summary_rows, result_summary = _artifact_result_details(
        renderer_manifests=persisted_manifests,
        deliverables=deliverables,
        deliverables_summary=deliverables_summary,
    )
    render_manifest = {
        "schema_version": "0.1.0",
        "report_id": report.get("report_id", ""),
        "renderer_manifests": persisted_manifests,
        "scene_binding_summary": _default_scene_binding_summary(),
        "deliverables_summary": deliverables_summary,
        "deliverable_summary_rows": deliverable_summary_rows,
        "result_summary": result_summary,
    }
    render_manifest["deliverables"] = deliverables
    _validate_render_manifest(
        render_manifest,
        schemas_dir() /"render_manifest.schema.json",
    )

    out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_manifest_path.write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "render:"
        f" result={_deliverable_result_bucket(deliverables_summary)}"
        f" overall_status={_coerce_str(deliverables_summary.get('overall_status')).strip() or 'none'}"
        f" deliverables={deliverables_summary.get('deliverable_count', 0)}"
        f" success={deliverables_summary.get('success_count', 0)}"
        f" partial={deliverables_summary.get('partial_count', 0)}"
        f" failed={deliverables_summary.get('failed_count', 0)}"
        f" invalid_master={deliverables_summary.get('invalid_master_count', 0)}"
        + (
            f" top_failure_reason={_deliverable_top_failure_reason(deliverables_summary)}"
            if _deliverable_top_failure_reason(deliverables_summary)
            else ""
        ),
        file=sys.stderr,
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
        repo_root=None,
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
    from mmo.core.precedence import apply_recommendation_precedence  # noqa: WPS433
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_renderers,
    )

    report = _load_report(report_path)
    _set_session_workspace_dir(report, workspace_dir=report_path.parent)
    if run_config is not None:
        # Apply the same normalized routing contract here that render and
        # compare flows see, or auto-apply can stamp a stale layout plan.
        normalized_run_config = normalize_run_config(run_config)
        report["run_config"] = normalized_run_config
        if routing_layout_ids_from_run_config(normalized_run_config) is not None:
            apply_routing_plan_to_report(report, normalized_run_config)
    apply_gates_to_report(
        report,
        policy_path=ontology_dir() /"policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=ontology_dir() /"policies" / "authority_profiles.yaml",
    )

    recommendations = report.get("recommendations")
    recs: list[dict[str, Any]] = []
    if isinstance(recommendations, list):
        recs = [rec for rec in recommendations if isinstance(rec, dict)]
    session_payload = report.get("session")
    scene_payload = (
        session_payload.get("scene_payload")
        if isinstance(session_payload, dict)
        else None
    )
    if not isinstance(scene_payload, dict) and isinstance(session_payload, dict):
        candidate_scene = session_payload.get("scene")
        if isinstance(candidate_scene, dict):
            scene_payload = candidate_scene
    if isinstance(scene_payload, dict):
        # Auto-apply uses the same locked scene authority as render. A rec that
        # survives gates can still stay visible here while hard locks block it.
        apply_recommendation_precedence(scene_payload, recs)

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
    deliverables_summary = _deliverable_result_payload(deliverables)
    deliverable_summary_rows, result_summary = _artifact_result_details(
        renderer_manifests=renderer_manifests,
        deliverables=deliverables,
        deliverables_summary=deliverables_summary,
    )
    apply_manifest = {
        "schema_version": "0.1.0",
        "context": "auto_apply",
        "report_id": report.get("report_id", ""),
        "renderer_manifests": renderer_manifests,
        "deliverables_summary": deliverables_summary,
        "deliverable_summary_rows": deliverable_summary_rows,
        "result_summary": result_summary,
    }
    apply_manifest["deliverables"] = deliverables
    _validate_apply_manifest(
        apply_manifest,
        schemas_dir() /"apply_manifest.schema.json",
    )

    out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_manifest_path.write_text(
        json.dumps(apply_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "apply:"
        f" result={_deliverable_result_bucket(deliverables_summary)}"
        f" overall_status={_coerce_str(deliverables_summary.get('overall_status')).strip() or 'none'}"
        f" deliverables={deliverables_summary.get('deliverable_count', 0)}"
        f" success={deliverables_summary.get('success_count', 0)}"
        f" partial={deliverables_summary.get('partial_count', 0)}"
        f" failed={deliverables_summary.get('failed_count', 0)}"
        f" invalid_master={deliverables_summary.get('invalid_master_count', 0)}"
        + (
            f" top_failure_reason={_deliverable_top_failure_reason(deliverables_summary)}"
            if _deliverable_top_failure_reason(deliverables_summary)
            else ""
        ),
        file=sys.stderr,
    )

    if out_report_path is not None:
        applied_report = _build_applied_report(
            report,
            out_dir=out_dir,
            renderer_manifests=renderer_manifests,
        )
        _write_json_file(out_report_path, applied_report)

    return 0


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
        schema_path=schemas_dir() /"routing_plan.schema.json",
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
    render_request_path: Path | None = None,
    render_execute_path: Path | None = None,
    render_report_path: Path | None = None,
    event_log_path: Path | None = None,
    render_preflight_path: Path | None = None,
    include_plugins: bool = False,
    include_plugin_layouts: bool = False,
    include_plugin_layout_snapshots: bool = False,
    include_plugin_ui_hints: bool = False,
    plugins_dir: Path | None = None,
) -> int:
    from mmo.core.ui_bundle import build_ui_bundle  # noqa: WPS433

    if include_plugin_layout_snapshots and not include_plugin_layouts:
        raise ValueError(
            "--include-plugin-layout-snapshots requires --include-plugin-layouts."
        )
    if (include_plugin_layouts or include_plugin_layout_snapshots) and not include_plugins:
        raise ValueError(
            "--include-plugin-layouts requires --include-plugins."
        )
    if include_plugin_ui_hints and not include_plugins:
        raise ValueError(
            "--include-plugin-ui-hints requires --include-plugins."
        )

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
    plugins_payload: dict[str, Any] | None = None
    if include_plugins:
        from mmo.core.plugin_schema_index import (  # noqa: WPS433
            build_plugins_config_schema_index,
        )

        normalized_plugins_dir = plugins_dir if plugins_dir is not None else Path("plugins")
        plugins_payload = build_plugins_config_schema_index(
            plugins_dir=normalized_plugins_dir,
            include_schema=False,
            include_ui_layout=include_plugin_layouts,
            include_ui_layout_snapshot=include_plugin_layout_snapshots,
            include_ui_hints=include_plugin_ui_hints,
        )

    bundle = build_ui_bundle(
        report,
        render_manifest,
        apply_manifest=apply_manifest,
        applied_report=applied_report,
        help_registry_path=ontology_dir() /"help.yaml",
        ui_copy_path=ontology_dir() /"ui_copy.yaml",
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
        render_request_path=render_request_path,
        render_plan_artifact_path=render_plan_path,
        render_execute_path=render_execute_path,
        render_preflight_path=render_preflight_path,
        render_report_path=render_report_path,
        event_log_path=event_log_path,
        plugins=plugins_payload,
    )
    _validate_json_payload(
        bundle,
        schema_path=schemas_dir() /"ui_bundle.schema.json",
        payload_name="UI bundle",
    )
    _write_json_file(out_path, bundle)
    return 0


def _build_validated_listen_pack(
    *,
    repo_root: Path,
    presets_dir: Path,
    variant_result: dict[str, Any],
) -> dict[str, Any]:
    listen_pack = build_listen_pack(variant_result, presets_dir)
    _validate_json_payload(
        listen_pack,
        schema_path=schemas_dir() /"listen_pack.schema.json",
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
        schema_path=schemas_dir() /"deliverables_index.schema.json",
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
        schema_path=schemas_dir() /"deliverables_index.schema.json",
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
                repo_root=None,
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
                repo_root=None,
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


# ---------------------------------------------------------------------------
# Safe-render: full plugin-chain (detect → resolve → gate → render) with
# bounded authority and safe-run receipt.
# ---------------------------------------------------------------------------

_RENDER_MANY_DEFAULT_TARGETS: list[str] = ["stereo", "5.1", "7.1.4"]


def _check_cancel_requested(
    *,
    cancel_token: CancelToken,
    cancel_file: Path | None,
) -> None:
    if cancel_file is not None:
        try:
            if cancel_file.exists():
                cancel_token.cancel(
                    f"cancel requested via {cancel_file.resolve().as_posix()}"
                )
        except OSError:
            pass
    cancel_token.raise_if_cancelled()


def _new_safe_render_progress(
    *,
    total_steps: int,
    cancel_token: CancelToken,
    live_progress: bool,
) -> ProgressTracker:
    if not live_progress:
        return ProgressTracker(total_steps=total_steps, cancel_token=cancel_token)

    def _live_logger(event: Any) -> None:
        print(format_live_log_line(event), file=sys.stderr)

    return ProgressTracker(
        total_steps=total_steps,
        cancel_token=cancel_token,
        log_listener=_live_logger,
    )


def _run_render_many_targets(
    *,
    render_many_targets: list[str],
    repo_root: Path,
    report_path: Path,
    plugins_dir: Path,
    out_dir: Path | None,
    receipt_out_path: Path | None,
    qa_out_path: Path | None,
    profile_id: str,
    dry_run: bool,
    approve: str | None,
    approve_rec_ids: list[str] | None,
    approve_file: Path | None,
    output_formats: list[str] | None = None,
    run_config: dict[str, Any] | None = None,
    force: bool = False,
    user_profile: dict[str, Any] | None = None,
    layout_standard: str = "SMPTE",
    preview_headphones: bool = False,
    allow_empty_outputs: bool = False,
    export_stems: bool = False,
    export_buses: bool = False,
    export_master: bool = True,
    export_layouts: list[str] | None = None,
    live_progress: bool = False,
    cancel_file: Path | None = None,
    cancel_token: CancelToken | None = None,
    scene_path: Path | None = None,
    scene_locks_path: Path | None = None,
    scene_strict: bool = False,
) -> int:
    """Run safe-render for multiple targets in parallel (mix-once, render-many).

    Each target gets its own sub-directory under ``out_dir`` and per-target
    receipt / manifest files.  Returns 0 only when every target succeeds.
    """
    import concurrent.futures  # noqa: WPS433
    token = cancel_token or CancelToken()
    _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)

    targets_raw = (
        render_many_targets
        if render_many_targets
        else _RENDER_MANY_DEFAULT_TARGETS
    )
    targets: list[str] = []
    for raw_target in targets_raw:
        normalized_target = _coerce_str(raw_target).strip()
        if not normalized_target:
            continue
        # Validate every token using the shared resolver before launching jobs.
        resolve_target_token(normalized_target)
        targets.append(normalized_target)
    if not targets:
        raise ValueError("--render-many-targets must include at least one target token.")
    print(
        f"safe-render/render-many: targets={','.join(targets)}",
        file=sys.stderr,
    )

    def _run_one(tgt: str) -> tuple[str, int]:
        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        tgt_slug = tgt.replace(".", "_").replace(" ", "_")
        tgt_out_dir = (out_dir / tgt_slug) if out_dir is not None else None
        tgt_manifest = (
            tgt_out_dir / "render_manifest.json" if tgt_out_dir is not None else None
        )
        tgt_receipt = (
            receipt_out_path.parent / f"receipt.{tgt_slug}.json"
            if receipt_out_path is not None
            else None
        )
        tgt_qa = (
            qa_out_path.parent / f"qa.{tgt_slug}.json"
            if qa_out_path is not None
            else None
        )
        rc = _run_safe_render_command(
            repo_root=repo_root,
            report_path=report_path,
            plugins_dir=plugins_dir,
            out_dir=tgt_out_dir,
            out_manifest_path=tgt_manifest,
            receipt_out_path=tgt_receipt,
            qa_out_path=tgt_qa,
            profile_id=profile_id,
            target=tgt,
            dry_run=dry_run,
            approve=approve,
            approve_rec_ids=approve_rec_ids,
            approve_file=approve_file,
            output_formats=output_formats,
            run_config=run_config,
            force=force,
            user_profile=user_profile,
            render_many_targets=None,  # do not recurse
            layout_standard=layout_standard,
            preview_headphones=preview_headphones,
            allow_empty_outputs=allow_empty_outputs,
            export_stems=export_stems,
            export_buses=export_buses,
            export_master=export_master,
            export_layouts=export_layouts,
            live_progress=live_progress,
            cancel_file=cancel_file,
            cancel_token=token,
            scene_path=scene_path,
            scene_locks_path=scene_locks_path,
            scene_strict=scene_strict,
        )
        return tgt, rc

    results: list[tuple[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(targets), thread_name_prefix="render_many"
    ) as pool:
        futures = {pool.submit(_run_one, tgt): tgt for tgt in sorted(targets)}
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                tgt = futures[fut]
                print(
                    f"safe-render/render-many: target={tgt} raised {exc}",
                    file=sys.stderr,
                )
                results.append((tgt, 1))
            _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)

    # Sort after the futures finish so parallel completion order does not
    # reshuffle the summary output.
    results.sort(key=lambda r: r[0])
    if token.is_cancelled:
        return 130
    failed = [tgt for tgt, rc in results if rc != 0]
    succeeded = [tgt for tgt, rc in results if rc == 0]
    if any(rc == 130 for _, rc in results):
        return 130
    print(
        f"safe-render/render-many: completed"
        f" succeeded={len(succeeded)}"
        f" failed={len(failed)}"
        f"{' failed_targets=' + ','.join(failed) if failed else ''}",
        file=sys.stderr,
    )
    return 0 if not failed else 1


def _parse_approve_arg(approve_arg: str | None) -> tuple[bool, set[str]]:
    """Parse the legacy --approve argument."""
    if approve_arg is None:
        return False, set()
    stripped = approve_arg.strip()
    normalized = stripped.lower()
    if normalized in {"", "none"}:
        return False, set()
    if normalized == "all":
        return True, set()
    return False, {part.strip() for part in approve_arg.split(",") if part.strip()}


def _load_approved_ids_from_file(approve_file: Path | None) -> set[str]:
    if approve_file is None:
        return set()
    payload = json.loads(approve_file.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        source = payload
    elif isinstance(payload, dict) and isinstance(payload.get("recommendation_ids"), list):
        source = payload["recommendation_ids"]
    else:
        raise ValueError("--approve-file must be a JSON list of recommendation_id values.")
    return {
        _coerce_str(item).strip()
        for item in source
        if _coerce_str(item).strip()
    }


def _collect_approval_inputs(
    *,
    approve: str | None,
    approve_rec_ids: list[str] | None,
    approve_file: Path | None,
) -> tuple[bool, set[str], list[str]]:
    approve_all, legacy_ids = _parse_approve_arg(approve)
    explicit_ids = set(legacy_ids)
    if isinstance(approve_rec_ids, list):
        explicit_ids.update(
            _coerce_str(rec_id).strip()
            for rec_id in approve_rec_ids
            if _coerce_str(rec_id).strip()
        )
    explicit_ids.update(_load_approved_ids_from_file(approve_file))

    raw_inputs: list[str] = []
    if approve_all:
        raw_inputs.append("all")
    raw_inputs.extend(sorted(explicit_ids))
    return approve_all, explicit_ids, raw_inputs


def _has_hard_precedence_conflict(rec: dict[str, Any]) -> bool:
    precedence_conflicts = rec.get("precedence_conflicts")
    if not isinstance(precedence_conflicts, list):
        return False
    return any(
        isinstance(conflict, dict)
        and _coerce_str(conflict.get("severity")).strip().lower() == "hard"
        for conflict in precedence_conflicts
    )


def _blocked_by_non_approval_gate(rec: dict[str, Any]) -> bool:
    approval_reason_ids = {
        "REASON.APPROVAL_REQUIRED",
        "REASON.SPATIAL_LOCK_OR_APPROVAL_REQUIRED",
    }
    gate_results = rec.get("gate_results")
    if not isinstance(gate_results, list):
        return False
    for result in gate_results:
        if not isinstance(result, dict):
            continue
        if _coerce_str(result.get("context")).strip().lower() != "render":
            continue
        if _coerce_str(result.get("outcome")).strip().lower() == "allow":
            continue
        if _coerce_str(result.get("reason_id")).strip() not in approval_reason_ids:
            return True
    return False


def _apply_approve_overrides(
    recs: list[dict[str, Any]],
    *,
    approve_all: bool,
    approved_ids: set[str],
) -> list[dict[str, Any]]:
    """Mutate eligible_render=True for approval-gated recs explicitly approved by the user."""
    approved_recs: list[dict[str, Any]] = []
    for rec in recs:
        rec["approved_by_user"] = False
        if _has_hard_precedence_conflict(rec):
            continue
        if rec.get("eligible_render") is True:
            continue
        if not recommendation_requires_user_approval(rec):
            continue
        if _blocked_by_non_approval_gate(rec):
            continue

        rec_id = _coerce_str(rec.get("recommendation_id")).strip()
        issue_id = _coerce_str(rec.get("issue_id")).strip()
        if not approve_all and rec_id not in approved_ids and issue_id not in approved_ids:
            continue

        rec["eligible_render"] = True
        rec["approved_by_user"] = True
        approved_recs.append(rec)
    return approved_recs


def _build_receipt_id(report_id: str, target: str) -> str:
    import hashlib  # noqa: WPS433
    digest = hashlib.sha256(
        f"{report_id}:{target}".encode("utf-8")
    ).hexdigest()
    return f"RECEIPT.SAFE_RENDER.{digest[:16].upper()}"


def _resolve_export_layout_ids(export_layouts: list[str] | None) -> list[str]:
    if not export_layouts:
        return []
    layout_ids: set[str] = set()
    for raw_token in export_layouts:
        token = _coerce_str(raw_token).strip()
        if not token:
            continue
        resolved_target = resolve_target_token(token)
        layout_id = _coerce_str(resolved_target.layout_id).strip()
        if layout_id:
            layout_ids.add(layout_id)
    return sorted(layout_ids)


def _collect_output_entries_from_manifests(
    manifests: list[dict[str, Any]],
    out_dir: Path | None,
    workspace_dir: Path | None,
) -> list[dict[str, Any]]:
    """Collect rendered output files info for QA analysis."""
    entries: list[dict[str, Any]] = []
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            file_path_str = _coerce_str(output.get("file_path"))
            sha256_val = _coerce_str(output.get("sha256"))
            channels_raw = output.get("channel_count")
            sample_rate_raw = output.get("sample_rate_hz")
            channels = (
                int(channels_raw)
                if isinstance(channels_raw, int) and channels_raw > 0
                else 0
            )
            sample_rate_hz = (
                int(sample_rate_raw)
                if isinstance(sample_rate_raw, int) and sample_rate_raw > 0
                else 0
            )
            if not file_path_str or not sha256_val:
                continue
            analysis_path = file_path_str
            portable_path = file_path_str
            if out_dir is not None and not is_absolute_posix_path(file_path_str):
                resolved = resolve_posix_ref(file_path_str, anchor_dir=out_dir.resolve())
                analysis_path = resolved.as_posix()
                portable_path = (
                    _portable_ref_for_workspace(
                        analysis_path,
                        workspace_dir=workspace_dir,
                        fallback=file_path_str,
                    )
                    or file_path_str
                )
            elif is_absolute_posix_path(file_path_str):
                portable_path = (
                    _portable_ref_for_workspace(
                        file_path_str,
                        workspace_dir=workspace_dir,
                        fallback=file_path_str,
                    )
                    or file_path_str
                )
            entries.append(
                {
                    "analysis_path": analysis_path,
                    "path": portable_path,
                    "sha256": sha256_val,
                    "channels": channels,
                    "sample_rate_hz": sample_rate_hz,
                }
            )
    return entries


def _count_manifest_outputs(manifests: list[dict[str, Any]]) -> int:
    output_count = 0
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        output_count += sum(1 for output in outputs if isinstance(output, dict))
    return output_count


def _build_no_outputs_issue(
    *,
    out_dir: Path | None,
    workspace_dir: Path | None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "issue_id": ISSUE_RENDER_NO_OUTPUTS,
        "severity": "warn",
        "message": _NO_OUTPUTS_WARNING_MESSAGE,
        "metric": "output_count",
        "value": 0,
        "threshold": 1,
        "failure_reason": RENDER_RESULT_NO_OUTPUT_ARTIFACT,
    }
    if out_dir is not None:
        issue["output_path"] = _portable_ref_for_workspace(
            out_dir.resolve().as_posix(),
            workspace_dir=workspace_dir,
            fallback="render",
        )
    return enrich_issue_for_user(issue)


def _default_fallback_final(*, final_outcome: str) -> dict[str, Any]:
    return {
        "applied_steps": [],
        "final_outcome": final_outcome,
        "safety_collapse_applied": False,
        "passed_layout_ids": [],
        "failed_layout_ids": [],
    }


def _fallback_step_sort_key(step_id: str) -> tuple[int, str]:
    normalized = _coerce_str(step_id).strip()
    if normalized in _FALLBACK_STEP_SEQUENCE:
        return (_FALLBACK_STEP_SEQUENCE.index(normalized), normalized)
    return (len(_FALLBACK_STEP_SEQUENCE), normalized)


def _output_similarity_metadata(output: dict[str, Any]) -> dict[str, Any] | None:
    metadata = output.get("metadata")
    if not isinstance(metadata, dict):
        return None
    similarity = metadata.get("downmix_similarity_qa")
    if isinstance(similarity, dict):
        return similarity
    return None


def _collect_fallback_reporting(
    *,
    manifests: list[dict[str, Any]],
    out_dir: Path | None,
    workspace_dir: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    applied_steps: list[str] = []
    seen_steps: set[str] = set()
    passed_layout_ids: list[str] = []
    failed_layout_ids: list[str] = []
    layout_summaries: list[dict[str, Any]] = []
    safety_collapse_applied = False
    saw_similarity_checks = False
    saw_fallback_applied = False
    issues: list[dict[str, Any]] = []

    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            similarity = _output_similarity_metadata(output)
            if not isinstance(similarity, dict):
                continue
            saw_similarity_checks = True
            layout_id = (
                _coerce_str(similarity.get("source_layout_id")).strip()
                or _coerce_str(output.get("layout_id")).strip()
            )
            output_path = _coerce_str(output.get("file_path")).strip()
            if output_path and out_dir is not None:
                output_path = (
                    _portable_ref_for_workspace(
                        (out_dir / output_path).resolve().as_posix(),
                        workspace_dir=workspace_dir,
                        fallback=output_path,
                    )
                    or output_path
                )
            fallback_attempts = similarity.get("fallback_attempts")
            if isinstance(fallback_attempts, list):
                for attempt in fallback_attempts:
                    if not isinstance(attempt, dict):
                        continue
                    row = json.loads(json.dumps(attempt))
                    if layout_id and not _coerce_str(row.get("layout_id")).strip():
                        row["layout_id"] = layout_id
                    attempts.append(row)
            fallback_final = similarity.get("fallback_final")
            if isinstance(fallback_final, dict):
                applied = fallback_final.get("applied_steps")
                if isinstance(applied, list):
                    for raw_step in applied:
                        step_id = _coerce_str(raw_step).strip()
                        if step_id and step_id not in seen_steps:
                            seen_steps.add(step_id)
                            applied_steps.append(step_id)
                if fallback_final.get("safety_collapse_applied") is True:
                    safety_collapse_applied = True
                summary = {"layout_id": layout_id} if layout_id else {}
                for key in ("final_outcome", "stop_reason", "applied_steps"):
                    if key in fallback_final:
                        summary[key] = fallback_final[key]
                if summary:
                    layout_summaries.append(summary)
            if similarity.get("fallback_applied") is True:
                saw_fallback_applied = True
            if similarity.get("passed") is True:
                if layout_id:
                    passed_layout_ids.append(layout_id)
                continue
            if layout_id:
                failed_layout_ids.append(layout_id)
            still_failed_after_safety_collapse = bool(
                isinstance(fallback_final, dict)
                and fallback_final.get("safety_collapse_applied") is True
            )
            issue: dict[str, Any] = {
                "issue_id": "ISSUE.DOWNMIX.QA.SIMILARITY_GATE_FAILED",
                "severity": "error",
                "message": (
                    (
                        "Rendered surround similarity gate still failed after safety collapse "
                        f"for {layout_id or 'unknown_layout'}."
                    )
                    if still_failed_after_safety_collapse
                    else (
                        "Rendered surround similarity gate failed after deterministic fallback "
                        f"for {layout_id or 'unknown_layout'}."
                    )
                ),
                "metric": "downmix_similarity_gate",
                "value": "fail",
                "threshold": "pass",
            }
            if layout_id:
                issue["layout_id"] = layout_id
            if output_path:
                issue["output_path"] = output_path
            issues.append(issue)

    final_outcome = "not_run"
    if failed_layout_ids:
        final_outcome = "fail"
    elif safety_collapse_applied:
        final_outcome = "pass_with_safety_collapse"
    elif saw_fallback_applied:
        final_outcome = "pass"
    elif saw_similarity_checks:
        final_outcome = "not_needed"

    attempts.sort(
        key=lambda row: (
            _coerce_str(row.get("layout_id")).strip(),
            _fallback_step_sort_key(_coerce_str(row.get("step_id")).strip()),
            _coerce_str(row.get("result")).strip(),
        )
    )
    ordered_applied_steps = sorted(set(applied_steps), key=_fallback_step_sort_key)

    fallback_final: dict[str, Any] = {
        "applied_steps": ordered_applied_steps,
        "final_outcome": final_outcome,
        "safety_collapse_applied": safety_collapse_applied,
        "passed_layout_ids": sorted(set(passed_layout_ids)),
        "failed_layout_ids": sorted(set(failed_layout_ids)),
    }
    if layout_summaries:
        fallback_final["layouts"] = sorted(
            layout_summaries,
            key=lambda row: (
                _coerce_str(row.get("layout_id")).strip(),
                _coerce_str(row.get("final_outcome")).strip(),
            ),
        )
    return attempts, fallback_final, issues


def _build_blocked_rec_summaries(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked = [rec for rec in recs if rec.get("eligible_render") is not True]
    return [recommendation_snapshot(rec) for rec in blocked]


def _build_eligible_rec_summaries(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [rec for rec in recs if rec.get("eligible_render") is True]
    return [recommendation_snapshot(rec) for rec in eligible]


def _build_applied_rec_summaries(
    recs: list[dict[str, Any]],
    manifests: list[dict[str, Any]],
    *,
    extra_received_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    received_ids: set[str] = set()
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        raw_received_ids = manifest.get("received_recommendation_ids")
        if not isinstance(raw_received_ids, list):
            continue
        for raw_id in raw_received_ids:
            rec_id = _coerce_str(raw_id).strip()
            if rec_id:
                received_ids.add(rec_id)
    for raw_id in extra_received_ids or []:
        rec_id = _coerce_str(raw_id).strip()
        if rec_id:
            received_ids.add(rec_id)

    applied = [
        rec
        for rec in recs
        if rec.get("eligible_render") is True
        and _coerce_str(rec.get("recommendation_id")).strip() in received_ids
    ]
    return [recommendation_snapshot(rec) for rec in applied]


def _output_channel_order(output: dict[str, Any]) -> list[str]:
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        channel_order = metadata.get("channel_order")
        if isinstance(channel_order, list):
            normalized = [
                _coerce_str(item).strip()
                for item in channel_order
                if _coerce_str(item).strip()
            ]
            if normalized:
                return normalized
        layout_id = _coerce_str(metadata.get("layout_id")).strip()
        if layout_id:
            from mmo.core.layout_negotiation import get_layout_channel_order  # noqa: WPS433

            layout_channel_order = get_layout_channel_order(layout_id)
            if isinstance(layout_channel_order, list):
                return [
                    _coerce_str(item).strip()
                    for item in layout_channel_order
                    if _coerce_str(item).strip()
                ]

    layout_id = _coerce_str(output.get("layout_id")).strip()
    if layout_id:
        from mmo.core.layout_negotiation import get_layout_channel_order  # noqa: WPS433

        layout_channel_order = get_layout_channel_order(layout_id)
        if isinstance(layout_channel_order, list):
            return [
                _coerce_str(item).strip()
                for item in layout_channel_order
                if _coerce_str(item).strip()
            ]
    return []


def _resolve_output_file_path(
    output: dict[str, Any],
    *,
    out_dir: Path,
) -> Path | None:
    file_path_value = _coerce_str(output.get("file_path")).strip()
    if not file_path_value:
        return None
    candidate = Path(file_path_value)
    if candidate.is_absolute():
        return candidate
    return out_dir / candidate


def _lfe_corrective_seed(*parts: str) -> int:
    import hashlib  # noqa: WPS433

    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _output_export_seed_and_policy(output: dict[str, Any]) -> tuple[int | None, str | None]:
    receipt = output.get("export_finalization_receipt")
    if not isinstance(receipt, dict):
        return None, None
    dither_policy = _coerce_str(receipt.get("dither_policy")).strip() or None
    seed_derivation = receipt.get("seed_derivation")
    if not isinstance(seed_derivation, dict):
        return None, dither_policy
    job_id = _coerce_str(seed_derivation.get("job_id")).strip()
    layout_id = _coerce_str(seed_derivation.get("layout_id")).strip()
    render_seed_raw = seed_derivation.get("render_seed")
    render_seed = (
        int(render_seed_raw)
        if isinstance(render_seed_raw, int) and not isinstance(render_seed_raw, bool)
        else 0
    )
    if not job_id or not layout_id:
        return None, dither_policy
    from mmo.dsp.export_finalize import derive_export_finalization_seed  # noqa: WPS433

    seed = derive_export_finalization_seed(
        job_id=job_id,
        layout_id=layout_id,
        stem_id=_coerce_str(seed_derivation.get("stem_id")).strip() or None,
        render_seed=render_seed,
    )
    return seed, dither_policy


def _apply_lfe_corrective_postprocess(
    *,
    manifests: list[dict[str, Any]],
    recs: list[dict[str, Any]],
    out_dir: Path,
    session_payload: dict[str, Any],
    explicit_lfe_ids: list[str],
) -> dict[str, Any]:
    import tempfile  # noqa: WPS433

    from mmo.core.lfe_corrective import (  # noqa: WPS433
        append_note,
        compare_filtered_output_to_baseline,
        corrective_filter_candidates,
        corrective_filter_spec_from_recommendation,
        recommendation_targets_explicit_lfe,
        write_filtered_lfe_wav,
    )
    from mmo.dsp.io import sha256_file  # noqa: WPS433

    approved_corrective_recs = [
        rec
        for rec in recs
        if rec.get("eligible_render") is True
        and rec.get("approved_by_user") is True
        and corrective_filter_spec_from_recommendation(rec) is not None
    ]
    approved_corrective_recs.sort(
        key=lambda rec: _coerce_str(rec.get("recommendation_id")).strip()
    )
    summary: dict[str, Any] = {
        "applied_recommendation_ids": [],
        "refused_recommendation_ids": [],
        "qa_rerun_count": 0,
        "post_manifest": None,
    }
    if not approved_corrective_recs:
        return summary

    post_manifest: dict[str, Any] = {
        "renderer_id": "PLUGIN.RENDERER.LFE_CORRECTIVE_POST",
        "outputs": [],
        "received_recommendation_ids": [],
        "skipped": [],
        "notes": "post_render_lfe_corrective_filters",
    }

    for rec in approved_corrective_recs:
        rec_id = _coerce_str(rec.get("recommendation_id")).strip()
        action_id = _coerce_str(rec.get("action_id")).strip()
        scope = rec.get("scope") if isinstance(rec.get("scope"), dict) else {}
        target_stem_id = _coerce_str(scope.get("stem_id")).strip()
        filter_spec = corrective_filter_spec_from_recommendation(rec)
        if filter_spec is None:
            post_manifest["skipped"].append(
                {
                    "recommendation_id": rec_id,
                    "action_id": action_id,
                    "reason": "unsupported_filter_spec",
                    "gate_summary": "",
                }
            )
            continue

        candidate_outputs: list[dict[str, Any]] = []
        for manifest in manifests:
            if not isinstance(manifest, dict):
                continue
            outputs = manifest.get("outputs")
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                if target_stem_id and _coerce_str(output.get("target_stem_id")).strip() != target_stem_id:
                    continue
                candidate_outputs.append(output)

        if not candidate_outputs:
            post_manifest["skipped"].append(
                {
                    "recommendation_id": rec_id,
                    "action_id": action_id,
                    "reason": "missing_target_output",
                    "gate_summary": "",
                }
            )
            continue

        rec_applied = False
        refusal_attempts: list[dict[str, Any]] = []
        explicit_lfe_target = recommendation_targets_explicit_lfe(rec, explicit_lfe_ids)
        for output in candidate_outputs:
            output_path = _resolve_output_file_path(output, out_dir=out_dir)
            if output_path is None or not output_path.exists():
                post_manifest["skipped"].append(
                    {
                        "recommendation_id": rec_id,
                        "action_id": action_id,
                        "reason": "missing_output_file",
                        "gate_summary": "",
                    }
                )
                continue

            channel_order = _output_channel_order(output)
            if not channel_order or not any(
                speaker_id.upper().startswith("SPK.LFE")
                for speaker_id in channel_order
            ):
                post_manifest["skipped"].append(
                    {
                        "recommendation_id": rec_id,
                        "action_id": action_id,
                        "reason": (
                            "explicit_lfe_no_silent_fix"
                            if explicit_lfe_target
                            else "no_lfe_output_channel"
                        ),
                        "gate_summary": "",
                    }
                )
                continue

            layout_id = (
                _coerce_str(output.get("layout_id")).strip()
                or _coerce_str(
                    (output.get("metadata") or {}).get("layout_id")
                    if isinstance(output.get("metadata"), dict)
                    else ""
                ).strip()
                or _coerce_str(session_payload.get("target_layout_id")).strip()
            )
            if not layout_id:
                post_manifest["skipped"].append(
                    {
                        "recommendation_id": rec_id,
                        "action_id": action_id,
                        "reason": "missing_layout_id",
                        "gate_summary": "",
                    }
                )
                continue

            for attempt_index, candidate in enumerate(
                corrective_filter_candidates(filter_spec),
                start=1,
            ):
                with tempfile.TemporaryDirectory(
                    dir=output_path.parent,
                    prefix=".mmo_lfe_corrective_",
                ) as temp_dir:
                    temp_output = Path(temp_dir) / output_path.name
                    seed, dither_policy = _output_export_seed_and_policy(output)
                    if seed is None:
                        seed = _lfe_corrective_seed(
                            rec_id,
                            _coerce_str(output.get("output_id")).strip(),
                            str(attempt_index),
                        )
                    wrote_output = write_filtered_lfe_wav(
                        source_path=output_path,
                        output_path=temp_output,
                        channel_order=channel_order,
                        filter_spec=candidate,
                        seed=seed,
                        dither_policy=dither_policy,
                    )
                    if not wrote_output:
                        continue
                    qa_compare = compare_filtered_output_to_baseline(
                        baseline_surround_path=output_path,
                        candidate_surround_path=temp_output,
                        source_layout_id=layout_id,
                    )
                    summary["qa_rerun_count"] += 1
                    refusal_attempts.append(
                        {
                            "attempt": attempt_index,
                            "filter_spec": dict(candidate),
                            "qa_compare": qa_compare,
                        }
                    )
                    if not qa_compare.get("passed"):
                        continue
                    temp_output.replace(output_path)
                    output["sha256"] = sha256_file(output_path)
                    output["notes"] = append_note(
                        output.get("notes"),
                        (
                            f"LFE corrective filter applied: {rec_id} "
                            f"({candidate['filter_type']} @ {candidate['cutoff_hz']} Hz)."
                        ),
                    )
                    metadata = output.get("metadata")
                    if not isinstance(metadata, dict):
                        metadata = {}
                        output["metadata"] = metadata
                    metadata["lfe_corrective_filter"] = dict(candidate)
                    metadata["lfe_corrective_qa"] = qa_compare
                    metadata["lfe_corrective_recommendation_id"] = rec_id
                    post_manifest["received_recommendation_ids"].append(rec_id)
                    summary["applied_recommendation_ids"].append(rec_id)
                    rec_applied = True
                    break
            if rec_applied:
                break

        if not rec_applied:
            post_manifest["skipped"].append(
                {
                    "recommendation_id": rec_id,
                    "action_id": action_id,
                    "reason": "refused_worsened_qa",
                    "gate_summary": "",
                    "details": {"attempts": refusal_attempts},
                }
            )
            summary["refused_recommendation_ids"].append(rec_id)

    post_manifest["received_recommendation_ids"] = sorted(
        {
            _coerce_str(rec_id).strip()
            for rec_id in post_manifest.get("received_recommendation_ids", [])
            if _coerce_str(rec_id).strip()
        }
    )
    skipped = post_manifest.get("skipped")
    if isinstance(skipped, list):
        skipped.sort(
            key=lambda item: (
                _coerce_str(item.get("recommendation_id")),
                _coerce_str(item.get("action_id")),
                _coerce_str(item.get("reason")),
            )
        )
    if post_manifest["received_recommendation_ids"] or post_manifest["skipped"]:
        manifests.append(post_manifest)
        summary["post_manifest"] = post_manifest
    summary["applied_recommendation_ids"] = sorted(
        {
            _coerce_str(rec_id).strip()
            for rec_id in summary["applied_recommendation_ids"]
            if _coerce_str(rec_id).strip()
        }
    )
    summary["refused_recommendation_ids"] = sorted(
        {
            _coerce_str(rec_id).strip()
            for rec_id in summary["refused_recommendation_ids"]
            if _coerce_str(rec_id).strip()
        }
    )
    return summary


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _report_session_stem_ids(report: dict[str, Any]) -> set[str]:
    session = report.get("session")
    if not isinstance(session, dict):
        return set()
    stems = session.get("stems")
    if not isinstance(stems, list):
        return set()
    return {
        stem_id
        for stem in stems
        if isinstance(stem, dict)
        for stem_id in [_coerce_str(stem.get("stem_id")).strip()]
        if stem_id
    }


def _scene_referenced_stem_ids(scene: dict[str, Any]) -> set[str]:
    stem_ids: set[str] = set()

    objects = scene.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            stem_id = _coerce_str(obj.get("stem_id")).strip()
            if stem_id:
                stem_ids.add(stem_id)

    beds = scene.get("beds")
    if isinstance(beds, list):
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            bed_stem_ids = bed.get("stem_ids")
            if not isinstance(bed_stem_ids, list):
                continue
            for stem_id in bed_stem_ids:
                normalized = _coerce_str(stem_id).strip()
                if normalized:
                    stem_ids.add(normalized)
    return stem_ids


def _scene_referenced_role_ids(scene: dict[str, Any]) -> set[str]:
    objects = scene.get("objects")
    if not isinstance(objects, list):
        return set()
    return {
        role_id
        for obj in objects
        if isinstance(obj, dict)
        for role_id in [_coerce_str(obj.get("role_id")).strip()]
        if role_id
    }


def _augment_preflight_scene(
    *,
    scene_payload: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    preflight_scene = _json_clone(scene_payload)

    report_recs = report.get("recommendations")
    if isinstance(report_recs, list) and report_recs:
        preflight_scene["recommendations"] = report_recs

    report_qa = report.get("qa_issues")
    if isinstance(report_qa, list) and report_qa:
        preflight_scene["qa_issues"] = report_qa

    report_meta = report.get("metadata")
    if isinstance(report_meta, dict):
        scene_meta = preflight_scene.setdefault("metadata", {})
        for key in ("correlation", "polarity_inverted"):
            val = report_meta.get(key)
            if val is not None and key not in scene_meta:
                scene_meta[key] = val
    else:
        report_meta = {}

    scene_meta = preflight_scene.setdefault("metadata", {})
    if "confidence" not in scene_meta:
        rec_scores = [
            float(rec["confidence"])
            for rec in (report_recs if isinstance(report_recs, list) else [])
            if isinstance(rec, dict)
            and isinstance(rec.get("confidence"), (int, float))
        ]
        report_meta_conf = report_meta.get("confidence")
        if isinstance(report_meta_conf, (int, float)):
            scene_meta["confidence"] = float(report_meta_conf)
        elif rec_scores:
            scene_meta["confidence"] = sum(rec_scores) / len(rec_scores)
        else:
            scene_meta["confidence"] = 1.0

    return preflight_scene


def _prepare_safe_render_scene_inputs(
    *,
    report: dict[str, Any],
    session_payload: dict[str, Any],
    scene_path: Path | None,
    scene_locks_path: Path | None,
    scene_strict: bool,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    str,
    str | None,
    str | None,
    dict[str, Any],
]:
    from mmo.core.locks import (  # noqa: WPS433
        load_scene_build_locks,
    )
    from mmo.core.precedence import apply_precedence  # noqa: WPS433
    from mmo.core.roles import list_roles  # noqa: WPS433
    from mmo.core.scene_binding import bind_scene_inputs_to_session  # noqa: WPS433
    from mmo.core.scene_lint import (  # noqa: WPS433
        build_scene_lint_payload,
        render_scene_lint_text,
        scene_lint_has_errors,
    )
    from mmo.core.scene_builder import build_scene_from_session  # noqa: WPS433

    scene_payload: dict[str, Any] | None = None
    locks_payload: dict[str, Any] | None = None
    scene_mode = "auto_built"
    scene_source_path: str | None = None
    scene_locks_source_path: str | None = None
    scene_binding_summary = _default_scene_binding_summary()

    if scene_path is not None:
        scene_payload = _load_json_object(scene_path, label="Scene")
        scene_mode = "explicit"
        scene_source_path = scene_path.resolve().as_posix()
    elif scene_locks_path is not None or scene_strict:
        # Locks and strict validation need the same canonical scene shape the
        # renderer would use later, even when no scene file was supplied.
        scene_payload = build_scene_from_session(session_payload)

    if scene_payload is not None:
        scene_payload = _json_clone(scene_payload)

    if scene_locks_path is not None:
        locks_payload = load_scene_build_locks(scene_locks_path)
        scene_locks_source_path = scene_locks_path.resolve().as_posix()

    if scene_payload is not None and (scene_path is not None or scene_locks_path is not None):
        # Explicit scenes and lock files can carry stale refs from another
        # workspace. Rebind before linting or precedence so strict mode judges
        # the current session, not machine-local leftovers.
        scene_payload, locks_payload, scene_binding_summary = bind_scene_inputs_to_session(
            scene_payload=scene_payload,
            session_payload=session_payload,
            locks_payload=locks_payload,
        )
        binding_status = _coerce_str(scene_binding_summary.get("status")).strip() or "unknown"
        bound_count = int(scene_binding_summary.get("bound_count", 0) or 0)
        unbound_count = int(scene_binding_summary.get("unbound_count", 0) or 0)
        rewritten_count = int(scene_binding_summary.get("rewritten_count", 0) or 0)
        failure_reason = _coerce_str(scene_binding_summary.get("failure_reason")).strip()
        print(
            "safe-render: scene-binding "
            f"status={binding_status} bound={bound_count} "
            f"unbound={unbound_count} rewritten={rewritten_count}",
            file=sys.stderr,
        )
        if failure_reason:
            print(
                f"safe-render: scene-binding reason={failure_reason}",
                file=sys.stderr,
            )
        if binding_status == "failed":
            print(
                "safe-render: scene-binding found zero overlap after normalization. "
                "Preflight will stop this render before audio is written.",
                file=sys.stderr,
            )
        elif binding_status == "partial":
            print(
                "safe-render: continuing with a partially bound scene. "
                "Unbound refs remain visible in the receipt and preflight may still stop the render.",
                file=sys.stderr,
            )

    if scene_path is not None and scene_payload is not None:
        # Lint after rebinding so strict mode stops on the scene as it will be
        # rendered here, not on stale refs from another workspace.
        lint_payload = build_scene_lint_payload(
            scene_payload=scene_payload,
            scene_path=scene_path,
            locks_payload=locks_payload,
            locks_path=scene_locks_path,
            extra_source_stem_ids=_report_session_stem_ids(report),
        )
        summary = lint_payload.get("summary")
        error_count = (
            summary.get("error_count", 0)
            if isinstance(summary, dict) and isinstance(summary.get("error_count"), int)
            else 0
        )
        warn_count = (
            summary.get("warn_count", 0)
            if isinstance(summary, dict) and isinstance(summary.get("warn_count"), int)
            else 0
        )
        print(
            "safe-render: scene-lint "
            f"errors={error_count} warnings={warn_count} strict={'on' if scene_strict else 'off'}",
            file=sys.stderr,
        )
        if error_count > 0 or warn_count > 0:
            print(render_scene_lint_text(lint_payload), file=sys.stderr)
            if not scene_strict:
                print(
                    "safe-render: continuing because --scene-strict is off."
                    " Review the scene-lint report above if the placement looks"
                    " surprising, or rerun with --scene-strict to stop here.",
                    file=sys.stderr,
                )
        if scene_strict and scene_lint_has_errors(lint_payload):
            issue_ids = sorted(
                {
                    _coerce_str(issue.get("issue_id")).strip()
                    for issue in lint_payload.get("issues", [])
                    if isinstance(issue, dict) and _coerce_str(issue.get("issue_id")).strip()
                }
            )
            issue_ids_label = ", ".join(issue_ids[:6])
            if len(issue_ids) > 6:
                issue_ids_label = f"{issue_ids_label}, +{len(issue_ids) - 6} more"
            raise ValueError(
                "safe-render: scene validation stopped the render. "
                f"Why: --scene-strict found {error_count} error(s), {warn_count} warning(s), "
                f"and issue_ids={issue_ids_label}. "
                "Next: fix the scene or rerun without --scene-strict only if you intentionally "
                "want MMO to continue past scene errors."
            )

    if scene_payload is not None:
        # Precedence must land before any strict reference check so the scene
        # validated here matches the one later gates and render steps will see.
        scene_payload = apply_precedence(
            scene_payload,
            locks_payload,
            None,
            locks_path=scene_locks_path,
        )

    if scene_strict:
        if scene_payload is None:
            scene_payload = build_scene_from_session(session_payload)

        # Strict mode is the last no-audio stop. Missing refs or an unreadable
        # role registry should fail here before render-side side effects begin.
        missing_stem_refs = sorted(
            _scene_referenced_stem_ids(scene_payload) - _report_session_stem_ids(report)
        )
        try:
            known_role_ids = set(list_roles())
        except (RuntimeError, ValueError) as exc:
            raise ValueError(
                "safe-render: scene validation could not load the roles registry. "
                f"Why: {exc}. "
                "Next: repair the install or bundled data before using --scene-strict."
            ) from exc
        missing_role_refs = sorted(
            role_id
            for role_id in _scene_referenced_role_ids(scene_payload)
            if role_id not in known_role_ids
        )

        if missing_stem_refs or missing_role_refs:
            details: list[str] = []
            if missing_stem_refs:
                details.append("missing stems: " + ", ".join(missing_stem_refs))
            if missing_role_refs:
                details.append("missing roles: " + ", ".join(missing_role_refs))
            raise ValueError(
                "safe-render: scene validation stopped the render. "
                "Why: "
                + "; ".join(details)
                + ". Next: rebuild the scene so it points at real stems and known roles, "
                + "or rerun without --scene-strict only if you are reviewing the draft."
            )

    return (
        scene_payload,
        locks_payload,
        scene_mode,
        scene_source_path,
        scene_locks_source_path,
        scene_binding_summary,
    )


def _run_safe_render_command(
    *,
    repo_root: Path,
    report_path: Path,
    plugins_dir: Path,
    out_dir: Path | None,
    out_manifest_path: Path | None,
    receipt_out_path: Path | None,
    qa_out_path: Path | None,
    profile_id: str,
    target: str,
    dry_run: bool,
    approve: str | None,
    approve_rec_ids: list[str] | None = None,
    approve_file: Path | None = None,
    output_formats: list[str] | None = None,
    run_config: dict[str, Any] | None = None,
    force: bool = False,
    user_profile: dict[str, Any] | None = None,
    render_many_targets: list[str] | None = None,
    layout_standard: str = "SMPTE",
    preview_headphones: bool = False,
    allow_empty_outputs: bool = False,
    export_stems: bool = False,
    export_buses: bool = False,
    export_master: bool = True,
    export_layouts: list[str] | None = None,
    live_progress: bool = False,
    cancel_file: Path | None = None,
    cancel_token: CancelToken | None = None,
    scene_path: Path | None = None,
    scene_locks_path: Path | None = None,
    scene_strict: bool = False,
) -> int:
    """Run the full plugin-chain render: detect → resolve → gate → render.

    Bounded authority:
    - Low-impact recommendations may auto-apply within configured limits.
    - Medium/high-impact recommendations stay blocked unless explicitly approved.

    Produces a safe-run receipt JSON and optionally a QA report with spectral
    slope metrics.

    When ``render_many_targets`` is provided, runs one full render pass per
    target (stereo + 5.1 + 7.1.4 by default) using parallel jobs.
    """
    from mmo.core.gates import apply_gates_to_report  # noqa: WPS433
    from mmo.core.binaural_target import (  # noqa: WPS433
        build_binaural_target_manifests,
        choose_binaural_source_layout,
        is_binaural_layout,
    )
    from mmo.core.lfe_corrective import (  # noqa: WPS433
        append_note,
        corrective_filter_spec_from_recommendation,
        explicit_lfe_stem_ids,
        recommendation_targets_explicit_lfe,
    )
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_detectors,
        run_renderers,
        run_resolvers,
    )
    from mmo.core.precedence import (  # noqa: WPS433
        apply_precedence,
        apply_recommendation_precedence,
    )
    from mmo.core.preflight import evaluate_preflight, preflight_receipt_blocks  # noqa: WPS433
    from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433
    from mmo.core.scene_builder import build_scene_from_session  # noqa: WPS433

    token = cancel_token or CancelToken()
    progress = _new_safe_render_progress(
        total_steps=6 if dry_run else 8,
        cancel_token=token,
        live_progress=live_progress,
    )

    if render_many_targets:
        try:
            return _run_render_many_targets(
                render_many_targets=render_many_targets,
                repo_root=repo_root,
                report_path=report_path,
                plugins_dir=plugins_dir,
                out_dir=out_dir,
                receipt_out_path=receipt_out_path,
                qa_out_path=qa_out_path,
                profile_id=profile_id,
                dry_run=dry_run,
                approve=approve,
                approve_rec_ids=approve_rec_ids,
                approve_file=approve_file,
                output_formats=output_formats,
                run_config=run_config,
                force=force,
                user_profile=user_profile,
                layout_standard=layout_standard,
                preview_headphones=preview_headphones,
                allow_empty_outputs=allow_empty_outputs,
                export_stems=export_stems,
                export_buses=export_buses,
                export_master=export_master,
                export_layouts=export_layouts,
                live_progress=live_progress,
                cancel_file=cancel_file,
                cancel_token=token,
                scene_path=scene_path,
                scene_locks_path=scene_locks_path,
                scene_strict=scene_strict,
            )
        except CancelledError as exc:
            print(f"safe-render: cancelled ({exc})", file=sys.stderr)
            return 130

    try:
        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        resolved_target = resolve_target_token(target)
        binaural_target_requested = is_binaural_layout(resolved_target.layout_id)
        resolved_export_layout_ids = _resolve_export_layout_ids(export_layouts)
        binaural_source_selection = None
        progress.emit_log(
            kind="info",
            scope="render",
            what="safe-render started",
            why="Beginning bounded-authority render workflow.",
            where=[report_path.resolve().as_posix(), target],
            confidence=1.0,
            evidence={"codes": ["SAFE_RENDER.STARTED"]},
        )

        for out_path, label in (
            (receipt_out_path, "receipt-out"),
            (out_manifest_path, "out-manifest"),
            (qa_out_path, "qa-out"),
        ):
            if out_path is not None and out_path.exists() and not force:
                print(
                    f"File exists (use --force to overwrite): {out_path.as_posix()}",
                    file=sys.stderr,
                )
                return 1

        report = _load_report(report_path)
        workspace_dir = report_path.parent.resolve()
        session_payload = report.get("session")
        if not isinstance(session_payload, dict):
            session_payload = {}
            report["session"] = session_payload
        session_payload["workspace_dir"] = workspace_dir.as_posix()
        explicit_lfe_ids = explicit_lfe_stem_ids(session_payload)
        (
            scene_payload_for_render,
            scene_locks_payload,
            scene_mode,
            scene_source_path,
            scene_locks_source_path,
            scene_binding_summary,
        ) = _prepare_safe_render_scene_inputs(
            report=report,
            session_payload=session_payload,
            scene_path=scene_path,
            scene_locks_path=scene_locks_path,
            scene_strict=scene_strict,
        )
        scene_source_path = _portable_ref_for_workspace(
            scene_source_path,
            workspace_dir=workspace_dir,
            fallback="scene.json",
        )
        scene_locks_source_path = _portable_ref_for_workspace(
            scene_locks_source_path,
            workspace_dir=workspace_dir,
            fallback="scene_locks.yaml",
        )
        scene_binding_summary = _portable_scene_binding_summary(
            scene_binding_summary,
            workspace_dir=workspace_dir,
        )
        # Persist the prepared scene and binding summary back into the session
        # so later receipts can show which scene drove this render.
        if isinstance(scene_payload_for_render, dict):
            session_payload["scene_payload"] = _json_clone(scene_payload_for_render)
        if isinstance(scene_locks_payload, dict):
            session_payload["scene_locks_payload"] = _json_clone(scene_locks_payload)
        session_payload["scene_binding_summary"] = _json_clone(scene_binding_summary)
        session_payload["render_export_options"] = _merged_render_export_options(
            session_payload=session_payload,
            export_stems=export_stems,
            export_buses=export_buses,
            export_master=export_master,
            export_layout_ids=resolved_export_layout_ids,
        )
        session_payload["target_layout_id"] = resolved_target.layout_id
        if run_config is not None:
            # Preflight and later receipts must read the same normalized layout
            # contract the renderer will follow if this run continues.
            normalized_run_config = normalize_run_config(run_config)
            report["run_config"] = normalized_run_config
            if routing_layout_ids_from_run_config(normalized_run_config) is not None:
                apply_routing_plan_to_report(report, normalized_run_config)

        session_for_preflight: dict[str, Any] = {
            "profile_id": profile_id,
            "scene_mode": scene_mode,
            "session_stem_ids": sorted(_report_session_stem_ids(report)),
        }
        if isinstance(session_payload, dict):
            src_layout = session_payload.get("source_layout_id")
            if not src_layout:
                rc = report.get("run_config")
                if isinstance(rc, dict):
                    src_layout = rc.get("source_layout_id")
            if isinstance(src_layout, str) and src_layout.strip():
                session_for_preflight["source_layout_id"] = src_layout.strip()
            if isinstance(scene_payload_for_render, dict):
                preflight_scene = _augment_preflight_scene(
                    scene_payload=scene_payload_for_render,
                    report=report,
                )
            else:
                # Reports can reach safe-render without a persisted scene. Fall
                # back to the shared builder so preflight still sees canonical
                # scene structure instead of a report-shaped guess.
                try:
                    preflight_scene = build_scene_from_session(session_payload)
                except (ValueError, KeyError, TypeError):
                    preflight_scene = report
                else:
                    preflight_scene = _augment_preflight_scene(
                        scene_payload=preflight_scene,
                        report=report,
                    )
        else:
            preflight_scene = report

        if binaural_target_requested:
            hinted_source_layout = _coerce_str(
                session_for_preflight.get("source_layout_id")
            ).strip() or None
            binaural_source_selection = choose_binaural_source_layout(
                report=report,
                scene=preflight_scene if isinstance(preflight_scene, dict) else None,
                source_layout_id_hint=hinted_source_layout,
            )

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        preflight_receipt = evaluate_preflight(
            session=session_for_preflight,
            scene=preflight_scene,
            target_layout=resolved_target.layout_id,
            options={},
            user_profile=user_profile,
        )
        preflight_summary = _preflight_summary_from_receipt(preflight_receipt)
        _preflight_decision = preflight_receipt.get("final_decision", "pass")
        print(
            f"safe-render: preflight={_preflight_decision}"
            f" target={target}"
            f" resolved_layout={resolved_target.layout_id}",
            file=sys.stderr,
        )
        primary_preflight_message = _coerce_str(
            preflight_summary.get("primary_message")
        ).strip()
        if primary_preflight_message:
            print(
                f"safe-render: preflight reason={primary_preflight_message}",
                file=sys.stderr,
            )
        progress.advance(
            phase="preflight",
            what="preflight evaluated",
            why="Evaluated safety gates before running any rendering stage.",
            where=[target],
            confidence=1.0,
            evidence={"codes": ["SAFE_RENDER.PREFLIGHT.EVALUATED"]},
        )

        preflight_blocks_render = preflight_receipt_blocks(preflight_receipt)
        preflight_requires_hard_stop = (
            preflight_blocks_render
            and (
                not dry_run
                or _preflight_should_hard_stop_dry_run(preflight_summary)
            )
        )
        if preflight_requires_hard_stop:
            blocked_gates = [
                g["gate_id"]
                for g in preflight_receipt.get("gates_evaluated", [])
                if g.get("outcome") == "block"
            ]
            print(
                f"safe-render: preflight BLOCKED by gates: {', '.join(blocked_gates)}",
                file=sys.stderr,
            )
            print(
                "safe-render: render stopped before audio was written.",
                file=sys.stderr,
            )
            if primary_preflight_message:
                print(
                    (
                        "safe-render: root-cause="
                        f"{primary_preflight_message}"
                    ),
                    file=sys.stderr,
                )
            print(
                (
                    "safe-render: next=review the receipt JSON to inspect the blocked "
                    "preflight decision."
                    if dry_run
                    else "safe-render: next=review the receipt JSON or rerun with --dry-run "
                    "to see what MMO was protecting."
                ),
                file=sys.stderr,
            )
            if receipt_out_path is not None:
                block_receipt_id = _build_receipt_id(
                    _coerce_str(report.get("report_id")),
                    target,
                )
                blocked_receipt: dict[str, Any] = {
                    "schema_version": "0.1.0",
                    "receipt_id": block_receipt_id,
                    "context": "safe_render",
                    "status": LIFECYCLE_STATUS_BLOCKED,
                    "dry_run": dry_run,
                    "target": target,
                    "profile_id": profile_id,
                    "scene_mode": scene_mode,
                    "scene_source_path": scene_source_path,
                    "scene_locks_source_path": scene_locks_source_path,
                    "scene_binding_summary": scene_binding_summary,
                    "preflight_summary": preflight_summary,
                    "approved_by": [],
                    "recommendations_summary": {
                        "total": 0,
                        "eligible": 0,
                        "auto_eligible": 0,
                        "approved_by_user": 0,
                        "blocked": 0,
                        "applied": 0,
                    },
                    "eligible_recommendations": [],
                    "approved_by_user": [],
                    "blocked_recommendations": [],
                    "applied_recommendations": [],
                    "renderer_manifests": [],
                    "qa_issues": [],
                    "fallback_attempts": [],
                    "fallback_final": _default_fallback_final(final_outcome="not_run"),
                    "notes": [
                        (
                            "MMO stopped before rendering because preflight safety gates blocked "
                            "this target. Review this receipt to inspect the blocked decision."
                            if dry_run
                            else "MMO stopped before rendering because preflight safety gates "
                            "blocked this target. Review this receipt or rerun with --dry-run "
                            "to inspect the blocked recommendations."
                        ),
                        "preflight_blocked=true",
                        f"blocked_gates={', '.join(blocked_gates)}",
                        (
                            "preflight_primary_issue_id="
                            f"{_coerce_str(preflight_summary.get('primary_issue_id')).strip() or '<none>'}"
                        ),
                        (
                            "preflight_primary_message="
                            f"{primary_preflight_message or '<none>'}"
                        ),
                        f"target={target}",
                        f"profile_id={profile_id}",
                        (
                            "layout_standard="
                            f"{layout_standard} (channel ordering: "
                            f"{'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})"
                        ),
                        (
                            "binaural_virtualization=true"
                            if binaural_target_requested
                            else "binaural_virtualization=false"
                        ),
                        f"export_stems={'true' if export_stems else 'false'}",
                        f"export_buses={'true' if export_buses else 'false'}",
                        f"export_master={'true' if export_master else 'false'}",
                        (
                            "export_layout_ids="
                            f"{','.join(resolved_export_layout_ids)}"
                            if resolved_export_layout_ids
                            else "export_layout_ids=all"
                        ),
                    ],
                }
                if binaural_target_requested and binaural_source_selection is not None:
                    blocked_receipt["notes"].append(
                        "binaural_source_layout="
                        f"{binaural_source_selection.source_layout_id}"
                    )
                receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json_file(receipt_out_path, blocked_receipt)
            progress.emit_log(
                kind="warn",
                scope="render",
                what="safe-render blocked",
                why="Preflight gates blocked rendering for the selected target.",
                where=[target],
                confidence=1.0,
                evidence={
                    "codes": ["SAFE_RENDER.BLOCKED"],
                    "ids": blocked_gates,
                },
            )
            return 1

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        plugins = load_plugins(plugins_dir)
        detector_ids = [p.plugin_id for p in plugins if p.plugin_type == "detector"]
        resolver_ids = [p.plugin_id for p in plugins if p.plugin_type == "resolver"]
        renderer_ids = [p.plugin_id for p in plugins if p.plugin_type == "renderer"]
        print(
            f"safe-render: target={target}"
            f" detectors={len(detector_ids)}"
            f" resolvers={len(resolver_ids)}"
            f" renderers={len(renderer_ids)}",
            file=sys.stderr,
        )
        progress.advance(
            phase="plugins",
            what="plugins loaded",
            why="Loaded detector, resolver, and renderer plugins for this target.",
            where=[plugins_dir.resolve().as_posix()],
            confidence=1.0,
            evidence={
                "codes": ["SAFE_RENDER.PLUGINS.LOADED"],
                "metrics": [
                    {"name": "detector_count", "value": float(len(detector_ids))},
                    {"name": "resolver_count", "value": float(len(resolver_ids))},
                    {"name": "renderer_count", "value": float(len(renderer_ids))},
                ],
            },
        )

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        run_detectors(report, plugins)
        progress.advance(
            phase="detect",
            what="detectors completed",
            why="Ran non-mutating analysis detectors to update report evidence.",
            where=[target],
            confidence=1.0,
            evidence={"codes": ["SAFE_RENDER.DETECTORS.COMPLETED"]},
        )

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        run_resolvers(report, plugins)
        if isinstance(scene_payload_for_render, dict):
            # Resolvers add advisory values after the first scene prep pass.
            # Reapply locks here so gates and approvals judge final winners.
            scene_payload_for_render = apply_precedence(
                scene_payload_for_render,
                scene_locks_payload,
                None,
                locks_path=scene_locks_path,
            )
            session_payload["scene_payload"] = _json_clone(scene_payload_for_render)
        progress.advance(
            phase="resolve",
            what="resolvers completed",
            why="Produced advisory recommendations from detector findings.",
            where=[target],
            confidence=1.0,
            evidence={"codes": ["SAFE_RENDER.RESOLVERS.COMPLETED"]},
        )

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        apply_gates_to_report(
            report,
            policy_path=ontology_dir() / "policies" / "gates.yaml",
            profile_id=profile_id,
            profiles_path=ontology_dir() / "policies" / "authority_profiles.yaml",
        )

        recommendations = report.get("recommendations")
        recs: list[dict[str, Any]] = []
        if isinstance(recommendations, list):
            recs = [
                normalize_recommendation_contract(rec)
                for rec in recommendations
                if isinstance(rec, dict)
            ]
        if isinstance(scene_payload_for_render, dict):
            # Gate results land first. Recommendation precedence then marks
            # which gated recs stay visible but blocked by scene locks.
            apply_recommendation_precedence(scene_payload_for_render, recs)
        for rec in recs:
            if not recommendation_targets_explicit_lfe(rec, explicit_lfe_ids):
                continue
            if corrective_filter_spec_from_recommendation(rec) is None:
                continue
            rec["notes"] = append_note(
                rec.get("notes"),
                (
                    "Explicit LFE stem detected; MMO will not silently fold or "
                    "reroute this content into mains."
                ),
            )

        approve_all, explicit_approved_ids, approve_list = _collect_approval_inputs(
            approve=approve,
            approve_rec_ids=approve_rec_ids,
            approve_file=approve_file,
        )
        approved_by_user = _apply_approve_overrides(
            recs,
            approve_all=approve_all,
            approved_ids=explicit_approved_ids,
        )
        approved_by_user_summaries = [recommendation_snapshot(rec) for rec in approved_by_user]
        eligible = [rec for rec in recs if rec.get("eligible_render") is True]
        eligible_summaries = _build_eligible_rec_summaries(recs)
        blocked_summaries = _build_blocked_rec_summaries(recs)
        blocked = [rec for rec in recs if rec.get("eligible_render") is not True]
        blocked_count = len(blocked_summaries)
        approved_by_user_count = len(approved_by_user_summaries)

        print(
            f"safe-render:"
            f" total_recommendations={len(recs)}"
            f" eligible={len(eligible)}"
            f" approved_by_user={approved_by_user_count}"
            f" blocked={blocked_count}",
            file=sys.stderr,
        )
        progress.advance(
            phase="gates",
            what="authority gates applied",
            why="Classified recommendations into eligible and blocked sets.",
            where=[target],
            confidence=1.0,
            evidence={
                "codes": ["SAFE_RENDER.GATES.APPLIED"],
                "metrics": [
                    {"name": "recommendation_total", "value": float(len(recs))},
                    {"name": "eligible_total", "value": float(len(eligible))},
                    {"name": "blocked_total", "value": float(blocked_count)},
                ],
            },
        )
        receipt_id = _build_receipt_id(
            _coerce_str(report.get("report_id")),
            target,
        )

        if dry_run:
            status = (
                LIFECYCLE_STATUS_BLOCKED
                if blocked and not eligible
                else LIFECYCLE_STATUS_DRY_RUN_ONLY
            )
            empty_deliverables: list[dict[str, Any]] = []
            empty_deliverables_summary = _deliverable_result_payload(empty_deliverables)
            empty_deliverable_summary_rows, empty_result_summary = _artifact_result_details(
                renderer_manifests=[],
                deliverables=empty_deliverables,
                deliverables_summary=empty_deliverables_summary,
            )
            receipt: dict[str, Any] = {
                "schema_version": "0.1.0",
                "receipt_id": receipt_id,
                "context": "safe_render",
                "status": status,
                "dry_run": True,
                "target": target,
                "profile_id": profile_id,
                "scene_mode": scene_mode,
                "scene_source_path": scene_source_path,
                "scene_locks_source_path": scene_locks_source_path,
                "scene_binding_summary": scene_binding_summary,
                "preflight_summary": preflight_summary,
                "approved_by": approve_list,
                "recommendations_summary": {
                    "total": len(recs),
                    "eligible": len(eligible_summaries),
                    "auto_eligible": max(0, len(eligible) - approved_by_user_count),
                    "approved_by_user": approved_by_user_count,
                    "blocked": blocked_count,
                    "applied": 0,
                },
                "eligible_recommendations": eligible_summaries,
                "approved_by_user": approved_by_user_summaries,
                "blocked_recommendations": blocked_summaries,
                "applied_recommendations": [],
                "deliverables": empty_deliverables,
                "deliverables_summary": empty_deliverables_summary,
                "deliverable_summary_rows": empty_deliverable_summary_rows,
                "result_summary": empty_result_summary,
                "renderer_manifests": [],
                "qa_issues": [],
                "fallback_attempts": [],
                "fallback_final": _default_fallback_final(final_outcome="not_run"),
                "notes": [
                    "dry_run=true: no audio was written",
                    f"target={target}",
                    f"profile_id={profile_id}",
                    (
                        "binaural_virtualization=true"
                        if binaural_target_requested
                        else "binaural_virtualization=false"
                    ),
                    (
                    "headphone_preview_requested=true"
                        if preview_headphones
                        else "headphone_preview_requested=false"
                    ),
                    (
                        "preflight_primary_issue_id="
                        f"{_coerce_str(preflight_summary.get('primary_issue_id')).strip() or '<none>'}"
                    ),
                    (
                        "preflight_primary_message="
                        f"{_coerce_str(preflight_summary.get('primary_message')).strip() or '<none>'}"
                    ),
                    (
                        "layout_standard="
                        f"{layout_standard} (channel ordering: "
                        f"{'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})"
                    ),
                    f"export_stems={'true' if export_stems else 'false'}",
                    f"export_buses={'true' if export_buses else 'false'}",
                    f"export_master={'true' if export_master else 'false'}",
                    (
                        "export_layout_ids="
                        f"{','.join(resolved_export_layout_ids)}"
                        if resolved_export_layout_ids
                        else "export_layout_ids=all"
                    ),
                ],
            }
            if explicit_lfe_ids:
                receipt["notes"].append(
                    f"explicit_lfe_stems={','.join(sorted(explicit_lfe_ids))}"
                )
                receipt["notes"].append("explicit_lfe_no_silent_fix=true")
            if binaural_target_requested and binaural_source_selection is not None:
                receipt["notes"].append(
                    "binaural_source_layout="
                    f"{binaural_source_selection.source_layout_id}"
                )
                receipt["notes"].append(
                    "binaural_source_selection_reason="
                    f"{binaural_source_selection.reason}"
                )
            if receipt_out_path is not None:
                receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json_file(receipt_out_path, receipt)
            if out_manifest_path is not None:
                # Manifest and receipt intentionally carry the same top-level
                # summaries so either artifact can stand alone in UI/smoke flows.
                dry_manifest = {
                    "schema_version": "0.1.0",
                    "report_id": _coerce_str(report.get("report_id")),
                    "renderer_manifests": [],
                    "scene_binding_summary": scene_binding_summary,
                    "preflight_summary": preflight_summary,
                    "deliverables": empty_deliverables,
                    "deliverables_summary": empty_deliverables_summary,
                    "deliverable_summary_rows": empty_deliverable_summary_rows,
                    "result_summary": empty_result_summary,
                }
                _validate_render_manifest(
                    dry_manifest,
                    schemas_dir() / "render_manifest.schema.json",
                )
                out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
                out_manifest_path.write_text(
                    json.dumps(dry_manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            progress.advance(
                phase="dry_run",
                what="dry-run receipt written",
                why="Recorded bounded-authority results without writing audio.",
                where=[
                    receipt_out_path.resolve().as_posix()
                    if receipt_out_path is not None
                    else "safe_render.receipt.json"
                ],
                confidence=1.0,
                evidence={"codes": ["SAFE_RENDER.DRY_RUN.COMPLETED"]},
            )
            print(
                f"safe-render: dry-run complete"
                f" (would apply {len(eligible)} recs, {blocked_count} blocked)",
                file=sys.stderr,
            )
            return 0

        if out_dir is None:
            print(
                "safe-render: full render needs --out-dir so MMO knows where to write the audio files.",
                file=sys.stderr,
            )
            print(
                "safe-render: next=choose an output folder, or rerun with --dry-run if you only want the receipt.",
                file=sys.stderr,
            )
            return 1

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        if isinstance(scene_payload_for_render, dict):
            scene_payload_for_render = apply_precedence(
                scene_payload_for_render,
                scene_locks_payload,
                None,
                locks_path=scene_locks_path,
            )
            session_payload["scene_payload"] = _json_clone(scene_payload_for_render)
        render_report = _json_clone(report)
        postprocess_rec_ids = {
            _coerce_str(rec.get("recommendation_id")).strip()
            for rec in recs
            if rec.get("eligible_render") is True
            and rec.get("approved_by_user") is True
            and corrective_filter_spec_from_recommendation(rec) is not None
            and _coerce_str(rec.get("recommendation_id")).strip()
        }
        render_report_recommendations = render_report.get("recommendations")
        if isinstance(render_report_recommendations, list) and postprocess_rec_ids:
            for render_rec in render_report_recommendations:
                if not isinstance(render_rec, dict):
                    continue
                rec_id = _coerce_str(render_rec.get("recommendation_id")).strip()
                if rec_id in postprocess_rec_ids:
                    render_rec["eligible_render"] = False
        renderer_output_formats = ["wav"] if binaural_target_requested else output_formats
        source_manifests = run_renderers(
            render_report,
            plugins,
            output_dir=out_dir,
            output_formats=renderer_output_formats,
        )
        lfe_corrective_summary = _apply_lfe_corrective_postprocess(
            manifests=source_manifests,
            recs=recs,
            out_dir=out_dir,
            session_payload=session_payload,
            explicit_lfe_ids=explicit_lfe_ids,
        )
        manifests = source_manifests
        preview_output_count = 0
        preview_skipped_count = 0
        if binaural_target_requested and binaural_source_selection is not None:
            manifests, binaural_counts = build_binaural_target_manifests(
                renderer_manifests=source_manifests,
                output_dir=out_dir,
                layout_standard=layout_standard,
                source_layout_id=binaural_source_selection.source_layout_id,
                output_formats=output_formats,
            )
            if isinstance(lfe_corrective_summary.get("post_manifest"), dict):
                manifests.append(lfe_corrective_summary["post_manifest"])
            preview_output_count = int(binaural_counts.get("outputs", 0))
            preview_skipped_count = int(binaural_counts.get("skipped", 0))
        elif preview_headphones:
            from mmo.plugins.subjective.binaural_preview_v0 import (  # noqa: WPS433
                build_headphone_preview_manifest,
            )

            preview_manifest = build_headphone_preview_manifest(
                renderer_manifests=manifests,
                output_dir=out_dir,
                layout_standard=layout_standard,
            )
            manifests.append(preview_manifest)
            preview_outputs = preview_manifest.get("outputs")
            preview_skipped = preview_manifest.get("skipped")
            preview_output_count = len(preview_outputs) if isinstance(preview_outputs, list) else 0
            preview_skipped_count = len(preview_skipped) if isinstance(preview_skipped, list) else 0
        output_count = _count_manifest_outputs(manifests)
        deliverables = build_deliverables_for_renderer_manifests(manifests)
        deliverables_summary = _deliverable_result_payload(
            deliverables,
            fallback_status="failed" if output_count == 0 else None,
            fallback_failure_reason=(
                RENDER_RESULT_NO_OUTPUT_ARTIFACT if output_count == 0 else None
            ),
        )
        persisted_manifests = _portable_renderer_manifests(
            manifests,
            workspace_dir=workspace_dir,
        )
        deliverable_summary_rows, result_summary = _artifact_result_details(
            renderer_manifests=persisted_manifests,
            deliverables=deliverables,
            deliverables_summary=deliverables_summary,
        )
        # Manifest intentionally mirrors summary surfaces also present on the
        # receipt so UI, smoke, and diagnostics can open either artifact alone.
        render_manifest = {
            "schema_version": "0.1.0",
            "report_id": _coerce_str(report.get("report_id")),
            "renderer_manifests": persisted_manifests,
            "scene_binding_summary": scene_binding_summary,
            "preflight_summary": preflight_summary,
            "deliverables_summary": deliverables_summary,
            "deliverable_summary_rows": deliverable_summary_rows,
            "result_summary": result_summary,
        }
        render_manifest["deliverables"] = deliverables
        no_outputs_issue: dict[str, Any] | None = None
        all_masters_invalid_issue: dict[str, Any] | None = None
        if output_count == 0:
            no_outputs_issue = _build_no_outputs_issue(
                out_dir=out_dir,
                workspace_dir=workspace_dir,
            )
            print(
                f"safe-render: {ISSUE_RENDER_NO_OUTPUTS}"
                f" message={_NO_OUTPUTS_WARNING_MESSAGE}",
                file=sys.stderr,
            )
            print(
                "safe-render: render finished without writing any audio files.",
                file=sys.stderr,
            )
            print(
                "safe-render: next=check the receipt/QA files and confirm at least one renderer can write the selected target. "
                "Use --allow-empty-outputs only when a receipt-only pass is intentional.",
                file=sys.stderr,
            )
            progress.emit_log(
                kind="warn",
                scope="render",
                what="safe-render wrote zero outputs",
                why="Renderer stage completed with no audio files emitted.",
                where=[out_dir.resolve().as_posix()],
                confidence=1.0,
                evidence={
                    "codes": ["SAFE_RENDER.NO_OUTPUTS"],
                    "ids": [ISSUE_RENDER_NO_OUTPUTS],
                    "metrics": [{"name": "output_count", "value": 0.0}],
                },
            )
        elif _master_deliverables_invalid_for_safe_render(deliverables):
            all_masters_invalid_issue = _build_all_masters_invalid_issue(
                failure_reason=_deliverable_top_failure_reason(deliverables_summary) or None,
            )
            print(
                f"safe-render: {ISSUE_RENDER_ALL_MASTERS_INVALID}"
                f" message={_ALL_MASTERS_INVALID_MESSAGE}",
                file=sys.stderr,
            )
            print(
                "safe-render: render artifacts were kept for diagnostics, but no valid master was produced.",
                file=sys.stderr,
            )
            progress.emit_log(
                kind="warn",
                scope="render",
                what="safe-render wrote only invalid masters",
                why="All master deliverables failed because no stems decoded or the rendered output is effectively silent.",
                where=[out_dir.resolve().as_posix()],
                confidence=1.0,
                evidence={
                    "codes": ["SAFE_RENDER.INVALID_MASTERS"],
                    "ids": [ISSUE_RENDER_ALL_MASTERS_INVALID],
                    "metrics": [
                        {
                            "name": "valid_master_count",
                            "value": float(deliverables_summary.get("valid_master_count", 0) or 0),
                        }
                    ],
                },
            )
        _validate_render_manifest(
            render_manifest,
            schemas_dir() / "render_manifest.schema.json",
        )
        if out_manifest_path is not None:
            out_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            out_manifest_path.write_text(
                json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        progress.advance(
            phase="render",
            what="renderers completed",
            why="Applied eligible actions and wrote deterministic render outputs.",
            where=[out_dir.resolve().as_posix()],
            confidence=1.0,
            evidence={
                "codes": ["SAFE_RENDER.RENDERERS.COMPLETED"],
                "metrics": [{"name": "output_count", "value": float(output_count)}],
            },
        )

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        qa_payload: dict[str, Any] = {}
        qa_issues: list[dict[str, Any]] = []
        fallback_attempts: list[dict[str, Any]] = []
        fallback_final: dict[str, Any] = _default_fallback_final(final_outcome="not_run")
        if qa_out_path is not None or receipt_out_path is not None:
            output_entries = _collect_output_entries_from_manifests(
                manifests,
                out_dir,
                workspace_dir,
            )
            if output_entries:
                qa_payload = build_safe_render_qa(output_entries=output_entries)
                qa_issues = qa_payload.get("issues") or []
            else:
                qa_payload = {
                    "schema_version": "0.1.0",
                    "outputs": [],
                    "issues": [],
                    "thresholds": {},
                }
        fallback_attempts, fallback_final, fallback_issues = _collect_fallback_reporting(
            manifests=manifests,
            out_dir=out_dir,
            workspace_dir=workspace_dir,
        )
        if fallback_issues:
            qa_issues.extend(fallback_issues)
            qa_payload_issues = qa_payload.get("issues")
            if isinstance(qa_payload_issues, list):
                qa_payload_issues.extend(json.loads(json.dumps(fallback_issues)))
        if qa_payload:
            qa_payload["deliverables"] = json.loads(json.dumps(deliverables))
            qa_payload["deliverables_summary"] = json.loads(json.dumps(deliverables_summary))
            qa_payload["fallback_attempts"] = json.loads(json.dumps(fallback_attempts))
            qa_payload["fallback_final"] = json.loads(json.dumps(fallback_final))
        if no_outputs_issue is not None:
            qa_issues.append(dict(no_outputs_issue))
            qa_payload_issues = qa_payload.get("issues")
            if isinstance(qa_payload_issues, list):
                qa_payload_issues.append(dict(no_outputs_issue))
        if all_masters_invalid_issue is not None:
            qa_issues.append(dict(all_masters_invalid_issue))
            qa_payload_issues = qa_payload.get("issues")
            if isinstance(qa_payload_issues, list):
                qa_payload_issues.append(dict(all_masters_invalid_issue))
        qa_issues = enrich_issue_list_for_user(qa_issues)
        if qa_payload:
            qa_payload["issues"] = json.loads(json.dumps(qa_issues))
        if qa_payload:
            qa_payload = _rewrite_nested_path_fields(
                qa_payload,
                workspace_dir=workspace_dir,
                field_names=_PERSISTED_QA_PATH_FIELDS,
            )
            rewritten_issues = qa_payload.get("issues")
            if isinstance(rewritten_issues, list):
                qa_issues = rewritten_issues
        if qa_out_path is not None:
            qa_out_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_file(qa_out_path, qa_payload)
        qa_error_count = sum(
            1
            for iss in qa_issues
            if isinstance(iss, dict) and _coerce_str(iss.get("severity")) == "error"
        )
        progress.advance(
            phase="qa",
            what="render QA completed",
            why="Computed post-render QA metrics and issue severities.",
            where=[
                qa_out_path.resolve().as_posix()
                if qa_out_path is not None
                else "safe_render.qa"
            ],
            confidence=1.0,
            evidence={
                "codes": ["SAFE_RENDER.QA.COMPLETED"],
                "metrics": [
                    {"name": "qa_error_count", "value": float(qa_error_count)},
                    {"name": "qa_warn_count", "value": float(len(qa_issues) - qa_error_count)},
                ],
            },
        )

        # Safe-render remains back-compatible and user-helpful by keeping
        # partial/safe artifacts plus explicit QA failure metadata when
        # similarity fallback exhausts. The only hard-stop retained here is
        # the existing "no outputs" contract unless another explicit strict
        # policy is introduced separately.
        render_status = (
            LIFECYCLE_STATUS_BLOCKED
            if (
                (no_outputs_issue is not None and not allow_empty_outputs)
                or all_masters_invalid_issue is not None
            )
            else LIFECYCLE_STATUS_COMPLETED
        )
        applied_summaries = _build_applied_rec_summaries(
            recs,
            manifests,
            extra_received_ids=list(
                lfe_corrective_summary.get("applied_recommendation_ids", [])
                if isinstance(lfe_corrective_summary, dict)
                else []
            ),
        )
        render_result_status = _deliverable_result_bucket(deliverables_summary)
        render_overall_status = (
            _coerce_str(deliverables_summary.get("overall_status")).strip()
            or ("failed" if output_count == 0 else "success")
        )
        top_failure_reason = _deliverable_top_failure_reason(deliverables_summary)
        # Receipt keeps the same summary surfaces as the manifest, plus the
        # execution/approval context unique to safe-render.
        receipt = {
            "schema_version": "0.1.0",
            "receipt_id": receipt_id,
            "context": "safe_render",
            "status": render_status,
            "dry_run": False,
            "target": target,
            "profile_id": profile_id,
            "scene_mode": scene_mode,
            "scene_source_path": scene_source_path,
            "scene_locks_source_path": scene_locks_source_path,
            "scene_binding_summary": scene_binding_summary,
            "preflight_summary": preflight_summary,
            "approved_by": approve_list,
            "recommendations_summary": {
                "total": len(recs),
                "eligible": len(eligible_summaries),
                "auto_eligible": max(0, len(eligible) - approved_by_user_count),
                "approved_by_user": approved_by_user_count,
                "blocked": blocked_count,
                "applied": len(applied_summaries),
            },
            "eligible_recommendations": eligible_summaries,
            "approved_by_user": approved_by_user_summaries,
            "blocked_recommendations": blocked_summaries,
            "applied_recommendations": applied_summaries,
            "deliverables": deliverables,
            "deliverables_summary": deliverables_summary,
            "deliverable_summary_rows": deliverable_summary_rows,
            "result_summary": result_summary,
            "renderer_manifests": render_manifest["renderer_manifests"],
            "qa_issues": qa_issues,
            "fallback_attempts": fallback_attempts,
            "fallback_final": fallback_final,
            "notes": [
                f"target={target}",
                f"profile_id={profile_id}",
                f"renderers={','.join(renderer_ids) if renderer_ids else '<none>'}",
                f"outputs={output_count}",
                f"deliverable_result={render_result_status}",
                f"deliverable_overall_status={render_overall_status}",
                (
                    "scene_binding_status="
                    f"{_coerce_str(scene_binding_summary.get('status')).strip() or 'not_applicable'}"
                ),
                (
                    "scene_binding_bound="
                    f"{int(scene_binding_summary.get('bound_count', 0) or 0)}"
                ),
                (
                    "scene_binding_unbound="
                    f"{int(scene_binding_summary.get('unbound_count', 0) or 0)}"
                ),
                (
                    "preflight_primary_issue_id="
                    f"{_coerce_str(preflight_summary.get('primary_issue_id')).strip() or '<none>'}"
                ),
                (
                    "preflight_primary_message="
                    f"{_coerce_str(preflight_summary.get('primary_message')).strip() or '<none>'}"
                ),
                f"allow_empty_outputs={'true' if allow_empty_outputs else 'false'}",
                (
                    "headphone_preview="
                    f"enabled(outputs={preview_output_count},skipped={preview_skipped_count})"
                    if preview_headphones
                    else "headphone_preview=disabled"
                ),
                (
                    "binaural_virtualization=true"
                    if binaural_target_requested
                    else "binaural_virtualization=false"
                ),
                (
                    "layout_standard="
                    f"{layout_standard} (channel ordering: "
                    f"{'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})"
                ),
                f"export_stems={'true' if export_stems else 'false'}",
                f"export_buses={'true' if export_buses else 'false'}",
                f"export_master={'true' if export_master else 'false'}",
                (
                "export_layout_ids="
                f"{','.join(resolved_export_layout_ids)}"
                if resolved_export_layout_ids
                else "export_layout_ids=all"
            ),
            ],
        }
        if explicit_lfe_ids:
            receipt["notes"].append(
                f"explicit_lfe_stems={','.join(sorted(explicit_lfe_ids))}"
            )
            receipt["notes"].append("explicit_lfe_no_silent_fix=true")
        receipt["notes"].append(
            "lfe_corrective_qa_rerun_count="
            f"{int(lfe_corrective_summary.get('qa_rerun_count', 0) or 0)}"
        )
        receipt["notes"].append(
            "lfe_corrective_applied="
            f"{len(lfe_corrective_summary.get('applied_recommendation_ids', []))}"
        )
        receipt["notes"].append(
            "lfe_corrective_refused="
            f"{len(lfe_corrective_summary.get('refused_recommendation_ids', []))}"
        )
        if fallback_attempts:
            receipt["notes"].append("fallback_applied=true")
        if fallback_final.get("safety_collapse_applied") is True:
            receipt["notes"].append("safety_collapse_applied=true")
        receipt["notes"].extend(_plugin_safety_receipt_notes(manifests))
        receipt["notes"].append(
            "fallback_final_outcome="
            f"{_coerce_str(fallback_final.get('final_outcome')).strip() or 'not_run'}"
        )
        if top_failure_reason:
            receipt["notes"].append(f"top_failure_reason={top_failure_reason}")
        if no_outputs_issue is not None:
            receipt["notes"].append(f"{ISSUE_RENDER_NO_OUTPUTS}: {_NO_OUTPUTS_WARNING_MESSAGE}")
        if all_masters_invalid_issue is not None:
            receipt["notes"].append(
                f"{ISSUE_RENDER_ALL_MASTERS_INVALID}: {_ALL_MASTERS_INVALID_MESSAGE}"
            )
        if binaural_target_requested and binaural_source_selection is not None:
            receipt["notes"].append(
                "binaural_source_layout="
                f"{binaural_source_selection.source_layout_id}"
            )
            receipt["notes"].append(
                "binaural_source_selection_reason="
                f"{binaural_source_selection.reason}"
            )
        if receipt_out_path is not None:
            receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_file(receipt_out_path, receipt)
        progress.advance(
            phase="receipt",
            what="safe-render receipt written",
            why="Persisted explainable render outcome and QA summary.",
            where=[
                receipt_out_path.resolve().as_posix()
                if receipt_out_path is not None
                else "safe_render.receipt.json"
            ],
            confidence=1.0,
            evidence={"codes": ["SAFE_RENDER.RECEIPT.WRITTEN"]},
        )

        exit_code = 0
        if no_outputs_issue is not None and not allow_empty_outputs:
            print(
                "safe-render: failing because outputs=0."
                " Override with --allow-empty-outputs only if a receipt-only pass is intentional.",
                file=sys.stderr,
            )
            exit_code = 1
        elif all_masters_invalid_issue is not None:
            print(
                "safe-render: failing because all rendered masters are invalid."
                " MMO kept the artifacts for debugging, but they do not count as a successful render.",
                file=sys.stderr,
            )
            exit_code = 1
        elif fallback_final.get("final_outcome") == "fail":
            print(
                "safe-render: deterministic fallback sequence exhausted without"
                " passing similarity QA; outputs were kept and the receipt/QA"
                " report mark the failure explicitly.",
                file=sys.stderr,
            )
        elif no_outputs_issue is not None and allow_empty_outputs:
            print(
                "safe-render: outputs=0 allowed by --allow-empty-outputs."
                " Receipt and QA files were still written for review.",
                file=sys.stderr,
            )

        print(
            f"safe-render:"
            f" result={render_result_status}"
            f" overall_status={render_overall_status}"
            f" deliverables={deliverables_summary.get('deliverable_count', 0)}"
            f" valid_masters={deliverables_summary.get('valid_master_count', 0)}"
            f" success={deliverables_summary.get('success_count', 0)}"
            f" partial={deliverables_summary.get('partial_count', 0)}"
            f" failed={deliverables_summary.get('failed_count', 0)}"
            f" invalid_master={deliverables_summary.get('invalid_master_count', 0)}"
            f" outputs={output_count}"
            f" qa_errors={qa_error_count}"
            f" qa_warns={len(qa_issues) - qa_error_count}"
            + (
                f" top_failure_reason={top_failure_reason}"
                if top_failure_reason
                else ""
            ),
            file=sys.stderr,
        )
        return exit_code
    except CancelledError as exc:
        print(f"safe-render: cancelled ({exc})", file=sys.stderr)
        return 130


# ---------------------------------------------------------------------------
# Demo: render-many-standards (all 5 channel-ordering standards in parallel)
# ---------------------------------------------------------------------------

_DEMO_LAYOUT_STANDARDS: list[str] = ["SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF"]
"""All 5 channel-ordering standards used by the --demo render-many flow."""


def _run_safe_render_demo(
    *,
    fixture_path: Path,
    plugins_dir: Path,
    out_dir: Path | None,
    profile_id: str = "PROFILE.ASSIST",
    run_config: dict[str, Any] | None = None,
    force: bool = False,
) -> int:
    """Run the render-many-standards demo using the built-in 7.1.4 fixture.

    Loads ``fixture_path`` (``fixtures/immersive/report.7_1_4.json``) and
    runs a dry-run safe-render pass for every channel-ordering standard in
    :data:`_DEMO_LAYOUT_STANDARDS` (SMPTE, FILM, LOGIC_PRO, VST3, AAF) in
    parallel using :class:`concurrent.futures.ThreadPoolExecutor`.

    Each standard gets its own sub-directory under ``out_dir``.  All passes
    run in ``--dry-run`` mode so no audio I/O is required.

    Args:
        fixture_path: Path to the 7.1.4 fixture report JSON.
        plugins_dir: Plugins directory (passed through to safe-render).
        out_dir: Root output directory.  Per-standard sub-dirs are created
            automatically (e.g. ``<out_dir>/SMPTE/``, ``<out_dir>/FILM/``).
        profile_id: Authority profile for gating (default PROFILE.ASSIST).
        run_config: Optional merged run config dict.
        force: Overwrite existing output files if True.

    Returns:
        0 if all standard passes succeed, 1 if any fail.
    """
    import concurrent.futures  # noqa: WPS433

    if not fixture_path.exists():
        print(
            f"safe-render --demo: fixture not found: {fixture_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    standards = _DEMO_LAYOUT_STANDARDS
    print(
        f"safe-render --demo: fixture={fixture_path.as_posix()}"
        f" standards={','.join(standards)}",
        file=sys.stderr,
    )

    def _run_one_standard(standard: str) -> tuple[str, int]:
        std_out_dir = (out_dir / standard) if out_dir is not None else None
        std_receipt = (
            std_out_dir / "receipt.json" if std_out_dir is not None else None
        )
        rc = _run_safe_render_command(
            repo_root=None,
            report_path=fixture_path,
            plugins_dir=plugins_dir,
            out_dir=std_out_dir,
            out_manifest_path=(
                std_out_dir / "render_manifest.json" if std_out_dir is not None else None
            ),
            receipt_out_path=std_receipt,
            qa_out_path=None,
            profile_id=profile_id,
            target="7.1.4",
            dry_run=True,  # demo always dry-run — no audio required
            approve=None,
            approve_rec_ids=None,
            approve_file=None,
            output_formats=None,
            run_config=run_config,
            force=force,
            user_profile=None,
            render_many_targets=None,
            layout_standard=standard,
        )
        return standard, rc

    results: list[tuple[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(standards), thread_name_prefix="demo_standard"
    ) as pool:
        futures = {pool.submit(_run_one_standard, std): std for std in standards}
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                std = futures[fut]
                print(
                    f"safe-render --demo: standard={std} raised {exc}",
                    file=sys.stderr,
                )
                results.append((std, 1))

    # Sort after the futures finish so parallel completion order does not
    # reshuffle the summary output.
    results.sort(key=lambda r: r[0])
    failed = [std for std, rc in results if rc != 0]
    succeeded = [std for std, rc in results if rc == 0]
    print(
        f"safe-render --demo: completed"
        f" succeeded={len(succeeded)}"
        f" failed={len(failed)}"
        f"{' failed_standards=' + ','.join(failed) if failed else ''}",
        file=sys.stderr,
    )
    return 0 if not failed else 1
