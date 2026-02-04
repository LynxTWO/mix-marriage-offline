from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.backends.ffprobe_meta import find_ffprobe
from mmo.dsp.correlation import OnlineCorrelationAccumulator
from mmo.dsp.decoders import read_metadata
from mmo.dsp.downmix import (
    load_downmix_registry,
    resolve_downmix_matrix,
    _find_policy_pack_for_matrix,
)
from mmo.dsp.downmix import iter_apply_matrix_to_chunks

_CHUNK_FRAMES = 4096


@dataclass
class _AlignedStats:
    samples_read: int = 0
    frames_emitted: int = 0
    remainder_samples_dropped: int = 0


class _AlignedChunkIterator:
    def __init__(
        self,
        samples_iter: Iterable[List[float]],
        channels: int,
        max_frames: Optional[int],
        chunk_frames: int = _CHUNK_FRAMES,
    ) -> None:
        if channels <= 0:
            raise ValueError("channels must be positive")
        if chunk_frames <= 0:
            raise ValueError("chunk_frames must be positive")
        self._samples_iter = iter(samples_iter)
        self._channels = channels
        self._max_frames = max_frames
        self._chunk_frames = chunk_frames
        self.stats = _AlignedStats()

    def __iter__(self) -> Iterator[List[float]]:
        buffer: List[float] = []
        offset = 0
        for chunk in self._samples_iter:
            if not chunk:
                continue
            self.stats.samples_read += len(chunk)
            if offset:
                buffer = buffer[offset:]
                offset = 0
            buffer.extend(chunk)
            while True:
                available_frames = (len(buffer) - offset) // self._channels
                if self._max_frames is not None:
                    remaining = self._max_frames - self.stats.frames_emitted
                    if remaining <= 0:
                        break
                    available_frames = min(available_frames, remaining)
                if available_frames < self._chunk_frames:
                    break
                end = offset + self._chunk_frames * self._channels
                yield buffer[offset:end]
                offset = end
                self.stats.frames_emitted += self._chunk_frames
            if self._max_frames is not None and self.stats.frames_emitted >= self._max_frames:
                break

        if offset:
            buffer = buffer[offset:]
            offset = 0
        remaining_frames = len(buffer) // self._channels
        if self._max_frames is not None:
            remaining = self._max_frames - self.stats.frames_emitted
            if remaining <= 0:
                self.stats.remainder_samples_dropped = (
                    self.stats.samples_read - self.stats.frames_emitted * self._channels
                )
                return
            remaining_frames = min(remaining_frames, remaining)
        if remaining_frames > 0:
            end = remaining_frames * self._channels
            yield buffer[:end]
            self.stats.frames_emitted += remaining_frames
        self.stats.remainder_samples_dropped = (
            self.stats.samples_read - self.stats.frames_emitted * self._channels
        )


def _compute_stereo_correlation_from_interleaved(samples: List[float]) -> float:
    accumulator = OnlineCorrelationAccumulator()
    total = len(samples) - (len(samples) % 2)
    for index in range(0, total, 2):
        accumulator.update(samples[index], samples[index + 1])
    return accumulator.correlation()


def _compute_basic_metrics_from_chunks(chunks: Iterable[List[float]]) -> Dict[str, float]:
    peak = 0.0
    total_sq = 0.0
    count = 0
    corr_acc = OnlineCorrelationAccumulator()
    for chunk in chunks:
        total = len(chunk) - (len(chunk) % 2)
        for index in range(0, total, 2):
            left = float(chunk[index])
            right = float(chunk[index + 1])
            abs_left = abs(left)
            abs_right = abs(right)
            if abs_left > peak:
                peak = abs_left
            if abs_right > peak:
                peak = abs_right
            total_sq += left * left + right * right
            count += 2
            corr_acc.update(left, right)
    if count <= 0:
        rms_dbfs = float("-inf")
    else:
        rms = math.sqrt(total_sq / count)
        if rms <= 0.0:
            rms_dbfs = float("-inf")
        else:
            rms_dbfs = 20.0 * math.log10(rms)
    return {
        "peak": peak,
        "rms_dbfs": rms_dbfs,
        "correlation": corr_acc.correlation(),
    }


def _truth_metrics_from_interleaved(samples: List[float], sample_rate_hz: int) -> Dict[str, float]:
    try:
        import numpy as np
        from mmo.dsp import meters_truth
    except ImportError as exc:
        raise RuntimeError(
            "Truth meters require numpy, or choose --meters basic"
        ) from exc

    total = (len(samples) // 2) * 2
    if total <= 0:
        return {
            "lufs": float("-inf"),
            "true_peak": float("-inf"),
            "correlation": 0.0,
        }
    clipped = samples[:total]
    array = np.asarray(clipped, dtype=np.float64).reshape(-1, 2)
    lufs = meters_truth.compute_lufs_integrated_float64(
        array,
        sample_rate_hz,
        2,
        channel_mask=None,
        channel_layout="stereo",
    )
    true_peak = meters_truth.compute_true_peak_dbtp_float64(array, sample_rate_hz)
    correlation = _compute_stereo_correlation_from_interleaved(clipped)
    return {
        "lufs": float(lufs),
        "true_peak": float(true_peak),
        "correlation": float(correlation),
    }


def _issue(
    issue_id: str,
    severity: int,
    message: str,
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "confidence": 1.0,
        "target": {"scope": "session"},
        "evidence": evidence,
        "message": message,
    }


def run_downmix_qa(
    src_path: Path,
    ref_path: Path,
    *,
    source_layout_id: str,
    target_layout_id: str = "LAYOUT.2_0",
    policy_id: Optional[str] = None,
    tolerance_lufs: float = 1.0,
    tolerance_true_peak_db: float = 1.0,
    tolerance_corr: float = 0.15,
    repo_root: Path,
    meters: str = "truth",
    max_seconds: float = 120.0,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    measurements: List[Dict[str, Any]] = []

    ffmpeg_cmd = resolve_ffmpeg_cmd()
    if ffmpeg_cmd is None:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP", "value": "ffmpeg"},
            {
                "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                "value": "Install FFmpeg or set MMO_FFMPEG_PATH",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.DECODE_FAILED",
                90,
                "Missing dependency for downmix QA: ffmpeg",
                evidence,
            )
        )
        log_payload = {
            "matrix_id": None,
            "policy_id": policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": None,
            "ref_channels": None,
            "sample_rate_hz": None,
            "seconds_available": 0.0,
            "max_seconds": max_seconds,
            "seconds_compared": 0.0,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": policy_id,
                "matrix_id": None,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    layouts_path = repo_root / "ontology" / "layouts.yaml"
    registry_path = repo_root / "ontology" / "policies" / "downmix.yaml"
    matrix = resolve_downmix_matrix(
        repo_root=repo_root,
        source_layout_id=source_layout_id,
        target_layout_id=target_layout_id,
        policy_id=policy_id,
        layouts_path=layouts_path,
        registry_path=registry_path,
    )
    matrix_id = matrix.get("matrix_id")
    source_speakers = matrix.get("source_speakers") or []
    coeffs = matrix.get("coeffs") or []

    resolved_policy_id = policy_id
    if resolved_policy_id is None and isinstance(matrix_id, str):
        registry = load_downmix_registry(registry_path)
        found_policy, _ = _find_policy_pack_for_matrix(
            registry, matrix_id, repo_root, {}
        )
        if found_policy:
            resolved_policy_id = found_policy

    src_suffix = src_path.suffix.lower()
    ref_suffix = ref_path.suffix.lower()
    ffprobe_required = src_suffix not in {".wav", ".wave"} or ref_suffix not in {
        ".wav",
        ".wave",
    }
    if ffprobe_required and find_ffprobe() is None:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP", "value": "ffprobe"},
            {
                "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                "value": "Install FFmpeg (ffprobe) or set MMO_FFPROBE_PATH",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.DECODE_FAILED",
                90,
                "Missing dependency for downmix QA: ffprobe",
                evidence,
            )
        )
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": None,
            "ref_channels": None,
            "sample_rate_hz": None,
            "seconds_available": 0.0,
            "max_seconds": max_seconds,
            "seconds_compared": 0.0,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    try:
        src_meta = read_metadata(src_path)
        ref_meta = read_metadata(ref_path)
    except (ValueError, NotImplementedError) as exc:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(src_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(ref_path)},
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.DECODE_FAILED",
                90,
                f"Metadata decode failed for downmix QA: {exc}",
                evidence,
            )
        )
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": None,
            "ref_channels": None,
            "sample_rate_hz": None,
            "seconds_available": 0.0,
            "max_seconds": max_seconds,
            "seconds_compared": 0.0,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    src_channels = int(src_meta.get("channels", 0) or 0)
    ref_channels = int(ref_meta.get("channels", 0) or 0)
    src_sample_rate = int(src_meta.get("sample_rate_hz", 0) or 0)
    ref_sample_rate = int(ref_meta.get("sample_rate_hz", 0) or 0)
    src_duration = float(src_meta.get("duration_s", 0.0) or 0.0)
    ref_duration = float(ref_meta.get("duration_s", 0.0) or 0.0)
    seconds_available = min(src_duration, ref_duration)
    if max_seconds <= 0.0:
        seconds_compared = seconds_available
    else:
        seconds_compared = min(seconds_available, max_seconds)

    if ref_channels != 2:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {
                "evidence_id": "EVID.SESSION.CHANNEL_COUNT",
                "value": ref_channels,
                "unit_id": "UNIT.COUNT",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.CHANNELS_INVALID",
                90,
                f"Reference must be stereo; got {ref_channels} channels.",
                evidence,
            )
        )
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": src_channels,
            "ref_channels": ref_channels,
            "sample_rate_hz": None,
            "seconds_available": seconds_available,
            "max_seconds": max_seconds,
            "seconds_compared": seconds_compared,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    expected_src_channels = len(source_speakers)
    if expected_src_channels and src_channels != expected_src_channels:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {
                "evidence_id": "EVID.SESSION.CHANNEL_COUNT",
                "value": src_channels,
                "unit_id": "UNIT.COUNT",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.CHANNELS_INVALID",
                90,
                f"Source channels ({src_channels}) do not match matrix ({expected_src_channels}).",
                evidence,
            )
        )
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": src_channels,
            "ref_channels": ref_channels,
            "sample_rate_hz": None,
            "seconds_available": seconds_available,
            "max_seconds": max_seconds,
            "seconds_compared": seconds_compared,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    if src_sample_rate != ref_sample_rate:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {
                "evidence_id": "EVID.SESSION.SAMPLE_RATE_HZ",
                "value": src_sample_rate,
                "unit_id": "UNIT.HZ",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.SAMPLE_RATE_MISMATCH",
                90,
                (
                    "Source and reference sample rates do not match; "
                    f"src={src_sample_rate} Hz, ref={ref_sample_rate} Hz."
                ),
                evidence,
            )
        )
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": src_channels,
            "ref_channels": ref_channels,
            "sample_rate_hz": None,
            "seconds_available": seconds_available,
            "max_seconds": max_seconds,
            "seconds_compared": seconds_compared,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": 0,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": None,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    max_frames = int(seconds_compared * src_sample_rate)

    src_samples_iter = iter_ffmpeg_float64_samples(
        src_path, ffmpeg_cmd, chunk_frames=_CHUNK_FRAMES
    )
    ref_samples_iter = iter_ffmpeg_float64_samples(
        ref_path, ffmpeg_cmd, chunk_frames=_CHUNK_FRAMES
    )

    src_aligned = _AlignedChunkIterator(
        src_samples_iter, src_channels, max_frames, chunk_frames=_CHUNK_FRAMES
    )
    ref_aligned = _AlignedChunkIterator(
        ref_samples_iter, ref_channels, max_frames, chunk_frames=_CHUNK_FRAMES
    )

    remainder_samples_dropped = 0
    fold_metrics: Dict[str, float] = {}
    ref_metrics: Dict[str, float] = {}

    try:
        folded_chunks = iter_apply_matrix_to_chunks(
            coeffs,
            src_aligned,
            src_channels,
            target_channels=2,
            chunk_frames=_CHUNK_FRAMES,
        )
        if meters == "basic":
            fold_metrics = _compute_basic_metrics_from_chunks(folded_chunks)
            ref_metrics = _compute_basic_metrics_from_chunks(ref_aligned)
        elif meters == "truth":
            folded_samples: List[float] = []
            ref_samples: List[float] = []
            for chunk in folded_chunks:
                folded_samples.extend(chunk)
            for chunk in ref_aligned:
                ref_samples.extend(chunk)
            fold_metrics = _truth_metrics_from_interleaved(
                folded_samples, src_sample_rate
            )
            ref_metrics = _truth_metrics_from_interleaved(ref_samples, src_sample_rate)
        else:
            raise ValueError(f"Unsupported meter pack: {meters}")
    except RuntimeError as exc:
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP", "value": "numpy"},
            {
                "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                "value": "Install numpy (truth meters) or use --meters basic",
            },
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.DECODE_FAILED",
                90,
                str(exc),
                evidence,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface decode/meter failures as QA issues
        evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
        ]
        issues.append(
            _issue(
                "ISSUE.DOWNMIX.QA.DECODE_FAILED",
                90,
                f"Downmix QA decode failed: {exc}",
                evidence,
            )
        )
    finally:
        remainder_samples_dropped = src_aligned.stats.remainder_samples_dropped

    if issues:
        log_payload = {
            "matrix_id": matrix_id,
            "policy_id": resolved_policy_id,
            "source_layout_id": source_layout_id,
            "target_layout_id": target_layout_id,
            "src_channels": src_channels,
            "ref_channels": ref_channels,
            "sample_rate_hz": src_sample_rate,
            "seconds_available": seconds_available,
            "max_seconds": max_seconds,
            "seconds_compared": seconds_compared,
            "tolerances": {
                "lufs": tolerance_lufs,
                "true_peak_db": tolerance_true_peak_db,
                "correlation": tolerance_corr,
            },
            "decode_backend": "ffmpeg_f64le",
            "remainder_samples_dropped": remainder_samples_dropped,
        }
        log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
        measurements.append(
            {
                "evidence_id": "EVID.DOWNMIX.QA.LOG",
                "value": log_json,
                "unit_id": "UNIT.NONE",
            }
        )
        return {
            "downmix_qa": {
                "src_path": str(src_path),
                "ref_path": str(ref_path),
                "policy_id": resolved_policy_id,
                "matrix_id": matrix_id,
                "sample_rate_hz": src_sample_rate,
                "issues": issues,
                "measurements": measurements,
                "log": log_json,
            }
        }

    if meters == "truth":
        lufs_delta = fold_metrics["lufs"] - ref_metrics["lufs"]
        tp_delta = fold_metrics["true_peak"] - ref_metrics["true_peak"]
        corr_delta = fold_metrics["correlation"] - ref_metrics["correlation"]

        measurements.extend(
            [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_FOLD",
                    "value": fold_metrics["lufs"],
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_REF",
                    "value": ref_metrics["lufs"],
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": lufs_delta,
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_FOLD",
                    "value": fold_metrics["true_peak"],
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_REF",
                    "value": ref_metrics["true_peak"],
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": tp_delta,
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_FOLD",
                    "value": fold_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                    "value": ref_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": corr_delta,
                    "unit_id": "UNIT.CORRELATION",
                },
            ]
        )

        base_evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(src_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(ref_path)},
        ]
        if resolved_policy_id:
            base_evidence.append(
                {"evidence_id": "EVID.DOWNMIX.POLICY_ID", "value": resolved_policy_id}
            )
        if matrix_id:
            base_evidence.append(
                {"evidence_id": "EVID.DOWNMIX.MATRIX_ID", "value": matrix_id}
            )

        if abs(lufs_delta) > tolerance_lufs:
            evidence = base_evidence + [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_FOLD",
                    "value": fold_metrics["lufs"],
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_REF",
                    "value": ref_metrics["lufs"],
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": lufs_delta,
                    "unit_id": "UNIT.LUFS",
                },
            ]
            issues.append(
                _issue(
                    "ISSUE.DOWNMIX.QA.LUFS_MISMATCH",
                    60,
                    "Folded downmix LUFS differs from reference beyond tolerance.",
                    evidence,
                )
            )

        if abs(tp_delta) > tolerance_true_peak_db:
            evidence = base_evidence + [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_FOLD",
                    "value": fold_metrics["true_peak"],
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_REF",
                    "value": ref_metrics["true_peak"],
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": tp_delta,
                    "unit_id": "UNIT.DBTP",
                },
            ]
            issues.append(
                _issue(
                    "ISSUE.DOWNMIX.QA.TRUE_PEAK_MISMATCH",
                    60,
                    "Folded downmix true peak differs from reference beyond tolerance.",
                    evidence,
                )
            )

        if abs(corr_delta) > tolerance_corr:
            evidence = base_evidence + [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_FOLD",
                    "value": fold_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                    "value": ref_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": corr_delta,
                    "unit_id": "UNIT.CORRELATION",
                },
            ]
            issues.append(
                _issue(
                    "ISSUE.DOWNMIX.QA.CORRELATION_MISMATCH",
                    60,
                    "Folded downmix correlation differs from reference beyond tolerance.",
                    evidence,
                )
            )
    else:
        corr_delta = fold_metrics["correlation"] - ref_metrics["correlation"]
        measurements.extend(
            [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_FOLD",
                    "value": fold_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                    "value": ref_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": corr_delta,
                    "unit_id": "UNIT.CORRELATION",
                },
            ]
        )
        base_evidence = [
            {"evidence_id": "EVID.DOWNMIX.QA.SRC_PATH", "value": str(src_path)},
            {"evidence_id": "EVID.DOWNMIX.QA.REF_PATH", "value": str(ref_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(src_path)},
            {"evidence_id": "EVID.FILE.PATH", "value": str(ref_path)},
        ]
        if resolved_policy_id:
            base_evidence.append(
                {"evidence_id": "EVID.DOWNMIX.POLICY_ID", "value": resolved_policy_id}
            )
        if matrix_id:
            base_evidence.append(
                {"evidence_id": "EVID.DOWNMIX.MATRIX_ID", "value": matrix_id}
            )
        if abs(corr_delta) > tolerance_corr:
            evidence = base_evidence + [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_FOLD",
                    "value": fold_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                    "value": ref_metrics["correlation"],
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": corr_delta,
                    "unit_id": "UNIT.CORRELATION",
                },
            ]
            issues.append(
                _issue(
                    "ISSUE.DOWNMIX.QA.CORRELATION_MISMATCH",
                    60,
                    "Folded downmix correlation differs from reference beyond tolerance.",
                    evidence,
                )
            )

    log_payload = {
        "matrix_id": matrix_id,
        "policy_id": resolved_policy_id,
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "src_channels": src_channels,
        "ref_channels": ref_channels,
        "sample_rate_hz": src_sample_rate,
        "seconds_available": seconds_available,
        "max_seconds": max_seconds,
        "seconds_compared": seconds_compared,
        "tolerances": {
            "lufs": tolerance_lufs,
            "true_peak_db": tolerance_true_peak_db,
            "correlation": tolerance_corr,
        },
        "decode_backend": "ffmpeg_f64le",
        "remainder_samples_dropped": remainder_samples_dropped,
    }
    log_json = json.dumps(log_payload, sort_keys=True, separators=(",", ":"))
    measurements.append(
        {
            "evidence_id": "EVID.DOWNMIX.QA.LOG",
            "value": log_json,
            "unit_id": "UNIT.NONE",
        }
    )

    return {
        "downmix_qa": {
            "src_path": str(src_path),
            "ref_path": str(ref_path),
            "policy_id": resolved_policy_id,
            "matrix_id": matrix_id,
            "sample_rate_hz": src_sample_rate,
            "issues": issues,
            "measurements": measurements,
            "log": log_json,
        }
    }
