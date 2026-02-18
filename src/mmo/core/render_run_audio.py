"""Deterministic offline audio rendering for ``render-run``."""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

from mmo.core.render_reporting import build_render_report_from_plan
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import read_metadata
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS, transcode_wav_to_format

_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_WAV_EXTENSIONS = frozenset({".wav", ".wave"})
_FFMPEG_EXTENSIONS = frozenset({".flac", ".wv", ".aif", ".aiff", ".m4a"})
_LOSSY_EXTENSIONS = frozenset({".mp3", ".aac", ".ogg", ".opus"})
_SOURCE_EXTENSIONS = _WAV_EXTENSIONS | _FFMPEG_EXTENSIONS | _LOSSY_EXTENSIONS
_BIT_DEPTHS = frozenset({16, 24, 32})
_INTERMEDIATE_ROOT = ".mmo_tmp/render_run"
_FLOAT_MAX = math.nextafter(1.0, 0.0)

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
) -> dict[str, Any]:
    """Render stereo deliverables and return a schema-valid render report payload."""
    job = _single_stereo_job_or_raise(plan_payload)
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
            job_id=_coerce_str(job.get("job_id")).strip() or "JOB.001",
            output_format="wav",
        )
    else:
        wav_path = _intermediate_wav_path(
            report_dir=report_dir,
            job_id=_coerce_str(job.get("job_id")).strip() or "JOB.001",
        )

    ffmpeg_cmd_for_decode: Sequence[str] | None = None
    ffmpeg_cmd_for_encode: Sequence[str] | None = None
    needs_ffmpeg_decode = source_path.suffix.lower() in _FFMPEG_EXTENSIONS
    needs_ffmpeg_encode = any(fmt != "wav" for fmt in output_formats)
    if needs_ffmpeg_decode or needs_ffmpeg_encode:
        ffmpeg_cmd_for_decode = resolve_ffmpeg_cmd()
        ffmpeg_cmd_for_encode = ffmpeg_cmd_for_decode
        if ffmpeg_cmd_for_decode is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message=(
                    "ffmpeg is required for requested render-run operation "
                    "(decode and/or encode lossless non-WAV audio)."
                ),
            )

    float_samples_iter: Iterator[list[float]]
    if source_path.suffix.lower() in _WAV_EXTENSIONS:
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
        float_samples_iter = iter_ffmpeg_float64_samples(source_path, ffmpeg_cmd_for_decode)

    try:
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
                transcode_wav_to_format(
                    ffmpeg_cmd_for_encode,
                    wav_path,
                    target_path,
                    output_format,
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
    report_job["notes"] = [
        "reason: rendered",
        f"source_file: {source_path.resolve().as_posix()}",
        "source_layout_id: LAYOUT.2_0",
        "target_layout_id: LAYOUT.2_0",
    ]
    return report_payload


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
