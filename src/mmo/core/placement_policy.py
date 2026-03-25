from __future__ import annotations

import math
from typing import Any

from mmo.core.precedence import apply_precedence, has_precedence_receipt
from mmo.dsp.downmix import load_layouts
from mmo.resources import ontology_dir

PLACEMENT_POLICY_ID = "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1"
PLACEMENT_POLICY_SCHEMA_VERSION = "0.1.0"

_SUPPORTED_LAYOUT_IDS: frozenset[str] = frozenset(
    {
        "LAYOUT.2_0",
        "LAYOUT.32CH",
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
_BED_HEIGHT_SEND_CAP = 0.14
_BED_SURROUND_CONFIDENCE_MIN = 0.6
_IMMERSIVE_PERSPECTIVES: frozenset[str] = frozenset({"in_band", "in_orchestra"})
_HALL_ROOM_CONTENT_HINTS: frozenset[str] = frozenset(
    {"ambience", "reverb_return", "crowd"}
)
_MUSIC_ROLE_PREFIXES: tuple[str, ...] = (
    "ROLE.BRASS.",
    "ROLE.GTR.",
    "ROLE.KEYS.",
    "ROLE.MUSIC.",
    "ROLE.STRINGS.",
    "ROLE.SYNTH.",
    "ROLE.WINDS.",
    "ROLE.WW.",
)
_PERCUSSION_ROLE_PREFIXES: tuple[str, ...] = (
    "ROLE.DRUM.CYMBALS",
    "ROLE.DRUM.HAND_PERC",
    "ROLE.DRUM.LATIN_PERC",
    "ROLE.DRUM.MALLETS",
    "ROLE.DRUM.OVERHEADS",
    "ROLE.DRUM.PERCUSSION",
    "ROLE.DRUM.ROOM",
    "ROLE.DRUM.TIMPANI",
    "ROLE.DRUM.TOMS",
    "ROLE.DRUM.WORLD_PERC",
)

_AZIMUTH_CENTER_DEG = 12.0
_AZIMUTH_WIDE_MIN_DEG = 35.0
_AZIMUTH_WIDE_MAX_DEG = 70.0
_AZIMUTH_FRONT_EDGE_DEG = 75.0
_AZIMUTH_SIDE_EDGE_DEG = 125.0
_AZIMUTH_REAR_EDGE_DEG = 165.0
_GENERIC_FRONT_SAFE_POLICY_CLASS = "GENERIC.FRONT_SAFE_V1"


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


def _scene_precedence_note_index(scene: dict[str, Any]) -> dict[str, dict[str, str]]:
    metadata = scene.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    precedence_receipt = metadata.get("precedence_receipt")
    if isinstance(precedence_receipt, dict):
        entries = precedence_receipt.get("entries")
        if isinstance(entries, list):
            index: dict[str, dict[str, str]] = {}
            field_to_note_key = {
                "role_id": "role_source",
                "bus_id": "bus_source",
                "azimuth_deg": "azimuth_source",
                "width": "width_source",
                "surround_send_caps": "surround_send_caps_source",
                "depth": "depth_source",
                "height_send_caps": "height_send_caps_source",
            }
            for row in entries:
                if not isinstance(row, dict):
                    continue
                if _coerce_str(row.get("scope")).strip() != "object":
                    continue
                stem_id = _coerce_str(row.get("stem_id")).strip()
                field = _coerce_str(row.get("field")).strip()
                source = _coerce_str(row.get("source")).strip()
                if source == "explicit_metadata":
                    source = "explicit"
                note_key = field_to_note_key.get(field)
                if not stem_id or not note_key or not source:
                    continue
                index.setdefault(stem_id, {})[note_key] = source
    return index


def _scene_precedence_source(scene: dict[str, Any], *, field: str) -> str | None:
    metadata = scene.get("metadata")
    if not isinstance(metadata, dict):
        return None
    precedence_receipt = metadata.get("precedence_receipt")
    if not isinstance(precedence_receipt, dict):
        return None
    entries = precedence_receipt.get("entries")
    if not isinstance(entries, list):
        return None
    for row in entries:
        if not isinstance(row, dict):
            continue
        if _coerce_str(row.get("scope")).strip() != "scene":
            continue
        if _coerce_str(row.get("field")).strip() != field:
            continue
        source = _coerce_str(row.get("source")).strip()
        if source:
            return source
    return None


def _scene_immersive_perspective(scene: dict[str, Any]) -> tuple[str, str] | None:
    scene_intent = _scene_intent_payload(scene)
    perspective = _coerce_str(scene_intent.get("perspective")).strip().lower()
    if perspective in _IMMERSIVE_PERSPECTIVES:
        return perspective, _scene_precedence_source(scene, field="perspective") or "scene.intent.perspective"

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
    if role_id.startswith(("ROLE.VOCAL.", "ROLE.DIALOGUE.", "ROLE.VOX.")):
        return "BUS.VOX"
    if role_id.startswith(_MUSIC_ROLE_PREFIXES):
        return "BUS.MUSIC"
    if role_id.startswith("ROLE.FX.") or role_id.startswith("ROLE.SFX."):
        return "BUS.FX"
    return _BUS_UNKNOWN


def _round_gain(value: float) -> float:
    rounded = round(value, 4)
    if rounded == -0.0:
        return 0.0
    return rounded


def _clamp_gain(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _empty_gains(channel_order: list[str]) -> dict[str, float]:
    return {speaker_id: 0.0 for speaker_id in channel_order}


def _add_gain(gains: dict[str, float], speaker_id: str, gain: float) -> None:
    if speaker_id not in gains:
        return
    gains[speaker_id] = _clamp_gain(gains.get(speaker_id, 0.0) + gain)


def _add_pair_with_pan(
    gains: dict[str, float],
    *,
    left_speaker: str,
    right_speaker: str,
    base_gain: float,
    pan: float,
) -> None:
    pan_clamped = max(-1.0, min(1.0, pan))
    left_gain = _clamp_gain(base_gain * (1.0 + (0.5 * pan_clamped)))
    right_gain = _clamp_gain(base_gain * (1.0 - (0.5 * pan_clamped)))
    _add_gain(gains, left_speaker, left_gain)
    _add_gain(gains, right_speaker, right_gain)


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


def _needs_generic_front_safe_fallback(channel_order: list[str]) -> bool:
    return _FRONT_LEFT not in channel_order or _FRONT_RIGHT not in channel_order


def _generic_front_safe_gains(channel_order: list[str]) -> dict[str, float]:
    gains = _empty_gains(channel_order)
    if not channel_order:
        return gains
    if len(channel_order) == 1:
        gains[channel_order[0]] = 1.0
        return gains
    gains[channel_order[0]] = 0.5
    gains[channel_order[1]] = 0.5
    return gains


def _generic_front_safe_send(
    *,
    stem_id: str,
    role_id: str,
    group_bus: str,
    confidence: float,
    width_hint: float,
    depth_hint: float,
    locks: set[str],
    channel_order: list[str],
    extra_notes: list[str] | None = None,
    source_receipt_row: dict[str, str] | None = None,
) -> dict[str, Any]:
    gains = _generic_front_safe_gains(channel_order)
    notes = [
        "generic_front_safe_layout_fallback",
        "semantic_front_channels_unavailable",
    ]
    nonzero = _nonzero_channels(gains, channel_order)
    if nonzero:
        if len(nonzero) == 1:
            notes.append(f"front_safe_channel:{nonzero[0]}")
        else:
            notes.append(f"front_safe_pair:{nonzero[0]},{nonzero[1]}")
    if isinstance(extra_notes, list):
        notes.extend(note for note in extra_notes if isinstance(note, str) and note.strip())
    _append_source_notes(notes, source_receipt_row)
    return {
        "stem_id": stem_id,
        "role_id": role_id,
        "group_bus": group_bus,
        "policy_class": _GENERIC_FRONT_SAFE_POLICY_CLASS,
        "confidence": confidence,
        "width_hint": width_hint,
        "depth_hint": depth_hint,
        "locks": sorted(locks),
        "bus_trim_db": _bus_trim_db_for_class(_GENERIC_FRONT_SAFE_POLICY_CLASS),
        "gains": {
            speaker_id: _round_gain(gains.get(speaker_id, 0.0))
            for speaker_id in channel_order
        },
        "nonzero_channels": nonzero,
        "notes": sorted(notes),
    }


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


def _is_backing_vocal_role(role_id: str) -> bool:
    return role_id.startswith(
        (
            "ROLE.VOCAL.BGV",
            "ROLE.VOCAL.HARMONY",
            "ROLE.VOCAL.DOUBLE",
            "ROLE.VOCAL.AD_LIB",
            "ROLE.VOCAL.CHOPS",
            "ROLE.VOX.BGV",
        )
    )


def _is_strings_role(role_id: str) -> bool:
    return role_id.startswith("ROLE.STRINGS.")


def _is_winds_role(role_id: str) -> bool:
    return role_id.startswith("ROLE.WW.") or role_id.startswith("ROLE.WINDS.")


def _is_brass_role(role_id: str) -> bool:
    return role_id.startswith("ROLE.BRASS.")


def _is_percussion_role(role_id: str) -> bool:
    return role_id.startswith(_PERCUSSION_ROLE_PREFIXES)


def _is_broad_strings_role(role_id: str, *, width_hint: float) -> bool:
    if not _is_strings_role(role_id):
        return False
    return width_hint >= 0.5 or role_id.startswith("ROLE.STRINGS.SECTION")


def _role_slot_group_key(role_id: str, group_bus: str) -> str:
    if _is_lead_center_role(role_id):
        return "SECTION.VOCAL.LEAD"
    if _is_backing_vocal_role(role_id):
        return "SECTION.VOCAL.BACKING"
    if role_id.startswith(("ROLE.BASS.", "ROLE.STRINGS.BASS")):
        return "SECTION.BASS"
    if role_id.startswith("ROLE.DRUM."):
        if _is_percussion_role(role_id):
            return "SECTION.DRUMS.PERCUSSION"
        return "SECTION.DRUMS.KIT"
    if _is_strings_role(role_id):
        if role_id.startswith("ROLE.STRINGS.VIOLIN"):
            return "SECTION.STRINGS.VIOLIN"
        if role_id.startswith("ROLE.STRINGS.VIOLA"):
            return "SECTION.STRINGS.VIOLA"
        if role_id.startswith("ROLE.STRINGS.CELLO"):
            return "SECTION.STRINGS.CELLO"
        return "SECTION.STRINGS.OTHER"
    if _is_winds_role(role_id):
        return "SECTION.WINDS"
    if _is_brass_role(role_id):
        return "SECTION.BRASS"
    if role_id.startswith("ROLE.GTR."):
        return "SECTION.GTR"
    if role_id.startswith("ROLE.KEYS."):
        return "SECTION.KEYS"
    if role_id.startswith("ROLE.SYNTH."):
        return "SECTION.SYNTH"
    if group_bus:
        return f"SECTION.{group_bus}"
    return f"SECTION.{role_id or _ROLE_UNKNOWN}"


def _role_default_azimuth(
    role_id: str,
    *,
    perspective: str | None,
) -> float:
    if _is_lead_center_role(role_id):
        return 0.0
    if _is_backing_vocal_role(role_id):
        return 0.0

    if role_id.startswith("ROLE.STRINGS.VIOLIN"):
        return 45.0
    if role_id.startswith("ROLE.STRINGS.VIOLA"):
        return 20.0
    if role_id.startswith("ROLE.STRINGS.CELLO"):
        return -20.0
    if role_id.startswith(("ROLE.STRINGS.BASS", "ROLE.BASS.")):
        return -52.0
    if role_id.startswith("ROLE.STRINGS.HARP"):
        return 56.0
    if role_id.startswith("ROLE.STRINGS.BOWED"):
        return 30.0
    if role_id.startswith("ROLE.STRINGS.PLUCKED"):
        return 18.0
    if role_id.startswith("ROLE.STRINGS.STRUCK"):
        return 14.0
    if role_id.startswith("ROLE.STRINGS."):
        return 34.0

    if _is_winds_role(role_id):
        if role_id.startswith("ROLE.WINDS.BAGPIPE"):
            return 14.0
        if role_id.startswith("ROLE.WINDS.DIDGERIDOO"):
            return -12.0
        if role_id.startswith("ROLE.WINDS.DUDUK"):
            return -8.0
        if role_id.startswith("ROLE.WINDS.PAN_FLUTE"):
            return 10.0
        if role_id.startswith("ROLE.WINDS.OCARINA"):
            return 6.0
        if role_id.startswith("ROLE.WINDS.RECORDER"):
            return 8.0
        if role_id.startswith("ROLE.WINDS.SHAKUHACHI"):
            return 8.0
        if role_id.startswith("ROLE.WINDS.WHISTLE"):
            return 12.0
        if role_id.startswith("ROLE.WW.BASSOON"):
            return -10.0
        if role_id.startswith("ROLE.WW.BASS_CLARINET"):
            return -6.0
        if role_id.startswith("ROLE.WW.CONTRABASSOON"):
            return -16.0
        if role_id.startswith("ROLE.WW.ENGLISH_HORN"):
            return 2.0
        if role_id.startswith("ROLE.WW.OBOE"):
            return 6.0
        if role_id.startswith("ROLE.WW.PICCOLO"):
            return 12.0
        return 0.0

    if _is_brass_role(role_id):
        if role_id.startswith("ROLE.BRASS.TUBA"):
            if perspective == "in_orchestra":
                return -168.0
            return -140.0
        if role_id.startswith("ROLE.BRASS.EUPHONIUM"):
            if perspective == "in_orchestra":
                return -172.0
            return -146.0
        if role_id.startswith(("ROLE.BRASS.CORNET", "ROLE.BRASS.FLUGELHORN")):
            if perspective == "in_orchestra":
                return 170.0
            return 142.0
        if perspective == "in_orchestra":
            return 176.0
        return 150.0

    if _is_percussion_role(role_id):
        if role_id.startswith("ROLE.DRUM.TIMPANI"):
            if perspective == "in_orchestra":
                return 176.0
            return 150.0
        if role_id.startswith("ROLE.DRUM.MALLETS"):
            if perspective == "in_orchestra":
                return 164.0
            return 142.0
        if perspective == "in_orchestra":
            return 170.0
        return 138.0

    if role_id.startswith("ROLE.DRUM."):
        return 0.0
    if role_id.startswith("ROLE.GTR.") and role_id.endswith("_L"):
        return 42.0
    if role_id.startswith("ROLE.GTR.") and role_id.endswith("_R"):
        return -42.0
    if role_id.startswith("ROLE.GTR.STEEL"):
        return 34.0
    if role_id.startswith(("ROLE.GTR.BANJO", "ROLE.GTR.MANDOLIN", "ROLE.GTR.WORLD_PLUCKED")):
        return 24.0
    if role_id.startswith("ROLE.GTR.UKULELE"):
        return 20.0
    if role_id.startswith("ROLE.GTR."):
        return 28.0
    if role_id.startswith("ROLE.KEYS.ORGAN"):
        return -10.0
    if role_id.startswith(("ROLE.KEYS.ACCORDION", "ROLE.KEYS.REED_ORGAN")):
        return -4.0
    if role_id.startswith("ROLE.KEYS.CELESTA"):
        return 10.0
    if role_id.startswith("ROLE.KEYS.HARPSICHORD"):
        return -18.0
    if role_id.startswith("ROLE.KEYS."):
        return -26.0
    if role_id.startswith("ROLE.SYNTH."):
        return 18.0
    return 0.0


def _object_azimuth_hint(
    obj: dict[str, Any],
    *,
    intent_payload: dict[str, Any],
) -> tuple[float | None, str | None]:
    direct_hint = _coerce_float(obj.get("azimuth_hint"))
    if direct_hint is not None:
        return max(-180.0, min(180.0, direct_hint)), "object.azimuth_hint"

    position = intent_payload.get("position")
    if isinstance(position, dict):
        intent_azimuth = _coerce_float(position.get("azimuth_deg"))
        if intent_azimuth is not None:
            return max(-180.0, min(180.0, intent_azimuth)), "intent.position.azimuth_deg"

    intent_hint = _coerce_float(intent_payload.get("azimuth_hint"))
    if intent_hint is not None:
        return max(-180.0, min(180.0, intent_hint)), "intent.azimuth_hint"
    return None, None


def _section_spread_span_deg(role_id: str, *, width_hint: float, slot_count: int) -> float:
    if slot_count <= 1:
        return 0.0

    if _is_lead_center_role(role_id):
        base_span = 16.0
    elif _is_backing_vocal_role(role_id):
        base_span = 58.0
    elif _is_strings_role(role_id):
        base_span = 46.0
    elif _is_winds_role(role_id) or _is_brass_role(role_id):
        base_span = 32.0
    elif role_id.startswith(("ROLE.GTR.", "ROLE.KEYS.", "ROLE.SYNTH.")):
        base_span = 34.0
    else:
        base_span = 24.0

    width_influence = 26.0 * width_hint
    density_influence = 6.0 * max(0, slot_count - 2)
    return min(120.0, base_span + width_influence + density_influence)


def _spread_azimuth_for_section(
    azimuth_deg: float,
    *,
    role_id: str,
    width_hint: float,
    slot_index: int,
    slot_count: int,
) -> float:
    if slot_count <= 1:
        return azimuth_deg

    span = _section_spread_span_deg(role_id, width_hint=width_hint, slot_count=slot_count)
    if span <= 0.0:
        return azimuth_deg
    step = span / float(max(1, slot_count - 1))
    offset = (-span * 0.5) + (step * slot_index)
    return max(-179.0, min(179.0, azimuth_deg + offset))


def _azimuth_region(azimuth_deg: float | None, *, has_wides: bool) -> str:
    if azimuth_deg is None:
        return "front"
    absolute = abs(float(azimuth_deg))
    if absolute <= _AZIMUTH_CENTER_DEG:
        return "center"
    if has_wides and _AZIMUTH_WIDE_MIN_DEG <= absolute <= _AZIMUTH_WIDE_MAX_DEG:
        return "wide"
    if absolute <= _AZIMUTH_FRONT_EDGE_DEG:
        return "front"
    if absolute <= _AZIMUTH_SIDE_EDGE_DEG:
        return "side"
    if absolute <= _AZIMUTH_REAR_EDGE_DEG:
        return "rear"
    return "rear_center"


def _pair_pan(azimuth_deg: float | None, *, edge_deg: float) -> float:
    if azimuth_deg is None or edge_deg <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, float(azimuth_deg) / edge_deg))


def _region_pair_speakers(
    gains: dict[str, float],
    *,
    region: str,
) -> tuple[str, str]:
    if region == "wide":
        if _WIDE_LEFT in gains and _WIDE_RIGHT in gains:
            return _WIDE_LEFT, _WIDE_RIGHT
        if _SIDE_LEFT in gains and _SIDE_RIGHT in gains:
            return _SIDE_LEFT, _SIDE_RIGHT
        return _FRONT_LEFT, _FRONT_RIGHT
    if region == "side":
        if _SIDE_LEFT in gains and _SIDE_RIGHT in gains:
            return _SIDE_LEFT, _SIDE_RIGHT
        if _REAR_LEFT in gains and _REAR_RIGHT in gains:
            return _REAR_LEFT, _REAR_RIGHT
        return _FRONT_LEFT, _FRONT_RIGHT
    if region == "rear":
        if _REAR_LEFT in gains and _REAR_RIGHT in gains:
            return _REAR_LEFT, _REAR_RIGHT
        if _SIDE_LEFT in gains and _SIDE_RIGHT in gains:
            return _SIDE_LEFT, _SIDE_RIGHT
        return _FRONT_LEFT, _FRONT_RIGHT
    return _FRONT_LEFT, _FRONT_RIGHT


def _bed_is_hall_room(
    *,
    bed: dict[str, Any],
    content_hint: str,
) -> bool:
    if content_hint.strip().lower() in _HALL_ROOM_CONTENT_HINTS:
        return True

    label = _coerce_str(bed.get("label")).strip().lower()
    if any(token in label for token in ("hall", "room", "ambience", "reverb", "audience", "crowd")):
        return True

    for note in _string_list(bed.get("notes")):
        normalized = note.strip().lower()
        if any(token in normalized for token in ("hall", "room", "ambience", "reverb", "audience", "crowd")):
            return True
    return False


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
    role_slot_group: str = "",
    role_slot_index: int = 0,
    role_slot_count: int = 1,
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
    policy_class = "OBJECT.AZIMUTH_STAGE_V1"
    notes = ["object_stage_azimuth_policy_v2"]

    if _is_anchor_role(role_id):
        policy_class = "OBJECT.ANCHOR_STAGE_V1"
        front_gain = 0.86
    elif _is_lead_center_role(role_id):
        policy_class = "OBJECT.LEAD_STAGE_V1"
        front_gain = 0.58
        center_gain = 0.72

    if _LOCK_PRESERVE_CENTER_IMAGE in effective_locks and _CENTER in channel_order:
        if _is_lead_center_role(role_id):
            center_gain = max(center_gain, 0.86)
            front_gain = min(front_gain, 0.52)
            notes.append("center_anchor_strengthened_by_lock")

    azimuth_hint, azimuth_source = _object_azimuth_hint(
        obj,
        intent_payload=intent_payload,
    )
    if azimuth_hint is None:
        azimuth_hint = _role_default_azimuth(
            role_id,
            perspective=immersive_perspective,
        )
        azimuth_source = "role_stage_default"

    azimuth_hint = _spread_azimuth_for_section(
        float(azimuth_hint),
        role_id=role_id,
        width_hint=width_hint,
        slot_index=max(0, role_slot_index),
        slot_count=max(1, role_slot_count),
    )

    has_wides = _WIDE_LEFT in channel_order and _WIDE_RIGHT in channel_order
    region = _azimuth_region(azimuth_hint, has_wides=has_wides)
    immersive_enabled = immersive_perspective in _IMMERSIVE_PERSPECTIVES

    front_pair_base = front_gain
    side_pair_base = 0.0
    rear_pair_base = 0.0
    wide_pair_base = 0.0

    if region == "center":
        front_pair_base *= 0.78
        if _CENTER in channel_order:
            center_gain = max(center_gain, front_gain * 0.5)
    elif region == "wide":
        front_pair_base *= 0.78
        wide_pair_base = front_gain * 0.38

    if immersive_enabled:
        if region == "side":
            front_pair_base *= 0.62
            side_pair_base = front_gain * (0.56 if immersive_perspective == "in_orchestra" else 0.42)
            rear_pair_base = front_gain * (0.2 if immersive_perspective == "in_orchestra" else 0.1)
        elif region == "rear":
            front_pair_base *= 0.48 if immersive_perspective == "in_orchestra" else 0.66
            side_pair_base = front_gain * (0.26 if immersive_perspective == "in_orchestra" else 0.18)
            rear_pair_base = front_gain * (0.62 if immersive_perspective == "in_orchestra" else 0.3)
        elif region == "rear_center":
            front_pair_base *= 0.42 if immersive_perspective == "in_orchestra" else 0.7
            side_pair_base = front_gain * (0.22 if immersive_perspective == "in_orchestra" else 0.14)
            rear_pair_base = front_gain * (0.64 if immersive_perspective == "in_orchestra" else 0.24)

    if has_wides and _is_broad_strings_role(role_id, width_hint=width_hint):
        if region in {"front", "wide"}:
            wide_pair_base = max(
                wide_pair_base,
                front_gain * (0.32 if immersive_enabled else 0.24),
            )
            front_pair_base *= 0.88
            notes.append("strings_section_wide_support")

    if (_is_brass_role(role_id) or _is_percussion_role(role_id)) and immersive_perspective != "in_orchestra":
        if rear_pair_base > 0.0 or side_pair_base > 0.0:
            notes.append("rear_bias_softened_for_translation")
        rear_pair_base = 0.0
        if side_pair_base > 0.0:
            side_pair_base *= 0.35 if immersive_perspective == "in_band" else 0.0
        front_pair_base = max(front_pair_base, front_gain * 0.82)

    if immersive_perspective:
        notes.append(f"immersive_perspective:{immersive_perspective}")
    notes.append(f"azimuth_source:{azimuth_source or 'none'}")
    notes.append(f"azimuth_deg:{round(float(azimuth_hint), 3):.3f}")
    notes.append(f"azimuth_region:{region}")
    if role_slot_count > 1:
        notes.append(f"section_slot:{role_slot_index + 1}/{role_slot_count}")
    if role_slot_group:
        notes.append(f"section_group:{role_slot_group}")

    _append_source_notes(notes, source_receipt_row)

    gains = _empty_gains(channel_order)
    front_pan = _pair_pan(azimuth_hint, edge_deg=_AZIMUTH_FRONT_EDGE_DEG)
    side_pan = _pair_pan(azimuth_hint, edge_deg=_AZIMUTH_SIDE_EDGE_DEG)
    rear_pan = _pair_pan(azimuth_hint, edge_deg=180.0)
    wide_pan = _pair_pan(azimuth_hint, edge_deg=_AZIMUTH_WIDE_MAX_DEG)
    if region == "rear_center":
        rear_pan = 0.0

    front_left, front_right = _region_pair_speakers(gains, region="front")
    side_left, side_right = _region_pair_speakers(gains, region="side")
    rear_left, rear_right = _region_pair_speakers(gains, region="rear")
    wide_left, wide_right = _region_pair_speakers(gains, region="wide")

    _add_pair_with_pan(
        gains,
        left_speaker=front_left,
        right_speaker=front_right,
        base_gain=front_pair_base,
        pan=front_pan,
    )
    if side_pair_base > 0.0:
        _add_pair_with_pan(
            gains,
            left_speaker=side_left,
            right_speaker=side_right,
            base_gain=side_pair_base,
            pan=side_pan,
        )
    if rear_pair_base > 0.0:
        _add_pair_with_pan(
            gains,
            left_speaker=rear_left,
            right_speaker=rear_right,
            base_gain=rear_pair_base,
            pan=rear_pan,
        )
    if wide_pair_base > 0.0:
        _add_pair_with_pan(
            gains,
            left_speaker=wide_left,
            right_speaker=wide_right,
            base_gain=wide_pair_base,
            pan=wide_pan,
        )

    if _CENTER in gains:
        gains[_CENTER] = _clamp_gain(gains.get(_CENTER, 0.0) + center_gain)
    elif center_gain > 0.0:
        _add_pair_with_pan(
            gains,
            left_speaker=front_left,
            right_speaker=front_right,
            base_gain=center_gain * 0.35,
            pan=0.0,
        )

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
    height_eligible = _bed_is_hall_room(
        bed=bed,
        content_hint=content_hint,
    )

    front_gain = 0.68
    side_gain = 0.0
    rear_gain = 0.0
    wide_gain = 0.0
    top_front_gain = 0.0
    top_rear_gain = 0.0
    top_center_gains: tuple[float, float] | None = None
    policy_class = "BED.FRONT_ONLY_LOW_CONFIDENCE"
    notes = [
        "source_kind:bed",
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
        notes.append("surround_send_enabled")
        if height_eligible:
            top_front_gain = min(_BED_HEIGHT_SEND_CAP, side_gain * 0.65)
            top_rear_gain = min(_BED_HEIGHT_SEND_CAP, side_gain * 0.55)
            top_center_gains = (
                min(_BED_HEIGHT_SEND_CAP, top_front_gain * 0.7),
                min(_BED_HEIGHT_SEND_CAP, top_rear_gain * 0.7),
            )
            notes.append("overhead_send_enabled")
        else:
            notes.append("overhead_send_disabled_non_hall_room_bed")

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
    if not has_precedence_receipt(scene):
        scene = apply_precedence(scene, None, None)

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
    source_receipt_index = _scene_precedence_note_index(scene)
    immersive_perspective_marker = _scene_immersive_perspective(scene)
    immersive_perspective = (
        immersive_perspective_marker[0]
        if isinstance(immersive_perspective_marker, tuple)
        else None
    )
    generic_front_safe_layout = _needs_generic_front_safe_fallback(channel_order)

    group_counts: dict[str, int] = {}
    object_group_keys: list[str] = []
    for obj in objects:
        role_id = _coerce_str(obj.get("role_id")).strip().upper() or _ROLE_UNKNOWN
        group_bus = _group_bus_from_object(obj, role_id)
        group_key = _role_slot_group_key(role_id, group_bus)
        object_group_keys.append(group_key)
        group_counts[group_key] = group_counts.get(group_key, 0) + 1

    group_offsets: dict[str, int] = {}
    object_rows: list[dict[str, Any]] = []
    for obj, group_key in zip(objects, object_group_keys):
        slot_index = group_offsets.get(group_key, 0)
        group_offsets[group_key] = slot_index + 1
        if generic_front_safe_layout:
            role_id = _coerce_str(obj.get("role_id")).strip().upper() or _ROLE_UNKNOWN
            intent_payload = obj.get("intent")
            intent_payload = intent_payload if isinstance(intent_payload, dict) else {}
            object_rows.append(
                _generic_front_safe_send(
                    stem_id=_coerce_str(obj.get("stem_id")).strip(),
                    role_id=role_id,
                    group_bus=_group_bus_from_object(obj, role_id),
                    confidence=_clamp_unit(
                        obj.get("confidence", intent_payload.get("confidence")),
                        default=0.0,
                    ),
                    width_hint=_clamp_unit(
                        obj.get("width_hint", intent_payload.get("width")),
                        default=0.5,
                    ),
                    depth_hint=_clamp_unit(
                        obj.get("depth_hint", intent_payload.get("depth")),
                        default=0.5,
                    ),
                    locks=scene_locks | _object_lock_ids(obj),
                    channel_order=channel_order,
                    extra_notes=["source_kind:object"],
                    source_receipt_row=source_receipt_index.get(
                        _coerce_str(obj.get("stem_id")).strip()
                    ),
                )
            )
            continue
        object_rows.append(
            _object_send(
                obj=obj,
                channel_order=channel_order,
                scene_locks=scene_locks,
                source_receipt_row=source_receipt_index.get(
                    _coerce_str(obj.get("stem_id")).strip()
                ),
                immersive_perspective=immersive_perspective,
                role_slot_group=group_key,
                role_slot_index=slot_index,
                role_slot_count=group_counts.get(group_key, 1),
            )
        )

    bed_rows: list[dict[str, Any]] = []
    for bed in beds:
        for stem_id in _bed_stem_ids(bed):
            if generic_front_safe_layout:
                intent_payload = bed.get("intent")
                intent_payload = intent_payload if isinstance(intent_payload, dict) else {}
                content_hint = _coerce_str(bed.get("content_hint")).strip()
                bed_id = _coerce_str(bed.get("bed_id")).strip()
                bus_id = _coerce_str(bed.get("bus_id")).strip().upper() or _BUS_UNKNOWN
                notes: list[str] = ["source_kind:bed"]
                if bed_id:
                    notes.append(f"bed_id:{bed_id}")
                if content_hint:
                    notes.append(f"content_hint:{content_hint}")
                bed_rows.append(
                    _generic_front_safe_send(
                        stem_id=stem_id,
                        role_id=_bed_role_from_content_hint(content_hint),
                        group_bus=bus_id,
                        confidence=_clamp_unit(
                            bed.get("confidence", intent_payload.get("confidence")),
                            default=0.0,
                        ),
                        width_hint=_clamp_unit(
                            bed.get("width_hint", intent_payload.get("diffuse")),
                            default=0.75,
                        ),
                        depth_hint=0.7,
                        locks=scene_locks | _bed_lock_ids(bed),
                        channel_order=channel_order,
                        extra_notes=notes,
                    )
                )
                continue
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
        "Objects use deterministic stage seating from azimuth hints and role defaults.",
        (
            "Immersive perspectives (in_band/in_orchestra) may route objects to side/rear/wide "
            "pairs while keeping anchor roles translation-safe."
        ),
        (
            "Bed stems may receive subtle deterministic surround/height sends "
            "at approximately -12 dB relative, with hall/room-only overhead routing and caps."
        ),
        "Bed surround sends are disabled when confidence is below threshold.",
        "LFE sends remain zero by default (manual/explicit only).",
    ]
    if isinstance(immersive_perspective_marker, tuple):
        perspective_value, source_label = immersive_perspective_marker
        notes.append(f"immersive_perspective:{perspective_value}")
        notes.append(f"immersive_perspective_source:{source_label}")
    if generic_front_safe_layout:
        notes.append(
            "Layouts without semantic SPK.L/SPK.R channels fall back to a deterministic front-safe pair."
        )

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
