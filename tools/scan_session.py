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

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo import __version__ as engine_version  # noqa: E402
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
    if meters == "basic":
        missing_ffmpeg = _add_basic_meter_measurements(session, stems_dir)
    issues = validate_session(session, strict=strict)
    if meters == "truth":
        try:
            import numpy  # noqa: F401
        except ImportError:
            numpy_available = False
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Install: pip install .[truth]",
            )
        else:
            numpy_available = True
            missing_ffmpeg = _add_truth_meter_measurements(session, stems_dir) or missing_ffmpeg
    if meters in {"basic", "truth"}:
        if numpy_available is None:
            try:
                import numpy  # noqa: F401
            except ImportError:
                numpy_available = False
                _add_optional_dep_issue(
                    issues,
                    dep_name="numpy",
                    hint="Install: pip install .[truth]",
                )
            else:
                numpy_available = True
        if numpy_available:
            mix_complexity, mix_missing_ffmpeg = _build_mix_complexity(session, stems_dir)
            missing_ffmpeg = mix_missing_ffmpeg or missing_ffmpeg
        else:
            mix_complexity = _default_mix_complexity_payload()
    if missing_ffmpeg:
        _add_optional_dep_issue(
            issues,
            dep_name="ffmpeg",
            hint="Install FFmpeg or set MMO_FFMPEG_PATH=/path/to/ffmpeg",
        )
    stem_hash = _hash_from_stems(session.get("stems", []))
    ontology_version = _load_ontology_version(ROOT_DIR / "ontology" / "ontology.yaml")
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

        output = json.dumps(report, indent=2)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)

        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
