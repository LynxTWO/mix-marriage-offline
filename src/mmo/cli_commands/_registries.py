"""Registry-related CLI helpers: presets, roles, render targets, translation,
help, UI copy, UI examples, plugins, and scene locks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mmo.resources import ontology_dir, schemas_dir

from mmo.cli_commands._helpers import (
    _BASELINE_RENDER_TARGET_ID,
    _PRESET_PREVIEW_DEFAULT_MAX_SECONDS,
    _PRESET_PREVIEW_DEFAULT_METERS,
    _PRESET_PREVIEW_DEFAULT_PROFILE_ID,
    _PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID,
    RUN_CONFIG_SCHEMA_VERSION,
    _coerce_str,
    _config_string,
    _flag_present,
    _load_json_object,
    _load_report,
    _rel_path_if_under_root,
    _set_nested,
    _validate_json_payload,
    _write_json_file,
)
from mmo.core.presets import (
    list_preset_packs,
    list_presets,
    load_preset_pack,
    load_preset_run_config,
)
from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    resolve_render_target_id,
)
from mmo.core.roles import list_roles, load_roles, resolve_role
from mmo.core.run_config import (
    diff_run_config,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.scene_locks import get_scene_lock, list_scene_locks
from mmo.core.target_recommendations import recommend_render_targets
from mmo.core.translation_audition import render_translation_auditions
from mmo.core.translation_checks import run_translation_checks
from mmo.core.translation_profiles import (
    get_translation_profile,
    list_translation_profiles,
    load_translation_profiles,
)
from mmo.core.translation_reference import (
    TranslationReferenceResolutionError,
    resolve_translation_reference_audio,
)
from mmo.core.translation_summary import build_translation_summary

__all__ = [
    "_build_preset_show_payload",
    "_string_list",
    "_preset_preview_placeholder_help",
    "_build_preset_preview_help",
    "_build_preset_preview_default_run_config",
    "_build_preset_preview_cli_overrides",
    "_build_preset_preview_payload",
    "_render_preset_preview_text",
    "_build_preset_label_map",
    "_build_preset_pack_payload",
    "_build_preset_pack_list_payload",
    "_build_preset_recommendations_payload",
    "_build_render_target_list_payload",
    "_build_render_target_show_payload",
    "_build_role_list_payload",
    "_build_role_show_payload",
    "_render_role_text",
    "_build_translation_profile_list_payload",
    "_build_translation_profile_show_payload",
    "_render_translation_profile_text",
    "_parse_translation_profile_ids_csv",
    "_parse_translation_audio_csv",
    "_translation_audio_sort_key",
    "_discover_translation_audio_paths",
    "_resolve_translation_compare_audio_paths",
    "_coerce_translation_compare_score",
    "_build_translation_compare_payload",
    "_render_translation_compare_text",
    "_build_translation_run_payload",
    "_build_translation_audition_payload",
    "_render_translation_results_text",
    "_write_translation_results_json",
    "_write_translation_audition_manifest",
    "_write_report_with_translation_results",
    "_sorted_translation_results",
    "_render_translation_audition_text",
    "_dict_list",
    "_load_report_from_path_or_dir",
    "_format_confidence",
    "_build_render_target_recommendations_payload",
    "_render_target_recommendations_text",
    "_render_target_text",
    "_build_help_list_payload",
    "_build_help_show_payload",
    "_ui_copy_locale_ids",
    "_resolve_ui_copy_locale",
    "_build_ui_copy_list_payload",
    "_build_ui_copy_show_payload",
    "_ui_examples_paths",
    "_build_ui_examples_list_payload",
    "_build_ui_examples_show_payload",
    "_build_plugins_list_payload",
    "_render_plugins_list_text",
    "_print_lock_verify_summary",
]


# ── Preset helpers ────────────────────────────────────────────────


def _build_preset_show_payload(*, presets_dir: Path, preset_id: str) -> dict[str, Any]:
    normalized_preset_id = preset_id.strip() if isinstance(preset_id, str) else ""
    if not normalized_preset_id:
        raise ValueError("preset_id must be a non-empty string.")

    presets = list_presets(presets_dir)
    preset_entry = next(
        (
            item
            for item in presets
            if isinstance(item, dict) and item.get("preset_id") == normalized_preset_id
        ),
        None,
    )
    if preset_entry is None:
        available = ", ".join(
            item["preset_id"]
            for item in presets
            if isinstance(item, dict) and isinstance(item.get("preset_id"), str)
        )
        if available:
            raise ValueError(
                f"Unknown preset_id: {normalized_preset_id}. Available presets: {available}"
            )
        raise ValueError(
            f"Unknown preset_id: {normalized_preset_id}. No presets are available."
        )

    payload = dict(preset_entry)
    payload["run_config"] = load_preset_run_config(
        presets_dir,
        normalized_preset_id,
    )
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _preset_preview_placeholder_help() -> dict[str, Any]:
    return {
        "title": "Preset help unavailable",
        "short": "No musician-language help text is available for this preset yet.",
        "cues": [
            "Use this preset as a workflow lens and confirm by ear in context.",
        ],
        "watch_out_for": [
            "Double-check translation on your main playback systems.",
        ],
    }


def _build_preset_preview_help(
    *,
    help_registry_path: Path,
    help_id: str | None,
) -> dict[str, Any]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    placeholder = _preset_preview_placeholder_help()
    normalized_help_id = help_id.strip() if isinstance(help_id, str) else ""
    if not normalized_help_id:
        return placeholder

    registry = load_help_registry(help_registry_path)
    resolved = resolve_help_entries([normalized_help_id], registry)
    entry = resolved.get(normalized_help_id)
    if not isinstance(entry, dict):
        return placeholder

    entry_title = entry.get("title")
    entry_short = entry.get("short")
    if not isinstance(entry_short, str) or not entry_short.strip():
        return placeholder
    if (
        entry_short == "Missing help entry"
        and isinstance(entry_title, str)
        and entry_title == normalized_help_id
    ):
        return placeholder

    payload: dict[str, Any] = {
        "title": entry_title if isinstance(entry_title, str) and entry_title else "",
        "short": entry_short,
    }
    long_text = entry.get("long")
    if isinstance(long_text, str) and long_text:
        payload["long"] = long_text

    cues = _string_list(entry.get("cues"))
    watch_out_for = _string_list(entry.get("watch_out_for"))
    payload["cues"] = cues if cues else list(placeholder["cues"])
    payload["watch_out_for"] = (
        watch_out_for if watch_out_for else list(placeholder["watch_out_for"])
    )
    return payload


def _build_preset_preview_default_run_config() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "profile_id": _PRESET_PREVIEW_DEFAULT_PROFILE_ID,
        "meters": _PRESET_PREVIEW_DEFAULT_METERS,
        "max_seconds": _PRESET_PREVIEW_DEFAULT_MAX_SECONDS,
        "downmix": {
            "target_layout_id": _PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID,
        },
    }
    return normalize_run_config(payload)


def _build_preset_preview_cli_overrides(
    *,
    args: argparse.Namespace,
    raw_argv: list[str],
) -> dict[str, Any]:
    cli_overrides: dict[str, Any] = {}
    if _flag_present(raw_argv, "--profile"):
        cli_overrides["profile_id"] = args.profile
    if _flag_present(raw_argv, "--meters"):
        cli_overrides["meters"] = args.meters
    if _flag_present(raw_argv, "--max-seconds"):
        cli_overrides["max_seconds"] = args.max_seconds
    if _flag_present(raw_argv, "--source-layout"):
        _set_nested(["downmix", "source_layout_id"], cli_overrides, args.source_layout)
    if _flag_present(raw_argv, "--target-layout"):
        _set_nested(["downmix", "target_layout_id"], cli_overrides, args.target_layout)
    if _flag_present(raw_argv, "--policy-id"):
        _set_nested(["downmix", "policy_id"], cli_overrides, args.policy_id)
    return cli_overrides


def _build_preset_preview_payload(
    *,
    repo_root: Path,
    presets_dir: Path,
    preset_id: str,
    config_path: str | None,
    cli_overrides: dict[str, Any],
) -> dict[str, Any]:
    preset_payload = _build_preset_show_payload(presets_dir=presets_dir, preset_id=preset_id)
    normalized_preset_id = (
        preset_payload.get("preset_id", "").strip()
        if isinstance(preset_payload.get("preset_id"), str)
        else ""
    )
    if not normalized_preset_id:
        raise ValueError("preset_id must be a non-empty string.")

    preset_cfg = preset_payload.get("run_config")
    if not isinstance(preset_cfg, dict):
        raise ValueError("Preset run_config must be an object.")

    base_cfg = _build_preset_preview_default_run_config()
    config_cfg: dict[str, Any] = {}
    if config_path:
        config_cfg = load_run_config(Path(config_path))

    effective_cfg = merge_run_config(base_cfg, preset_cfg)
    effective_cfg = merge_run_config(effective_cfg, config_cfg)
    pre_cli_cfg = dict(effective_cfg)
    effective_cfg = merge_run_config(effective_cfg, cli_overrides)
    effective_cfg["preset_id"] = normalized_preset_id
    effective_cfg = normalize_run_config(effective_cfg)

    _validate_json_payload(
        effective_cfg,
        schema_path=schemas_dir() /"run_config.schema.json",
        payload_name="Preset preview effective_run_config",
    )

    help_payload = _build_preset_preview_help(
        help_registry_path=ontology_dir() /"help.yaml",
        help_id=preset_payload.get("help_id")
        if isinstance(preset_payload.get("help_id"), str)
        else None,
    )
    changes_by_key_path = {
        item["key_path"]: item
        for item in diff_run_config(base_cfg, effective_cfg)
        if isinstance(item.get("key_path"), str)
    }
    cli_override_key_paths = {
        item["key_path"]
        for item in diff_run_config({}, cli_overrides)
        if isinstance(item.get("key_path"), str)
    }
    for item in diff_run_config(pre_cli_cfg, effective_cfg):
        key_path = item.get("key_path")
        if not isinstance(key_path, str):
            continue
        if key_path not in cli_override_key_paths:
            continue
        if key_path in changes_by_key_path:
            continue
        changes_by_key_path[key_path] = item
    changes_by_key_path.pop("preset_id", None)
    changes_from_defaults = [
        changes_by_key_path[key_path]
        for key_path in sorted(changes_by_key_path.keys())
    ]

    label = preset_payload.get("label")
    overlay = preset_payload.get("overlay")
    category = preset_payload.get("category")
    payload: dict[str, Any] = {
        "preset_id": normalized_preset_id,
        "label": label if isinstance(label, str) else "",
        "overlay": overlay if isinstance(overlay, str) else "",
        "category": category if isinstance(category, str) else "",
        "tags": _string_list(preset_payload.get("tags")),
        "goals": _string_list(preset_payload.get("goals")),
        "warnings": _string_list(preset_payload.get("warnings")),
        "help": help_payload,
        "effective_run_config": effective_cfg,
        "changes_from_defaults": changes_from_defaults,
    }
    return payload


def _render_preset_preview_text(payload: dict[str, Any]) -> str:
    preset_id = payload.get("preset_id")
    label = payload.get("label")
    category = payload.get("category")
    overlay = payload.get("overlay")
    help_payload = payload.get("help")
    changes = payload.get("changes_from_defaults")

    normalized_preset_id = preset_id if isinstance(preset_id, str) else ""
    normalized_label = label if isinstance(label, str) else ""
    normalized_category = category if isinstance(category, str) and category else "UNCATEGORIZED"
    normalized_overlay = overlay if isinstance(overlay, str) and overlay else "none"

    short_text = ""
    cues: list[str] = []
    watch_out_for: list[str] = []
    if isinstance(help_payload, dict):
        short = help_payload.get("short")
        if isinstance(short, str):
            short_text = short
        cues = _string_list(help_payload.get("cues"))
        watch_out_for = _string_list(help_payload.get("watch_out_for"))

    lines = [
        f"{normalized_label} ({normalized_preset_id}) [{normalized_category}]",
        f"Overlay: {normalized_overlay}",
        f"Short: {short_text}",
        "When to use:",
    ]
    for cue in cues:
        lines.append(f"  - {cue}")

    lines.append("Watch out for:")
    for item in watch_out_for:
        lines.append(f"  - {item}")

    lines.append("What changes if you use this preset:")
    if isinstance(changes, list) and changes:
        for item in changes:
            if not isinstance(item, dict):
                continue
            key_path = item.get("key_path")
            if not isinstance(key_path, str) or not key_path:
                continue
            before_value = json.dumps(item.get("before"), sort_keys=True)
            after_value = json.dumps(item.get("after"), sort_keys=True)
            lines.append(f"  - {key_path}: {before_value} -> {after_value}")
    else:
        lines.append(
            "This preset is a workflow lens. It doesnt change settings, it changes what you focus on."
        )
    return "\n".join(lines)


def _build_preset_label_map(*, presets_dir: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in list_presets(presets_dir):
        if not isinstance(item, dict):
            continue
        preset_id = item.get("preset_id")
        label = item.get("label")
        if isinstance(preset_id, str) and isinstance(label, str):
            labels[preset_id] = label
    return labels


def _build_preset_pack_payload(*, presets_dir: Path, pack_id: str) -> dict[str, Any]:
    payload = load_preset_pack(presets_dir, pack_id)
    label_map = _build_preset_label_map(presets_dir=presets_dir)
    presets: list[dict[str, str]] = []
    for preset_id in payload.get("preset_ids", []):
        if not isinstance(preset_id, str):
            continue
        presets.append(
            {
                "preset_id": preset_id,
                "label": label_map.get(preset_id, ""),
            }
        )
    payload["presets"] = presets
    return payload


def _build_preset_pack_list_payload(*, presets_dir: Path) -> list[dict[str, Any]]:
    label_map = _build_preset_label_map(presets_dir=presets_dir)
    payload: list[dict[str, Any]] = []
    for item in list_preset_packs(presets_dir):
        if not isinstance(item, dict):
            continue
        pack_payload = dict(item)
        presets: list[dict[str, str]] = []
        for preset_id in pack_payload.get("preset_ids", []):
            if not isinstance(preset_id, str):
                continue
            presets.append(
                {
                    "preset_id": preset_id,
                    "label": label_map.get(preset_id, ""),
                }
            )
        pack_payload["presets"] = presets
        payload.append(pack_payload)
    return payload


def _build_preset_recommendations_payload(
    *,
    report_path: Path,
    presets_dir: Path,
    n: int,
) -> list[dict[str, Any]]:
    from mmo.core.preset_recommendations import derive_preset_recommendations  # noqa: WPS433

    if n <= 0:
        raise ValueError("--n must be greater than 0.")
    report = _load_report(report_path)
    return derive_preset_recommendations(report, presets_dir, n=n)


# ── Render target helpers ─────────────────────────────────────────


def _build_render_target_list_payload(*, render_targets_path: Path) -> list[dict[str, Any]]:
    return list_render_targets(render_targets_path)


def _build_render_target_show_payload(
    *,
    render_targets_path: Path,
    target_id: str,
) -> dict[str, Any]:
    resolved_target_id = resolve_render_target_id(target_id, render_targets_path)
    payload = get_render_target(resolved_target_id, render_targets_path)
    if payload is None:
        raise ValueError(f"Resolved target is missing from registry: {resolved_target_id}")
    return payload


# ── Role helpers ──────────────────────────────────────────────────


def _build_role_list_payload(*, roles_path: Path) -> list[str]:
    return list_roles(roles_path)


def _build_role_show_payload(*, roles_path: Path, role_id: str) -> dict[str, Any]:
    normalized_role_id = role_id.strip() if isinstance(role_id, str) else ""
    if not normalized_role_id:
        raise ValueError("role_id must be a non-empty string.")
    payload = resolve_role(normalized_role_id, roles_path)
    row = {"role_id": normalized_role_id}
    row.update(dict(payload))
    return row


def _render_role_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("role_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"kind: {_coerce_str(payload.get('kind')).strip()}",
    ]

    default_bus_group = payload.get("default_bus_group")
    if isinstance(default_bus_group, str) and default_bus_group.strip():
        lines.append(f"default_bus_group: {default_bus_group.strip()}")

    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        lines.append(f"description: {description.strip()}")

    inference = payload.get("inference")
    if isinstance(inference, dict):
        keywords = inference.get("keywords")
        if isinstance(keywords, list):
            normalized_keywords = [
                keyword.strip()
                for keyword in keywords
                if isinstance(keyword, str) and keyword.strip()
            ]
            if normalized_keywords:
                lines.append(f"keywords: {', '.join(normalized_keywords)}")

        regex_values = inference.get("regex")
        if isinstance(regex_values, list):
            normalized_regex_values = [
                pattern.strip()
                for pattern in regex_values
                if isinstance(pattern, str) and pattern.strip()
            ]
            if normalized_regex_values:
                lines.append("regex:")
                for pattern in normalized_regex_values:
                    lines.append(f"- {pattern}")

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        normalized_notes = [item.strip() for item in notes if isinstance(item, str) and item.strip()]
        if normalized_notes:
            lines.append("notes:")
            for item in normalized_notes:
                lines.append(f"- {item}")

    return "\n".join(lines)


# ── Translation helpers ───────────────────────────────────────────


def _build_translation_profile_list_payload(
    *,
    translation_profiles_path: Path,
) -> list[dict[str, Any]]:
    return list_translation_profiles(translation_profiles_path)


def _build_translation_profile_show_payload(
    *,
    translation_profiles_path: Path,
    profile_id: str,
) -> dict[str, Any]:
    return get_translation_profile(profile_id, translation_profiles_path)


def _render_translation_profile_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("profile_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"description: {_coerce_str(payload.get('description')).strip()}",
        f"intent: {_coerce_str(payload.get('intent')).strip()}",
    ]

    thresholds = payload.get("default_thresholds")
    if isinstance(thresholds, dict):
        lines.append("default_thresholds:")
        for key in sorted(thresholds.keys()):
            value = thresholds.get(key)
            lines.append(f"- {key}: {value}")

    scoring = payload.get("scoring")
    if isinstance(scoring, dict):
        lines.append("scoring:")
        for key in sorted(scoring.keys()):
            value = scoring.get(key)
            lines.append(f"- {key}: {value}")

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes:")
        for item in notes:
            if isinstance(item, str):
                lines.append(f"- {item}")

    return "\n".join(lines)


def _parse_translation_profile_ids_csv(
    raw_value: str,
    *,
    translation_profiles_path: Path,
) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("translation profiles must be a comma-separated string.")

    requested = [
        profile_id.strip()
        for profile_id in raw_value.split(",")
        if isinstance(profile_id, str) and profile_id.strip()
    ]
    if not requested:
        raise ValueError("translation profiles must include at least one profile ID.")

    profiles = load_translation_profiles(translation_profiles_path)
    known_ids = sorted(profile_id for profile_id in profiles.keys() if isinstance(profile_id, str))
    known_set = set(known_ids)
    unknown_ids = sorted(
        {
            profile_id
            for profile_id in requested
            if profile_id not in known_set
        }
    )
    if unknown_ids:
        unknown_label = ", ".join(unknown_ids)
        known_label = ", ".join(known_ids)
        if known_label:
            raise ValueError(
                f"Unknown translation profile_id: {unknown_label}. Known profile_ids: {known_label}"
            )
        raise ValueError(
            f"Unknown translation profile_id: {unknown_label}. No translation profiles are available."
        )

    selected: list[str] = []
    seen: set[str] = set()
    for profile_id in requested:
        if profile_id not in seen:
            selected.append(profile_id)
            seen.add(profile_id)
    return selected


def _parse_translation_audio_csv(raw_value: str) -> list[Path]:
    if not isinstance(raw_value, str):
        raise ValueError("audio must be a comma-separated string.")

    selected: list[Path] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        normalized = item.strip()
        if not normalized:
            continue
        key = Path(normalized).as_posix().strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(Path(normalized))

    if not selected:
        raise ValueError("audio must include at least one WAV path.")
    return selected


def _translation_audio_sort_key(path: Path) -> tuple[str, str, str, str]:
    filename = path.name
    normalized_filename = filename.casefold()
    normalized_path = path.as_posix().casefold()
    return (normalized_filename, filename, normalized_path, path.as_posix())


def _discover_translation_audio_paths(
    *,
    in_dir: Path,
    glob_pattern: str,
) -> list[Path]:
    if not in_dir.exists():
        raise ValueError(f"Audio directory does not exist: {in_dir}")
    if not in_dir.is_dir():
        raise ValueError(f"Audio directory is not a directory: {in_dir}")
    if not isinstance(glob_pattern, str) or not glob_pattern.strip():
        raise ValueError("glob pattern must be a non-empty string.")

    pattern = glob_pattern.strip()
    candidates = [path for path in in_dir.glob(pattern) if path.is_file()]
    wav_paths = [
        path
        for path in candidates
        if path.suffix.lower() in {".wav", ".wave"}
    ]
    if not wav_paths:
        raise ValueError(f"No WAV files matched {pattern!r} under directory: {in_dir}")
    return sorted(wav_paths, key=_translation_audio_sort_key)


def _resolve_translation_compare_audio_paths(
    *,
    raw_audio: str | None,
    in_dir_value: str | None,
    glob_pattern: str | None,
) -> list[Path]:
    audio_value = raw_audio.strip() if isinstance(raw_audio, str) else ""
    in_dir_raw = in_dir_value.strip() if isinstance(in_dir_value, str) else ""
    if audio_value and in_dir_raw:
        raise ValueError("translation compare accepts either --audio or --in-dir, not both.")

    if audio_value:
        audio_paths = _parse_translation_audio_csv(audio_value)
        return sorted(audio_paths, key=_translation_audio_sort_key)

    if in_dir_raw:
        pattern = glob_pattern.strip() if isinstance(glob_pattern, str) else "*.wav"
        return _discover_translation_audio_paths(
            in_dir=Path(in_dir_raw),
            glob_pattern=pattern or "*.wav",
        )

    raise ValueError("translation compare requires either --audio or --in-dir.")


def _coerce_translation_compare_score(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    return 0


def _build_translation_compare_payload(
    *,
    translation_profiles_path: Path,
    audio_paths: list[Path],
    profile_ids: list[str],
    max_issues_per_profile: int = 3,
) -> list[dict[str, Any]]:
    if not isinstance(audio_paths, list):
        raise ValueError("audio paths must be provided as a list.")
    if not audio_paths:
        raise ValueError("At least one WAV audio input is required.")

    sorted_profile_ids = sorted(
        {
            profile_id.strip()
            for profile_id in profile_ids
            if isinstance(profile_id, str) and profile_id.strip()
        }
    )
    if not sorted_profile_ids:
        raise ValueError("At least one translation profile_id is required.")

    profiles = load_translation_profiles(translation_profiles_path)
    rows: list[dict[str, Any]] = []

    for audio_path in sorted(audio_paths, key=_translation_audio_sort_key):
        translation_results = run_translation_checks(
            audio_path=audio_path,
            profiles=profiles,
            profile_ids=sorted_profile_ids,
            max_issues_per_profile=max_issues_per_profile,
        )
        summary_rows = build_translation_summary(translation_results, profiles)
        status_by_profile = {
            _coerce_str(item.get("profile_id")).strip(): _coerce_str(item.get("status")).strip()
            for item in summary_rows
            if isinstance(item, dict)
        }

        for result in _sorted_translation_results(translation_results):
            profile_id = _coerce_str(result.get("profile_id")).strip()
            if not profile_id:
                continue
            issues_raw = result.get("issues")
            issues_count = len(
                [item for item in issues_raw if isinstance(item, dict)]
            ) if isinstance(issues_raw, list) else 0
            rows.append(
                {
                    "audio": audio_path.name,
                    "profile_id": profile_id,
                    "score": _coerce_translation_compare_score(result.get("score")),
                    "status": status_by_profile.get(profile_id, ""),
                    "issues_count": issues_count,
                }
            )

    rows.sort(
        key=lambda item: (
            _coerce_str(item.get("audio")).strip().casefold(),
            _coerce_str(item.get("audio")).strip(),
            _coerce_str(item.get("profile_id")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )
    return rows


def _render_translation_compare_text(payload: list[dict[str, Any]]) -> str:
    lines = ["audio | profile_id | score | status"]
    for row in payload:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{_coerce_str(row.get('audio')).strip()} | "
            f"{_coerce_str(row.get('profile_id')).strip()} | "
            f"{_coerce_translation_compare_score(row.get('score'))} | "
            f"{_coerce_str(row.get('status')).strip()}"
        )
    return "\n".join(lines)


def _build_translation_run_payload(
    *,
    translation_profiles_path: Path,
    audio_path: Path,
    profile_ids: list[str],
    max_issues_per_profile: int = 3,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    profiles = load_translation_profiles(translation_profiles_path)
    return run_translation_checks(
        audio_path=audio_path,
        profiles=profiles,
        profile_ids=profile_ids,
        max_issues_per_profile=max_issues_per_profile,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )


def _build_translation_audition_payload(
    *,
    translation_profiles_path: Path,
    audio_path: Path,
    out_dir: Path,
    profile_ids: list[str],
    segment_s: float | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    profiles = load_translation_profiles(translation_profiles_path)
    return render_translation_auditions(
        audio_path=audio_path,
        out_dir=out_dir,
        profiles=profiles,
        profile_ids=profile_ids,
        segment_s=segment_s,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )


def _render_translation_results_text(payload: list[dict[str, Any]]) -> str:
    if not payload:
        return "translation_results: (none)"

    lines = ["translation_results:"]
    for row in payload:
        if not isinstance(row, dict):
            continue
        profile_id = _coerce_str(row.get("profile_id")).strip()
        score = row.get("score")
        issues = row.get("issues")
        issue_count = len(issues) if isinstance(issues, list) else 0
        lines.append(f"- {profile_id} score={score} issues={issue_count}")
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = _coerce_str(issue.get("issue_id")).strip()
            message = _coerce_str(issue.get("message")).strip()
            lines.append(f"  {issue_id}: {message}")
    return "\n".join(lines)


def _write_translation_results_json(
    path: Path,
    payload: list[dict[str, Any]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(f"Failed to write translation results JSON: {path}: {exc}") from exc


def _write_translation_audition_manifest(
    path: Path,
    payload: dict[str, Any],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(
            f"Failed to write translation audition manifest JSON: {path}: {exc}"
        ) from exc


def _write_report_with_translation_results(
    *,
    report_in_path: Path,
    report_out_path: Path,
    translation_results: list[dict[str, Any]],
    repo_root: Path,
    profiles: dict[str, dict[str, Any]] | None = None,
    translation_reference: dict[str, Any] | None = None,
) -> None:
    report_payload = _load_report(report_in_path)
    profile_map = (
        profiles
        if isinstance(profiles, dict)
        else load_translation_profiles(ontology_dir() /"translation_profiles.yaml")
    )
    report_payload["translation_results"] = translation_results
    report_payload["translation_summary"] = build_translation_summary(
        translation_results,
        profile_map,
    )
    if isinstance(translation_reference, dict):
        report_payload["translation_reference"] = dict(translation_reference)
    _validate_json_payload(
        report_payload,
        schema_path=schemas_dir() /"report.schema.json",
        payload_name="Report",
    )
    try:
        report_out_path.parent.mkdir(parents=True, exist_ok=True)
        report_out_path.write_text(
            json.dumps(report_payload, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(f"Failed to write report JSON: {report_out_path}: {exc}") from exc


def _sorted_translation_results(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(item) for item in payload if isinstance(item, dict)]
    rows.sort(
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )
    return rows


def _render_translation_audition_text(
    *,
    payload: dict[str, Any],
    root_out_dir: Path,
    audition_out_dir: Path,
) -> str:
    renders = payload.get("renders")
    rows = [item for item in renders if isinstance(item, dict)] if isinstance(renders, list) else []
    rows = sorted(
        rows,
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            _coerce_str(item.get("path")).strip(),
        ),
    )

    lines = [f"Wrote {len(rows)} audition files to {audition_out_dir.resolve().as_posix()}"]
    for row in rows:
        profile_id = _coerce_str(row.get("profile_id")).strip()
        path_value = _coerce_str(row.get("path")).strip()
        rendered_path = Path(path_value) if path_value else Path()
        relative = _rel_path_if_under_root(root_out_dir, rendered_path) if path_value else None
        target_path = relative if relative else path_value
        lines.append(f"- {profile_id} -> {target_path}")
    return "\n".join(lines)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


# ── Report / target recommendation helpers ────────────────────────


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


def _format_confidence(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "0.00"
    clamped = max(0.0, min(1.0, float(value)))
    return f"{clamped:.2f}"


def _build_render_target_recommendations_payload(
    *,
    repo_root: Path,
    render_targets_path: Path,
    report_input: str | None,
    scene_input: str | None,
    max_results: int,
) -> list[dict[str, Any]]:
    if max_results <= 0:
        raise ValueError("--max must be greater than 0.")

    report_payload: dict[str, Any] | None = None
    report_dir: Path | None = None
    if isinstance(report_input, str) and report_input.strip():
        report_payload, report_dir = _load_report_from_path_or_dir(Path(report_input))

    scene_payload: dict[str, Any] | None = None
    if isinstance(scene_input, str) and scene_input.strip():
        scene_path = Path(scene_input)
        if scene_path.is_dir():
            raise ValueError(f"Expected scene JSON file path, got directory: {scene_path}")
        scene_payload = _load_json_object(scene_path, label="Scene")
    elif report_dir is not None:
        auto_scene_path = report_dir / "scene.json"
        if auto_scene_path.exists():
            if auto_scene_path.is_dir():
                raise ValueError(
                    f"Expected scene JSON file path, got directory: {auto_scene_path}"
                )
            scene_payload = _load_json_object(auto_scene_path, label="Scene")

    return recommend_render_targets(
        repo_root=None,
        render_targets_path=render_targets_path,
        report=report_payload,
        scene=scene_payload,
        max_results=max_results,
    )


def _render_target_recommendations_text(payload: list[dict[str, Any]]) -> str:
    lines = ["Recommended targets:"]
    if not payload:
        lines.append("  (none)")
        return "\n".join(lines)

    for row in payload:
        rank = row.get("rank")
        target_id = _coerce_str(row.get("target_id")).strip()
        lines.append(
            f"  {rank}) {target_id} (conf={_format_confidence(row.get('confidence'))})"
        )
        reasons = row.get("reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                if isinstance(reason, str):
                    lines.append(f"     - {reason}")
    return "\n".join(lines)


def _render_target_text(payload: dict[str, Any]) -> str:
    lines = [
        _coerce_str(payload.get("target_id")).strip(),
        f"label: {_coerce_str(payload.get('label')).strip()}",
        f"layout_id: {_coerce_str(payload.get('layout_id')).strip()}",
        f"channel_order_ref: {_coerce_str(payload.get('channel_order_ref')).strip()}",
    ]

    aliases = payload.get("aliases")
    normalized_aliases = (
        [item for item in aliases if isinstance(item, str) and item.strip()]
        if isinstance(aliases, list)
        else []
    )
    if normalized_aliases:
        lines.append("aliases:")
        for alias in normalized_aliases:
            lines.append(f"- {alias}")

    downmix_policy_id = _coerce_str(payload.get("downmix_policy_id")).strip()
    safety_policy_id = _coerce_str(payload.get("safety_policy_id")).strip()
    lines.append(f"downmix_policy_id: {downmix_policy_id or '(none)'}")
    lines.append(f"safety_policy_id: {safety_policy_id or '(none)'}")

    speaker_positions = payload.get("speaker_positions")
    if isinstance(speaker_positions, list) and speaker_positions:
        lines.append("speaker_positions:")
        for position in speaker_positions:
            if not isinstance(position, dict):
                continue
            ch = position.get("ch")
            azimuth_deg = position.get("azimuth_deg")
            elevation_deg = position.get("elevation_deg")
            lines.append(
                f"- ch={ch} azimuth_deg={azimuth_deg} elevation_deg={elevation_deg}"
            )

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("notes:")
        for item in notes:
            if isinstance(item, str):
                lines.append(f"- {item}")
    return "\n".join(lines)


# ── Help registry helpers ─────────────────────────────────────────


def _build_help_list_payload(*, help_registry_path: Path) -> list[dict[str, str]]:
    from mmo.core.help_registry import load_help_registry  # noqa: WPS433

    registry = load_help_registry(help_registry_path)
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        return []

    payload: list[dict[str, str]] = []
    for help_id in sorted(
        key for key in entries.keys() if isinstance(key, str) and key.strip()
    ):
        entry = entries.get(help_id)
        title = ""
        if isinstance(entry, dict):
            title_value = entry.get("title")
            if isinstance(title_value, str):
                title = title_value
        payload.append({"help_id": help_id, "title": title})
    return payload


def _build_help_show_payload(*, help_registry_path: Path, help_id: str) -> dict[str, Any]:
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433

    normalized_help_id = help_id.strip() if isinstance(help_id, str) else ""
    if not normalized_help_id:
        raise ValueError("help_id must be a non-empty string.")

    registry = load_help_registry(help_registry_path)
    resolved = resolve_help_entries([normalized_help_id], registry)
    entry = resolved.get(normalized_help_id)
    payload: dict[str, Any] = {"help_id": normalized_help_id}
    if isinstance(entry, dict):
        payload.update(entry)
    return payload


# ── UI copy helpers ───────────────────────────────────────────────


def _ui_copy_locale_ids(registry: dict[str, Any]) -> list[str]:
    locales = registry.get("locales")
    if not isinstance(locales, dict):
        return []
    return sorted(
        locale_id.strip()
        for locale_id in locales.keys()
        if isinstance(locale_id, str) and locale_id.strip()
    )


def _resolve_ui_copy_locale(*, registry: dict[str, Any], locale: str | None) -> str:
    locale_ids = _ui_copy_locale_ids(registry)
    requested_locale = locale.strip() if isinstance(locale, str) else ""
    if requested_locale:
        if locale_ids and requested_locale not in locale_ids:
            joined_locales = ", ".join(locale_ids)
            raise ValueError(
                f"Unknown locale: {requested_locale}. Available locales: {joined_locales}"
            )
        return requested_locale

    default_locale = registry.get("default_locale")
    normalized_default = default_locale.strip() if isinstance(default_locale, str) else ""
    if normalized_default:
        return normalized_default
    if locale_ids:
        return locale_ids[0]
    raise ValueError("UI copy registry does not define any locales.")


def _build_ui_copy_list_payload(
    *,
    ui_copy_registry_path: Path,
    locale: str | None,
) -> dict[str, Any]:
    from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy  # noqa: WPS433

    registry = load_ui_copy(ui_copy_registry_path)
    resolved_locale = _resolve_ui_copy_locale(registry=registry, locale=locale)
    locales = registry.get("locales")
    locale_payload = (
        locales.get(resolved_locale) if isinstance(locales, dict) else None
    )
    entries = (
        locale_payload.get("entries")
        if isinstance(locale_payload, dict)
        else None
    )
    copy_keys = (
        [copy_id for copy_id in entries.keys() if isinstance(copy_id, str)]
        if isinstance(entries, dict)
        else []
    )
    resolved_entries = resolve_ui_copy(
        copy_keys,
        registry,
        locale=resolved_locale,
    )

    items: list[dict[str, Any]] = []
    for copy_id in sorted(resolved_entries.keys()):
        entry = resolved_entries.get(copy_id)
        row: dict[str, Any] = {"copy_id": copy_id}
        if isinstance(entry, dict):
            row.update(entry)
        items.append(row)
    return {"locale": resolved_locale, "entries": items}


def _build_ui_copy_show_payload(
    *,
    ui_copy_registry_path: Path,
    locale: str | None,
    copy_id: str,
) -> dict[str, Any]:
    from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy  # noqa: WPS433

    normalized_copy_id = copy_id.strip() if isinstance(copy_id, str) else ""
    if not normalized_copy_id:
        raise ValueError("copy_id must be a non-empty string.")

    registry = load_ui_copy(ui_copy_registry_path)
    resolved_locale = _resolve_ui_copy_locale(registry=registry, locale=locale)
    entry = resolve_ui_copy([normalized_copy_id], registry, locale=resolved_locale).get(
        normalized_copy_id
    )
    payload: dict[str, Any] = {
        "locale": resolved_locale,
        "copy_id": normalized_copy_id,
    }
    if isinstance(entry, dict):
        payload.update(entry)
    return payload


# ── UI examples helpers ───────────────────────────────────────────


def _ui_examples_paths(*, ui_examples_dir: Path) -> list[Path]:
    if not ui_examples_dir.exists():
        raise ValueError(f"UI examples directory does not exist: {ui_examples_dir}")
    if not ui_examples_dir.is_dir():
        raise ValueError(f"UI examples path is not a directory: {ui_examples_dir}")
    return sorted(ui_examples_dir.glob("*.json"), key=lambda path: path.name)


def _build_ui_examples_list_payload(*, ui_examples_dir: Path) -> list[dict[str, Any]]:
    from mmo.core.ui_screen_examples import load_ui_screen_example  # noqa: WPS433

    rows: list[dict[str, Any]] = []
    for path in _ui_examples_paths(ui_examples_dir=ui_examples_dir):
        payload = load_ui_screen_example(path)
        rows.append(
            {
                "filename": path.name,
                "screen_id": payload.get("screen_id", ""),
                "mode": payload.get("mode", ""),
                "title": payload.get("title", ""),
                "description": payload.get("description", ""),
            }
        )
    return rows


def _build_ui_examples_show_payload(
    *,
    ui_examples_dir: Path,
    filename: str,
) -> dict[str, Any]:
    from mmo.core.ui_screen_examples import load_ui_screen_example  # noqa: WPS433

    normalized_filename = filename.strip() if isinstance(filename, str) else ""
    if not normalized_filename:
        raise ValueError("filename must be a non-empty string.")
    if normalized_filename != Path(normalized_filename).name:
        raise ValueError("filename must not include a directory path.")
    if not normalized_filename.endswith(".json"):
        raise ValueError("filename must end with .json.")

    candidate = ui_examples_dir / normalized_filename
    if not candidate.exists():
        available = ", ".join(
            path.name for path in _ui_examples_paths(ui_examples_dir=ui_examples_dir)
        )
        raise ValueError(
            f"Unknown ui example filename: {normalized_filename}. "
            f"Available files: {available}"
        )

    payload = load_ui_screen_example(candidate)
    result = dict(payload)
    result["filename"] = normalized_filename
    return result


# ── Plugins helpers ───────────────────────────────────────────────


def _build_plugins_list_payload(*, plugins_dir: Path) -> list[dict[str, Any]]:
    from mmo.core.pipeline import load_plugins  # noqa: WPS433

    plugins = load_plugins(plugins_dir)
    payload: list[dict[str, Any]] = []
    for plugin in plugins:
        row: dict[str, Any] = {
            "plugin_id": plugin.plugin_id,
            "plugin_type": plugin.plugin_type,
            "version": plugin.version or "",
            "capabilities": {},
        }
        if plugin.capabilities is not None:
            row["capabilities"] = plugin.capabilities.to_dict()
        payload.append(row)
    return payload


def _render_plugins_list_text(payload: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in payload:
        plugin_id = row.get("plugin_id", "")
        capabilities = row.get("capabilities")
        max_channels = "-"
        contexts = "-"
        scene = "-"
        if isinstance(capabilities, dict):
            max_channels_value = capabilities.get("max_channels")
            if isinstance(max_channels_value, int):
                max_channels = str(max_channels_value)
            supported_contexts = capabilities.get("supported_contexts")
            if isinstance(supported_contexts, list):
                contexts_list = [
                    item for item in supported_contexts if isinstance(item, str) and item
                ]
                if contexts_list:
                    contexts = ",".join(contexts_list)
            scene_payload = capabilities.get("scene")
            if isinstance(scene_payload, dict):
                scene_parts: list[str] = []
                if scene_payload.get("supports_objects") is True:
                    scene_parts.append("objects")
                if scene_payload.get("supports_beds") is True:
                    scene_parts.append("beds")
                if scene_payload.get("supports_locks") is True:
                    scene_parts.append("locks")
                if scene_payload.get("requires_speaker_positions") is True:
                    scene_parts.append("requires_speaker_positions")
                supported_target_ids = scene_payload.get("supported_target_ids")
                if isinstance(supported_target_ids, list):
                    target_ids = [
                        item
                        for item in supported_target_ids
                        if isinstance(item, str) and item
                    ]
                    if target_ids:
                        scene_parts.append(f"targets={','.join(target_ids)}")
                if scene_parts:
                    scene = ",".join(scene_parts)
        lines.append(
            f"{plugin_id} (max_channels={max_channels}) contexts={contexts} scene={scene}"
        )
    return "\n".join(lines)


# ── Lock verify helpers ───────────────────────────────────────────


def _print_lock_verify_summary(verify_result: dict[str, Any]) -> None:
    missing = verify_result.get("missing", [])
    extra = verify_result.get("extra", [])
    changed = verify_result.get("changed", [])
    ok = bool(verify_result.get("ok"))

    status = "ok" if ok else "drift detected"
    print(f"lock verify: {status}")
    print(
        "summary:"
        f" missing={len(missing)}"
        f" extra={len(extra)}"
        f" changed={len(changed)}"
    )

    for rel in missing:
        print(f"- missing: {rel}")
    for rel in extra:
        print(f"- extra: {rel}")
    for item in changed:
        if not isinstance(item, dict):
            continue
        rel = item.get("rel", "")
        expected_sha = item.get("expected_sha", "")
        actual_sha = item.get("actual_sha", "")
        print(
            f"- changed: {rel}"
            f" expected_sha={expected_sha}"
            f" actual_sha={actual_sha}"
        )
