from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

UI_BUNDLE_SCHEMA_VERSION = "0.1.0"
TOP_ISSUE_LIMIT = 5
_RISK_LEVELS = {"low", "medium", "high"}
_BASELINE_RENDER_TARGET_ID = "TARGET.STEREO.2_0"
_SCENE_LOCK_SEVERITIES = {"hard", "taste"}
_SCENE_LOCK_APPLIES_TO = {"object", "bed", "scene"}
_UNKNOWN_LOCK_DESCRIPTION = "Unknown lock ID; definition not found in the scene lock registry."


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _top_issues(report: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for issue in _iter_dict_list(report.get("issues")):
        issue_id = issue.get("issue_id")
        severity = issue.get("severity")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        if not isinstance(severity, int) or isinstance(severity, bool):
            continue
        message = issue.get("message")
        ranked.append(
            {
                "issue_id": issue_id,
                "severity": severity,
                "summary": message if isinstance(message, str) else "",
            }
        )
    ranked.sort(key=lambda item: (-item["severity"], item["issue_id"], item["summary"]))
    return ranked[:limit]


def _recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    return _iter_dict_list(report.get("recommendations"))


def _list_length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _renderer_manifests(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    return _iter_dict_list(manifest.get("renderer_manifests"))


def _manifest_deliverables(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    return _iter_dict_list(manifest.get("deliverables"))


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]
    return sorted(set(normalized))


def _dashboard_deliverable_entry(
    deliverable: dict[str, Any],
    *,
    id_prefix: str = "",
    label_suffix: str = "",
) -> dict[str, Any] | None:
    deliverable_id = _coerce_str(deliverable.get("deliverable_id")).strip()
    if not deliverable_id:
        return None

    label = _coerce_str(deliverable.get("label")).strip() or "Deliverable"
    output_count = 0
    output_ids = deliverable.get("output_ids")
    if isinstance(output_ids, list):
        output_count = sum(
            1
            for item in output_ids
            if isinstance(item, str) and item.strip()
        )

    mapped: dict[str, Any] = {
        "deliverable_id": f"{id_prefix}{deliverable_id}",
        "label": f"{label}{label_suffix}",
        "output_count": output_count,
    }

    target_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip()
    if target_layout_id:
        mapped["target_layout_id"] = target_layout_id

    channel_count = deliverable.get("channel_count")
    if isinstance(channel_count, int) and not isinstance(channel_count, bool) and channel_count >= 1:
        mapped["channel_count"] = channel_count

    formats = _normalized_string_list(deliverable.get("formats"))
    if formats:
        mapped["formats"] = formats

    return mapped


def _dashboard_deliverables(
    render_manifest: dict[str, Any] | None,
    apply_manifest: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for deliverable in _manifest_deliverables(render_manifest):
        item = _dashboard_deliverable_entry(deliverable)
        if item is not None:
            mapped.append(item)
    for deliverable in _manifest_deliverables(apply_manifest):
        item = _dashboard_deliverable_entry(
            deliverable,
            id_prefix="APPLY.",
            label_suffix=" (apply)",
        )
        if item is not None:
            mapped.append(item)

    mapped.sort(
        key=lambda item: (
            _coerce_str(item.get("deliverable_id")).strip(),
            _coerce_str(item.get("label")).strip(),
        )
    )
    return mapped


def _count_if_true(recommendations: list[dict[str, Any]], field: str) -> int:
    return sum(1 for rec in recommendations if rec.get(field) is True)


def _count_if_not_true(recommendations: list[dict[str, Any]], field: str) -> int:
    return sum(1 for rec in recommendations if rec.get(field) is not True)


def _profile_id(report: dict[str, Any]) -> str:
    profile = report.get("profile_id")
    if isinstance(profile, str):
        return profile
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        run_profile = run_config.get("profile_id")
        if isinstance(run_profile, str):
            return run_profile
    return ""


def _preset_id(report: dict[str, Any]) -> str:
    run_config = report.get("run_config")
    if not isinstance(run_config, dict):
        return ""
    preset_id = run_config.get("preset_id")
    if isinstance(preset_id, str):
        return preset_id
    return ""


def _help_id_for_preset(preset_id: str) -> str | None:
    from mmo.core.presets import get_preset_help_id  # noqa: WPS433

    normalized = preset_id.strip()
    if not normalized:
        return None
    return get_preset_help_id(normalized)


def _help_id_for_profile(profile_id: str) -> str | None:
    normalized = profile_id.strip()
    if not normalized or not normalized.startswith("PROFILE."):
        return None
    return f"HELP.MODE.{normalized[len('PROFILE.'):]}"


def _normalized_preset_recommendations(
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for recommendation in recommendations:
        preset_id = recommendation.get("preset_id")
        if not isinstance(preset_id, str) or not preset_id.strip():
            continue

        reasons_value = recommendation.get("reasons")
        if not isinstance(reasons_value, list):
            continue
        reasons = [
            reason.strip()
            for reason in reasons_value
            if isinstance(reason, str) and reason.strip()
        ]
        if not reasons:
            continue

        item: dict[str, Any] = {
            "preset_id": preset_id.strip(),
            "reasons": reasons,
        }

        overlay = recommendation.get("overlay")
        if isinstance(overlay, str) and overlay.strip():
            item["overlay"] = overlay.strip()

        help_id = recommendation.get("help_id")
        if isinstance(help_id, str) and help_id.strip():
            item["help_id"] = help_id.strip()

        normalized.append(item)
    return normalized


def _dashboard_preset_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    if "preset_recommendations" in report:
        raw = report.get("preset_recommendations")
        return _normalized_preset_recommendations(_iter_dict_list(raw))

    from mmo.core.preset_recommendations import derive_preset_recommendations  # noqa: WPS433

    derived = derive_preset_recommendations(report, _repo_root() / "presets")
    return _normalized_preset_recommendations(_iter_dict_list(derived))


def _collect_help_ids(
    report: dict[str, Any],
    *,
    preset_recommendations: list[dict[str, Any]],
) -> list[str]:
    help_ids: set[str] = set()
    profile_help_id = _help_id_for_profile(_profile_id(report))
    if profile_help_id is not None:
        help_ids.add(profile_help_id)

    preset_help_id = _help_id_for_preset(_preset_id(report))
    if preset_help_id is not None:
        help_ids.add(preset_help_id)

    for recommendation in preset_recommendations:
        help_id = recommendation.get("help_id")
        if isinstance(help_id, str) and help_id.strip():
            help_ids.add(help_id.strip())
            continue
        preset_id = recommendation.get("preset_id")
        if isinstance(preset_id, str) and preset_id.strip():
            mapped_help_id = _help_id_for_preset(preset_id)
            if mapped_help_id is not None:
                help_ids.add(mapped_help_id)

    return sorted(help_ids)


def _resolve_repo_path(path: Path) -> Path:
    if path.exists() or path.is_absolute():
        return path
    repo_relative = Path(__file__).resolve().parents[3] / path
    if repo_relative.exists():
        return repo_relative
    return path


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _validate_json_payload(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate UI bundle dependencies.")

    from mmo.core.schema_registry import build_schema_registry, load_json_schema  # noqa: WPS433

    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _load_scene_payload(scene_path: Path | None) -> dict[str, Any] | None:
    if scene_path is None:
        return None

    resolved_scene_path = _resolve_repo_path(scene_path)
    if not resolved_scene_path.exists():
        return None
    if not resolved_scene_path.is_file():
        raise ValueError(f"Scene path is not a file: {resolved_scene_path}")

    payload = _load_json_object(resolved_scene_path, label="Scene")
    _validate_json_payload(
        payload,
        schema_path=_repo_root() / "schemas" / "scene.schema.json",
        payload_name="Scene",
    )
    return payload


def _normalized_lock_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        }
    )


def _intent_lock_ids(intent: Any) -> list[str]:
    intent_payload = intent if isinstance(intent, dict) else {}
    return _normalized_lock_ids(intent_payload.get("locks"))


def _scene_lock_specs(scene_locks_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locks = scene_locks_registry.get("locks")
    if not isinstance(locks, dict):
        return {}
    return {
        lock_id: dict(lock_spec)
        for lock_id, lock_spec in locks.items()
        if isinstance(lock_id, str) and isinstance(lock_spec, dict)
    }


def _scene_lock_summary(
    lock_id: str,
    scene_lock_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    lock_spec = scene_lock_specs.get(lock_id)
    if not isinstance(lock_spec, dict):
        return {
            "lock_id": lock_id,
            "label": lock_id,
            "description": _UNKNOWN_LOCK_DESCRIPTION,
            "severity": "taste",
            "applies_to": [],
        }

    label = _coerce_str(lock_spec.get("label")).strip() or lock_id
    description = _coerce_str(lock_spec.get("description"))
    severity = _coerce_str(lock_spec.get("severity")).strip()
    if severity not in _SCENE_LOCK_SEVERITIES:
        severity = "taste"
    applies_to = sorted(
        {
            item
            for item in lock_spec.get("applies_to", [])
            if isinstance(item, str) and item in _SCENE_LOCK_APPLIES_TO
        }
    )
    return {
        "lock_id": lock_id,
        "label": label,
        "description": description,
        "severity": severity,
        "applies_to": applies_to,
    }


def _scene_overlay_lock_summary(
    lock_id: str,
    scene_lock_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    lock_summary = _scene_lock_summary(lock_id, scene_lock_specs)
    return {
        "lock_id": lock_summary["lock_id"],
        "label": lock_summary["label"],
        "severity": lock_summary["severity"],
    }


def _scene_lock_ids_used(scene_payload: dict[str, Any]) -> list[str]:
    lock_ids: set[str] = set(_intent_lock_ids(scene_payload.get("intent")))
    for object_payload in _iter_dict_list(scene_payload.get("objects")):
        lock_ids.update(_intent_lock_ids(object_payload.get("intent")))
    for bed_payload in _iter_dict_list(scene_payload.get("beds")):
        lock_ids.update(_intent_lock_ids(bed_payload.get("intent")))
    return sorted(lock_ids)


def _intent_param_defs(intent_params_registry: dict[str, Any]) -> list[dict[str, Any]]:
    params = intent_params_registry.get("params")
    if not isinstance(params, dict):
        return []

    normalized: list[dict[str, Any]] = []
    for param_id in sorted(params.keys()):
        param_spec = params.get(param_id)
        if not isinstance(param_id, str) or not isinstance(param_spec, dict):
            continue
        param_type = _coerce_str(param_spec.get("type")).strip()
        if param_type not in {"number", "enum"}:
            continue

        entry: dict[str, Any] = {
            "param_id": param_id,
            "type": param_type,
        }

        unit = _coerce_str(param_spec.get("unit")).strip()
        if unit:
            entry["unit"] = unit

        min_value = param_spec.get("min")
        if isinstance(min_value, (int, float)) and not isinstance(min_value, bool):
            entry["min"] = float(min_value)

        max_value = param_spec.get("max")
        if isinstance(max_value, (int, float)) and not isinstance(max_value, bool):
            entry["max"] = float(max_value)

        values = param_spec.get("values")
        if isinstance(values, list):
            normalized_values = [
                item.strip()
                for item in values
                if isinstance(item, str) and item.strip()
            ]
            if normalized_values:
                entry["values"] = normalized_values

        if "default" in param_spec:
            default_value = param_spec.get("default")
            if (
                default_value is None
                or isinstance(default_value, (str, bool))
                or (isinstance(default_value, (int, float)) and not isinstance(default_value, bool))
            ):
                entry["default"] = default_value

        normalized.append(entry)
    return normalized


def _scene_objects_by_stem_id(scene_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for object_payload in _iter_dict_list(scene_payload.get("objects")):
        stem_id = _coerce_str(object_payload.get("stem_id")).strip()
        if stem_id and stem_id not in mapping:
            mapping[stem_id] = object_payload
    return mapping


def _recommendation_target_stem_id(recommendation: dict[str, Any]) -> str:
    direct_target_stem_id = _coerce_str(recommendation.get("target_stem_id")).strip()
    if direct_target_stem_id:
        return direct_target_stem_id

    direct_stem_id = _coerce_str(recommendation.get("stem_id")).strip()
    if direct_stem_id:
        return direct_stem_id

    target = recommendation.get("target")
    if isinstance(target, dict):
        target_stem_id = _coerce_str(target.get("stem_id")).strip()
        if target_stem_id:
            return target_stem_id
    return ""


def _scene_meta_payload(
    scene_payload: dict[str, Any],
    scene_locks_registry: dict[str, Any],
    intent_params_registry: dict[str, Any],
) -> dict[str, Any]:
    scene_lock_specs = _scene_lock_specs(scene_locks_registry)
    lock_ids_used = _scene_lock_ids_used(scene_payload)
    return {
        "locks_used": [
            _scene_lock_summary(lock_id, scene_lock_specs)
            for lock_id in lock_ids_used
        ],
        "intent_param_defs": _intent_param_defs(intent_params_registry),
    }


def _recommendation_overlays_payload(
    report: dict[str, Any],
    scene_payload: dict[str, Any],
    scene_locks_registry: dict[str, Any],
) -> dict[str, Any]:
    recommendation_rows: list[tuple[str, dict[str, Any]]] = []
    recommendations = _recommendations(report)
    if not recommendations:
        return {}

    scene_lock_specs = _scene_lock_specs(scene_locks_registry)
    scene_level_lock_ids = _intent_lock_ids(scene_payload.get("intent"))
    objects_by_stem_id = _scene_objects_by_stem_id(scene_payload)
    for recommendation in recommendations:
        recommendation_id = _coerce_str(recommendation.get("recommendation_id")).strip()
        if not recommendation_id:
            continue

        target_stem_id = _recommendation_target_stem_id(recommendation)
        object_payload = objects_by_stem_id.get(target_stem_id)

        lock_ids_in_effect: set[str] = set(scene_level_lock_ids)
        if isinstance(object_payload, dict):
            lock_ids_in_effect.update(_intent_lock_ids(object_payload.get("intent")))

        scope: dict[str, Any] = {"scene": True}
        if isinstance(object_payload, dict):
            object_id = _coerce_str(object_payload.get("object_id")).strip()
            if object_id:
                scope["object_id"] = object_id

        recommendation_rows.append(
            (
                recommendation_id,
                {
                    "locks_in_effect": [
                        _scene_overlay_lock_summary(lock_id, scene_lock_specs)
                        for lock_id in sorted(lock_ids_in_effect)
                    ],
                    "scope": scope,
                },
            )
        )

    return {
        recommendation_id: payload
        for recommendation_id, payload in sorted(recommendation_rows, key=lambda row: row[0])
    }


def _screen_template_ui_copy_keys(gui_design_payload: dict[str, Any]) -> list[str]:
    screen_templates = gui_design_payload.get("screen_templates")
    if not isinstance(screen_templates, dict):
        return []
    return sorted(
        {
            f"COPY.NAV.{screen_id.strip().upper()}"
            for screen_id in screen_templates.keys()
            if isinstance(screen_id, str) and screen_id.strip()
        }
    )


def _dashboard_ui_copy_keys(_dashboard: dict[str, Any]) -> set[str]:
    return {
        "COPY.PANEL.SIGNALS.TITLE",
        "COPY.PANEL.DELIVERABLES.TITLE",
        "COPY.BADGE.EXTREME",
        "COPY.BADGE.BLOCKED",
    }


def _collect_ui_copy_keys(dashboard: dict[str, Any], gui_design_payload: dict[str, Any]) -> list[str]:
    keys = _dashboard_ui_copy_keys(dashboard)
    keys.update(_screen_template_ui_copy_keys(gui_design_payload))
    return sorted(keys)


def _ui_copy_locale_ids(registry: dict[str, Any]) -> list[str]:
    locales = registry.get("locales")
    if not isinstance(locales, dict):
        return []
    return sorted(
        locale_id.strip()
        for locale_id in locales.keys()
        if isinstance(locale_id, str) and locale_id.strip()
    )


def _resolve_ui_copy_locale(registry: dict[str, Any], requested_locale: str | None) -> str:
    locale_ids = _ui_copy_locale_ids(registry)
    normalized_locale = (
        requested_locale.strip()
        if isinstance(requested_locale, str) and requested_locale.strip()
        else ""
    )
    if normalized_locale:
        if locale_ids and normalized_locale not in locale_ids:
            joined_locales = ", ".join(locale_ids)
            raise ValueError(
                f"Unknown ui locale: {normalized_locale}. Available locales: {joined_locales}"
            )
        return normalized_locale

    default_locale = registry.get("default_locale")
    normalized_default = default_locale.strip() if isinstance(default_locale, str) else ""
    if normalized_default and normalized_default in locale_ids:
        return normalized_default
    if locale_ids:
        return locale_ids[0]
    return normalized_default or "en-US"


def _collect_downmix_metric_values(downmix_qa: dict[str, Any], evidence_id: str) -> list[float]:
    values: list[float] = []
    for measurement in _iter_dict_list(downmix_qa.get("measurements")):
        if measurement.get("evidence_id") != evidence_id:
            continue
        numeric = _numeric_value(measurement.get("value"))
        if numeric is not None:
            values.append(numeric)

    for issue in _iter_dict_list(downmix_qa.get("issues")):
        for evidence in _iter_dict_list(issue.get("evidence")):
            if evidence.get("evidence_id") != evidence_id:
                continue
            numeric = _numeric_value(evidence.get("value"))
            if numeric is not None:
                values.append(numeric)
    return values


def _downmix_qa_summary(report: dict[str, Any]) -> dict[str, Any]:
    downmix_qa = report.get("downmix_qa")
    if not isinstance(downmix_qa, dict):
        return {
            "has_issues": False,
            "max_delta_lufs": None,
            "max_delta_true_peak": None,
            "min_corr": None,
        }

    issue_count = len(_iter_dict_list(downmix_qa.get("issues")))
    lufs_delta_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.LUFS_DELTA")
    true_peak_delta_values = _collect_downmix_metric_values(
        downmix_qa, "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA"
    )
    corr_fold_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.CORR_FOLD")
    corr_ref_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.CORR_REF")
    corr_values = corr_fold_values + corr_ref_values
    return {
        "has_issues": issue_count > 0,
        "max_delta_lufs": max((abs(value) for value in lufs_delta_values), default=None),
        "max_delta_true_peak": max(
            (abs(value) for value in true_peak_delta_values), default=None
        ),
        "min_corr": min(corr_values, default=None),
    }


def _mix_complexity_summary(report: dict[str, Any]) -> dict[str, Any]:
    mix_complexity = report.get("mix_complexity")
    if not isinstance(mix_complexity, dict):
        return {
            "density_mean": None,
            "density_peak": None,
            "top_masking_pairs_count": 0,
        }

    density_mean = _numeric_value(mix_complexity.get("density_mean"))
    density_peak_numeric = _numeric_value(mix_complexity.get("density_peak"))
    density_peak = int(density_peak_numeric) if density_peak_numeric is not None else None

    top_pairs = mix_complexity.get("top_masking_pairs")
    if isinstance(top_pairs, list):
        top_masking_pairs_count = len(top_pairs)
    else:
        top_count = _numeric_value(mix_complexity.get("top_masking_pairs_count"))
        top_masking_pairs_count = int(top_count) if top_count is not None else 0

    return {
        "density_mean": density_mean,
        "density_peak": density_peak,
        "top_masking_pairs_count": top_masking_pairs_count,
    }


def _vibe_signals_summary(report: dict[str, Any]) -> dict[str, Any] | None:
    vibe_signals = report.get("vibe_signals")
    if not isinstance(vibe_signals, dict):
        return None

    density_level = vibe_signals.get("density_level")
    masking_level = vibe_signals.get("masking_level")
    translation_risk = vibe_signals.get("translation_risk")
    if (
        density_level not in _RISK_LEVELS
        or masking_level not in _RISK_LEVELS
        or translation_risk not in _RISK_LEVELS
    ):
        return None

    notes = vibe_signals.get("notes")
    note_items: list[str] = []
    if isinstance(notes, list):
        note_items = [item for item in notes if isinstance(item, str)]

    return {
        "density_level": density_level,
        "masking_level": masking_level,
        "translation_risk": translation_risk,
        "notes": note_items,
    }


def _apply_summary(report: dict[str, Any], apply_manifest: dict[str, Any]) -> dict[str, int]:
    recommendations = _recommendations(report)
    renderer_manifests = _renderer_manifests(apply_manifest)
    return {
        "eligible_count": _count_if_true(recommendations, "eligible_auto_apply"),
        "blocked_count": _count_if_not_true(recommendations, "eligible_auto_apply"),
        "outputs_count": sum(
            _list_length(manifest.get("outputs")) for manifest in renderer_manifests
        ),
        "skipped_count": sum(
            _list_length(manifest.get("skipped")) for manifest in renderer_manifests
        ),
    }


def _project_last_run_summary(last_run: Any) -> dict[str, Any] | None:
    if not isinstance(last_run, dict):
        return None

    summary: dict[str, Any] = {}
    mode = last_run.get("mode")
    out_dir = last_run.get("out_dir")
    if isinstance(mode, str):
        summary["mode"] = mode
    if isinstance(out_dir, str):
        summary["out_dir"] = out_dir
    for key in (
        "deliverables_index_path",
        "listen_pack_path",
        "variant_plan_path",
        "variant_result_path",
    ):
        value = last_run.get(key)
        if isinstance(value, str):
            summary[key] = value

    if "mode" not in summary or "out_dir" not in summary:
        return None
    return summary


def _project_summary(project_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": _coerce_str(project_payload.get("project_id")).strip(),
        "stems_dir": _coerce_str(project_payload.get("stems_dir")).strip(),
        "last_run": _project_last_run_summary(project_payload.get("last_run")),
        "updated_at_utc": _coerce_str(project_payload.get("updated_at_utc")).strip(),
    }


def _gui_design_summary(gui_design_payload: dict[str, Any]) -> dict[str, Any]:
    theme = gui_design_payload.get("theme")
    theme_mapping = theme if isinstance(theme, dict) else {}
    palette = theme_mapping.get("palette")
    typography = theme_mapping.get("typography")
    layout_rules = gui_design_payload.get("layout_rules")
    return {
        "palette": palette if isinstance(palette, dict) else {},
        "typography": typography if isinstance(typography, dict) else {},
        "layout_rules": layout_rules if isinstance(layout_rules, dict) else {},
    }


def _bundle_pointers(
    *,
    project_path: Path | None,
    deliverables_index_path: Path | None,
    listen_pack_path: Path | None,
    scene_path: Path | None,
    render_plan_path: Path | None,
    timeline_path: Path | None,
) -> dict[str, str]:
    pointers: dict[str, str] = {}
    if deliverables_index_path is not None:
        pointers["deliverables_index_path"] = _path_to_posix(deliverables_index_path)
    if listen_pack_path is not None:
        pointers["listen_pack_path"] = _path_to_posix(listen_pack_path)
    if scene_path is not None:
        pointers["scene_path"] = _path_to_posix(scene_path)
    if render_plan_path is not None:
        pointers["render_plan_path"] = _path_to_posix(render_plan_path)
    if timeline_path is not None:
        pointers["timeline_path"] = _path_to_posix(timeline_path)
    if project_path is not None:
        pointers["project_path"] = _path_to_posix(project_path)
    return pointers


def _collect_referenced_target_layout_ids(
    report: dict[str, Any],
    dashboard_deliverables: list[dict[str, Any]],
) -> set[str]:
    layout_ids: set[str] = set()

    routing_plan = report.get("routing_plan")
    if isinstance(routing_plan, dict):
        target_layout_id = _coerce_str(routing_plan.get("target_layout_id")).strip()
        if target_layout_id:
            layout_ids.add(target_layout_id)

    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        downmix_cfg = run_config.get("downmix")
        if isinstance(downmix_cfg, dict):
            target_layout_id = _coerce_str(downmix_cfg.get("target_layout_id")).strip()
            if target_layout_id:
                layout_ids.add(target_layout_id)

    for deliverable in dashboard_deliverables:
        target_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip()
        if target_layout_id:
            layout_ids.add(target_layout_id)
    return layout_ids


def _ui_bundle_render_targets(
    report: dict[str, Any],
    dashboard_deliverables: list[dict[str, Any]],
) -> dict[str, Any]:
    from mmo.core.render_targets import get_render_target, list_render_targets  # noqa: WPS433

    referenced_layout_ids = _collect_referenced_target_layout_ids(
        report,
        dashboard_deliverables,
    )
    selected_targets: dict[str, dict[str, Any]] = {}

    baseline_target = get_render_target(_BASELINE_RENDER_TARGET_ID)
    if baseline_target is None:
        raise ValueError(
            "Render targets registry is missing baseline target: "
            f"{_BASELINE_RENDER_TARGET_ID}"
        )
    selected_targets[_BASELINE_RENDER_TARGET_ID] = dict(baseline_target)

    for target in list_render_targets():
        target_id = _coerce_str(target.get("target_id")).strip()
        layout_id = _coerce_str(target.get("layout_id")).strip()
        if not target_id or not layout_id:
            continue
        if layout_id in referenced_layout_ids:
            selected_targets[target_id] = dict(target)

    return {
        "targets": [
            selected_targets[target_id]
            for target_id in sorted(selected_targets.keys())
        ]
    }


def build_ui_bundle(
    report: dict[str, Any],
    render_manifest: dict[str, Any] | None,
    apply_manifest: dict[str, Any] | None = None,
    applied_report: dict[str, Any] | None = None,
    help_registry_path: Path = Path("ontology/help.yaml"),
    ui_copy_path: Path = Path("ontology/ui_copy.yaml"),
    ui_locale: str | None = None,
    project_path: Path | None = None,
    deliverables_index_path: Path | None = None,
    listen_pack_path: Path | None = None,
    scene_path: Path | None = None,
    render_plan_path: Path | None = None,
    timeline_path: Path | None = None,
) -> dict[str, Any]:
    from mmo.core.gui_design import load_gui_design  # noqa: WPS433
    from mmo.core.help_registry import load_help_registry, resolve_help_entries  # noqa: WPS433
    from mmo.core.intent_params import load_intent_params  # noqa: WPS433
    from mmo.core.scene_locks import load_scene_locks  # noqa: WPS433
    from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy  # noqa: WPS433

    gui_design_payload = load_gui_design(_repo_root() / "ontology" / "gui_design.yaml")
    recommendations = _recommendations(report)
    preset_recommendations = _dashboard_preset_recommendations(report)
    dashboard = {
        "profile_id": _profile_id(report),
        "top_issues": _top_issues(report, limit=TOP_ISSUE_LIMIT),
        "eligible_counts": {
            "auto_apply": _count_if_true(recommendations, "eligible_auto_apply"),
            "render": _count_if_true(recommendations, "eligible_render"),
        },
        "blocked_counts": {
            "auto_apply": _count_if_not_true(recommendations, "eligible_auto_apply"),
            "render": _count_if_not_true(recommendations, "eligible_render"),
        },
        "extreme_count": _count_if_true(recommendations, "extreme"),
        "downmix_qa": _downmix_qa_summary(report),
        "mix_complexity": _mix_complexity_summary(report),
    }
    vibe_signals_summary = _vibe_signals_summary(report)
    if vibe_signals_summary is not None:
        dashboard["vibe_signals"] = vibe_signals_summary
    if preset_recommendations:
        dashboard["preset_recommendations"] = preset_recommendations
    if apply_manifest is not None:
        dashboard["apply"] = _apply_summary(report, apply_manifest)
    dashboard_deliverables = _dashboard_deliverables(render_manifest, apply_manifest)
    if dashboard_deliverables:
        dashboard["deliverables"] = dashboard_deliverables

    payload: dict[str, Any] = {
        "schema_version": UI_BUNDLE_SCHEMA_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "report": report,
        "dashboard": dashboard,
        "gui_design": _gui_design_summary(gui_design_payload),
        "render_targets": _ui_bundle_render_targets(report, dashboard_deliverables),
    }
    scene_payload = _load_scene_payload(scene_path)
    if scene_payload is not None:
        scene_locks_registry = load_scene_locks()
        intent_params_registry = load_intent_params()
        payload["scene_meta"] = _scene_meta_payload(
            scene_payload,
            scene_locks_registry,
            intent_params_registry,
        )
        recommendation_overlays = _recommendation_overlays_payload(
            report,
            scene_payload,
            scene_locks_registry,
        )
        if recommendation_overlays:
            payload["recommendation_overlays"] = recommendation_overlays

    help_ids = _collect_help_ids(
        report,
        preset_recommendations=preset_recommendations,
    )
    if help_ids:
        registry = load_help_registry(_resolve_repo_path(help_registry_path))
        payload["help"] = resolve_help_entries(help_ids, registry)

    ui_copy_registry = load_ui_copy(_resolve_repo_path(ui_copy_path))
    resolved_ui_locale = _resolve_ui_copy_locale(ui_copy_registry, ui_locale)
    ui_copy_keys = _collect_ui_copy_keys(dashboard, gui_design_payload)
    if ui_copy_keys:
        payload["ui_copy"] = {
            "locale": resolved_ui_locale,
            "entries": resolve_ui_copy(
                ui_copy_keys,
                ui_copy_registry,
                locale=resolved_ui_locale,
            ),
        }

    if render_manifest is not None:
        payload["render_manifest"] = render_manifest
    if apply_manifest is not None:
        payload["apply_manifest"] = apply_manifest
    if applied_report is not None:
        payload["applied_report"] = applied_report

    if project_path is not None:
        from mmo.core.project_file import load_project  # noqa: WPS433

        payload["project"] = _project_summary(load_project(project_path))

    pointers = _bundle_pointers(
        project_path=project_path,
        deliverables_index_path=deliverables_index_path,
        listen_pack_path=listen_pack_path,
        scene_path=scene_path,
        render_plan_path=render_plan_path,
        timeline_path=timeline_path,
    )
    if pointers:
        payload["pointers"] = pointers
    return payload
