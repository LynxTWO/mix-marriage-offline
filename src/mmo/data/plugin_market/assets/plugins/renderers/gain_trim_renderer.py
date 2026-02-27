from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Any, Dict, Iterator, List, Sequence

from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin


_ALLOWED_ACTIONS = {
    "ACTION.UTILITY.GAIN": "PARAM.GAIN.DB",
    "ACTION.UTILITY.TRIM": "PARAM.GAIN.TRIM_DB",
}
_WAV_EXTENSIONS = {".wav", ".wave"}
_LOSSLESS_FFMPEG_EXTENSIONS = {".flac", ".wv", ".aif", ".aiff"}
_LOSSY_EXTENSIONS = {".mp3", ".aac", ".ogg", ".opus", ".m4a"}
_VALID_OUTPUT_BIT_DEPTHS = {16, 24, 32}
_FLOAT_MAX = math.nextafter(1.0, 0.0)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _extract_gain_db(rec: Dict[str, Any], param_id: str) -> float | None:
    params = rec.get("params")
    if not isinstance(params, list):
        return None
    for param in params:
        if not isinstance(param, dict):
            continue
        if param.get("param_id") != param_id:
            continue
        return _coerce_float(param.get("value"))
    return None


def _iter_applicable_recommendations(
    recommendations: List[Recommendation],
) -> List[Dict[str, Any]]:
    applicable: List[Dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        action_id = _coerce_str(rec.get("action_id"))
        param_id = _ALLOWED_ACTIONS.get(action_id)
        if param_id is None:
            continue
        if rec.get("risk") != "low":
            continue
        if rec.get("requires_approval") is not False:
            continue
        target = rec.get("target")
        if not isinstance(target, dict):
            continue
        if target.get("scope") != "stem":
            continue
        stem_id = _coerce_str(target.get("stem_id"))
        if not stem_id:
            continue
        recommendation_id = _coerce_str(rec.get("recommendation_id"))
        if not recommendation_id:
            continue
        gain_db = _extract_gain_db(rec, param_id)
        if gain_db is None or gain_db > 0.0:
            continue
        applicable.append(
            {
                "recommendation_id": recommendation_id,
                "action_id": action_id,
                "stem_id": stem_id,
                "gain_db": gain_db,
            }
        )
    applicable.sort(
        key=lambda item: (
            item["stem_id"],
            item["recommendation_id"],
            item["action_id"],
        )
    )
    return applicable


def _clamp_sample(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > _FLOAT_MAX:
        return _FLOAT_MAX
    return value


def _dithered_int_samples(
    float_samples: list[float],
    bits_per_sample: int,
    gain_scalar: float,
    rng: random.Random,
) -> list[int]:
    divisor = float(2 ** (bits_per_sample - 1))
    min_int = -int(divisor)
    max_int = int(divisor) - 1
    output: list[int] = []
    for sample in float_samples:
        value = _clamp_sample(sample * gain_scalar)
        noise = (rng.random() - rng.random()) / divisor
        value = _clamp_sample(value + noise)
        scaled = int(round(value * divisor))
        if scaled < min_int:
            scaled = min_int
        elif scaled > max_int:
            scaled = max_int
        output.append(scaled)
    return output


def _int_samples_to_bytes(samples: list[int], bits_per_sample: int) -> bytes:
    if bits_per_sample == 16:
        return struct.pack(f"<{len(samples)}h", *samples)
    if bits_per_sample == 24:
        data = bytearray(len(samples) * 3)
        for index, sample in enumerate(samples):
            value = sample & 0xFFFFFF
            offset = index * 3
            data[offset : offset + 3] = bytes(
                (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
            )
        return bytes(data)
    if bits_per_sample == 32:
        return struct.pack(f"<{len(samples)}i", *samples)
    raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")


def _output_bit_depth(input_bits_per_sample: Any) -> int:
    bits = _coerce_int(input_bits_per_sample)
    if bits in _VALID_OUTPUT_BIT_DEPTHS:
        return bits
    return 24


def _db_to_linear(gain_db: float) -> float:
    return math.pow(10.0, gain_db / 20.0)


def _routing_plan(session: Dict[str, Any]) -> Dict[str, Any] | None:
    value = session.get("routing_plan")
    if isinstance(value, dict):
        return value
    return None


def _routing_routes_by_stem(routing_plan: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    if not isinstance(routing_plan, dict):
        return {}
    routes = routing_plan.get("routes")
    if not isinstance(routes, list):
        return {}

    indexed: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        if not isinstance(route, dict):
            continue
        stem_id = _coerce_str(route.get("stem_id"))
        if not stem_id or stem_id in indexed:
            continue
        indexed[stem_id] = route
    return indexed


def _route_notes(route: Dict[str, Any]) -> List[str]:
    notes_raw = route.get("notes")
    if not isinstance(notes_raw, list):
        return []
    notes: List[str] = []
    for note in notes_raw:
        if isinstance(note, str) and note:
            notes.append(note)
    return notes


def _route_mapping_entries(
    route: Dict[str, Any],
    *,
    source_channels: int,
    target_channels: int,
) -> List[tuple[int, int, float]] | None:
    mapping_raw = route.get("mapping")
    if not isinstance(mapping_raw, list):
        return None
    if not mapping_raw:
        return []

    entries: List[tuple[int, int, float]] = []
    for raw_entry in mapping_raw:
        if not isinstance(raw_entry, dict):
            return None
        src_ch = _coerce_int(raw_entry.get("src_ch"))
        dst_ch = _coerce_int(raw_entry.get("dst_ch"))
        if src_ch is None or dst_ch is None:
            return None
        if src_ch < 0 or src_ch >= source_channels:
            return None
        if dst_ch < 0 or dst_ch >= target_channels:
            return None
        gain_db = _coerce_float(raw_entry.get("gain_db"))
        gain_scalar = _db_to_linear(gain_db if gain_db is not None else 0.0)
        entries.append((src_ch, dst_ch, gain_scalar))
    return entries


def _apply_route_mapping(
    aligned_samples: list[float],
    *,
    source_channels: int,
    target_channels: int,
    mapping: List[tuple[int, int, float]],
) -> list[float]:
    frame_count = len(aligned_samples) // source_channels
    routed_samples = [0.0] * (frame_count * target_channels)
    for frame_index in range(frame_count):
        source_offset = frame_index * source_channels
        target_offset = frame_index * target_channels
        for src_ch, dst_ch, gain_scalar in mapping:
            routed_samples[target_offset + dst_ch] += (
                aligned_samples[source_offset + src_ch] * gain_scalar
            )
    return routed_samples


def _iter_wav_samples_for_render(source_path: Path) -> Iterator[list[float]]:
    yield from iter_wav_float64_samples(source_path, error_context="render gain/trim")


def _iter_ffmpeg_samples_for_render(
    source_path: Path,
    ffmpeg_cmd: Sequence[str],
) -> Iterator[list[float]]:
    yield from iter_ffmpeg_float64_samples(source_path, ffmpeg_cmd)


def _render_gain_trim(
    float_samples_iter: Iterator[list[float]],
    output_path: Path,
    gain_db: float,
    *,
    bits_per_sample: int,
    channels: int,
    sample_rate_hz: int,
    target_channels: int | None = None,
    route_mapping: List[tuple[int, int, float]] | None = None,
) -> None:
    gain_scalar = _db_to_linear(gain_db)
    rng = random.Random(0)
    pending_samples: list[float] = []
    source_frame_width = channels
    output_frame_width = channels if target_channels is None else target_channels
    if output_frame_width <= 0:
        raise ValueError("target channel count must be > 0")
    if route_mapping is None and output_frame_width != source_frame_width:
        raise ValueError("target channel count mismatch without route mapping")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out_handle:
        out_handle.setnchannels(output_frame_width)
        out_handle.setsampwidth(bits_per_sample // 8)
        out_handle.setframerate(sample_rate_hz)

        for float_samples in float_samples_iter:
            pending_samples.extend(float_samples)
            aligned_sample_count = (
                len(pending_samples) // source_frame_width
            ) * source_frame_width
            if aligned_sample_count <= 0:
                continue
            aligned_samples = pending_samples[:aligned_sample_count]
            pending_samples = pending_samples[aligned_sample_count:]
            if route_mapping is not None:
                aligned_samples = _apply_route_mapping(
                    aligned_samples,
                    source_channels=source_frame_width,
                    target_channels=output_frame_width,
                    mapping=route_mapping,
                )

            int_samples = _dithered_int_samples(
                aligned_samples,
                bits_per_sample,
                gain_scalar,
                rng,
            )
            out_handle.writeframes(_int_samples_to_bytes(int_samples, bits_per_sample))

        if pending_samples:
            raise ValueError("decoder returned non-frame-aligned sample data")


def _resolve_stems_dir(session: Dict[str, Any]) -> Path | None:
    stems_dir = session.get("stems_dir")
    if isinstance(stems_dir, str) and stems_dir:
        return Path(stems_dir)
    return None


def _stem_index(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    stems = session.get("stems")
    if not isinstance(stems, list):
        return {}
    indexed: Dict[str, Dict[str, Any]] = {}
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if not stem_id or stem_id in indexed:
            continue
        indexed[stem_id] = stem
    return indexed


def _resolve_source_and_relative_path(
    stem: Dict[str, Any],
    stems_dir: Path | None,
) -> tuple[Path | None, Path | None, str | None]:
    file_path_value = _coerce_str(stem.get("file_path"))
    if not file_path_value:
        return None, None, "missing_stem_file_path"

    file_path = Path(file_path_value)
    if file_path.is_absolute():
        if stems_dir is None:
            return file_path, Path(file_path.name), None
        try:
            return file_path, file_path.relative_to(stems_dir), None
        except ValueError:
            return file_path, Path(file_path.name), None

    if stems_dir is None:
        return None, None, "missing_stems_dir"

    return stems_dir / file_path, file_path, None


def _rendered_relative_path(source_relative_path: Path) -> Path:
    return source_relative_path.with_name(
        f"{source_relative_path.stem}.mmo_gaintrim.wav"
    )


def _append_skipped(
    skipped: List[Dict[str, str]],
    contributions: List[Dict[str, Any]],
    reason: str,
) -> None:
    for rec in contributions:
        skipped.append(
            {
                "recommendation_id": rec["recommendation_id"],
                "action_id": rec["action_id"],
                "reason": reason,
                "gate_summary": "",
            }
        )


def _sorted_skipped(skipped: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    items = sorted(
        skipped,
        key=lambda item: (
            item["recommendation_id"],
            item["action_id"],
            item["reason"],
        ),
    )
    merged: List[Dict[str, str]] = []
    for item in items:
        key = (item["recommendation_id"], item["action_id"], item["reason"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


class GainTrimRenderer(RendererPlugin):
    plugin_id = "PLUGIN.RENDERER.GAIN_TRIM"

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        applicable = _iter_applicable_recommendations(recommendations)
        manifest: RenderManifest = {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": [],
        }
        if not applicable:
            return manifest

        out_dir: Path | None = None
        if output_dir is not None:
            out_dir = Path(output_dir)
        if out_dir is None:
            manifest["skipped"] = _sorted_skipped(
                [
                    {
                        "recommendation_id": rec["recommendation_id"],
                        "action_id": rec["action_id"],
                        "reason": "missing_output_dir",
                        "gate_summary": "",
                    }
                    for rec in applicable
                ]
            )
            return manifest

        stems_dir = _resolve_stems_dir(session)
        stems_by_id = _stem_index(session)
        routing_plan = _routing_plan(session)
        routing_routes = _routing_routes_by_stem(routing_plan)
        routing_source_layout_id = (
            _coerce_str(routing_plan.get("source_layout_id"))
            if isinstance(routing_plan, dict)
            else ""
        )
        routing_target_layout_id = (
            _coerce_str(routing_plan.get("target_layout_id"))
            if isinstance(routing_plan, dict)
            else ""
        )
        ffmpeg_cmd: Sequence[str] | None = None

        grouped_by_stem: Dict[str, List[Dict[str, Any]]] = {}
        for rec in applicable:
            grouped_by_stem.setdefault(rec["stem_id"], []).append(rec)

        outputs: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        for stem_id in sorted(grouped_by_stem.keys()):
            contributions = grouped_by_stem[stem_id]
            stem = stems_by_id.get(stem_id)
            if stem is None:
                _append_skipped(skipped, contributions, "missing_stem")
                continue

            source_path, source_relative_path, resolve_reason = (
                _resolve_source_and_relative_path(stem, stems_dir)
            )
            if resolve_reason is not None or source_path is None or source_relative_path is None:
                reason = resolve_reason or "missing_stem_file_path"
                _append_skipped(skipped, contributions, reason)
                continue

            output_relative_path = _rendered_relative_path(source_relative_path)
            output_path = out_dir / output_relative_path
            applied_gain_db = sum(float(rec["gain_db"]) for rec in contributions)

            extension = source_path.suffix.lower()
            channels: int | None = None
            sample_rate_hz: int | None = None
            bits_per_sample = 24
            render_samples_iter: Iterator[list[float]] | None = None

            if extension in _WAV_EXTENSIONS:
                stem_wav_format = _coerce_int(stem.get("wav_audio_format_resolved"))
                if stem_wav_format is not None and stem_wav_format not in (1, 3):
                    _append_skipped(skipped, contributions, "unsupported_wav_format")
                    continue

                try:
                    metadata = read_wav_metadata(source_path)
                except ValueError:
                    _append_skipped(skipped, contributions, "unsupported_format")
                    continue

                audio_format = metadata.get("audio_format_resolved")
                input_bits = metadata.get("bits_per_sample")
                channels = _coerce_int(metadata.get("channels"))
                sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))

                if audio_format == 1:
                    if input_bits not in _VALID_OUTPUT_BIT_DEPTHS:
                        _append_skipped(skipped, contributions, "unsupported_wav_format")
                        continue
                elif audio_format == 3:
                    if input_bits not in (32, 64):
                        _append_skipped(skipped, contributions, "unsupported_wav_format")
                        continue
                else:
                    _append_skipped(skipped, contributions, "unsupported_wav_format")
                    continue

                if channels is None or channels <= 0 or sample_rate_hz is None or sample_rate_hz <= 0:
                    _append_skipped(skipped, contributions, "unsupported_wav_format")
                    continue

                bits_per_sample = _output_bit_depth(input_bits)
                render_samples_iter = _iter_wav_samples_for_render(source_path)
            elif extension in _LOSSLESS_FFMPEG_EXTENSIONS:
                if ffmpeg_cmd is None:
                    ffmpeg_cmd = resolve_ffmpeg_cmd()
                if ffmpeg_cmd is None:
                    _append_skipped(skipped, contributions, "missing_ffmpeg")
                    continue

                channels = _coerce_int(stem.get("channel_count"))
                sample_rate_hz = _coerce_int(stem.get("sample_rate_hz"))
                if channels is None or channels <= 0 or sample_rate_hz is None or sample_rate_hz <= 0:
                    _append_skipped(skipped, contributions, "missing_metadata")
                    continue

                bits_per_sample = _output_bit_depth(stem.get("bits_per_sample"))
                render_samples_iter = _iter_ffmpeg_samples_for_render(source_path, ffmpeg_cmd)
            elif extension in _LOSSY_EXTENSIONS:
                _append_skipped(skipped, contributions, "lossy_input")
                continue
            else:
                _append_skipped(skipped, contributions, "unsupported_format")
                continue

            if render_samples_iter is None or channels is None or sample_rate_hz is None:
                _append_skipped(skipped, contributions, "unsupported_format")
                continue

            output_channels = channels
            route_mapping: List[tuple[int, int, float]] | None = None
            route_notes: List[str] = []
            routing_applied = False
            route = routing_routes.get(stem_id)
            if isinstance(route, dict):
                route_target_channels = _coerce_int(route.get("target_channels"))
                route_stem_channels = _coerce_int(route.get("stem_channels"))
                if (
                    route_target_channels is not None
                    and route_target_channels > 0
                    and route_target_channels != channels
                ):
                    if (
                        route_stem_channels is not None
                        and route_stem_channels > 0
                        and route_stem_channels != channels
                    ):
                        _append_skipped(skipped, contributions, "no_safe_routing")
                        continue
                    route_mapping = _route_mapping_entries(
                        route,
                        source_channels=channels,
                        target_channels=route_target_channels,
                    )
                    if not route_mapping:
                        _append_skipped(skipped, contributions, "no_safe_routing")
                        continue
                    output_channels = route_target_channels
                    route_notes = _route_notes(route)
                    routing_applied = True

            try:
                _render_gain_trim(
                    render_samples_iter,
                    output_path,
                    applied_gain_db,
                    bits_per_sample=bits_per_sample,
                    channels=channels,
                    sample_rate_hz=sample_rate_hz,
                    target_channels=output_channels,
                    route_mapping=route_mapping,
                )
            except ValueError:
                _append_skipped(skipped, contributions, "unsupported_format")
                continue
            output_sha256 = sha256_file(output_path)

            recommendation_ids = sorted(rec["recommendation_id"] for rec in contributions)
            representative = min(
                contributions,
                key=lambda rec: (rec["recommendation_id"], rec["action_id"]),
            )

            notes = ""
            if len(recommendation_ids) > 1:
                notes = f"Contributing recommendation IDs: {','.join(recommendation_ids)}"

            metadata: Dict[str, Any] = {
                "applied_gain_db": applied_gain_db,
                "contributing_recommendation_ids": recommendation_ids,
            }
            if routing_applied:
                metadata["routing_applied"] = True
                if routing_source_layout_id:
                    metadata["source_layout_id"] = routing_source_layout_id
                if routing_target_layout_id:
                    metadata["target_layout_id"] = routing_target_layout_id
                if route_notes:
                    metadata["routing_notes"] = route_notes

            outputs.append(
                {
                    "output_id": f"OUTPUT.GAIN_TRIM.{stem_id}.{output_sha256[:12]}",
                    "file_path": output_relative_path.as_posix(),
                    "action_id": representative["action_id"],
                    "recommendation_id": representative["recommendation_id"],
                    "target_stem_id": stem_id,
                    "format": "wav",
                    "sample_rate_hz": sample_rate_hz,
                    "bit_depth": bits_per_sample,
                    "channel_count": output_channels,
                    "sha256": output_sha256,
                    "notes": notes,
                    "metadata": metadata,
                }
            )

        outputs.sort(key=lambda item: (item.get("target_stem_id", ""), item.get("output_id", "")))
        manifest["outputs"] = outputs
        manifest["skipped"] = _sorted_skipped(skipped)
        return manifest
