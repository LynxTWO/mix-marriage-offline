from __future__ import annotations

from typing import Any

from mmo.dsp.downmix import load_layouts
from mmo.resources import ontology_dir

PLACEMENT_POLICY_ID = "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1"
PLACEMENT_POLICY_SCHEMA_VERSION = "0.1.0"

_SUPPORTED_LAYOUT_IDS: frozenset[str] = frozenset({
    "LAYOUT.2_0",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
})

_FRONT_LEFT = "SPK.L"
_FRONT_RIGHT = "SPK.R"
_CENTER = "SPK.C"
_SIDE_LEFT = "SPK.LS"
_SIDE_RIGHT = "SPK.RS"
_REAR_LEFT = "SPK.LRS"
_REAR_RIGHT = "SPK.RRS"

_LOCK_NO_STEREO_WIDENING = "LOCK.NO_STEREO_WIDENING"
_LOCK_PRESERVE_CENTER_IMAGE = "LOCK.PRESERVE_CENTER_IMAGE"
_LOCK_PRESERVE_TRANSIENTS = "LOCK.PRESERVE_TRANSIENTS"

_BUS_OTHER = "BUS.OTHER"
_ROLE_UNKNOWN = "ROLE.OTHER.UNKNOWN"

_AMBIENT_TOKENS: frozenset[str] = frozenset({
    "AMBIENCE",
    "AMBIENT",
    "ATMOS",
    "AUDIENCE",
    "CROWD",
    "LONG",
    "PAD",
    "PADS",
    "REVERB",
    "ROOM",
    "SFX",
    "TEXTURE",
    "WASH",
})
_PERCUSSION_TOKENS: frozenset[str] = frozenset({
    "CYMBAL",
    "CYMBALS",
    "HAT",
    "HIHAT",
    "PERC",
    "PERCUSSION",
})
_IMMERSIVE_INTENT_MARKERS: frozenset[str] = frozenset({
    "YOU_ARE_THERE",
    "IN_THE_MIDDLE",
    "MIDDLE_OF_BAND",
    "MIDDLE_OF_ORCHESTRA",
    "IMMERSIVE_ANCHOR_WRAP",
})


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


def _scene_lock_ids(scene: dict[str, Any]) -> set[str]:
    scene_intent = _scene_intent_payload(scene)
    return {
        lock_id.strip()
        for lock_id in _string_list(scene_intent.get("locks"))
        if lock_id.strip()
    }


def _scene_intent_payload(scene: dict[str, Any]) -> dict[str, Any]:
    intent = scene.get("intent")
    if not isinstance(intent, dict):
        return {}
    return intent


def _object_lock_ids(obj: dict[str, Any]) -> set[str]:
    intent = obj.get("intent")
    if not isinstance(intent, dict):
        return set()
    return {
        lock_id.strip()
        for lock_id in _string_list(intent.get("locks"))
        if lock_id.strip()
    }


def _tokenize_text(value: str) -> set[str]:
    normalized = _coerce_str(value).strip().upper()
    if not normalized:
        return set()
    token = []
    tokens: set[str] = set()
    for ch in normalized:
        if ch.isalnum():
            token.append(ch)
            continue
        if token:
            tokens.add("".join(token))
            token.clear()
    if token:
        tokens.add("".join(token))
    return tokens


def _normalize_marker_text(value: str) -> str:
    normalized = _coerce_str(value).strip().upper()
    if not normalized:
        return ""
    chars: list[str] = []
    previous_was_separator = False
    for ch in normalized:
        if ch.isalnum():
            chars.append(ch)
            previous_was_separator = False
            continue
        if not previous_was_separator:
            chars.append("_")
            previous_was_separator = True
    return "".join(chars).strip("_")


def _has_immersive_intent_marker(candidates: list[str]) -> bool:
    for candidate in candidates:
        normalized = _normalize_marker_text(candidate)
        if not normalized:
            continue
        for marker in _IMMERSIVE_INTENT_MARKERS:
            if marker in normalized:
                return True
    return False


def _role_tokens(obj: dict[str, Any]) -> set[str]:
    role_id = _coerce_str(obj.get("role_id")).strip().upper()
    label = _coerce_str(obj.get("label")).strip()
    group_bus = _coerce_str(obj.get("group_bus")).strip().upper()
    tokens: set[str] = set()
    tokens.update(_tokenize_text(role_id))
    tokens.update(_tokenize_text(label))
    tokens.update(_tokenize_text(group_bus))
    for note in _string_list(obj.get("notes")):
        tokens.update(_tokenize_text(note))
    return tokens


def _is_anchor_transient(role_id: str) -> bool:
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


def _is_ambient_role(role_id: str, tokens: set[str]) -> bool:
    if role_id.startswith("ROLE.SYNTH.PAD"):
        return True
    if role_id.startswith("ROLE.FX.REVERB"):
        return True
    if role_id.startswith("ROLE.FX.AMBIENCE"):
        return True
    if role_id.startswith("ROLE.SFX."):
        return True
    return bool(tokens & _AMBIENT_TOKENS)


def _is_percussion_role(role_id: str, tokens: set[str]) -> bool:
    if role_id.startswith("ROLE.DRUM.HIHAT"):
        return True
    if role_id.startswith("ROLE.DRUM.PERC"):
        return True
    if role_id.startswith("ROLE.DRUM.CYMBAL"):
        return True
    return bool(tokens & _PERCUSSION_TOKENS)


def _anchor_wrap_intent_requested(
    *,
    scene_intent: dict[str, Any],
    object_intent: dict[str, Any],
    obj: dict[str, Any],
) -> bool:
    object_bias = _coerce_str(object_intent.get("loudness_bias")).strip().lower()
    scene_bias = _coerce_str(scene_intent.get("loudness_bias")).strip().lower()
    if object_bias == "back" or scene_bias == "back":
        return True
    marker_candidates: list[str] = [
        _coerce_str(obj.get("label")),
        _coerce_str(obj.get("role_id")),
    ]
    marker_candidates.extend(_string_list(obj.get("notes")))
    marker_candidates.extend(_string_list(scene_intent.get("notes")))
    return _has_immersive_intent_marker(marker_candidates)


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
    if role_id.startswith("ROLE.SYNTH.") or role_id.startswith("ROLE.INSTRUMENT."):
        return "BUS.MUSIC"
    if role_id.startswith("ROLE.FX.") or role_id.startswith("ROLE.SFX."):
        return "BUS.FX"
    return _BUS_OTHER


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


def _measurement_surround_wrap_allowed(
    *,
    confidence: float,
    width_hint: float,
    depth_hint: float,
    locks: set[str],
    immersive_intent: bool,
) -> bool:
    if not immersive_intent:
        return False
    if _LOCK_NO_STEREO_WIDENING in locks:
        return False
    if _LOCK_PRESERVE_TRANSIENTS in locks:
        return False
    if confidence < 0.9:
        return False
    if width_hint < 0.9:
        return False
    if depth_hint < 0.75:
        return False
    return True


def _bus_trim_db_for_class(policy_class: str) -> float:
    if policy_class == "AMBIENT.MODEST_SURROUND":
        return -1.5
    if policy_class == "PERCUSSION.TINY_SURROUND":
        return -0.75
    return 0.0


def _nonzero_channels(gains: dict[str, float], channel_order: list[str]) -> list[str]:
    return [speaker_id for speaker_id in channel_order if gains.get(speaker_id, 0.0) > 0.0]


def _stem_send(
    *,
    obj: dict[str, Any],
    channel_order: list[str],
    scene_locks: set[str],
    scene_intent: dict[str, Any],
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
    tokens = _role_tokens(obj)
    anchor_wrap_intent = _anchor_wrap_intent_requested(
        scene_intent=scene_intent,
        object_intent=intent_payload,
        obj=obj,
    )

    front_gain = 0.74
    center_gain = 0.0
    side_gain = 0.0
    rear_gain = 0.0
    notes: list[str] = []

    if _is_anchor_transient(role_id):
        policy_class = "ANCHOR.TRANSIENT_FRONT_ONLY"
        front_gain = 0.86
        if _measurement_surround_wrap_allowed(
            confidence=confidence,
            width_hint=width_hint,
            depth_hint=depth_hint,
            locks=effective_locks,
            immersive_intent=anchor_wrap_intent,
        ):
            policy_class = "ANCHOR.TRANSIENT_SURROUND_WRAP_MEASURED"
            front_gain = 0.32
            side_gain = 0.34
            rear_gain = 0.24
            notes.append("measurement_gated_surround_wrap")
        elif (
            confidence >= 0.9
            and width_hint >= 0.9
            and depth_hint >= 0.75
            and _LOCK_NO_STEREO_WIDENING not in effective_locks
            and _LOCK_PRESERVE_TRANSIENTS not in effective_locks
            and not anchor_wrap_intent
        ):
            notes.append("surround_wrap_blocked_missing_immersive_intent")
        elif (
            anchor_wrap_intent
            and _LOCK_NO_STEREO_WIDENING not in effective_locks
            and _LOCK_PRESERVE_TRANSIENTS not in effective_locks
        ):
            notes.append("surround_wrap_blocked_insufficient_measurement_evidence")
    elif _is_lead_center_role(role_id):
        policy_class = "LEAD.CENTER_OPTIONAL"
        front_gain = 0.58
        center_gain = 0.72
    elif _is_ambient_role(role_id, tokens):
        policy_class = "AMBIENT.MODEST_SURROUND"
        front_gain = 0.68
        spread = 0.22 * (0.6 + (0.4 * width_hint)) * (0.65 + (0.35 * confidence))
        side_gain = spread
        rear_gain = spread * 0.72
    elif _is_percussion_role(role_id, tokens):
        policy_class = "PERCUSSION.TINY_SURROUND"
        front_gain = 0.72
        if width_hint >= 0.78 and confidence >= 0.75:
            send = 0.06 * (0.7 + (0.3 * width_hint)) * (0.7 + (0.3 * confidence))
            side_gain = send
            rear_gain = send * 0.6
            notes.append("tiny_surround_send_enabled")
        else:
            notes.append("tiny_surround_send_disabled_low_confidence_or_width")
    else:
        policy_class = "FRONT.DEFAULT_SAFE"
        front_gain = 0.74
        if width_hint >= 0.85 and confidence >= 0.9:
            side_gain = 0.035
            rear_gain = 0.02
            notes.append("minimal_surround_send_high_confidence")

    if _LOCK_NO_STEREO_WIDENING in effective_locks:
        side_gain = 0.0
        rear_gain = 0.0
        notes.append("surround_send_disabled_by_lock_no_stereo_widening")

    if _LOCK_PRESERVE_TRANSIENTS in effective_locks and _is_anchor_transient(role_id):
        side_gain = 0.0
        rear_gain = 0.0
        notes.append("transient_anchor_front_safety_lock")

    if _LOCK_PRESERVE_TRANSIENTS in effective_locks and _is_percussion_role(role_id, tokens):
        side_gain = 0.0
        rear_gain = 0.0
        notes.append("percussion_surround_send_disabled_preserve_transients")

    if _LOCK_PRESERVE_CENTER_IMAGE in effective_locks and _CENTER in channel_order:
        if _is_lead_center_role(role_id):
            center_gain = max(center_gain, 0.86)
            front_gain = min(front_gain, 0.52)
            notes.append("center_anchor_strengthened_by_lock")

    gains = _empty_gains(channel_order)
    _set_front(gains, front_gain)
    _set_center(gains, center_gain)
    _set_surround(gains, side_gain=side_gain, rear_gain=rear_gain)

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


def _has_policy_signals(objects: list[dict[str, Any]]) -> bool:
    for obj in objects:
        role_id = _coerce_str(obj.get("role_id")).strip()
        group_bus = _coerce_str(obj.get("group_bus")).strip()
        if role_id or group_bus:
            return True
        if "width_hint" in obj or "depth_hint" in obj:
            return True
    return False


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
    """Build conservative scene->layout placement sends for renderer consumption.

    Returns ``None`` when the scene does not carry role/group/hint data needed
    by this policy path, or when ``target_layout_id`` is outside current scope.
    """
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")

    normalized_layout_id = _coerce_str(target_layout_id).strip().upper()
    if normalized_layout_id not in _SUPPORTED_LAYOUT_IDS:
        return None

    channel_order = _layout_channel_order(normalized_layout_id, layouts=layouts)
    if not channel_order:
        return None

    objects = _scene_objects(scene)
    if not objects or not _has_policy_signals(objects):
        return None

    scene_locks = _scene_lock_ids(scene)
    scene_intent = _scene_intent_payload(scene)
    stem_sends = [
        _stem_send(
            obj=obj,
            channel_order=channel_order,
            scene_locks=scene_locks,
            scene_intent=scene_intent,
        )
        for obj in objects
    ]

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
        "notes": [
            "Conservative front-heavy placement policy.",
            "Primary transient anchors remain front-safe by default.",
            (
                "Measured surround-wrap exception requires explicit immersive "
                "intent plus high width/depth/confidence evidence."
            ),
            "LFE sends remain zero by default (manual/explicit only).",
        ],
    }
