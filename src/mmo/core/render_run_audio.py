"""Deterministic offline audio rendering for ``render-run``."""

from __future__ import annotations

import math
import random
import struct
import subprocess
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

from mmo.core.render_execute import resolve_ffmpeg_version
from mmo.core.render_reporting import build_render_report_from_plan
from mmo.dsp.backends.ffmpeg_decode import (
    build_ffmpeg_decode_command,
    iter_ffmpeg_float64_samples,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import read_metadata
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.transcode import (
    LOSSLESS_OUTPUT_FORMATS,
    ffmpeg_determinism_flags,
    transcode_wav_to_format,
)

_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_WAV_EXTENSIONS = frozenset({".wav", ".wave"})
_FFMPEG_EXTENSIONS = frozenset({".flac", ".wv", ".aif", ".aiff", ".m4a"})
_LOSSY_EXTENSIONS = frozenset({".mp3", ".aac", ".ogg", ".opus"})
_SOURCE_EXTENSIONS = _WAV_EXTENSIONS | _FFMPEG_EXTENSIONS | _LOSSY_EXTENSIONS
_BIT_DEPTHS = frozenset({16, 24, 32})
_INTERMEDIATE_ROOT = ".mmo_tmp/render_run"
_FLOAT_MAX = math.nextafter(1.0, 0.0)
_GAIN_V0_PLUGIN_ID = "gain_v0"

ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED = "ISSUE.RENDER.RUN.DOWNMIX_SCOPE_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID = "ISSUE.RENDER.RUN.SOURCE_STEMS_DIR_INVALID"
ISSUE_RENDER_RUN_SOURCE_MISSING = "ISSUE.RENDER.RUN.SOURCE_MISSING"
ISSUE_RENDER_RUN_SOURCE_COUNT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_COUNT_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_FORMAT_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_LAYOUT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_LAYOUT_UNSUPPORTED"
ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED = "ISSUE.RENDER.RUN.OUTPUT_FORMAT_UNSUPPORTED"
ISSUE_RENDER_RUN_OPTION_UNSUPPORTED = "ISSUE.RENDER.RUN.OPTION_UNSUPPORTED"
ISSUE_RENDER_RUN_FFMPEG_REQUIRED = "ISSUE.RENDER.RUN.FFMPEG_REQUIRED"
ISSUE_RENDER_RUN_DECODE_FAILED = "ISSUE.RENDER.RUN.DECODE_FAILED"
ISSUE_RENDER_RUN_ENCODE_FAILED = "ISSUE.RENDER.RUN.ENCODE_FAILED"
ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID = "ISSUE.RENDER.RUN.PLUGIN_CHAIN_INVALID"
ISSUE_RENDER_RUN_PLUGIN_SOURCE_FORMAT_UNSUPPORTED = (
    "ISSUE.RENDER.RUN.PLUGIN_SOURCE_FORMAT_UNSUPPORTED"
)


class RenderRunRefusalError(ValueError):
    """Raised when ``render-run`` audio execution must refuse a request."""

    def __init__(self, *, issue_id: str, message: str) -> None:
        self.issue_id = issue_id
        super().__init__(f"{issue_id}: {message}")


def request_dry_run_enabled(request_payload: dict[str, Any]) -> bool:
    """Return True unless options explicitly opt into execution."""
    options = request_payload.get("options")
    if not isinstance(options, dict):
        return True
    dry_run = options.get("dry_run")
    if isinstance(dry_run, bool):
        return dry_run
    return True


def build_render_report_with_audio(
    *,
    plan_payload: dict[str, Any],
    request_payload: dict[str, Any],
    scene_payload: dict[str, Any],
    scene_path: Path,
    report_out_path: Path,
    capture_execute_trace: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    """Render stereo deliverables and return report payload plus execute job trace."""
    job = _single_stereo_job_or_raise(plan_payload)
    job_id = _coerce_str(job.get("job_id")).strip() or "JOB.001"
    source_path = _resolve_single_source_or_raise(scene_payload)
    source_metadata = _read_source_metadata_or_raise(source_path)
    _validate_source_layout_or_raise(source_metadata)

    options = _coerce_dict(request_payload.get("options"))
    source_rate_hz = _coerce_int(source_metadata.get("sample_rate_hz")) or 0
    requested_rate_hz = _coerce_int(options.get("sample_rate_hz"))
    if requested_rate_hz is not None and requested_rate_hz != source_rate_hz:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "sample_rate_hz override is not supported for PR52 render-run. "
                f"requested={requested_rate_hz}, source={source_rate_hz}"
            ),
        )

    output_bit_depth = _resolve_output_bit_depth(
        requested_bit_depth=_coerce_int(options.get("bit_depth")),
        source_bit_depth=_coerce_int(source_metadata.get("bits_per_sample")),
    )
    output_formats = _job_output_formats_or_raise(job)

    planned_outputs = _planned_outputs_by_format(job)
    scene_anchor = _scene_anchor_root(
        request_scene_path=_coerce_str(request_payload.get("scene_path")),
        scene_path=scene_path,
    )
    report_dir = report_out_path.resolve().parent
    plugin_chain = _plugin_chain_from_request(request_payload)
    plugin_chain_enabled = bool(plugin_chain)
    plugin_step_events: list[dict[str, Any]] = []

    wav_path: Path
    keep_wav_output = "wav" in output_formats
    wav_candidate = planned_outputs.get("wav")
    if isinstance(wav_candidate, str) and wav_candidate:
        wav_path = _resolve_output_path(
            raw_path=wav_candidate,
            scene_anchor=scene_anchor,
            report_dir=report_dir,
        )
    elif keep_wav_output:
        wav_path = _fallback_output_path(
            report_dir=report_dir,
            job_id=job_id,
            output_format="wav",
        )
    else:
        wav_path = _intermediate_wav_path(
            report_dir=report_dir,
            job_id=job_id,
        )

    ffmpeg_cmd_for_decode: Sequence[str] | None = None
    ffmpeg_cmd_for_encode: Sequence[str] | None = None
    source_extension = source_path.suffix.lower()
    needs_ffmpeg_decode = source_extension in _FFMPEG_EXTENSIONS
    needs_ffmpeg_encode = any(fmt != "wav" for fmt in output_formats)
    needs_ffmpeg_for_trace = keep_wav_output and capture_execute_trace
    if needs_ffmpeg_decode or needs_ffmpeg_encode or needs_ffmpeg_for_trace:
        ffmpeg_cmd_for_decode = resolve_ffmpeg_cmd()
        ffmpeg_cmd_for_encode = ffmpeg_cmd_for_decode
        if ffmpeg_cmd_for_decode is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message=(
                    "ffmpeg is required for requested render-run operation "
                    "(decode and/or encode lossless non-WAV audio, "
                    "or deterministic execution tracing)."
                ),
            )

    ffmpeg_command_rows: list[dict[str, Any]] = []

    try:
        if plugin_chain_enabled:
            if capture_execute_trace and source_extension in _FFMPEG_EXTENSIONS:
                if ffmpeg_cmd_for_decode is None:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                        message="ffmpeg is required to decode non-WAV source audio.",
                    )
                ffmpeg_command_rows.append(
                    {
                        "args": build_ffmpeg_decode_command(source_path, ffmpeg_cmd_for_decode),
                        "determinism_flags": [],
                    }
                )
            plugin_step_events = _render_wav_with_plugin_chain(
                source_path=source_path,
                output_path=wav_path,
                sample_rate_hz=source_rate_hz,
                bit_depth=output_bit_depth,
                plugin_chain=plugin_chain,
                ffmpeg_cmd_for_decode=ffmpeg_cmd_for_decode,
            )
        else:
            float_samples_iter: Iterator[list[float]]
            if source_extension in _WAV_EXTENSIONS:
                float_samples_iter = iter_wav_float64_samples(
                    source_path,
                    error_context="render-run stereo downmix",
                )
            else:
                if ffmpeg_cmd_for_decode is None:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                        message="ffmpeg is required to decode non-WAV source audio.",
                    )
                if capture_execute_trace:
                    ffmpeg_command_rows.append(
                        {
                            "args": build_ffmpeg_decode_command(source_path, ffmpeg_cmd_for_decode),
                            "determinism_flags": [],
                        }
                    )
                float_samples_iter = iter_ffmpeg_float64_samples(
                    source_path,
                    ffmpeg_cmd_for_decode,
                )

            _write_stereo_wav(
                float_samples_iter=float_samples_iter,
                output_path=wav_path,
                sample_rate_hz=source_rate_hz,
                bit_depth=output_bit_depth,
            )
    except RenderRunRefusalError:
        raise
    except ValueError as exc:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
            message=f"Failed to decode and render source audio: {exc}",
        ) from exc

    output_files: list[dict[str, Any]] = []
    try:
        if keep_wav_output and capture_execute_trace:
            if ffmpeg_cmd_for_encode is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                    message=(
                        "ffmpeg is required to normalize WAV output metadata "
                        "for deterministic execution tracing."
                    ),
                )
            _normalize_wav_for_determinism(
                ffmpeg_cmd=ffmpeg_cmd_for_encode,
                wav_path=wav_path,
                bit_depth=output_bit_depth,
                command_rows=ffmpeg_command_rows,
            )

        if keep_wav_output:
            output_files.append(
                _output_file_payload(
                    output_path=wav_path,
                    output_format="wav",
                    sample_rate_hz=source_rate_hz,
                    bit_depth=output_bit_depth,
                )
            )

        for output_format in output_formats:
            if output_format == "wav":
                continue
            target_path = _resolve_output_path(
                raw_path=planned_outputs.get(output_format, ""),
                scene_anchor=scene_anchor,
                report_dir=report_dir,
                fallback=_fallback_output_path(
                    report_dir=report_dir,
                    job_id=_coerce_str(job.get("job_id")).strip() or "JOB.001",
                    output_format=output_format,
                ),
            )
            try:
                if ffmpeg_cmd_for_encode is None:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                        message="ffmpeg is required to encode non-WAV deliverables.",
                    )
                transcode_command_rows: list[list[str]] | None = []
                if not capture_execute_trace:
                    transcode_command_rows = None
                transcode_wav_to_format(
                    ffmpeg_cmd_for_encode,
                    wav_path,
                    target_path,
                    output_format,
                    command_recorder=transcode_command_rows,
                )
                if transcode_command_rows:
                    ffmpeg_command_rows.append(
                        {
                            "args": transcode_command_rows[-1],
                            "determinism_flags": list(
                                ffmpeg_determinism_flags(for_wav=False)
                            ),
                        }
                    )
            except RenderRunRefusalError:
                raise
            except ValueError as exc:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                    message=f"Failed to encode {output_format} deliverable: {exc}",
                ) from exc
            output_files.append(
                _output_file_payload(
                    output_path=target_path,
                    output_format=output_format,
                    sample_rate_hz=source_rate_hz,
                    bit_depth=output_bit_depth,
                )
            )
    finally:
        if not keep_wav_output:
            try:
                if wav_path.exists():
                    wav_path.unlink()
            except OSError:
                # Keep deterministic behavior: refusal path should be from prior stable error.
                pass

    output_files.sort(key=lambda item: _output_sort_key(_coerce_str(item.get("format"))))

    report_payload = build_render_report_from_plan(
        plan_payload,
        status="completed",
        reason="rendered",
    )
    report_jobs = report_payload.get("jobs")
    if not isinstance(report_jobs, list) or len(report_jobs) != 1:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message="Expected exactly one report job for stereo render-run execution.",
        )
    report_job = report_jobs[0]
    if not isinstance(report_job, dict):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message="Expected report job payload to be an object.",
        )
    report_job["status"] = "completed"
    report_job["output_files"] = output_files
    report_notes = [
        "reason: rendered",
        f"source_file: {source_path.resolve().as_posix()}",
        "source_layout_id: LAYOUT.2_0",
        "target_layout_id: LAYOUT.2_0",
    ]
    if plugin_chain_enabled:
        report_notes.append("macro_mix applied as linear blend.")
    report_job["notes"] = report_notes

    execute_job_row: dict[str, Any] | None = None
    if capture_execute_trace:
        ffmpeg_cmd_for_trace = ffmpeg_cmd_for_encode or ffmpeg_cmd_for_decode
        if ffmpeg_cmd_for_trace is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required to capture deterministic execute traces.",
            )
        output_paths = _output_paths_from_rows(output_files)
        if not output_paths:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                message="No output paths were produced for deterministic execute tracing.",
            )
        execute_job_row = {
            "job_id": job_id,
            "input_paths": [source_path.resolve()],
            "output_paths": output_paths,
            "ffmpeg_version": resolve_ffmpeg_version(ffmpeg_cmd_for_trace),
            "ffmpeg_commands": ffmpeg_command_rows,
        }
    return report_payload, execute_job_row, plugin_step_events


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


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, float) and value in (0.0, 1.0):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _plugin_chain_from_request(request_payload: dict[str, Any]) -> list[dict[str, Any]]:
    options = _coerce_dict(request_payload.get("options"))
    if "plugin_chain" not in options:
        return []
    raw_chain = options.get("plugin_chain")
    if not isinstance(raw_chain, list) or not raw_chain:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message="options.plugin_chain must be a non-empty list when provided.",
        )
    normalized_chain: list[dict[str, Any]] = []
    for stage_index, raw_stage in enumerate(raw_chain, start=1):
        if not isinstance(raw_stage, dict):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"options.plugin_chain[{stage_index}] must be an object.",
            )
        plugin_id = _coerce_str(raw_stage.get("plugin_id")).strip().lower()
        if not plugin_id:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"options.plugin_chain[{stage_index}].plugin_id is required.",
            )
        normalized_chain.append(
            {
                "plugin_id": plugin_id,
                "params": _coerce_dict(raw_stage.get("params")),
            }
        )
    return normalized_chain


def _render_wav_with_plugin_chain(
    *,
    source_path: Path,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
    plugin_chain: list[dict[str, Any]],
    ffmpeg_cmd_for_decode: Sequence[str] | None,
) -> list[dict[str, Any]]:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "options.plugin_chain requires numpy runtime support. "
                "Install numpy or remove plugin_chain from the request."
            ),
        ) from exc

    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    stereo_samples = _read_stereo_source_float32(
        source_path,
        ffmpeg_cmd=ffmpeg_cmd_for_decode,
    )
    frame_count = int(stereo_samples.shape[0])

    source_posix = source_path.resolve().as_posix()
    output_posix = output_path.resolve().as_posix()
    step_events: list[dict[str, Any]] = [
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain source loaded",
            "why": "Loaded stereo source into float32 buffer for deterministic plugin execution.",
            "where": [source_posix],
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.SOURCE_LOADED"],
                "paths": [source_posix],
                "metrics": [
                    {"name": "channel_count", "value": 2},
                    {"name": "frame_count", "value": frame_count},
                ],
            },
        },
    ]

    rendered = stereo_samples
    for stage_index, stage in enumerate(plugin_chain, start=1):
        plugin_id = _coerce_str(stage.get("plugin_id")).strip().lower()
        params = _coerce_dict(stage.get("params"))
        if plugin_id != _GAIN_V0_PLUGIN_ID:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    "Unsupported plugin_chain stage. "
                    f"stage={stage_index}, plugin_id={plugin_id or '(missing)'}"
                ),
            )
        gain_db = _coerce_float(params.get("gain_db"))
        if gain_db is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{_GAIN_V0_PLUGIN_ID} requires numeric params.gain_db.",
            )
        bypass_raw = params.get("bypass")
        bypass = False
        if bypass_raw is not None:
            bypass = _coerce_bool(bypass_raw)
            if bypass is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=f"{_GAIN_V0_PLUGIN_ID} requires boolean params.bypass when provided.",
                )
        raw_macro_mix = params.get("macro_mix")
        if raw_macro_mix is None:
            macro_mix = 1.0
            macro_mix_input = 1.0
        else:
            macro_mix_input = _coerce_float(raw_macro_mix)
            if macro_mix_input is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=(
                        f"{_GAIN_V0_PLUGIN_ID} requires numeric params.macro_mix "
                        "in [0.0, 1.0] or [0.0, 100.0]."
                    ),
                )
            if 0.0 <= macro_mix_input <= 1.0:
                macro_mix = macro_mix_input
            elif 0.0 <= macro_mix_input <= 100.0:
                macro_mix = macro_mix_input / 100.0
            else:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=(
                        f"{_GAIN_V0_PLUGIN_ID} requires params.macro_mix "
                        "in [0.0, 1.0] or [0.0, 100.0]."
                    ),
                )
        linear_gain = float(math.pow(10.0, gain_db / 20.0))
        if bypass:
            stage_what = "plugin stage bypassed"
            stage_why = (
                "Bypass enabled; preserved dry stereo float32 buffer without gain "
                "or wet/dry mixing."
            )
        else:
            stage_what = "plugin stage applied"
            wet = np.multiply(
                rendered,
                np.float32(linear_gain),
                dtype=np.float32,
            )
            wet = np.clip(wet, -1.0, 1.0).astype(np.float32, copy=False)
            if macro_mix <= 0.0:
                stage_why = "macro_mix=0 selected dry signal path (linear blend endpoint)."
            elif macro_mix >= 1.0:
                rendered = wet
                stage_why = "macro_mix=1 selected fully wet signal path."
            else:
                dry = rendered
                rendered = np.add(
                    np.multiply(
                        dry,
                        np.float32(1.0 - macro_mix),
                        dtype=np.float32,
                    ),
                    np.multiply(
                        wet,
                        np.float32(macro_mix),
                        dtype=np.float32,
                    ),
                    dtype=np.float32,
                )
                rendered = np.clip(rendered, -1.0, 1.0).astype(np.float32, copy=False)
                stage_why = (
                    "Applied gain_v0 wet path and macro_mix as a linear dry/wet blend."
                )
        stage_token = f"plugin_chain.stage.{stage_index:03d}.{plugin_id}"
        step_events.append(
            {
                "kind": "action",
                "scope": "render",
                "what": stage_what,
                "why": stage_why,
                "where": [source_posix, stage_token],
                "confidence": None,
                "evidence": {
                    "codes": ["RENDER.RUN.PLUGIN.STAGE_APPLIED"],
                    "ids": [plugin_id],
                    "metrics": [
                        {"name": "stage_index", "value": stage_index},
                        {"name": "gain_db", "value": gain_db},
                        {"name": "macro_mix", "value": macro_mix},
                        {"name": "macro_mix_input", "value": macro_mix_input},
                        {"name": "bypass", "value": 1.0 if bypass else 0.0},
                    ],
                },
            }
        )

    _write_stereo_pcm_wav_from_float32(
        float32_samples=rendered,
        output_path=output_path,
        sample_rate_hz=sample_rate_hz,
        bit_depth=bit_depth,
    )
    step_events.append(
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain output written",
            "why": "Wrote deterministic PCM WAV from plugin-chain float32 output buffer.",
            "where": [output_posix],
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.OUTPUT_WRITTEN"],
                "paths": [output_posix],
                "metrics": [
                    {"name": "bit_depth", "value": bit_depth},
                    {"name": "frame_count", "value": frame_count},
                    {"name": "stage_count", "value": len(plugin_chain)},
                ],
            },
        }
    )
    return step_events


def _read_stereo_source_float32(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
) -> Any:
    import numpy as np

    source_extension = path.suffix.lower()
    float_samples_iter: Iterator[list[float]]
    if source_extension in _WAV_EXTENSIONS:
        float_samples_iter = iter_wav_float64_samples(
            path,
            error_context="render-run plugin-chain decode",
        )
    else:
        if ffmpeg_cmd is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required to decode non-WAV source audio.",
            )
        float_samples_iter = iter_ffmpeg_float64_samples(path, ffmpeg_cmd)

    chunks: list[Any] = []
    for float_samples in float_samples_iter:
        if len(float_samples) % 2 != 0:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message="Decoded sample stream is not frame-aligned for stereo.",
            )
        if not float_samples:
            continue
        chunk = np.asarray(float_samples, dtype=np.float32).reshape(-1, 2)
        chunks.append(chunk)
    if not chunks:
        return np.zeros((0, 2), dtype=np.float32)
    return np.concatenate(chunks, axis=0).astype(np.float32, copy=False)


def _write_stereo_pcm_wav_from_float32(
    *,
    float32_samples: Any,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
) -> None:
    import numpy as np

    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    samples = np.asarray(float32_samples, dtype=np.float32)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message="Plugin-chain runner expects a stereo float32 sample matrix.",
        )
    interleaved = samples.reshape(-1)
    pcm_bytes = _float32_to_pcm_bytes(interleaved, bit_depth)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm_bytes)


def _float32_to_pcm_bytes(float_samples: Any, bit_depth: int) -> bytes:
    import numpy as np

    samples = np.asarray(float_samples, dtype=np.float32)
    samples64 = np.asarray(samples, dtype=np.float64)

    if bit_depth == 16:
        scaled = np.rint(samples64 * float(2**15))
        clamped = np.clip(scaled, -32768.0, 32767.0).astype("<i2")
        return clamped.tobytes()
    if bit_depth == 24:
        scaled = np.rint(samples64 * float(2**23))
        clamped = np.clip(scaled, -8388608.0, 8388607.0).astype(np.int32)
        unsigned = (clamped & 0xFFFFFF).astype(np.uint32)
        data = np.empty(unsigned.size * 3, dtype=np.uint8)
        data[0::3] = (unsigned & 0xFF).astype(np.uint8)
        data[1::3] = ((unsigned >> 8) & 0xFF).astype(np.uint8)
        data[2::3] = ((unsigned >> 16) & 0xFF).astype(np.uint8)
        return data.tobytes()
    if bit_depth == 32:
        scaled = np.rint(samples64 * float(2**31))
        clamped = np.clip(scaled, -2147483648.0, 2147483647.0).astype("<i4")
        return clamped.tobytes()
    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
        message=f"Unsupported output bit depth: {bit_depth}",
    )


def _single_stereo_job_or_raise(plan_payload: dict[str, Any]) -> dict[str, Any]:
    jobs = plan_payload.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 1:
        job_count = len(jobs) if isinstance(jobs, list) else 0
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message=(
                "PR52 render-run supports exactly one job "
                "(single source stereo -> stereo target). "
                f"job_count={job_count}"
            ),
        )
    job = jobs[0]
    if not isinstance(job, dict):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message="PR52 render-run supports only object job entries.",
        )

    target_layout_id = _coerce_str(job.get("target_layout_id")).strip()
    if target_layout_id != _STEREO_LAYOUT_ID:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message=(
                "PR52 render-run only supports stereo targets. "
                f"target_layout_id={target_layout_id or '(missing)'}"
            ),
        )

    routing_plan_path = _coerce_str(job.get("routing_plan_path")).strip()
    if routing_plan_path:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message=(
                "PR52 render-run does not support routing_plan_path yet. "
                f"routing_plan_path={routing_plan_path}"
            ),
        )

    downmix_routes = job.get("downmix_routes")
    if isinstance(downmix_routes, list) and downmix_routes:
        first_route = downmix_routes[0]
        if not isinstance(first_route, dict):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message="PR52 render-run requires object downmix_routes entries.",
            )
        route_from = _coerce_str(first_route.get("from_layout_id")).strip()
        route_to = _coerce_str(first_route.get("to_layout_id")).strip()
        route_kind = _coerce_str(first_route.get("kind")).strip()
        if route_from != _STEREO_LAYOUT_ID or route_to != _STEREO_LAYOUT_ID:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message=(
                    "PR52 render-run supports only identity stereo routes. "
                    f"route={route_from or '(missing)'}->{route_to or '(missing)'}"
                ),
            )
        if route_kind and route_kind != "direct":
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message=(
                    "PR52 render-run supports only direct stereo routes. "
                    f"route_kind={route_kind}"
                ),
            )
    return job


def _resolve_single_source_or_raise(scene_payload: dict[str, Any]) -> Path:
    source_payload = scene_payload.get("source")
    if not isinstance(source_payload, dict):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message="scene.source must be an object with stems_dir.",
        )
    stems_dir_text = _coerce_str(source_payload.get("stems_dir")).strip()
    stems_dir = Path(stems_dir_text) if stems_dir_text else None
    if stems_dir is None or not stems_dir.is_absolute():
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir must be an absolute path for PR52 render-run. "
                f"stems_dir={stems_dir_text or '(missing)'}"
            ),
        )
    if not stems_dir.exists() or not stems_dir.is_dir():
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir must exist and be a directory. "
                f"stems_dir={stems_dir.resolve().as_posix()}"
            ),
        )

    candidates = _audio_source_candidates(stems_dir)
    if not candidates:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_MISSING,
            message=(
                "No source audio files were found in stems_dir for PR52 render-run. "
                f"stems_dir={stems_dir.resolve().as_posix()}"
            ),
        )
    if len(candidates) != 1:
        rel_paths = [item.relative_to(stems_dir).as_posix() for item in candidates]
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_COUNT_UNSUPPORTED,
            message=(
                "PR52 render-run requires exactly one source audio file in stems_dir. "
                f"found={len(candidates)} files: {', '.join(rel_paths)}"
            ),
        )
    return candidates[0]


def _audio_source_candidates(stems_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for item in stems_dir.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix.lower() in _SOURCE_EXTENSIONS:
            candidates.append(item)
    candidates.sort(key=lambda path: path.relative_to(stems_dir).as_posix())
    return candidates


def _read_source_metadata_or_raise(source_path: Path) -> dict[str, Any]:
    extension = source_path.suffix.lower()
    if extension in _LOSSY_EXTENSIONS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
            message=(
                "PR52 render-run supports only lossless source audio "
                "(wav/flac/wv/aiff/alac). "
                f"source={source_path.resolve().as_posix()}"
            ),
        )
    if extension in _WAV_EXTENSIONS:
        try:
            return read_wav_metadata(source_path)
        except ValueError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=f"Failed to read WAV metadata: {exc}",
            ) from exc
    if extension in _FFMPEG_EXTENSIONS:
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required for non-WAV source decoding.",
            )
        try:
            metadata = read_metadata(source_path)
        except (NotImplementedError, ValueError) as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=f"Failed to read source metadata: {exc}",
            ) from exc
        if extension == ".m4a":
            codec_name = _coerce_str(metadata.get("codec_name")).strip().lower()
            if codec_name != "alac":
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
                    message=(
                        "PR52 render-run only supports lossless ALAC for .m4a inputs. "
                        f"codec_name={codec_name or '(missing)'}"
                    ),
                )
        return metadata

    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
        message=(
            "Unsupported source extension for PR52 render-run. "
            f"source={source_path.resolve().as_posix()}"
        ),
    )


def _validate_source_layout_or_raise(source_metadata: dict[str, Any]) -> None:
    channels = _coerce_int(source_metadata.get("channels"))
    if channels != 2:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_LAYOUT_UNSUPPORTED,
            message=(
                "PR52 render-run requires a stereo source (2 channels). "
                f"source_channels={channels if channels is not None else '(missing)'}"
            ),
        )

    sample_rate_hz = _coerce_int(source_metadata.get("sample_rate_hz"))
    if sample_rate_hz is None or sample_rate_hz <= 0:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
            message="Source metadata is missing a valid sample_rate_hz.",
        )


def _resolve_output_bit_depth(
    *,
    requested_bit_depth: int | None,
    source_bit_depth: int | None,
) -> int:
    if requested_bit_depth is not None and requested_bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "Requested bit_depth is unsupported for PR52 render-run. "
                f"bit_depth={requested_bit_depth}"
            ),
        )
    if requested_bit_depth in _BIT_DEPTHS:
        return requested_bit_depth
    if source_bit_depth in _BIT_DEPTHS:
        return source_bit_depth
    return 24


def _job_output_formats_or_raise(job: dict[str, Any]) -> list[str]:
    raw_output_formats = job.get("output_formats")
    selected: set[str] = set()
    if isinstance(raw_output_formats, list):
        for item in raw_output_formats:
            normalized = _coerce_str(item).strip().lower()
            if not normalized:
                continue
            if normalized not in _OUTPUT_FORMAT_ORDER:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED,
                    message=(
                        "Unsupported output format requested in render plan job. "
                        f"output_format={normalized}"
                    ),
                )
            selected.add(normalized)
    if not selected:
        selected.add("wav")
    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _planned_outputs_by_format(job: dict[str, Any]) -> dict[str, str]:
    outputs = job.get("outputs")
    if not isinstance(outputs, list):
        return {}
    by_format: dict[str, str] = {}
    normalized_rows: list[tuple[str, str]] = []
    for row in outputs:
        if not isinstance(row, dict):
            continue
        output_format = _coerce_str(row.get("format")).strip().lower()
        output_path = _coerce_str(row.get("path")).strip()
        if not output_format or not output_path:
            continue
        normalized_rows.append((output_format, output_path))
    normalized_rows.sort(key=lambda item: (item[0], item[1]))
    for output_format, output_path in normalized_rows:
        by_format.setdefault(output_format, output_path)
    return by_format


def _scene_anchor_root(*, request_scene_path: str, scene_path: Path) -> Path | None:
    raw = request_scene_path.strip()
    if not raw:
        return None
    if _is_absolute_posix_path(raw):
        return None
    parts = PurePosixPath(raw).parts
    anchor = scene_path.resolve()
    for _ in parts:
        parent = anchor.parent
        if parent == anchor:
            return None
        anchor = parent
    return anchor


def _is_absolute_posix_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    return len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/"


def _resolve_output_path(
    *,
    raw_path: str,
    scene_anchor: Path | None,
    report_dir: Path,
    fallback: Path | None = None,
) -> Path:
    normalized_raw = raw_path.strip()
    if not normalized_raw:
        if fallback is not None:
            return fallback
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED,
            message="Render plan output path is missing.",
        )

    normalized = normalized_raw.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if _is_absolute_posix_path(normalized):
        return Path(normalized)

    relative_parts = [part for part in pure.parts if part not in {"", "."}]
    relative_path = Path(*relative_parts) if relative_parts else Path("mix.wav")
    if scene_anchor is not None:
        return scene_anchor / relative_path
    return report_dir / relative_path


def _fallback_output_path(
    *,
    report_dir: Path,
    job_id: str,
    output_format: str,
) -> Path:
    suffix_by_format = {
        "wav": "wav",
        "flac": "flac",
        "wv": "wv",
        "aiff": "aiff",
        "alac": "m4a",
    }
    suffix = suffix_by_format.get(output_format, output_format)
    slug = job_id.replace(".", "_").lower()
    return report_dir / "render_outputs" / slug / f"mix.{suffix}"


def _intermediate_wav_path(*, report_dir: Path, job_id: str) -> Path:
    slug = job_id.replace(".", "_").lower()
    return report_dir / _INTERMEDIATE_ROOT / f"{slug}.wav"


def _write_stereo_wav(
    *,
    float_samples_iter: Iterator[list[float]],
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
) -> None:
    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)

        for float_samples in float_samples_iter:
            if len(float_samples) % 2 != 0:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                    message="Decoded sample stream is not frame-aligned for stereo.",
                )
            int_samples = _dithered_pcm_samples(float_samples, bit_depth, rng)
            handle.writeframes(_int_samples_to_bytes(int_samples, bit_depth))


def _dithered_pcm_samples(
    float_samples: list[float],
    bit_depth: int,
    rng: random.Random,
) -> list[int]:
    divisor = float(2 ** (bit_depth - 1))
    min_value = -int(divisor)
    max_value = int(divisor) - 1
    output: list[int] = []
    for sample in float_samples:
        noise = (rng.random() - rng.random()) / divisor
        value = _clamp_sample(sample + noise)
        scaled = int(round(value * divisor))
        if scaled < min_value:
            scaled = min_value
        elif scaled > max_value:
            scaled = max_value
        output.append(scaled)
    return output


def _clamp_sample(sample: float) -> float:
    if sample < -1.0:
        return -1.0
    if sample > _FLOAT_MAX:
        return _FLOAT_MAX
    return sample


def _int_samples_to_bytes(samples: list[int], bit_depth: int) -> bytes:
    if bit_depth == 16:
        return struct.pack(f"<{len(samples)}h", *samples)
    if bit_depth == 24:
        data = bytearray(len(samples) * 3)
        for index, sample in enumerate(samples):
            value = sample & 0xFFFFFF
            offset = index * 3
            data[offset : offset + 3] = bytes(
                (
                    value & 0xFF,
                    (value >> 8) & 0xFF,
                    (value >> 16) & 0xFF,
                )
            )
        return bytes(data)
    if bit_depth == 32:
        return struct.pack(f"<{len(samples)}i", *samples)
    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
        message=f"Unsupported output bit depth: {bit_depth}",
    )


def _path_arg(path: Path) -> str:
    return path.resolve().as_posix()


def _wav_codec_for_bit_depth(bit_depth: int) -> str:
    codecs = {
        16: "pcm_s16le",
        24: "pcm_s24le",
        32: "pcm_s32le",
    }
    codec = codecs.get(bit_depth)
    if codec is None:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )
    return codec


def _normalize_wav_for_determinism(
    *,
    ffmpeg_cmd: Sequence[str],
    wav_path: Path,
    bit_depth: int,
    command_rows: list[dict[str, Any]],
) -> None:
    deterministic_flags = list(ffmpeg_determinism_flags(for_wav=True))
    tmp_path = wav_path.with_suffix(wav_path.suffix + ".tmp")
    command = list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        _path_arg(wav_path),
        *deterministic_flags,
        "-f",
        "wav",
        "-c:a",
        _wav_codec_for_bit_depth(bit_depth),
        _path_arg(tmp_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        if message:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                message=f"ffmpeg WAV normalization failed: {message}",
            )
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
            message=f"ffmpeg WAV normalization failed with exit code {completed.returncode}",
        )

    try:
        tmp_path.replace(wav_path)
    except OSError as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
            message=f"Failed to finalize deterministic WAV output: {exc}",
        ) from exc
    command_rows.append(
        {
            "args": command,
            "determinism_flags": deterministic_flags,
        }
    )


def _output_paths_from_rows(output_files: list[dict[str, Any]]) -> list[Path]:
    deduped: dict[str, Path] = {}
    for row in output_files:
        if not isinstance(row, dict):
            continue
        raw_path = _coerce_str(row.get("file_path")).strip()
        if not raw_path:
            continue
        resolved = Path(raw_path).resolve()
        deduped.setdefault(resolved.as_posix(), resolved)
    return [deduped[path] for path in sorted(deduped.keys())]


def _output_file_payload(
    *,
    output_path: Path,
    output_format: str,
    sample_rate_hz: int,
    bit_depth: int,
) -> dict[str, Any]:
    sha256_hex = sha256_file(output_path)
    return {
        "file_path": output_path.resolve().as_posix(),
        "format": output_format,
        "channel_count": 2,
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": bit_depth,
        "sha256": sha256_hex,
    }


def _output_sort_key(output_format: str) -> tuple[int, str]:
    try:
        return (_OUTPUT_FORMAT_ORDER.index(output_format), output_format)
    except ValueError:
        return (len(_OUTPUT_FORMAT_ORDER), output_format)
