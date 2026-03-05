from __future__ import annotations

import json
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Sequence

from mmo.core.layout_negotiation import get_layout_channel_order
from mmo.core.placement_policy import build_render_intent
from mmo.core.scene_builder import build_scene_from_bus_plan, build_scene_from_session
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1"
_SUPPORTED_LAYOUT_IDS: tuple[str, ...] = (
    "LAYOUT.2_0",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
    "LAYOUT.7_1_4",
    "LAYOUT.7_1_6",
    "LAYOUT.9_1_6",
)
_DEFAULT_CHANNEL_ORDER: dict[str, tuple[str, ...]] = {
    "LAYOUT.2_0": ("SPK.L", "SPK.R"),
    "LAYOUT.5_1": ("SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"),
    "LAYOUT.7_1": (
        "SPK.L",
        "SPK.R",
        "SPK.C",
        "SPK.LFE",
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
    ),
    "LAYOUT.7_1_4": (
        "SPK.L",
        "SPK.R",
        "SPK.C",
        "SPK.LFE",
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
        "SPK.TFL",
        "SPK.TFR",
        "SPK.TRL",
        "SPK.TRR",
    ),
    "LAYOUT.7_1_6": (
        "SPK.L",
        "SPK.R",
        "SPK.C",
        "SPK.LFE",
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
        "SPK.TFL",
        "SPK.TFR",
        "SPK.TRL",
        "SPK.TRR",
        "SPK.TFC",
        "SPK.TBC",
    ),
    "LAYOUT.9_1_6": (
        "SPK.L",
        "SPK.R",
        "SPK.C",
        "SPK.LFE",
        "SPK.LS",
        "SPK.RS",
        "SPK.LRS",
        "SPK.RRS",
        "SPK.LW",
        "SPK.RW",
        "SPK.TFL",
        "SPK.TFR",
        "SPK.TRL",
        "SPK.TRR",
        "SPK.TFC",
        "SPK.TBC",
    ),
}
_WAV_EXTENSIONS = {".wav", ".wave"}
_DEFAULT_SAMPLE_RATE_HZ = 48_000
_DEFAULT_SILENCE_FRAMES = 4_800
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
_IMMERSIVE_WRAP_PERSPECTIVES: frozenset[str] = frozenset({"in_band", "in_orchestra"})
_SIDE_WRAP_CONFIDENCE_MIN = 0.8
_SIDE_WRAP_WIDE_GAIN_RATIO = 0.12


@dataclass(frozen=True)
class _PreparedStem:
    stem_id: str
    source_path: Path
    stem_channels: int
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


@dataclass
class _StemPassState:
    stem: _PreparedStem
    iterator: Iterator[list[float]]
    active: bool = True
    failed: bool = False


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


def _resolve_stems_dir(session: Dict[str, Any]) -> Path | None:
    stems_dir = _coerce_str(session.get("stems_dir")).strip()
    if not stems_dir:
        return None
    return Path(stems_dir)


def _stem_rows(session: Dict[str, Any]) -> list[dict[str, Any]]:
    rows = session.get("stems")
    if not isinstance(rows, list):
        return []
    stems: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
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
    stems_dir: Path | None,
) -> tuple[Path | None, str | None]:
    file_path = _coerce_str(stem.get("file_path")).strip()
    if not file_path:
        return None, "missing_stem_file_path"

    candidate = Path(file_path)
    if not candidate.is_absolute():
        if stems_dir is None:
            return None, "missing_stems_dir"
        candidate = stems_dir / candidate

    if not candidate.exists():
        return None, "missing_stem_file"
    if candidate.suffix.lower() not in _WAV_EXTENSIONS:
        return None, "unsupported_non_wav_source"
    return candidate, None


def _layout_channel_order(layout_id: str) -> list[str]:
    order = get_layout_channel_order(layout_id)
    if isinstance(order, list):
        cleaned = [
            item.strip()
            for item in order
            if isinstance(item, str) and item.strip()
        ]
        if cleaned:
            return cleaned
    return list(_DEFAULT_CHANNEL_ORDER.get(layout_id, ()))


def _layout_slug(layout_id: str) -> str:
    return layout_id.replace(".", "_")


def _output_relative_path(
    *,
    output_dir: Path,
    layout_id: str,
) -> Path:
    layout_dir = _layout_slug(layout_id)
    if output_dir.name.casefold() == layout_dir.casefold():
        return Path("master.wav")
    return Path(layout_dir) / "master.wav"


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


def _float_samples_to_pcm24_bytes(samples: Sequence[float]) -> bytes:
    scale = 8_388_607.0
    min_int = -8_388_608
    max_int = 8_388_607
    out = bytearray()
    for sample in samples:
        value = _clamp_sample(sample)
        quantized = int(round(value * scale))
        if quantized < min_int:
            quantized = min_int
        elif quantized > max_int:
            quantized = max_int
        out.extend(struct.pack("<i", quantized)[:3])
    return bytes(out)


def _mix_stem_chunk_into_buffer(
    *,
    destination_chunk: list[float],
    source_chunk: list[float],
    frame_count: int,
    channel_count: int,
    stem: _PreparedStem,
) -> None:
    source_index = 0
    for frame_index in range(frame_count):
        target_base = frame_index * channel_count
        if stem.stem_channels == 1:
            mono = float(source_chunk[source_index])
            source_index += 1
            for channel_index, gain in enumerate(stem.gain_vector):
                if gain == 0.0:
                    continue
                destination_chunk[target_base + channel_index] += mono * gain
            continue

        if stem.stereo_channel_wise:
            left = float(source_chunk[source_index])
            right = float(source_chunk[source_index + 1])
            source_index += 2
            if stem.front_left_gain != 0.0:
                destination_chunk[target_base + stem.front_left_idx] += left * stem.front_left_gain
            if stem.front_right_gain != 0.0:
                destination_chunk[target_base + stem.front_right_idx] += right * stem.front_right_gain
            continue

        left = 0.0
        right = 0.0
        mono_sum = 0.0
        for source_channel_index in range(stem.stem_channels):
            sample = float(source_chunk[source_index])
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
            destination_chunk[target_base + channel_index] += mid * gain

        if stem.front_left_gain != 0.0:
            destination_chunk[target_base + stem.front_left_idx] += side * stem.front_left_gain
        if stem.front_right_gain != 0.0:
            destination_chunk[target_base + stem.front_right_idx] -= side * stem.front_right_gain

        if stem.wide_wrap_left_gain != 0.0 and isinstance(stem.wide_left_idx, int):
            destination_chunk[target_base + stem.wide_left_idx] += side * stem.wide_wrap_left_gain
        if stem.wide_wrap_right_gain != 0.0 and isinstance(stem.wide_right_idx, int):
            destination_chunk[target_base + stem.wide_right_idx] -= side * stem.wide_wrap_right_gain


def _run_mix_pass(
    *,
    prepared_stems: list[_PreparedStem],
    channel_count: int,
    layout_id: str,
    on_chunk: Callable[[list[float], int], None],
) -> tuple[int, int, list[str]]:
    states = [
        _StemPassState(
            stem=stem,
            iterator=iter_wav_float64_samples(
                stem.source_path,
                error_context="placement mixdown renderer",
            ),
        )
        for stem in prepared_stems
    ]
    notes: list[str] = []
    total_frames = 0

    while True:
        any_active = False
        mixed_chunk = [0.0] * (_RENDER_CHUNK_FRAMES * channel_count)
        mixed_frame_count = 0

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

            sample_count = len(chunk)
            if sample_count % state.stem.stem_channels != 0:
                state.active = False
                state.failed = True
                notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
                continue

            frame_count = sample_count // state.stem.stem_channels
            if frame_count <= 0 or frame_count > _RENDER_CHUNK_FRAMES:
                state.active = False
                state.failed = True
                notes.append(f"{layout_id}:{state.stem.stem_id}:decode_failed")
                continue

            if frame_count > mixed_frame_count:
                mixed_frame_count = frame_count
            _mix_stem_chunk_into_buffer(
                destination_chunk=mixed_chunk,
                source_chunk=chunk,
                frame_count=frame_count,
                channel_count=channel_count,
                stem=state.stem,
            )

        if mixed_frame_count > 0:
            on_chunk(mixed_chunk, mixed_frame_count)
            total_frames += mixed_frame_count

        if not any_active:
            break

    decoded_stems = sum(1 for state in states if not state.failed)
    return decoded_stems, total_frames, notes


def _prepare_layout_stems(
    *,
    session: Dict[str, Any],
    render_intent: dict[str, Any],
    layout_id: str,
    normalized_channel_order: list[str],
    sends_by_stem: dict[str, dict[str, Any]],
) -> tuple[list[_PreparedStem], int | None, dict[str, str], list[str]]:
    notes: list[str] = []
    stems_dir = _resolve_stems_dir(session)
    stems = _stem_rows(session)
    speaker_idx = _speaker_index(normalized_channel_order)
    front_left_idx = speaker_idx.get("SPK.L")
    front_right_idx = speaker_idx.get("SPK.R")
    if not isinstance(front_left_idx, int) or not isinstance(front_right_idx, int):
        return [], None, {}, [f"{layout_id}:missing_front_lr_channels"]

    wide_left_idx = speaker_idx.get("SPK.LW")
    wide_right_idx = speaker_idx.get("SPK.RW")
    prepared_stems: list[_PreparedStem] = []
    stem_mix_modes: dict[str, str] = {}
    sample_rate_hz: int | None = None

    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip() or "<unknown>"
        source_path, resolve_reason = _resolve_stem_source_path(stem, stems_dir)
        if resolve_reason is not None or source_path is None:
            notes.append(f"{layout_id}:{stem_id}:{resolve_reason}")
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

        try:
            metadata = read_wav_metadata(source_path)
            stem_channels = _coerce_int(metadata.get("channels"))
            stem_sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
            if stem_channels is None or stem_channels < 1:
                raise ValueError("invalid_channel_count")
            if stem_sample_rate_hz is None or stem_sample_rate_hz < 1:
                raise ValueError("invalid_sample_rate")
            if sample_rate_hz is None:
                sample_rate_hz = stem_sample_rate_hz
            elif sample_rate_hz != stem_sample_rate_hz:
                notes.append(
                    f"{layout_id}:{stem_id}:sample_rate_mismatch"
                    f"({stem_sample_rate_hz}!={sample_rate_hz})"
                )
                continue

            if stem_channels == 1:
                stem_mix_mode = "mono_by_policy_gains"
            elif stem_channels == 2 and layout_id == "LAYOUT.2_0":
                stem_mix_mode = "stereo_channel_wise"
            elif stem_channels == 2:
                stem_mix_mode = "stereo_mid_side_preserve"
            else:
                stem_mix_mode = "multichannel_mid_side_preserve"
            if stereo_side_wrap_enabled and (
                wide_wrap_left_gain > 0.0 or wide_wrap_right_gain > 0.0
            ):
                stem_mix_mode = f"{stem_mix_mode}_wide_wrap"
            stem_mix_modes[stem_id] = stem_mix_mode

            prepared_stems.append(
                _PreparedStem(
                    stem_id=stem_id,
                    source_path=source_path,
                    stem_channels=stem_channels,
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
                )
            )
        except Exception:
            notes.append(f"{layout_id}:{stem_id}:decode_failed")

    return prepared_stems, sample_rate_hz, stem_mix_modes, notes


def _update_chunk_peak_by_channel(
    *,
    peak_by_channel: list[float],
    mixed_chunk: list[float],
    frame_count: int,
    channel_count: int,
) -> None:
    for frame_index in range(frame_count):
        frame_base = frame_index * channel_count
        for channel_index in range(channel_count):
            sample = abs(mixed_chunk[frame_base + channel_index])
            if sample > peak_by_channel[channel_index]:
                peak_by_channel[channel_index] = sample


def _write_trimmed_chunk(
    *,
    handle: wave.Wave_write,
    mixed_chunk: list[float],
    frame_count: int,
    channel_count: int,
    trim_linear: float,
) -> None:
    sample_count = frame_count * channel_count
    trimmed = [
        _clamp_sample(mixed_chunk[index] * trim_linear)
        for index in range(sample_count)
    ]
    handle.writeframes(_float_samples_to_pcm24_bytes(trimmed))


def _mix_layout_from_intent(
    *,
    session: Dict[str, Any],
    render_intent: dict[str, Any],
    layout_id: str,
    output_dir: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    notes: list[str] = []
    channel_order = render_intent.get("channel_order")
    if not isinstance(channel_order, list) or not channel_order:
        return None, [f"{layout_id}:missing_channel_order"]

    normalized_channel_order = [
        speaker_id
        for speaker_id in channel_order
        if isinstance(speaker_id, str) and speaker_id
    ]
    if not normalized_channel_order:
        return None, [f"{layout_id}:invalid_channel_order"]

    rel_path = _output_relative_path(output_dir=output_dir, layout_id=layout_id)
    abs_path = output_dir / rel_path
    if abs_path.exists():
        return None, [
            f"{layout_id}:skipped_existing_output:{rel_path.as_posix()}"
        ]

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
    prepared_stems, sample_rate_hz, stem_mix_modes, prep_notes = _prepare_layout_stems(
        session=session,
        render_intent=render_intent,
        layout_id=layout_id,
        normalized_channel_order=normalized_channel_order,
        sends_by_stem=sends_by_stem,
    )
    if prep_notes:
        notes.extend(prep_notes)

    if sample_rate_hz is None:
        sample_rate_hz = _DEFAULT_SAMPLE_RATE_HZ
    peak_by_channel = [0.0] * channel_count
    decoded_stems, pass1_frames, pass1_notes = _run_mix_pass(
        prepared_stems=prepared_stems,
        channel_count=channel_count,
        layout_id=layout_id,
        on_chunk=lambda chunk, frame_count: _update_chunk_peak_by_channel(
            peak_by_channel=peak_by_channel,
            mixed_chunk=chunk,
            frame_count=frame_count,
            channel_count=channel_count,
        ),
    )
    if pass1_notes:
        notes.extend(pass1_notes)

    rendered_audio = pass1_frames > 0
    if not rendered_audio:
        notes.append(f"{layout_id}:rendered_silence:no_decodable_stems")

    pre_trim_peak = max(peak_by_channel) if peak_by_channel else 0.0
    target_peak_linear = _db_to_linear(_TARGET_PEAK_DBFS)
    if pre_trim_peak <= 0.0:
        trim_linear = 1.0
    else:
        trim_linear = min(1.0, target_peak_linear / pre_trim_peak)
    trim_db = _linear_to_db(trim_linear)

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    pass2_frames = 0
    with wave.open(str(abs_path), "wb") as handle:
        handle.setnchannels(channel_count)
        handle.setsampwidth(3)
        handle.setframerate(sample_rate_hz)

        if rendered_audio:
            _, pass2_frames, pass2_notes = _run_mix_pass(
                prepared_stems=prepared_stems,
                channel_count=channel_count,
                layout_id=layout_id,
                on_chunk=lambda chunk, frame_count: _write_trimmed_chunk(
                    handle=handle,
                    mixed_chunk=chunk,
                    frame_count=frame_count,
                    channel_count=channel_count,
                    trim_linear=trim_linear,
                ),
            )
            if pass2_notes:
                notes.extend(pass2_notes)
        if pass2_frames <= 0:
            silence = [0.0] * (_DEFAULT_SILENCE_FRAMES * channel_count)
            handle.writeframes(_float_samples_to_pcm24_bytes(silence))

    output_sha = sha256_file(abs_path)
    layout_slug = _layout_slug(layout_id)

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

    output_row: dict[str, Any] = {
        "output_id": f"OUTPUT.PLACEMENT_MIXDOWN.{layout_slug}.{output_sha[:12]}",
        "file_path": rel_path.as_posix(),
        "layout_id": layout_id,
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": 24,
        "channel_count": channel_count,
        "sha256": output_sha,
        "notes": (
            "scene_placement_mixdown stereo_imaging_preserved"
            f" trim_db={trim_db:.4f}"
        ),
        "metadata": {
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
            "what_why": (
                "Rendered one layout-agnostic scene into layout speakers using "
                "conservative placement sends; stereo stems keep L/R imaging in "
                "stereo outputs and mid/side handling in multichannel outputs."
            ),
            "stem_send_summary": stem_send_summary,
        },
    }
    if notes:
        output_row["metadata"]["warnings"] = sorted(set(notes))
    return output_row, []


class PlacementMixdownRenderer(RendererPlugin):
    plugin_id = _PLUGIN_ID

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        manifest: RenderManifest = {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": [],
            "received_recommendation_ids": _received_recommendation_ids(recommendations),
        }
        if output_dir is None:
            manifest["notes"] = "missing_output_dir"
            return manifest

        scene = _build_scene(session)
        if not isinstance(scene, dict):
            manifest["notes"] = "placement_scene_unavailable"
            return manifest

        out_dir = Path(output_dir)
        outputs: list[dict[str, Any]] = []
        notes: list[str] = []

        for layout_id in _SUPPORTED_LAYOUT_IDS:
            channel_order = _layout_channel_order(layout_id)
            if not channel_order:
                notes.append(f"{layout_id}:missing_channel_order")
                continue

            render_intent = build_render_intent(scene, layout_id)
            if not isinstance(render_intent, dict):
                notes.append(f"{layout_id}:placement_policy_unavailable")
                continue

            output_row, layout_notes = _mix_layout_from_intent(
                session=session,
                render_intent=render_intent,
                layout_id=layout_id,
                output_dir=out_dir,
            )
            if layout_notes:
                notes.extend(layout_notes)
            if isinstance(output_row, dict):
                outputs.append(output_row)

        outputs.sort(
            key=lambda row: (
                _coerce_str(row.get("layout_id")),
                _coerce_str(row.get("file_path")),
            )
        )
        manifest["outputs"] = outputs
        if notes:
            manifest["notes"] = ";".join(sorted(set(notes)))
        else:
            manifest["notes"] = (
                "placement_mixdown_rendered="
                + ",".join(_coerce_str(row.get("layout_id")) for row in outputs)
            )
        return manifest
