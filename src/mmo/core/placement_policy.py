from __future__ import annotations

import math
from typing import Any

from mmo.dsp.downmix import load_layouts
from mmo.resources import ontology_dir

PLACEMENT_POLICY_ID = "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1"
PLACEMENT_POLICY_SCHEMA_VERSION = "0.1.0"

_SUPPORTED_LAYOUT_IDS: frozenset[str] = frozenset(
    {
        "LAYOUT.2_0",
        "LAYOUT.5_1",
        "LAYOUT.7_1",
        "LAYOUT.7_1_4",
        "LAYOUT.7_1_6",
        "LAYOUT.9_1_6",
    }
)

_FRONT_LEFT = "SPK.L"
_FRONT_RIGHT = "SPK.R"
_CENTER = "SPK.C"
_SIDE_LEFT = "SPK.LS"
_SIDE_RIGHT = "SPK.RS"
_REAR_LEFT = "SPK.LRS"
_REAR_RIGHT = "SPK.RRS"
_WIDE_LEFT = "SPK.LW"
_WIDE_RIGHT = "SPK.RW"
_TOP_FRONT_LEFT = "SPK.TFL"
_TOP_FRONT_RIGHT = "SPK.TFR"
_TOP_REAR_LEFT = "SPK.TRL"
_TOP_REAR_RIGHT = "SPK.TRR"
_TOP_FRONT_CENTER = "SPK.TFC"
_TOP_BACK_CENTER = "SPK.TBC"

_LOCK_NO_STEREO_WIDENING = "LOCK.NO_STEREO_WIDENING"
_LOCK_NO_HEIGHT_SEND = "LOCK.NO_HEIGHT_SEND"
_LOCK_PRESERVE_CENTER_IMAGE = "LOCK.PRESERVE_CENTER_IMAGE"

_ROLE_UNKNOWN = "ROLE.OTHER.UNKNOWN"
_BUS_UNKNOWN = "BUS.OTHER"

_BED_SURROUND_RELATIVE_DB = -12.0
_BED_SURROUND_SEND_CAP = 0.2
_BED_SURROUND_CONFIDENCE_MIN = 0.6
_IMMERSIVE_PERSPECTIVES: frozenset[str] = frozenset({"in_band", "in_orchestra"})


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clamp_unit(value: Any, *, default: float) -> float:
    numeric = _coerce_float(value)
    if numeric is None:
        numeric = default
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return round(numeric, 3)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _layout_channel_order(
    target_layout_id: str,
    *,
    layouts: dict[str, Any] | None,
) -> list[str]:
    layout_map = layouts
    if not isinstance(layout_map, dict):
        try:
            layout_map = load_layouts(ontology_dir() / "layouts.yaml")
        except (RuntimeError, ValueError):
            return []
    entry = layout_map.get(target_layout_id)
    if not isinstance(entry, dict):
        return []
    channel_order = entry.get("channel_order")
    if not isinstance(channel_order, list):
        return []
    normalized: list[str] = []
    for speaker_id in channel_order:
        speaker = _coerce_str(speaker_id).strip().upper()
        if speaker:
            normalized.append(speaker)
    return normalized


def _scene_objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    raw_objects = scene.get("objects")
    if not isinstance(raw_objects, list):
        return []
    rows: list[tuple[str, str, int, dict[str, Any]]] = []
    for index, row in enumerate(raw_objects):
        if not isinstance(row, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if not stem_id:
            continue
        object_id = _coerce_str(row.get("object_id")).strip()
        rows.append((stem_id, object_id, index, row))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in rows]


def _scene_beds(scene: dict[str, Any]) -> list[dict[str, Any]]:
    raw_beds = scene.get("beds")
    if not isinstance(raw_beds, list):
        return []
    rows: list[tuple[str, str, int, dict[str, Any]]] = []
    for index, row in enumerate(raw_beds):
        if not isinstance(row, dict):
            continue
        bed_id = _coerce_str(row.get("bed_id")).strip()
        label = _coerce_str(row.get("label")).strip()
        rows.append((bed_id, label, index, row))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in rows]


def _scene_intent_payload(scene: dict[str, Any]) -> dict[str, Any]:
    intent = scene.get("intent")
    if not isinstance(intent, dict):
        return {}
    return intent


def _scene_lock_ids(scene: dict[str, Any]) -> set[str]:
    scene_intent = _scene_intent_payload(scene)
    return {
        lock_id.strip()
        for lock_id in _string_list(scene_intent.get("locks"))
        if lock_id.strip()
    }


def _object_lock_ids(obj: dict[str, Any]) -> set[str]:
    intent = obj.get("intent")
    if not isinstance(intent, dict):
        return set()
    return {
        lock_id.strip()
        for lock_id in _string_list(intent.get("locks"))
        if lock_id.strip()
    }


def _bed_lock_ids(bed: dict[str, Any]) -> set[str]:
    intent = bed.get("intent")
    if not isinstance(intent, dict):
        return set()
    return {
        lock_id.strip()
        for lock_id in _string_list(intent.get("locks"))
        if lock_id.strip()
    }


def _scene_locks_receipt_index(scene: dict[str, Any]) -> dict[str, dict[str, str]]:
    metadata = scene.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    locks_receipt = metadata.get("locks_receipt")
    if not isinstance(locks_receipt, dict):
        return {}
    objects = locks_receipt.get("objects")
    if not isinstance(objects, list):
        return {}

    index: dict[str, dict[str, str]] = {}
    for row in objects:
        if not isinstance(row, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if not stem_id:
            continue
        index[stem_id] = {
            key: _coerce_str(row.get(key)).strip()
            for key in (
                "role_source",
                "bus_source",
                "azimuth_source",
                "width_source",
                "surround_send_caps_source",
                "depth_source",
                "height_send_caps_source",
            )
            if _coerce_str(row.get(key)).strip()
        }
    return index


def _scene_immersive_perspective(scene: dict[str, Any]) -> tuple[str, str] | None:
    scene_intent = _scene_intent_payload(scene)
    perspective = _coerce_str(scene_intent.get("perspective")).strip().lower()
    if perspective in _IMMERSIVE_PERSPECTIVES:
        return perspective, "scene.intent.perspective"

    for note in _string_list(scene_intent.get("notes")):
        normalized_note = note.strip().lower().replace("-", "_").replace(" ", "_")
        if "in_orchestra" in normalized_note:
            return "in_orchestra", "scene.intent.notes"
        if "in_band" in normalized_note:
            return "in_band", "scene.intent.notes"
    return None


def _group_bus_from_object(obj: dict[str, Any], role_id: str) -> str:
    group_bus = _coerce_str(obj.get("group_bus")).strip().upper()
    if group_bus:
        return group_bus
    if role_id.startswith("ROLE.DRUM."):
        return "BUS.DRUMS"
    if role_id.startswith("ROLE.BASS."):
        return "BUS.BASS"
    if role_id.startswith("ROLE.VOCAL.") or role_id.startswith("ROLE.DIALOGUE."):
        return "BUS.VOX"
    if role_id.startswith("ROLE.GTR.") or role_id.startswith("ROLE.KEYS."):
        return "BUS.MUSIC"
    if role_id.startswith("ROLE.FX.") or role_id.startswith("ROLE.SFX."):
        return "BUS.FX"
    return _BUS_UNKNOWN


def _round_gain(value: float) -> float:
    rounded = round(value, 4)
    if rounded == -0.0:
        return 0.0
    return rounded


def _empty_gains(channel_order: list[str]) -> dict[str, float]:
    return {speaker_id: 0.0 for speaker_id in channel_order}


def _set_front(gains: dict[str, float], front_gain: float) -> None:
    if _FRONT_LEFT in gains:
        gains[_FRONT_LEFT] = _round_gain(front_gain)
    if _FRONT_RIGHT in gains:
        gains[_FRONT_RIGHT] = _round_gain(front_gain)


def _set_center(gains: dict[str, float], center_gain: float) -> None:
    if _CENTER in gains:
        gains[_CENTER] = _round_gain(center_gain)


def _set_surround(
    gains: dict[str, float],
    *,
    side_gain: float,
    rear_gain: float,
) -> None:
    if _SIDE_LEFT in gains:
        gains[_SIDE_LEFT] = _round_gain(side_gain)
    if _SIDE_RIGHT in gains:
        gains[_SIDE_RIGHT] = _round_gain(side_gain)
    if _REAR_LEFT in gains:
        gains[_REAR_LEFT] = _round_gain(rear_gain)
    if _REAR_RIGHT in gains:
        gains[_REAR_RIGHT] = _round_gain(rear_gain)


def _set_wides(gains: dict[str, float], wide_gain: float) -> None:
    if _WIDE_LEFT in gains:
        gains[_WIDE_LEFT] = _round_gain(wide_gain)
    if _WIDE_RIGHT in gains:
        gains[_WIDE_RIGHT] = _round_gain(wide_gain)


def _set_heights(
    gains: dict[str, float],
    *,
    top_front_gain: float,
    top_rear_gain: float,
    top_center_gains: tuple[float, float] | None = None,
) -> None:
    if _TOP_FRONT_LEFT in gains:
        gains[_TOP_FRONT_LEFT] = _round_gain(top_front_gain)
    if _TOP_FRONT_RIGHT in gains:
        gains[_TOP_FRONT_RIGHT] = _round_gain(top_front_gain)
    if _TOP_REAR_LEFT in gains:
        gains[_TOP_REAR_LEFT] = _round_gain(top_rear_gain)
    if _TOP_REAR_RIGHT in gains:
        gains[_TOP_REAR_RIGHT] = _round_gain(top_rear_gain)
    if top_center_gains is None:
        return
    top_front_center, top_back_center = top_center_gains
    if _TOP_FRONT_CENTER in gains:
        gains[_TOP_FRONT_CENTER] = _round_gain(top_front_center)
    if _TOP_BACK_CENTER in gains:
        gains[_TOP_BACK_CENTER] = _round_gain(top_back_center)


def _nonzero_channels(gains: dict[str, float], channel_order: list[str]) -> list[str]:
    return [speaker_id for speaker_id in channel_order if gains.get(speaker_id, 0.0) > 0.0]


def _db_to_linear(db_value: float) -> float:
    return math.pow(10.0, db_value / 20.0)


def _bus_trim_db_for_class(policy_class: str) -> float:
    if policy_class.startswith("BED."):
        return -1.5
    return 0.0


def _is_anchor_role(role_id: str) -> bool:
    return (
        role_id.startswith("ROLE.DRUM.KICK")
        or role_id.startswith("ROLE.DRUM.SNARE")
        or role_id.startswith("ROLE.BASS.")
    )


def _is_lead_center_role(role_id: str) -> bool:
    return (
        role_id.startswith("ROLE.VOCAL.LEAD")
        or role_id.startswith("ROLE.DIALOGUE.LEAD")
    )


def _append_source_notes(
    notes: list[str],
    source_receipt_row: dict[str, str] | None,
) -> None:
    if not isinstance(source_receipt_row, dict):
        return
    for key in (
        "role_source",
        "bus_source",
        "azimuth_source",
        "width_source",
        "surround_send_caps_source",
        "depth_source",
        "height_send_caps_source",
    ):
        value = _coerce_str(source_receipt_row.get(key)).strip()
        if value:
            notes.append(f"{key}:{value}")


def _height_send_caps(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, float] = {}
    for key in ("top_max_gain", "top_front_max_gain", "top_rear_max_gain"):
        raw = _coerce_float(value.get(key))
        if raw is not None:
            normalized[key] = _clamp_unit(raw, default=1.0)
    return normalized or None


def _cap_height_gains(
    *,
    top_front_gain: float,
    top_rear_gain: float,
    top_center_gains: tuple[float, float] | None,
    height_send_caps: dict[str, float] | None,
) -> tuple[float, float, tuple[float, float] | None]:
    if not isinstance(height_send_caps, dict):
        return top_front_gain, top_rear_gain, top_center_gains

    top_max = _coerce_float(height_send_caps.get("top_max_gain"))
    top_front_max = _coerce_float(height_send_caps.get("top_front_max_gain"))
    top_rear_max = _coerce_float(height_send_caps.get("top_rear_max_gain"))

    front_caps = [
        cap for cap in (top_max, top_front_max)
        if isinstance(cap, (int, float))
    ]
    rear_caps = [
        cap for cap in (top_max, top_rear_max)
        if isinstance(cap, (int, float))
    ]
    front_cap = min(front_caps) if front_caps else None
    rear_cap = min(rear_caps) if rear_caps else None

    if front_cap is not None:
        top_front_gain = min(top_front_gain, front_cap)
    if rear_cap is not None:
        top_rear_gain = min(top_rear_gain, rear_cap)

    if top_center_gains is not None:
        top_front_center, top_back_center = top_center_gains
        if front_cap is not None:
            top_front_center = min(top_front_center, front_cap)
        if rear_cap is not None:
            top_back_center = min(top_back_center, rear_cap)
        top_center_gains = (top_front_center, top_back_center)

    return top_front_gain, top_rear_gain, top_center_gains


def _object_send(
    *,
    obj: dict[str, Any],
    channel_order: list[str],
    scene_locks: set[str],
    source_receipt_row: dict[str, str] | None = None,
    immersive_perspective: str | None = None,
) -> dict[str, Any]:
    stem_id = _coerce_str(obj.get("stem_id")).strip()
    role_id = _coerce_str(obj.get("role_id")).strip().upper() or _ROLE_UNKNOWN
    intent = obj.get("intent")
    intent_payload = intent if isinstance(intent, dict) else {}
    confidence = _clamp_unit(
        obj.get("confidence", intent_payload.get("confidence")),
        default=0.0,
    )
    width_hint = _clamp_unit(
        obj.get("width_hint", intent_payload.get("width")),
        default=0.5,
    )
    depth_hint = _clamp_unit(
        obj.get("depth_hint", intent_payload.get("depth")),
        default=0.5,
    )
    effective_locks = set(scene_locks) | _object_lock_ids(obj)
    group_bus = _group_bus_from_object(obj, role_id)

    front_gain = 0.74
    center_gain = 0.0
    policy_class = "OBJECT.FRONT_ONLY"
    notes = ["object_front_only_v1"]

    if _is_anchor_role(role_id):
        policy_class = "OBJECT.ANCHOR_FRONT_ONLY"
        front_gain = 0.86
    elif _is_lead_center_role(role_id):
        policy_class = "OBJECT.LEAD_FRONT_ONLY"
        front_gain = 0.58
        center_gain = 0.72

    if _LOCK_PRESERVE_CENTER_IMAGE in effective_locks and _CENTER in channel_order:
        if _is_lead_center_role(role_id):
            center_gain = max(center_gain, 0.86)
            front_gain = min(front_gain, 0.52)
            notes.append("center_anchor_strengthened_by_lock")

    if immersive_perspective:
        notes.append(f"immersive_perspective:{immersive_perspective}")

    _append_source_notes(notes, source_receipt_row)

    gains = _empty_gains(channel_order)
    _set_front(gains, front_gain)
    _set_center(gains, center_gain)

    return {
        "stem_id": stem_id,
        "role_id": role_id,
        "group_bus": group_bus,
        "policy_class": policy_class,
        "confidence": confidence,
        "width_hint": width_hint,
        "depth_hint": depth_hint,
        "locks": sorted(effective_locks),
        "bus_trim_db": _bus_trim_db_for_class(policy_class),
        "gains": {
            speaker_id: _round_gain(gains.get(speaker_id, 0.0))
            for speaker_id in channel_order
        },
        "nonzero_channels": _nonzero_channels(gains, channel_order),
        "notes": sorted(notes),
    }


def _bed_role_from_content_hint(content_hint: str) -> str:
    normalized = _coerce_str(content_hint).strip().lower()
    if normalized == "reverb_return":
        return "ROLE.FX.REVERB"
    if normalized == "ambience":
        return "ROLE.FX.AMBIENCE"
    if normalized == "pad_texture":
        return "ROLE.SYNTH.PAD"
    if normalized == "crowd":
        return "ROLE.FX.AMBIENCE"
    return _ROLE_UNKNOWN


def _bed_stem_ids(bed: dict[str, Any]) -> list[str]:
    stem_ids_raw = bed.get("stem_ids")
    if not isinstance(stem_ids_raw, list):
        return []
    stem_ids = sorted(
        {
            _coerce_str(stem_id).strip()
            for stem_id in stem_ids_raw
            if _coerce_str(stem_id).strip()
        }
    )
    return stem_ids


def _bed_send(
    *,
    bed: dict[str, Any],
    stem_id: str,
    channel_order: list[str],
    scene_locks: set[str],
    immersive_perspective: str | None = None,
) -> dict[str, Any]:
    bed_id = _coerce_str(bed.get("bed_id")).strip()
    bus_id = _coerce_str(bed.get("bus_id")).strip().upper() or _BUS_UNKNOWN
    content_hint = _coerce_str(bed.get("content_hint")).strip()
    intent = bed.get("intent")
    intent_payload = intent if isinstance(intent, dict) else {}
    confidence = _clamp_unit(
        bed.get("confidence", intent_payload.get("confidence")),
        default=0.0,
    )
    width_hint = _clamp_unit(
        bed.get("width_hint", intent_payload.get("diffuse")),
        default=0.75,
    )
    depth_hint = 0.7
    locks = set(scene_locks) | _bed_lock_ids(bed)
    role_id = _bed_role_from_content_hint(content_hint)
    height_send_caps = _height_send_caps(intent_payload.get("height_send_caps"))

    front_gain = 0.68
    side_gain = 0.0
    rear_gain = 0.0
    wide_gain = 0.0
    top_front_gain = 0.0
    top_rear_gain = 0.0
    top_center_gains: tuple[float, float] | None = None
    policy_class = "BED.FRONT_ONLY_LOW_CONFIDENCE"
    notes = [
        "bed_subtle_surround_policy_v1",
        f"bed_id:{bed_id or '<unknown>'}",
        f"bed_surround_relative_db:{_BED_SURROUND_RELATIVE_DB:.1f}",
    ]

    if _LOCK_NO_STEREO_WIDENING in locks:
        notes.append("surround_send_disabled_by_lock_no_stereo_widening")
    elif confidence < _BED_SURROUND_CONFIDENCE_MIN:
        notes.append("surround_send_disabled_low_confidence")
    else:
        policy_class = "BED.SUBTLE_SURROUND_V1"
        base = front_gain * _db_to_linear(_BED_SURROUND_RELATIVE_DB)
        spatial_scale = (0.75 + (0.25 * width_hint)) * (0.7 + (0.3 * confidence))
        side_gain = min(_BED_SURROUND_SEND_CAP, base * spatial_scale)
        rear_gain = min(_BED_SURROUND_SEND_CAP, side_gain * 0.85)
        wide_gain = min(_BED_SURROUND_SEND_CAP, side_gain * 0.75)
        top_front_gain = min(_BED_SURROUND_SEND_CAP, side_gain * 0.65)
        top_rear_gain = min(_BED_SURROUND_SEND_CAP, side_gain * 0.55)
        top_center_gains = (
            min(_BED_SURROUND_SEND_CAP, top_front_gain * 0.7),
            min(_BED_SURROUND_SEND_CAP, top_rear_gain * 0.7),
        )
        notes.append("surround_send_enabled")
        if top_front_gain > 0.0:
            notes.append("overhead_send_enabled")

    if _LOCK_NO_HEIGHT_SEND in locks:
        top_front_gain = 0.0
        top_rear_gain = 0.0
        if top_center_gains is not None:
            top_center_gains = (0.0, 0.0)
        notes.append("height_send_disabled_by_lock_no_height_send")
    elif height_send_caps is not None:
        top_front_gain, top_rear_gain, top_center_gains = _cap_height_gains(
            top_front_gain=top_front_gain,
            top_rear_gain=top_rear_gain,
            top_center_gains=top_center_gains,
            height_send_caps=height_send_caps,
        )
        notes.append("height_send_capped_by_intent")

    if immersive_perspective:
        notes.append(f"immersive_perspective:{immersive_perspective}")

    gains = _empty_gains(channel_order)
    _set_front(gains, front_gain)
    _set_surround(gains, side_gain=side_gain, rear_gain=rear_gain)
    _set_wides(gains, wide_gain)
    _set_heights(
        gains,
        top_front_gain=top_front_gain,
        top_rear_gain=top_rear_gain,
        top_center_gains=top_center_gains,
    )

    if content_hint:
        notes.append(f"content_hint:{content_hint}")

    return {
        "stem_id": stem_id,
        "role_id": role_id,
        "group_bus": bus_id,
        "policy_class": policy_class,
        "confidence": confidence,
        "width_hint": width_hint,
        "depth_hint": depth_hint,
        "locks": sorted(locks),
        "bus_trim_db": _bus_trim_db_for_class(policy_class),
        "gains": {
            speaker_id: _round_gain(gains.get(speaker_id, 0.0))
            for speaker_id in channel_order
        },
        "nonzero_channels": _nonzero_channels(gains, channel_order),
        "notes": sorted(notes),
    }


def _bus_gain_staging(
    *,
    channel_order: list[str],
    stem_sends: list[dict[str, Any]],
) -> dict[str, Any]:
    group_trims: dict[str, float] = {}
    for row in stem_sends:
        group_bus = _coerce_str(row.get("group_bus")).strip().upper()
        if not group_bus:
            continue
        trim = _coerce_float(row.get("bus_trim_db"))
        if trim is None:
            trim = 0.0
        if group_bus in group_trims:
            group_trims[group_bus] = min(group_trims[group_bus], trim)
        else:
            group_trims[group_bus] = trim

    has_surround = any(
        speaker_id in channel_order
        for speaker_id in (_SIDE_LEFT, _SIDE_RIGHT, _REAR_LEFT, _REAR_RIGHT)
    )
    master_gain_db = -1.0 if has_surround else 0.0

    return {
        "master_gain_db": _round_gain(master_gain_db),
        "group_trims_db": {
            group_bus: _round_gain(group_trims[group_bus])
            for group_bus in sorted(group_trims.keys())
        },
    }


def build_render_intent(
    scene: dict[str, Any],
    target_layout_id: str,
    *,
    layouts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build conservative scene->layout placement sends for renderer consumption."""
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    normalized_layout_id = _coerce_str(target_layout_id).strip().upper()
    if normalized_layout_id not in _SUPPORTED_LAYOUT_IDS:
        return None

    channel_order = _layout_channel_order(normalized_layout_id, layouts=layouts)
    if not channel_order:
        return None

    objects = _scene_objects(scene)
    beds = _scene_beds(scene)
    if not objects and not beds:
        return None

    scene_locks = _scene_lock_ids(scene)
    source_receipt_index = _scene_locks_receipt_index(scene)
    immersive_perspective_marker = _scene_immersive_perspective(scene)
    immersive_perspective = (
        immersive_perspective_marker[0]
        if isinstance(immersive_perspective_marker, tuple)
        else None
    )

    object_rows = [
        _object_send(
            obj=obj,
            channel_order=channel_order,
            scene_locks=scene_locks,
            source_receipt_row=source_receipt_index.get(
                _coerce_str(obj.get("stem_id")).strip()
            ),
            immersive_perspective=immersive_perspective,
        )
        for obj in objects
    ]

    bed_rows: list[dict[str, Any]] = []
    for bed in beds:
        for stem_id in _bed_stem_ids(bed):
            bed_rows.append(
                _bed_send(
                    bed=bed,
                    stem_id=stem_id,
                    channel_order=channel_order,
                    scene_locks=scene_locks,
                    immersive_perspective=immersive_perspective,
                )
            )

    combined_by_stem: dict[str, dict[str, Any]] = {}
    for row in object_rows:
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if stem_id:
            combined_by_stem[stem_id] = row
    for row in bed_rows:
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if not stem_id:
            continue
        existing = combined_by_stem.get(stem_id)
        if isinstance(existing, dict):
            existing_notes = existing.get("notes")
            if isinstance(existing_notes, list):
                existing_notes.append("bed_overrides_object_send")
        combined_by_stem[stem_id] = row

    stem_sends = [
        combined_by_stem[stem_id]
        for stem_id in sorted(combined_by_stem.keys())
    ]
    if not stem_sends:
        return None

    notes = [
        "Objects are front-only by default in conservative placement v1.",
        (
            "Bed stems may receive subtle deterministic surround/height sends "
            "at approximately -12 dB relative, capped for translation safety."
        ),
        "Bed surround sends are disabled when confidence is below threshold.",
        "LFE sends remain zero by default (manual/explicit only).",
    ]
    if isinstance(immersive_perspective_marker, tuple):
        perspective_value, source_label = immersive_perspective_marker
        notes.append(f"immersive_perspective:{perspective_value}")
        notes.append(f"immersive_perspective_source:{source_label}")

    return {
        "schema_version": PLACEMENT_POLICY_SCHEMA_VERSION,
        "policy_id": PLACEMENT_POLICY_ID,
        "target_layout_id": normalized_layout_id,
        "channel_order": list(channel_order),
        "bus_gain_staging": _bus_gain_staging(
            channel_order=channel_order,
            stem_sends=stem_sends,
        ),
        "stem_sends": stem_sends,
        "notes": notes,
    }
