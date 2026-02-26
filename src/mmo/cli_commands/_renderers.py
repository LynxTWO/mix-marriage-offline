"""Renderer, apply, bundle, and deliverables-index CLI helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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

    manifests = run_renderers(
        report,
        plugins,
        output_dir=out_dir,
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
) -> int:
    """Run safe-render for multiple targets in parallel (mix-once, render-many).

    Each target gets its own sub-directory under ``out_dir`` and per-target
    receipt / manifest files.  Returns 0 only when every target succeeds.
    """
    import concurrent.futures  # noqa: WPS433

    targets = render_many_targets if render_many_targets else _RENDER_MANY_DEFAULT_TARGETS
    print(
        f"safe-render/render-many: targets={','.join(targets)}",
        file=sys.stderr,
    )

    def _run_one(tgt: str) -> tuple[str, int]:
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

    # Stable output order
    results.sort(key=lambda r: r[0])
    failed = [tgt for tgt, rc in results if rc != 0]
    succeeded = [tgt for tgt, rc in results if rc == 0]
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

    # -- render-many: delegate to multi-target helper --------------------------
    if render_many_targets:
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
        )

    # -- overwrite guards -------------------------------------------------------
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

    # -- load inputs -----------------------------------------------------------
    report = _load_report(report_path)
    if run_config is not None:
        normalized_run_config = normalize_run_config(run_config)
        report["run_config"] = normalized_run_config
        if routing_layout_ids_from_run_config(normalized_run_config) is not None:
            apply_routing_plan_to_report(report, normalized_run_config)

    # -- stage 1: build scene from validated session (mix-once, render-many) --
    session_payload = report.get("session")
    session_for_preflight: dict[str, Any] = {"profile_id": profile_id}
    if isinstance(session_payload, dict):
        # Carry source_layout_id into preflight session context
        src_layout = session_payload.get("source_layout_id")
        if not src_layout:
            rc = report.get("run_config")
            if isinstance(rc, dict):
                src_layout = rc.get("source_layout_id")
        if isinstance(src_layout, str) and src_layout.strip():
            session_for_preflight["source_layout_id"] = src_layout.strip()
        try:
            preflight_scene = build_scene_from_session(session_payload)
        except (ValueError, KeyError, TypeError):
            preflight_scene = report  # safe fallback when session is incomplete
        else:
            # Augment scene with analysis data from report so preflight gates
            # have full context: recommendations confidence, qa_issues, and any
            # metadata the analysis pass produced (e.g. correlation, polarity).
            report_recs = report.get("recommendations")
            if isinstance(report_recs, list) and report_recs:
                preflight_scene["recommendations"] = report_recs
            report_qa = report.get("qa_issues")
            if isinstance(report_qa, list) and report_qa:
                preflight_scene["qa_issues"] = report_qa
            # Merge report metadata (correlation, polarity_inverted) into scene.
            report_meta = report.get("metadata")
            if isinstance(report_meta, dict):
                scene_meta = preflight_scene.setdefault("metadata", {})
                for key in ("correlation", "polarity_inverted"):
                    val = report_meta.get(key)
                    if val is not None and key not in scene_meta:
                        scene_meta[key] = val
            # Compute effective confidence for preflight from report recommendations.
            # If no confidence values exist in the report, default to 1.0 so that
            # a scene built without metering data preserves the existing
            # "no data → assume full confidence" semantics.
            scene_meta = preflight_scene.setdefault("metadata", {})
            if "confidence" not in scene_meta:
                recs_for_conf = report.get("recommendations")
                rec_scores = [
                    float(r["confidence"])
                    for r in (recs_for_conf if isinstance(recs_for_conf, list) else [])
                    if isinstance(r, dict)
                    and isinstance(r.get("confidence"), (int, float))
                ]
                report_meta_conf = (
                    report_meta.get("confidence")
                    if isinstance(report_meta, dict) else None
                )
                if isinstance(report_meta_conf, (int, float)):
                    scene_meta["confidence"] = float(report_meta_conf)
                elif rec_scores:
                    scene_meta["confidence"] = sum(rec_scores) / len(rec_scores)
                else:
                    # No confidence data → assume full confidence (backward compat)
                    scene_meta["confidence"] = 1.0
    else:
        preflight_scene = report

    # -- stage 1a: preflight safety gates (no audio; fail-fast) ---------------
    preflight_receipt = evaluate_preflight(
        session=session_for_preflight,
        scene=preflight_scene,
        target_layout=target,
        options={},
        user_profile=user_profile,
    )
    _preflight_decision = preflight_receipt.get("final_decision", "pass")
    print(
        f"safe-render: preflight={_preflight_decision}"
        f" target={target}",
        file=sys.stderr,
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
                _coerce_str(report.get("report_id")), target
            )
            blocked_receipt: dict[str, Any] = {
                "schema_version": "0.1.0",
                "receipt_id": block_receipt_id,
                "context": "safe_render",
                "status": "blocked",
                "dry_run": False,
                "target": target,
                "profile_id": profile_id,
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
                    f"preflight_blocked=true",
                    f"blocked_gates={', '.join(blocked_gates)}",
                    f"target={target}",
                    f"profile_id={profile_id}",
                    f"layout_standard={layout_standard} (channel ordering: {'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})",
                ],
            }
            receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_file(receipt_out_path, blocked_receipt)
        return 1

    # -- load plugins ----------------------------------------------------------
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

    # -- stage 2: analysis / metering pass (detectors, no audio mutation) ------
    run_detectors(report, plugins)

    # -- stage 3: scene inference / resolve pass (advisory) -------------------
    run_resolvers(report, plugins)

    # -- stage 4: bounded authority gate --------------------------------------
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

    # -- apply --approve overrides --------------------------------------------
    parsed_approve = _parse_approve_arg(approve)
    approved_by_user_count = _apply_approve_overrides(recs, parsed_approve)

    auto_eligible = [
        rec for rec in recs
        if rec.get("eligible_render") is True
        and not (rec.get("requires_approval") and rec.get("_approved_by_user"))
    ]
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

    approve_list: list[str] = (
        [approve] if isinstance(approve, str) and approve
        else sorted(parsed_approve) if isinstance(parsed_approve, set)
        else []
    )
    receipt_id = _build_receipt_id(
        _coerce_str(report.get("report_id")), target
    )

    # -- dry-run: write receipt only, no audio --------------------------------
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
                f"dry_run=true: no audio was written",
                f"target={target}",
                f"profile_id={profile_id}",
                f"layout_standard={layout_standard} (channel ordering: {'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})",
            ],
        }
        if receipt_out_path is not None:
            receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_file(receipt_out_path, receipt)
        if out_manifest_path is not None:
            # Write an empty dry-run manifest
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
        print(
            f"safe-render: dry-run complete"
            f" (would apply {len(eligible)} recs, {blocked_count} blocked)",
            file=sys.stderr,
        )
        return 0

    # -- stage 5: render pass (plugin renderers write audio) ------------------
    if out_dir is None:
        print(
            "safe-render: --out-dir is required for full render (not --dry-run).",
            file=sys.stderr,
        )
        return 1

    manifests = run_renderers(
        report,
        plugins,
        output_dir=out_dir,
        output_formats=output_formats,
    )
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

    # -- stage 6: post-render QA pass (spectral slopes + gates) ---------------
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

    if qa_out_path is not None:
        qa_out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_file(qa_out_path, qa_payload)

    # -- stage 7: export pass (write safe-run receipt) ------------------------
    status = "completed"
    receipt = {
        "schema_version": "0.1.0",
        "receipt_id": receipt_id,
        "context": "safe_render",
        "status": status,
        "dry_run": False,
        "target": target,
        "profile_id": profile_id,
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
            f"layout_standard={layout_standard} (channel ordering: {'SMPTE/ITU-R default' if layout_standard == 'SMPTE' else 'Film/Cinema/Pro Tools'})",
        ],
    }
    if receipt_out_path is not None:
        receipt_out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_file(receipt_out_path, receipt)

    output_count = sum(
        len(m.get("outputs", []))
        for m in manifests
        if isinstance(m, dict)
    )
    qa_error_count = sum(
        1 for iss in qa_issues
        if isinstance(iss, dict) and _coerce_str(iss.get("severity")) == "error"
    )
    print(
        f"safe-render: completed"
        f" outputs={output_count}"
        f" qa_errors={qa_error_count}"
        f" qa_warns={len(qa_issues) - qa_error_count}",
        file=sys.stderr,
    )
    return 0


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
