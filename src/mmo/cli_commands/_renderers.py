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
from mmo.core.listen_pack import build_listen_pack
from mmo.core.routing import (
    apply_routing_plan_to_report,
    routing_layout_ids_from_run_config,
)
from mmo.core.run_config import normalize_run_config
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
_NO_OUTPUTS_WARNING_MESSAGE = (
    "No audio outputs were written. This build may not include a mixdown renderer yet."
)


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
    from mmo.core.binaural_target import (  # noqa: WPS433
        build_binaural_target_manifests,
        choose_binaural_source_layout,
        is_binaural_layout,
    )
    from mmo.core.gates import apply_gates_to_report  # noqa: WPS433
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_renderers,
    )

    report = _load_report(report_path)
    normalized_run_config: dict[str, Any] | None = None
    if run_config is not None:
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
    render_manifest = {
        "schema_version": "0.1.0",
        "report_id": report.get("report_id", ""),
        "renderer_manifests": manifests,
    }
    if deliverables:
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
        policy_path=ontology_dir() /"policies" / "gates.yaml",
        profile_id=profile_id,
        profiles_path=ontology_dir() /"policies" / "authority_profiles.yaml",
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
        schemas_dir() /"apply_manifest.schema.json",
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

    # Stable output order
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


def _parse_approve_arg(approve_arg: str | None) -> set[str] | str | None:
    """Parse the --approve argument into a usable form.

    Returns:
      ``"all"``        – approve every blocked rec.
      ``"none"``       – approve nothing (gate decisions are final).
      A ``set[str]``   – set of recommendation_id / issue_id values to approve.
      ``None``         – no --approve flag given; same as "none".
    """
    if approve_arg is None:
        return None
    stripped = approve_arg.strip().lower()
    if stripped in ("all", "none", ""):
        return stripped
    return {part.strip() for part in approve_arg.split(",") if part.strip()}


def _apply_approve_overrides(
    recs: list[dict[str, Any]],
    approve: set[str] | str | None,
) -> int:
    """Mutate eligible_render=True for recs covered by the approval.

    Returns the count of recs that were approved this way.
    """
    if approve is None or approve == "none":
        return 0
    count = 0
    for rec in recs:
        if rec.get("eligible_render") is True:
            continue  # already eligible
        if approve == "all":
            rec["eligible_render"] = True
            count += 1
        elif isinstance(approve, set):
            rec_id = _coerce_str(rec.get("recommendation_id"))
            issue_id = _coerce_str(rec.get("issue_id"))
            if rec_id in approve or issue_id in approve:
                rec["eligible_render"] = True
                count += 1
    return count


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
            abs_path = file_path_str
            if out_dir is not None:
                resolved = out_dir / file_path_str
                if resolved.exists():
                    abs_path = resolved.as_posix()
            entries.append(
                {
                    "path": abs_path,
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
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "issue_id": ISSUE_RENDER_NO_OUTPUTS,
        "severity": "warn",
        "message": _NO_OUTPUTS_WARNING_MESSAGE,
        "metric": "output_count",
        "value": 0,
        "threshold": 1,
    }
    if out_dir is not None:
        issue["output_path"] = out_dir.resolve().as_posix()
    return issue


def _build_blocked_rec_summaries(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked = [
        rec for rec in recs
        if rec.get("eligible_render") is not True
        and rec.get("requires_approval") is True
    ]
    summaries: list[dict[str, Any]] = []
    for rec in blocked:
        gate_results = rec.get("gate_results")
        gate_summary = ""
        if isinstance(gate_results, list):
            for gr in gate_results:
                if isinstance(gr, dict) and gr.get("eligible") is False:
                    reason = _coerce_str(gr.get("reason"))
                    if reason:
                        gate_summary = reason
                        break
        summaries.append(
            {
                "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                "issue_id": _coerce_str(rec.get("issue_id")),
                "action_id": _coerce_str(rec.get("action_id")),
                "risk": _coerce_str(rec.get("risk")),
                "requires_approval": bool(rec.get("requires_approval")),
                "gate_summary": gate_summary,
            }
        )
    return summaries


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
) -> tuple[dict[str, Any] | None, str, str | None, str | None]:
    from mmo.core.locks import (  # noqa: WPS433
        apply_scene_build_locks,
        load_scene_build_locks,
    )
    from mmo.core.roles import list_roles  # noqa: WPS433
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

    if scene_path is not None:
        scene_payload = _load_json_object(scene_path, label="Scene")
        scene_mode = "explicit"
        scene_source_path = scene_path.resolve().as_posix()
    elif scene_locks_path is not None or scene_strict:
        scene_payload = build_scene_from_session(session_payload)

    if scene_payload is not None:
        scene_payload = _json_clone(scene_payload)

    if scene_locks_path is not None:
        locks_payload = load_scene_build_locks(scene_locks_path)
        scene_locks_source_path = scene_locks_path.resolve().as_posix()

    if scene_path is not None and scene_payload is not None:
        lint_payload = build_scene_lint_payload(
            scene_payload=scene_payload,
            scene_path=scene_path,
            locks_payload=locks_payload,
            locks_path=scene_locks_path,
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
                "safe-render: --scene-strict failed scene lint "
                f"({error_count} error(s), {warn_count} warning(s); issue_ids={issue_ids_label})."
            )

    if scene_locks_path is not None:
        if scene_payload is None:
            scene_payload = build_scene_from_session(session_payload)
        if locks_payload is None:
            locks_payload = load_scene_build_locks(scene_locks_path)
        scene_payload = apply_scene_build_locks(
            scene_payload,
            locks_payload,
            locks_path=scene_locks_path,
        )

    if scene_strict:
        if scene_payload is None:
            scene_payload = build_scene_from_session(session_payload)

        missing_stem_refs = sorted(
            _scene_referenced_stem_ids(scene_payload) - _report_session_stem_ids(report)
        )
        try:
            known_role_ids = set(list_roles())
        except (RuntimeError, ValueError) as exc:
            raise ValueError(
                f"safe-render: failed to load roles registry for --scene-strict: {exc}"
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
                "safe-render: --scene-strict failed ("
                + "; ".join(details)
                + ")."
            )

    return (
        scene_payload,
        scene_mode,
        scene_source_path,
        scene_locks_source_path,
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
    - Low-risk (requires_approval=False, risk=low): auto-applied.
    - Medium/high (requires_approval=True): blocked unless covered by --approve.

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
    from mmo.core.pipeline import (  # noqa: WPS433
        build_deliverables_for_renderer_manifests,
        load_plugins,
        run_detectors,
        run_renderers,
        run_resolvers,
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
        session_payload = report.get("session")
        if not isinstance(session_payload, dict):
            session_payload = {}
            report["session"] = session_payload
        (
            scene_payload_for_render,
            scene_mode,
            scene_source_path,
            scene_locks_source_path,
        ) = _prepare_safe_render_scene_inputs(
            report=report,
            session_payload=session_payload,
            scene_path=scene_path,
            scene_locks_path=scene_locks_path,
            scene_strict=scene_strict,
        )
        if isinstance(scene_payload_for_render, dict):
            session_payload["scene_payload"] = _json_clone(scene_payload_for_render)
        session_payload["render_export_options"] = {
            "export_stems": bool(export_stems),
            "export_buses": bool(export_buses),
            "export_master": bool(export_master),
            "export_layout_ids": resolved_export_layout_ids,
        }
        session_payload["target_layout_id"] = resolved_target.layout_id
        if run_config is not None:
            normalized_run_config = normalize_run_config(run_config)
            report["run_config"] = normalized_run_config
            if routing_layout_ids_from_run_config(normalized_run_config) is not None:
                apply_routing_plan_to_report(report, normalized_run_config)

        session_for_preflight: dict[str, Any] = {"profile_id": profile_id}
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
        _preflight_decision = preflight_receipt.get("final_decision", "pass")
        print(
            f"safe-render: preflight={_preflight_decision}"
            f" target={target}"
            f" resolved_layout={resolved_target.layout_id}",
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

        if not dry_run and preflight_receipt_blocks(preflight_receipt):
            blocked_gates = [
                g["gate_id"]
                for g in preflight_receipt.get("gates_evaluated", [])
                if g.get("outcome") == "block"
            ]
            print(
                f"safe-render: preflight BLOCKED by gates: {', '.join(blocked_gates)}",
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
                    "status": "blocked",
                    "dry_run": False,
                    "target": target,
                    "profile_id": profile_id,
                    "scene_mode": scene_mode,
                    "scene_source_path": scene_source_path,
                    "scene_locks_source_path": scene_locks_source_path,
                    "approved_by": [],
                    "recommendations_summary": {
                        "total": 0,
                        "auto_eligible": 0,
                        "approved_by_user": 0,
                        "blocked": 0,
                    },
                    "blocked_recommendations": [],
                    "renderer_manifests": [],
                    "qa_issues": [],
                    "notes": [
                        "preflight_blocked=true",
                        f"blocked_gates={', '.join(blocked_gates)}",
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
            recs = [rec for rec in recommendations if isinstance(rec, dict)]

        parsed_approve = _parse_approve_arg(approve)
        approved_by_user_count = _apply_approve_overrides(recs, parsed_approve)
        eligible = [rec for rec in recs if rec.get("eligible_render") is True]
        blocked_summaries = _build_blocked_rec_summaries(recs)
        blocked_count = len(blocked_summaries)

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

        approve_list: list[str] = (
            [approve] if isinstance(approve, str) and approve
            else sorted(parsed_approve) if isinstance(parsed_approve, set)
            else []
        )
        receipt_id = _build_receipt_id(
            _coerce_str(report.get("report_id")),
            target,
        )

        if dry_run:
            status = "blocked" if blocked_count > 0 and len(eligible) == 0 else "dry_run_only"
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
                "approved_by": approve_list,
                "recommendations_summary": {
                    "total": len(recs),
                    "auto_eligible": len(eligible) - approved_by_user_count,
                    "approved_by_user": approved_by_user_count,
                    "blocked": blocked_count,
                },
                "blocked_recommendations": blocked_summaries,
                "renderer_manifests": [],
                "qa_issues": [],
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
                dry_manifest = {
                    "schema_version": "0.1.0",
                    "report_id": _coerce_str(report.get("report_id")),
                    "renderer_manifests": [],
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
                "safe-render: --out-dir is required for full render (not --dry-run).",
                file=sys.stderr,
            )
            return 1

        _check_cancel_requested(cancel_token=token, cancel_file=cancel_file)
        renderer_output_formats = ["wav"] if binaural_target_requested else output_formats
        source_manifests = run_renderers(
            report,
            plugins,
            output_dir=out_dir,
            output_formats=renderer_output_formats,
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
        deliverables = build_deliverables_for_renderer_manifests(manifests)
        render_manifest = {
            "schema_version": "0.1.0",
            "report_id": _coerce_str(report.get("report_id")),
            "renderer_manifests": manifests,
        }
        if deliverables:
            render_manifest["deliverables"] = deliverables
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
        output_count = _count_manifest_outputs(manifests)
        no_outputs_issue: dict[str, Any] | None = None
        if output_count == 0:
            no_outputs_issue = _build_no_outputs_issue(out_dir=out_dir)
            print(
                f"safe-render: {ISSUE_RENDER_NO_OUTPUTS}"
                f" message={_NO_OUTPUTS_WARNING_MESSAGE}",
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
        if qa_out_path is not None or receipt_out_path is not None:
            output_entries = _collect_output_entries_from_manifests(manifests, out_dir)
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
        if no_outputs_issue is not None:
            qa_issues.append(dict(no_outputs_issue))
            qa_payload_issues = qa_payload.get("issues")
            if isinstance(qa_payload_issues, list):
                qa_payload_issues.append(dict(no_outputs_issue))
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

        render_status = (
            "blocked"
            if no_outputs_issue is not None and not allow_empty_outputs
            else "completed"
        )
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
            "approved_by": approve_list,
            "recommendations_summary": {
                "total": len(recs),
                "auto_eligible": max(0, len(eligible) - approved_by_user_count),
                "approved_by_user": approved_by_user_count,
                "blocked": blocked_count,
            },
            "blocked_recommendations": blocked_summaries,
            "renderer_manifests": manifests,
            "qa_issues": qa_issues,
            "notes": [
                f"target={target}",
                f"profile_id={profile_id}",
                f"renderers={','.join(renderer_ids) if renderer_ids else '<none>'}",
                f"outputs={output_count}",
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
        if no_outputs_issue is not None:
            receipt["notes"].append(f"{ISSUE_RENDER_NO_OUTPUTS}: {_NO_OUTPUTS_WARNING_MESSAGE}")
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
                "safe-render: failing because outputs=0"
                " (override with --allow-empty-outputs).",
                file=sys.stderr,
            )
            exit_code = 1
        elif no_outputs_issue is not None and allow_empty_outputs:
            print(
                "safe-render: outputs=0 allowed by --allow-empty-outputs.",
                file=sys.stderr,
            )

        print(
            f"safe-render: completed"
            f" outputs={output_count}"
            f" qa_errors={qa_error_count}"
            f" qa_warns={len(qa_issues) - qa_error_count}",
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

    # Stable output order
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
