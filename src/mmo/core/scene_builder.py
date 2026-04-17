"""scene_builder.py — build a layout-agnostic Scene from a validated session + metering.

This is the "mix-once, render-many" entry point (DoD 4.3).

Key principles:
- Conservative classification: infer hints only when objective evidence supports them.
- Advisory only for stereo stems: confidence capped; never override explicit user locks.
- Explicit user locks always override inferred values.
- Deterministic: same inputs → same output (sorted stems, stable field order).
- Offline-first: no network calls; pure data transformation.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from re import split as re_split
from typing import Any

from mmo.core.media_tags import source_metadata_from_value
from mmo.core.portable_refs import is_absolute_posix_path, normalize_posix_ref, path_from_posix_ref
from mmo.core.source_locator import resolve_session_stems, resolved_stem_path
from mmo.core.stem_features import infer_stereo_hints

SCENE_SCHEMA_VERSION = "0.1.0"
_CREATED_FROM = "analyze"
_LOCK_HASH_PREFIX_LEN = 12

# Inference thresholds
_CONFIDENCE_GATE = 0.3          # below this, don't emit inferred hints
_ADVISORY_STEREO_CONF_CAP = 0.35  # max confidence for stereo-stem advisory inference
_STEREO_HINT_CONFIDENCE_GATE = 0.5
_WAV_EXTENSIONS = {".wav", ".wave"}

# Height bed channel counts (advisory; channel count alone cannot disambiguate all layouts)
_IMMERSIVE_714_CHANNELS = 12   # 7.1.4: 8-ch bed + 4 height speakers
_IMMERSIVE_10CH_CHANNELS = 10  # 5.1.4 or 7.1.2: 6/8-ch bed + 4/2 height speakers (ambiguous)

_SCENE_INTENT_DEFAULT_GENERATED_UTC = "1970-01-01T00:00:00Z"
_SCENE_INTENT_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_SCENE_INTENT_CREATED_FROM = "draft"
_SCENE_INTENT_STEMS_DIR = "/SCENE/INTENT"
_SCENE_INTENT_DEFAULT_STEMS_MAP_REF = "stems_map.json"
_SCENE_INTENT_DEFAULT_BUS_PLAN_REF = "bus_plan.json"
_SCENE_INTENT_UNKNOWN_ROLE_ID = "ROLE.OTHER.UNKNOWN"
_SCENE_INTENT_UNKNOWN_BUS_ID = "BUS.OTHER.UNKNOWN"
_SCENE_INTENT_UNKNOWN_GROUP_BUS = "BUS.OTHER"
_SCENE_INTENT_UNKNOWN_CONTENT_HINT = "fx_bed"
_SCENE_INTENT_BED_HINTS = {
    "RETURN",
    "RETURNS",
    "REVERB",
    "ROOM",
    "AMBIENCE",
    "AMBIENT",
    "LONG",
    "SFX",
    "DRONE",
    "DRONES",
    "PAD",
    "PADS",
    "CROWD",
    "AUDIENCE",
}
_SCENE_INTENT_CLOSE_INSTRUMENT_ROLE_PREFIXES: tuple[str, ...] = (
    "ROLE.GTR.",
    "ROLE.KEYS.",
    "ROLE.STRINGS.",
    "ROLE.BRASS.",
    "ROLE.WINDS.",
    "ROLE.WW.",
    "ROLE.SYNTH.LEAD",
    "ROLE.SYNTH.ARP",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_channel_count(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, float) and value >= 1.0:
        return int(value)
    return 1


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _index_metering(metering_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build stem_id → metering-row index from a metering report."""
    if not isinstance(metering_report, dict):
        return {}
    stems = metering_report.get("stems")
    if not isinstance(stems, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for entry in stems:
        if not isinstance(entry, dict):
            continue
        stem_id = _coerce_str(entry.get("stem_id")).strip()
        if stem_id:
            index[stem_id] = entry
    return index


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _resolve_stem_source_path(
    *,
    stem: dict[str, Any],
    stems_dir_path: Path,
) -> Path | None:
    del stems_dir_path
    # Run stereo-hint inference on the same canonical path that later scene and
    # render stages use. If this drifts, hints can describe a different file
    # than the one later rendered.
    candidate = resolved_stem_path(stem)
    if candidate is None:
        return None
    # The current stereo feature extractor only trusts WAV inputs here. Other
    # formats stay advisory-free instead of adding a second decode path inside
    # scene assembly.
    if candidate.suffix.lower() not in _WAV_EXTENSIONS:
        return None
    return candidate


def _stereo_hint_metrics_rows(metrics: Any) -> list[dict[str, Any]]:
    if not isinstance(metrics, dict):
        return []
    rows: list[dict[str, Any]] = []
    for metric_id in sorted(metrics.keys()):
        value = metrics.get(metric_id)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            rows.append(
                {
                    "metric_id": metric_id,
                    "value": round(float(value), 6),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Inference functions (objective, conservative, advisory)
# ---------------------------------------------------------------------------

def _infer_width_from_correlation(
    correlation: float | None,
    *,
    is_stereo: bool,
) -> tuple[float | None, float]:
    """Return (width, confidence).  Advisory only; only meaningful for stereo stems."""
    if not is_stereo or correlation is None:
        return None, 0.0
    # High correlation → narrow (mono-like); low correlation → wide
    if correlation >= 0.85:
        return 0.2, 0.35
    if correlation >= 0.5:
        return 0.5, 0.3
    return 0.8, 0.3


def _infer_depth_from_crest(crest_db: float | None) -> tuple[float | None, float]:
    """Return (depth, confidence).  Crest factor as directness/distance proxy.

    High crest (transient, dry) → forward (low depth).
    Low crest (dense, reverberant) → distant (high depth).
    """
    if crest_db is None:
        return None, 0.0
    if crest_db >= 18.0:
        return 0.15, 0.35
    if crest_db >= 12.0:
        return 0.30, 0.35
    if crest_db >= 8.0:
        return 0.50, 0.30
    return 0.70, 0.30


def _infer_routing_intent(stems: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer session-level routing hint from stem channel counts."""
    max_channels = max(
        (_coerce_channel_count(s.get("channel_count")) for s in stems),
        default=0,
    )
    if max_channels > 6:
        routing_notes = ["multichannel_stem_gt6ch"]
        if max_channels == _IMMERSIVE_714_CHANNELS:
            routing_notes.append("height_bed_714_candidate")
        elif max_channels == _IMMERSIVE_10CH_CHANNELS:
            routing_notes.append("height_bed_10ch_candidate")
        return {
            "suggested_layout_class": "immersive",
            "confidence": 0.8,
            "notes": routing_notes,
        }
    if max_channels > 2:
        return {
            "suggested_layout_class": "surround",
            "confidence": 0.7,
            "notes": ["multichannel_stem_found"],
        }
    if max_channels == 2:
        return {
            "suggested_layout_class": "stereo",
            "confidence": 0.6,
            "notes": ["stereo_stems_advisory"],
        }
    return {
        "suggested_layout_class": "stereo",
        "confidence": 0.4,
        "notes": ["mono_stems_only"],
    }


def _build_object_intent(
    stem: dict[str, Any],
    meter: dict[str, Any] | None,
    lock_ids: list[str],
    stereo_hints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, float], list[str]]:
    """Return (intent_dict, applied_hints, advisory_notes).

    Width and depth are only emitted when confidence >= _CONFIDENCE_GATE.
    Confidence for stereo stems is always capped at _ADVISORY_STEREO_CONF_CAP.
    Explicit lock_ids always propagate regardless of confidence.
    """
    channel_count = _coerce_channel_count(stem.get("channel_count"))
    is_stereo = channel_count == 2
    is_multichannel = channel_count > 2

    correlation = _safe_float(meter.get("correlation")) if isinstance(meter, dict) else None
    crest_db = _safe_float(meter.get("crest_db")) if isinstance(meter, dict) else None

    width, width_conf = _infer_width_from_correlation(correlation, is_stereo=is_stereo)
    depth, depth_conf = _infer_depth_from_crest(crest_db)
    stereo_width = _safe_float(stereo_hints.get("width_hint")) if isinstance(stereo_hints, dict) else None
    stereo_azimuth = (
        _safe_float(stereo_hints.get("azimuth_deg_hint"))
        if isinstance(stereo_hints, dict)
        else None
    )
    stereo_depth = _safe_float(stereo_hints.get("depth_hint")) if isinstance(stereo_hints, dict) else None
    stereo_conf = _safe_float(stereo_hints.get("confidence")) if isinstance(stereo_hints, dict) else None
    stereo_hint_ready = bool(
        is_stereo
        and stereo_width is not None
        and stereo_azimuth is not None
        and stereo_conf is not None
        and stereo_conf >= _STEREO_HINT_CONFIDENCE_GATE
    )

    if stereo_hint_ready and stereo_width is not None and stereo_conf is not None:
        width = max(0.0, min(1.0, stereo_width))
        width_conf = max(width_conf, stereo_conf)
        # Prefer measured reverb depth over crest-factor proxy when available
        if stereo_depth is not None:
            depth = max(0.0, min(1.0, stereo_depth))
            depth_conf = max(depth_conf, stereo_conf)

    # Cap confidence for advisory stereo inferences
    if is_stereo:
        width_conf = min(width_conf, _ADVISORY_STEREO_CONF_CAP)
        depth_conf = min(depth_conf, _ADVISORY_STEREO_CONF_CAP)

    effective_conf = round(max(width_conf, depth_conf), 3)

    intent: dict[str, Any] = {
        "confidence": effective_conf,
        "locks": sorted(lock_ids),
    }
    applied_hints: dict[str, float] = {}
    notes: list[str] = []

    if effective_conf >= _CONFIDENCE_GATE:
        if width is not None and width_conf >= _CONFIDENCE_GATE:
            intent["width"] = round(width, 3)
            applied_hints["width_hint"] = round(width, 3)
        if depth is not None and depth_conf >= _CONFIDENCE_GATE:
            intent["depth"] = round(depth, 3)
        if stereo_hint_ready and stereo_azimuth is not None:
            azimuth = max(-180.0, min(180.0, stereo_azimuth))
            intent["position"] = {"azimuth_deg": round(azimuth, 3)}
            applied_hints["azimuth_hint"] = round(azimuth, 3)
            notes.append("stereo_feature_hint")

    if is_stereo and meter is not None:
        notes.append("advisory_stereo_stem")
    if is_multichannel:
        notes.append("multichannel_as_object")
        if channel_count == _IMMERSIVE_714_CHANNELS:
            notes.append("height_bed_714_candidate")
        elif channel_count == _IMMERSIVE_10CH_CHANNELS:
            notes.append("height_bed_10ch_candidate")

    return intent, applied_hints, notes


def _label_from_stem(stem: dict[str, Any], *, index: int) -> str:
    label = _coerce_str(stem.get("label")).strip()
    if label:
        return label
    file_path = _coerce_str(stem.get("file_path")).strip()
    if file_path:
        return Path(file_path).name
    stem_id = _coerce_str(stem.get("stem_id")).strip()
    return stem_id or f"stem_{index:03d}"


def _build_scene_metering(
    metering_report: dict[str, Any],
    objects: list[dict[str, Any]],
    meter_index: dict[str, dict[str, Any]],
    stem_count: int,
) -> dict[str, Any]:
    """Build the scene_metering block from a metering report."""
    mode = _coerce_str(metering_report.get("mode")).strip() or "none"
    scene_metering: dict[str, Any] = {"mode": mode}

    # Per-object metering
    object_meters: list[dict[str, Any]] = []
    for obj in objects:
        oid = obj["object_id"]
        sid = obj["stem_id"]
        m = meter_index.get(sid)
        if m is not None:
            entry: dict[str, Any] = {"object_id": oid, "stem_id": sid}
            for key in ("lufs_i", "true_peak_dbtp", "crest_db", "correlation"):
                val = _safe_float(m.get(key))
                entry[key] = val
            object_meters.append(entry)
    if object_meters:
        scene_metering["objects"] = object_meters

    # Session aggregates
    sess = metering_report.get("session")
    if isinstance(sess, dict):
        scene_metering["session"] = {
            "stem_count": stem_count,
            "lufs_i_min": _safe_float(sess.get("lufs_i_min")),
            "lufs_i_max": _safe_float(sess.get("lufs_i_max")),
            "lufs_i_range_db": _safe_float(sess.get("lufs_i_range_db")),
            "true_peak_max_dbtp": _safe_float(sess.get("true_peak_max_dbtp")),
        }

    return scene_metering


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_scene_from_session(
    validated_session: dict[str, Any],
    metering_report: dict[str, Any] | None = None,
    *,
    scene_id: str | None = None,
    lock_hash: str | None = None,
    user_locks: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build a layout-agnostic Scene dict from a validated session + optional metering.

    Args:
        validated_session: Session dict with ``stems_dir`` and ``stems`` list.
            Each stem entry should have ``stem_id``, ``channel_count``, and
            optionally ``label``, ``file_path``, ``notes``.
        metering_report: Optional dict produced by ``_build_metering_summary`` (or
            equivalent), containing ``mode``, ``stems``, and ``session`` keys.
        scene_id: Optional explicit scene ID string (overrides auto-generation).
        lock_hash: Optional lock hash for deterministic scene ID generation.
        user_locks: Optional mapping of ``stem_id`` → list of lock ID strings.
            These are applied verbatim and override any inferred placement.

    Returns:
        A scene dict that validates against ``scene.schema.json``.

    Raises:
        ValueError: If ``validated_session`` is not a dict, or ``stems_dir``
            is missing or not absolute.
    """
    if not isinstance(validated_session, dict):
        raise ValueError("validated_session must be an object.")

    stems_dir_raw = _coerce_str(validated_session.get("stems_dir")).strip()
    if not stems_dir_raw:
        raise ValueError("validated_session.stems_dir is required.")
    stems_dir_path = Path(stems_dir_raw)
    # Scene receipts use an absolute anchor here so later render and lock
    # helpers do not have to guess which workspace the session came from.
    if not stems_dir_path.is_absolute():
        raise ValueError("validated_session.stems_dir must be an absolute path.")
    stems_dir_posix = stems_dir_path.resolve().as_posix()

    # Normalize stem locators before any inference so object ordering and
    # source-backed hints all see the same canonical stem payload.
    stems = resolve_session_stems(validated_session)

    meter_index = _index_metering(metering_report)
    user_locks_map: dict[str, list[str]] = user_locks or {}

    # Build objects (all stems → objects; multichannel noted but not reclassified)
    objects: list[dict[str, Any]] = []
    stereo_hint_evidence: list[dict[str, Any]] = []
    for idx, stem in enumerate(stems):
        stem_id = _coerce_str(stem.get("stem_id")).strip() or f"STEM.{idx:03d}"
        object_id = f"OBJ.{stem_id}"
        meter = meter_index.get(stem_id)
        lock_ids = list(user_locks_map.get(stem_id, []))
        channel_count = _coerce_channel_count(stem.get("channel_count"))

        stereo_hints: dict[str, Any] | None = None
        if channel_count == 2:
            source_path = _resolve_stem_source_path(stem=stem, stems_dir_path=stems_dir_path)
            if source_path is not None:
                try:
                    # Stereo hints stay advisory. Failure here should not block
                    # scene creation or hide the rest of the session.
                    stereo_hints = infer_stereo_hints(source_path)
                except ValueError:
                    stereo_hints = None

        intent, applied_hints, infer_notes = _build_object_intent(
            stem,
            meter,
            lock_ids,
            stereo_hints=stereo_hints,
        )

        existing_notes = _string_list(stem.get("notes"))
        all_notes = existing_notes + [n for n in infer_notes if n not in existing_notes]

        object_payload = {
            "object_id": object_id,
            "stem_id": stem_id,
            "label": _label_from_stem(stem, index=idx),
            "channel_count": channel_count,
            "intent": intent,
            "notes": all_notes,
        }
        if "width_hint" in applied_hints:
            object_payload["width_hint"] = applied_hints["width_hint"]
        if "azimuth_hint" in applied_hints:
            object_payload["azimuth_hint"] = applied_hints["azimuth_hint"]
        source_metadata = source_metadata_from_value(stem.get("source_metadata"))
        if source_metadata is not None:
            object_payload["source_metadata"] = source_metadata
        objects.append(object_payload)

        if isinstance(stereo_hints, dict):
            stereo_width = _safe_float(stereo_hints.get("width_hint"))
            stereo_azimuth = _safe_float(stereo_hints.get("azimuth_deg_hint"))
            stereo_confidence = _safe_float(stereo_hints.get("confidence"))
            if (
                stereo_width is not None
                and stereo_azimuth is not None
                and stereo_confidence is not None
            ):
                stereo_hint_evidence.append(
                    {
                        "object_id": object_id,
                        "stem_id": stem_id,
                        "width_hint": round(max(0.0, min(1.0, stereo_width)), 3),
                        "azimuth_deg_hint": round(max(-180.0, min(180.0, stereo_azimuth)), 3),
                        "confidence": round(max(0.0, min(1.0, stereo_confidence)), 3),
                        "applied": bool(
                            "width_hint" in applied_hints and "azimuth_hint" in applied_hints
                        ),
                        "metrics": _stereo_hint_metrics_rows(stereo_hints.get("metrics")),
                    }
                )

    # Sort once here so repeated scene builds stay deterministic even if the
    # incoming stem order changed upstream.
    objects.sort(key=lambda o: (o["stem_id"], o["object_id"]))

    # Leave the field bed present even for object-only sessions so later layout
    # and precedence code can rely on one stable bed anchor.
    beds: list[dict[str, Any]] = [
        {
            "bed_id": "BED.FIELD.001",
            "label": "Field",
            "kind": "field",
            "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []},
            "notes": [],
        }
    ]

    # Session-level routing intent (advisory)
    routing_intent = _infer_routing_intent(stems)

    # Metadata
    metadata: dict[str, Any] = {}
    profile_id = _coerce_str(validated_session.get("profile_id")).strip()
    if profile_id:
        metadata["profile_id"] = profile_id
    preset_id = _coerce_str(validated_session.get("preset_id")).strip()
    if preset_id:
        metadata["preset_id"] = preset_id

    if isinstance(metering_report, dict) and "mode" in metering_report:
        metadata["metering"] = _build_scene_metering(
            metering_report, objects, meter_index, len(stems)
        )
    if stereo_hint_evidence:
        metadata["stereo_hints"] = sorted(
            stereo_hint_evidence,
            key=lambda row: (
                _coerce_str(row.get("stem_id")),
                _coerce_str(row.get("object_id")),
            ),
        )

    # Source block
    normalized_lock_hash = _coerce_str(lock_hash).strip() or None
    source: dict[str, Any] = {
        "stems_dir": stems_dir_posix,
        "created_from": _CREATED_FROM,
    }
    if normalized_lock_hash:
        source["lock_hash"] = normalized_lock_hash

    # Explicit scene IDs win. Otherwise the lock hash is the stable override
    # key, and only the no-lock fallback stays generic.
    override_id = _coerce_str(scene_id).strip() or None
    if override_id:
        final_scene_id = override_id
    elif normalized_lock_hash:
        final_scene_id = f"SCENE.{normalized_lock_hash[:_LOCK_HASH_PREFIX_LEN]}"
    else:
        final_scene_id = "SCENE.UNKNOWN"

    return {
        "schema_version": SCENE_SCHEMA_VERSION,
        "scene_id": final_scene_id,
        "source": source,
        "objects": objects,
        "beds": beds,
        "routing_intent": routing_intent,
        "metadata": metadata,
    }


def _clamp_unit(value: Any, *, default: float) -> float:
    numeric = _safe_float(value)
    if numeric is None:
        return default
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return round(numeric, 3)


def _scene_intent_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = _coerce_str(value).strip().upper()
        if not normalized:
            continue
        for token in re_split(r"[^A-Z0-9]+", normalized):
            if token:
                tokens.add(token)
    return tokens


def _scene_intent_group_bus(bus_id: str) -> str:
    normalized = _coerce_str(bus_id).strip().upper()
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 2 and parts[0] == "BUS":
        return f"BUS.{parts[1]}"
    if len(parts) == 1 and parts[0].startswith("BUS"):
        return normalized
    return _SCENE_INTENT_UNKNOWN_GROUP_BUS


def _scene_intent_label(file_path: str, stem_id: str, *, index: int) -> str:
    file_name = Path(file_path).name if file_path else ""
    if file_name:
        stem = Path(file_name).stem
        if stem:
            return stem
        return file_name
    if stem_id:
        return stem_id
    return f"stem_{index:03d}"


def _scene_intent_content_hint(tokens: set[str]) -> str:
    if "REVERB" in tokens or "RETURN" in tokens or "RETURNS" in tokens:
        return "reverb_return"
    if "ROOM" in tokens or "AMBIENCE" in tokens or "AMBIENT" in tokens:
        return "ambience"
    if "PAD" in tokens or "PADS" in tokens:
        return "pad_texture"
    if "CROWD" in tokens or "AUDIENCE" in tokens:
        return "crowd"
    return _SCENE_INTENT_UNKNOWN_CONTENT_HINT


def _scene_intent_bed_width_hint(content_hint: str) -> float:
    if content_hint in {"reverb_return", "ambience", "crowd"}:
        return 1.0
    if content_hint == "pad_texture":
        return 0.85
    return 0.75


def _scene_intent_object_hints(
    role_id: str,
    assignment_confidence: float,
    *,
    uncertain: bool,
    close_instrument: bool,
) -> dict[str, Any]:
    role_upper = role_id.upper()
    is_bass = role_upper.startswith("ROLE.BASS.")
    is_drum = role_upper.startswith("ROLE.DRUM.")
    is_lead_vox = role_upper in {
        "ROLE.VOCAL.LEAD",
        "ROLE.DIALOGUE.LEAD",
    } or role_upper.startswith("ROLE.VOCAL.LEAD.")
    is_center_anchor = is_bass or is_lead_vox or role_upper in {
        "ROLE.DRUM.KICK",
        "ROLE.DRUM.SNARE",
    }

    if uncertain:
        return {
            "width_hint": None,
            "depth_hint": None,
            "confidence": min(0.35, max(0.2, assignment_confidence)),
            "azimuth_hint": None,
            "classification_note": "object_low_confidence_no_hint",
        }

    if is_center_anchor:
        return {
            "width_hint": 0.2,
            "depth_hint": 0.25,
            "confidence": max(0.8, assignment_confidence),
            "azimuth_hint": 0.0,
            "classification_note": "close_miked_anchor_object",
        }

    if is_drum:
        return {
            "width_hint": 0.3,
            "depth_hint": 0.3,
            "confidence": max(0.75, assignment_confidence),
            "azimuth_hint": None,
            "classification_note": "close_miked_drum_object",
        }

    if close_instrument:
        return {
            "width_hint": 0.3,
            "depth_hint": 0.35,
            "confidence": max(0.72, assignment_confidence),
            "azimuth_hint": None,
            "classification_note": "close_instrument_object",
        }

    return {
        "width_hint": 0.35,
        "depth_hint": 0.4,
        "confidence": max(0.7, assignment_confidence),
        "azimuth_hint": None,
        "classification_note": "default_object",
    }


def _scene_intent_scene_id(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "SCENE.BUS.UNKNOWN"
    digest_input = "|".join(
        f"{row['stem_id']}::{row['role_id']}::{row['bus_id']}"
        for row in rows
    )
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:12].upper()
    return f"SCENE.BUS.{digest}"


def _scene_intent_source_refs(
    stems_map: dict[str, Any],
    bus_plan: dict[str, Any],
    *,
    stems_map_ref: str | None,
    bus_plan_ref: str | None,
) -> dict[str, Any]:
    bus_plan_source = bus_plan.get("source")
    bus_plan_source_obj = bus_plan_source if isinstance(bus_plan_source, dict) else {}

    resolved_stems_map_ref = (
        _coerce_str(stems_map_ref).strip()
        or _coerce_str(stems_map.get("stems_map_ref")).strip()
        or _coerce_str(bus_plan_source_obj.get("stems_map_ref")).strip()
        or _SCENE_INTENT_DEFAULT_STEMS_MAP_REF
    )
    resolved_bus_plan_ref = (
        _coerce_str(bus_plan_ref).strip()
        or _SCENE_INTENT_DEFAULT_BUS_PLAN_REF
    )

    refs: dict[str, Any] = {
        "stems_map_ref": resolved_stems_map_ref,
        "bus_plan_ref": resolved_bus_plan_ref,
    }

    roles_ref = (
        _coerce_str(stems_map.get("roles_ref")).strip()
        or _coerce_str(bus_plan_source_obj.get("roles_ref")).strip()
    )
    if roles_ref:
        refs["roles_ref"] = roles_ref

    stems_index_ref = _coerce_str(stems_map.get("stems_index_ref")).strip()
    if stems_index_ref:
        refs["stems_index_ref"] = stems_index_ref

    return refs


def _scene_intent_stems_dir(
    stems_map: dict[str, Any],
    bus_plan: dict[str, Any],
) -> str:
    bus_plan_source_obj = bus_plan.get("source")
    if not isinstance(bus_plan_source_obj, dict):
        bus_plan_source_obj = {}

    candidates = (
        _coerce_str(stems_map.get("stems_index_ref")).strip(),
        _coerce_str(bus_plan_source_obj.get("stems_index_ref")).strip(),
    )
    for candidate in candidates:
        normalized_candidate = normalize_posix_ref(candidate)
        if not normalized_candidate:
            continue
        path = path_from_posix_ref(normalized_candidate)
        if is_absolute_posix_path(normalized_candidate):
            if path.is_dir():
                return path.resolve().as_posix()
            if path.is_file():
                return path.parent.resolve().as_posix()
        elif path.suffix:
            parent = path.parent.as_posix()
            return parent or "."
        else:
            return path.as_posix() or "."
    return _SCENE_INTENT_STEMS_DIR


def build_scene_from_bus_plan(
    stems_map: dict[str, Any],
    bus_plan: dict[str, Any],
    *,
    profile_id: str = _SCENE_INTENT_DEFAULT_PROFILE_ID,
    stems_map_ref: str | None = None,
    bus_plan_ref: str | None = None,
) -> dict[str, Any]:
    """Build scene intent scaffolding from stems_map + bus_plan.

    This path is deliberately conservative:
    - `objects` contain close-miked anchors and uncertain sources.
    - `beds` aggregate ambience/fx-style sources.
    - Uncertain assignments remain objects with low confidence and no azimuth hint.
    """
    if not isinstance(stems_map, dict):
        raise ValueError("stems_map must be an object.")
    if not isinstance(bus_plan, dict):
        raise ValueError("bus_plan must be an object.")

    map_assignments_raw = stems_map.get("assignments")
    if not isinstance(map_assignments_raw, list):
        raise ValueError("stems_map.assignments must be an array.")
    bus_assignments_raw = bus_plan.get("assignments")
    if not isinstance(bus_assignments_raw, list):
        raise ValueError("bus_plan.assignments must be an array.")

    map_assignments: dict[str, dict[str, Any]] = {}
    for item in map_assignments_raw:
        if not isinstance(item, dict):
            continue
        stem_id = _coerce_str(item.get("stem_id")).strip()
        if stem_id:
            map_assignments[stem_id] = item

    merged_rows: list[dict[str, str | float]] = []
    seen_stem_ids: set[str] = set()
    # Prefer bus-plan rows when they exist, then fill gaps from stems_map so
    # scene scaffolding stays complete without inventing duplicate stems.
    for item in bus_assignments_raw:
        if not isinstance(item, dict):
            continue
        stem_id = _coerce_str(item.get("stem_id")).strip()
        if not stem_id:
            continue
        map_entry = map_assignments.get(stem_id, {})
        file_path = (
            _coerce_str(item.get("file_path")).strip()
            or _coerce_str(map_entry.get("rel_path")).strip()
        )
        role_id = (
            _coerce_str(item.get("role_id")).strip()
            or _coerce_str(map_entry.get("role_id")).strip()
            or _SCENE_INTENT_UNKNOWN_ROLE_ID
        )
        bus_id = _coerce_str(item.get("bus_id")).strip() or _SCENE_INTENT_UNKNOWN_BUS_ID
        confidence = _clamp_unit(
            item.get("confidence", map_entry.get("confidence")),
            default=0.0,
        )
        merged_rows.append(
            {
                "stem_id": stem_id,
                "file_path": file_path,
                "role_id": role_id,
                "bus_id": bus_id,
                "confidence": confidence,
            }
        )
        seen_stem_ids.add(stem_id)

    for item in sorted(
        [entry for entry in map_assignments_raw if isinstance(entry, dict)],
        key=lambda entry: (
            _coerce_str(entry.get("rel_path")).strip(),
            _coerce_str(entry.get("stem_id")).strip(),
        ),
    ):
        stem_id = _coerce_str(item.get("stem_id")).strip()
        if not stem_id or stem_id in seen_stem_ids:
            continue
        merged_rows.append(
            {
                "stem_id": stem_id,
                "file_path": _coerce_str(item.get("rel_path")).strip(),
                "role_id": _coerce_str(item.get("role_id")).strip() or _SCENE_INTENT_UNKNOWN_ROLE_ID,
                "bus_id": _SCENE_INTENT_UNKNOWN_BUS_ID,
                "confidence": _clamp_unit(item.get("confidence"), default=0.0),
            }
        )

    sorted_rows = sorted(
        merged_rows,
        key=lambda row: (
            _coerce_str(row.get("file_path")).strip(),
            _coerce_str(row.get("stem_id")).strip(),
            _coerce_str(row.get("role_id")).strip(),
            _coerce_str(row.get("bus_id")).strip(),
        ),
    )

    object_rows: list[dict[str, Any]] = []
    bed_buckets: dict[str, list[dict[str, Any]]] = {}

    for row in sorted_rows:
        stem_id = _coerce_str(row.get("stem_id")).strip()
        file_path = _coerce_str(row.get("file_path")).strip()
        role_id = _coerce_str(row.get("role_id")).strip() or _SCENE_INTENT_UNKNOWN_ROLE_ID
        bus_id = _coerce_str(row.get("bus_id")).strip() or _SCENE_INTENT_UNKNOWN_BUS_ID
        group_bus = _scene_intent_group_bus(bus_id)
        assignment_confidence = _clamp_unit(row.get("confidence"), default=0.0)
        tokens = _scene_intent_tokens(role_id, file_path, bus_id)

        is_bed_candidate = any(token in _SCENE_INTENT_BED_HINTS for token in tokens)
        is_anchor_object = (
            role_id.startswith("ROLE.DRUM.")
            or role_id.startswith("ROLE.BASS.")
            or role_id.startswith("ROLE.VOCAL.LEAD")
            or role_id.startswith("ROLE.DIALOGUE.LEAD")
        )
        is_close_instrument = role_id.startswith(_SCENE_INTENT_CLOSE_INSTRUMENT_ROLE_PREFIXES)
        if not is_close_instrument and (
            "CLOSE" in tokens
            or "MIC" in tokens
            or "DI" in tokens
        ):
            is_close_instrument = True
        is_object_candidate = is_anchor_object or is_close_instrument

        if is_bed_candidate:
            # Ambience and return-style material collapse to beds on purpose.
            # Unknowns that are not clearly bed-like stay as low-confidence
            # objects instead of disappearing into a diffuse bucket.
            content_hint = _scene_intent_content_hint(tokens)
            bed_bucket = bed_buckets.setdefault(bus_id, [])
            bed_bucket.append(
                {
                    "stem_id": stem_id,
                    "content_hint": content_hint,
                    "width_hint": _scene_intent_bed_width_hint(content_hint),
                    "confidence": max(0.65, assignment_confidence),
                }
            )
            continue

        hints = _scene_intent_object_hints(
            role_id,
            assignment_confidence,
            uncertain=not is_object_candidate,
            close_instrument=is_close_instrument,
        )
        object_rows.append(
            {
                "stem_id": stem_id,
                "role_id": role_id,
                "group_bus": group_bus,
                "file_path": file_path,
                "width_hint": hints["width_hint"],
                "depth_hint": hints["depth_hint"],
                "confidence": round(_clamp_unit(hints["confidence"], default=0.0), 3),
                "azimuth_hint": hints["azimuth_hint"],
                "classification_note": hints["classification_note"],
            }
        )

    objects: list[dict[str, Any]] = []
    # Sort object scaffolding before IDs and labels are assigned so repeated
    # scene drafts keep one object list and one note order.
    for index, row in enumerate(
        sorted(
            object_rows,
            key=lambda item: (
                item["group_bus"],
                item["stem_id"],
                item["role_id"],
            ),
        )
    ):
        confidence = _clamp_unit(row.get("confidence"), default=0.0)
        width_hint_raw = _safe_float(row.get("width_hint"))
        width_hint = _clamp_unit(width_hint_raw, default=0.4) if width_hint_raw is not None else None
        depth_hint_raw = _safe_float(row.get("depth_hint"))
        depth_hint = _clamp_unit(depth_hint_raw, default=0.5) if depth_hint_raw is not None else None

        object_intent: dict[str, Any] = {
            "confidence": confidence,
            "locks": [],
        }
        if width_hint is not None:
            object_intent["width"] = width_hint
        if depth_hint is not None:
            object_intent["depth"] = depth_hint

        azimuth_hint_value = row.get("azimuth_hint")
        if isinstance(azimuth_hint_value, (int, float)):
            object_intent["position"] = {"azimuth_deg": float(azimuth_hint_value)}

        object_payload: dict[str, Any] = {
            "object_id": f"OBJ.{row['stem_id']}",
            "stem_id": row["stem_id"],
            "role_id": row["role_id"],
            "group_bus": row["group_bus"],
            "label": _scene_intent_label(
                _coerce_str(row.get("file_path")).strip(),
                row["stem_id"],
                index=index,
            ),
            "channel_count": 1,
            "azimuth_hint": azimuth_hint_value if isinstance(azimuth_hint_value, (int, float)) else None,
            "confidence": confidence,
            "locks": {
                "azimuth_hint": False,
                "width_hint": False,
                "depth_hint": False,
            },
            "intent": object_intent,
            "notes": [
                f"role_id: {row['role_id']}",
                f"group_bus: {row['group_bus']}",
                f"classification: {row['classification_note']}",
            ],
        }
        if object_payload["azimuth_hint"] is None:
            object_payload.pop("azimuth_hint")
        if width_hint is not None:
            object_payload["width_hint"] = width_hint
        if depth_hint is not None:
            object_payload["depth_hint"] = depth_hint
        objects.append(object_payload)

    beds: list[dict[str, Any]] = []
    # Build each bed from its whole bucket in one pass so stem_ids, width
    # hints, and confidence stay internally consistent.
    for bus_id in sorted(bed_buckets.keys()):
        bucket = bed_buckets[bus_id]
        content_counts: dict[str, int] = {}
        for item in bucket:
            hint = _coerce_str(item.get("content_hint")).strip() or _SCENE_INTENT_UNKNOWN_CONTENT_HINT
            content_counts[hint] = content_counts.get(hint, 0) + 1
        content_hint = sorted(
            content_counts.keys(),
            key=lambda hint: (-content_counts[hint], hint),
        )[0]
        width_hint = round(
            max(
                (_clamp_unit(item.get("width_hint"), default=0.75) for item in bucket),
                default=0.75,
            ),
            3,
        )
        confidence = round(
            sum(_clamp_unit(item.get("confidence"), default=0.0) for item in bucket) / len(bucket),
            3,
        )
        stem_ids = sorted(
            {
                _coerce_str(item.get("stem_id")).strip()
                for item in bucket
                if _coerce_str(item.get("stem_id")).strip()
            }
        )
        bed_id = f"BED.{bus_id.replace('BUS.', '').replace('.', '_')}"
        beds.append(
            {
                "bed_id": bed_id,
                "label": bus_id.replace("BUS.", "").replace(".", " ").title(),
                "kind": "bed",
                "bus_id": bus_id,
                "stem_ids": stem_ids,
                "content_hint": content_hint,
                "width_hint": width_hint,
                "confidence": confidence,
                "intent": {
                    "diffuse": width_hint,
                    "confidence": confidence,
                    "locks": [],
                },
                "notes": [f"content_hint: {content_hint}"],
            }
        )

    normalized_profile_id = (
        _coerce_str(profile_id).strip() or _SCENE_INTENT_DEFAULT_PROFILE_ID
    )
    scene_rows_for_id = [
        {
            "stem_id": _coerce_str(row.get("stem_id")).strip(),
            "role_id": _coerce_str(row.get("role_id")).strip() or _SCENE_INTENT_UNKNOWN_ROLE_ID,
            "bus_id": _coerce_str(row.get("bus_id")).strip() or _SCENE_INTENT_UNKNOWN_BUS_ID,
        }
        for row in sorted_rows
    ]
    source_refs = _scene_intent_source_refs(
        stems_map,
        bus_plan,
        stems_map_ref=stems_map_ref,
        bus_plan_ref=bus_plan_ref,
    )
    # Derive source refs and stems_dir from portable refs first. Scene drafts
    # should survive repo moves better than machine-local absolute guesses.
    generated_utc = (
        _coerce_str(bus_plan.get("generated_utc")).strip()
        or _SCENE_INTENT_DEFAULT_GENERATED_UTC
    )

    return {
        "schema_version": SCENE_SCHEMA_VERSION,
        "scene_id": _scene_intent_scene_id(scene_rows_for_id),
        "generated_utc": generated_utc,
        "source": {
            "stems_dir": _scene_intent_stems_dir(stems_map, bus_plan),
            "created_from": _SCENE_INTENT_CREATED_FROM,
        },
        "source_refs": source_refs,
        "objects": objects,
        "beds": beds,
        "rules": {
            "layout_safety_defaults": {
                "unknown_role_strategy": "object_low_confidence",
                "default_azimuth_mode": "none",
                "prefer_bed_for_ambient": True,
            },
            "lfe_policy_defaults": {
                "allow_inferred_lfe_send": False,
                "mode": "manual_only",
            },
        },
        "metadata": {
            "profile_id": normalized_profile_id,
        },
    }
