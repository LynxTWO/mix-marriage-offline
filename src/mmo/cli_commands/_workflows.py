"""Workflow orchestration functions extracted from cli.py.

Contains render-many helpers, variant/one-shot/render-many workflows,
UI launcher helpers, and the UI workflow entry-point.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

from mmo.resources import _repo_checkout_root, ontology_dir, schemas_dir

_checkout_root = _repo_checkout_root()

from mmo.cli_commands._helpers import (
    _BASELINE_RENDER_TARGET_ID,
    _DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
    _OUTPUT_FORMAT_ORDER,
    _coerce_str,
    _config_int,
    _config_nested_output_formats,
    _config_optional_string,
    _config_string,
    _load_and_merge_run_config,
    _load_json_object,
    _load_report,
    _load_timeline_payload,
    _parse_output_format_sets,
    _parse_output_formats_csv,
    _rel_path_if_under_root,
    _set_nested,
    _validate_json_payload,
    _write_json_file,
)
from mmo.cli_commands._analysis import (
    _analysis_cache_key,
    _analysis_run_config_for_variant_cache,
    _run_analyze,
    _run_export,
    _should_skip_analysis_cache_save,
    _analyze_run_config,
)
from mmo.cli_commands._renderers import (
    _build_applied_report,
    _build_validated_deliverables_index_single,
    _build_validated_deliverables_index_variants,
    _build_validated_listen_pack,
    _run_apply_command,
    _run_bundle,
    _run_render_command,
    _write_routing_plan_artifact,
)
from mmo.cli_commands._scene import (
    _apply_run_config_to_render_many_variant_plan,
    _apply_scene_templates_to_payload,
    _build_selected_render_targets_payload,
    _build_validated_render_plan_payload,
    _build_validated_scene_payload,
    _default_render_plan_targets_payload,
    _parse_scene_template_ids_csv,
    _parse_target_ids_csv,
    _render_plan_policies_from_report,
    _validate_scene_schema,
)
from mmo.cli_commands._registries import (
    _build_preset_preview_payload,
    _build_preset_recommendations_payload,
    _build_translation_audition_payload,
    _build_translation_run_payload,
    _render_preset_preview_text,
    _sorted_translation_results,
    _write_report_with_translation_results,
    _write_translation_audition_manifest,
    _parse_translation_profile_ids_csv,
)
from mmo.cli_commands._project import (
    _project_last_run_payload,
    _project_run_config_defaults,
)
from mmo.core.cache_keys import hash_lockfile
from mmo.core.cache_store import (
    report_schema_is_valid,
    rewrite_report_stems_dir,
    save_cached_report,
    try_load_cached_report,
)
from mmo.core.listen_pack import index_stems_auditions
from mmo.core.presets import list_presets
from mmo.core.project_file import (
    load_project,
    update_project_last_run,
    write_project,
)
from mmo.core.render_plan_bridge import render_plan_to_variant_plan
from mmo.core.render_targets import get_render_target
from mmo.core.routing import apply_routing_plan_to_report
from mmo.core.run_config import normalize_run_config
from mmo.core.translation_profiles import load_translation_profiles
from mmo.core.translation_reference import (
    TranslationReferenceResolutionError,
    resolve_translation_reference_audio,
)
from mmo.core.variants import build_variant_plan, run_variant_plan
from mmo.ui.tui import choose_from_list, multi_toggle, render_header, yes_no

# ── Constants ────────────────────────────────────────────────────────

_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS: tuple[str, ...] = (
    "TRANS.MONO.COLLAPSE",
    "TRANS.DEVICE.PHONE",
    "TRANS.DEVICE.SMALL_SPEAKER",
)

_UI_OVERLAY_CHIPS: tuple[str, ...] = (
    "Warm",
    "Air",
    "Punch",
    "Glue",
    "Wide",
    "Safe",
    "Live",
    "Vocal",
)

_UIInputProvider = Callable[[str], str]
_UIOutputWriter = Callable[[str], None]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


# ── __all__ ──────────────────────────────────────────────────────────

__all__ = [
    "_dict_list",
    "_path_from_result_value",
    "_render_output_sort_key",
    "_render_many_variant_artifacts",
    "_resolve_wav_output_path",
    "_wav_output_path_from_manifest",
    "_resolve_render_many_stereo_audio_path",
    "_resolve_render_many_translation_cache_dir",
    "_run_render_many_translation_checks",
    "_coerce_float",
    "_render_many_rel_posix",
    "_render_many_rel_posix_from_value",
    "_translation_audition_summary_from_manifest",
    "_write_render_many_listen_pack_translation_auditions",
    "_run_render_many_translation_auditions",
    "_load_report_from_path_or_dir",
    "_run_variants_listen_pack_command",
    "_run_variants_workflow",
    "_run_one_shot_workflow",
    "_run_render_many_workflow",
    "_run_workflow_from_run_args",
    "_ui_count_list",
    "_ui_lockfile_status",
    "_ui_last_run_pointer_rows",
    "_ui_report_path_from_variant_result",
    "_ui_report_path_from_project",
    "_ui_workflow_help_short_map",
    "_ui_render_preview_text",
    "_ui_first_variant_bundle_path",
    "_run_ui_workflow",
    "_string_list",
    "_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS",
    "_UI_OVERLAY_CHIPS",
    "_UIInputProvider",
    "_UIOutputWriter",
]


# ── render-many helpers ──────────────────────────────────────────────


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _path_from_result_value(
    value: Any,
    *,
    root_out_dir: Path,
    variant_out_dir: Path | None = None,
) -> Path | None:
    raw = _coerce_str(value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    if variant_out_dir is not None:
        return (variant_out_dir / candidate).resolve()
    return (root_out_dir / candidate).resolve()


def _render_output_sort_key(output: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _render_many_variant_artifacts(
    *,
    variant_result: dict[str, Any],
    root_out_dir: Path,
) -> list[dict[str, Any]]:
    plan = variant_result.get("plan")
    plan_variants = (
        _dict_list(plan.get("variants"))
        if isinstance(plan, dict)
        else []
    )
    by_variant_id: dict[str, dict[str, Any]] = {}
    for variant in plan_variants:
        variant_id = _coerce_str(variant.get("variant_id")).strip()
        if variant_id and variant_id not in by_variant_id:
            by_variant_id[variant_id] = variant

    artifacts: list[dict[str, Any]] = []
    results = sorted(
        _dict_list(variant_result.get("results")),
        key=lambda item: _coerce_str(item.get("variant_id")).strip(),
    )
    for result in results:
        variant_id = _coerce_str(result.get("variant_id")).strip()
        plan_variant = by_variant_id.get(variant_id, {})
        variant_out_dir = _path_from_result_value(
            result.get("out_dir"),
            root_out_dir=root_out_dir,
        )
        artifact = {
            "variant_id": variant_id,
            "target_id": (
                _coerce_str(plan_variant.get("label")).strip()
                if _coerce_str(plan_variant.get("label")).strip().startswith("TARGET.")
                else ""
            ),
            "target_layout_id": _coerce_str(plan_variant.get("target_layout_id")).strip(),
            "out_dir": variant_out_dir,
            "report_path": _path_from_result_value(
                result.get("report_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "bundle_path": _path_from_result_value(
                result.get("bundle_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "render_manifest_path": _path_from_result_value(
                result.get("render_manifest_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "apply_manifest_path": _path_from_result_value(
                result.get("apply_manifest_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
            "applied_report_path": _path_from_result_value(
                result.get("applied_report_path"),
                root_out_dir=root_out_dir,
                variant_out_dir=variant_out_dir,
            ),
        }
        artifacts.append(artifact)
    return artifacts


def _resolve_wav_output_path(
    *,
    output: dict[str, Any],
    candidate_roots: list[Path],
) -> Path | None:
    output_format = _coerce_str(output.get("format")).strip().lower()
    file_path = _coerce_str(output.get("file_path")).strip()
    if not file_path:
        return None
    if output_format and output_format != "wav":
        return None
    if not output_format and Path(file_path).suffix.lower() not in {".wav", ".wave"}:
        return None

    channel_count = output.get("channel_count")
    if (
        isinstance(channel_count, int)
        and not isinstance(channel_count, bool)
        and channel_count != 2
    ):
        return None

    file_candidate = Path(file_path)
    if file_candidate.is_absolute():
        if file_candidate.exists() and file_candidate.is_file():
            return file_candidate.resolve()
        return None

    for root in candidate_roots:
        candidate = (root / file_candidate).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _wav_output_path_from_manifest(
    *,
    render_manifest: dict[str, Any],
    target_layout_id: str,
    candidate_roots: list[Path],
    allow_fallback: bool,
) -> Path | None:
    outputs_by_id: dict[str, list[dict[str, Any]]] = {}
    outputs_all: list[dict[str, Any]] = []
    for renderer_manifest in _dict_list(render_manifest.get("renderer_manifests")):
        for output in _dict_list(renderer_manifest.get("outputs")):
            output_id = _coerce_str(output.get("output_id")).strip()
            if output_id:
                outputs_by_id.setdefault(output_id, []).append(output)
            outputs_all.append(output)

    for output_id in list(outputs_by_id.keys()):
        outputs_by_id[output_id] = sorted(
            outputs_by_id[output_id],
            key=_render_output_sort_key,
        )
    outputs_all = sorted(outputs_all, key=_render_output_sort_key)

    preferred_output_ids: list[str] = []
    for deliverable in sorted(
        _dict_list(render_manifest.get("deliverables")),
        key=lambda item: _coerce_str(item.get("deliverable_id")).strip(),
    ):
        deliverable_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip()
        if deliverable_layout_id != target_layout_id:
            continue
        for output_id in sorted(
            {
                _coerce_str(output_id).strip()
                for output_id in deliverable.get("output_ids", [])
                if isinstance(output_id, str) and _coerce_str(output_id).strip()
            }
        ):
            preferred_output_ids.append(output_id)

    for output_id in preferred_output_ids:
        for output in outputs_by_id.get(output_id, []):
            resolved = _resolve_wav_output_path(
                output=output,
                candidate_roots=candidate_roots,
            )
            if resolved is not None:
                return resolved

    if not allow_fallback:
        return None

    for output in outputs_all:
        resolved = _resolve_wav_output_path(
            output=output,
            candidate_roots=candidate_roots,
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_render_many_stereo_audio_path(
    *,
    variant_artifacts: list[dict[str, Any]],
    stereo_layout_id: str,
) -> Path | None:
    for artifact in variant_artifacts:
        target_id = _coerce_str(artifact.get("target_id")).strip()
        target_layout_id = _coerce_str(artifact.get("target_layout_id")).strip()
        if target_id != _BASELINE_RENDER_TARGET_ID and target_layout_id != stereo_layout_id:
            continue

        render_manifest_path = artifact.get("render_manifest_path")
        if not isinstance(render_manifest_path, Path) or not render_manifest_path.exists():
            continue
        if render_manifest_path.is_dir():
            continue

        try:
            render_manifest = _load_json_object(
                render_manifest_path,
                label=f"Render manifest ({artifact.get('variant_id')})",
            )
        except ValueError:
            continue

        candidate_roots: list[Path] = []
        out_dir = artifact.get("out_dir")
        if isinstance(out_dir, Path):
            candidate_roots.append((out_dir / "render").resolve())
            candidate_roots.append(out_dir.resolve())
        candidate_roots.append((render_manifest_path.parent / "render").resolve())
        candidate_roots.append(render_manifest_path.parent.resolve())

        deduped_roots: list[Path] = []
        seen_roots: set[str] = set()
        for root in candidate_roots:
            token = root.as_posix()
            if token in seen_roots:
                continue
            seen_roots.add(token)
            deduped_roots.append(root)

        resolved = _wav_output_path_from_manifest(
            render_manifest=render_manifest,
            target_layout_id=stereo_layout_id,
            candidate_roots=deduped_roots,
            allow_fallback=(target_id == _BASELINE_RENDER_TARGET_ID),
        )
        if resolved is not None:
            return resolved
    return None


def _resolve_render_many_translation_cache_dir(
    *,
    root_out_dir: Path,
    cache_dir: Path | None,
) -> Path:
    if isinstance(cache_dir, Path):
        return cache_dir
    return root_out_dir / ".mmo_cache"


def _run_render_many_translation_checks(
    *,
    repo_root: Path,
    root_out_dir: Path,
    report_path: Path,
    variant_result: dict[str, Any],
    profile_ids: list[str],
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    timeline_path: Path | None,
    cache_dir: Path | None,
    use_cache: bool,
) -> None:
    if not profile_ids:
        return

    variant_artifacts = _render_many_variant_artifacts(
        variant_result=variant_result,
        root_out_dir=root_out_dir,
    )
    fallback_render_manifest_path: Path | None = None
    for artifact in variant_artifacts:
        manifest_path = artifact.get("render_manifest_path")
        if isinstance(manifest_path, Path) and manifest_path.exists() and not manifest_path.is_dir():
            fallback_render_manifest_path = manifest_path
            break

    resolved_deliverables_index_path = (
        deliverables_index_path
        if isinstance(deliverables_index_path, Path)
        else root_out_dir / "deliverables_index.json"
    )
    try:
        translation_audio_path, translation_reference_meta = resolve_translation_reference_audio(
            out_dir=root_out_dir,
            deliverables_index_path=resolved_deliverables_index_path,
            render_manifest_path=fallback_render_manifest_path,
        )
    except (TranslationReferenceResolutionError, ValueError):
        return

    translation_profiles_path = ontology_dir() /"translation_profiles.yaml"
    translation_profiles: dict[str, dict[str, Any]]
    translation_reference_payload: dict[str, Any] = dict(translation_reference_meta)
    audio_rel_path = _rel_path_if_under_root(root_out_dir, translation_audio_path)
    translation_reference_payload["audio_path"] = (
        audio_rel_path
        if isinstance(audio_rel_path, str) and audio_rel_path
        else translation_audio_path.resolve().as_posix()
    )
    try:
        translation_results = _build_translation_run_payload(
            translation_profiles_path=translation_profiles_path,
            audio_path=translation_audio_path,
            profile_ids=profile_ids,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        translation_results = _sorted_translation_results(translation_results)
        translation_profiles = load_translation_profiles(translation_profiles_path)
    except ValueError:
        return

    try:
        _write_report_with_translation_results(
            report_in_path=report_path,
            report_out_path=report_path,
            translation_results=translation_results,
            repo_root=None,
            profiles=translation_profiles,
            translation_reference=translation_reference_payload,
        )
    except (SystemExit, ValueError):
        return

    for artifact in variant_artifacts:
        variant_report_path = artifact.get("report_path")
        if isinstance(variant_report_path, Path) and variant_report_path.exists():
            try:
                _write_report_with_translation_results(
                    report_in_path=variant_report_path,
                    report_out_path=variant_report_path,
                    translation_results=translation_results,
                    repo_root=None,
                    profiles=translation_profiles,
                    translation_reference=translation_reference_payload,
                )
            except (SystemExit, ValueError):
                continue

        variant_bundle_path = artifact.get("bundle_path")
        if not isinstance(variant_bundle_path, Path):
            continue
        if not isinstance(variant_report_path, Path) or not variant_report_path.exists():
            continue

        try:
            _run_bundle(
                repo_root=None,
                report_path=variant_report_path,
                out_path=variant_bundle_path,
                render_manifest_path=artifact.get("render_manifest_path"),
                apply_manifest_path=artifact.get("apply_manifest_path"),
                applied_report_path=artifact.get("applied_report_path"),
                project_path=project_path,
                deliverables_index_path=deliverables_index_path,
                listen_pack_path=listen_pack_path,
                scene_path=None,
                render_plan_path=None,
                stems_index_path=None,
                stems_map_path=None,
                timeline_path=timeline_path,
            )
        except ValueError:
            continue


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _render_many_rel_posix(path: Path, *, root_out_dir: Path) -> str | None:
    rel_path = _rel_path_if_under_root(root_out_dir, path)
    if isinstance(rel_path, str) and rel_path:
        return rel_path
    return None


def _render_many_rel_posix_from_value(
    path_value: Any,
    *,
    root_out_dir: Path,
) -> str | None:
    raw = _coerce_str(path_value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root_out_dir / candidate).resolve()
    return _render_many_rel_posix(resolved, root_out_dir=root_out_dir)


def _translation_audition_summary_from_manifest(
    *,
    root_out_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    manifest_rel_path = _render_many_rel_posix(
        manifest_path.resolve(),
        root_out_dir=root_out_dir,
    )
    if manifest_rel_path is None:
        raise ValueError(f"Translation audition manifest path is outside root_out_dir: {manifest_path}")

    renders: list[dict[str, Any]] = []
    for row in _dict_list(manifest.get("renders")):
        profile_id = _coerce_str(row.get("profile_id")).strip()
        rel_render_path = _render_many_rel_posix_from_value(
            row.get("path"),
            root_out_dir=root_out_dir,
        )
        if not profile_id or rel_render_path is None:
            continue

        notes_raw = row.get("notes")
        notes = [
            item.strip()
            for item in notes_raw
            if isinstance(item, str) and item.strip()
        ] if isinstance(notes_raw, list) else []
        renders.append(
            {
                "profile_id": profile_id,
                "path": rel_render_path,
                "notes": notes,
            }
        )

    if not renders:
        return None
    renders.sort(
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            _coerce_str(item.get("path")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )

    segment_raw = manifest.get("segment")
    segment_payload: dict[str, float] | None = None
    if isinstance(segment_raw, dict):
        start_s = _coerce_float(segment_raw.get("start_s"))
        end_s = _coerce_float(segment_raw.get("end_s"))
        if start_s is not None and end_s is not None:
            segment_payload = {
                "start_s": start_s,
                "end_s": end_s,
            }

    return {
        "manifest_path": manifest_rel_path,
        "renders": renders,
        "segment": segment_payload,
    }


def _write_render_many_listen_pack_translation_auditions(
    *,
    root_out_dir: Path,
    listen_pack_path: Path | None,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    if not isinstance(listen_pack_path, Path):
        return
    if not listen_pack_path.exists() or listen_pack_path.is_dir():
        return

    resolved_root = root_out_dir.resolve()
    listen_pack_payload = _load_json_object(listen_pack_path, label="Listen pack")
    summary = _translation_audition_summary_from_manifest(
        root_out_dir=resolved_root,
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if summary is None:
        listen_pack_payload.pop("translation_auditions", None)
    else:
        listen_pack_payload["translation_auditions"] = summary

    _write_json_file(listen_pack_path, listen_pack_payload)


def _run_render_many_translation_auditions(
    *,
    repo_root: Path,
    root_out_dir: Path,
    variant_result: dict[str, Any],
    profile_ids: list[str],
    segment_s: float | None,
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    timeline_path: Path | None,
    cache_dir: Path | None,
    use_cache: bool,
) -> None:
    if not profile_ids:
        return

    stereo_target = get_render_target(
        _BASELINE_RENDER_TARGET_ID,
        ontology_dir() /"render_targets.yaml",
    )
    if not isinstance(stereo_target, dict):
        return
    stereo_layout_id = _coerce_str(stereo_target.get("layout_id")).strip()
    if not stereo_layout_id:
        return

    variant_artifacts = _render_many_variant_artifacts(
        variant_result=variant_result,
        root_out_dir=root_out_dir,
    )
    stereo_audio_path = _resolve_render_many_stereo_audio_path(
        variant_artifacts=variant_artifacts,
        stereo_layout_id=stereo_layout_id,
    )
    if stereo_audio_path is None:
        return

    translation_profiles_path = ontology_dir() /"translation_profiles.yaml"
    auditions_out_dir = root_out_dir / "listen_pack" / "translation_auditions"
    manifest_path = auditions_out_dir / "manifest.json"
    try:
        manifest = _build_translation_audition_payload(
            translation_profiles_path=translation_profiles_path,
            audio_path=stereo_audio_path,
            out_dir=auditions_out_dir,
            profile_ids=profile_ids,
            segment_s=segment_s,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        _write_translation_audition_manifest(manifest_path, manifest)
        _write_render_many_listen_pack_translation_auditions(
            root_out_dir=root_out_dir,
            listen_pack_path=listen_pack_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

        if not isinstance(listen_pack_path, Path):
            return
        if not listen_pack_path.exists() or listen_pack_path.is_dir():
            return

        for artifact in variant_artifacts:
            variant_report_path = artifact.get("report_path")
            variant_bundle_path = artifact.get("bundle_path")
            if not isinstance(variant_bundle_path, Path):
                continue
            if not isinstance(variant_report_path, Path) or not variant_report_path.exists():
                continue
            if variant_report_path.is_dir():
                continue

            try:
                _run_bundle(
                    repo_root=None,
                    report_path=variant_report_path,
                    out_path=variant_bundle_path,
                    render_manifest_path=artifact.get("render_manifest_path"),
                    apply_manifest_path=artifact.get("apply_manifest_path"),
                    applied_report_path=artifact.get("applied_report_path"),
                    project_path=project_path,
                    deliverables_index_path=deliverables_index_path,
                    listen_pack_path=listen_pack_path,
                    scene_path=None,
                    render_plan_path=None,
                    stems_index_path=None,
                    stems_map_path=None,
                    timeline_path=timeline_path,
                )
            except ValueError:
                continue
    except Exception as exc:
        print(
            f"warning: translation audition skipped: {exc}",
            file=sys.stderr,
        )


# NOTE: _load_report_from_path_or_dir may also exist in _registries.py.
# Included here for completeness; deduplicate later if needed.
def _load_report_from_path_or_dir(path: Path) -> tuple[dict[str, Any], Path | None]:
    if path.is_dir():
        report_path = path / "report.json"
        if not report_path.exists():
            raise ValueError(f"Missing report.json in directory: {path}")
        if report_path.is_dir():
            raise ValueError(f"Expected report JSON file path, got directory: {report_path}")
        return _load_report(report_path), path

    if not path.exists():
        raise ValueError(f"Report path does not exist: {path}")
    if path.is_dir():
        raise ValueError(f"Expected report JSON file path, got directory: {path}")
    return _load_report(path), None


# ── variants listen-pack command ─────────────────────────────────────


def _run_variants_listen_pack_command(
    *,
    repo_root: Path,
    presets_dir: Path,
    variant_result_path: Path,
    out_path: Path,
    stems_auditions_manifest: Path | None = None,
) -> int:
    try:
        variant_result = _load_json_object(variant_result_path, label="Variant result")
        listen_pack = _build_validated_listen_pack(
            repo_root=None,
            presets_dir=presets_dir,
            variant_result=variant_result,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    if isinstance(stems_auditions_manifest, Path):
        listen_pack["stems_auditions"] = index_stems_auditions(
            stems_auditions_manifest,
        )

    _write_json_file(out_path, listen_pack)
    return 0


# ── _run_variants_workflow ───────────────────────────────────────────


def _run_variants_workflow(
    *,
    repo_root: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_values: list[str] | None,
    config_values: list[str] | None,
    apply: bool,
    render: bool,
    export_pdf: bool,
    export_csv: bool,
    bundle: bool,
    scene: bool,
    render_plan: bool = False,
    profile: str | None = None,
    meters: str | None = None,
    max_seconds: float | None = None,
    routing: bool = False,
    source_layout: str | None = None,
    target_layout: str | None = None,
    downmix_qa: bool = False,
    qa_ref: str | None = None,
    qa_meters: str | None = None,
    qa_max_seconds: float | None = None,
    policy_id: str | None = None,
    truncate_values: int | None = None,
    output_formats: str | None = None,
    render_output_formats: str | None = None,
    apply_output_formats: str | None = None,
    format_set_values: list[str] | None = None,
    listen_pack: bool = False,
    deliverables_index: bool = False,
    project_path: Path | None = None,
    timeline_path: Path | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    run_config_overrides: dict[str, Any] = {}
    if profile is not None:
        run_config_overrides["profile_id"] = profile
    if meters is not None:
        run_config_overrides["meters"] = meters
    if max_seconds is not None:
        run_config_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_config_overrides["truncate_values"] = truncate_values
    if source_layout is not None:
        _set_nested(
            ["downmix", "source_layout_id"],
            run_config_overrides,
            source_layout,
        )
    if target_layout is not None:
        _set_nested(
            ["downmix", "target_layout_id"],
            run_config_overrides,
            target_layout,
        )
    if policy_id is not None:
        _set_nested(
            ["downmix", "policy_id"],
            run_config_overrides,
            policy_id,
        )
    if downmix_qa and not qa_ref:
        print(
            "Missing --qa-ref. Provide a stereo reference path when --downmix-qa is enabled.",
            file=sys.stderr,
        )
        return 1
    if qa_max_seconds is not None and qa_max_seconds < 0:
        print("--qa-max-seconds must be >= 0.", file=sys.stderr)
        return 1

    resolved_timeline_path: Path | None = None
    normalized_timeline: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            normalized_timeline = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    shared_output_formats: list[str] | None = None
    if output_formats is not None:
        try:
            shared_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    resolved_render_output_formats = (
        list(shared_output_formats) if isinstance(shared_output_formats, list) else None
    )
    if render_output_formats is not None:
        try:
            resolved_render_output_formats = _parse_output_formats_csv(
                render_output_formats
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    resolved_apply_output_formats = (
        list(shared_output_formats) if isinstance(shared_output_formats, list) else None
    )
    if apply_output_formats is not None:
        try:
            resolved_apply_output_formats = _parse_output_formats_csv(apply_output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if resolved_render_output_formats is not None:
        _set_nested(
            ["render", "output_formats"],
            run_config_overrides,
            resolved_render_output_formats,
        )
    if resolved_apply_output_formats is not None:
        _set_nested(
            ["apply", "output_formats"],
            run_config_overrides,
            resolved_apply_output_formats,
        )

    format_sets: list[tuple[str, list[str]]] | None = None
    if isinstance(format_set_values, list) and format_set_values:
        try:
            format_sets = _parse_output_format_sets(format_set_values)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    steps = {
        "analyze": True,
        "routing": routing,
        "downmix_qa": downmix_qa,
        "export_pdf": export_pdf,
        "export_csv": export_csv,
        "apply": apply,
        "render": render,
        "bundle": bundle,
    }
    try:
        plan = build_variant_plan(
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_ids=list(preset_values) if isinstance(preset_values, list) else None,
            config_paths=(
                [Path(item) for item in config_values]
                if isinstance(config_values, list)
                else None
            ),
            cli_run_config_overrides=run_config_overrides,
            steps=steps,
            format_sets=format_sets,
            presets_dir=presets_dir,
            source_layout_id=source_layout,
            target_layout_id=target_layout,
            qa_ref_path=Path(qa_ref) if qa_ref else None,
            qa_meters=qa_meters,
            qa_max_seconds=qa_max_seconds,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    plan_path = out_dir / "variant_plan.json"
    result_path = out_dir / "variant_result.json"
    listen_pack_path = out_dir / "listen_pack.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    try:
        _validate_json_payload(
            plan,
            schema_path=schemas_dir() /"variant_plan.schema.json",
            payload_name="Variant plan",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(plan_path, plan)
    variants = plan.get("variants")
    if isinstance(variants, list) and len(variants) > 1:
        print("Youll get one folder per variant.")

    try:
        run_variant_plan_kwargs: dict[str, Any] = {
            "cache_enabled": cache_enabled,
            "cache_dir": cache_dir,
        }
        if project_path is not None:
            run_variant_plan_kwargs["project_path"] = project_path
        if deliverables_index:
            run_variant_plan_kwargs["deliverables_index_path"] = deliverables_index_path
        if listen_pack:
            run_variant_plan_kwargs["listen_pack_path"] = listen_pack_path
        if normalized_timeline is not None:
            run_variant_plan_kwargs["timeline"] = normalized_timeline
        if resolved_timeline_path is not None:
            run_variant_plan_kwargs["timeline_path"] = resolved_timeline_path
        run_variant_plan_kwargs["scene"] = scene
        run_variant_plan_kwargs["render_plan"] = render_plan

        result = run_variant_plan(
            plan,
            repo_root=None,
            **run_variant_plan_kwargs,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _validate_json_payload(
            result,
            schema_path=schemas_dir() /"variant_result.schema.json",
            payload_name="Variant result",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(result_path, result)
    if listen_pack:
        try:
            listen_pack_payload = _build_validated_listen_pack(
                repo_root=None,
                presets_dir=presets_dir,
                variant_result=result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(listen_pack_path, listen_pack_payload)
    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_variants(
                repo_root=None,
                root_out_dir=out_dir,
                variant_result=result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    results = result.get("results")
    if not isinstance(results, list):
        return 1
    has_failure = any(
        isinstance(item, dict) and item.get("ok") is not True
        for item in results
    )
    return 1 if has_failure else 0


# ── _run_one_shot_workflow ───────────────────────────────────────────


def _run_one_shot_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_id: str | None,
    config_path: str | None,
    project_path: Path | None,
    timeline_path: Path | None,
    profile: str | None,
    meters: str | None,
    max_seconds: float | None,
    truncate_values: int | None,
    export_pdf: bool,
    export_csv: bool,
    apply: bool,
    render: bool,
    bundle: bool,
    scene: bool,
    render_plan: bool = False,
    deliverables_index: bool = False,
    output_formats: str | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    resolved_timeline_path: Path | None = None
    timeline_payload: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            timeline_payload = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    run_overrides: dict[str, Any] = {}
    if profile is not None:
        run_overrides["profile_id"] = profile
    if meters is not None:
        run_overrides["meters"] = meters
    if max_seconds is not None:
        run_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_overrides["truncate_values"] = truncate_values
    if output_formats is not None:
        try:
            parsed_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _set_nested(["render", "output_formats"], run_overrides, parsed_output_formats)
        _set_nested(["apply", "output_formats"], run_overrides, parsed_output_formats)

    try:
        merged_run_config = _load_and_merge_run_config(
            config_path,
            run_overrides,
            preset_id=preset_id,
            presets_dir=presets_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    effective_profile = _config_string(merged_run_config, "profile_id", "PROFILE.ASSIST")
    effective_meters = _config_optional_string(merged_run_config, "meters", None)
    effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
    effective_run_config = _analyze_run_config(
        profile_id=effective_profile,
        meters=effective_meters,
        preset_id=effective_preset_id,
        base_run_config=merged_run_config,
    )
    effective_truncate_values = _config_int(merged_run_config, "truncate_values", 200)
    render_output_formats = _config_nested_output_formats(
        merged_run_config,
        "render",
        ["wav"],
    )
    apply_output_formats = _config_nested_output_formats(
        merged_run_config,
        "apply",
        ["wav"],
    )

    report_path = out_dir / "report.json"
    pdf_path = out_dir / "report.pdf"
    csv_path = out_dir / "recall.csv"
    apply_manifest_path = out_dir / "apply_manifest.json"
    applied_report_path = out_dir / "applied_report.json"
    render_manifest_path = out_dir / "render_manifest.json"
    bundle_path = out_dir / "ui_bundle.json"
    scene_path = out_dir / "scene.json"
    render_plan_path = out_dir / "render_plan.json"
    routing_plan_path = out_dir / "routing_plan.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    render_out_dir = out_dir / "render"
    apply_out_dir = out_dir / "apply"

    report_schema_path = schemas_dir() /"report.schema.json"
    plugins_dir = str((_checkout_root / "plugins" if _checkout_root is not None else Path("plugins")))
    lock_payload: dict[str, Any] | None = None
    cache_key_value: str | None = None
    report_payload: dict[str, Any] | None = None
    scene_payload: dict[str, Any] | None = None

    out_dir.mkdir(parents=True, exist_ok=True)
    if cache_enabled:
        from mmo.core.lockfile import build_lockfile  # noqa: WPS433

        try:
            lock_payload = build_lockfile(stems_dir)
            cache_key_value = _analysis_cache_key(lock_payload, effective_run_config)
        except ValueError:
            cache_enabled = False
            lock_payload = None
            cache_key_value = None

        if lock_payload is not None:
            cached_report = try_load_cached_report(
                cache_dir,
                lock_payload,
                effective_run_config,
            )
            if (
                isinstance(cached_report, dict)
                and report_schema_is_valid(cached_report, report_schema_path)
            ):
                rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                rewritten_report["run_config"] = normalize_run_config(effective_run_config)
                apply_routing_plan_to_report(rewritten_report, rewritten_report["run_config"])
                if report_schema_is_valid(rewritten_report, report_schema_path):
                    try:
                        _validate_json_payload(
                            rewritten_report,
                            schema_path=report_schema_path,
                            payload_name="Report",
                        )
                    except SystemExit as exc:
                        return int(exc.code) if isinstance(exc.code, int) else 1
                    _write_json_file(report_path, rewritten_report)
                    report_payload = rewritten_report
                    print(f"analysis cache: hit {cache_key_value}")
            if report_payload is None:
                print(f"analysis cache: miss {cache_key_value}")

    if report_payload is None:
        exit_code = _run_analyze(
            tools_dir,
            stems_dir,
            report_path,
            effective_meters,
            False,
            plugins_dir,
            False,
            effective_profile,
        )
        if exit_code != 0:
            return exit_code
        try:
            report_payload = _load_report(report_path)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        report_payload["run_config"] = normalize_run_config(effective_run_config)
        apply_routing_plan_to_report(report_payload, report_payload["run_config"])
        try:
            _validate_json_payload(
                report_payload,
                schema_path=report_schema_path,
                payload_name="Report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(report_path, report_payload)

    if cache_enabled and lock_payload is not None and report_payload is not None:
        if report_schema_is_valid(report_payload, report_schema_path):
            if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
            else:
                try:
                    save_cached_report(
                        cache_dir,
                        lock_payload,
                        effective_run_config,
                        report_payload,
                    )
                except OSError:
                    pass

    if timeline_payload is not None and report_payload is not None:
        report_payload["timeline"] = timeline_payload
        try:
            _validate_json_payload(
                report_payload,
                schema_path=report_schema_path,
                payload_name="Report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(report_path, report_payload)

    if scene or render_plan:
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        try:
            scene_payload = _build_validated_scene_payload(
                repo_root=None,
                report=report_payload,
                timeline_payload=timeline_payload,
                lock_hash=(
                    hash_lockfile(lock_payload)
                    if isinstance(lock_payload, dict)
                    else None
                ),
                created_from="analyze",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)

    if render_plan:
        if report_payload is None or scene_payload is None:
            print("Scene/report payload is unavailable for render plan.", file=sys.stderr)
            return 1
        try:
            render_targets_payload = _default_render_plan_targets_payload(
                report=report_payload,
                render_targets_path=ontology_dir() /"render_targets.yaml",
            )
            routing_plan_artifact_path = _write_routing_plan_artifact(
                repo_root=None,
                report_payload=report_payload,
                out_path=routing_plan_path,
            )

            render_plan_contexts: list[str] = []
            if render:
                render_plan_contexts.append("render")
            if apply:
                render_plan_contexts.append("auto_apply")
            if not render_plan_contexts:
                render_plan_contexts = ["render"]

            render_plan_format_set: set[str] = set()
            if render:
                render_plan_format_set.update(render_output_formats)
            if apply:
                render_plan_format_set.update(apply_output_formats)
            if not render_plan_format_set:
                render_plan_format_set.update(render_output_formats)
            render_plan_output_formats = [
                fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in render_plan_format_set
            ]

            render_plan_payload = _build_validated_render_plan_payload(
                repo_root=None,
                scene_payload=scene_payload,
                scene_path=scene_path,
                render_targets_payload=render_targets_payload,
                routing_plan_path=routing_plan_artifact_path,
                output_formats=render_plan_output_formats,
                contexts=render_plan_contexts,
                policies=_render_plan_policies_from_report(report_payload),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(render_plan_path, render_plan_payload)

    exit_code = _run_export(
        tools_dir,
        report_path,
        str(csv_path) if export_csv else None,
        str(pdf_path) if export_pdf else None,
        no_measurements=False,
        no_gates=False,
        truncate_values=effective_truncate_values,
    )
    if exit_code != 0:
        return exit_code

    if apply:
        try:
            exit_code = _run_apply_command(
                repo_root=None,
                report_path=report_path,
                plugins_dir=Path(plugins_dir),
                out_manifest_path=apply_manifest_path,
                out_dir=apply_out_dir,
                out_report_path=None,
                profile_id=effective_profile,
                output_formats=apply_output_formats,
                run_config=effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

        try:
            apply_manifest = _load_json_object(apply_manifest_path, label="Apply manifest")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        renderer_manifests_raw = apply_manifest.get("renderer_manifests")
        if not isinstance(renderer_manifests_raw, list):
            print("Apply manifest renderer_manifests must be a list.", file=sys.stderr)
            return 1
        renderer_manifests = [
            item for item in renderer_manifests_raw if isinstance(item, dict)
        ]
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        applied_report = _build_applied_report(
            report_payload,
            out_dir=apply_out_dir,
            renderer_manifests=renderer_manifests,
        )
        try:
            _validate_json_payload(
                applied_report,
                schema_path=report_schema_path,
                payload_name="Applied report",
            )
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(applied_report_path, applied_report)

    if render:
        try:
            exit_code = _run_render_command(
                repo_root=None,
                report_path=report_path,
                plugins_dir=Path(plugins_dir),
                out_manifest_path=render_manifest_path,
                out_dir=render_out_dir,
                profile_id=effective_profile,
                command_label="render",
                output_formats=render_output_formats,
                run_config=effective_run_config,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

    if bundle:
        try:
            exit_code = _run_bundle(
                repo_root=None,
                report_path=report_path,
                out_path=bundle_path,
                render_manifest_path=render_manifest_path if render else None,
                apply_manifest_path=apply_manifest_path if apply else None,
                applied_report_path=applied_report_path if apply else None,
                project_path=project_path,
                deliverables_index_path=(
                    deliverables_index_path if deliverables_index else None
                ),
                listen_pack_path=None,
                scene_path=scene_path if scene_payload is not None else None,
                render_plan_path=render_plan_path if render_plan else None,
                stems_index_path=None,
                stems_map_path=None,
                timeline_path=resolved_timeline_path,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if exit_code != 0:
            return exit_code

    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_single(
                repo_root=None,
                out_dir=out_dir,
                report_path=report_path,
                apply_manifest_path=apply_manifest_path if apply else None,
                render_manifest_path=render_manifest_path if render else None,
                bundle_path=bundle_path if bundle else None,
                pdf_path=pdf_path if export_pdf else None,
                csv_path=csv_path if export_csv else None,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    summary: list[tuple[str, Path]] = [("report", report_path)]
    if export_pdf:
        summary.append(("report_pdf", pdf_path))
    if export_csv:
        summary.append(("recall_csv", csv_path))
    if apply:
        summary.append(("apply_manifest", apply_manifest_path))
        summary.append(("applied_report", applied_report_path))
    if render:
        summary.append(("render_manifest", render_manifest_path))
    if bundle:
        summary.append(("ui_bundle", bundle_path))
    if scene_payload is not None:
        summary.append(("scene", scene_path))
    if render_plan:
        summary.append(("render_plan", render_plan_path))
    if deliverables_index:
        summary.append(("deliverables_index", deliverables_index_path))

    print("run complete:")
    for label, path in summary:
        print(f"- {label}: {path.resolve().as_posix()}")
    return 0


# ── _run_render_many_workflow ────────────────────────────────────────


def _run_render_many_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    preset_id: str | None,
    config_path: str | None,
    project_path: Path | None,
    timeline_path: Path | None,
    profile: str | None,
    meters: str | None,
    max_seconds: float | None,
    truncate_values: int | None,
    export_pdf: bool,
    export_csv: bool,
    scene_requested: bool,
    render_plan_requested: bool,
    scene_template_ids: list[str] | None,
    target_ids: list[str],
    contexts: list[str],
    deliverables_index: bool,
    listen_pack: bool = False,
    translation_profile_ids: list[str] | None = None,
    translation_audition: bool = False,
    translation_audition_segment_s: float | None = _DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
    output_formats: str | None = None,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
) -> int:
    resolved_timeline_path: Path | None = None
    timeline_payload: dict[str, Any] | None = None
    if timeline_path is not None:
        resolved_timeline_path = timeline_path.resolve()
        try:
            timeline_payload = _load_timeline_payload(resolved_timeline_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    run_overrides: dict[str, Any] = {}
    if profile is not None:
        run_overrides["profile_id"] = profile
    if meters is not None:
        run_overrides["meters"] = meters
    if max_seconds is not None:
        run_overrides["max_seconds"] = max_seconds
    if truncate_values is not None:
        run_overrides["truncate_values"] = truncate_values
    if output_formats is not None:
        try:
            parsed_output_formats = _parse_output_formats_csv(output_formats)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _set_nested(["render", "output_formats"], run_overrides, parsed_output_formats)
        _set_nested(["apply", "output_formats"], run_overrides, parsed_output_formats)

    try:
        merged_run_config = _load_and_merge_run_config(
            config_path,
            run_overrides,
            preset_id=preset_id,
            presets_dir=presets_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    effective_profile = _config_string(merged_run_config, "profile_id", "PROFILE.ASSIST")
    effective_meters = _config_optional_string(merged_run_config, "meters", None)
    effective_preset_id = _config_optional_string(merged_run_config, "preset_id", None)
    effective_run_config = _analyze_run_config(
        profile_id=effective_profile,
        meters=effective_meters,
        preset_id=effective_preset_id,
        base_run_config=merged_run_config,
    )
    analysis_cache_run_config = _analysis_run_config_for_variant_cache(effective_run_config)
    render_output_formats = _config_nested_output_formats(
        merged_run_config,
        "render",
        ["wav"],
    )
    apply_output_formats = _config_nested_output_formats(
        merged_run_config,
        "apply",
        ["wav"],
    )

    report_path = out_dir / "report.json"
    scene_path = out_dir / "scene.json"
    render_plan_path = out_dir / "render_plan.json"
    routing_plan_path = out_dir / "routing_plan.json"
    variant_plan_path = out_dir / "variant_plan.json"
    variant_result_path = out_dir / "variant_result.json"
    listen_pack_path = out_dir / "listen_pack.json"
    deliverables_index_path = out_dir / "deliverables_index.json"
    report_schema_path = schemas_dir() /"report.schema.json"
    plugins_dir = str((_checkout_root / "plugins" if _checkout_root is not None else Path("plugins")))

    out_dir.mkdir(parents=True, exist_ok=True)

    should_build_scene = scene_requested or not scene_path.exists()
    should_build_render_plan = render_plan_requested or not render_plan_path.exists()
    needs_report = should_build_scene or should_build_render_plan

    lock_payload: dict[str, Any] | None = None
    cache_key_value: str | None = None
    report_payload: dict[str, Any] | None = None
    scene_payload: dict[str, Any] | None = None
    render_plan_payload: dict[str, Any] | None = None

    if needs_report:
        if cache_enabled:
            from mmo.core.lockfile import build_lockfile  # noqa: WPS433

            try:
                lock_payload = build_lockfile(stems_dir)
                cache_key_value = _analysis_cache_key(lock_payload, analysis_cache_run_config)
            except ValueError:
                cache_enabled = False
                lock_payload = None
                cache_key_value = None

            if lock_payload is not None:
                cached_report = try_load_cached_report(
                    cache_dir,
                    lock_payload,
                    analysis_cache_run_config,
                )
                if (
                    isinstance(cached_report, dict)
                    and report_schema_is_valid(cached_report, report_schema_path)
                ):
                    rewritten_report = rewrite_report_stems_dir(cached_report, stems_dir)
                    rewritten_report["run_config"] = normalize_run_config(effective_run_config)
                    apply_routing_plan_to_report(rewritten_report, rewritten_report["run_config"])
                    if report_schema_is_valid(rewritten_report, report_schema_path):
                        try:
                            _validate_json_payload(
                                rewritten_report,
                                schema_path=report_schema_path,
                                payload_name="Report",
                            )
                        except SystemExit as exc:
                            return int(exc.code) if isinstance(exc.code, int) else 1
                        _write_json_file(report_path, rewritten_report)
                        report_payload = rewritten_report
                        print(f"analysis cache: hit {cache_key_value}")
                if report_payload is None:
                    print(f"analysis cache: miss {cache_key_value}")

        if report_payload is None:
            exit_code = _run_analyze(
                tools_dir,
                stems_dir,
                report_path,
                effective_meters,
                False,
                plugins_dir,
                False,
                effective_profile,
            )
            if exit_code != 0:
                return exit_code
            try:
                report_payload = _load_report(report_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            report_payload["run_config"] = normalize_run_config(effective_run_config)
            apply_routing_plan_to_report(report_payload, report_payload["run_config"])
            try:
                _validate_json_payload(
                    report_payload,
                    schema_path=report_schema_path,
                    payload_name="Report",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(report_path, report_payload)

        if cache_enabled and lock_payload is not None and report_payload is not None:
            if report_schema_is_valid(report_payload, report_schema_path):
                if _should_skip_analysis_cache_save(report_payload, effective_run_config):
                    print(f"analysis cache: skip-save {cache_key_value} (time-cap stop)")
                else:
                    try:
                        save_cached_report(
                            cache_dir,
                            lock_payload,
                            analysis_cache_run_config,
                            report_payload,
                        )
                    except OSError:
                        pass

        if timeline_payload is not None and report_payload is not None:
            report_payload["timeline"] = timeline_payload
            try:
                _validate_json_payload(
                    report_payload,
                    schema_path=report_schema_path,
                    payload_name="Report",
                )
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else 1
            _write_json_file(report_path, report_payload)

    if should_build_scene:
        if report_payload is None:
            print("Report payload is unavailable after analysis.", file=sys.stderr)
            return 1
        try:
            scene_payload = _build_validated_scene_payload(
                repo_root=None,
                report=report_payload,
                timeline_payload=timeline_payload,
                lock_hash=(
                    hash_lockfile(lock_payload)
                    if isinstance(lock_payload, dict)
                    else None
                ),
                created_from="analyze",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)
    else:
        try:
            scene_payload = _load_json_object(scene_path, label="Scene")
            _validate_scene_schema(repo_root=None, scene_payload=scene_payload)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    if scene_payload is not None and isinstance(scene_template_ids, list) and scene_template_ids:
        try:
            scene_payload = _apply_scene_templates_to_payload(
                repo_root=None,
                scene_payload=scene_payload,
                template_ids=scene_template_ids,
                force=False,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(scene_path, scene_payload)

    if should_build_render_plan:
        if scene_payload is None:
            print("Scene payload is unavailable for render plan.", file=sys.stderr)
            return 1
        if report_payload is None:
            print("Report payload is unavailable for render plan.", file=sys.stderr)
            return 1
        try:
            render_targets_payload = _build_selected_render_targets_payload(
                target_ids=target_ids,
                render_targets_path=ontology_dir() /"render_targets.yaml",
            )
            routing_plan_artifact_path = _write_routing_plan_artifact(
                repo_root=None,
                report_payload=report_payload,
                out_path=routing_plan_path,
            )
            render_plan_format_set: set[str] = set()
            if "render" in contexts:
                render_plan_format_set.update(render_output_formats)
            if "auto_apply" in contexts:
                render_plan_format_set.update(apply_output_formats)
            if not render_plan_format_set:
                render_plan_format_set.update(render_output_formats)
            render_plan_output_formats = [
                fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in render_plan_format_set
            ]
            render_plan_payload = _build_validated_render_plan_payload(
                repo_root=None,
                scene_payload=scene_payload,
                scene_path=scene_path,
                render_targets_payload=render_targets_payload,
                routing_plan_path=routing_plan_artifact_path,
                output_formats=render_plan_output_formats,
                contexts=contexts,
                policies=_render_plan_policies_from_report(report_payload),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(render_plan_path, render_plan_payload)
    else:
        try:
            render_plan_payload = _load_json_object(render_plan_path, label="Render plan")
            _validate_json_payload(
                render_plan_payload,
                schema_path=schemas_dir() /"render_plan.schema.json",
                payload_name="Render plan",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    if scene_payload is None:
        try:
            scene_payload = _load_json_object(scene_path, label="Scene")
            _validate_scene_schema(repo_root=None, scene_payload=scene_payload)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
    if render_plan_payload is None:
        print("Render plan payload is unavailable.", file=sys.stderr)
        return 1

    scene_for_bridge = json.loads(json.dumps(scene_payload))
    scene_for_bridge["scene_path"] = scene_path.resolve().as_posix()
    render_plan_for_bridge = json.loads(json.dumps(render_plan_payload))
    render_plan_for_bridge["render_plan_path"] = render_plan_path.resolve().as_posix()
    bridge_default_steps = {
        "routing": False,
        "export_pdf": export_pdf,
        "export_csv": export_csv,
        "render": "render" in contexts,
        "apply": "auto_apply" in contexts,
        "bundle": True,
    }
    try:
        variant_plan = render_plan_to_variant_plan(
            render_plan_for_bridge,
            scene_for_bridge,
            base_out_dir=out_dir.resolve().as_posix(),
            default_steps=bridge_default_steps,
        )
        variant_plan = _apply_run_config_to_render_many_variant_plan(
            variant_plan=variant_plan,
            run_config=effective_run_config,
            preset_id=effective_preset_id,
            config_path=Path(config_path) if config_path else None,
        )
        _validate_json_payload(
            variant_plan,
            schema_path=schemas_dir() /"variant_plan.schema.json",
            payload_name="Variant plan",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(variant_plan_path, variant_plan)
    variants = variant_plan.get("variants")
    if isinstance(variants, list) and len(variants) > 1:
        print("Youll get one folder per variant.")

    run_variant_plan_kwargs: dict[str, Any] = {
        "cache_enabled": cache_enabled,
        "cache_dir": cache_dir,
    }
    if project_path is not None:
        run_variant_plan_kwargs["project_path"] = project_path
    if deliverables_index:
        run_variant_plan_kwargs["deliverables_index_path"] = deliverables_index_path
    if listen_pack:
        run_variant_plan_kwargs["listen_pack_path"] = listen_pack_path
    if timeline_payload is not None:
        run_variant_plan_kwargs["timeline"] = timeline_payload
    if resolved_timeline_path is not None:
        run_variant_plan_kwargs["timeline_path"] = resolved_timeline_path

    try:
        variant_result = run_variant_plan(
            variant_plan,
            repo_root=None,
            **run_variant_plan_kwargs,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _validate_json_payload(
            variant_result,
            schema_path=schemas_dir() /"variant_result.schema.json",
            payload_name="Variant result",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    _write_json_file(variant_result_path, variant_result)

    if listen_pack:
        try:
            listen_pack_payload = _build_validated_listen_pack(
                repo_root=None,
                presets_dir=presets_dir,
                variant_result=variant_result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(listen_pack_path, listen_pack_payload)
    if deliverables_index:
        try:
            deliverables_index_payload = _build_validated_deliverables_index_variants(
                repo_root=None,
                root_out_dir=out_dir,
                variant_result=variant_result,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1
        _write_json_file(deliverables_index_path, deliverables_index_payload)

    if isinstance(translation_profile_ids, list) and translation_profile_ids:
        translation_cache_dir = _resolve_render_many_translation_cache_dir(
            root_out_dir=out_dir,
            cache_dir=cache_dir,
        )
        _run_render_many_translation_checks(
            repo_root=None,
            root_out_dir=out_dir,
            report_path=report_path,
            variant_result=variant_result,
            profile_ids=list(translation_profile_ids),
            project_path=project_path,
            deliverables_index_path=(
                deliverables_index_path if deliverables_index else None
            ),
            listen_pack_path=listen_pack_path if listen_pack else None,
            timeline_path=resolved_timeline_path,
            cache_dir=translation_cache_dir,
            use_cache=cache_enabled,
        )
    if translation_audition:
        audition_profile_ids = (
            list(translation_profile_ids)
            if isinstance(translation_profile_ids, list) and translation_profile_ids
            else list(_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS)
        )
        translation_cache_dir = _resolve_render_many_translation_cache_dir(
            root_out_dir=out_dir,
            cache_dir=cache_dir,
        )
        _run_render_many_translation_auditions(
            repo_root=None,
            root_out_dir=out_dir,
            variant_result=variant_result,
            profile_ids=audition_profile_ids,
            segment_s=translation_audition_segment_s,
            project_path=project_path,
            deliverables_index_path=(
                deliverables_index_path if deliverables_index else None
            ),
            listen_pack_path=listen_pack_path if listen_pack else None,
            timeline_path=resolved_timeline_path,
            cache_dir=translation_cache_dir,
            use_cache=cache_enabled,
        )

    results = variant_result.get("results")
    if not isinstance(results, list):
        return 1

    summary: list[tuple[str, Path]] = [
        ("scene", scene_path),
        ("render_plan", render_plan_path),
        ("variant_plan", variant_plan_path),
        ("variant_result", variant_result_path),
    ]
    if listen_pack:
        summary.append(("listen_pack", listen_pack_path))
    if deliverables_index:
        summary.append(("deliverables_index", deliverables_index_path))
    print("render-many complete:")
    for label, path in summary:
        print(f"- {label}: {path.resolve().as_posix()}")

    has_failure = any(
        isinstance(item, dict) and item.get("ok") is not True
        for item in results
    )
    return 1 if has_failure else 0


# ── _run_workflow_from_run_args ──────────────────────────────────────


def _run_workflow_from_run_args(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    args: argparse.Namespace,
) -> tuple[int, str]:
    preset_values = list(args.preset) if isinstance(args.preset, list) else []
    config_values = list(args.config) if isinstance(args.config, list) else []
    format_set_values = list(args.format_set) if isinstance(args.format_set, list) else []
    project_path: Path | None = None
    project_path_value = getattr(args, "project", None)
    if isinstance(project_path_value, str) and project_path_value.strip():
        project_path = Path(project_path_value)
    timeline_path: Path | None = None
    timeline_path_value = getattr(args, "timeline", None)
    if isinstance(timeline_path_value, str) and timeline_path_value.strip():
        timeline_path = Path(timeline_path_value)
    if getattr(args, "render_many", False):
        if len(preset_values) > 1 or len(config_values) > 1 or bool(format_set_values):
            print(
                (
                    "--render-many supports at most one --preset, at most one --config, "
                    "and does not support --format-set."
                ),
                file=sys.stderr,
            )
            return 1, "variants"
        try:
            target_ids = _parse_target_ids_csv(
                getattr(args, "targets", _BASELINE_RENDER_TARGET_ID),
                render_targets_path=ontology_dir() /"render_targets.yaml",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1, "variants"

        context_values = (
            list(args.context)
            if isinstance(getattr(args, "context", None), list)
            else []
        )
        context_set = {
            _coerce_str(item).strip().lower()
            for item in context_values
            if _coerce_str(item).strip()
        }
        contexts = [
            item
            for item in ("render", "auto_apply")
            if item in context_set
        ]
        if not contexts:
            contexts = ["render"]
        scene_template_ids: list[str] = []
        scene_templates_value = getattr(args, "scene_templates", None)
        if isinstance(scene_templates_value, str) and scene_templates_value.strip():
            try:
                scene_template_ids = _parse_scene_template_ids_csv(scene_templates_value)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1, "variants"

        translation_profiles_path = ontology_dir() /"translation_profiles.yaml"
        translation_profiles_value = getattr(args, "translation_profiles", None)
        translation_enabled = bool(getattr(args, "translation", False))
        translation_profile_ids: list[str] | None = None
        if isinstance(translation_profiles_value, str) and translation_profiles_value.strip():
            try:
                translation_profile_ids = _parse_translation_profile_ids_csv(
                    translation_profiles_value,
                    translation_profiles_path=translation_profiles_path,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1, "variants"
            translation_enabled = True
        if translation_enabled and translation_profile_ids is None:
            translation_profile_ids = list(_DEFAULT_RENDER_MANY_TRANSLATION_PROFILE_IDS)
        translation_audition_enabled = bool(getattr(args, "translation_audition", False))
        translation_audition_segment_s: float | None = None
        if translation_audition_enabled:
            raw_segment = getattr(
                args,
                "translation_audition_segment",
                _DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S,
            )
            if (
                isinstance(raw_segment, bool)
                or not isinstance(raw_segment, (int, float))
                or not math.isfinite(float(raw_segment))
                or float(raw_segment) <= 0.0
            ):
                print(
                    "--translation-audition-segment must be a positive number of seconds.",
                    file=sys.stderr,
                )
                return 1, "variants"
            translation_audition_segment_s = float(raw_segment)

        exit_code = _run_render_many_workflow(
            repo_root=None,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_id=preset_values[0] if preset_values else None,
            config_path=config_values[0] if config_values else None,
            project_path=project_path,
            timeline_path=timeline_path,
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            truncate_values=args.truncate_values,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            scene_requested=getattr(args, "scene", False),
            render_plan_requested=getattr(args, "render_plan", False),
            scene_template_ids=scene_template_ids,
            target_ids=target_ids,
            contexts=contexts,
            deliverables_index=args.deliverables_index,
            listen_pack=getattr(args, "listen_pack", False),
            translation_profile_ids=translation_profile_ids,
            translation_audition=translation_audition_enabled,
            translation_audition_segment_s=translation_audition_segment_s,
            output_formats=args.output_formats,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
        return exit_code, "variants"

    should_delegate_to_variants = (
        args.variants
        or len(preset_values) > 1
        or len(config_values) > 1
        or bool(format_set_values)
    )
    if should_delegate_to_variants:
        exit_code = _run_variants_workflow(
            repo_root=None,
            presets_dir=presets_dir,
            stems_dir=stems_dir,
            out_dir=out_dir,
            preset_values=preset_values if preset_values else None,
            config_values=config_values if config_values else None,
            apply=args.apply,
            render=args.render,
            export_pdf=args.export_pdf,
            export_csv=args.export_csv,
            bundle=args.bundle,
            scene=getattr(args, "scene", False),
            render_plan=getattr(args, "render_plan", False),
            profile=args.profile,
            meters=args.meters,
            max_seconds=args.max_seconds,
            routing=False,
            downmix_qa=False,
            qa_ref=None,
            qa_meters=None,
            qa_max_seconds=None,
            truncate_values=args.truncate_values,
            output_formats=args.output_formats,
            format_set_values=format_set_values if format_set_values else None,
            listen_pack=getattr(args, "listen_pack", False),
            deliverables_index=args.deliverables_index,
            project_path=project_path,
            timeline_path=timeline_path,
            cache_enabled=args.cache == "on",
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        )
        return exit_code, "variants"

    exit_code = _run_one_shot_workflow(
        repo_root=None,
        tools_dir=tools_dir,
        presets_dir=presets_dir,
        stems_dir=stems_dir,
        out_dir=out_dir,
        preset_id=preset_values[0] if preset_values else None,
        config_path=config_values[0] if config_values else None,
        project_path=project_path,
        timeline_path=timeline_path,
        profile=args.profile,
        meters=args.meters,
        max_seconds=args.max_seconds,
        truncate_values=args.truncate_values,
        export_pdf=args.export_pdf,
        export_csv=args.export_csv,
        apply=args.apply,
        render=args.render,
        bundle=args.bundle,
        scene=getattr(args, "scene", False),
        render_plan=getattr(args, "render_plan", False),
        deliverables_index=args.deliverables_index,
        output_formats=args.output_formats,
        cache_enabled=args.cache == "on",
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
    )
    return exit_code, "single"


# ── UI helpers ───────────────────────────────────────────────────────


def _ui_count_list(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _ui_lockfile_status(
    *,
    stems_dir: Path,
    project_payload: dict[str, Any],
    nerd: bool,
) -> str:
    from mmo.core.lockfile import verify_lockfile  # noqa: WPS433

    lockfile_path_value = project_payload.get("lockfile_path")
    if not isinstance(lockfile_path_value, str) or not lockfile_path_value.strip():
        return "missing"

    lockfile_path = Path(lockfile_path_value)
    if not lockfile_path.exists():
        if nerd:
            return f"missing ({lockfile_path.resolve().as_posix()})"
        return "missing"

    try:
        lock_payload = _load_json_object(lockfile_path, label="Lockfile")
        verify_result = verify_lockfile(stems_dir, lock_payload)
    except ValueError as exc:
        if nerd:
            return f"invalid ({exc})"
        return "invalid"

    if verify_result.get("ok") is True:
        return "in sync"

    missing_count = _ui_count_list(verify_result.get("missing"))
    extra_count = _ui_count_list(verify_result.get("extra"))
    changed_count = _ui_count_list(verify_result.get("changed"))
    return (
        "drift"
        f" (missing={missing_count}, extra={extra_count}, changed={changed_count})"
    )


def _ui_last_run_pointer_rows(project_payload: dict[str, Any]) -> list[tuple[str, str]]:
    last_run = project_payload.get("last_run")
    if not isinstance(last_run, dict):
        return []

    rows: list[tuple[str, str]] = []
    key_map = [
        ("mode", "mode"),
        ("out_dir", "out_dir"),
        ("deliverables_index_path", "deliverables_index"),
        ("listen_pack_path", "listen_pack"),
        ("variant_plan_path", "variant_plan"),
        ("variant_result_path", "variant_result"),
    ]
    for key, label in key_map:
        value = last_run.get(key)
        if isinstance(value, str) and value.strip():
            rows.append((label, value.strip()))
    return rows


def _ui_report_path_from_variant_result(variant_result_path: Path) -> Path | None:
    try:
        payload = _load_json_object(variant_result_path, label="Variant result")
    except ValueError:
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        return None

    normalized_results = sorted(
        [item for item in results if isinstance(item, dict)],
        key=lambda item: str(item.get("variant_id", "")),
    )
    for item in normalized_results:
        report_path_value = item.get("report_path")
        if not isinstance(report_path_value, str) or not report_path_value.strip():
            continue
        report_path = Path(report_path_value.strip())
        if not report_path.is_absolute():
            out_dir_value = item.get("out_dir")
            if isinstance(out_dir_value, str) and out_dir_value.strip():
                report_path = Path(out_dir_value.strip()) / report_path
            else:
                report_path = variant_result_path.parent / report_path
        if report_path.exists():
            return report_path.resolve()
    return None


def _ui_report_path_from_project(project_payload: dict[str, Any]) -> Path | None:
    last_run = project_payload.get("last_run")
    if not isinstance(last_run, dict):
        return None

    mode = last_run.get("mode")
    out_dir_value = last_run.get("out_dir")
    if mode == "single" and isinstance(out_dir_value, str) and out_dir_value.strip():
        candidate = Path(out_dir_value.strip()) / "report.json"
        if candidate.exists():
            return candidate.resolve()

    variant_result_candidates: list[Path] = []
    variant_result_path_value = last_run.get("variant_result_path")
    if isinstance(variant_result_path_value, str) and variant_result_path_value.strip():
        variant_result_candidates.append(Path(variant_result_path_value.strip()))
    if isinstance(out_dir_value, str) and out_dir_value.strip():
        variant_result_candidates.append(Path(out_dir_value.strip()) / "variant_result.json")

    for candidate in variant_result_candidates:
        if not candidate.exists():
            continue
        report_path = _ui_report_path_from_variant_result(candidate)
        if report_path is not None:
            return report_path
    return None


def _ui_workflow_help_short_map(repo_root: Path) -> dict[str, str]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    help_ids = ["HELP.WORKFLOW.RUN", "HELP.WORKFLOW.VARIANTS_RUN"]
    try:
        registry = load_help_registry(ontology_dir() /"help.yaml")
        resolved = resolve_help_entries(help_ids, registry)
    except (RuntimeError, ValueError):
        return {}

    payload: dict[str, str] = {}
    for help_id in help_ids:
        entry = resolved.get(help_id)
        if not isinstance(entry, dict):
            continue
        short = entry.get("short")
        if not isinstance(short, str):
            continue
        normalized_short = short.strip()
        if not normalized_short or normalized_short == "Missing help entry":
            continue
        payload[help_id] = normalized_short
    return payload


def _ui_render_preview_text(payload: dict[str, Any], *, nerd: bool) -> str:
    if nerd:
        lines = [_render_preset_preview_text(payload)]
        effective_run_config = payload.get("effective_run_config")
        if isinstance(effective_run_config, dict):
            profile_id = effective_run_config.get("profile_id")
            meters = effective_run_config.get("meters")
            max_seconds = effective_run_config.get("max_seconds")
            lines.append("")
            lines.append(f"profile_id: {profile_id}")
            lines.append(f"meters: {meters}")
            lines.append(f"max_seconds: {max_seconds}")
            lines.append("effective_run_config:")
            lines.append(json.dumps(effective_run_config, indent=2, sort_keys=True))
        return "\n".join(lines)

    label = payload.get("label")
    overlay = payload.get("overlay")
    help_payload = payload.get("help")
    warnings = payload.get("warnings")

    normalized_label = label if isinstance(label, str) and label.strip() else "Preset"
    normalized_overlay = overlay if isinstance(overlay, str) and overlay.strip() else "None"
    short = ""
    cues: list[str] = []
    watch_out_for: list[str] = []
    if isinstance(help_payload, dict):
        short_value = help_payload.get("short")
        if isinstance(short_value, str):
            short = short_value
        cues = _string_list(help_payload.get("cues"))
        watch_out_for = _string_list(help_payload.get("watch_out_for"))
    warning_rows = _string_list(warnings)
    for warning in warning_rows:
        if warning not in watch_out_for:
            watch_out_for.append(warning)

    lines = [
        f"{normalized_label}  [{normalized_overlay}]",
        f"What it does: {short}",
        "Try it when:",
    ]
    for cue in cues[:4]:
        lines.append(f"  - {cue}")
    lines.append("Watch out for:")
    for item in watch_out_for[:4]:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def _ui_first_variant_bundle_path(out_dir: Path) -> Path | None:
    variant_result_path = out_dir / "variant_result.json"
    if variant_result_path.exists():
        try:
            payload = _load_json_object(variant_result_path, label="Variant result")
        except ValueError:
            payload = {}
        results = payload.get("results")
        if isinstance(results, list):
            normalized_results = sorted(
                [item for item in results if isinstance(item, dict)],
                key=lambda item: str(item.get("variant_id", "")),
            )
            for item in normalized_results:
                bundle_path_value = item.get("bundle_path")
                if not isinstance(bundle_path_value, str) or not bundle_path_value.strip():
                    continue
                candidate = Path(bundle_path_value.strip())
                if candidate.exists():
                    return candidate.resolve()
    for candidate in sorted(out_dir.glob("VARIANT.*__*/ui_bundle.json")):
        if candidate.exists():
            return candidate.resolve()
    return None


# ── _run_ui_workflow ─────────────────────────────────────────────────


def _run_ui_workflow(
    *,
    repo_root: Path,
    tools_dir: Path,
    presets_dir: Path,
    stems_dir: Path,
    out_dir: Path,
    project_path: Path | None,
    nerd: bool,
    input_provider: _UIInputProvider = input,
    output: _UIOutputWriter = print,
) -> int:
    resolved_stems_dir = stems_dir.resolve()
    resolved_out_dir = out_dir.resolve()
    resolved_project_path = project_path.resolve() if project_path is not None else None

    project_payload: dict[str, Any] | None = None
    if resolved_project_path is not None:
        try:
            project_payload = load_project(resolved_project_path)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    render_header(
        "MMO UI Launcher",
        subtitle="Preset picker -> preview -> run",
        output=output,
    )
    output(f"Stems dir: {resolved_stems_dir.as_posix()}")
    output(f"Output dir: {resolved_out_dir.as_posix()}")
    if project_payload is not None and resolved_project_path is not None:
        output(f"Project: {resolved_project_path.as_posix()}")
        output(
            "Lockfile status: "
            + _ui_lockfile_status(
                stems_dir=resolved_stems_dir,
                project_payload=project_payload,
                nerd=nerd,
            )
        )
        pointer_rows = _ui_last_run_pointer_rows(project_payload)
        if pointer_rows:
            output("Last run pointers:")
            for label, value in pointer_rows:
                output(f"- {label}: {value}")
        else:
            output("Last run pointers: none")
    else:
        output("Project: none")

    try:
        all_presets = list_presets(presets_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not all_presets:
        print("No presets are available.", file=sys.stderr)
        return 1

    render_header("Choose a vibe preset", output=output)
    overlay_values = {
        item.get("overlay").strip()
        for item in all_presets
        if isinstance(item, dict)
        and isinstance(item.get("overlay"), str)
        and item.get("overlay", "").strip()
    }
    chips = [chip for chip in _UI_OVERLAY_CHIPS if chip in overlay_values]
    if chips:
        output("Overlay chips: " + " ".join(f"[{chip}]" for chip in chips))

    recommendation_report_path: Path | None = None
    if project_payload is not None:
        recommendation_report_path = _ui_report_path_from_project(project_payload)
    if recommendation_report_path is None:
        out_report_path = resolved_out_dir / "report.json"
        if out_report_path.exists():
            recommendation_report_path = out_report_path
    if recommendation_report_path is None:
        quick_report_path = resolved_out_dir / ".ui_recommend_report.json"
        output("No prior report found. Running a quick scan for recommendations...")
        quick_report_path.parent.mkdir(parents=True, exist_ok=True)
        exit_code = _run_analyze(
            tools_dir,
            resolved_stems_dir,
            quick_report_path,
            None,
            False,
            str((_checkout_root / "plugins" if _checkout_root is not None else Path("plugins"))),
            False,
            "PROFILE.ASSIST",
        )
        if exit_code == 0 and quick_report_path.exists():
            recommendation_report_path = quick_report_path

    recommendations: list[dict[str, Any]] = []
    if recommendation_report_path is not None:
        try:
            recommendations = _build_preset_recommendations_payload(
                report_path=recommendation_report_path,
                presets_dir=presets_dir,
                n=3,
            )
        except ValueError:
            recommendations = []

    preset_by_id: dict[str, dict[str, Any]] = {}
    for item in all_presets:
        if not isinstance(item, dict):
            continue
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str):
            preset_by_id[preset_id] = item

    recommended_ids: list[str] = []
    for item in recommendations:
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str) and preset_id in preset_by_id:
            recommended_ids.append(preset_id)
    if recommended_ids:
        output("Recommended:")
        for preset_id in recommended_ids:
            preset = preset_by_id[preset_id]
            label = preset.get("label", "")
            overlay = preset.get("overlay", "")
            recommendation = next(
                (
                    row
                    for row in recommendations
                    if isinstance(row, dict) and row.get("preset_id") == preset_id
                ),
                {},
            )
            reasons = (
                recommendation.get("reasons")
                if isinstance(recommendation, dict)
                else []
            )
            first_reason = ""
            if isinstance(reasons, list):
                for reason in reasons:
                    if isinstance(reason, str) and reason.strip():
                        first_reason = reason.strip()
                        break
            if nerd:
                output(f"- {preset_id} | {label} | overlay={overlay}")
            else:
                overlay_suffix = f" [{overlay}]" if isinstance(overlay, str) and overlay else ""
                output(f"- {label}{overlay_suffix}")
            if first_reason:
                output(f"  reason: {first_reason}")

    filter_mode_index = choose_from_list(
        "Filter presets",
        ["No filter", "By tag", "By category"],
        default_index=0,
        input_provider=input_provider,
        output=output,
    )
    filter_tag: str | None = None
    filter_category: str | None = None

    if filter_mode_index == 1:
        tags = sorted(
            {
                tag
                for item in all_presets
                if isinstance(item, dict)
                for tag in _string_list(item.get("tags"))
            }
        )
        if tags:
            selected_tag_index = choose_from_list(
                "Choose tag",
                tags,
                default_index=0,
                input_provider=input_provider,
                output=output,
            )
            filter_tag = tags[selected_tag_index]
    elif filter_mode_index == 2:
        categories = sorted(
            {
                item.get("category").strip()
                for item in all_presets
                if isinstance(item, dict)
                and isinstance(item.get("category"), str)
                and item.get("category", "").strip()
            }
        )
        if categories:
            selected_category_index = choose_from_list(
                "Choose category",
                categories,
                default_index=0,
                input_provider=input_provider,
                output=output,
            )
            filter_category = categories[selected_category_index]

    filtered_presets = list_presets(
        presets_dir,
        tag=filter_tag,
        category=filter_category,
    )
    if not filtered_presets:
        output("No presets matched that filter. Showing all presets instead.")
        filtered_presets = list(all_presets)

    option_labels: list[str] = []
    for item in filtered_presets:
        preset_id = item.get("preset_id")
        label = item.get("label", "")
        overlay = item.get("overlay", "")
        category = item.get("category", "")
        recommended_suffix = (
            " (Recommended)"
            if isinstance(preset_id, str) and preset_id in recommended_ids
            else ""
        )
        if nerd:
            option_labels.append(
                f"{label} ({preset_id}) [{category}] overlay={overlay}{recommended_suffix}"
            )
        else:
            overlay_suffix = (
                f" [{overlay}]"
                if isinstance(overlay, str) and overlay.strip()
                else ""
            )
            option_labels.append(f"{label}{overlay_suffix}{recommended_suffix}")

    default_preset_index = 0
    for index, item in enumerate(filtered_presets):
        preset_id = item.get("preset_id")
        if isinstance(preset_id, str) and preset_id in recommended_ids:
            default_preset_index = index
            break

    selected_preset_index = choose_from_list(
        "Choose preset",
        option_labels,
        default_index=default_preset_index,
        input_provider=input_provider,
        output=output,
    )
    selected_preset = filtered_presets[selected_preset_index]
    selected_preset_id = selected_preset.get("preset_id", "")
    if not isinstance(selected_preset_id, str) or not selected_preset_id.strip():
        print("Selected preset is missing preset_id.", file=sys.stderr)
        return 1

    try:
        preview_payload = _build_preset_preview_payload(
            repo_root=None,
            presets_dir=presets_dir,
            preset_id=selected_preset_id,
            config_path=None,
            cli_overrides={},
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    render_header("Preset preview", output=output)
    output(_ui_render_preview_text(preview_payload, nerd=nerd))

    help_short_map = _ui_workflow_help_short_map(repo_root)
    run_help_text = help_short_map.get("HELP.WORKFLOW.RUN")
    if isinstance(run_help_text, str) and run_help_text:
        output("")
        output(f"Run workflow: {run_help_text}")

    use_variants = yes_no(
        "Use variants mode (needed for listen pack)?",
        default=False,
        input_provider=input_provider,
        output=output,
    )
    if use_variants:
        variants_help_text = help_short_map.get("HELP.WORKFLOW.VARIANTS_RUN")
        if isinstance(variants_help_text, str) and variants_help_text:
            output(f"Variants workflow: {variants_help_text}")

    step_options: list[dict[str, Any]] = [
        {"key": "analyze", "label": "Analyze", "enabled": True, "locked": True},
        {"key": "export_pdf", "label": "Export PDF", "enabled": False},
        {"key": "export_csv", "label": "Export CSV", "enabled": False},
        {"key": "apply", "label": "Apply (auto-apply)", "enabled": False},
        {"key": "render", "label": "Render (render suggestions)", "enabled": False},
        {"key": "bundle", "label": "Bundle", "enabled": True, "locked": True},
        {"key": "deliverables_index", "label": "Deliverables index", "enabled": True},
    ]
    if use_variants:
        step_options.append(
            {"key": "listen_pack", "label": "Listen pack", "enabled": False}
        )
    step_state = multi_toggle(
        "Choose steps",
        step_options,
        input_provider=input_provider,
        output=output,
    )

    export_pdf = step_state.get("export_pdf") is True
    export_csv = step_state.get("export_csv") is True
    apply = step_state.get("apply") is True
    render = step_state.get("render") is True
    deliverables_index = step_state.get("deliverables_index") is True
    listen_pack = use_variants and step_state.get("listen_pack") is True

    render_header("Run", output=output)
    if use_variants:
        exit_code = _run_variants_workflow(
            repo_root=None,
            presets_dir=presets_dir,
            stems_dir=resolved_stems_dir,
            out_dir=resolved_out_dir,
            preset_values=[selected_preset_id],
            config_values=None,
            apply=apply,
            render=render,
            export_pdf=export_pdf,
            export_csv=export_csv,
            bundle=True,
            scene=False,
            profile=None,
            meters=None,
            max_seconds=None,
            routing=False,
            source_layout=None,
            target_layout=None,
            downmix_qa=False,
            qa_ref=None,
            qa_meters=None,
            qa_max_seconds=None,
            policy_id=None,
            truncate_values=None,
            output_formats=None,
            render_output_formats=None,
            apply_output_formats=None,
            format_set_values=None,
            listen_pack=listen_pack,
            deliverables_index=deliverables_index,
            project_path=resolved_project_path,
            cache_enabled=True,
            cache_dir=None,
        )
        run_mode = "variants"
    else:
        exit_code = _run_one_shot_workflow(
            repo_root=None,
            tools_dir=tools_dir,
            presets_dir=presets_dir,
            stems_dir=resolved_stems_dir,
            out_dir=resolved_out_dir,
            preset_id=selected_preset_id,
            config_path=None,
            project_path=resolved_project_path,
            timeline_path=None,
            profile=None,
            meters=None,
            max_seconds=None,
            truncate_values=None,
            export_pdf=export_pdf,
            export_csv=export_csv,
            apply=apply,
            render=render,
            bundle=True,
            scene=False,
            deliverables_index=deliverables_index,
            output_formats=None,
            cache_enabled=True,
            cache_dir=None,
        )
        run_mode = "single"
    if exit_code != 0:
        return exit_code

    if resolved_project_path is not None and project_payload is not None:
        try:
            project_payload = update_project_last_run(
                project_payload,
                _project_last_run_payload(mode=run_mode, out_dir=resolved_out_dir),
            )
            run_config_defaults = _project_run_config_defaults(
                mode=run_mode,
                out_dir=resolved_out_dir,
            )
            if isinstance(run_config_defaults, dict):
                project_payload["run_config_defaults"] = run_config_defaults

            try:
                from mmo.core.lockfile import build_lockfile  # noqa: WPS433

                lock_payload = build_lockfile(resolved_stems_dir)
            except ValueError:
                lock_payload = None
            if isinstance(lock_payload, dict):
                lockfile_path = resolved_out_dir / "lockfile.json"
                _write_json_file(lockfile_path, lock_payload)
                project_payload["lockfile_path"] = lockfile_path.as_posix()
                project_payload["lock_hash"] = hash_lockfile(lock_payload)

            write_project(resolved_project_path, project_payload)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    render_header("Finish", output=output)
    if use_variants:
        bundle_path = _ui_first_variant_bundle_path(resolved_out_dir)
    else:
        bundle_path = resolved_out_dir / "ui_bundle.json"
        if not bundle_path.exists():
            bundle_path = None

    if bundle_path is not None:
        output(f"ui_bundle.json: {bundle_path.resolve().as_posix()}")
    else:
        output("ui_bundle.json: not generated")

    deliverables_index_path = resolved_out_dir / "deliverables_index.json"
    if deliverables_index_path.exists():
        output(
            "deliverables_index.json: "
            + deliverables_index_path.resolve().as_posix()
        )
    else:
        output("deliverables_index.json: not generated")

    if listen_pack:
        listen_pack_path = resolved_out_dir / "listen_pack.json"
        if listen_pack_path.exists():
            output(f"listen_pack.json: {listen_pack_path.resolve().as_posix()}")

    if use_variants:
        output("Tip: open deliverables_index.json, then the first variant ui_bundle.json.")
    else:
        output("Tip: open ui_bundle.json first, then check report.json for details.")
    return 0
