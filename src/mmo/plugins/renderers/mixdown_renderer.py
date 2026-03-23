from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from mmo.dsp.buffer import AudioBufferF64, generic_channel_order
from mmo.dsp.decoders import (
    detect_format_from_path,
    is_lossless_format_id,
    iter_audio_float64_samples,
    read_audio_metadata,
)
from mmo.dsp.export_finalize import (
    build_export_finalization_receipt,
    derive_export_finalization_seed,
    export_finalize_interleaved_f64,
    resolve_dither_policy_for_bit_depth,
)
from mmo.dsp.io import sha256_file, write_wav_ixml_chunk
from mmo.dsp.process_context import build_process_context
from mmo.dsp.sample_rate import build_resampling_receipt, choose_target_rate_for_session
from mmo.core.deliverables import (
    RENDER_RESULT_SILENT_OUTPUT,
    build_output_render_result,
    canonical_warning_codes,
    is_effectively_silent_peak_linear,
)
from mmo.core.source_locator import (
    resolve_session_stems,
    resolved_stem_path,
    stem_resolution_entries,
)
from mmo.core.trace_metadata import add_trace_metadata, build_trace_ixml_payload, build_trace_metadata
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.MIXDOWN_BASELINE"
_SUPPORTED_LAYOUT_IDS: tuple[str, ...] = (
    "LAYOUT.2_0",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
    "LAYOUT.7_1_4",
    "LAYOUT.9_1_6",
)
_DEFAULT_SAMPLE_RATE_HZ = 48_000
_TARGET_PEAK_DBFS = -1.0
_FALLBACK_TRIM_DB = -12.0
_CENTER_FOLD_REDUCTION_DB = -3.0
_CENTER_FOLD_LINEAR = math.pow(10.0, _CENTER_FOLD_REDUCTION_DB / 20.0)
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
    resampling: dict[str, Any]


@dataclass(frozen=True)
class _StemDecodePlan:
    stem_id: str
    source_path: Path
    source_format_id: str
    channels: int
    source_sample_rate_hz: int


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


def _export_job_id(session: Dict[str, Any]) -> str:
    return _coerce_str(session.get("report_id")).strip() or _PLUGIN_ID


def _resolve_explicit_render_sample_rate_hz(session: Dict[str, Any]) -> tuple[int | None, str | None]:
    candidates: list[tuple[str, Any]] = [
        ("explicit_user_choice", session.get("render_sample_rate_hz")),
    ]
    options_payload = session.get("options")
    if isinstance(options_payload, dict):
        candidates.append(("explicit_user_choice", options_payload.get("render_sample_rate_hz")))
    candidates.append(("render_contract_target", session.get("sample_rate_hz")))

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


def _selected_layout_ids() -> list[str]:
    return list(_SUPPORTED_LAYOUT_IDS)


def _layout_channel_order(layout_id: str) -> list[str]:
    try:
        process_ctx = build_process_context(layout_id)
    except ValueError:
        return []
    return list(process_ctx.channel_order)


def _read_stereo_program_from_stems(session: Dict[str, Any]) -> _ProgramStereo:
    stems = _stem_rows(session)
    notes: list[str] = []
    left: list[float] = []
    right: list[float] = []
    decoded_stem_count = 0
    measured_stem_count = 0
    worst_case_peak_sum = 0.0
    measurement_failed = False
    decode_plans: list[_StemDecodePlan] = []
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
            notes.append(f"{stem_id}:{resolve_reason or 'unresolved_path'}")
            measurement_failed = True
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "decoder_warnings": stem_warning_rows,
                }
            )
            continue

        try:
            source_format_id = detect_format_from_path(source_path)
            if source_format_id == "unknown":
                notes.append(f"{stem_id}:unsupported_format")
                measurement_failed = True
                stem_meta_rows.append(
                    {
                        "stem_id": stem_id,
                        "decoder_warnings": stem_warning_rows,
                    }
                )
                continue

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
                notes.append(f"{stem_id}:lossy_input")
                stem_warning_rows.append(
                    _resampling_warning_row(
                        stem_id=stem_id,
                        warning="lossy_source",
                        format_id=source_format_id,
                    )
                )

            channels = _coerce_int(metadata.get("channels"))
            stem_sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
            if channels is None or channels < 1:
                raise ValueError("invalid channel count")
            if stem_sample_rate_hz is None or stem_sample_rate_hz < 1:
                stem_warning_rows.append(
                    _resampling_warning_row(
                        stem_id=stem_id,
                        warning="missing_sample_rate_metadata",
                        format_id=source_format_id,
                    )
                )
                raise ValueError("invalid sample rate")
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
            decode_plans.append(
                _StemDecodePlan(
                    stem_id=stem_id,
                    source_path=source_path,
                    source_format_id=source_format_id,
                    channels=channels,
                    source_sample_rate_hz=stem_sample_rate_hz,
                )
            )
        except Exception:
            notes.append(f"{stem_id}:decode_failed")
            measurement_failed = True
            stem_meta_rows.append(
                {
                    "stem_id": stem_id,
                    "decoder_warnings": stem_warning_rows,
                }
            )

    explicit_sample_rate_hz, explicit_sample_rate_reason = _resolve_explicit_render_sample_rate_hz(session)
    sample_rate_hz, selection_receipt = choose_target_rate_for_session(
        stem_meta_rows,
        explicit_rate=explicit_sample_rate_hz,
        explicit_rate_reason=explicit_sample_rate_reason,
        default=_DEFAULT_SAMPLE_RATE_HZ,
    )
    notes.append(
        f"render_sample_rate_selected:{sample_rate_hz}:"
        f"{_coerce_str(selection_receipt.get('sample_rate_policy')).strip()}:"
        f"{_coerce_str(selection_receipt.get('sample_rate_policy_reason')).strip()}"
    )

    resampled_stems: list[dict[str, Any]] = []
    native_rate_stems: list[dict[str, Any]] = []
    for plan in decode_plans:
        frame_cursor = 0
        stem_peak = 0.0
        if plan.source_sample_rate_hz != sample_rate_hz:
            notes.append(
                f"{plan.stem_id}:resampled({plan.source_sample_rate_hz}->{sample_rate_hz})"
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
        try:
            source_channel_order = generic_channel_order(plan.channels)
            for chunk in iter_audio_float64_samples(
                plan.source_path,
                error_context="baseline mixdown renderer",
                metadata={
                    "channels": plan.channels,
                    "sample_rate_hz": plan.source_sample_rate_hz,
                },
                target_sample_rate_hz=sample_rate_hz,
            ):
                if not chunk:
                    continue
                chunk_buffer = AudioBufferF64(
                    data=chunk,
                    channels=plan.channels,
                    channel_order=source_channel_order,
                    sample_rate_hz=sample_rate_hz,
                )
                frame_count = chunk_buffer.frame_count
                if frame_count <= 0:
                    continue

                needed = (frame_cursor + frame_count) - len(left)
                if needed > 0:
                    left.extend([0.0] * needed)
                    right.extend([0.0] * needed)

                chunk_peak = max(chunk_buffer.peak_per_channel())
                if chunk_peak > stem_peak:
                    stem_peak = chunk_peak

                planar_chunk = chunk_buffer.to_planar_lists()
                if plan.channels == 1:
                    mono_samples = planar_chunk[0]
                    for frame_index, value in enumerate(mono_samples):
                        target_index = frame_cursor + frame_index
                        left[target_index] += value
                        right[target_index] += value
                else:
                    left_channel = planar_chunk[0]
                    right_channel = planar_chunk[1]
                    for frame_index in range(frame_count):
                        target_index = frame_cursor + frame_index
                        left[target_index] += left_channel[frame_index]
                        right[target_index] += right_channel[frame_index]

                frame_cursor += frame_count

            if frame_cursor > 0:
                decoded_stem_count += 1
                measured_stem_count += 1
                worst_case_peak_sum += stem_peak
            else:
                notes.append(f"{plan.stem_id}:decode_failed")
                measurement_failed = True
        except Exception:
            notes.append(f"{plan.stem_id}:decode_failed")
            measurement_failed = True

    if not left or not right:
        left = []
        right = []
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
        resampling=build_resampling_receipt(
            selection=selection_receipt,
            output_sample_rate_hz=sample_rate_hz,
            input_stem_count=len(stems),
            planned_stem_count=len(decode_plans),
            decoded_stem_count=decoded_stem_count,
            skipped_stem_count=max(0, len(stems) - len(decode_plans)),
            resampled_stems=resampled_stems,
            native_rate_stems=native_rate_stems,
            decoder_warnings=list(selection_receipt.get("decoder_warnings") or []),
            resample_stage="decode",
            resample_method_id="linear_interpolation_v1",
        ),
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


def _layout_audio_buffer(
    layout_channel_order: Sequence[str],
    *,
    left: Sequence[float],
    right: Sequence[float],
    trim_linear: float,
    sample_rate_hz: int,
) -> AudioBufferF64:
    interleaved: list[float] = []
    frame_count = min(len(left), len(right))
    for frame_index in range(frame_count):
        sample_l = _clamp_sample(left[frame_index] * trim_linear)
        sample_r = _clamp_sample(right[frame_index] * trim_linear)
        sample_c = _clamp_sample((sample_l + sample_r) * 0.5 * _CENTER_FOLD_LINEAR)
        for speaker_id in layout_channel_order:
            interleaved.append(
                _speaker_sample(
                    speaker_id,
                    left=sample_l,
                    right=sample_r,
                    center=sample_c,
                )
            )
    return AudioBufferF64(
        data=interleaved,
        channels=len(layout_channel_order),
        channel_order=tuple(layout_channel_order),
        sample_rate_hz=sample_rate_hz,
    )


def _write_pcm_wav(
    output_path: Path,
    *,
    buffer: AudioBufferF64,
    bit_depth: int,
    dither_policy: str,
    seed: int,
    trace_metadata: dict[str, str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pcm_bytes = export_finalize_interleaved_f64(
        list(buffer.data),
        channels=buffer.channels,
        bit_depth=bit_depth,
        dither_policy=dither_policy,
        seed=seed,
    )
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(buffer.channels)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(buffer.sample_rate_hz)
        handle.writeframes(pcm_bytes)
    write_wav_ixml_chunk(output_path, build_trace_ixml_payload(trace_metadata))


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
            "stem_resolution": stem_resolution_entries(resolve_session_stems(session)),
        }
        if output_dir is None:
            manifest["notes"] = "missing_output_dir"
            return manifest

        out_dir = Path(output_dir)
        selected_layouts = _selected_layout_ids()

        program = _read_stereo_program_from_stems(session)
        trim_linear, trim_db, trim_reason = _compute_trim(program)

        outputs: list[dict[str, Any]] = []
        for layout_id in selected_layouts:
            channel_order = _layout_channel_order(layout_id)
            if not channel_order:
                continue
            bit_depth = 24
            dither_policy = resolve_dither_policy_for_bit_depth(bit_depth)
            render_seed = _session_render_seed(session)
            export_seed = derive_export_finalization_seed(
                job_id=_export_job_id(session),
                layout_id=layout_id,
                render_seed=render_seed,
            )

            output_buffer = _layout_audio_buffer(
                channel_order,
                left=program.left,
                right=program.right,
                trim_linear=trim_linear,
                sample_rate_hz=program.sample_rate_hz,
            )
            rel_path = _output_relative_path(output_dir=out_dir, layout_id=layout_id)
            abs_path = out_dir / rel_path
            trace_metadata = build_trace_metadata(
                {
                    "session": session,
                    "layout_id": layout_id,
                    "render_seed": render_seed,
                }
            )
            _write_pcm_wav(
                abs_path,
                buffer=output_buffer,
                bit_depth=bit_depth,
                dither_policy=dither_policy,
                seed=export_seed,
                trace_metadata=trace_metadata,
            )
            output_sha = sha256_file(abs_path)
            layout_slug = _layout_slug(layout_id)
            rendered_frame_count = (
                len(output_buffer.data) // output_buffer.channels
                if output_buffer.channels > 0
                else 0
            )
            rendered_peak_linear = (
                max(abs(sample) for sample in output_buffer.data)
                if output_buffer.data
                else 0.0
            )
            render_warning_codes = canonical_warning_codes(
                list(program.notes),
                list(program.resampling.get("decoder_warnings") or []),
            )
            if rendered_frame_count > 0 and is_effectively_silent_peak_linear(rendered_peak_linear):
                render_warning_codes = canonical_warning_codes(
                    render_warning_codes,
                    [RENDER_RESULT_SILENT_OUTPUT],
                )
            output_row: dict[str, Any] = {
                "output_id": f"OUTPUT.MIXDOWN_BASELINE.{layout_slug}.{output_sha[:12]}",
                "file_path": rel_path.as_posix(),
                "layout_id": layout_id,
                "format": "wav",
                "sample_rate_hz": output_buffer.sample_rate_hz,
                "bit_depth": bit_depth,
                "channel_count": output_buffer.channels,
                "sha256": output_sha,
                "notes": (
                    f"baseline_mixdown trim_db={trim_db:.4f}"
                    f" policy={trim_reason}"
                ),
                "export_finalization_receipt": build_export_finalization_receipt(
                    bit_depth=bit_depth,
                    dither_policy=dither_policy,
                    job_id=_export_job_id(session),
                    layout_id=layout_id,
                    render_seed=render_seed,
                    target_peak_dbfs=_TARGET_PEAK_DBFS,
                ),
                "metadata": {
                    "artifact_role": "master",
                    "headroom_policy": "worst_case_sum_to_-1dBFS",
                    "trim_db": trim_db,
                    "trim_reason": trim_reason,
                    "fallback_trim_db": _FALLBACK_TRIM_DB,
                    "target_peak_dbfs": _TARGET_PEAK_DBFS,
                    "source_stem_count": program.decoded_stem_count,
                    "prepared_stem_count": program.decoded_stem_count,
                    "measured_stem_count": program.measured_stem_count,
                    "worst_case_peak_sum": program.worst_case_peak_sum,
                    "target_layout_id": layout_id,
                    "channel_order": list(output_buffer.channel_order),
                    "resampling": program.resampling,
                    "render_result": build_output_render_result(
                        artifact_role="master",
                        planned_stem_count=_coerce_int(
                            program.resampling.get("counts", {}).get("planned_stem_count")
                        ),
                        decoded_stem_count=program.decoded_stem_count,
                        prepared_stem_count=program.decoded_stem_count,
                        skipped_stem_count=_coerce_int(
                            program.resampling.get("counts", {}).get("skipped_stem_count")
                        ),
                        rendered_frame_count=rendered_frame_count,
                        duration_seconds=(
                            rendered_frame_count / output_buffer.sample_rate_hz
                            if output_buffer.sample_rate_hz > 0
                            else None
                        ),
                        warning_codes=render_warning_codes,
                        target_layout_id=layout_id,
                    ),
                    "center_policy": (
                        "0.5*(L+R)*center_reduction for SPK.C"
                        f" (center_reduction_db={_CENTER_FOLD_REDUCTION_DB:.1f})"
                    ),
                    "center_reduction_db": _CENTER_FOLD_REDUCTION_DB,
                },
            }
            output_row["metadata"] = add_trace_metadata(
                output_row.get("metadata"),
                {
                    "session": session,
                    "layout_id": layout_id,
                    "render_seed": render_seed,
                },
            )
            if program.notes:
                output_row["metadata"]["warnings"] = list(program.notes)
            decoder_warnings = program.resampling.get("decoder_warnings")
            if isinstance(decoder_warnings, list) and decoder_warnings:
                existing_warnings = output_row["metadata"].get("warnings")
                normalized_warnings = (
                    list(existing_warnings)
                    if isinstance(existing_warnings, list)
                    else []
                )
                normalized_warnings.extend(
                    f"decoder_warning:{_coerce_str(row.get('stem_id')).strip()}:{_coerce_str(row.get('warning')).strip()}"
                    for row in decoder_warnings
                    if isinstance(row, dict)
                )
                output_row["metadata"]["warnings"] = sorted(set(normalized_warnings))
            outputs.append(output_row)

        outputs.sort(key=lambda row: (_coerce_str(row.get("layout_id")), _coerce_str(row.get("file_path"))))
        manifest["outputs"] = outputs
        manifest["notes"] = (
            f"rendered_layouts={','.join(selected_layouts)}"
            f" decoded_stems={program.decoded_stem_count}"
        )
        return manifest
