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

from pathlib import Path
from typing import Any

from mmo.core.media_tags import source_metadata_from_value

SCENE_SCHEMA_VERSION = "0.1.0"
_CREATED_FROM = "analyze"
_LOCK_HASH_PREFIX_LEN = 12

# Inference thresholds
_CONFIDENCE_GATE = 0.3          # below this, don't emit inferred hints
_ADVISORY_STEREO_CONF_CAP = 0.35  # max confidence for stereo-stem advisory inference

# Height bed channel counts (advisory; channel count alone cannot disambiguate all layouts)
_IMMERSIVE_714_CHANNELS = 12   # 7.1.4: 8-ch bed + 4 height speakers
_IMMERSIVE_10CH_CHANNELS = 10  # 5.1.4 or 7.1.2: 6/8-ch bed + 4/2 height speakers (ambiguous)


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
) -> tuple[dict[str, Any], list[str]]:
    """Return (intent_dict, advisory_notes).

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

    # Cap confidence for advisory stereo inferences
    if is_stereo:
        width_conf = min(width_conf, _ADVISORY_STEREO_CONF_CAP)
        depth_conf = min(depth_conf, _ADVISORY_STEREO_CONF_CAP)

    effective_conf = round(max(width_conf, depth_conf), 3)

    intent: dict[str, Any] = {
        "confidence": effective_conf,
        "locks": sorted(lock_ids),
    }
    notes: list[str] = []

    if effective_conf >= _CONFIDENCE_GATE:
        if width is not None and width_conf >= _CONFIDENCE_GATE:
            intent["width"] = round(width, 3)
        if depth is not None and depth_conf >= _CONFIDENCE_GATE:
            intent["depth"] = round(depth, 3)

    if is_stereo and meter is not None:
        notes.append("advisory_stereo_stem")
    if is_multichannel:
        notes.append("multichannel_as_object")
        if channel_count == _IMMERSIVE_714_CHANNELS:
            notes.append("height_bed_714_candidate")
        elif channel_count == _IMMERSIVE_10CH_CHANNELS:
            notes.append("height_bed_10ch_candidate")

    return intent, notes


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
    if not stems_dir_path.is_absolute():
        raise ValueError("validated_session.stems_dir must be an absolute path.")
    stems_dir_posix = stems_dir_path.resolve().as_posix()

    raw_stems = validated_session.get("stems")
    stems: list[dict[str, Any]] = (
        [s for s in raw_stems if isinstance(s, dict)]
        if isinstance(raw_stems, list)
        else []
    )

    meter_index = _index_metering(metering_report)
    user_locks_map: dict[str, list[str]] = user_locks or {}

    # Build objects (all stems → objects; multichannel noted but not reclassified)
    objects: list[dict[str, Any]] = []
    for idx, stem in enumerate(stems):
        stem_id = _coerce_str(stem.get("stem_id")).strip() or f"STEM.{idx:03d}"
        object_id = f"OBJ.{stem_id}"
        meter = meter_index.get(stem_id)
        lock_ids = list(user_locks_map.get(stem_id, []))

        intent, infer_notes = _build_object_intent(stem, meter, lock_ids)

        existing_notes = _string_list(stem.get("notes"))
        all_notes = existing_notes + [n for n in infer_notes if n not in existing_notes]

        object_payload = {
            "object_id": object_id,
            "stem_id": stem_id,
            "label": _label_from_stem(stem, index=idx),
            "channel_count": _coerce_channel_count(stem.get("channel_count")),
            "intent": intent,
            "notes": all_notes,
        }
        source_metadata = source_metadata_from_value(stem.get("source_metadata"))
        if source_metadata is not None:
            object_payload["source_metadata"] = source_metadata
        objects.append(object_payload)

    # Stable sort: stem_id then object_id
    objects.sort(key=lambda o: (o["stem_id"], o["object_id"]))

    # Default bed/field entry
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

    # Source block
    normalized_lock_hash = _coerce_str(lock_hash).strip() or None
    source: dict[str, Any] = {
        "stems_dir": stems_dir_posix,
        "created_from": _CREATED_FROM,
    }
    if normalized_lock_hash:
        source["lock_hash"] = normalized_lock_hash

    # Scene ID
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
