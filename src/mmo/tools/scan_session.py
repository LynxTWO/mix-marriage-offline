"""Scan a stems directory and emit a deterministic MMO report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
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
from mmo.core.lfe_audit import (  # noqa: E402
    audit_lfe_channel,
    build_lfe_audit_issues,
    detect_lfe_channel_indices,
    _extract_channel,
)
from mmo.core.preset_recommendations import derive_preset_recommendations  # noqa: E402
from mmo.core.session import build_session_from_stems_dir  # noqa: E402
from mmo.core.validators import validate_session  # noqa: E402
from mmo.core.vibe_signals import derive_vibe_signals  # noqa: E402
from mmo.dsp.decoders import detect_format_from_path  # noqa: E402
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd  # noqa: E402
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples  # noqa: E402
from mmo.dsp.correlation import (  # noqa: E402
    PairCorrelationAccumulator,
    compute_pair_correlations_wav,
)
from mmo.dsp.meters import (  # noqa: E402
    compute_basic_stats_from_float64,
    compute_clip_sample_count_wav,
    compute_crest_factor_db_wav,
    compute_dc_offset_wav,
    compute_rms_dbfs_wav,
    compute_sample_peak_dbfs_wav,
    iter_wav_float64_samples,
)
from mmo.dsp.stereo import compute_stereo_correlation_wav  # noqa: E402
from mmo.resources import ontology_dir, presets_dir  # noqa: E402


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
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
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


def _add_basic_meter_measurements(
    session: Dict[str, Any], stems_dir: Path
) -> bool:
    missing_ffmpeg = False
    ffmpeg_cmd = None
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        format_id = detect_format_from_path(stem_path)
        if format_id == "wav":
            if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
                continue
        elif format_id in {"flac", "wavpack", "aiff"}:
            if ffmpeg_cmd is None:
                ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True
                continue

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
                continue

            if peak <= 0.0:
                peak_dbfs = float("-inf")
            else:
                peak_dbfs = 20.0 * math.log10(peak)

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
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.CLIP_SAMPLE_COUNT",
                value=clip_count,
                unit_id="UNIT.COUNT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
                value=clip_count,
                unit_id="UNIT.COUNT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.DC_OFFSET",
                value=dc_offset,
                unit_id="UNIT.RATIO",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.QUALITY.DC_OFFSET_PERCENT",
                value=dc_offset * 100.0,
                unit_id="UNIT.PERCENT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.RMS_DBFS",
                value=rms_dbfs,
                unit_id="UNIT.DBFS",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.CREST_FACTOR_DB",
                value=crest_factor_db,
                unit_id="UNIT.DB",
            )
            continue
        else:
            continue

        try:
            clip_count = compute_clip_sample_count_wav(stem_path)
            dc_offset = compute_dc_offset_wav(stem_path)
            rms_dbfs = compute_rms_dbfs_wav(stem_path)
            crest_factor_db = compute_crest_factor_db_wav(stem_path)
        except ValueError:
            continue

        upsert_measurement(
            stem,
            evidence_id="EVID.METER.CLIP_SAMPLE_COUNT",
            value=clip_count,
            unit_id="UNIT.COUNT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
            value=clip_count,
            unit_id="UNIT.COUNT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.DC_OFFSET",
            value=dc_offset,
            unit_id="UNIT.RATIO",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.QUALITY.DC_OFFSET_PERCENT",
            value=dc_offset * 100.0,
            unit_id="UNIT.PERCENT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.RMS_DBFS",
            value=rms_dbfs,
            unit_id="UNIT.DBFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.CREST_FACTOR_DB",
            value=crest_factor_db,
            unit_id="UNIT.DB",
        )

        if stem.get("channel_count") == 2:
            try:
                correlation = compute_stereo_correlation_wav(stem_path)
            except ValueError:
                correlation = None
            if correlation is not None:
                upsert_measurement(
                    stem,
                    evidence_id="EVID.IMAGE.CORRELATION",
                    value=correlation,
                    unit_id="UNIT.CORRELATION",
                )
    return missing_ffmpeg


def _add_truth_meter_measurements(session: Dict[str, Any], stems_dir: Path) -> bool:
    from mmo.dsp.meters_truth import (  # noqa: WPS433
        bs1770_weighting_info,
        compute_lufs_integrated_float64,
        compute_lufs_integrated_wav,
        compute_lufs_shortterm_float64,
        compute_lufs_shortterm_wav,
        compute_true_peak_dbtp_float64,
        compute_true_peak_dbtp_wav,
    )
    import numpy as np  # noqa: WPS433

    missing_ffmpeg = False
    ffmpeg_cmd = None
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        format_id = detect_format_from_path(stem_path)
        channels = stem.get("channels")
        if not isinstance(channels, int) or channels <= 0:
            channels = stem.get("channel_count")
        if not isinstance(channels, int) or channels <= 0:
            continue
        sample_rate_hz = stem.get("sample_rate_hz")
        if not isinstance(sample_rate_hz, (int, float)) or sample_rate_hz <= 0:
            continue
        mask = stem.get("wav_channel_mask")
        channel_mask = mask if isinstance(mask, int) else None
        weights, order_csv, mode_str = bs1770_weighting_info(
            channels,
            channel_mask,
            channel_layout=stem.get("channel_layout"),
        )
        pairs, pair_meta, skip_reason = _plan_correlation_pairs(
            order_csv, mode_str, channels
        )
        pair_correlations: Dict[str, float] | None = None
        pair_source: str | None = None

        if format_id == "wav":
            try:
                truepeak_dbtp = compute_true_peak_dbtp_wav(stem_path)
                lufs_i = compute_lufs_integrated_wav(stem_path)
                lufs_s = compute_lufs_shortterm_wav(stem_path)
            except ValueError:
                continue
            if pairs:
                try:
                    pair_correlations = compute_pair_correlations_wav(stem_path, pairs)
                except ValueError:
                    pair_correlations = None
                else:
                    pair_source = "wav_reader"
        elif format_id in {"flac", "wavpack", "aiff"}:
            if ffmpeg_cmd is None:
                ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True
                continue

            try:
                samples: list[float] = []
                pair_accumulator = (
                    PairCorrelationAccumulator(channels, pairs) if pairs else None
                )
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
                continue

            try:
                truepeak_dbtp = compute_true_peak_dbtp_float64(
                    samples_array, int(sample_rate_hz)
                )
                lufs_i = compute_lufs_integrated_float64(
                    samples_array,
                    int(sample_rate_hz),
                    channels,
                    channel_mask=stem.get("wav_channel_mask"),
                    channel_layout=stem.get("channel_layout"),
                )
                lufs_s = compute_lufs_shortterm_float64(
                    samples_array,
                    int(sample_rate_hz),
                    channels,
                    channel_mask=stem.get("wav_channel_mask"),
                    channel_layout=stem.get("channel_layout"),
                )
            except ValueError:
                continue
            if pair_accumulator is not None:
                pair_correlations = pair_accumulator.correlations()
                pair_source = "ffmpeg_f64le"
        else:
            continue

        upsert_measurement(
            stem,
            evidence_id="EVID.METER.TRUEPEAK_DBTP",
            value=truepeak_dbtp,
            unit_id="UNIT.DBTP",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_I",
            value=lufs_i,
            unit_id="UNIT.LUFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_S",
            value=lufs_s,
            unit_id="UNIT.LUFS",
        )
        gi_csv = ",".join(f"{weight:.2f}" for weight in weights)

        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_WEIGHTING_MODE",
            value=mode_str,
            unit_id="UNIT.NONE",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_WEIGHTING_ORDER",
            value=order_csv,
            unit_id="UNIT.NONE",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_WEIGHTING_GI",
            value=gi_csv,
            unit_id="UNIT.NONE",
        )

        if pair_correlations is not None and pair_source is not None and pair_meta:
            for meta in pair_meta:
                token = meta["token"]
                corr = pair_correlations.get(token)
                if corr is None:
                    continue
                upsert_measurement(
                    stem,
                    evidence_id=meta["evidence_id"],
                    value=corr,
                    unit_id="UNIT.CORRELATION",
                )
            pairs_log = _build_pairs_log(
                mode_str=mode_str,
                order_csv=order_csv,
                channels=channels,
                source=pair_source,
                pair_meta=pair_meta,
                correlations=pair_correlations,
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.IMAGE.CORRELATION_PAIRS_LOG",
                value=pairs_log,
                unit_id="UNIT.NONE",
            )
        elif skip_reason and channels >= 2:
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
                upsert_measurement(
                    stem,
                    evidence_id="EVID.IMAGE.CORRELATION_PAIRS_LOG",
                    value=pairs_log,
                    unit_id="UNIT.NONE",
                )

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
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue

        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
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
        elif format_id in {"flac", "wavpack", "aiff"}:
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
    file_path = stem.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return None
    stem_path = Path(file_path)
    if not stem_path.is_absolute():
        stem_path = stems_dir / stem_path
    format_id = detect_format_from_path(stem_path)
    samples: List[float] = []
    if format_id == "wav":
        try:
            for chunk in iter_wav_float64_samples(stem_path, error_context="lfe audit"):
                samples.extend(chunk)
        except ValueError:
            return None
        return samples
    elif format_id in {"flac", "wavpack", "aiff"}:
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
        file_path = stem.get("file_path", "")
        stem_path = Path(file_path) if file_path else None
        if stem_path and not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        format_id = detect_format_from_path(stem_path) if stem_path else None
        if format_id in {"flac", "wavpack", "aiff"} and ffmpeg_cmd is None:
            ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True

        all_samples = _collect_stem_samples(stem, stems_dir, ffmpeg_cmd)
        if all_samples is None:
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

        for lfe_idx in lfe_indices:
            lfe_mono = _extract_channel(all_samples, channels, lfe_idx)
            if not lfe_mono:
                continue

            audit_result = audit_lfe_channel(
                lfe_mono,
                mains_samples if mains_samples else None,
                int(sample_rate_hz),
            )

            # Store LFE measurements on the stem
            _upsert_lfe_measurements(stem, lfe_idx, audit_result)

            # Build issues
            stem_issues = build_lfe_audit_issues(
                stem_id, lfe_idx, audit_result, strict=strict
            )
            issues.extend(stem_issues)

    return missing_ffmpeg


def _upsert_lfe_measurements(
    stem: Dict[str, Any], channel_index: int, audit_result: Dict[str, Any]
) -> None:
    """Store LFE audit metrics as stem measurements."""
    import math  # noqa: WPS433

    def _safe(v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return round(v, 3) if math.isfinite(v) else None

    pairs = [
        ("EVID.LFE.BAND_ENERGY_DB", audit_result.get("inband_energy_db"), "UNIT.DB"),
        ("EVID.LFE.OUT_OF_BAND_DB", audit_result.get("out_of_band_energy_db"), "UNIT.DB"),
        ("EVID.LFE.INFRASONIC_DB", audit_result.get("infrasonic_energy_db"), "UNIT.DB"),
        ("EVID.LFE.CREST_FACTOR_DB", audit_result.get("crest_factor_db"), "UNIT.DB"),
        ("EVID.LFE.PEAK_DBFS", audit_result.get("peak_dbfs"), "UNIT.DBFS"),
    ]
    for evidence_id, value, unit_id in pairs:
        safe_val = _safe(value)
        if safe_val is not None:
            upsert_measurement(stem, evidence_id=evidence_id, value=safe_val, unit_id=unit_id)

    ratio = audit_result.get("lfe_to_mains_ratio_db")
    if ratio is not None:
        safe_ratio = _safe(ratio)
        if safe_ratio is not None:
            upsert_measurement(
                stem,
                evidence_id="EVID.LFE.MAINS_RATIO_DB",
                value=safe_ratio,
                unit_id="UNIT.DB",
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

    import re  # noqa: WPS433
    _token_re = re.compile(r"[\s_.\-\[\]\(\)\{\}]+")

    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id", "")
        file_path = stem.get("file_path", "")
        name = Path(file_path).stem if file_path else stem_id
        tokens = {t.lower() for t in _token_re.split(name) if t}
        # Strip leading track numbers (e.g. "01_kick" → tokens {"01", "kick"})
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


def build_report(
    stems_dir: Path,
    generated_at: str,
    *,
    strict: bool = False,
    include_peak: bool = False,
    meters: Optional[str] = None,
) -> Dict[str, Any]:
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

    # Detect numpy availability early (shared by truth meters, mix complexity, LFE audit)
    try:
        import numpy  # noqa: F401
        numpy_available = True
    except ImportError:
        numpy_available = False

    # truth mode subsumes basic: run both so crest/RMS/peak are always present
    if meters in {"basic", "truth"}:
        missing_ffmpeg = _add_basic_meter_measurements(session, stems_dir)
    issues = validate_session(session, strict=strict)

    # Role naming convention validation (lightweight keyword check)
    _validate_role_names(session, issues)

    if meters == "truth":
        if not numpy_available:
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Install: pip install .[truth]",
            )
        else:
            missing_ffmpeg = _add_truth_meter_measurements(session, stems_dir) or missing_ffmpeg
    if meters in {"basic", "truth"}:
        if numpy_available:
            mix_complexity, mix_missing_ffmpeg = _build_mix_complexity(session, stems_dir)
            missing_ffmpeg = mix_missing_ffmpeg or missing_ffmpeg
        else:
            mix_complexity = _default_mix_complexity_payload()
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Install: pip install .[truth]",
            )

    # LFE content audit — always attempt when numpy is available
    lfe_missing_numpy = _add_lfe_audit_issues(session, stems_dir, issues, strict=strict)
    if lfe_missing_numpy and not numpy_available:
        # Only surface numpy issue once
        _add_optional_dep_issue(
            issues,
            dep_name="numpy",
            hint="Install: pip install .[truth]",
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
        report["mix_complexity"] = mix_complexity
        report["vibe_signals"] = derive_vibe_signals(report)
        report["preset_recommendations"] = derive_preset_recommendations(
            report,
            presets_dir(),
        )
    if metering_summary is not None:
        report["metering"] = metering_summary
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
            _validate_schema(Path(args.schema), report)

        # --dry-run: print summary only, do not write file
        if args.dry_run:
            print(_render_scan_summary(report))
            return 0

        # --summary: print human-readable summary to stdout
        if args.summary:
            print(_render_scan_summary(report))

        output = json.dumps(report, indent=2)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output + "\n", encoding="utf-8")
        elif not args.summary:
            # Default: print JSON to stdout (unless --summary already printed it)
            print(output)

        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
