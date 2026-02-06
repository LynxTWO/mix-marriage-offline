from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any

from mmo.core.presets import list_presets

LISTEN_PACK_SCHEMA_VERSION = "0.1.0"
_TRANSLATION_SAFE_PRESET_ID = "PRESET.VIBE.TRANSLATION_SAFE"
_SAFE_CLEANUP_PRESET_ID = "PRESET.SAFE_CLEANUP"
_RISK_LEVELS = {"low", "medium", "high"}
_FORMAT_SET_SUFFIX_RE = re.compile(r"\[([a-z0-9_]+)\]\s*$")
_VARIANT_ID_RE = re.compile(r"^VARIANT\.(\d+)$")


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_posix_path(value: Any) -> str | None:
    normalized = _coerce_str(value).strip()
    if not normalized or "\\" in normalized:
        return None
    return normalized


def _path_parent(path_value: str) -> str:
    return Path(path_value).parent.as_posix()


def _read_json_object(path_value: str | None) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value.strip():
        return {}
    path = Path(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _variant_sort_key(variant_id: str, variant_slug: str) -> tuple[int, int, str, str]:
    match = _VARIANT_ID_RE.fullmatch(variant_id)
    if match is None:
        return (1, 0, variant_id, variant_slug)
    return (0, int(match.group(1)), variant_id, variant_slug)


def _format_set_name(plan_variant: dict[str, Any], variant_slug: str) -> str:
    label = _coerce_str(plan_variant.get("label")).strip()
    if label:
        match = _FORMAT_SET_SUFFIX_RE.search(label)
        if match is not None:
            return match.group(1)

    if "__" in variant_slug:
        candidate = variant_slug.rsplit("__", 1)[-1]
        if len(candidate) > 1 and re.fullmatch(r"[a-z0-9_]+", candidate):
            return candidate
    return ""


def _preset_metadata_map(presets_dir: Path) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for item in list_presets(presets_dir):
        if not isinstance(item, dict):
            continue
        preset_id = _coerce_str(item.get("preset_id")).strip()
        if not preset_id:
            continue
        label = _coerce_str(item.get("label")).strip()
        overlay = _coerce_str(item.get("overlay")).strip()
        metadata[preset_id] = {"label": label, "overlay": overlay}
    return metadata


def _plan_variant_map(variant_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    plan = _coerce_dict(variant_result.get("plan"))
    for item in _coerce_dict_list(plan.get("variants")):
        variant_id = _coerce_str(item.get("variant_id")).strip()
        if not variant_id or variant_id in mapping:
            continue
        mapping[variant_id] = item
    return mapping


def _variant_slug(plan_variant: dict[str, Any], result: dict[str, Any]) -> str:
    slug_from_plan = _coerce_str(plan_variant.get("variant_slug")).strip()
    if slug_from_plan:
        return slug_from_plan

    out_dir = _optional_posix_path(result.get("out_dir"))
    if not out_dir:
        return ""
    folder_name = Path(out_dir).name
    _, separator, suffix = folder_name.partition("__")
    if separator == "__":
        return suffix
    return ""


def _entry_variant_id(variant_id: str, variant_slug: str) -> str:
    if "__" in variant_id or not variant_slug:
        return variant_id
    return f"{variant_id}__{variant_slug}"


def _paths_payload(result: dict[str, Any], out_dir: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    path_field_map = (
        ("bundle_path", "bundle"),
        ("pdf_path", "pdf"),
        ("csv_path", "csv"),
        ("render_manifest_path", "render_manifest"),
        ("apply_manifest_path", "apply_manifest"),
    )
    for source_key, target_key in path_field_map:
        resolved = _optional_posix_path(result.get(source_key))
        if resolved is not None:
            paths[target_key] = resolved

    if out_dir and "render_manifest" in paths:
        paths["rendered_dir"] = f"{out_dir.rstrip('/')}/render"
    if out_dir and (
        "apply_manifest" in paths or _optional_posix_path(result.get("applied_report_path"))
    ):
        paths["applied_dir"] = f"{out_dir.rstrip('/')}/apply"
    return paths


def _bundle_translation_risk(bundle: dict[str, Any]) -> str:
    dashboard = _coerce_dict(bundle.get("dashboard"))
    vibe_signals = _coerce_dict(dashboard.get("vibe_signals"))
    translation_risk = _coerce_str(vibe_signals.get("translation_risk")).strip().lower()
    if translation_risk in _RISK_LEVELS:
        return translation_risk
    return ""


def _translation_risk(bundle: dict[str, Any], report: dict[str, Any]) -> str:
    from_bundle = _bundle_translation_risk(bundle)
    if from_bundle:
        return from_bundle
    vibe_signals = _coerce_dict(report.get("vibe_signals"))
    from_report = _coerce_str(vibe_signals.get("translation_risk")).strip().lower()
    if from_report in _RISK_LEVELS:
        return from_report
    return ""


def _profile_id(bundle: dict[str, Any], report: dict[str, Any]) -> str:
    dashboard = _coerce_dict(bundle.get("dashboard"))
    profile = _coerce_str(dashboard.get("profile_id")).strip()
    if profile:
        return profile

    run_config = _coerce_dict(report.get("run_config"))
    profile = _coerce_str(run_config.get("profile_id")).strip()
    if profile:
        return profile
    return _coerce_str(report.get("profile_id")).strip()


def _label(
    *,
    variant_slug: str,
    preset_id: str,
    format_set_name: str,
    preset_metadata: dict[str, dict[str, str]],
) -> str:
    if preset_id:
        preset_label = _coerce_str(_coerce_dict(preset_metadata.get(preset_id)).get("label")).strip()
        base_label = preset_label or variant_slug or preset_id
        if format_set_name:
            return f"{base_label} ({format_set_name})"
        return base_label
    return variant_slug or "variant"


def _overlay_note(overlay: str) -> str:
    lowered = overlay.strip().lower()
    if lowered in {"safe", "translation"}:
        return "Prioritize cross-device translation: phones, buds, and small speakers."
    if lowered in {"warm"}:
        return "Focus on body and closeness without losing vocal clarity."
    if lowered in {"air", "bright"}:
        return "Listen for sparkle, then check for harshness or sibilance."
    if lowered in {"punch"}:
        return "Check kick/snare impact and whether transients stay controlled."
    if lowered in {"glue", "dense"}:
        return "Listen for cohesion and watch for low-mid buildup."
    if lowered in {"wide"}:
        return "Check stereo size, then confirm mono still feels anchored."
    if lowered in {"vocal"}:
        return "Keep attention on lyric intelligibility in busy sections."
    if lowered in {"fast"}:
        return "Treat this as a fast draft and keep only moves that stay musical."
    return f"Use this pass to evaluate the {lowered} direction."


def _profile_note(profile_id: str) -> str:
    normalized = profile_id.strip().upper()
    if normalized == "PROFILE.ASSIST":
        return "Balanced assist profile: level-match before deciding favorites."
    if normalized == "PROFILE.FULL_SEND":
        return "Aggressive profile: double-check anything that feels overcooked."
    if normalized:
        return f"Profile {profile_id}: compare at matched loudness before deciding."
    return "Level-match against other variants before choosing."


def _notes(
    *,
    preset_id: str,
    overlay: str,
    profile_id: str,
    translation_risk: str,
    translation_risk_high_any: bool,
) -> list[str]:
    notes: list[str] = []
    if translation_risk_high_any and preset_id in {
        _TRANSLATION_SAFE_PRESET_ID,
        _SAFE_CLEANUP_PRESET_ID,
    }:
        notes.append("Start here if you want safety first.")
    elif translation_risk_high_any and translation_risk == "high":
        notes.append("Compare this after the safety-first pass for tone tradeoffs.")
    else:
        notes.append("Start with this if its direction fits the song.")

    if overlay:
        notes.append(_overlay_note(overlay))
    notes.append(_profile_note(profile_id))

    deduped: list[str] = []
    for note in notes:
        if note and note not in deduped:
            deduped.append(note)
    return deduped[:3]


def _audition_priority(preset_id: str) -> int:
    if preset_id == _TRANSLATION_SAFE_PRESET_ID:
        return 0
    if preset_id == _SAFE_CLEANUP_PRESET_ID:
        return 1
    return 2


def _root_out_dir(results: list[dict[str, Any]]) -> str:
    parent_dirs = [
        _path_parent(path_value)
        for path_value in (
            _optional_posix_path(item.get("out_dir"))
            for item in results
            if isinstance(item, dict)
        )
        if path_value
    ]
    if not parent_dirs:
        return Path.cwd().resolve().as_posix()
    try:
        common = posixpath.commonpath(parent_dirs)
    except ValueError:
        common = sorted(parent_dirs)[0]
    if re.fullmatch(r"(?:[A-Za-z]:/|/).+", common):
        return common
    return Path(common).resolve().as_posix()


def build_listen_pack(variant_result: dict[str, Any], presets_dir: Path) -> dict[str, Any]:
    if not isinstance(variant_result, dict):
        raise ValueError("variant_result must be an object.")

    preset_metadata = _preset_metadata_map(presets_dir)
    plan_variants = _plan_variant_map(variant_result)
    raw_results = _coerce_dict_list(variant_result.get("results"))

    entries_raw: list[dict[str, Any]] = []
    for result in raw_results:
        base_variant_id = _coerce_str(result.get("variant_id")).strip()
        if not base_variant_id:
            continue
        plan_variant = _coerce_dict(plan_variants.get(base_variant_id))
        variant_slug = _variant_slug(plan_variant, result)
        variant_id = _entry_variant_id(base_variant_id, variant_slug)
        out_dir = _optional_posix_path(result.get("out_dir")) or ""
        paths = _paths_payload(result, out_dir)

        bundle_path = paths.get("bundle")
        bundle = _read_json_object(bundle_path)
        report = _read_json_object(_optional_posix_path(result.get("report_path")))

        preset_id = _coerce_str(plan_variant.get("preset_id")).strip()
        if not preset_id:
            run_config = _coerce_dict(report.get("run_config"))
            preset_id = _coerce_str(run_config.get("preset_id")).strip()

        profile_id = _profile_id(bundle, report)
        overlay = _coerce_str(_coerce_dict(preset_metadata.get(preset_id)).get("overlay")).strip()
        format_set_name = _format_set_name(plan_variant, variant_slug)
        translation_risk = _translation_risk(bundle, report)
        bundle_translation_risk = _bundle_translation_risk(bundle)
        entry_sort_key = _variant_sort_key(base_variant_id, variant_slug)

        entries_raw.append(
            {
                "base_variant_id": base_variant_id,
                "variant_id": variant_id,
                "variant_slug": variant_slug,
                "sort_key": entry_sort_key,
                "label": _label(
                    variant_slug=variant_slug,
                    preset_id=preset_id,
                    format_set_name=format_set_name,
                    preset_metadata=preset_metadata,
                ),
                "preset_id": preset_id,
                "profile_id": profile_id,
                "overlay": overlay,
                "paths": paths,
                "translation_risk": translation_risk,
                "bundle_translation_risk": bundle_translation_risk,
            }
        )

    entries_by_variant = sorted(entries_raw, key=lambda item: item["sort_key"])
    translation_risk_high_any = any(
        item.get("bundle_translation_risk") == "high"
        for item in entries_by_variant
    )

    audition_rank_source = list(entries_by_variant)
    if translation_risk_high_any:
        audition_rank_source = sorted(
            audition_rank_source,
            key=lambda item: (
                _audition_priority(_coerce_str(item.get("preset_id"))),
                item["sort_key"],
            ),
        )

    audition_order_by_variant: dict[str, int] = {}
    for index, item in enumerate(audition_rank_source, start=1):
        audition_order_by_variant[_coerce_str(item.get("variant_id"))] = index

    entries: list[dict[str, Any]] = []
    for item in entries_by_variant:
        entry: dict[str, Any] = {
            "variant_id": _coerce_str(item.get("variant_id")),
            "label": _coerce_str(item.get("label")) or "variant",
            "paths": _coerce_dict(item.get("paths")),
            "audition_order": audition_order_by_variant.get(
                _coerce_str(item.get("variant_id")),
                len(entries) + 1,
            ),
            "notes": _notes(
                preset_id=_coerce_str(item.get("preset_id")),
                overlay=_coerce_str(item.get("overlay")),
                profile_id=_coerce_str(item.get("profile_id")),
                translation_risk=_coerce_str(item.get("translation_risk")),
                translation_risk_high_any=translation_risk_high_any,
            ),
        }

        preset_id = _coerce_str(item.get("preset_id")).strip()
        if preset_id:
            entry["preset_id"] = preset_id

        profile_id = _coerce_str(item.get("profile_id")).strip()
        if profile_id:
            entry["profile_id"] = profile_id

        overlay = _coerce_str(item.get("overlay")).strip()
        if overlay:
            entry["overlay"] = overlay

        entries.append(entry)

    return {
        "schema_version": LISTEN_PACK_SCHEMA_VERSION,
        "root_out_dir": _root_out_dir(raw_results),
        "entries": entries,
    }
