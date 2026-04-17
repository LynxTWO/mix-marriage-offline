from __future__ import annotations

import hashlib
import json
import math
import shutil
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Sequence

from mmo.core.downmix import (
    RENDERED_SIMILARITY_GATE_VERSION,
    compare_rendered_surround_to_stereo_reference,
    similarity_gate_score,
)
from mmo.core.lfe_derivation_profiles import (
    DEFAULT_LFE_DERIVATION_PROFILE_ID,
    get_lfe_derivation_profile,
)
from mmo.core.deliverables import (
    RENDER_RESULT_DOWNMIX_QA_FAILED,
    RENDER_RESULT_FALLBACK_APPLIED,
    RENDER_RESULT_SAFETY_COLLAPSE_APPLIED,
    RENDER_RESULT_SILENT_OUTPUT,
    build_output_render_result,
    canonical_warning_codes,
    is_effectively_silent_peak_linear,
)
from mmo.core.fallback_sequencer import run_fallback_sequence
from mmo.core.placement_policy import build_render_intent
from mmo.core.scene_builder import build_scene_from_bus_plan, build_scene_from_session
from mmo.core.source_locator import (
    resolve_session_stems,
    resolved_stem_path,
    stem_resolution_entries,
)
from mmo.core.trace_metadata import add_trace_metadata, build_trace_ixml_payload, build_trace_metadata
from mmo.dsp.buffer import AudioBufferF64, generic_channel_order
from mmo.dsp.decoders import (
    detect_format_from_path,
    is_lossless_format_id,
    iter_audio_float64_samples,
    read_audio_metadata,
)
from mmo.dsp.export_finalize import (
    StreamingExportFinalizer,
    build_export_finalization_receipt,
    derive_export_finalization_seed,
    resolve_dither_policy_for_bit_depth,
)
from mmo.dsp.io import sha256_file, write_wav_ixml_chunk
from mmo.dsp.lfe_derive import derive_missing_lfe
from mmo.dsp.process_context import build_process_context
from mmo.dsp.sample_rate import build_resampling_receipt, choose_target_rate_for_session
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1"
_SUPPORTED_LAYOUT_IDS: tuple[str, ...] = (
    "LAYOUT.2_0",
    "LAYOUT.32CH",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
    "LAYOUT.7_1_4",
    "LAYOUT.7_1_6",
    "LAYOUT.9_1_6",
)
_DEFAULT_SAMPLE_RATE_HZ = 48_000
_TARGET_PEAK_DBFS = -1.0
_RENDER_CHUNK_FRAMES = 4096
_RENDER_PASS_COUNT = 2
_FLOAT_MAX = math.nextafter(1.0, 0.0)
_SURROUND_CHANNEL_IDS: frozenset[str] = frozenset(
    {
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
        "SPK.LW",
        "SPK.RW",
    }
)
_OVERHEAD_CHANNEL_IDS: frozenset[str] = frozenset(
    {"SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR", "SPK.TFC", "SPK.TBC"}
)
_BED_DECORRELATED_CHANNEL_IDS: frozenset[str] = _SURROUND_CHANNEL_IDS | _OVERHEAD_CHANNEL_IDS
_LFE_SPEAKER_PREFIX = "SPK.LFE"
_LFE_L_SPEAKER = "SPK.L"
_LFE_R_SPEAKER = "SPK.R"
_BED_DECORRELATED_CONTENT_HINTS: frozenset[str] = frozenset(
    {"ambience", "pad_texture", "reverb_return", "crowd"}
)
_IMMERSIVE_WRAP_PERSPECTIVES: frozenset[str] = frozenset({"in_band", "in_orchestra"})
_SIDE_WRAP_CONFIDENCE_MIN = 0.8
_SIDE_WRAP_WIDE_GAIN_RATIO = 0.12
_BED_DECORRELATION_PLUGIN_ID = "decorrelated_bed_widening_v0"
_BED_DECORRELATION_MIN_DELAY_MS = 1.0
_BED_DECORRELATION_MAX_DELAY_MS = 40.0
_BED_DECORRELATION_DEFAULT_MIN_DELAY_MS = 3.0
_BED_DECORRELATION_DEFAULT_MAX_DELAY_MS = 12.0
_BED_DECORRELATION_DEFAULT_MIX = 0.32
_BED_DECORRELATION_DEFAULT_CONFIDENCE_THRESHOLD = 0.85
_BED_DECORRELATION_DEFAULT_SEED = 0
_BED_DECORRELATION_DEFAULT_QA_DISABLE_ON_FAIL = True
_BED_DECORRELATION_DEFAULT_QA_SURROUND_BACKOFF_DB = -3.0
_BED_DECORRELATION_MIN_BACKOFF_DB = -36.0
_BED_DECORRELATION_MAX_BACKOFF_DB = 0.0
_SIMILARITY_FALLBACK_SURROUND_STEP_DB = -3.0
_SIMILARITY_FALLBACK_HEIGHT_STEP_DB = -3.0
_SIMILARITY_FALLBACK_REAR_STEP_DB = -6.0
_SIMILARITY_FALLBACK_DECORRELATION_MIX_DELTA = 0.16
_SIMILARITY_FALLBACK_STOP_EPSILON = 0.01
_SIMILARITY_FALLBACK_STOP_STAGNATION_LIMIT = 6
_SIMILARITY_FALLBACK_MAX_STEPS = 6
_DEFAULT_SUBBUS_EXPORT_IDS: tuple[str, ...] = (
    "BUS.DRUMS",
    "BUS.BASS",
    "BUS.MUSIC",
    "BUS.VOX",
    "BUS.FX",
)
_SUBBUS_FILENAME_BY_ID: dict[str, str] = {
    "BUS.DRUMS": "drums",
    "BUS.BASS": "bass",
    "BUS.MUSIC": "music",
    "BUS.VOX": "vox",
    "BUS.FX": "fx",
}
_STEM_COPY_SUFFIX_BY_FORMAT: dict[str, str] = {
    "wav": "wav",
    "flac": "flac",
    "wv": "wv",
    "aiff": "aiff",
    "alac": "m4a",
}


@dataclass(frozen=True)
class _BedDecorrelatedQaConfig:
    disable_on_fail: bool
    surround_backoff_db: float


@dataclass(frozen=True)
class _BedDecorrelatedOptions:
    enabled: bool
    seed: int
    confidence_threshold: float
    mix: float
    min_delay_ms: float
    max_delay_ms: float
    qa: _BedDecorrelatedQaConfig


@dataclass(frozen=True)
class _BedDecorrelationTap:
    channel_index: int
    delay_samples: int
    polarity: float
    mix: float


@dataclass
class _BedDecorrelationDelayState:
    buffer: list[float]
    index: int = 0


@dataclass(frozen=True)
class _PreparedStem:
    stem_id: str
    source_path: Path
    source_format_id: str
    stem_channels: int
    source_sample_rate_hz: int
    render_sample_rate_hz: int
    gain_vector: tuple[float, ...]
    front_left_idx: int
    front_right_idx: int
    front_left_gain: float
    front_right_gain: float
    wide_left_idx: int | None
    wide_right_idx: int | None
    wide_wrap_left_gain: float
    wide_wrap_right_gain: float
    stereo_channel_wise: bool
    bed_decorrelation_taps: tuple[_BedDecorrelationTap, ...] = ()


@dataclass(frozen=True)
class _StemDecodePlan:
    stem_id: str
    source_path: Path
    source_format_id: str
    stem_channels: int
    source_sample_rate_hz: int
    gain_vector: tuple[float, ...]
    front_left_idx: int
    front_right_idx: int
    front_left_gain: float
    front_right_gain: float
    wide_left_idx: int | None
    wide_right_idx: int | None
    wide_wrap_left_gain: float
    wide_wrap_right_gain: float
    stereo_channel_wise: bool
    bed_decorrelation_candidate_channels: tuple[int, ...] = ()
    bed_decorrelation_seed: int | None = None
    bed_decorrelation_mix: float = 0.0


@dataclass
class _StemPassState:
    stem: _PreparedStem
    iterator: Iterator[list[float]]
    active: bool = True
    failed: bool = False
    produced_frames: int = 0
    bed_decorrelation_taps: dict[int, _BedDecorrelationTap] = field(default_factory=dict)
    bed_decorrelation_state: dict[int, _BedDecorrelationDelayState] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class _ExportOptions:
    export_stems: bool
    export_buses: bool
    export_master: bool
    export_layout_ids: tuple[str, ...]


@dataclass(frozen=True)
class _LayoutFallbackState:
    render_intent: dict[str, Any]
    bed_decorrelation_options: _BedDecorrelatedOptions
    enable_bed_decorrelation: bool
    layout_outputs: tuple[dict[str, Any], ...] = ()
    layout_notes: tuple[str, ...] = ()
    needs_rerender: bool = False
    safety_collapse_applied: bool = False


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str) and value.strip():
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _session_render_seed(session: Dict[str, Any]) -> int:
    candidates: list[Any] = [session.get("render_seed")]
    options = session.get("options")
    if isinstance(options, dict):
        candidates.append(options.get("render_seed"))
        export_cfg = options.get("export_finalization")
        if isinstance(export_cfg, dict):
            candidates.append(export_cfg.get("render_seed"))
    for candidate in candidates:
        value = _coerce_int(candidate)
        if value is not None:
            return value
    return 0


def _export_job_id(session: Dict[str, Any], *, artifact_id: str | None = None) -> str:
    base = _coerce_str(session.get("report_id")).strip() or _PLUGIN_ID
    suffix = _coerce_str(artifact_id).strip()
    if suffix:
        return f"{base}:{suffix}"
    return base


def _normalize_layout_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    normalized = {
        item.strip().upper()
        for item in value
        if isinstance(item, str) and item.strip()
    }
    if not normalized:
        return ()
    return tuple(
        layout_id
        for layout_id in _SUPPORTED_LAYOUT_IDS
        if layout_id in normalized
    )


def _clamp_float(
    value: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _default_bed_decorrelated_options() -> _BedDecorrelatedOptions:
    return _BedDecorrelatedOptions(
        enabled=False,
        seed=_BED_DECORRELATION_DEFAULT_SEED,
        confidence_threshold=_BED_DECORRELATION_DEFAULT_CONFIDENCE_THRESHOLD,
        mix=_BED_DECORRELATION_DEFAULT_MIX,
        min_delay_ms=_BED_DECORRELATION_DEFAULT_MIN_DELAY_MS,
        max_delay_ms=_BED_DECORRELATION_DEFAULT_MAX_DELAY_MS,
        qa=_BedDecorrelatedQaConfig(
            disable_on_fail=_BED_DECORRELATION_DEFAULT_QA_DISABLE_ON_FAIL,
            surround_backoff_db=_BED_DECORRELATION_DEFAULT_QA_SURROUND_BACKOFF_DB,
        ),
    )


def _resolve_bed_decorrelated_options(session: Dict[str, Any]) -> _BedDecorrelatedOptions:
    defaults = _default_bed_decorrelated_options()
    raw_export_options = session.get("render_export_options")
    if not isinstance(raw_export_options, dict):
        return defaults

    raw_config = raw_export_options.get("decorrelated_bed_widening")
    if isinstance(raw_config, bool):
        return _BedDecorrelatedOptions(
            enabled=raw_config,
            seed=defaults.seed,
            confidence_threshold=defaults.confidence_threshold,
            mix=defaults.mix,
            min_delay_ms=defaults.min_delay_ms,
            max_delay_ms=defaults.max_delay_ms,
            qa=defaults.qa,
        )
    if not isinstance(raw_config, dict):
        return defaults

    enabled_value = _coerce_bool(raw_config.get("enabled"))
    enabled = defaults.enabled if enabled_value is None else enabled_value

    seed_value = _coerce_int(raw_config.get("seed"))
    if seed_value is None:
        seed = defaults.seed
    else:
        seed = max(0, min(seed_value, 2_147_483_647))

    confidence_raw = _coerce_float(raw_config.get("confidence_threshold"))
    confidence_threshold = (
        defaults.confidence_threshold
        if confidence_raw is None
        else _clamp_float(confidence_raw, minimum=0.0, maximum=1.0)
    )

    mix_raw = _coerce_float(raw_config.get("mix"))
    mix = defaults.mix if mix_raw is None else _clamp_float(mix_raw, minimum=0.0, maximum=1.0)

    min_delay_raw = _coerce_float(raw_config.get("min_delay_ms"))
    max_delay_raw = _coerce_float(raw_config.get("max_delay_ms"))
    min_delay_ms = (
        defaults.min_delay_ms
        if min_delay_raw is None
        else _clamp_float(
            min_delay_raw,
            minimum=_BED_DECORRELATION_MIN_DELAY_MS,
            maximum=_BED_DECORRELATION_MAX_DELAY_MS,
        )
    )
    max_delay_ms = (
        defaults.max_delay_ms
        if max_delay_raw is None
        else _clamp_float(
            max_delay_raw,
            minimum=_BED_DECORRELATION_MIN_DELAY_MS,
            maximum=_BED_DECORRELATION_MAX_DELAY_MS,
        )
    )
    if max_delay_ms < min_delay_ms:
        min_delay_ms, max_delay_ms = max_delay_ms, min_delay_ms

    qa_disable_raw = _coerce_bool(raw_config.get("qa_disable_on_fail"))
    qa_disable_on_fail = (
        defaults.qa.disable_on_fail
        if qa_disable_raw is None
        else qa_disable_raw
    )
    qa_backoff_raw = _coerce_float(raw_config.get("qa_surround_backoff_db"))
    qa_surround_backoff_db = (
        defaults.qa.surround_backoff_db
        if qa_backoff_raw is None
        else _clamp_float(
            qa_backoff_raw,
            minimum=_BED_DECORRELATION_MIN_BACKOFF_DB,
            maximum=_BED_DECORRELATION_MAX_BACKOFF_DB,
        )
    )

    return _BedDecorrelatedOptions(
        enabled=enabled,
        seed=seed,
        confidence_threshold=confidence_threshold,
        mix=mix,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
        qa=_BedDecorrelatedQaConfig(
            disable_on_fail=qa_disable_on_fail,
            surround_backoff_db=qa_surround_backoff_db,
        ),
    )


def _stable_hash_u32(*parts: str) -> int:
    joined = "|".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big", signed=False)


def _stable_unit_value(*parts: str) -> float:
    return _stable_hash_u32(*parts) / float(0xFFFFFFFF)


def _resolve_export_options(session: Dict[str, Any]) -> _ExportOptions:
    defaults = _ExportOptions(
        export_stems=False,
        export_buses=False,
        export_master=True,
        export_layout_ids=(),
    )
    raw_options = session.get("render_export_options")
    if not isinstance(raw_options, dict):
        return defaults
    export_stems = _coerce_bool(raw_options.get("export_stems"))
    export_buses = _coerce_bool(raw_options.get("export_buses"))
    export_master = _coerce_bool(raw_options.get("export_master"))
    return _ExportOptions(
        export_stems=defaults.export_stems if export_stems is None else export_stems,
        export_buses=defaults.export_buses if export_buses is None else export_buses,
        export_master=defaults.export_master if export_master is None else export_master,
        export_layout_ids=_normalize_layout_ids(raw_options.get("export_layout_ids")),
    )


def _layout_relative_dir(
    *,
    output_dir: Path,
    layout_id: str,
) -> Path:
    layout_dir = _layout_slug(layout_id)
    if output_dir.name.casefold() == layout_dir.casefold():
        return Path()
    return Path(layout_dir)


def _master_output_relative_path(
    *,
    output_dir: Path,
    layout_id: str,
) -> Path:
    return _layout_relative_dir(output_dir=output_dir, layout_id=layout_id) / "master.wav"


def _bus_slug(bus_id: str) -> str:
    mapped = _SUBBUS_FILENAME_BY_ID.get(bus_id)
    if mapped:
        return mapped
    token = bus_id.strip().upper()
    if token.startswith("BUS."):
        token = token[4:]
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in token)
    cleaned = cleaned.strip("_").lower()
    return cleaned or "other"


def _identifier_token(value: str) -> str:
    token = "".join(
        ch if ch.isalnum() else "_"
        for ch in value.strip().upper()
    )
    token = token.strip("_")
    return token or "UNKNOWN"


def _bus_output_relative_path(
    *,
    output_dir: Path,
    layout_id: str,
    bus_id: str,
) -> Path:
    base_dir = _layout_relative_dir(output_dir=output_dir, layout_id=layout_id)
    return base_dir / "buses" / f"{_bus_slug(bus_id)}.wav"


def _scene_stem_reference_map(scene: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    refs: dict[str, dict[str, set[str]]] = {}
    objects = scene.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            stem_id = _coerce_str(obj.get("stem_id")).strip()
            if not stem_id:
                continue
            object_id = _coerce_str(obj.get("object_id")).strip()
            row = refs.setdefault(stem_id, {"objects": set(), "beds": set()})
            if object_id:
                row["objects"].add(object_id)
    beds = scene.get("beds")
    if isinstance(beds, list):
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            bed_id = _coerce_str(bed.get("bed_id")).strip()
            stem_ids = bed.get("stem_ids")
            if not isinstance(stem_ids, list):
                continue
            for raw_stem_id in stem_ids:
                stem_id = _coerce_str(raw_stem_id).strip()
                if not stem_id:
                    continue
                row = refs.setdefault(stem_id, {"objects": set(), "beds": set()})
                if bed_id:
                    row["beds"].add(bed_id)
    normalized: dict[str, dict[str, list[str]]] = {}
    for stem_id in sorted(refs.keys()):
        normalized[stem_id] = {
            "objects": sorted(refs[stem_id]["objects"]),
            "beds": sorted(refs[stem_id]["beds"]),
        }
    return normalized


def _stem_reference_summary(refs: dict[str, list[str]]) -> str:
    object_ids = refs.get("objects") if isinstance(refs, dict) else None
    bed_ids = refs.get("beds") if isinstance(refs, dict) else None
    parts: list[str] = []
    if isinstance(object_ids, list) and object_ids:
        parts.append("object:" + ",".join(object_ids))
    if isinstance(bed_ids, list) and bed_ids:
        parts.append("bed:" + ",".join(bed_ids))
    if not parts:
        return "scene_unmapped"
    return ";".join(parts)


def _selected_layout_ids(
    export_options: _ExportOptions,
) -> list[str]:
    if export_options.export_layout_ids:
        return list(export_options.export_layout_ids)
    return list(_SUPPORTED_LAYOUT_IDS)


def _infer_stem_copy_format(source_path: Path) -> str:
    format_id = detect_format_from_path(source_path)
    if format_id in _STEM_COPY_SUFFIX_BY_FORMAT:
        return format_id
    return ""


def _resolve_explicit_render_sample_rate_hz(
    session: Dict[str, Any],
    render_intent: dict[str, Any],
) -> tuple[int | None, str | None]:
    candidates: list[tuple[str, Any]] = [
        ("explicit_user_choice", session.get("render_sample_rate_hz")),
        ("explicit_export_target", render_intent.get("render_sample_rate_hz")),
        ("render_contract_target", session.get("sample_rate_hz")),
        ("render_contract_target", render_intent.get("sample_rate_hz")),
    ]
    options_payload = session.get("options")
    if isinstance(options_payload, dict):
        candidates.append(("explicit_user_choice", options_payload.get("render_sample_rate_hz")))

    for reason, candidate in candidates:
        value = _coerce_int(candidate)
        if value is not None and value > 0:
            return value, reason
    return None, None


def _resampling_warning_row(
    *,
    stem_id: str,
    warning: str,
    format_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stem_id": stem_id,
        "warning": warning,
    }
    if isinstance(format_id, str) and format_id.strip():
        row["format"] = format_id.strip().lower()
    if isinstance(detail, str) and detail.strip():
        row["detail"] = detail.strip()
    return row


def _db_to_linear(gain_db: float) -> float:
    return math.pow(10.0, gain_db / 20.0)


def _linear_to_db(gain: float) -> float:
    if gain <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(gain)


def _clamp_sample(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > _FLOAT_MAX:
        return _FLOAT_MAX
    return value


def _stem_rows(session: Dict[str, Any]) -> list[dict[str, Any]]:
    stems: list[dict[str, Any]] = []
    for row in resolve_session_stems(session):
        stems.append(row)
    stems.sort(
        key=lambda row: (
            _coerce_str(row.get("stem_id")),
            _coerce_str(row.get("file_path")),
        )
    )
    return stems


def _resolve_stem_source_path(
    stem: Dict[str, Any],
) -> tuple[Path | None, str | None]:
    source_path = resolved_stem_path(stem)
    if source_path is not None:
        return source_path, None
    return None, _coerce_str(stem.get("resolve_error_code")).strip() or None


def _layout_channel_order(layout_id: str) -> list[str]:
    try:
        process_ctx = build_process_context(layout_id)
    except ValueError:
        return []
    return list(process_ctx.channel_order)


def _layout_slug(layout_id: str) -> str:
    return layout_id.replace(".", "_")


def _received_recommendation_ids(
    recommendations: List[Recommendation],
) -> list[str]:
    ids: list[str] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        recommendation_id = _coerce_str(rec.get("recommendation_id")).strip()
        if recommendation_id:
            ids.append(recommendation_id)
    return sorted(set(ids))


def _build_scene(session: Dict[str, Any]) -> dict[str, Any] | None:
    explicit_scene = session.get("scene_payload")
    if isinstance(explicit_scene, dict):
        return _json_clone(explicit_scene)

    explicit_scene = session.get("scene")
    if isinstance(explicit_scene, dict):
        return _json_clone(explicit_scene)

    stems_map = session.get("stems_map")
    bus_plan = session.get("bus_plan")
    if isinstance(stems_map, dict) and isinstance(bus_plan, dict):
        try:
            return build_scene_from_bus_plan(stems_map, bus_plan)
        except ValueError:
            return None

    try:
        return build_scene_from_session(session)
    except (ValueError, TypeError):
        return None


def _gain_vector(
    *,
    stem_row: dict[str, Any],
    channel_order: list[str],
) -> list[float]:
    gains_payload = stem_row.get("gains")
    gains = gains_payload if isinstance(gains_payload, dict) else {}
    vector: list[float] = []
    for speaker_id in channel_order:
        gain = _coerce_float(gains.get(speaker_id))
        vector.append(gain if gain is not None else 0.0)
    return vector


def _positive_send_map(
    gains_payload: Any,
    *,
    allowed_channels: frozenset[str],
) -> dict[str, float]:
    gains = gains_payload if isinstance(gains_payload, dict) else {}
    rows: dict[str, float] = {}
    for speaker_id in sorted(gains.keys()):
        if speaker_id not in allowed_channels:
            continue
        gain = _coerce_float(gains.get(speaker_id))
        if gain is None or gain <= 0.0:
            continue
        rows[speaker_id] = round(gain, 6)
    return rows


def _speaker_index(channel_order: list[str]) -> dict[str, int]:
    return {
        speaker_id: index
        for index, speaker_id in enumerate(channel_order)
    }


def _front_safe_pair_indices(
    channel_order: list[str],
) -> tuple[int, int] | None:
    speaker_idx = _speaker_index(channel_order)
    front_left_idx = speaker_idx.get("SPK.L")
    front_right_idx = speaker_idx.get("SPK.R")
    if isinstance(front_left_idx, int) and isinstance(front_right_idx, int):
        return front_left_idx, front_right_idx
    if len(channel_order) >= 2:
        return 0, 1
    if len(channel_order) == 1:
        return 0, 0
    return None


def _perspective_from_notes(notes_payload: Any) -> str | None:
    notes = notes_payload if isinstance(notes_payload, list) else []
    for note in notes:
        if not isinstance(note, str):
            continue
        normalized = note.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized.startswith("immersive_perspective:"):
            continue
        perspective = normalized.split(":", 1)[1].strip()
        if perspective in _IMMERSIVE_WRAP_PERSPECTIVES:
            return perspective
    return None


def _bool_flag_from_notes(
    notes_payload: Any,
    *,
    key: str,
) -> bool | None:
    notes = notes_payload if isinstance(notes_payload, list) else []
    prefix = f"{key.strip().lower()}:"
    for note in notes:
        if not isinstance(note, str):
            continue
        normalized = note.strip().lower()
        if not normalized.startswith(prefix):
            continue
        value = normalized.split(":", 1)[1].strip()
        return _coerce_bool(value)
    return None


def _scene_stereo_reinterpret_allowed(scene: dict[str, Any]) -> bool:
    intent = scene.get("intent")
    if isinstance(intent, dict):
        explicit = _coerce_bool(intent.get("stereo_reinterpret_allowed"))
        if explicit is not None:
            return explicit
        from_notes = _bool_flag_from_notes(
            intent.get("notes"),
            key="stereo_reinterpret_allowed",
        )
        if from_notes is not None:
            return from_notes

    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        explicit = _coerce_bool(metadata.get("stereo_reinterpret_allowed"))
        if explicit is not None:
            return explicit
        from_notes = _bool_flag_from_notes(
            metadata.get("notes"),
            key="stereo_reinterpret_allowed",
        )
        if from_notes is not None:
            return from_notes

    return False


def _stereo_reinterpret_allowed_for_stem(
    *,
    stem_row: dict[str, Any],
    render_intent: dict[str, Any],
) -> bool:
    per_stem = _coerce_bool(stem_row.get("stereo_reinterpret_allowed"))
    if per_stem is not None:
        return per_stem

    from_intent = _coerce_bool(render_intent.get("stereo_reinterpret_allowed"))
    if from_intent is not None:
        return from_intent

    return False


def _stereo_side_wrap_allowed(
    *,
    stem_row: dict[str, Any],
    render_intent: dict[str, Any],
) -> bool:
    confidence = _coerce_float(stem_row.get("confidence")) or 0.0
    if confidence < _SIDE_WRAP_CONFIDENCE_MIN:
        return False

    policy_class = _coerce_str(stem_row.get("policy_class")).strip().upper()
    if policy_class.startswith("OBJECT.ANCHOR") or policy_class.startswith("OBJECT.LEAD"):
        return False

    perspective = _perspective_from_notes(stem_row.get("notes"))
    if perspective is None:
        perspective = _perspective_from_notes(render_intent.get("notes"))
    return perspective in _IMMERSIVE_WRAP_PERSPECTIVES


def _bed_content_hint_from_send_row(send_row: dict[str, Any]) -> str:
    notes_payload = send_row.get("notes")
    notes = notes_payload if isinstance(notes_payload, list) else []
    for note in notes:
        if not isinstance(note, str):
            continue
        normalized = note.strip().lower()
        if not normalized.startswith("content_hint:"):
            continue
        return normalized.split(":", 1)[1].strip()
    return ""


def _bed_decorrelation_candidate_channels(
    *,
    send_row: dict[str, Any],
    channel_order: list[str],
) -> tuple[int, ...]:
    gains_payload = send_row.get("gains")
    gains = gains_payload if isinstance(gains_payload, dict) else {}
    indices: list[int] = []
    for index, speaker_id in enumerate(channel_order):
        if speaker_id not in _BED_DECORRELATED_CHANNEL_IDS:
            continue
        gain = _coerce_float(gains.get(speaker_id))
        if gain is None or gain <= 0.0:
            continue
        indices.append(index)
    return tuple(sorted(set(indices)))


def _bed_decorrelation_eligible(
    *,
    send_row: dict[str, Any],
    channel_order: list[str],
    options: _BedDecorrelatedOptions,
) -> tuple[bool, tuple[int, ...]]:
    policy_class = _coerce_str(send_row.get("policy_class")).strip().upper()
    if not policy_class.startswith("BED."):
        return False, ()
    confidence = _coerce_float(send_row.get("confidence")) or 0.0
    if confidence < options.confidence_threshold:
        return False, ()
    content_hint = _bed_content_hint_from_send_row(send_row)
    if content_hint not in _BED_DECORRELATED_CONTENT_HINTS:
        return False, ()
    candidate_channels = _bed_decorrelation_candidate_channels(
        send_row=send_row,
        channel_order=channel_order,
    )
    return bool(candidate_channels), candidate_channels


def _build_bed_decorrelation_taps(
    *,
    stem_id: str,
    layout_id: str,
    sample_rate_hz: int,
    seed: int,
    mix: float,
    min_delay_ms: float,
    max_delay_ms: float,
    candidate_channels: tuple[int, ...],
) -> tuple[_BedDecorrelationTap, ...]:
    if sample_rate_hz <= 0 or mix <= 0.0 or not candidate_channels:
        return ()
    delay_span_ms = max(0.0, max_delay_ms - min_delay_ms)
    taps: list[_BedDecorrelationTap] = []
    for channel_index in candidate_channels:
        channel_token = str(channel_index)
        delay_unit = _stable_unit_value(
            str(seed),
            stem_id,
            layout_id,
            channel_token,
            "delay_ms",
        )
        delay_ms = min_delay_ms + (delay_span_ms * delay_unit)
        delay_samples = max(1, int(round((delay_ms / 1000.0) * float(sample_rate_hz))))
        polarity_hash = _stable_hash_u32(
            str(seed),
            stem_id,
            layout_id,
            channel_token,
            "polarity",
        )
        polarity = -1.0 if (polarity_hash & 0x1) else 1.0
        mix_unit = _stable_unit_value(
            str(seed),
            stem_id,
            layout_id,
            channel_token,
            "mix",
        )
        channel_mix = _clamp_float(mix * (0.85 + (0.3 * mix_unit)), minimum=0.0, maximum=1.0)
        taps.append(
            _BedDecorrelationTap(
                channel_index=channel_index,
                delay_samples=delay_samples,
                polarity=polarity,
                mix=channel_mix,
            )
        )
    taps.sort(key=lambda tap: tap.channel_index)
    return tuple(taps)


def _init_bed_decorrelation_state(
    taps: dict[int, _BedDecorrelationTap],
) -> dict[int, _BedDecorrelationDelayState]:
    state: dict[int, _BedDecorrelationDelayState] = {}
    for channel_index, tap in taps.items():
        state[channel_index] = _BedDecorrelationDelayState(
            buffer=[0.0] * tap.delay_samples,
            index=0,
        )
    return state


def _apply_bed_decorrelation(
    *,
    dry_sample: float,
    tap: _BedDecorrelationTap | None,
    delay_state: _BedDecorrelationDelayState | None,
) -> float:
    if tap is None or delay_state is None:
        return dry_sample
    if not delay_state.buffer:
        return dry_sample
    read_sample = delay_state.buffer[delay_state.index]
    delay_state.buffer[delay_state.index] = dry_sample
    delay_state.index = (delay_state.index + 1) % len(delay_state.buffer)
    wet_sample = read_sample * tap.polarity
    return (dry_sample * (1.0 - tap.mix)) + (wet_sample * tap.mix)


def _mix_stem_chunk_into_buffer(
    *,
    destination_chunk: AudioBufferF64,
    source_chunk: AudioBufferF64,
    state: _StemPassState,
) -> None:
    if destination_chunk.sample_rate_hz != source_chunk.sample_rate_hz:
        raise ValueError("source and destination buffers must share a sample rate")
    if destination_chunk.frame_count < source_chunk.frame_count:
        raise ValueError("destination chunk is smaller than source chunk")

    stem = state.stem
    source_index = 0
    for frame_index in range(source_chunk.frame_count):
        target_base = frame_index * destination_chunk.channels
        if stem.stem_channels == 1:
            mono = float(source_chunk.data[source_index])
            source_index += 1
            for channel_index, gain in enumerate(stem.gain_vector):
                if gain == 0.0:
                    continue
                decorrelation_tap = state.bed_decorrelation_taps.get(channel_index)
                decorrelation_state = state.bed_decorrelation_state.get(channel_index)
                sample = _apply_bed_decorrelation(
                    dry_sample=mono,
                    tap=decorrelation_tap,
                    delay_state=decorrelation_state,
                )
                destination_chunk.data[target_base + channel_index] += sample * gain
            continue

        if stem.stereo_channel_wise:
            left = float(source_chunk.data[source_index])
            right = float(source_chunk.data[source_index + 1])
            source_index += 2
            if stem.front_left_gain != 0.0:
                destination_chunk.data[target_base + stem.front_left_idx] += (
                    left * stem.front_left_gain
                )
            if stem.front_right_gain != 0.0:
                destination_chunk.data[target_base + stem.front_right_idx] += (
                    right * stem.front_right_gain
                )
            continue

        left = 0.0
        right = 0.0
        mono_sum = 0.0
        for source_channel_index in range(stem.stem_channels):
            sample = float(source_chunk.data[source_index])
            source_index += 1
            mono_sum += sample
            if source_channel_index == 0:
                left = sample
            elif source_channel_index == 1:
                right = sample

        mid = mono_sum / float(stem.stem_channels)
        side = 0.5 * (left - right)

        for channel_index, gain in enumerate(stem.gain_vector):
            if gain == 0.0:
                continue
            decorrelation_tap = state.bed_decorrelation_taps.get(channel_index)
            decorrelation_state = state.bed_decorrelation_state.get(channel_index)
            sample = _apply_bed_decorrelation(
                dry_sample=mid,
                tap=decorrelation_tap,
                delay_state=decorrelation_state,
            )
            destination_chunk.data[target_base + channel_index] += sample * gain

        if stem.front_left_gain != 0.0:
            destination_chunk.data[target_base + stem.front_left_idx] += (
                side * stem.front_left_gain
            )
        if stem.front_right_gain != 0.0:
            destination_chunk.data[target_base + stem.front_right_idx] -= (
                side * stem.front_right_gain
            )

        if stem.wide_wrap_left_gain != 0.0 and isinstance(stem.wide_left_idx, int):
            destination_chunk.data[target_base + stem.wide_left_idx] += (
                side * stem.wide_wrap_left_gain
            )
        if stem.wide_wrap_right_gain != 0.0 and isinstance(stem.wide_right_idx, int):
            destination_chunk.data[target_base + stem.wide_right_idx] -= (
                side * stem.wide_wrap_right_gain
            )


def _run_mix_pass(
    *,
    prepared_stems: list[_PreparedStem],
    channel_order: Sequence[str],
    sample_rate_hz: int,
    layout_id: str,
    on_chunk: Callable[[AudioBufferF64], None],
) -> tuple[int, int, list[str]]:
    normalized_channel_order = tuple(channel_order)
    channel_count = len(normalized_channel_order)
    states = [
        _StemPassState(
            stem=stem,
            iterator=iter_audio_float64_samples(
                stem.source_path,
                error_context="placement mixdown renderer",
                chunk_frames=_RENDER_CHUNK_FRAMES,
                metadata={
                    "channels": stem.stem_channels,
                    "sample_rate_hz": stem.source_sample_rate_hz,
                },
                target_sample_rate_hz=stem.render_sample_rate_hz,
            ),
            bed_decorrelation_taps={
                tap.channel_index: tap for tap in stem.bed_decorrelation_taps
            },
        )
        for stem in prepared_stems
    ]
    for state in states:
        if state.bed_decorrelation_taps:
            state.bed_decorrelation_state = _init_bed_decorrelation_state(
                state.bed_decorrelation_taps
            )
    notes: list[str] = []
    total_frames = 0

    while True:
        any_active = False
        mixed_chunk = AudioBufferF64(
            data=[0.0] * (_RENDER_CHUNK_FRAMES * channel_count),
            channels=channel_count,
            channel_order=normalized_channel_order,
            sample_rate_hz=sample_rate_hz,
        )
        mixed_frame_count = 0
        states_with_audio: list[_StemPassState] = []

        for state in states:
            if not state.active:
                continue
            any_active = True

            try:
                chunk = next(state.iterator)
            except StopIteration:
                state.active = False
                continue
            except Exception:
                state.active = False
                state.failed = True
                notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
                continue

            if not chunk:
                continue

            try:
                source_chunk = AudioBufferF64(
                    data=chunk,
                    channels=state.stem.stem_channels,
                    channel_order=generic_channel_order(state.stem.stem_channels),
                    sample_rate_hz=state.stem.render_sample_rate_hz,
                )
            except ValueError:
                state.active = False
                state.failed = True
                notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
                continue

            frame_count = source_chunk.frame_count
            if frame_count <= 0 or frame_count > _RENDER_CHUNK_FRAMES:
                state.active = False
                state.failed = True
                notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
                continue

            if frame_count > mixed_frame_count:
                mixed_frame_count = frame_count
            _mix_stem_chunk_into_buffer(
                destination_chunk=mixed_chunk,
                source_chunk=source_chunk,
                state=state,
            )
            states_with_audio.append(state)

        if mixed_frame_count > 0:
            on_chunk(mixed_chunk.slice_frames(0, mixed_frame_count))
            total_frames += mixed_frame_count
            for state in states_with_audio:
                if not state.failed:
                    state.produced_frames += mixed_frame_count

        if not any_active:
            break

    for state in states:
        if not state.failed and state.produced_frames <= 0:
            state.failed = True
            notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
    decoded_stems = sum(1 for state in states if not state.failed)
    return decoded_stems, total_frames, notes


def _prepare_layout_stems(
    *,
    session: Dict[str, Any],
    render_intent: dict[str, Any],
    layout_id: str,
    normalized_channel_order: list[str],
    sends_by_stem: dict[str, dict[str, Any]],
    bed_decorrelation_options: _BedDecorrelatedOptions,
    enable_bed_decorrelation: bool,
) -> tuple[
    list[_PreparedStem],
    int | None,
    dict[str, str],
    list[str],
    dict[str, Any],
    dict[str, Any],
]:
    notes: list[str] = []
    plugin_requested = bool(bed_decorrelation_options.enabled)
    plugin_enabled = bool(plugin_requested and enable_bed_decorrelation)
    empty_decorrelation_receipt = {
        "plugin_id": _BED_DECORRELATION_PLUGIN_ID,
        "requested": plugin_requested,
        "active": False,
        "active_stem_ids": [],
        "seed": int(bed_decorrelation_options.seed),
        "mix": round(float(bed_decorrelation_options.mix), 6),
        "confidence_threshold": round(float(bed_decorrelation_options.confidence_threshold), 6),
        "min_delay_ms": round(float(bed_decorrelation_options.min_delay_ms), 6),
        "max_delay_ms": round(float(bed_decorrelation_options.max_delay_ms), 6),
    }
    stems = _stem_rows(session)
    speaker_idx = _speaker_index(normalized_channel_order)
    front_pair = _front_safe_pair_indices(normalized_channel_order)
    if front_pair is None:
        return (
            [],
            None,
            {},
            [f"{layout_id}:missing_front_lr_channels"],
            {},
            empty_decorrelation_receipt,
        )
    front_left_idx, front_right_idx = front_pair
    if (
        "SPK.L" not in speaker_idx
        or "SPK.R" not in speaker_idx
    ):
        notes.append(
            f"{layout_id}:using_front_safe_pair:"
            f"{normalized_channel_order[front_left_idx]},"
            f"{normalized_channel_order[front_right_idx]}"
        )

    wide_left_idx = speaker_idx.get("SPK.LW")
    wide_right_idx = speaker_idx.get("SPK.RW")
    decode_plans: list[_StemDecodePlan] = []
    stem_mix_modes: dict[str, str] = {}
    stem_meta_rows: list[dict[str, Any]] = []

    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip() or "<unknown>"
        source_format_id = ""
        stem_warning_rows: list[dict[str, Any]] = []
        if "sample_rate_hz" in stem:
            declared_sample_rate_hz = _coerce_int(stem.get("sample_rate_hz"))
            if declared_sample_rate_hz is None or declared_sample_rate_hz < 1:
                stem_warning_rows.append(
                    _resampling_warning_row(
                        stem_id=stem_id,
                        warning="metadata_sample_rate_invalid",
                        detail=f"stem.sample_rate_hz={stem.get('sample_rate_hz')!r}",
                    )
                )
        source_path, resolve_reason = _resolve_stem_source_path(stem)
        if resolve_reason is not None or source_path is None:
            notes.append(f"{layout_id}:{stem_id}:{resolve_reason}")
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "decoder_warnings": stem_warning_rows,
                }
            )
            continue

        send_row = sends_by_stem.get(stem_id)
        if send_row is None:
            notes.append(f"{layout_id}:{stem_id}:missing_send_row")
            continue

        gain_vector = _gain_vector(stem_row=send_row, channel_order=normalized_channel_order)
        if not any(abs(gain) > 0.0 for gain in gain_vector):
            continue

        front_left_gain = gain_vector[front_left_idx]
        front_right_gain = gain_vector[front_right_idx]
        stereo_side_wrap_enabled = _stereo_side_wrap_allowed(
            stem_row=send_row,
            render_intent=render_intent,
        )
        wide_wrap_left_gain = (
            front_left_gain * _SIDE_WRAP_WIDE_GAIN_RATIO
            if stereo_side_wrap_enabled and isinstance(wide_left_idx, int)
            else 0.0
        )
        wide_wrap_right_gain = (
            front_right_gain * _SIDE_WRAP_WIDE_GAIN_RATIO
            if stereo_side_wrap_enabled and isinstance(wide_right_idx, int)
            else 0.0
        )
        bed_candidate_channels: tuple[int, ...] = ()
        bed_seed: int | None = None
        bed_mix = 0.0
        if plugin_enabled:
            eligible, candidate_channels = _bed_decorrelation_eligible(
                send_row=send_row,
                channel_order=normalized_channel_order,
                options=bed_decorrelation_options,
            )
            if eligible:
                bed_candidate_channels = candidate_channels
                bed_seed = _stable_hash_u32(
                    str(bed_decorrelation_options.seed),
                    layout_id,
                    stem_id,
                    _BED_DECORRELATION_PLUGIN_ID,
                )
                bed_mix = bed_decorrelation_options.mix

        source_format_id = detect_format_from_path(source_path)
        if source_format_id == "unknown":
            notes.append(f"{layout_id}:{stem_id}:unsupported_format")
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "decoder_warnings": stem_warning_rows,
                }
            )
            continue

        try:
            metadata: dict[str, Any] | None = None
            metadata_source = "decoder_metadata"
            try:
                metadata = read_audio_metadata(source_path)
            except Exception:
                stem_channels_hint = _coerce_int(stem.get("channel_count"))
                if stem_channels_hint is None:
                    stem_channels_hint = _coerce_int(stem.get("channels"))
                stem_sample_rate_hint = _coerce_int(stem.get("sample_rate_hz"))
                if (
                    stem_channels_hint is not None
                    and stem_channels_hint > 0
                    and stem_sample_rate_hint is not None
                    and stem_sample_rate_hint > 0
                ):
                    metadata = {
                        "channels": stem_channels_hint,
                        "sample_rate_hz": stem_sample_rate_hint,
                        "codec_name": stem.get("codec_name"),
                    }
                    metadata_source = "stem_hints"
                    stem_warning_rows.append(
                        _resampling_warning_row(
                            stem_id=stem_id,
                            warning="decoder_metadata_unavailable_used_stem_hints",
                            format_id=source_format_id,
                        )
                    )
                else:
                    stem_warning_rows.append(
                        _resampling_warning_row(
                            stem_id=stem_id,
                            warning="missing_metadata",
                            format_id=source_format_id,
                            detail="decoder metadata unavailable and no valid stem hints",
                        )
                    )
                    raise

            codec_name = _coerce_str(metadata.get("codec_name")).strip().lower()
            if not is_lossless_format_id(source_format_id, codec_name=codec_name):
                notes.append(f"{layout_id}:{stem_id}:lossy_input")
                stem_warning_rows.append(
                    _resampling_warning_row(
                        stem_id=stem_id,
                        warning="lossy_source",
                        format_id=source_format_id,
                    )
                )

            stem_channels = _coerce_int(metadata.get("channels"))
            stem_sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
            if stem_channels is None or stem_channels < 1:
                raise ValueError("invalid_channel_count")
            if stem_sample_rate_hz is None or stem_sample_rate_hz < 1:
                stem_warning_rows.append(
                    _resampling_warning_row(
                        stem_id=stem_id,
                        warning="missing_sample_rate_metadata",
                        format_id=source_format_id,
                    )
                )
                raise ValueError("invalid_sample_rate")
            if metadata_source == "decoder_metadata" and "sample_rate_hz" in stem:
                declared_sample_rate_hz = _coerce_int(stem.get("sample_rate_hz"))
                if declared_sample_rate_hz is None or declared_sample_rate_hz < 1:
                    stem_warning_rows.append(
                        _resampling_warning_row(
                            stem_id=stem_id,
                            warning="metadata_sample_rate_invalid_used_decoder_rate",
                            format_id=source_format_id,
                            detail=f"decoder_sample_rate_hz={stem_sample_rate_hz}",
                        )
                    )
                elif declared_sample_rate_hz != stem_sample_rate_hz:
                    stem_warning_rows.append(
                        _resampling_warning_row(
                            stem_id=stem_id,
                            warning="metadata_sample_rate_mismatch_used_decoder_rate",
                            format_id=source_format_id,
                            detail=(
                                f"stem.sample_rate_hz={declared_sample_rate_hz}, "
                                f"decoder_sample_rate_hz={stem_sample_rate_hz}"
                            ),
                        )
                    )
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "sample_rate_hz": stem_sample_rate_hz,
                    "sample_rate_source": metadata_source,
                    "decoder_warnings": stem_warning_rows,
                }
            )

            if stem_channels == 1:
                stem_mix_mode = "mono_by_policy_gains"
            elif stem_channels == 2 and layout_id == "LAYOUT.2_0":
                common_stereo_gain = 0.5 * (front_left_gain + front_right_gain)
                front_left_gain = common_stereo_gain
                front_right_gain = common_stereo_gain
                stem_mix_mode = "stereo_channel_wise_ratio_preserve"
            elif stem_channels == 2:
                stem_mix_mode = "stereo_mid_side_preserve"
            else:
                stem_mix_mode = "multichannel_mid_side_preserve"
            if stereo_side_wrap_enabled and (
                wide_wrap_left_gain > 0.0 or wide_wrap_right_gain > 0.0
            ):
                stem_mix_mode = f"{stem_mix_mode}_wide_wrap"
            stem_mix_modes[stem_id] = stem_mix_mode

            decode_plans.append(
                _StemDecodePlan(
                    stem_id=stem_id,
                    source_path=source_path,
                    source_format_id=source_format_id,
                    stem_channels=stem_channels,
                    source_sample_rate_hz=stem_sample_rate_hz,
                    gain_vector=tuple(gain_vector),
                    front_left_idx=front_left_idx,
                    front_right_idx=front_right_idx,
                    front_left_gain=front_left_gain,
                    front_right_gain=front_right_gain,
                    wide_left_idx=wide_left_idx,
                    wide_right_idx=wide_right_idx,
                    wide_wrap_left_gain=wide_wrap_left_gain,
                    wide_wrap_right_gain=wide_wrap_right_gain,
                    stereo_channel_wise=(stem_channels == 2 and layout_id == "LAYOUT.2_0"),
                    bed_decorrelation_candidate_channels=bed_candidate_channels,
                    bed_decorrelation_seed=bed_seed,
                    bed_decorrelation_mix=bed_mix,
                )
            )
        except Exception:
            notes.append(f"{layout_id}:{stem_id}:decode_failed")
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "decoder_warnings": stem_warning_rows,
                }
            )

    explicit_sample_rate_hz, explicit_sample_rate_reason = _resolve_explicit_render_sample_rate_hz(
        session,
        render_intent,
    )
    sample_rate_hz, selection_receipt = choose_target_rate_for_session(
        stem_meta_rows,
        explicit_rate=explicit_sample_rate_hz,
        explicit_rate_reason=explicit_sample_rate_reason,
        default=_DEFAULT_SAMPLE_RATE_HZ,
    )

    notes.append(
        f"{layout_id}:render_sample_rate_selected:{sample_rate_hz}:"
        f"{_coerce_str(selection_receipt.get('sample_rate_policy')).strip()}:"
        f"{_coerce_str(selection_receipt.get('sample_rate_policy_reason')).strip()}"
    )

    prepared_stems: list[_PreparedStem] = []
    resampled_stems: list[dict[str, Any]] = []
    native_rate_stems: list[dict[str, Any]] = []
    active_decorrelation_stem_ids: list[str] = []
    for plan in decode_plans:
        bed_taps: tuple[_BedDecorrelationTap, ...] = ()
        if (
            plugin_enabled
            and plan.bed_decorrelation_seed is not None
            and plan.bed_decorrelation_mix > 0.0
            and plan.bed_decorrelation_candidate_channels
        ):
            bed_taps = _build_bed_decorrelation_taps(
                stem_id=plan.stem_id,
                layout_id=layout_id,
                sample_rate_hz=sample_rate_hz,
                seed=plan.bed_decorrelation_seed,
                mix=plan.bed_decorrelation_mix,
                min_delay_ms=bed_decorrelation_options.min_delay_ms,
                max_delay_ms=bed_decorrelation_options.max_delay_ms,
                candidate_channels=plan.bed_decorrelation_candidate_channels,
            )
            if bed_taps:
                active_decorrelation_stem_ids.append(plan.stem_id)
        prepared_stems.append(
            _PreparedStem(
                stem_id=plan.stem_id,
                source_path=plan.source_path,
                source_format_id=plan.source_format_id,
                stem_channels=plan.stem_channels,
                source_sample_rate_hz=plan.source_sample_rate_hz,
                render_sample_rate_hz=sample_rate_hz,
                gain_vector=plan.gain_vector,
                front_left_idx=plan.front_left_idx,
                front_right_idx=plan.front_right_idx,
                front_left_gain=plan.front_left_gain,
                front_right_gain=plan.front_right_gain,
                wide_left_idx=plan.wide_left_idx,
                wide_right_idx=plan.wide_right_idx,
                wide_wrap_left_gain=plan.wide_wrap_left_gain,
                wide_wrap_right_gain=plan.wide_wrap_right_gain,
                stereo_channel_wise=plan.stereo_channel_wise,
                bed_decorrelation_taps=bed_taps,
            )
        )
        if plan.source_sample_rate_hz != sample_rate_hz:
            notes.append(
                f"{layout_id}:{plan.stem_id}:resampled"
                f"({plan.source_sample_rate_hz}->{sample_rate_hz})"
            )
            resampled_stems.append(
                {
                    "stem_id": plan.stem_id,
                    "from_sample_rate_hz": plan.source_sample_rate_hz,
                    "to_sample_rate_hz": sample_rate_hz,
                    "format": plan.source_format_id,
                }
            )
        else:
            native_rate_stems.append(
                {
                    "stem_id": plan.stem_id,
                    "sample_rate_hz": sample_rate_hz,
                    "format": plan.source_format_id,
                }
            )

    decorrelation_receipt = {
        "plugin_id": _BED_DECORRELATION_PLUGIN_ID,
        "requested": plugin_requested,
        "active": bool(active_decorrelation_stem_ids),
        "active_stem_ids": sorted(active_decorrelation_stem_ids),
        "seed": int(bed_decorrelation_options.seed),
        "mix": round(float(bed_decorrelation_options.mix), 6),
        "confidence_threshold": round(float(bed_decorrelation_options.confidence_threshold), 6),
        "min_delay_ms": round(float(bed_decorrelation_options.min_delay_ms), 6),
        "max_delay_ms": round(float(bed_decorrelation_options.max_delay_ms), 6),
    }

    return (
        prepared_stems,
        sample_rate_hz,
        stem_mix_modes,
        notes,
        build_resampling_receipt(
            selection=selection_receipt,
            output_sample_rate_hz=sample_rate_hz,
            input_stem_count=len(stems),
            planned_stem_count=len(decode_plans),
            decoded_stem_count=0,
            prepared_stem_count=len(prepared_stems),
            skipped_stem_count=max(0, len(stems) - len(decode_plans)),
            resampled_stems=resampled_stems,
            native_rate_stems=native_rate_stems,
            decoder_warnings=list(selection_receipt.get("decoder_warnings") or []),
            resample_stage="decode",
            resample_method_id="linear_interpolation_v1",
        ),
        decorrelation_receipt,
    )


def _update_chunk_peak_by_channel(
    *,
    peak_by_channel: list[float],
    mixed_chunk: AudioBufferF64,
) -> None:
    for channel_index, sample in enumerate(mixed_chunk.peak_per_channel()):
        if sample > peak_by_channel[channel_index]:
            peak_by_channel[channel_index] = sample


def _write_trimmed_chunk(
    *,
    handle: wave.Wave_write,
    mixed_chunk: AudioBufferF64,
    trim_linear: float,
    finalizer: StreamingExportFinalizer,
) -> None:
    trimmed_buffer = mixed_chunk.apply_gain_scalar(trim_linear)
    trimmed = [_clamp_sample(sample) for sample in trimmed_buffer.data]
    handle.writeframes(finalizer.finalize_chunk(trimmed))


def _lfe_channel_indices(channel_order: Sequence[str]) -> list[int]:
    """Return indices of LFE channels (prefix SPK.LFE) in channel_order."""
    return [
        idx
        for idx, ch_id in enumerate(channel_order)
        if ch_id.startswith(_LFE_SPEAKER_PREFIX)
    ]


def _resolve_lfe_profile(session: Dict[str, Any]) -> dict[str, Any]:
    """Resolve LFE derivation profile from session, falling back to the default."""
    profile_id = _coerce_str(session.get("lfe_derivation_profile_id")).strip()
    return get_lfe_derivation_profile(profile_id or None)


def _inject_lfe_into_chunk(
    chunk: AudioBufferF64,
    lfe_channels: list[list[float]],
    lfe_indices: list[int],
    frame_offset: int,
) -> AudioBufferF64:
    """Return a new chunk with LFE channel slots replaced from precomputed data."""
    new_data = list(chunk.data)
    n_channels = chunk.channels
    frame_count = chunk.frame_count
    for frame in range(frame_count):
        flat_src = frame_offset + frame
        for ch_pos, lfe_idx in enumerate(lfe_indices):
            if ch_pos >= len(lfe_channels):
                break
            lfe_ch = lfe_channels[ch_pos]
            new_data[frame * n_channels + lfe_idx] = (
                lfe_ch[flat_src] if flat_src < len(lfe_ch) else 0.0
            )
    return AudioBufferF64(
        data=new_data,
        channels=chunk.channels,
        channel_order=chunk.channel_order,
        sample_rate_hz=chunk.sample_rate_hz,
    )


def _render_subbus_output(
    *,
    session: Dict[str, Any],
    scene: dict[str, Any],
    layout_id: str,
    output_dir: Path,
    bus_id: str,
    prepared_stems: list[_PreparedStem],
    trim_linear: float,
    sample_rate_hz: int,
    channel_order: Sequence[str],
    bus_trim_db: float,
    stem_scene_refs: dict[str, dict[str, list[str]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    if not prepared_stems:
        return None, []
    channel_count = len(tuple(channel_order))
    rel_path = _bus_output_relative_path(
        output_dir=output_dir,
        layout_id=layout_id,
        bus_id=bus_id,
    )
    abs_path = output_dir / rel_path
    if abs_path.exists():
        return None, [f"{layout_id}:{bus_id}:skipped_existing_output:{rel_path.as_posix()}"]

    notes: list[str] = []
    bit_depth = 24
    dither_policy = resolve_dither_policy_for_bit_depth(bit_depth)
    render_seed = _session_render_seed(session)
    export_job_id = _export_job_id(session, artifact_id=bus_id)
    export_seed = derive_export_finalization_seed(
        job_id=export_job_id,
        layout_id=layout_id,
        render_seed=render_seed,
    )
    finalizer = StreamingExportFinalizer(
        channels=channel_count,
        bit_depth=bit_depth,
        dither_policy=dither_policy,
        seed=export_seed,
    )
    trace_context = {
        "session": session,
        "scene_payload": scene,
        "layout_id": layout_id,
        "render_seed": render_seed,
    }
    trace_metadata = build_trace_metadata(trace_context)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    pass_frames = 0
    with wave.open(str(abs_path), "wb") as handle:
        handle.setnchannels(channel_count)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)
        _, pass_frames, pass_notes = _run_mix_pass(
            prepared_stems=prepared_stems,
            channel_order=channel_order,
            sample_rate_hz=sample_rate_hz,
            layout_id=layout_id,
            on_chunk=lambda chunk: _write_trimmed_chunk(
                handle=handle,
                mixed_chunk=chunk,
                trim_linear=trim_linear,
                finalizer=finalizer,
            ),
        )
        if pass_notes:
            notes.extend(pass_notes)
    write_wav_ixml_chunk(abs_path, build_trace_ixml_payload(trace_metadata))

    output_sha = sha256_file(abs_path)
    stem_ids = sorted(stem.stem_id for stem in prepared_stems)
    scene_bindings = {
        stem_id: _stem_reference_summary(stem_scene_refs.get(stem_id, {}))
        for stem_id in stem_ids
    }
    output_row: dict[str, Any] = {
        "output_id": (
            "OUTPUT.PLACEMENT_SUBBUS."
            f"{_layout_slug(layout_id)}."
            f"{_identifier_token(bus_id)}."
            f"{output_sha[:12]}"
        ),
        "file_path": rel_path.as_posix(),
        "layout_id": layout_id,
        "target_bus_id": bus_id,
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": bit_depth,
        "channel_count": channel_count,
        "sha256": output_sha,
        "notes": (
            "scene_subbus_export "
            f"trim_linear_from_master={trim_linear:.6f}"
        ),
        "export_finalization_receipt": build_export_finalization_receipt(
            bit_depth=bit_depth,
            dither_policy=dither_policy,
            job_id=export_job_id,
            layout_id=layout_id,
            render_seed=render_seed,
            target_peak_dbfs=_TARGET_PEAK_DBFS,
        ),
        "metadata": {
            "artifact_role": "subbus",
            "main_bus_id": "BUS.MAIN",
            "bus_trim_db": bus_trim_db,
            "source_stem_ids": stem_ids,
            "scene_bindings": scene_bindings,
        },
    }
    output_row["metadata"] = add_trace_metadata(output_row.get("metadata"), trace_context)
    if notes:
        output_row["metadata"]["warnings"] = sorted(set(notes))
    return output_row, []


def _export_subbus_outputs(
    *,
    session: Dict[str, Any],
    scene: dict[str, Any],
    layout_id: str,
    output_dir: Path,
    prepared_stems: list[_PreparedStem],
    sends_by_stem: dict[str, dict[str, Any]],
    trim_linear: float,
    sample_rate_hz: int,
    channel_order: Sequence[str],
    render_intent: dict[str, Any],
    stem_scene_refs: dict[str, dict[str, list[str]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    stem_bus_by_id: dict[str, str] = {}
    for stem in prepared_stems:
        send_row = sends_by_stem.get(stem.stem_id)
        bus_id = (
            _coerce_str(send_row.get("group_bus")).strip().upper()
            if isinstance(send_row, dict)
            else ""
        ) or "BUS.OTHER"
        stem_bus_by_id[stem.stem_id] = bus_id

    stems_by_bus: dict[str, list[_PreparedStem]] = {}
    for stem in prepared_stems:
        bus_id = stem_bus_by_id.get(stem.stem_id, "BUS.OTHER")
        stems_by_bus.setdefault(bus_id, []).append(stem)

    bus_gain_staging = render_intent.get("bus_gain_staging")
    group_trims = (
        bus_gain_staging.get("group_trims_db")
        if isinstance(bus_gain_staging, dict)
        else None
    )

    outputs: list[dict[str, Any]] = []
    notes: list[str] = []
    for bus_id in _DEFAULT_SUBBUS_EXPORT_IDS:
        bus_stems = stems_by_bus.get(bus_id) or []
        if not bus_stems:
            continue
        bus_trim_db = _coerce_float(group_trims.get(bus_id)) if isinstance(group_trims, dict) else None
        output_row, output_notes = _render_subbus_output(
            session=session,
            scene=scene,
            layout_id=layout_id,
            output_dir=output_dir,
            bus_id=bus_id,
            prepared_stems=bus_stems,
            trim_linear=trim_linear,
            sample_rate_hz=sample_rate_hz,
            channel_order=channel_order,
            bus_trim_db=bus_trim_db if bus_trim_db is not None else 0.0,
            stem_scene_refs=stem_scene_refs,
        )
        if output_notes:
            notes.extend(output_notes)
        if isinstance(output_row, dict):
            outputs.append(output_row)
    return outputs, notes


def _export_stem_copy_outputs(
    *,
    session: Dict[str, Any],
    output_dir: Path,
    stem_bus_by_id: dict[str, str],
    stem_scene_refs: dict[str, dict[str, list[str]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    stems = _stem_rows(session)
    outputs: list[dict[str, Any]] = []
    notes: list[str] = []
    seen_stem_ids: set[str] = set()
    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip()
        if not stem_id or stem_id in seen_stem_ids:
            continue
        seen_stem_ids.add(stem_id)
        source_path, resolve_reason = _resolve_stem_source_path(stem)
        if resolve_reason is not None or source_path is None:
            notes.append(f"stems:{stem_id}:{resolve_reason or 'unresolved_path'}")
            continue
        if not source_path.exists():
            notes.append(f"stems:{stem_id}:missing_source_file")
            continue

        source_format = _infer_stem_copy_format(source_path)
        if not source_format:
            notes.append(f"stems:{stem_id}:unsupported_copy_format")
            continue
        suffix = _STEM_COPY_SUFFIX_BY_FORMAT[source_format]
        rel_path = Path("stems") / f"{stem_id}.{suffix}"
        abs_path = output_dir / rel_path
        if abs_path.exists():
            notes.append(f"stems:{stem_id}:skipped_existing_output:{rel_path.as_posix()}")
            continue

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source_path, abs_path)
        except OSError:
            notes.append(f"stems:{stem_id}:copy_failed")
            continue

        output_sha = sha256_file(abs_path)
        metadata_payload: dict[str, Any] = {
            "artifact_role": "stem_copy",
            "main_bus_id": "BUS.MAIN",
            "subbus_id": stem_bus_by_id.get(stem_id, "BUS.OTHER"),
            "scene_binding": _stem_reference_summary(stem_scene_refs.get(stem_id, {})),
            "source_path": source_path.as_posix(),
        }

        channel_count = _coerce_int(stem.get("channel_count"))
        sample_rate_hz = _coerce_int(stem.get("sample_rate_hz"))
        try:
            source_meta = read_audio_metadata(source_path)
        except Exception:
            source_meta = {}
        if channel_count is None:
            channel_count = _coerce_int(source_meta.get("channels"))
        if sample_rate_hz is None:
            sample_rate_hz = _coerce_int(source_meta.get("sample_rate_hz"))

        output_row: dict[str, Any] = {
            "output_id": f"OUTPUT.PLACEMENT_STEM_COPY.{_identifier_token(stem_id)}.{output_sha[:12]}",
            "file_path": rel_path.as_posix(),
            "target_stem_id": stem_id,
            "target_bus_id": stem_bus_by_id.get(stem_id, "BUS.OTHER"),
            "format": source_format,
            "sha256": output_sha,
            "notes": "scene_stem_copy_export",
            "metadata": metadata_payload,
        }
        if isinstance(channel_count, int) and channel_count > 0:
            output_row["channel_count"] = channel_count
        if isinstance(sample_rate_hz, int) and sample_rate_hz > 0:
            output_row["sample_rate_hz"] = sample_rate_hz
        outputs.append(output_row)

    outputs.sort(
        key=lambda row: (
            _coerce_str(row.get("target_stem_id")),
            _coerce_str(row.get("file_path")),
        )
    )
    return outputs, notes


def _mix_layout_from_intent(
    *,
    session: Dict[str, Any],
    scene: dict[str, Any],
    render_intent: dict[str, Any],
    layout_id: str,
    output_dir: Path,
    export_options: _ExportOptions,
    stem_scene_refs: dict[str, dict[str, list[str]]],
    bed_decorrelation_options: _BedDecorrelatedOptions,
    enable_bed_decorrelation: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    channel_order = render_intent.get("channel_order")
    if not isinstance(channel_order, list) or not channel_order:
        return [], [f"{layout_id}:missing_channel_order"]

    normalized_channel_order = [
        speaker_id
        for speaker_id in channel_order
        if isinstance(speaker_id, str) and speaker_id
    ]
    if not normalized_channel_order:
        return [], [f"{layout_id}:invalid_channel_order"]

    lfe_indices = _lfe_channel_indices(normalized_channel_order)
    lfe_l_idx = next(
        (idx for idx, ch in enumerate(normalized_channel_order) if ch == _LFE_L_SPEAKER),
        None,
    )
    lfe_r_idx = next(
        (idx for idx, ch in enumerate(normalized_channel_order) if ch == _LFE_R_SPEAKER),
        None,
    )
    derive_lfe = bool(lfe_indices and lfe_l_idx is not None and lfe_r_idx is not None)

    stem_sends = render_intent.get("stem_sends")
    stem_send_rows = stem_sends if isinstance(stem_sends, list) else []
    sends_by_stem: dict[str, dict[str, Any]] = {}
    for row in stem_send_rows:
        if not isinstance(row, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        if not stem_id or stem_id in sends_by_stem:
            continue
        sends_by_stem[stem_id] = row

    channel_count = len(normalized_channel_order)
    (
        prepared_stems,
        sample_rate_hz,
        stem_mix_modes,
        prep_notes,
        resampling_receipt,
        decorrelation_receipt,
    ) = _prepare_layout_stems(
        session=session,
        render_intent=render_intent,
        layout_id=layout_id,
        normalized_channel_order=normalized_channel_order,
        sends_by_stem=sends_by_stem,
        bed_decorrelation_options=bed_decorrelation_options,
        enable_bed_decorrelation=enable_bed_decorrelation,
    )
    if prep_notes:
        notes.extend(prep_notes)

    if sample_rate_hz is None:
        sample_rate_hz = _DEFAULT_SAMPLE_RATE_HZ
        if isinstance(resampling_receipt, dict):
            resampling_receipt = dict(resampling_receipt)
            resampling_receipt.setdefault("target_sample_rate_hz", sample_rate_hz)
    peak_by_channel = [0.0] * channel_count
    lfe_l_acc: list[float] = []
    lfe_r_acc: list[float] = []

    def _on_pass1_chunk(chunk: AudioBufferF64) -> None:
        _update_chunk_peak_by_channel(peak_by_channel=peak_by_channel, mixed_chunk=chunk)
        if derive_lfe:
            n_ch = chunk.channels
            for frame_idx in range(chunk.frame_count):
                lfe_l_acc.append(chunk.data[frame_idx * n_ch + lfe_l_idx])
                lfe_r_acc.append(chunk.data[frame_idx * n_ch + lfe_r_idx])

    decoded_stems, pass1_frames, pass1_notes = _run_mix_pass(
        prepared_stems=prepared_stems,
        channel_order=normalized_channel_order,
        sample_rate_hz=sample_rate_hz,
        layout_id=layout_id,
        on_chunk=_on_pass1_chunk,
    )
    if pass1_notes:
        notes.extend(pass1_notes)
    if isinstance(resampling_receipt, dict):
        counts = resampling_receipt.get("counts")
        if isinstance(counts, dict):
            counts["decoded_stem_count"] = decoded_stems

    rendered_audio = pass1_frames > 0
    if not rendered_audio:
        notes.append(f"{layout_id}:rendered_silence:no_decodable_stems")

    # ── LFE derivation (runs after pass 1, before trim calculation) ───────
    lfe_derived_channels: list[list[float]] = []
    lfe_derivation_receipt: dict[str, Any] = {}
    if derive_lfe and lfe_l_acc:
        try:
            lfe_profile = _resolve_lfe_profile(session)
            lfe_derived_channels, lfe_derivation_receipt = derive_missing_lfe(
                left=lfe_l_acc,
                right=lfe_r_acc,
                sample_rate_hz=sample_rate_hz,
                target_lfe_channel_count=len(lfe_indices),
                profile=lfe_profile,
            )
            # Update peak_by_channel with actual LFE peaks so trim accounts for them.
            for ch_pos, lfe_idx in enumerate(lfe_indices):
                if ch_pos < len(lfe_derived_channels):
                    lfe_ch = lfe_derived_channels[ch_pos]
                    lfe_peak = max((abs(s) for s in lfe_ch), default=0.0)
                    if lfe_peak > peak_by_channel[lfe_idx]:
                        peak_by_channel[lfe_idx] = lfe_peak
        except Exception as exc:
            notes.append(f"{layout_id}:lfe_derivation_failed")
            lfe_derivation_receipt = {"status": "error", "error": str(exc)[:200]}

    pre_trim_peak = max(peak_by_channel) if peak_by_channel else 0.0
    target_peak_linear = _db_to_linear(_TARGET_PEAK_DBFS)
    if pre_trim_peak <= 0.0:
        trim_linear = 1.0
    else:
        trim_linear = min(1.0, target_peak_linear / pre_trim_peak)
    trim_db = _linear_to_db(trim_linear)
    rendered_peak_linear = pre_trim_peak * trim_linear if rendered_audio else 0.0
    render_warning_codes = canonical_warning_codes(notes)
    if rendered_audio and is_effectively_silent_peak_linear(rendered_peak_linear):
        render_warning_codes = canonical_warning_codes(
            render_warning_codes,
            [RENDER_RESULT_SILENT_OUTPUT],
        )

    layout_slug = _layout_slug(layout_id)
    stereo_reinterpret_allowed = bool(
        _coerce_bool(render_intent.get("stereo_reinterpret_allowed"))
    )

    stem_send_summary = []
    for row in stem_send_rows:
        if not isinstance(row, dict):
            continue
        summary_stem_id = _coerce_str(row.get("stem_id"))
        mix_mode = stem_mix_modes.get(summary_stem_id, "skipped")
        stem_send_summary.append(
            {
                "stem_id": summary_stem_id,
                "policy_class": _coerce_str(row.get("policy_class")),
                "mix_mode": mix_mode,
                "stereo_reinterpret_allowed": _stereo_reinterpret_allowed_for_stem(
                    stem_row=row,
                    render_intent=render_intent,
                ),
                "nonzero_channels": list(row.get("nonzero_channels") or []),
                "surround_sends": _positive_send_map(
                    row.get("gains"),
                    allowed_channels=_SURROUND_CHANNEL_IDS,
                ),
                "overhead_sends": _positive_send_map(
                    row.get("gains"),
                    allowed_channels=_OVERHEAD_CHANNEL_IDS,
                ),
                "notes": list(row.get("notes") or []),
                "why": list(row.get("notes") or []),
            }
        )

    outputs: list[dict[str, Any]] = []
    master_rel_path = _master_output_relative_path(output_dir=output_dir, layout_id=layout_id)
    master_abs_path = output_dir / master_rel_path
    if export_options.export_master:
        if master_abs_path.exists():
            notes.append(f"{layout_id}:skipped_existing_output:{master_rel_path.as_posix()}")
        else:
            bit_depth = 24
            dither_policy = resolve_dither_policy_for_bit_depth(bit_depth)
            render_seed = _session_render_seed(session)
            export_job_id = _export_job_id(session, artifact_id="master")
            export_seed = derive_export_finalization_seed(
                job_id=export_job_id,
                layout_id=layout_id,
                render_seed=render_seed,
            )
            finalizer = StreamingExportFinalizer(
                channels=channel_count,
                bit_depth=bit_depth,
                dither_policy=dither_policy,
                seed=export_seed,
            )
            master_abs_path.parent.mkdir(parents=True, exist_ok=True)
            pass2_frames = 0
            with wave.open(str(master_abs_path), "wb") as handle:
                handle.setnchannels(channel_count)
                handle.setsampwidth(bit_depth // 8)
                handle.setframerate(sample_rate_hz)

                if rendered_audio:
                    lfe_frame_cursor: list[int] = [0]

                    if lfe_derived_channels:
                        def _write_chunk_with_lfe(chunk: AudioBufferF64) -> None:
                            injected = _inject_lfe_into_chunk(
                                chunk,
                                lfe_channels=lfe_derived_channels,
                                lfe_indices=lfe_indices,
                                frame_offset=lfe_frame_cursor[0],
                            )
                            lfe_frame_cursor[0] += injected.frame_count
                            _write_trimmed_chunk(
                                handle=handle,
                                mixed_chunk=injected,
                                trim_linear=trim_linear,
                                finalizer=finalizer,
                            )
                        pass2_callback: Callable[[AudioBufferF64], None] = (
                            _write_chunk_with_lfe
                        )
                    else:
                        pass2_callback = lambda chunk: _write_trimmed_chunk(
                            handle=handle,
                            mixed_chunk=chunk,
                            trim_linear=trim_linear,
                            finalizer=finalizer,
                        )

                    _, pass2_frames, pass2_notes = _run_mix_pass(
                        prepared_stems=prepared_stems,
                        channel_order=normalized_channel_order,
                        sample_rate_hz=sample_rate_hz,
                        layout_id=layout_id,
                        on_chunk=pass2_callback,
                    )
                    if pass2_notes:
                        notes.extend(pass2_notes)
            trace_context = {
                "session": session,
                "scene_payload": scene,
                "layout_id": layout_id,
                "render_seed": render_seed,
            }
            write_wav_ixml_chunk(
                master_abs_path,
                build_trace_ixml_payload(build_trace_metadata(trace_context)),
            )

            output_sha = sha256_file(master_abs_path)
            outputs.append(
                {
                    "output_id": f"OUTPUT.PLACEMENT_MIXDOWN.{layout_slug}.{output_sha[:12]}",
                    "file_path": master_rel_path.as_posix(),
                    "layout_id": layout_id,
                    "format": "wav",
                    "sample_rate_hz": sample_rate_hz,
                    "bit_depth": bit_depth,
                    "channel_count": channel_count,
                    "sha256": output_sha,
                    "notes": (
                        "scene_placement_mixdown stereo_imaging_preserved"
                        f" trim_db={trim_db:.4f}"
                    ),
                    "export_finalization_receipt": build_export_finalization_receipt(
                        bit_depth=bit_depth,
                        dither_policy=dither_policy,
                        job_id=export_job_id,
                        layout_id=layout_id,
                        render_seed=render_seed,
                        target_peak_dbfs=_TARGET_PEAK_DBFS,
                    ),
                    "metadata": {
                        "artifact_role": "master",
                        "applied_policy_id": _coerce_str(render_intent.get("policy_id")),
                        "channel_order": list(normalized_channel_order),
                        "trim_db": trim_db,
                        "trim_linear": trim_linear,
                        "target_peak_dbfs": _TARGET_PEAK_DBFS,
                        "pre_trim_peak": pre_trim_peak,
                        "decoded_stem_count": decoded_stems,
                        "render_strategy": "two_pass_streaming",
                        "render_passes": _RENDER_PASS_COUNT,
                        "chunk_frames": _RENDER_CHUNK_FRAMES,
                        "stereo_reinterpret_allowed": stereo_reinterpret_allowed,
                        "resampling": resampling_receipt,
                        "lfe_derivation": lfe_derivation_receipt or None,
                        "bed_decorrelated_widening": dict(decorrelation_receipt),
                        "render_result": build_output_render_result(
                            artifact_role="master",
                            planned_stem_count=_coerce_int(
                                resampling_receipt.get("counts", {}).get("planned_stem_count")
                                if isinstance(resampling_receipt, dict)
                                else None
                            ),
                            decoded_stem_count=decoded_stems,
                            prepared_stem_count=len(prepared_stems),
                            skipped_stem_count=_coerce_int(
                                resampling_receipt.get("counts", {}).get("skipped_stem_count")
                                if isinstance(resampling_receipt, dict)
                                else None
                            ),
                            rendered_frame_count=pass2_frames,
                            duration_seconds=(
                                pass2_frames / sample_rate_hz
                                if sample_rate_hz > 0
                                else None
                            ),
                            warning_codes=render_warning_codes,
                            target_layout_id=layout_id,
                        ),
                        "what_why": (
                            "Rendered one layout-agnostic scene into layout speakers using "
                            "conservative placement sends; stereo stems keep L/R imaging in "
                            "stereo outputs and mid/side handling in multichannel outputs."
                        ),
                        "stem_send_summary": stem_send_summary,
                    },
                }
            )
            outputs[-1]["metadata"] = add_trace_metadata(
                outputs[-1].get("metadata"),
                trace_context,
            )

    if export_options.export_buses:
        bus_outputs, bus_notes = _export_subbus_outputs(
            session=session,
            scene=scene,
            layout_id=layout_id,
            output_dir=output_dir,
            prepared_stems=prepared_stems,
            sends_by_stem=sends_by_stem,
            trim_linear=trim_linear,
            sample_rate_hz=sample_rate_hz,
            channel_order=normalized_channel_order,
            render_intent=render_intent,
            stem_scene_refs=stem_scene_refs,
        )
        outputs.extend(bus_outputs)
        if bus_notes:
            notes.extend(bus_notes)

    if notes:
        for output_row in outputs:
            metadata = output_row.get("metadata")
            if isinstance(metadata, dict):
                metadata["warnings"] = sorted(set(notes))
    return outputs, notes


def _master_output_row_for_layout(
    *,
    layout_outputs: list[dict[str, Any]],
    layout_id: str,
) -> dict[str, Any] | None:
    for row in layout_outputs:
        if not isinstance(row, dict):
            continue
        if _coerce_str(row.get("layout_id")).strip() != layout_id:
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if _coerce_str(metadata.get("artifact_role")).strip().lower() != "master":
            continue
        return row
    return None


def _master_output_path(
    *,
    output_dir: Path,
    output_row: dict[str, Any] | None,
) -> Path | None:
    if not isinstance(output_row, dict):
        return None
    file_path = _coerce_str(output_row.get("file_path")).strip()
    if not file_path:
        return None
    return (output_dir / Path(file_path)).resolve()


def _remove_layout_output_files(
    *,
    output_dir: Path,
    layout_outputs: list[dict[str, Any]],
) -> None:
    for row in layout_outputs:
        if not isinstance(row, dict):
            continue
        file_path = _coerce_str(row.get("file_path")).strip()
        if not file_path:
            continue
        abs_path = (output_dir / Path(file_path)).resolve()
        try:
            if abs_path.exists() and abs_path.is_file():
                abs_path.unlink()
        except OSError:
            continue


def _bed_decorrelated_metadata(output_row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(output_row, dict):
        return None
    metadata = output_row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    plugin_meta = metadata.get("bed_decorrelated_widening")
    if isinstance(plugin_meta, dict):
        return plugin_meta
    payload = {
        "plugin_id": _BED_DECORRELATION_PLUGIN_ID,
        "requested": False,
        "active": False,
        "active_stem_ids": [],
    }
    metadata["bed_decorrelated_widening"] = payload
    return payload


def _round_fallback_gain(value: float) -> float:
    if value <= 0.0:
        return 0.0
    return round(float(value), 6)


def _send_row_notes(row: dict[str, Any]) -> list[str]:
    notes = row.get("notes")
    if not isinstance(notes, list):
        return []
    return [
        _coerce_str(item).strip()
        for item in notes
        if _coerce_str(item).strip()
    ]


def _send_row_is_bed(row: dict[str, Any]) -> bool:
    return "source_kind:bed" in set(_send_row_notes(row))


def _refresh_nonzero_channels(row: dict[str, Any], *, channel_order: list[str]) -> None:
    gains = row.get("gains")
    if not isinstance(gains, dict):
        row["nonzero_channels"] = []
        return
    row["nonzero_channels"] = [
        speaker_id
        for speaker_id in channel_order
        if _coerce_float(gains.get(speaker_id)) not in (None, 0.0)
    ]


def _step_scale_render_intent_gains(
    state: _LayoutFallbackState,
    *,
    speaker_ids: frozenset[str],
    gain_db: float,
    change_kind: str,
    row_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[_LayoutFallbackState, list[dict[str, Any]]]:
    render_intent = _json_clone(state.render_intent)
    channel_order = render_intent.get("channel_order")
    if not isinstance(channel_order, list):
        return state, []
    stem_rows = render_intent.get("stem_sends")
    if not isinstance(stem_rows, list):
        return state, []

    linear = _db_to_linear(gain_db)
    changes: list[dict[str, Any]] = []
    for row in stem_rows:
        if not isinstance(row, dict):
            continue
        if row_filter is not None and not row_filter(row):
            continue
        gains = row.get("gains")
        if not isinstance(gains, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        for speaker_id in sorted(speaker_ids):
            value = _coerce_float(gains.get(speaker_id))
            if value is None or value <= 0.0:
                continue
            updated = _round_fallback_gain(value * linear)
            if abs(updated - value) <= 1e-9:
                continue
            gains[speaker_id] = updated
            changes.append(
                {
                    "change_kind": change_kind,
                    "stem_id": stem_id,
                    "speaker_id": speaker_id,
                    "from": round(float(value), 6),
                    "to": updated,
                    "unit": "linear_gain",
                }
            )
        _refresh_nonzero_channels(row, channel_order=channel_order)
    if not changes:
        return state, []
    return (
        replace(
            state,
            render_intent=render_intent,
            needs_rerender=True,
        ),
        changes,
    )


def _step_zero_render_intent_gains(
    state: _LayoutFallbackState,
    *,
    speaker_ids: frozenset[str],
    change_kind: str,
    row_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[_LayoutFallbackState, list[dict[str, Any]]]:
    render_intent = _json_clone(state.render_intent)
    channel_order = render_intent.get("channel_order")
    if not isinstance(channel_order, list):
        return state, []
    stem_rows = render_intent.get("stem_sends")
    if not isinstance(stem_rows, list):
        return state, []

    changes: list[dict[str, Any]] = []
    for row in stem_rows:
        if not isinstance(row, dict):
            continue
        if row_filter is not None and not row_filter(row):
            continue
        gains = row.get("gains")
        if not isinstance(gains, dict):
            continue
        stem_id = _coerce_str(row.get("stem_id")).strip()
        for speaker_id in sorted(speaker_ids):
            value = _coerce_float(gains.get(speaker_id))
            if value is None or value <= 0.0:
                continue
            gains[speaker_id] = 0.0
            changes.append(
                {
                    "change_kind": change_kind,
                    "stem_id": stem_id,
                    "speaker_id": speaker_id,
                    "from": round(float(value), 6),
                    "to": 0.0,
                    "unit": "linear_gain",
                }
            )
        _refresh_nonzero_channels(row, channel_order=channel_order)
    if not changes:
        return state, []
    return (
        replace(
            state,
            render_intent=render_intent,
            needs_rerender=True,
        ),
        changes,
    )


def _step_reduce_decorrelation_amount(
    state: _LayoutFallbackState,
) -> tuple[_LayoutFallbackState, list[dict[str, Any]]]:
    if not state.enable_bed_decorrelation or state.bed_decorrelation_options.mix <= 0.0:
        return state, []
    reduced_mix = max(
        0.0,
        round(
            state.bed_decorrelation_options.mix - _SIMILARITY_FALLBACK_DECORRELATION_MIX_DELTA,
            6,
        ),
    )
    if abs(reduced_mix - state.bed_decorrelation_options.mix) <= 1e-9:
        return state, []
    return (
        replace(
            state,
            bed_decorrelation_options=replace(
                state.bed_decorrelation_options,
                mix=reduced_mix,
            ),
            enable_bed_decorrelation=reduced_mix > 0.0,
            needs_rerender=True,
        ),
        [
            {
                "change_kind": "bed_decorrelation_mix",
                "from": round(float(state.bed_decorrelation_options.mix), 6),
                "to": reduced_mix,
                "unit": "mix_ratio",
            }
        ],
    )


def _step_disable_bed_polish(
    state: _LayoutFallbackState,
) -> tuple[_LayoutFallbackState, list[dict[str, Any]]]:
    if not state.enable_bed_decorrelation:
        return state, []
    return (
        replace(
            state,
            enable_bed_decorrelation=False,
            needs_rerender=True,
        ),
        [
            {
                "change_kind": "bed_decorrelation_enabled",
                "from": True,
                "to": False,
                "unit": "boolean",
            }
        ],
    )


def _step_collapse_bed_to_front_only(
    state: _LayoutFallbackState,
) -> tuple[_LayoutFallbackState, list[dict[str, Any]]]:
    collapsed_state, changes = _step_zero_render_intent_gains(
        state,
        speaker_ids=_SURROUND_CHANNEL_IDS | _OVERHEAD_CHANNEL_IDS,
        change_kind="collapse_bed_to_front_only",
        row_filter=_send_row_is_bed,
    )
    if not changes:
        return collapsed_state, changes
    return replace(collapsed_state, safety_collapse_applied=True), changes


def _render_layout_fallback_state(
    *,
    state: _LayoutFallbackState,
    session: Dict[str, Any],
    scene: dict[str, Any],
    layout_id: str,
    output_dir: Path,
    export_options: _ExportOptions,
    stem_scene_refs: dict[str, dict[str, list[str]]],
) -> _LayoutFallbackState:
    if not state.needs_rerender and state.layout_outputs:
        return state
    if state.layout_outputs:
        _remove_layout_output_files(
            output_dir=output_dir,
            layout_outputs=list(state.layout_outputs),
        )
    layout_outputs, layout_notes = _mix_layout_from_intent(
        session=session,
        scene=scene,
        render_intent=state.render_intent,
        layout_id=layout_id,
        output_dir=output_dir,
        export_options=export_options,
        stem_scene_refs=stem_scene_refs,
        bed_decorrelation_options=state.bed_decorrelation_options,
        enable_bed_decorrelation=state.enable_bed_decorrelation,
    )
    return replace(
        state,
        layout_outputs=tuple(layout_outputs),
        layout_notes=tuple(layout_notes),
        needs_rerender=False,
    )


def _clone_layout_fallback_state(
    state: _LayoutFallbackState,
) -> _LayoutFallbackState:
    return _LayoutFallbackState(
        render_intent=_json_clone(state.render_intent),
        bed_decorrelation_options=state.bed_decorrelation_options,
        enable_bed_decorrelation=state.enable_bed_decorrelation,
        layout_outputs=tuple(_json_clone(list(state.layout_outputs))),
        layout_notes=tuple(state.layout_notes),
        needs_rerender=state.needs_rerender,
        safety_collapse_applied=state.safety_collapse_applied,
    )


def _layout_similarity_result(
    *,
    layout_id: str,
    stereo_master_path: Path,
    surround_master_path: Path,
    sequence_report: dict[str, Any],
    final_state: _LayoutFallbackState,
) -> dict[str, Any]:
    initial_qa = dict(sequence_report.get("initial_qa") or {})
    fallback_attempts = [
        dict(item)
        for item in list(sequence_report.get("fallback_attempts") or [])
        if isinstance(item, dict)
    ]
    fallback_final = dict(sequence_report.get("fallback_final") or {})
    final_qa = dict(fallback_final.get("final_qa") or initial_qa)
    attempts = [initial_qa] if initial_qa else []
    attempts.extend(
        dict(item.get("qa_after") or {})
        for item in fallback_attempts
        if isinstance(item, dict)
    )
    fallback_final["safety_collapse_applied"] = bool(final_state.safety_collapse_applied)
    if (
        fallback_final.get("final_outcome") == "pass"
        and final_state.safety_collapse_applied
    ):
        fallback_final["final_outcome"] = "pass_with_safety_collapse"
    return {
        "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
        "gate_version": RENDERED_SIMILARITY_GATE_VERSION,
        "source_layout_id": layout_id,
        "target_layout_id": "LAYOUT.2_0",
        "stereo_render_path": stereo_master_path.resolve().as_posix(),
        "surround_render_path": surround_master_path.resolve().as_posix(),
        "fallback_applied": bool(sequence_report.get("fallback_applied")),
        "attempts": attempts,
        "fallback_attempts": fallback_attempts,
        "fallback_final": fallback_final,
        "passed": bool(final_qa.get("passed")),
        "risk_level": _coerce_str(final_qa.get("risk_level")).strip() or "high",
        "matrix_id": _coerce_str(final_qa.get("matrix_id")).strip(),
        "metrics": dict(final_qa.get("metrics") or {}),
        "thresholds": dict(final_qa.get("thresholds") or {}),
        "notes": list(final_qa.get("notes") or []),
    }


def _attach_similarity_metadata(
    *,
    output_row: dict[str, Any] | None,
    similarity_result: dict[str, Any],
) -> None:
    if not isinstance(output_row, dict):
        return
    metadata = output_row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        output_row["metadata"] = metadata
    metadata["downmix_similarity_qa"] = _json_clone(similarity_result)
    manifest_tags = metadata.get("manifest_tags")
    if isinstance(manifest_tags, list):
        tags = [
            _coerce_str(tag).strip()
            for tag in manifest_tags
            if _coerce_str(tag).strip()
        ]
    else:
        tags = []
    if similarity_result.get("fallback_applied") is True:
        tags.append("fallback_applied=true")
    fallback_final = similarity_result.get("fallback_final")
    if isinstance(fallback_final, dict) and fallback_final.get("safety_collapse_applied") is True:
        tags.append("safety_collapse_applied=true")
    if tags:
        metadata["manifest_tags"] = sorted(set(tags))

    warning_codes = canonical_warning_codes(metadata.get("warnings"))
    if similarity_result.get("fallback_applied") is True:
        warning_codes.append(RENDER_RESULT_FALLBACK_APPLIED)
    if isinstance(fallback_final, dict) and fallback_final.get("safety_collapse_applied") is True:
        warning_codes.append(RENDER_RESULT_SAFETY_COLLAPSE_APPLIED)
    if similarity_result.get("passed") is not True:
        warning_codes.append(RENDER_RESULT_DOWNMIX_QA_FAILED)
    warning_codes = sorted(set(warning_codes))
    if warning_codes:
        existing_warnings = [
            item.strip()
            for item in list(metadata.get("warnings") or [])
            if isinstance(item, str) and item.strip()
        ]
        metadata["warnings"] = sorted(
            set(existing_warnings) | set(warning_codes)
        )
    render_result = metadata.get("render_result")
    if isinstance(render_result, dict):
        render_result["warning_codes"] = warning_codes
        render_result["failure_reason"] = (
            RENDER_RESULT_DOWNMIX_QA_FAILED
            if similarity_result.get("passed") is not True
            else render_result.get("failure_reason")
        )


def _run_layout_similarity_fallback_sequence(
    *,
    session: Dict[str, Any],
    scene: dict[str, Any],
    layout_id: str,
    output_dir: Path,
    export_options: _ExportOptions,
    stem_scene_refs: dict[str, dict[str, list[str]]],
    render_intent: dict[str, Any],
    bed_decorrelation_options: _BedDecorrelatedOptions,
    enable_bed_decorrelation: bool,
    initial_layout_outputs: list[dict[str, Any]],
    initial_layout_notes: list[str],
    stereo_master_path: Path,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    initial_state = _LayoutFallbackState(
        render_intent=_json_clone(render_intent),
        bed_decorrelation_options=bed_decorrelation_options,
        enable_bed_decorrelation=enable_bed_decorrelation,
        layout_outputs=tuple(_json_clone(initial_layout_outputs)),
        layout_notes=tuple(initial_layout_notes),
    )

    def _render_fn(state: _LayoutFallbackState) -> _LayoutFallbackState:
        return _render_layout_fallback_state(
            state=state,
            session=session,
            scene=scene,
            layout_id=layout_id,
            output_dir=output_dir,
            export_options=export_options,
            stem_scene_refs=stem_scene_refs,
        )

    def _qa_fn(state: _LayoutFallbackState) -> dict[str, Any]:
        master_row = _master_output_row_for_layout(
            layout_outputs=list(state.layout_outputs),
            layout_id=layout_id,
        )
        master_path = _master_output_path(output_dir=output_dir, output_row=master_row)
        if not isinstance(master_path, Path) or not master_path.exists():
            raise ValueError(f"Missing master output for similarity QA: {layout_id}")
        return compare_rendered_surround_to_stereo_reference(
            stereo_render_file=stereo_master_path,
            surround_render_file=master_path,
            source_layout_id=layout_id,
        )

    fallback_steps = [
        {
            "step_id": "reduce_surround",
            "apply": lambda state: _step_scale_render_intent_gains(
                state,
                speaker_ids=_SURROUND_CHANNEL_IDS,
                gain_db=_SIMILARITY_FALLBACK_SURROUND_STEP_DB,
                change_kind="attenuate_surround_and_wide",
            ),
        },
        {
            "step_id": "reduce_height",
            "apply": lambda state: _step_scale_render_intent_gains(
                state,
                speaker_ids=_OVERHEAD_CHANNEL_IDS,
                gain_db=_SIMILARITY_FALLBACK_HEIGHT_STEP_DB,
                change_kind="attenuate_height",
            ),
        },
        {
            "step_id": "reduce_decorrelation",
            "apply": _step_reduce_decorrelation_amount,
        },
        {
            "step_id": "disable_wideners",
            "apply": _step_disable_bed_polish,
        },
        {
            "step_id": "front_bias",
            "apply": lambda state: _step_scale_render_intent_gains(
                state,
                speaker_ids=frozenset({"SPK.LRS", "SPK.RRS"}),
                gain_db=_SIMILARITY_FALLBACK_REAR_STEP_DB,
                change_kind="front_bias_ambiguous_beds",
                row_filter=_send_row_is_bed,
            ),
        },
        {
            "step_id": "safety_collapse",
            "apply": _step_collapse_bed_to_front_only,
        },
    ]
    stop_rule = {
        "max_steps": _SIMILARITY_FALLBACK_MAX_STEPS,
        "improvement_epsilon": _SIMILARITY_FALLBACK_STOP_EPSILON,
        "stagnation_limit": _SIMILARITY_FALLBACK_STOP_STAGNATION_LIMIT,
        "score_fn": similarity_gate_score,
    }

    sequence_initial_state = _clone_layout_fallback_state(initial_state)

    final_state, sequence_report = run_fallback_sequence(
        render_fn=_render_fn,
        qa_fn=_qa_fn,
        initial_state=sequence_initial_state,
        steps=fallback_steps,
        stop_rule=stop_rule,
    )

    # Preserve the last pre-collapse artifact when collapse still does not
    # satisfy similarity QA. This keeps the failure explicit without erasing
    # surround/height content as an accidental side effect of the retry path.
    fallback_final = sequence_report.get("fallback_final")
    if (
        isinstance(fallback_final, dict)
        and fallback_final.get("final_outcome") == "fail"
        and final_state.safety_collapse_applied
    ):
        non_collapse_steps = [
            step
            for step in fallback_steps
            if _coerce_str(step.get("step_id")).strip() != "safety_collapse"
        ]
        final_state, sequence_report = run_fallback_sequence(
            render_fn=_render_fn,
            qa_fn=_qa_fn,
            initial_state=_clone_layout_fallback_state(initial_state),
            steps=non_collapse_steps,
            stop_rule=stop_rule,
        )
    final_outputs = list(final_state.layout_outputs)
    final_notes = list(final_state.layout_notes)
    master_row = _master_output_row_for_layout(
        layout_outputs=final_outputs,
        layout_id=layout_id,
    )
    master_path = _master_output_path(output_dir=output_dir, output_row=master_row)
    if not isinstance(master_path, Path) or not master_path.exists():
        raise ValueError(f"Missing master output after fallback sequence: {layout_id}")
    similarity_result = _layout_similarity_result(
        layout_id=layout_id,
        stereo_master_path=stereo_master_path,
        surround_master_path=master_path,
        sequence_report=sequence_report,
        final_state=final_state,
    )
    _attach_similarity_metadata(output_row=master_row, similarity_result=similarity_result)
    plugin_meta = _bed_decorrelated_metadata(master_row)
    if isinstance(plugin_meta, dict):
        plugin_meta["qa_gate"] = _json_clone(similarity_result)
        applied_steps = set(similarity_result.get("fallback_final", {}).get("applied_steps", []))
        if "disable_wideners" in applied_steps:
            plugin_meta["disabled_by_qa"] = True
    return final_outputs, final_notes, similarity_result


class PlacementMixdownRenderer(RendererPlugin):
    plugin_id = _PLUGIN_ID

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        workspace_dir_text = _coerce_str(session.get("workspace_dir")).strip()
        workspace_dir = Path(workspace_dir_text) if workspace_dir_text else None
        manifest: RenderManifest = {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": [],
            "received_recommendation_ids": _received_recommendation_ids(recommendations),
            "stem_resolution": stem_resolution_entries(
                resolve_session_stems(session),
                workspace_dir=workspace_dir,
                portable=True,
            ),
        }
        if output_dir is None:
            manifest["notes"] = "missing_output_dir"
            return manifest

        # Placement rendering only runs against a resolved scene. Falling back
        # to raw session data here would invent speaker intent.
        scene = _build_scene(session)
        if not isinstance(scene, dict):
            manifest["notes"] = "placement_scene_unavailable"
            return manifest

        stereo_reinterpret_allowed = _scene_stereo_reinterpret_allowed(scene)
        export_options = _resolve_export_options(session)
        bed_decorrelation_options = _resolve_bed_decorrelated_options(session)
        # If export_layout_ids not explicitly set, fall back to the
        # target_layout_id injected by the variants runner (or pipeline) so
        # we render only the requested layout rather than every supported one.
        if not export_options.export_layout_ids:
            _tgt = _coerce_str(session.get("target_layout_id")).strip()
            if _tgt in _SUPPORTED_LAYOUT_IDS:
                export_options = replace(export_options, export_layout_ids=(_tgt,))
        selected_layouts = _selected_layout_ids(export_options)
        out_dir = Path(output_dir)
        stem_scene_refs = _scene_stem_reference_map(scene)
        outputs: list[dict[str, Any]] = []
        notes: list[str] = []
        stem_bus_by_id: dict[str, str] = {}
        stereo_master_path: Path | None = None

        for layout_id in selected_layouts:
            channel_order = _layout_channel_order(layout_id)
            if not channel_order:
                notes.append(f"{layout_id}:missing_channel_order")
                continue

            render_intent = build_render_intent(scene, layout_id)
            if not isinstance(render_intent, dict):
                notes.append(f"{layout_id}:placement_policy_unavailable")
                continue
            render_intent = dict(render_intent)
            render_intent["stereo_reinterpret_allowed"] = stereo_reinterpret_allowed
            stem_sends = render_intent.get("stem_sends")
            if isinstance(stem_sends, list):
                # Keep the first bus assignment per stem so later stem-copy
                # exports reuse the same grouping the master render saw.
                for row in stem_sends:
                    if not isinstance(row, dict):
                        continue
                    stem_id = _coerce_str(row.get("stem_id")).strip()
                    if not stem_id or stem_id in stem_bus_by_id:
                        continue
                    group_bus = _coerce_str(row.get("group_bus")).strip().upper() or "BUS.OTHER"
                    stem_bus_by_id[stem_id] = group_bus

            if not (export_options.export_master or export_options.export_buses):
                continue

            # Bed decorrelation only activates after a stereo master exists.
            # Without that reference, the immersive master cannot prove the QA gate.
            enable_bed_decorrelation = (
                bed_decorrelation_options.enabled
                and layout_id != "LAYOUT.2_0"
                and export_options.export_master
                and isinstance(stereo_master_path, Path)
            )
            layout_outputs, layout_notes = _mix_layout_from_intent(
                session=session,
                scene=scene,
                render_intent=render_intent,
                layout_id=layout_id,
                output_dir=out_dir,
                export_options=export_options,
                stem_scene_refs=stem_scene_refs,
                bed_decorrelation_options=bed_decorrelation_options,
                enable_bed_decorrelation=enable_bed_decorrelation,
            )
            if layout_notes:
                notes.extend(layout_notes)
            layout_master_row = _master_output_row_for_layout(
                layout_outputs=layout_outputs,
                layout_id=layout_id,
            )
            layout_master_path = _master_output_path(
                output_dir=out_dir,
                output_row=layout_master_row,
            )
            if (
                layout_id == "LAYOUT.2_0"
                and isinstance(layout_master_path, Path)
                and layout_master_path.exists()
            ):
                stereo_master_path = layout_master_path

            plugin_meta = _bed_decorrelated_metadata(layout_master_row)
            if (
                layout_id != "LAYOUT.2_0"
                and bed_decorrelation_options.enabled
                and export_options.export_master
                and isinstance(plugin_meta, dict)
                and not enable_bed_decorrelation
            ):
                plugin_meta["requested"] = True
                plugin_meta["active"] = False
                if not isinstance(stereo_master_path, Path):
                    plugin_meta["disabled_reason"] = "missing_stereo_reference"
                else:
                    plugin_meta["disabled_reason"] = "qa_gate_not_enabled"

            if (
                layout_id != "LAYOUT.2_0"
                and export_options.export_master
                and isinstance(stereo_master_path, Path)
                and isinstance(layout_master_path, Path)
                and layout_master_path.exists()
            ):
                # Similarity QA can rewrite the layout output after the first
                # render. Keep notes and plugin metadata in sync with the final result.
                try:
                    layout_outputs, final_layout_notes, similarity_result = (
                        _run_layout_similarity_fallback_sequence(
                            session=session,
                            scene=scene,
                            layout_id=layout_id,
                            output_dir=out_dir,
                            export_options=export_options,
                            stem_scene_refs=stem_scene_refs,
                            render_intent=render_intent,
                            bed_decorrelation_options=bed_decorrelation_options,
                            enable_bed_decorrelation=enable_bed_decorrelation,
                            initial_layout_outputs=layout_outputs,
                            initial_layout_notes=layout_notes,
                            stereo_master_path=stereo_master_path,
                        )
                    )
                except (RuntimeError, ValueError, OSError) as exc:
                    if isinstance(plugin_meta, dict):
                        plugin_meta["qa_gate"] = {
                            "passed": False,
                            "gate_error": str(exc),
                        }
                    notes.append(f"{layout_id}:downmix_similarity_qa_error")
                else:
                    if final_layout_notes:
                        notes.extend(final_layout_notes)
                    layout_master_row = _master_output_row_for_layout(
                        layout_outputs=layout_outputs,
                        layout_id=layout_id,
                    )
                    layout_master_path = _master_output_path(
                        output_dir=out_dir,
                        output_row=layout_master_row,
                    )
                    if similarity_result.get("fallback_applied") is True:
                        notes.append(f"{layout_id}:fallback_applied")
                    fallback_final = similarity_result.get("fallback_final")
                    if (
                        isinstance(fallback_final, dict)
                        and fallback_final.get("safety_collapse_applied") is True
                    ):
                        notes.append(f"{layout_id}:safety_collapse_applied")
                    if not bool(similarity_result.get("passed")):
                        notes.append(f"{layout_id}:downmix_similarity_gate_failed_after_fallback")

            if layout_outputs:
                outputs.extend(layout_outputs)

        if export_options.export_stems:
            stem_outputs, stem_notes = _export_stem_copy_outputs(
                session=session,
                output_dir=out_dir,
                stem_bus_by_id=stem_bus_by_id,
                stem_scene_refs=stem_scene_refs,
            )
            if stem_outputs:
                outputs.extend(stem_outputs)
            if stem_notes:
                notes.extend(stem_notes)
        if export_options.export_layout_ids and not selected_layouts:
            notes.append("export_layout_ids: no supported layouts selected")

        outputs.sort(
            key=lambda row: (
                _coerce_str(row.get("layout_id")),
                _coerce_str(row.get("file_path")),
            )
        )
        manifest["outputs"] = outputs
        # Preserve degraded or collapsed outcomes in the manifest notes. Review
        # tools still need the final gate result even when files were written.
        if notes:
            manifest["notes"] = ";".join(sorted(set(notes)))
        else:
            manifest["notes"] = (
                "placement_mixdown_rendered="
                + ",".join(_coerce_str(row.get("layout_id")) for row in outputs)
            )
        return manifest
