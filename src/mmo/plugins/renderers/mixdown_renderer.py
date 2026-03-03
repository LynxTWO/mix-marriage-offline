from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from mmo.core.layout_negotiation import get_layout_channel_order
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_SUPPORTED_LAYOUT_IDS: tuple[str, ...] = (
    "LAYOUT.2_0",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
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
}
_TARGET_FALLBACK_LAYOUTS: dict[str, str] = {
    "LAYOUT.5_1_2": "LAYOUT.5_1",
    "LAYOUT.5_1_4": "LAYOUT.5_1",
    "LAYOUT.7_1_2": "LAYOUT.7_1",
    "LAYOUT.7_1_4": "LAYOUT.7_1",
}
_DEFAULT_SAMPLE_RATE_HZ = 48_000
_DEFAULT_SILENCE_FRAMES = 4_800
_TARGET_PEAK_DBFS = -1.0
_FALLBACK_TRIM_DB = -12.0
_FLOAT_MAX = math.nextafter(1.0, 0.0)


@dataclass(frozen=True)
class _ProgramStereo:
    sample_rate_hz: int
    left: list[float]
    right: list[float]
    decoded_stem_count: int
    measured_stem_count: int
    worst_case_peak_sum: float
    measurement_failed: bool
    notes: tuple[str, ...]


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
    if candidate.is_absolute():
        return candidate, None

    if stems_dir is None:
        return None, "missing_stems_dir"
    return stems_dir / candidate, None


def _target_layout_id(session: Dict[str, Any]) -> str:
    raw = _coerce_str(session.get("target_layout_id")).strip()
    if not raw:
        return ""
    return _TARGET_FALLBACK_LAYOUTS.get(raw, raw)


def _selected_layout_ids(session: Dict[str, Any]) -> list[str]:
    target_layout_id = _target_layout_id(session)
    if target_layout_id:
        return [target_layout_id] if target_layout_id in _SUPPORTED_LAYOUT_IDS else []
    return ["LAYOUT.2_0"]


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


def _read_stereo_program_from_stems(session: Dict[str, Any]) -> _ProgramStereo:
    stems_dir = _resolve_stems_dir(session)
    stems = _stem_rows(session)
    notes: list[str] = []
    sample_rate_hz: int | None = None
    left: list[float] = []
    right: list[float] = []
    decoded_stem_count = 0
    measured_stem_count = 0
    worst_case_peak_sum = 0.0
    measurement_failed = False

    for stem in stems:
        stem_id = _coerce_str(stem.get("stem_id")).strip() or "<unknown>"
        source_path, resolve_reason = _resolve_stem_source_path(stem, stems_dir)
        if resolve_reason is not None or source_path is None:
            notes.append(f"{stem_id}:{resolve_reason or 'unresolved_path'}")
            measurement_failed = True
            continue

        try:
            metadata = read_wav_metadata(source_path)
            channels = _coerce_int(metadata.get("channels"))
            stem_sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
            if channels is None or channels < 1:
                raise ValueError("invalid channel count")
            if stem_sample_rate_hz is None or stem_sample_rate_hz < 1:
                raise ValueError("invalid sample rate")

            if sample_rate_hz is None:
                sample_rate_hz = stem_sample_rate_hz
            elif sample_rate_hz != stem_sample_rate_hz:
                notes.append(
                    f"{stem_id}:sample_rate_mismatch({stem_sample_rate_hz}!={sample_rate_hz})"
                )
                measurement_failed = True
                continue

            frame_cursor = 0
            stem_peak = 0.0
            for chunk in iter_wav_float64_samples(
                source_path,
                error_context="baseline mixdown renderer",
            ):
                if not chunk:
                    continue
                frame_count = len(chunk) // channels
                if frame_count <= 0 or frame_count * channels != len(chunk):
                    raise ValueError("decoder returned non-frame-aligned data")

                needed = (frame_cursor + frame_count) - len(left)
                if needed > 0:
                    left.extend([0.0] * needed)
                    right.extend([0.0] * needed)

                chunk_peak = max(abs(sample) for sample in chunk)
                if chunk_peak > stem_peak:
                    stem_peak = chunk_peak

                idx = 0
                if channels == 1:
                    for frame_index in range(frame_count):
                        value = chunk[idx]
                        idx += 1
                        target_index = frame_cursor + frame_index
                        left[target_index] += value
                        right[target_index] += value
                else:
                    for frame_index in range(frame_count):
                        value_l = chunk[idx]
                        value_r = chunk[idx + 1]
                        idx += channels
                        target_index = frame_cursor + frame_index
                        left[target_index] += value_l
                        right[target_index] += value_r

                frame_cursor += frame_count

            decoded_stem_count += 1
            measured_stem_count += 1
            worst_case_peak_sum += stem_peak
        except Exception:
            notes.append(f"{stem_id}:decode_failed")
            measurement_failed = True

    if sample_rate_hz is None:
        sample_rate_hz = _DEFAULT_SAMPLE_RATE_HZ
    if not left or not right:
        left = [0.0] * _DEFAULT_SILENCE_FRAMES
        right = [0.0] * _DEFAULT_SILENCE_FRAMES
        notes.append("rendered_silence:no_decodable_stems")
        measurement_failed = True

    return _ProgramStereo(
        sample_rate_hz=sample_rate_hz,
        left=left,
        right=right,
        decoded_stem_count=decoded_stem_count,
        measured_stem_count=measured_stem_count,
        worst_case_peak_sum=worst_case_peak_sum,
        measurement_failed=measurement_failed,
        notes=tuple(sorted(notes)),
    )


def _compute_trim(
    program: _ProgramStereo,
) -> tuple[float, float, str]:
    fallback_trim = _db_to_linear(_FALLBACK_TRIM_DB)
    if program.measurement_failed:
        return fallback_trim, _FALLBACK_TRIM_DB, "fallback_fixed_trim"

    if program.worst_case_peak_sum <= 0.0:
        return 1.0, 0.0, "unity_no_signal"

    target_peak_linear = _db_to_linear(_TARGET_PEAK_DBFS)
    trim = min(1.0, target_peak_linear / program.worst_case_peak_sum)
    trim_db = _linear_to_db(trim)
    if not math.isfinite(trim_db):
        return fallback_trim, _FALLBACK_TRIM_DB, "fallback_invalid_trim"
    return trim, trim_db, "worst_case_peak_sum"


def _speaker_sample(
    speaker_id: str,
    *,
    left: float,
    right: float,
    center: float,
) -> float:
    if speaker_id == "SPK.L":
        return left
    if speaker_id == "SPK.R":
        return right
    if speaker_id == "SPK.C":
        return center
    return 0.0


def _layout_interleaved_samples(
    layout_channel_order: Sequence[str],
    *,
    left: Sequence[float],
    right: Sequence[float],
    trim_linear: float,
) -> list[float]:
    interleaved: list[float] = []
    frame_count = min(len(left), len(right))
    for frame_index in range(frame_count):
        sample_l = _clamp_sample(left[frame_index] * trim_linear)
        sample_r = _clamp_sample(right[frame_index] * trim_linear)
        sample_c = _clamp_sample((sample_l + sample_r) * 0.5)
        for speaker_id in layout_channel_order:
            interleaved.append(
                _speaker_sample(
                    speaker_id,
                    left=sample_l,
                    right=sample_r,
                    center=sample_c,
                )
            )
    return interleaved


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


def _write_pcm24_wav(
    output_path: Path,
    *,
    interleaved_samples: Sequence[float],
    channel_count: int,
    sample_rate_hz: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(channel_count)
        handle.setsampwidth(3)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(_float_samples_to_pcm24_bytes(interleaved_samples))


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


class MixdownRenderer(RendererPlugin):
    plugin_id = "PLUGIN.RENDERER.MIXDOWN_BASELINE"

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

        out_dir = Path(output_dir)
        selected_layouts = _selected_layout_ids(session)
        requested_layout = _coerce_str(session.get("target_layout_id")).strip()
        if not selected_layouts:
            manifest["notes"] = f"unsupported_target_layout={requested_layout or '<none>'}"
            return manifest

        program = _read_stereo_program_from_stems(session)
        trim_linear, trim_db, trim_reason = _compute_trim(program)

        outputs: list[dict[str, Any]] = []
        for layout_id in selected_layouts:
            channel_order = _layout_channel_order(layout_id)
            if not channel_order:
                continue

            interleaved = _layout_interleaved_samples(
                channel_order,
                left=program.left,
                right=program.right,
                trim_linear=trim_linear,
            )
            rel_path = _output_relative_path(output_dir=out_dir, layout_id=layout_id)
            abs_path = out_dir / rel_path
            _write_pcm24_wav(
                abs_path,
                interleaved_samples=interleaved,
                channel_count=len(channel_order),
                sample_rate_hz=program.sample_rate_hz,
            )
            output_sha = sha256_file(abs_path)
            layout_slug = _layout_slug(layout_id)
            output_row: dict[str, Any] = {
                "output_id": f"OUTPUT.MIXDOWN_BASELINE.{layout_slug}.{output_sha[:12]}",
                "file_path": rel_path.as_posix(),
                "layout_id": layout_id,
                "format": "wav",
                "sample_rate_hz": program.sample_rate_hz,
                "bit_depth": 24,
                "channel_count": len(channel_order),
                "sha256": output_sha,
                "notes": (
                    f"baseline_mixdown trim_db={trim_db:.4f}"
                    f" policy={trim_reason}"
                ),
                "metadata": {
                    "headroom_policy": "worst_case_sum_to_-1dBFS",
                    "trim_db": trim_db,
                    "trim_reason": trim_reason,
                    "fallback_trim_db": _FALLBACK_TRIM_DB,
                    "target_peak_dbfs": _TARGET_PEAK_DBFS,
                    "source_stem_count": program.decoded_stem_count,
                    "measured_stem_count": program.measured_stem_count,
                    "worst_case_peak_sum": program.worst_case_peak_sum,
                    "target_layout_id": layout_id,
                    "channel_order": channel_order,
                    "center_policy": "0.5*(L+R) for SPK.C",
                },
            }
            if program.notes:
                output_row["metadata"]["warnings"] = list(program.notes)
            mapped_layout = _TARGET_FALLBACK_LAYOUTS.get(requested_layout)
            if mapped_layout == layout_id and requested_layout != layout_id:
                output_row["metadata"]["requested_layout_id"] = requested_layout
                output_row["metadata"]["rendered_layout_id"] = layout_id
            outputs.append(output_row)

        outputs.sort(key=lambda row: (_coerce_str(row.get("layout_id")), _coerce_str(row.get("file_path"))))
        manifest["outputs"] = outputs
        manifest["notes"] = (
            f"rendered_layouts={','.join(selected_layouts)}"
            f" decoded_stems={program.decoded_stem_count}"
        )
        return manifest
