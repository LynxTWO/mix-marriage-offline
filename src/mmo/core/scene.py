from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCENE_SCHEMA_VERSION = "0.1.0"
_DEFAULT_CREATED_FROM = "analyze"
_LOCK_HASH_PREFIX_LEN = 12


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _coerce_channel_count(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, float) and value >= 1:
        return int(value)
    return 1


def _stems_dir_from_report(report: dict[str, Any]) -> str:
    session = report.get("session")
    if not isinstance(session, dict):
        raise ValueError("report.session must be an object.")

    stems_dir = _coerce_str(session.get("stems_dir")).strip()
    if not stems_dir:
        raise ValueError("report.session.stems_dir is required to build a scene.")
    stems_dir_path = Path(stems_dir)
    if not stems_dir_path.is_absolute():
        raise ValueError("report.session.stems_dir must be an absolute path.")
    return stems_dir_path.resolve().as_posix()


def _scene_id(*, report_id: str, lock_hash: str | None) -> str:
    if report_id:
        return f"SCENE.{report_id}"
    if isinstance(lock_hash, str) and lock_hash:
        return f"SCENE.{lock_hash[:_LOCK_HASH_PREFIX_LEN]}"
    return "SCENE.UNKNOWN"


def _object_label(stem: dict[str, Any], *, stem_id: str, default_index: int) -> str:
    label = _coerce_str(stem.get("label")).strip()
    if label:
        return label

    file_name = _coerce_str(stem.get("file_name")).strip()
    if file_name:
        return file_name

    file_path = _coerce_str(stem.get("file_path")).strip()
    if file_path:
        return Path(file_path).name

    return stem_id or f"stem_{default_index:03d}"


def _build_objects(report: dict[str, Any]) -> list[dict[str, Any]]:
    session = report.get("session")
    stems = session.get("stems") if isinstance(session, dict) else None
    if not isinstance(stems, list):
        return []

    objects: list[dict[str, Any]] = []
    for index, raw_stem in enumerate(stems):
        if not isinstance(raw_stem, dict):
            continue
        stem_id = _coerce_str(raw_stem.get("stem_id")).strip() or f"STEM.{index:03d}"
        object_id = f"OBJ.{stem_id}"
        object_entry = {
            "object_id": object_id,
            "stem_id": stem_id,
            "label": _object_label(raw_stem, stem_id=stem_id, default_index=index),
            "channel_count": _coerce_channel_count(raw_stem.get("channel_count")),
            "intent": {
                "confidence": 0.0,
                "locks": [],
            },
            "notes": _string_list(raw_stem.get("notes")),
        }
        objects.append(object_entry)

    objects.sort(key=lambda item: (item["stem_id"], item["object_id"]))
    return objects


def _default_beds() -> list[dict[str, Any]]:
    return [
        {
            "bed_id": "BED.FIELD.001",
            "label": "Field",
            "kind": "field",
            "intent": {
                "diffuse": 0.5,
                "confidence": 0.0,
                "locks": [],
            },
            "notes": [],
        }
    ]


def _metadata_from_report(report: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    profile_id = _coerce_str(report.get("profile_id")).strip()
    if profile_id:
        metadata["profile_id"] = profile_id

    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        preset_id = _coerce_str(run_config.get("preset_id")).strip()
        if preset_id:
            metadata["preset_id"] = preset_id

    vibe_signals = report.get("vibe_signals")
    if isinstance(vibe_signals, dict):
        vibe: dict[str, Any] = {}
        for key in ("density_level", "masking_level", "translation_risk"):
            value = _coerce_str(vibe_signals.get(key)).strip()
            if value:
                vibe[key] = value
        notes = _string_list(vibe_signals.get("notes"))
        if notes:
            vibe["notes"] = notes
        if vibe:
            metadata["vibe"] = vibe

    return metadata


def build_scene_from_report(
    report: dict[str, Any],
    *,
    timeline: dict[str, Any] | None = None,
    lock_hash: str | None = None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("report must be an object.")

    report_id = _coerce_str(report.get("report_id")).strip()
    normalized_lock_hash = _coerce_str(lock_hash).strip() or None

    source: dict[str, Any] = {
        "stems_dir": _stems_dir_from_report(report),
        "created_from": _DEFAULT_CREATED_FROM,
    }
    if report_id:
        source["report_id"] = report_id
    if normalized_lock_hash is not None:
        source["lock_hash"] = normalized_lock_hash

    scene: dict[str, Any] = {
        "schema_version": SCENE_SCHEMA_VERSION,
        "scene_id": _scene_id(report_id=report_id, lock_hash=normalized_lock_hash),
        "source": source,
        "objects": _build_objects(report),
        "beds": _default_beds(),
        "metadata": _metadata_from_report(report),
    }
    if timeline is not None:
        scene["timeline"] = _json_clone(timeline)
    return scene
