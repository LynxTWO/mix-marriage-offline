"""Scan a stems directory and emit a deterministic MMO report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

from mmo import __version__ as engine_version  # noqa: E402
from mmo.core.loudness_methods import DEFAULT_LOUDNESS_METHOD_ID  # noqa: E402
from mmo.core.lfe_audit import (  # noqa: E402
    audit_lfe_channels,
    build_lfe_audit_issues,
    detect_lfe_channel_indices,
    _extract_channel,
)
from mmo.core.preset_recommendations import derive_preset_recommendations  # noqa: E402
from mmo.core.session import build_session_from_stems_dir  # noqa: E402
from mmo.core.source_locator import resolve_stem_locator, resolved_stem_path  # noqa: E402
from mmo.core.stems_classifier import derive_role_name_tokens  # noqa: E402
from mmo.core.validators import validate_session  # noqa: E402
from mmo.core.vibe_signals import derive_vibe_signals  # noqa: E402
from mmo.dsp.decoders import detect_format_from_path  # noqa: E402
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd  # noqa: E402
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples  # noqa: E402
from mmo.dsp.correlation import PairCorrelationAccumulator  # noqa: E402
from mmo.dsp.meters import (  # noqa: E402
    compute_basic_stats_from_float64,
    compute_sample_peak_dbfs_wav,
    iter_wav_float64_samples,
)
from mmo.dsp.stereo import compute_stereo_correlation_wav  # noqa: E402
from mmo.resources import ontology_dir, presets_dir  # noqa: E402
from mmo.core.progress import ExplainableLogEvent, format_live_log_line  # noqa: E402


def _emit_live(
    *,
    what: str,
    why: str,
    where: List[str],
    kind: str = "meter",
    scope: str = "scan",
    step_index: int = 0,
    total_steps: int = 0,
    progress: float = 0.0,
    eta_seconds: float | None = None,
    evidence: Dict[str, Any] | None = None,
) -> None:
    """Emit a [MMO-LIVE] progress line to stderr."""
    event = ExplainableLogEvent(
        kind=kind,
        scope=scope,
        what=what,
        why=why,
        where=tuple(where),
        confidence=1.0,
        evidence=evidence or {},
        step_index=step_index,
        total_steps=total_steps,
        progress=progress,
        eta_seconds=eta_seconds,
    )
    print(format_live_log_line(event), file=sys.stderr, flush=True)


def upsert_measurement(stem: Dict[str, Any], evidence_id: str, value: Any, unit_id: str) -> None:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        measurements = []
        stem["measurements"] = measurements

    replaced = False
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        if measurement.get("evidence_id") == evidence_id:
            measurement["value"] = value
            measurement["unit_id"] = unit_id
            replaced = True
            break

    if not replaced:
        measurements.append(
            {
                "evidence_id": evidence_id,
                "value": value,
                "unit_id": unit_id,
            }
        )

    measurements.sort(key=lambda item: item.get("evidence_id", ""))


def _resolved_stem_path_for_scan(
    stem: Dict[str, Any],
    stems_dir: Path,
) -> Path | None:
    path = resolved_stem_path(stem)
    if path is not None:
        return path
    # Scan must recover paths with the same portable locator rules used by later
    # session and render stages. If that fallback drifts, scan can meter a
    # different file than the rest of the pipeline.
    return resolved_stem_path(resolve_stem_locator(stem, stems_dir=stems_dir))


def _plan_correlation_pairs(
    order_csv: str, mode_str: str, channels: int
) -> tuple[Dict[str, tuple[int, int]], list[dict], str | None]:
    if order_csv == "unknown":
        return {}, [], "order_unknown"
    if mode_str.startswith("fallback_") or "trimmed" in mode_str:
        return {}, [], "order_not_confident"
    order = [item.strip() for item in order_csv.split(",")]
    if not order or any(not item for item in order):
        return {}, [], "order_not_confident"
    if len(order) != channels:
        return {}, [], "order_not_confident"
    if len(set(order)) != len(order):
        return {}, [], "order_not_confident"

    label_to_index = {label: index for index, label in enumerate(order)}
    pair_defs = [
        ("FL_FR", "FL", "FR", "FL/FR"),
        ("SL_SR", "SL", "SR", "SL/SR"),
        ("BL_BR", "BL", "BR", "BL/BR"),
    ]
    pairs: Dict[str, tuple[int, int]] = {}
    meta: list[dict] = []
    for token, label_a, label_b, pair_label in pair_defs:
        if label_a not in label_to_index or label_b not in label_to_index:
            continue
        idx_a = label_to_index[label_a]
        idx_b = label_to_index[label_b]
        if channels == 2 and token == "FL_FR":
            evidence_id = "EVID.IMAGE.CORRELATION"
        else:
            evidence_id = f"EVID.IMAGE.CORRELATION.{token}"
        pairs[token] = (idx_a, idx_b)
        meta.append(
            {
                "token": token,
                "pair_label": pair_label,
                "idx_a": idx_a,
                "idx_b": idx_b,
                "evidence_id": evidence_id,
            }
        )
    return pairs, meta, None


def _rounded_correlation(value: float) -> float:
    rounded = round(value, 6)
    if rounded == 0.0:
        return 0.0
    return rounded


def _build_pairs_log(
    *,
    mode_str: str,
    order_csv: str,
    channels: int,
    source: str,
    pair_meta: list[dict],
    correlations: Dict[str, float],
) -> str:
    pairs_payload: list[dict] = []
    for meta in pair_meta:
        token = meta["token"]
        corr = correlations.get(token)
        if corr is None:
            continue
        pairs_payload.append(
            {
                "pair": meta["pair_label"],
                "idx_a": meta["idx_a"],
                "idx_b": meta["idx_b"],
                "evidence_id": meta["evidence_id"],
                "correlation": _rounded_correlation(corr),
            }
        )
    payload = {
        "mode": mode_str,
        "order": order_csv,
        "channels": channels,
        "source": source,
        "pairs": pairs_payload,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _load_ontology_version(path: Path) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot load ontology version.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    ontology = data.get("ontology", {}) if isinstance(data, dict) else {}
    version = ontology.get("ontology_version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"Missing ontology_version in {path}")
    return version


def _hash_from_stems(stems: List[Dict[str, Any]]) -> str:
    hashes = [stem.get("sha256", "") for stem in stems]
    joined = "\n".join(hashes)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _validate_schema(schema_path: Path, report: Dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is not installed; cannot validate report.")
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(report), key=lambda err: list(err.path))
    if errors:
        messages = "\n".join(f"- {err.message}" for err in errors)
        raise ValueError(f"Report schema validation failed:\n{messages}")


def _add_peak_metrics(session: Dict[str, Any], stems_dir: Path) -> None:
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
            continue
        stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
        if stem_path is None:
            continue
        if detect_format_from_path(stem_path) != "wav":
            continue
        try:
            peak_dbfs = compute_sample_peak_dbfs_wav(stem_path)
        except ValueError:
            continue
        metrics = stem.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
            stem["metrics"] = metrics
        metrics["peak_dbfs"] = peak_dbfs
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.SAMPLE_PEAK_DBFS",
            value=peak_dbfs,
            unit_id="UNIT.DBFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.PEAK_DBFS",
            value=peak_dbfs,
            unit_id="UNIT.DBFS",
        )


def _worker_basic_meters(
    stem: Dict[str, Any],
    stems_dir_str: str,
    step_index: int,
    total_steps: int,
    phase_start: float,
) -> Dict[str, Any]:
    """Top-level worker for ProcessPoolExecutor: compute basic meters for one stem.

    Returns a dict with keys: stem_id, measurements, stereo_correlation, missing_ffmpeg.
    Emits [MMO-LIVE] lines to stderr.
    """
    stems_dir = Path(stems_dir_str)
    stem_id = stem.get("stem_id", "")
    result: Dict[str, Any] = {
        "stem_id": stem_id,
        "measurements": [],
        "stereo_correlation": None,
        "missing_ffmpeg": False,
    }

    stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
    if stem_path is None:
        return result

    format_id = detect_format_from_path(stem_path)
    measurements: List[Dict[str, Any]] = []

    # Use the native WAV reader here. It matches the direct decode path used
    # elsewhere and leaves FFmpeg as the compatibility path for other formats.
    if format_id == "wav":
        if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
            return result
        try:
            (
                _basic_peak,
                clip_count,
                dc_offset,
                rms_dbfs,
                crest_factor_db,
            ) = compute_basic_stats_from_float64(
                iter_wav_float64_samples(stem_path, error_context="basic meters")
            )
        except ValueError:
            return result

        measurements = [
            {"evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT", "value": clip_count, "unit_id": "UNIT.COUNT"},
            {"evidence_id": "EVID.QUALITY.CLIPPED_SAMPLES_COUNT", "value": clip_count, "unit_id": "UNIT.COUNT"},
            {"evidence_id": "EVID.METER.DC_OFFSET", "value": dc_offset, "unit_id": "UNIT.RATIO"},
            {"evidence_id": "EVID.QUALITY.DC_OFFSET_PERCENT", "value": dc_offset * 100.0, "unit_id": "UNIT.PERCENT"},
            {"evidence_id": "EVID.METER.RMS_DBFS", "value": rms_dbfs, "unit_id": "UNIT.DBFS"},
            {"evidence_id": "EVID.METER.CREST_FACTOR_DB", "value": crest_factor_db, "unit_id": "UNIT.DB"},
        ]

        if stem.get("channel_count") == 2:
            try:
                correlation = compute_stereo_correlation_wav(stem_path)
                result["stereo_correlation"] = correlation
            except ValueError:
                pass

    elif format_id in {"flac", "wavpack", "aiff", "ape"}:
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            # Missing ffmpeg is an optional-dependency problem. Return a flag so
            # the session-level report can keep scanning the rest of the stems
            # and emit one shared issue instead of failing early here.
            result["missing_ffmpeg"] = True
            return result
        try:
            (
                peak,
                clip_count,
                dc_offset,
                rms_dbfs,
                crest_factor_db,
            ) = compute_basic_stats_from_float64(
                iter_ffmpeg_float64_samples(stem_path, ffmpeg_cmd)
            )
        except ValueError:
            return result

        if peak <= 0.0:
            peak_dbfs = float("-inf")
        else:
            peak_dbfs = 20.0 * math.log10(peak)

        measurements = [
            {"evidence_id": "EVID.METER.SAMPLE_PEAK_DBFS", "value": peak_dbfs, "unit_id": "UNIT.DBFS"},
            {"evidence_id": "EVID.METER.PEAK_DBFS", "value": peak_dbfs, "unit_id": "UNIT.DBFS"},
            {"evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT", "value": clip_count, "unit_id": "UNIT.COUNT"},
            {"evidence_id": "EVID.QUALITY.CLIPPED_SAMPLES_COUNT", "value": clip_count, "unit_id": "UNIT.COUNT"},
            {"evidence_id": "EVID.METER.DC_OFFSET", "value": dc_offset, "unit_id": "UNIT.RATIO"},
            {"evidence_id": "EVID.QUALITY.DC_OFFSET_PERCENT", "value": dc_offset * 100.0, "unit_id": "UNIT.PERCENT"},
            {"evidence_id": "EVID.METER.RMS_DBFS", "value": rms_dbfs, "unit_id": "UNIT.DBFS"},
            {"evidence_id": "EVID.METER.CREST_FACTOR_DB", "value": crest_factor_db, "unit_id": "UNIT.DB"},
        ]
    else:
        return result

    result["measurements"] = measurements

    elapsed = time.perf_counter() - phase_start
    done = step_index + 1
    eta = (elapsed / done) * (total_steps - done) if done < total_steps else 0.0
    _emit_live(
        what="basic meters",
        why="peak, RMS, crest factor, DC offset, clip count",
        where=[stem_id],
        step_index=done,
        total_steps=total_steps,
        progress=done / total_steps if total_steps else 1.0,
        eta_seconds=eta,
        evidence={"format": format_id},
    )
    return result


def _worker_truth_meters(
    stem: Dict[str, Any],
    stems_dir_str: str,
    method_id: str,
    step_index: int,
    total_steps: int,
    phase_start: float,
) -> Dict[str, Any]:
    """Top-level worker for ProcessPoolExecutor: compute truth meters for one stem.

    Returns a dict with keys: stem_id, measurements, missing_ffmpeg.
    Emits [MMO-LIVE] lines to stderr.
    """
    from mmo.dsp.meters_truth import (  # noqa: WPS433
        _read_wav_float64,
        bs1770_weighting_info,
        compute_lufs_integrated_float64,
        compute_lufs_shortterm_float64,
        compute_true_peak_dbtp_float64,
        loudness_weighting_receipt,
    )
    import numpy as np  # noqa: WPS433

    stems_dir = Path(stems_dir_str)
    stem_id = stem.get("stem_id", "")
    result: Dict[str, Any] = {
        "stem_id": stem_id,
        "measurements": [],
        "missing_ffmpeg": False,
    }

    stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
    if stem_path is None:
        return result

    format_id = detect_format_from_path(stem_path)
    channels = stem.get("channels")
    if not isinstance(channels, int) or channels <= 0:
        channels = stem.get("channel_count")
    if not isinstance(channels, int) or channels <= 0:
        return result

    sample_rate_hz = stem.get("sample_rate_hz")
    if not isinstance(sample_rate_hz, (int, float)) or sample_rate_hz <= 0:
        return result

    mask = stem.get("wav_channel_mask")
    channel_mask = mask if isinstance(mask, int) else None
    weights, order_csv, mode_str = bs1770_weighting_info(
        channels, channel_mask, channel_layout=stem.get("channel_layout")
    )
    weighting_receipt = loudness_weighting_receipt(
        channels, channel_mask,
        channel_layout=stem.get("channel_layout"),
        method_id=method_id,
    )
    # Pair correlations are only meaningful when channel order evidence is
    # strong enough to name the pair. Weak layout hints should emit a skipped
    # receipt, not guessed stereo evidence.
    pairs, pair_meta, skip_reason = _plan_correlation_pairs(order_csv, mode_str, channels)
    pair_correlations: Dict[str, float] | None = None
    pair_source: str | None = None

    if format_id == "wav":
        try:
            samples_array, _sr = _read_wav_float64(stem_path)
            pair_accumulator = PairCorrelationAccumulator(channels, pairs) if pairs else None
            if pair_accumulator is not None and samples_array.size > 0:
                for idx in range(0, len(samples_array), channels):
                    chunk = samples_array[idx : idx + channels].tolist()
                    pair_accumulator.update_chunk(chunk)
            truepeak_dbtp = compute_true_peak_dbtp_float64(samples_array, int(sample_rate_hz))
            lufs_i = compute_lufs_integrated_float64(
                samples_array, int(sample_rate_hz), channels,
                channel_mask=stem.get("wav_channel_mask"),
                channel_layout=stem.get("channel_layout"),
                method_id=method_id,
            )
            lufs_s = compute_lufs_shortterm_float64(
                samples_array, int(sample_rate_hz), channels,
                channel_mask=stem.get("wav_channel_mask"),
                channel_layout=stem.get("channel_layout"),
                method_id=method_id,
            )
        except ValueError:
            return result
        if pair_accumulator is not None:
            pair_correlations = pair_accumulator.correlations()
            pair_source = "wav_reader"

    elif format_id in {"flac", "wavpack", "aiff", "ape"}:
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            # Truth meters can still leave a useful session receipt behind even
            # when ffmpeg is absent. Report that gap later instead of hiding
            # all other scan evidence behind one missing tool.
            result["missing_ffmpeg"] = True
            return result
        try:
            samples: list[float] = []
            pair_accumulator = PairCorrelationAccumulator(channels, pairs) if pairs else None
            for chunk in iter_ffmpeg_float64_samples(stem_path, ffmpeg_cmd):
                samples.extend(chunk)
                if pair_accumulator is not None:
                    pair_accumulator.update_chunk(chunk)
            if samples:
                samples_array = np.asarray(samples, dtype=np.float64)
                total = (len(samples_array) // channels) * channels
                if total != len(samples_array):
                    samples_array = samples_array[:total]
                samples_array = samples_array.reshape(-1, channels)
            else:
                samples_array = np.zeros((0, channels), dtype=np.float64)
        except ValueError:
            return result
        try:
            truepeak_dbtp = compute_true_peak_dbtp_float64(samples_array, int(sample_rate_hz))
            lufs_i = compute_lufs_integrated_float64(
                samples_array, int(sample_rate_hz), channels,
                channel_mask=stem.get("wav_channel_mask"),
                channel_layout=stem.get("channel_layout"),
                method_id=method_id,
            )
            lufs_s = compute_lufs_shortterm_float64(
                samples_array, int(sample_rate_hz), channels,
                channel_mask=stem.get("wav_channel_mask"),
                channel_layout=stem.get("channel_layout"),
                method_id=method_id,
            )
        except ValueError:
            return result
        if pair_accumulator is not None:
            pair_correlations = pair_accumulator.correlations()
            pair_source = "ffmpeg_f64le"
    else:
        return result

    gi_csv = ",".join(f"{weight:.2f}" for weight in weights)
    receipt_json = json.dumps(
        {
            "method_id": weighting_receipt.method_id,
            "mode": weighting_receipt.mode_str,
            "order": weighting_receipt.order_csv,
            "warnings": list(weighting_receipt.warnings),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    measurements: List[Dict[str, Any]] = [
        {"evidence_id": "EVID.METER.TRUEPEAK_DBTP", "value": truepeak_dbtp, "unit_id": "UNIT.DBTP"},
        {"evidence_id": "EVID.METER.LUFS_I", "value": lufs_i, "unit_id": "UNIT.LUFS"},
        {"evidence_id": "EVID.METER.LUFS_S", "value": lufs_s, "unit_id": "UNIT.LUFS"},
        {"evidence_id": "EVID.METER.LUFS_WEIGHTING_MODE", "value": mode_str, "unit_id": "UNIT.NONE"},
        {"evidence_id": "EVID.METER.LUFS_WEIGHTING_ORDER", "value": order_csv, "unit_id": "UNIT.NONE"},
        {"evidence_id": "EVID.METER.LUFS_WEIGHTING_GI", "value": gi_csv, "unit_id": "UNIT.NONE"},
        {"evidence_id": "EVID.METER.LUFS_WEIGHTING_RECEIPT", "value": receipt_json, "unit_id": "UNIT.NONE"},
    ]

    if pair_correlations is not None and pair_source is not None and pair_meta:
        for meta in pair_meta:
            token = meta["token"]
            corr = pair_correlations.get(token)
            if corr is None:
                continue
            measurements.append(
                {"evidence_id": meta["evidence_id"], "value": corr, "unit_id": "UNIT.CORRELATION"}
            )
        pairs_log = _build_pairs_log(
            mode_str=mode_str,
            order_csv=order_csv,
            channels=channels,
            source=pair_source,
            pair_meta=pair_meta,
            correlations=pair_correlations,
        )
        measurements.append(
            {"evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG", "value": pairs_log, "unit_id": "UNIT.NONE"}
        )
    elif skip_reason and channels >= 2:
        # Record the skip when we know why correlation was withheld. Silence
        # here would look like a clean pass.
        layout = stem.get("channel_layout")
        if order_csv != "unknown" or channel_mask is not None or layout is not None:
            payload = {
                "mode": mode_str,
                "order": order_csv,
                "channels": channels,
                "source": "unknown",
                "skipped": True,
                "reason": skip_reason,
                "pairs": [],
            }
            pairs_log = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            measurements.append(
                {"evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG", "value": pairs_log, "unit_id": "UNIT.NONE"}
            )

    result["measurements"] = measurements

    elapsed = time.perf_counter() - phase_start
    done = step_index + 1
    eta = (elapsed / done) * (total_steps - done) if done < total_steps else 0.0
    _emit_live(
        what="truth meters",
        why="TruePeak, LUFS-I, LUFS-S, correlation",
        where=[stem_id],
        step_index=done,
        total_steps=total_steps,
        progress=done / total_steps if total_steps else 1.0,
        eta_seconds=eta,
        evidence={"format": format_id, "sample_rate_hz": int(sample_rate_hz)},
    )
    return result


def _add_basic_meter_measurements(
    session: Dict[str, Any], stems_dir: Path
) -> bool:
    stems = [s for s in session.get("stems", []) if isinstance(s, dict)]
    if not stems:
        return False

    stems_by_id = {s.get("stem_id"): s for s in stems if s.get("stem_id")}
    total = len(stems)
    missing_ffmpeg = False
    phase_start = time.perf_counter()

    _emit_live(
        what="basic meters: starting",
        why="peak, RMS, crest factor, DC offset, clip count for all stems",
        where=["session"],
        kind="action",
        step_index=0,
        total_steps=total,
        progress=0.0,
    )

    max_workers = min(total, os.cpu_count() or 1)
    futures = {}
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        for idx, stem in enumerate(stems):
            future = pool.submit(
                _worker_basic_meters,
                stem,
                str(stems_dir),
                idx,
                total,
                phase_start,
            )
            futures[future] = stem.get("stem_id")

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            stem_id = result.get("stem_id")
            stem = stems_by_id.get(stem_id)
            if stem is None:
                continue
            if result.get("missing_ffmpeg"):
                missing_ffmpeg = True
            for m in result.get("measurements", []):
                upsert_measurement(stem, evidence_id=m["evidence_id"], value=m["value"], unit_id=m["unit_id"])
            corr = result.get("stereo_correlation")
            if corr is not None:
                upsert_measurement(stem, evidence_id="EVID.IMAGE.CORRELATION", value=corr, unit_id="UNIT.CORRELATION")

    return missing_ffmpeg


def _add_truth_meter_measurements(session: Dict[str, Any], stems_dir: Path) -> bool:
    stems = [s for s in session.get("stems", []) if isinstance(s, dict)]
    if not stems:
        return False

    stems_by_id = {s.get("stem_id"): s for s in stems if s.get("stem_id")}
    method_id = DEFAULT_LOUDNESS_METHOD_ID
    total = len(stems)
    missing_ffmpeg = False
    phase_start = time.perf_counter()

    _emit_live(
        what="truth meters: starting",
        why="TruePeak, LUFS-I, LUFS-S, stereo correlation for all stems",
        where=["session"],
        kind="action",
        step_index=0,
        total_steps=total,
        progress=0.0,
    )

    max_workers = min(total, os.cpu_count() or 1)
    futures = {}
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        for idx, stem in enumerate(stems):
            future = pool.submit(
                _worker_truth_meters,
                stem,
                str(stems_dir),
                method_id,
                idx,
                total,
                phase_start,
            )
            futures[future] = stem.get("stem_id")

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            stem_id = result.get("stem_id")
            stem = stems_by_id.get(stem_id)
            if stem is None:
                continue
            if result.get("missing_ffmpeg"):
                missing_ffmpeg = True
            for m in result.get("measurements", []):
                upsert_measurement(stem, evidence_id=m["evidence_id"], value=m["value"], unit_id=m["unit_id"])

    return missing_ffmpeg


def _to_mono_samples(interleaved: List[float], channels: int) -> List[float]:
    if channels <= 1:
        return list(interleaved)
    usable = len(interleaved) - (len(interleaved) % channels)
    if usable <= 0:
        return []
    mono: List[float] = []
    scale = 1.0 / float(channels)
    for index in range(0, usable, channels):
        frame = interleaved[index : index + channels]
        mono.append(sum(frame) * scale)
    return mono


def _load_mix_complexity_stems(
    session: Dict[str, Any], stems_dir: Path
) -> tuple[List[Dict[str, Any]], bool]:
    import numpy as np  # noqa: WPS433

    loaded: List[Dict[str, Any]] = []
    missing_ffmpeg = False
    ffmpeg_cmd = None
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id")
        if not isinstance(stem_id, str) or not stem_id:
            continue
        channels = stem.get("channel_count")
        if not isinstance(channels, int) or channels <= 0:
            continue
        sample_rate_hz = stem.get("sample_rate_hz")
        if not isinstance(sample_rate_hz, (int, float)) or sample_rate_hz <= 0:
            continue
        stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
        if stem_path is None:
            continue
        format_id = detect_format_from_path(stem_path)
        mono_samples: List[float] = []

        if format_id == "wav":
            try:
                for chunk in iter_wav_float64_samples(
                    stem_path, error_context="mix complexity meter"
                ):
                    mono_samples.extend(_to_mono_samples(chunk, channels))
            except ValueError:
                continue
        elif format_id in {"flac", "wavpack", "aiff", "ape"}:
            if ffmpeg_cmd is None:
                ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True
                continue
            try:
                for chunk in iter_ffmpeg_float64_samples(stem_path, ffmpeg_cmd):
                    mono_samples.extend(_to_mono_samples(chunk, channels))
            except ValueError:
                continue
        else:
            continue

        loaded.append(
            {
                "stem_id": stem_id,
                "samples": np.asarray(mono_samples, dtype=np.float64),
                "sample_rate_hz": int(sample_rate_hz),
            }
        )

    loaded.sort(key=lambda item: item["stem_id"])
    return loaded, missing_ffmpeg


def _default_mix_complexity_payload() -> Dict[str, Any]:
    return {
        "density_mean": 0.0,
        "density_peak": 0,
        "density_timeline": [],
        "top_masking_pairs": [],
        "top_masking_pairs_count": 0,
        "sample_rate_hz": None,
        "included_stem_ids": [],
        "skipped_stem_ids": [],
        "density": {
            "density_mean": 0.0,
            "density_peak": 0,
            "density_timeline": [],
            "timeline_total_windows": 0,
            "timeline_truncated": False,
            "window_size": 2048,
            "hop_size": 1024,
            "rms_threshold_dbfs": -45.0,
            "bands_hz": [],
            "stem_count": 0,
        },
        "masking_risk": {
            "top_pairs": [],
            "pair_count": 0,
            "window_size": 2048,
            "hop_size": 1024,
            "mid_band_hz": {"low_hz": 300.0, "high_hz": 3000.0},
        },
    }


def _build_mix_complexity(
    session: Dict[str, Any], stems_dir: Path
) -> tuple[Dict[str, Any], bool]:
    from mmo.meters.meter_masking_risk import compute_masking_risk  # noqa: WPS433
    from mmo.meters.meter_mix_density import compute_mix_density  # noqa: WPS433

    loaded_stems, missing_ffmpeg = _load_mix_complexity_stems(session, stems_dir)
    if not loaded_stems:
        return _default_mix_complexity_payload(), missing_ffmpeg

    sample_rate_counts: Dict[int, int] = {}
    for item in loaded_stems:
        sample_rate_hz = int(item["sample_rate_hz"])
        sample_rate_counts[sample_rate_hz] = sample_rate_counts.get(sample_rate_hz, 0) + 1
    # Scan does not resample here. Pick the dominant rate so the masking and
    # density math stays deterministic, then surface the skipped stems in the
    # payload for later review.
    selected_sample_rate = sorted(
        sample_rate_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]

    included = [
        {"stem_id": item["stem_id"], "samples": item["samples"]}
        for item in loaded_stems
        if int(item["sample_rate_hz"]) == selected_sample_rate
    ]
    included_ids = sorted(item["stem_id"] for item in included)
    skipped_ids = sorted(
        item["stem_id"]
        for item in loaded_stems
        if int(item["sample_rate_hz"]) != selected_sample_rate
    )

    density = compute_mix_density(included, sample_rate_hz=selected_sample_rate)
    masking = compute_masking_risk(
        included,
        sample_rate_hz=selected_sample_rate,
        top_n=3,
    )

    payload = {
        "density_mean": density.get("density_mean", 0.0),
        "density_peak": density.get("density_peak", 0),
        "density_timeline": density.get("density_timeline", []),
        "top_masking_pairs": masking.get("top_pairs", []),
        "top_masking_pairs_count": len(masking.get("top_pairs", [])),
        "sample_rate_hz": selected_sample_rate,
        "included_stem_ids": included_ids,
        "skipped_stem_ids": skipped_ids,
        "density": density,
        "masking_risk": masking,
    }
    return payload, missing_ffmpeg


def _has_optional_dep_issue(issues: List[Dict[str, Any]], dep_name: str) -> bool:
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("issue_id") != "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING":
            continue
        evidence = issue.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if (
                item.get("evidence_id")
                == "EVID.VALIDATION.MISSING_OPTIONAL_DEP"
                and item.get("value") == dep_name
            ):
                return True
    return False


def _add_optional_dep_issue(
    issues: List[Dict[str, Any]],
    dep_name: str,
    hint: str,
) -> None:
    if _has_optional_dep_issue(issues, dep_name):
        return
    issues.append(
        {
            "issue_id": "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING",
            "severity": 30,
            "confidence": 1.0,
            "target": {"scope": "session"},
            "evidence": [
                {
                    "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP",
                    "value": dep_name,
                },
                {
                    "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                    "value": hint,
                },
            ],
            "message": f"Optional dependency '{dep_name}' is missing; skipping related meters.",
        }
    )


def _collect_stem_samples(
    stem: Dict[str, Any],
    stems_dir: Path,
    ffmpeg_cmd: Optional[str],
) -> Optional[List[float]]:
    """Load all interleaved float64 samples for a stem (WAV or ffmpeg path)."""
    stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
    if stem_path is None:
        return None
    format_id = detect_format_from_path(stem_path)
    samples: List[float] = []
    if format_id == "wav":
        try:
            for chunk in iter_wav_float64_samples(stem_path, error_context="lfe audit"):
                samples.extend(chunk)
        except ValueError:
            # Some valid WAV variants (e.g. WAVE_FORMAT_EXTENSIBLE in older Python
            # runtimes) may fail the pure-WAV decoder; fall back to ffmpeg when available.
            decoder_cmd = ffmpeg_cmd or resolve_ffmpeg_cmd()
            if decoder_cmd is None:
                return None
            try:
                for chunk in iter_ffmpeg_float64_samples(stem_path, decoder_cmd):
                    samples.extend(chunk)
            except ValueError:
                return None
        return samples
    elif format_id in {"flac", "wavpack", "aiff", "ape"}:
        if ffmpeg_cmd is None:
            return None
        try:
            for chunk in iter_ffmpeg_float64_samples(stem_path, ffmpeg_cmd):
                samples.extend(chunk)
        except ValueError:
            return None
        return samples
    return None


def _add_lfe_audit_issues(
    session: Dict[str, Any],
    stems_dir: Path,
    issues: List[Dict[str, Any]],
    *,
    strict: bool = False,
) -> bool:
    """Run LFE content audit for all stems that have LFE channels.

    Requires numpy (returns True if numpy is missing).
    Uses ffprobe channel_layout / WAV mask to detect LFE indices.
    Adds ISSUE.LFE.* issues to the shared issues list.
    """
    try:
        import numpy  # noqa: F401
    except ImportError:
        return True

    ffmpeg_cmd: Optional[str] = None
    missing_ffmpeg = False
    stems = session.get("stems", [])

    # Audit stems independently so one unreadable file does not hide LFE
    # evidence from the rest of the session.
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id", "")
        channels = stem.get("channel_count")
        if channels is None:
            channels = stem.get("channels")
        if not isinstance(channels, int) or channels <= 0:
            continue
        sample_rate_hz = stem.get("sample_rate_hz")
        if not isinstance(sample_rate_hz, (int, float)) or sample_rate_hz <= 0:
            continue

        lfe_indices = detect_lfe_channel_indices(
            channels,
            channel_layout=stem.get("channel_layout"),
            wav_channel_mask=stem.get("wav_channel_mask"),
        )
        if not lfe_indices:
            continue

        # Need ffmpeg for non-WAV
        stem_path = _resolved_stem_path_for_scan(stem, stems_dir)
        format_id = detect_format_from_path(stem_path) if stem_path else None
        if format_id in {"flac", "wavpack", "aiff", "ape"} and ffmpeg_cmd is None:
            ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True

        all_samples = _collect_stem_samples(stem, stems_dir, ffmpeg_cmd)
        if all_samples is None:
            # Validation already owns the broader session error surface. The LFE
            # audit only adds extra evidence when a stem can be decoded here.
            continue

        # Build mains samples = all non-LFE channels mixed together
        lfe_set = set(lfe_indices)
        mains_channels = [i for i in range(channels) if i not in lfe_set]
        mains_samples: List[float] = []
        if mains_channels:
            # Mix all mains channels to mono
            for ch_idx in mains_channels:
                ch_mono = _extract_channel(all_samples, channels, ch_idx)
                if not mains_samples:
                    mains_samples = list(ch_mono)
                else:
                    for j, s in enumerate(ch_mono):
                        if j < len(mains_samples):
                            mains_samples[j] += s

        lfe_summary = audit_lfe_channels(
            all_samples,
            channels=channels,
            lfe_indices=lfe_indices,
            sample_rate_hz=int(sample_rate_hz),
            mains_samples=mains_samples if mains_samples else None,
        )
        lfe_rows = lfe_summary.get("rows", [])
        if isinstance(lfe_rows, list):
            _upsert_lfe_channel_rows(stem, lfe_rows, lfe_summary)
            for row in lfe_rows:
                if not isinstance(row, dict):
                    continue
                lfe_idx = row.get("channel_index")
                audit_result = row.get("audit_result")
                if not isinstance(lfe_idx, int) or not isinstance(audit_result, dict):
                    continue
                stem_issues = build_lfe_audit_issues(
                    stem_id, lfe_idx, audit_result, strict=strict
                )
                issues.extend(stem_issues)

    return missing_ffmpeg


def _upsert_lfe_channel_rows(
    stem: Dict[str, Any],
    rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> None:
    """Store per-LFE channel receipts as structured measurements."""
    del summary
    rendered_rows: List[Dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: int(item.get("channel_index", 0))):
        if not isinstance(row, dict):
            continue
        channel_index = row.get("channel_index")
        if not isinstance(channel_index, int):
            continue
        rendered_rows.append(
            {
                "channel_index": channel_index,
                "inband_energy_db": row.get("inband_energy_db"),
                "out_of_band_energy_db": row.get("out_of_band_energy_db"),
                "infrasonic_energy_db": row.get("audit_result", {}).get("infrasonic_energy_db")
                if isinstance(row.get("audit_result"), dict)
                else None,
                "peak_dbfs": row.get("audit_result", {}).get("peak_dbfs")
                if isinstance(row.get("audit_result"), dict)
                else None,
                "true_peak_dbtp": row.get("true_peak_dbtp"),
                "crest_factor_db": row.get("audit_result", {}).get("crest_factor_db")
                if isinstance(row.get("audit_result"), dict)
                else None,
                "mains_inband_energy_db": row.get("audit_result", {}).get("mains_inband_energy_db")
                if isinstance(row.get("audit_result"), dict)
                else None,
                "lfe_to_mains_ratio_db": row.get("audit_result", {}).get("lfe_to_mains_ratio_db")
                if isinstance(row.get("audit_result"), dict)
                else None,
                "out_of_band_high": bool(row.get("out_of_band_high")),
                "infrasonic_rumble": bool(row.get("audit_result", {}).get("infrasonic_rumble"))
                if isinstance(row.get("audit_result"), dict)
                else False,
                "headroom_low": bool(row.get("audit_result", {}).get("headroom_low"))
                if isinstance(row.get("audit_result"), dict)
                else False,
                "band_level_low": bool(row.get("audit_result", {}).get("band_level_low"))
                if isinstance(row.get("audit_result"), dict)
                else False,
                "band_level_high": bool(row.get("audit_result", {}).get("band_level_high"))
                if isinstance(row.get("audit_result"), dict)
                else False,
            }
        )
    if rendered_rows:
        upsert_measurement(
            stem,
            evidence_id="EVID.LFE.CHANNEL_ROWS",
            value=json.dumps(rendered_rows, sort_keys=True, separators=(",", ":")),
            unit_id="UNIT.NONE",
        )


def _build_metering_summary(session: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Build a flat metering summary from per-stem measurements.

    Extracts LUFS_I, TRUEPEAK_DBTP, CREST_FACTOR_DB, and phase correlation
    from each stem's measurements list and computes session-level aggregates.
    Deterministic: sorted by stem_id, finite-only aggregation.
    """
    stems = session.get("stems", [])
    stems_summary: List[Dict[str, Any]] = []

    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id", "")
        measurements = stem.get("measurements", [])
        m: Dict[str, Any] = {}
        for meas in measurements:
            if isinstance(meas, dict) and "evidence_id" in meas and "value" in meas:
                m[meas["evidence_id"]] = meas["value"]

        entry: Dict[str, Any] = {"stem_id": stem_id}
        lufs_i = m.get("EVID.METER.LUFS_I")
        if lufs_i is not None and isinstance(lufs_i, (int, float)) and math.isfinite(lufs_i):
            entry["lufs_i"] = round(float(lufs_i), 2)
        else:
            entry["lufs_i"] = None
        tp = m.get("EVID.METER.TRUEPEAK_DBTP")
        if tp is not None and isinstance(tp, (int, float)) and math.isfinite(tp):
            entry["true_peak_dbtp"] = round(float(tp), 2)
        else:
            entry["true_peak_dbtp"] = None
        crest = m.get("EVID.METER.CREST_FACTOR_DB")
        if crest is not None and isinstance(crest, (int, float)) and math.isfinite(crest):
            entry["crest_db"] = round(float(crest), 2)
        else:
            entry["crest_db"] = None
        corr = m.get("EVID.IMAGE.CORRELATION")
        if corr is not None and isinstance(corr, (int, float)) and math.isfinite(corr):
            entry["correlation"] = round(float(corr), 6)
        else:
            entry["correlation"] = None

        stems_summary.append(entry)

    stems_summary.sort(key=lambda s: s.get("stem_id", ""))

    lufs_vals = [s["lufs_i"] for s in stems_summary if s.get("lufs_i") is not None]
    tp_vals = [s["true_peak_dbtp"] for s in stems_summary if s.get("true_peak_dbtp") is not None]

    session_stats: Dict[str, Any] = {"stem_count": len(stems)}
    if lufs_vals:
        session_stats["lufs_i_min"] = round(min(lufs_vals), 2)
        session_stats["lufs_i_max"] = round(max(lufs_vals), 2)
        session_stats["lufs_i_range_db"] = round(max(lufs_vals) - min(lufs_vals), 2)
    else:
        session_stats["lufs_i_min"] = None
        session_stats["lufs_i_max"] = None
        session_stats["lufs_i_range_db"] = None
    if tp_vals:
        session_stats["true_peak_max_dbtp"] = round(max(tp_vals), 2)
    else:
        session_stats["true_peak_max_dbtp"] = None

    buses = session.get("buses", [])
    buses_summary: List[Dict[str, Any]] = []
    for bus in buses:
        if not isinstance(bus, dict):
            continue
        bus_id = bus.get("bus_id", "")
        member_ids = bus.get("member_stem_ids", [])
        bus_entry: Dict[str, Any] = {"bus_id": bus_id, "member_stem_ids": list(member_ids)}
        bus_lufs = m_lufs = None
        bus_tp = m_tp = None
        bus_crest = m_crest = None
        bus_lufs_list = []
        bus_tp_list = []
        bus_crest_list = []
        for s in stems_summary:
            if s.get("stem_id") in member_ids:
                if s.get("lufs_i") is not None:
                    bus_lufs_list.append(s["lufs_i"])
                if s.get("true_peak_dbtp") is not None:
                    bus_tp_list.append(s["true_peak_dbtp"])
                if s.get("crest_db") is not None:
                    bus_crest_list.append(s["crest_db"])
        bus_entry["lufs_i"] = round(sum(bus_lufs_list) / len(bus_lufs_list), 2) if bus_lufs_list else None
        bus_entry["true_peak_dbtp"] = round(max(bus_tp_list), 2) if bus_tp_list else None
        bus_entry["crest_db"] = round(sum(bus_crest_list) / len(bus_crest_list), 2) if bus_crest_list else None
        buses_summary.append(bus_entry)

    result: Dict[str, Any] = {
        "mode": mode,
        "stems": stems_summary,
        "session": session_stats,
    }
    if buses_summary:
        result["buses"] = buses_summary
    return result


def _load_role_keywords() -> set:
    """Load all role inference keywords from roles.yaml (ontology).

    Falls back to empty set on any error.
    """
    try:
        import yaml as _yaml  # noqa: WPS433
    except ImportError:
        return set()

    try:
        roles_path = ontology_dir() / "roles.yaml"
        with roles_path.open("r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh)
    except Exception:  # noqa: BLE001
        return set()

    roles = data.get("roles", {}) if isinstance(data, dict) else {}
    known_keywords: set = set()
    for role_id, role_data in roles.items():
        if role_id == "_meta" or not isinstance(role_data, dict):
            continue
        inference = role_data.get("inference", {})
        for kw in inference.get("keywords", []):
            if isinstance(kw, str) and kw:
                # Tokenise multi-word keywords (e.g. "bass drum") into individual words
                for token in kw.lower().split():
                    known_keywords.add(token)
                known_keywords.add(kw.lower())
    return known_keywords


def _validate_role_names(
    session: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> None:
    """Check stem filenames against role naming conventions.

    Emits ISSUE.VALIDATION.UNKNOWN_ROLE for stems whose names
    do not match any known role keyword (from roles.yaml inference.keywords).
    """
    known_keywords = _load_role_keywords()
    if not known_keywords:
        return

    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id", "")
        file_path = stem.get("file_path", "")
        name = Path(file_path).stem if file_path else stem_id
        tokens = derive_role_name_tokens(name)
        if tokens & known_keywords:
            continue  # At least one recognizable role token

        issues.append(
            {
                "issue_id": "ISSUE.VALIDATION.UNKNOWN_ROLE",
                "severity": 20,
                "confidence": 0.7,
                "target": {"scope": "stem", "stem_id": stem_id},
                "evidence": [
                    {
                        "evidence_id": "EVID.FILE.PATH",
                        "value": file_path or stem_id,
                    },
                    {
                        "evidence_id": "EVID.FILE.NAME",
                        "value": name,
                    },
                ],
                "message": (
                    f"Stem '{name}' does not match any known role naming convention. "
                    "Role inference will fall back to ROLE.OTHER.UNKNOWN. "
                    "Rename using recognizable role keywords (e.g. kick, snare, bass, "
                    "guitar, strings, vox) to improve routing recommendations."
                ),
            }
        )


def _render_scan_summary(report: Dict[str, Any]) -> str:
    """Render a human-readable text summary of a scan report."""
    lines: List[str] = []
    session = report.get("session", {})
    stems = session.get("stems", [])
    issues = report.get("issues", [])
    stems_dir = session.get("stems_dir", "")

    lines.append("=== MMO Stem Scan Report ===")
    lines.append(f"Folder : {stems_dir}")
    lines.append(f"Stems  : {len(stems)}")
    lines.append(f"Issues : {len(issues)}")
    lines.append("")

    if stems:
        lines.append("STEMS:")
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            name = Path(stem.get("file_path", stem.get("stem_id", "?"))).name
            ch = stem.get("channel_count", stem.get("channels", "?"))
            sr = stem.get("sample_rate_hz", "?")
            bd = stem.get("bits_per_sample") or stem.get("bit_depth") or "?"
            dur = stem.get("duration_s")
            dur_str = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "?"
            layout = stem.get("channel_layout", "")
            layout_str = f" [{layout}]" if layout else ""
            lines.append(f"  {name}  ({ch}ch, {sr} Hz, {bd}-bit, {dur_str}){layout_str}")
        lines.append("")

    if issues:
        lines.append("ISSUES:")
        severity_label = {
            (90, 100): "ERROR",
            (70, 89): "WARN",
            (50, 69): "WARN",
            (30, 49): "INFO",
            (0, 29): "INFO",
        }

        def _sev_label(sev: int) -> str:
            for (lo, hi), label in severity_label.items():
                if lo <= sev <= hi:
                    return label
            return "INFO"

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            sev = issue.get("severity", 0)
            label = _sev_label(sev)
            issue_id = issue.get("issue_id", "ISSUE.?")
            message = issue.get("message", "")
            target = issue.get("target", {})
            where = ""
            if isinstance(target, dict):
                stem_id = target.get("stem_id")
                ch_idx = target.get("channel_index")
                if stem_id:
                    where = f" [{stem_id}]"
                if ch_idx is not None:
                    where += f"[ch{ch_idx}]"
            lines.append(f"  [{label:5s} {sev:3d}]{where} {issue_id}")
            if message:
                # Wrap long messages at 80 chars
                wrapped = message[:120] + ("..." if len(message) > 120 else "")
                lines.append(f"           {wrapped}")
        lines.append("")

    # LFE audit summary
    lfe_issues = [
        i for i in issues
        if isinstance(i, dict) and str(i.get("issue_id", "")).startswith("ISSUE.LFE.")
    ]
    if lfe_issues:
        lines.append(f"LFE AUDIT: {len(lfe_issues)} issue(s) found.")
    else:
        # Check if any LFE channels were detected
        lfe_stems = []
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            ch = stem.get("channel_count", 0)
            measurements = stem.get("measurements", [])
            lfe_m_ids = {
                m.get("evidence_id")
                for m in measurements
                if isinstance(m, dict)
            }
            if any(mid and mid.startswith("EVID.LFE.") for mid in lfe_m_ids):
                lfe_stems.append(stem.get("file_path", stem.get("stem_id", "")))
        if lfe_stems:
            lines.append(f"LFE AUDIT: {len(lfe_stems)} LFE stem(s) audited — no issues.")
        elif any(
            isinstance(s, dict) and (s.get("channel_count") or 0) > 2
            for s in stems
        ):
            lines.append("LFE AUDIT: No LFE channels detected in surround stems.")

    return "\n".join(lines)


def _path_text_is_absolute(path_text: str) -> bool:
    return path_text.startswith("/") or (
        len(path_text) >= 3
        and path_text[0].isalpha()
        and path_text[1] == ":"
        and path_text[2] == "/"
    )


def _shared_scan_path_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return None
    if _path_text_is_absolute(normalized):
        return Path(normalized).name or None
    if "/" in normalized:
        return Path(normalized).name or None
    return normalized


def _shared_scan_issue_evidence(
    issue: Dict[str, Any],
    evidence_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    shared_rows: List[Dict[str, Any]] = []
    for row in evidence_rows:
        evidence_id = row.get("evidence_id")
        if evidence_id == "EVID.FILE.HASH.SHA256":
            continue

        if evidence_id == "EVID.FILE.PATH":
            shared_ref = _shared_scan_path_ref(row.get("value"))
            if isinstance(shared_ref, str):
                row["value"] = shared_ref
            else:
                target = issue.get("target")
                if isinstance(target, dict):
                    stem_id = target.get("stem_id")
                    if isinstance(stem_id, str) and stem_id.strip():
                        row["value"] = stem_id.strip()
            shared_rows.append(row)
            continue

        if evidence_id == "EVID.FILE.NAME":
            value = row.get("value")
            if isinstance(value, str) and value.strip():
                row["value"] = Path(value.strip()).name or value.strip()
            shared_rows.append(row)
            continue

        shared_rows.append(row)

    return shared_rows or evidence_rows


def _build_shared_report_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    payload = json.loads(json.dumps(report))

    session = payload.get("session")
    if isinstance(session, dict):
        session.pop("stems_dir", None)
        raw_stems = session.get("stems")
        if isinstance(raw_stems, list):
            for stem in raw_stems:
                if not isinstance(stem, dict):
                    continue
                shared_file_path = _shared_scan_path_ref(stem.get("file_path"))
                stem["file_path"] = (
                    shared_file_path
                    or str(stem.get("stem_id") or "stem")
                )
                for field_name in (
                    "workspace_relative_path",
                    "source_ref",
                    "sha256",
                    "source_metadata",
                    "resolved_path",
                    "resolve_error_detail",
                ):
                    stem.pop(field_name, None)

    raw_issues = payload.get("issues")
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue
            if issue.get("issue_id") == "ISSUE.VALIDATION.UNKNOWN_ROLE":
                issue["message"] = (
                    "Stem name does not match any known role naming convention. "
                    "Role inference will fall back to ROLE.OTHER.UNKNOWN. "
                    "Rename the stem with recognizable role keywords to improve "
                    "routing recommendations."
                )
            evidence_rows = issue.get("evidence")
            if not isinstance(evidence_rows, list):
                continue
            normalized_rows = [
                row
                for row in evidence_rows
                if isinstance(row, dict)
            ]
            issue["evidence"] = _shared_scan_issue_evidence(issue, normalized_rows)

    return payload


def build_report(
    stems_dir: Path,
    generated_at: str,
    *,
    strict: bool = False,
    include_peak: bool = False,
    meters: Optional[str] = None,
) -> Dict[str, Any]:
    # Build the normalized session first so every later phase sees the same
    # resolved stem list and portable IDs.
    session = build_session_from_stems_dir(stems_dir)
    stems = session.get("stems", [])
    if not stems:
        raise ValueError(
            "No audio stems found in the provided directory. "
            "Point scan_session at an actual stems folder containing .wav/.flac/.wv/.aiff/.mp3/etc. "
            "Note: fixtures/sessions contains YAML fixture definitions, not audio stems."
        )
    if include_peak:
        _add_peak_metrics(session, stems_dir)
    missing_ffmpeg = False
    mix_complexity: Dict[str, Any] | None = None
    numpy_available: bool | None = None
    metering_summary: Dict[str, Any] | None = None
    scan_timings: Dict[str, float] = {}

    # Detect numpy availability early (shared by truth meters, mix complexity, LFE audit)
    try:
        import numpy  # noqa: F401
        numpy_available = True
    except ImportError:
        numpy_available = False

    stem_count = len(stems)
    phase_total = (
        (2 if meters == "truth" else 1 if meters == "basic" else 0) + 1 + 1
    )  # basic + optional truth + mix_complexity + lfe
    phase_index = 0

    # truth mode subsumes basic: run both so crest/RMS/peak are always present
    if meters in {"basic", "truth"}:
        phase_index += 1
        _emit_live(
            what="basic meters",
            why="peak, RMS, crest, DC offset, clip count across all stems",
            where=["session"],
            kind="action",
            step_index=phase_index,
            total_steps=phase_total,
            progress=phase_index / phase_total,
            evidence={"stem_count": stem_count},
        )
        t_start = time.perf_counter()
        missing_ffmpeg = _add_basic_meter_measurements(session, stems_dir)
        t_elapsed = (time.perf_counter() - t_start) * 1000
        scan_timings["basic_meters_ms"] = t_elapsed
    # Validate once the session shape is stable. Later phases add evidence, but
    # they should not change which stems exist or how they are identified.
    issues = validate_session(session, strict=strict)

    # Role naming convention validation (lightweight keyword check)
    _validate_role_names(session, issues)

    if meters == "truth":
        if not numpy_available:
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Reinstall base MMO deps or install numpy: pip install .",
            )
        else:
            phase_index += 1
            _emit_live(
                what="truth meters",
                why="TruePeak dBTP, LUFS-I, LUFS-S, stereo correlation across all stems",
                where=["session"],
                kind="action",
                step_index=phase_index,
                total_steps=phase_total,
                progress=phase_index / phase_total,
                evidence={"stem_count": stem_count},
            )
            t_start = time.perf_counter()
            missing_ffmpeg = _add_truth_meter_measurements(session, stems_dir) or missing_ffmpeg
            t_elapsed = (time.perf_counter() - t_start) * 1000
            scan_timings["truth_meters_ms"] = t_elapsed
    if meters in {"basic", "truth"}:
        if numpy_available:
            phase_index += 1
            _emit_live(
                what="mix complexity",
                why="spectral density and masking risk across stem pairs",
                where=["session"],
                kind="action",
                step_index=phase_index,
                total_steps=phase_total,
                progress=phase_index / phase_total,
                evidence={"stem_count": stem_count},
            )
            t_start = time.perf_counter()
            mix_complexity, mix_missing_ffmpeg = _build_mix_complexity(session, stems_dir)
            t_elapsed = (time.perf_counter() - t_start) * 1000
            scan_timings["mix_complexity_ms"] = t_elapsed
            missing_ffmpeg = mix_missing_ffmpeg or missing_ffmpeg
        else:
            mix_complexity = _default_mix_complexity_payload()
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Reinstall base MMO deps or install numpy: pip install .",
            )

    # LFE content audit — always attempt when numpy is available
    t_start = time.perf_counter()
    lfe_missing_numpy = _add_lfe_audit_issues(session, stems_dir, issues, strict=strict)
    t_elapsed = (time.perf_counter() - t_start) * 1000
    scan_timings["lfe_audit_ms"] = t_elapsed
    if lfe_missing_numpy and not numpy_available:
        # Only surface numpy issue once
        _add_optional_dep_issue(
            issues,
            dep_name="numpy",
            hint="Reinstall base MMO deps or install numpy: pip install .",
        )

    # Build metering summary when meters were run
    if meters in {"basic", "truth"}:
        metering_summary = _build_metering_summary(session, mode=meters)

    if missing_ffmpeg:
        _add_optional_dep_issue(
            issues,
            dep_name="ffmpeg",
            hint="Install FFmpeg or set MMO_FFMPEG_PATH=/path/to/ffmpeg",
        )
    stem_hash = _hash_from_stems(session.get("stems", []))
    ontology_version = _load_ontology_version(ontology_dir() / "ontology.yaml")
    report = {
        "schema_version": "0.1.0",
        "report_id": stem_hash,
        "project_id": stem_hash,
        "generated_at": generated_at,
        "engine_version": engine_version,
        "ontology_version": ontology_version,
        "session": session,
        "issues": issues,
        "recommendations": [],
    }
    if mix_complexity is not None:
        # Vibe and preset hints depend on the final mix-complexity payload. Run
        # them after meters and audits so downstream suggestions see the last
        # intake evidence, not a partial report.
        report["mix_complexity"] = mix_complexity
        report["vibe_signals"] = derive_vibe_signals(report)
        report["preset_recommendations"] = derive_preset_recommendations(
            report,
            presets_dir(),
        )
    if metering_summary is not None:
        report["metering"] = metering_summary
    if scan_timings:
        _emit_live(
            kind="action",
            scope="scan",
            what="scan complete",
            why="phase timing summary",
            where=["session"],
            evidence={k: round(v) for k, v in scan_timings.items()},
            step_index=phase_total,
            total_steps=phase_total,
            progress=1.0,
        )
    return report


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Scan a stems directory into an MMO report.")
        parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat lossy/unsupported formats as high-severity issues.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Run the scan but do not write the output file; print the summary to stdout.",
        )
        parser.add_argument(
            "--summary",
            action="store_true",
            help="Print a human-readable summary of the scan to stdout.",
        )
        parser.add_argument(
            "--peak",
            action="store_true",
            help="Compute WAV sample peak meter readings for stems.",
        )
        parser.add_argument(
            "--meters",
            choices=["basic", "truth"],
            default=None,
            help="Enable additional meter packs (basic or truth).",
        )
        parser.add_argument("--out", dest="out", default=None, help="Optional output JSON path.")
        parser.add_argument(
            "--format",
            choices=["json-shared"],
            default="json-shared",
            help=(
                "Output format for stdout JSON. "
                "'json-shared' drops machine-local path anchors, hashes, and "
                "source tags for shell use. "
                "Use --out when local tooling needs the full path-bearing "
                "report."
            ),
        )
        parser.add_argument(
            "--schema",
            dest="schema",
            default=None,
            help="Optional JSON schema path for validation.",
        )
        parser.add_argument(
            "--generated-at",
            dest="generated_at",
            default="2000-01-01T00:00:00Z",
            help="Override generated_at timestamp (ISO 8601).",
        )
        args = parser.parse_args()

        report = build_report(
            Path(args.stems_dir),
            args.generated_at,
            strict=args.strict,
            include_peak=args.peak,
            meters=args.meters,
        )

        if args.schema:
            # Validate before any write so callers do not persist a receipt that
            # the requested contract already rejects.
            _validate_schema(Path(args.schema), report)

        # Dry-run still builds and validates the artifact. It only stops short
        # of persisting JSON to disk.
        if args.dry_run:
            print(_render_scan_summary(report))
            return 0

        # Leave the human summary outside the write path so automation can
        # request JSON output without mixed stdout.
        if args.summary:
            print(_render_scan_summary(report))

        if args.out:
            output = json.dumps(report, indent=2)
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output + "\n", encoding="utf-8")
        elif not args.summary:
            # Default shell output should stay safe for issue threads and shared
            # logs while the file-backed report contract stays unchanged.
            output_payload = (
                _build_shared_report_payload(report)
                if args.format == "json-shared"
                else report
            )
            output = json.dumps(output_payload, indent=2)
            print(output)

        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
