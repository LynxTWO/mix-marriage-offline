from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from mmo.core.downmix import (
    apply_downmix_matrix_deterministic,
    compare_rendered_surround_to_stereo_reference,
)
from mmo.core.lfe_audit import detect_lfe_channel_indices
from mmo.dsp.downmix import _Biquad, _design_biquad
from mmo.dsp.export_finalize import (
    StreamingExportFinalizer,
    resolve_dither_policy_for_bit_depth,
)
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples

LFE_CORRECTIVE_QA_THRESHOLDS: dict[str, float] = {
    "loudness_delta_warn_abs": 0.5,
    "loudness_delta_error_abs": 1.0,
    "correlation_time_warn_lte": 0.92,
    "correlation_time_error_lte": 0.85,
    "spectral_distance_warn_db": 2.0,
    "spectral_distance_error_db": 4.0,
    "peak_delta_warn_abs": 1.0,
    "peak_delta_error_abs": 2.0,
    "true_peak_delta_warn_abs": 1.0,
    "true_peak_delta_error_abs": 2.0,
}

_SUPPORTED_FILTER_TYPES = frozenset({"bell", "high_pass", "low_pass"})
_SUPPORTED_PHASE_MODES = frozenset({"minimum_phase"})
_DEFAULT_FILTER_Q = 0.7071
_DEFAULT_FILTER_GAIN_DB = 0.0
_DEFAULT_PHASE_MODE = "minimum_phase"
_DEFAULT_BIT_DEPTH = 24
_WAV_EXTENSIONS = frozenset({".wav", ".wave"})

_LFE_CORRECTIVE_ACTION_IDS = frozenset(
    {
        "ACTION.EQ.HIGH_PASS",
        "ACTION.EQ.LOW_PASS",
        "ACTION.FILTER.BELL",
        "ACTION.FILTER.HPF",
        "ACTION.FILTER.LPF",
        "ACTION.LFE.CORRECTIVE_FILTER",
        "ACTION.LFE.HIGH_PASS",
        "ACTION.LFE.LOW_PASS",
    }
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
        return None
    if isinstance(value, str) and value.strip():
        try:
            candidate = float(value)
        except ValueError:
            return None
        if math.isfinite(candidate):
            return candidate
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def append_note(existing: Any, addition: str) -> str:
    base = _coerce_str(existing).strip()
    note = addition.strip()
    if not note:
        return base
    if not base:
        return note
    if note in base:
        return base
    return f"{base} {note}"


def is_lfe_corrective_action_id(action_id: str) -> bool:
    return _coerce_str(action_id).strip() in _LFE_CORRECTIVE_ACTION_IDS


def _measurement_index(stem: Mapping[str, Any]) -> dict[str, Any]:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        return {}
    indexed: dict[str, Any] = {}
    for row in measurements:
        if not isinstance(row, Mapping):
            continue
        evidence_id = _coerce_str(row.get("evidence_id")).strip()
        if not evidence_id:
            continue
        indexed[evidence_id] = row.get("value")
    return indexed


def stem_has_explicit_lfe(stem: Mapping[str, Any]) -> bool:
    speaker_id = _coerce_str(stem.get("speaker_id")).strip().upper()
    if speaker_id.startswith("SPK.LFE"):
        return True

    role_id = _coerce_str(stem.get("role_id")).strip().upper()
    if role_id.endswith(".LFE") or ".LFE." in role_id:
        return True

    measurements = _measurement_index(stem)
    if any(evidence_id.startswith("EVID.LFE.") for evidence_id in measurements):
        return True

    channels = _coerce_int(stem.get("channel_count"))
    if channels is None:
        channels = _coerce_int(stem.get("channels"))
    if channels is None or channels <= 0:
        return False

    lfe_indices = detect_lfe_channel_indices(
        channels,
        channel_layout=_coerce_str(stem.get("channel_layout")).strip() or None,
        wav_channel_mask=_coerce_int(stem.get("wav_channel_mask")),
    )
    return bool(lfe_indices)


def explicit_lfe_stem_ids(session: Mapping[str, Any]) -> list[str]:
    stems = session.get("stems")
    if not isinstance(stems, list):
        return []
    stem_ids = {
        stem_id
        for stem in stems
        if isinstance(stem, Mapping)
        for stem_id in [_coerce_str(stem.get("stem_id")).strip()]
        if stem_id and stem_has_explicit_lfe(stem)
    }
    return sorted(stem_ids)


def recommendation_targets_explicit_lfe(
    rec: Mapping[str, Any],
    explicit_lfe_ids: Sequence[str],
) -> bool:
    explicit_ids = {item for item in explicit_lfe_ids if _coerce_str(item).strip()}
    if not explicit_ids:
        return False

    scope = rec.get("scope")
    if isinstance(scope, Mapping):
        stem_id = _coerce_str(scope.get("stem_id")).strip()
        if stem_id and stem_id in explicit_ids:
            return True

    target = rec.get("target")
    if isinstance(target, Mapping):
        stem_id = _coerce_str(target.get("stem_id")).strip()
        if stem_id and stem_id in explicit_ids:
            return True

    return False


def corrective_filter_spec_from_recommendation(
    rec: Mapping[str, Any],
) -> dict[str, Any] | None:
    action_id = _coerce_str(rec.get("action_id")).strip()
    if not is_lfe_corrective_action_id(action_id):
        return None

    params = rec.get("params")
    param_values: dict[str, Any] = {}
    if isinstance(params, list):
        for row in params:
            if not isinstance(row, Mapping):
                continue
            param_id = _coerce_str(row.get("param_id")).strip()
            if not param_id:
                continue
            param_values[param_id] = row.get("value")

    filter_type = _coerce_str(param_values.get("PARAM.EQ.TYPE")).strip().lower()
    if not filter_type:
        if action_id in {"ACTION.EQ.HIGH_PASS", "ACTION.FILTER.HPF", "ACTION.LFE.HIGH_PASS"}:
            filter_type = "high_pass"
        elif action_id in {"ACTION.EQ.LOW_PASS", "ACTION.FILTER.LPF", "ACTION.LFE.LOW_PASS"}:
            filter_type = "low_pass"
    if filter_type not in _SUPPORTED_FILTER_TYPES:
        return None

    cutoff_hz = _coerce_float(param_values.get("PARAM.EQ.FREQ_HZ"))
    if cutoff_hz is None or cutoff_hz <= 0.0:
        return None

    slope_db_oct = _coerce_float(param_values.get("PARAM.EQ.SLOPE_DB_PER_OCT"))
    if slope_db_oct is None or slope_db_oct <= 0.0:
        slope_db_oct = 24.0

    q = _coerce_float(param_values.get("PARAM.EQ.Q"))
    if q is None or q <= 0.0:
        q = _DEFAULT_FILTER_Q

    gain_db = _coerce_float(param_values.get("PARAM.EQ.GAIN_DB"))
    if gain_db is None:
        gain_db = _DEFAULT_FILTER_GAIN_DB

    phase_mode = _coerce_str(param_values.get("PARAM.EQ.PHASE_MODE")).strip().lower()
    if not phase_mode:
        phase_mode = _DEFAULT_PHASE_MODE
    if phase_mode not in _SUPPORTED_PHASE_MODES:
        return None

    speaker_id = _coerce_str(param_values.get("PARAM.SURROUND.SPEAKER_ID")).strip()
    if not speaker_id:
        speaker_id = "SPK.LFE"

    return {
        "filter_type": filter_type,
        "cutoff_hz": round(cutoff_hz, 4),
        "slope_db_oct": round(abs(slope_db_oct), 4),
        "q": round(q, 4),
        "gain_db": round(gain_db, 4),
        "phase_mode": phase_mode,
        "speaker_id": speaker_id,
    }


def corrective_filter_candidates(filter_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    normalized = dict(filter_spec)
    candidates: list[dict[str, Any]] = [normalized]
    filter_type = _coerce_str(normalized.get("filter_type")).strip().lower()
    cutoff_hz = float(normalized.get("cutoff_hz") or 0.0)
    slope_db_oct = float(normalized.get("slope_db_oct") or 0.0)
    q = float(normalized.get("q") or _DEFAULT_FILTER_Q)
    gain_db = float(normalized.get("gain_db") or 0.0)

    if filter_type in {"high_pass", "low_pass"}:
        step_down_slope = max(12.0, min(slope_db_oct, 24.0) / 2.0)
        relaxed_cutoff = cutoff_hz
        if filter_type == "low_pass":
            relaxed_cutoff = cutoff_hz * 1.25
        elif filter_type == "high_pass":
            relaxed_cutoff = max(10.0, cutoff_hz * 0.8)

        for candidate in (
            {
                **normalized,
                "slope_db_oct": round(step_down_slope, 4),
            },
            {
                **normalized,
                "cutoff_hz": round(relaxed_cutoff, 4),
                "slope_db_oct": 12.0,
            },
        ):
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    if filter_type == "bell":
        for candidate_gain_db, candidate_q in (
            (gain_db * 0.5, max(0.5, q * 0.85)),
            (gain_db * 0.25, max(0.5, q * 0.7)),
        ):
            candidate = {
                **normalized,
                "gain_db": round(candidate_gain_db, 4),
                "q": round(candidate_q, 4),
            }
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _resolved_bit_depth(metadata: Mapping[str, Any]) -> int:
    bits = _coerce_int(metadata.get("bits_per_sample"))
    if bits in {16, 24, 32}:
        return bits
    return _DEFAULT_BIT_DEPTH


def _design_bell_biquad(
    *,
    freq_hz: float,
    sample_rate_hz: int,
    q: float,
    gain_db: float,
) -> _Biquad:
    nyquist = float(sample_rate_hz) / 2.0
    if freq_hz >= nyquist:
        raise ValueError(
            f"bell freq_hz must be < Nyquist ({nyquist:.3f} Hz)"
        )
    q_value = max(0.05, float(q))
    amplitude = math.pow(10.0, float(gain_db) / 40.0)
    omega = 2.0 * math.pi * float(freq_hz) / float(sample_rate_hz)
    sin_omega = math.sin(omega)
    cos_omega = math.cos(omega)
    alpha = sin_omega / (2.0 * q_value)

    b0 = 1.0 + (alpha * amplitude)
    b1 = -2.0 * cos_omega
    b2 = 1.0 - (alpha * amplitude)
    a0 = 1.0 + (alpha / amplitude)
    a1 = -2.0 * cos_omega
    a2 = 1.0 - (alpha / amplitude)
    if a0 == 0.0:
        raise ValueError("Invalid bell biquad design (a0 == 0)")

    inv_a0 = 1.0 / a0
    return _Biquad(
        b0=b0 * inv_a0,
        b1=b1 * inv_a0,
        b2=b2 * inv_a0,
        a1=a1 * inv_a0,
        a2=a2 * inv_a0,
    )


def _build_filter_chain(
    *,
    filter_spec: Mapping[str, Any],
    sample_rate_hz: int,
) -> list[_Biquad]:
    phase_mode = _coerce_str(filter_spec.get("phase_mode")).strip().lower()
    if phase_mode not in _SUPPORTED_PHASE_MODES:
        raise ValueError(
            f"Unsupported corrective filter phase_mode: {phase_mode!r}"
        )

    filter_type = _coerce_str(filter_spec.get("filter_type")).strip().lower()
    cutoff_hz = float(filter_spec.get("cutoff_hz") or 0.0)
    slope_db_oct = float(filter_spec.get("slope_db_oct") or 0.0)
    q = float(filter_spec.get("q") or _DEFAULT_FILTER_Q)
    gain_db = float(filter_spec.get("gain_db") or 0.0)

    if filter_type in {"low_pass", "high_pass"}:
        stage_count = max(1, int(round(max(12.0, abs(slope_db_oct)) / 12.0)))
        biquad_type = "lowpass" if filter_type == "low_pass" else "highpass"
        return [
            _design_biquad(biquad_type, cutoff_hz, int(sample_rate_hz))
            for _ in range(stage_count)
        ]

    if filter_type == "bell":
        return [
            _design_bell_biquad(
                freq_hz=cutoff_hz,
                sample_rate_hz=int(sample_rate_hz),
                q=q,
                gain_db=gain_db,
            )
        ]

    raise ValueError(f"Unsupported corrective filter type: {filter_type!r}")


def _lfe_channel_indices(channel_order: Sequence[str]) -> list[int]:
    indices: list[int] = []
    for index, speaker_id in enumerate(channel_order):
        if _coerce_str(speaker_id).strip().upper().startswith("SPK.LFE"):
            indices.append(index)
    return indices


def _process_interleaved_chunk(
    samples: list[float],
    *,
    channels: int,
    filter_chains: Mapping[int, list[_Biquad]],
) -> list[float]:
    if not samples or not filter_chains:
        return list(samples)
    processed = list(samples)
    frame_count = len(processed) // channels
    for channel_index, chain in filter_chains.items():
        if channel_index < 0 or channel_index >= channels:
            continue
        for frame_index in range(frame_count):
            sample_index = (frame_index * channels) + channel_index
            value = float(processed[sample_index])
            for biquad in chain:
                value = biquad.process(value)
            processed[sample_index] = value
    return processed


def write_filtered_lfe_wav(
    *,
    source_path: Path,
    output_path: Path,
    channel_order: Sequence[str],
    filter_spec: Mapping[str, Any],
    seed: int = 0,
    dither_policy: str | None = None,
) -> bool:
    metadata = read_wav_metadata(source_path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    if channels <= 0 or sample_rate_hz <= 0:
        raise ValueError(f"Invalid WAV metadata for corrective filter: {source_path}")
    if source_path.suffix.lower() not in _WAV_EXTENSIONS:
        raise ValueError("Corrective filter post-processing currently supports WAV outputs only.")
    if len(channel_order) != channels:
        raise ValueError(
            "channel_order length must match WAV channels for corrective filter post-processing."
        )

    lfe_indices = _lfe_channel_indices(channel_order)
    if not lfe_indices:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bit_depth = _resolved_bit_depth(metadata)
    resolved_dither_policy = resolve_dither_policy_for_bit_depth(bit_depth, dither_policy)
    chains = {
        channel_index: _build_filter_chain(
            filter_spec=filter_spec,
            sample_rate_hz=sample_rate_hz,
        )
        for channel_index in lfe_indices
    }

    carry: list[float] = []
    finalizer = StreamingExportFinalizer(
        channels=channels,
        bit_depth=bit_depth,
        dither_policy=resolved_dither_policy,
        seed=int(seed),
    )
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)

        for chunk in iter_wav_float64_samples(
            source_path,
            error_context="lfe corrective filter post-process",
        ):
            merged = carry + list(chunk)
            usable = (len(merged) // channels) * channels
            if usable <= 0:
                carry = merged
                continue
            carry = merged[usable:]
            processed = _process_interleaved_chunk(
                merged[:usable],
                channels=channels,
                filter_chains=chains,
            )
            handle.writeframes(finalizer.finalize_chunk(processed))

        if carry:
            raise ValueError("Corrective filter decode returned non-frame-aligned samples.")

    return True


def _load_wav_interleaved(path: Path) -> dict[str, Any]:
    metadata = read_wav_metadata(path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    if channels <= 0 or sample_rate_hz <= 0:
        raise ValueError(f"Invalid WAV metadata: {path}")

    interleaved: list[float] = []
    for chunk in iter_wav_float64_samples(
        path,
        error_context="lfe corrective reference fold",
    ):
        if chunk:
            interleaved.extend(chunk)

    total = len(interleaved) - (len(interleaved) % channels)
    return {
        "channels": channels,
        "sample_rate_hz": sample_rate_hz,
        "interleaved": interleaved[:total],
    }


def _write_interleaved_wav(
    *,
    output_path: Path,
    interleaved: Iterable[float],
    channels: int,
    sample_rate_hz: int,
    bit_depth: int = _DEFAULT_BIT_DEPTH,
    seed: int = 0,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    finalizer = StreamingExportFinalizer(
        channels=channels,
        bit_depth=bit_depth,
        dither_policy=resolve_dither_policy_for_bit_depth(bit_depth),
        seed=int(seed),
    )
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(finalizer.finalize_chunk(list(interleaved)))


def _mono_from_interleaved(
    interleaved: Sequence[float],
    *,
    channels: int,
) -> list[float]:
    if channels <= 0:
        return []
    usable = len(interleaved) - (len(interleaved) % channels)
    if usable <= 0:
        return []
    frames = usable // channels
    mono: list[float] = []
    for frame_index in range(frames):
        base = frame_index * channels
        total = 0.0
        for channel_index in range(channels):
            total += float(interleaved[base + channel_index])
        mono.append(total / float(channels))
    return mono


def _rms_dbfs(samples: Sequence[float]) -> float | None:
    if not samples:
        return None
    mean_square = sum(float(sample) * float(sample) for sample in samples) / float(len(samples))
    if mean_square <= 0.0:
        return None
    return 20.0 * math.log10(math.sqrt(mean_square))


def _peak_dbfs(samples: Sequence[float]) -> float | None:
    if not samples:
        return None
    peak = max(abs(float(sample)) for sample in samples)
    if peak <= 0.0:
        return None
    return 20.0 * math.log10(peak)


def _pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    count = min(len(left), len(right))
    if count <= 0:
        return 0.0
    left_mean = sum(float(value) for value in left[:count]) / float(count)
    right_mean = sum(float(value) for value in right[:count]) / float(count)
    numerator = 0.0
    left_power = 0.0
    right_power = 0.0
    for index in range(count):
        left_value = float(left[index]) - left_mean
        right_value = float(right[index]) - right_mean
        numerator += left_value * right_value
        left_power += left_value * left_value
        right_power += right_value * right_value
    denominator = math.sqrt(left_power * right_power)
    if denominator <= 0.0:
        return 0.0
    correlation = numerator / denominator
    if correlation > 1.0:
        return 1.0
    if correlation < -1.0:
        return -1.0
    return correlation


def _windowed_correlations(
    reference_mono: Sequence[float],
    candidate_mono: Sequence[float],
    *,
    sample_rate_hz: int,
) -> dict[str, float]:
    total = min(len(reference_mono), len(candidate_mono))
    if total <= 0:
        return {"min": 0.0, "mean": 0.0, "count": 0}
    window = max(1, int(sample_rate_hz))
    hop = max(1, window // 2)
    values: list[float] = []
    if total < window:
        values.append(_pearson_correlation(reference_mono[:total], candidate_mono[:total]))
    else:
        for start in range(0, total - window + 1, hop):
            end = start + window
            values.append(
                _pearson_correlation(
                    reference_mono[start:end],
                    candidate_mono[start:end],
                )
            )
    if not values:
        values = [0.0]
    return {
        "min": min(values),
        "mean": sum(values) / float(len(values)),
        "count": float(len(values)),
    }


def _delta_or_none(candidate: float | None, reference: float | None) -> float | None:
    if candidate is None or reference is None:
        return None
    return round(candidate - reference, 6)


def _fallback_similarity_metrics(
    *,
    reference_stereo: Sequence[float],
    candidate_stereo: Sequence[float],
    sample_rate_hz: int,
) -> dict[str, Any]:
    usable = min(len(reference_stereo), len(candidate_stereo))
    usable -= usable % 2
    if usable <= 0:
        raise ValueError("Corrective filter QA requires non-empty stereo reference and candidate audio.")

    reference_trimmed = list(reference_stereo[:usable])
    candidate_trimmed = list(candidate_stereo[:usable])
    reference_peak_dbfs = _peak_dbfs(reference_trimmed)
    candidate_peak_dbfs = _peak_dbfs(candidate_trimmed)
    if (
        reference_peak_dbfs is not None
        and candidate_peak_dbfs is not None
        and max(reference_peak_dbfs, candidate_peak_dbfs) <= -70.0
    ):
        return {
            "sample_rate_hz": int(sample_rate_hz),
            "frames_compared": usable // 2,
            "loudness_delta_lufs": 0.0,
            "correlation_over_time_min": 1.0,
            "correlation_over_time_mean": 1.0,
            "correlation_window_count": 1,
            "spectral_distance_db": None,
            "spectral_band_distance_db": {},
            "peak_delta_dbfs": 0.0,
            "true_peak_delta_dbtp": 0.0,
        }
    reference_mono = _mono_from_interleaved(reference_trimmed, channels=2)
    candidate_mono = _mono_from_interleaved(candidate_trimmed, channels=2)
    correlation = _windowed_correlations(
        reference_mono,
        candidate_mono,
        sample_rate_hz=sample_rate_hz,
    )
    return {
        "sample_rate_hz": int(sample_rate_hz),
        "frames_compared": usable // 2,
        "loudness_delta_lufs": _delta_or_none(
            _rms_dbfs(candidate_trimmed),
            _rms_dbfs(reference_trimmed),
        ),
        "correlation_over_time_min": round(float(correlation["min"]), 6),
        "correlation_over_time_mean": round(float(correlation["mean"]), 6),
        "correlation_window_count": int(correlation["count"]),
        "spectral_distance_db": None,
        "spectral_band_distance_db": {},
        "peak_delta_dbfs": _delta_or_none(
            candidate_peak_dbfs,
            reference_peak_dbfs,
        ),
        # Fallback mode uses sample peak as a conservative proxy when truth meters
        # are unavailable in the local environment.
        "true_peak_delta_dbtp": _delta_or_none(
            candidate_peak_dbfs,
            reference_peak_dbfs,
        ),
    }


def _evaluate_similarity_metrics(metrics: Mapping[str, Any]) -> tuple[str, list[str]]:
    thresholds = LFE_CORRECTIVE_QA_THRESHOLDS
    notes: list[str] = []
    risk_level = "low"

    loudness_delta = metrics.get("loudness_delta_lufs")
    if isinstance(loudness_delta, (int, float)):
        if abs(float(loudness_delta)) >= float(thresholds["loudness_delta_error_abs"]):
            risk_level = "high"
            notes.append(
                "Loudness delta exceeds error threshold "
                f"(abs={abs(float(loudness_delta)):.3f})."
            )
        elif abs(float(loudness_delta)) >= float(thresholds["loudness_delta_warn_abs"]):
            risk_level = "medium"
            notes.append(
                "Loudness delta exceeds warning threshold "
                f"(abs={abs(float(loudness_delta)):.3f})."
            )

    corr_min = metrics.get("correlation_over_time_min")
    if isinstance(corr_min, (int, float)):
        if float(corr_min) <= float(thresholds["correlation_time_error_lte"]):
            risk_level = "high"
            notes.append(
                "Correlation-over-time minimum is below error threshold "
                f"({float(corr_min):.3f})."
            )
        elif float(corr_min) <= float(thresholds["correlation_time_warn_lte"]):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Correlation-over-time minimum is below warning threshold "
                f"({float(corr_min):.3f})."
            )

    peak_delta = metrics.get("peak_delta_dbfs")
    if isinstance(peak_delta, (int, float)):
        if abs(float(peak_delta)) >= float(thresholds["peak_delta_error_abs"]):
            risk_level = "high"
            notes.append(
                "Peak delta exceeds error threshold "
                f"(abs={abs(float(peak_delta)):.3f} dBFS)."
            )
        elif abs(float(peak_delta)) >= float(thresholds["peak_delta_warn_abs"]):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "Peak delta exceeds warning threshold "
                f"(abs={abs(float(peak_delta)):.3f} dBFS)."
            )

    true_peak_delta = metrics.get("true_peak_delta_dbtp")
    if isinstance(true_peak_delta, (int, float)):
        if abs(float(true_peak_delta)) >= float(thresholds["true_peak_delta_error_abs"]):
            risk_level = "high"
            notes.append(
                "True-peak delta exceeds error threshold "
                f"(abs={abs(float(true_peak_delta)):.3f} dBTP)."
            )
        elif abs(float(true_peak_delta)) >= float(thresholds["true_peak_delta_warn_abs"]):
            if risk_level == "low":
                risk_level = "medium"
            notes.append(
                "True-peak delta exceeds warning threshold "
                f"(abs={abs(float(true_peak_delta)):.3f} dBTP)."
            )

    return risk_level, notes


def _compare_filtered_output_to_baseline_fallback(
    *,
    baseline_surround_path: Path,
    candidate_surround_path: Path,
    source_layout_id: str,
) -> dict[str, Any]:
    baseline = _load_wav_interleaved(baseline_surround_path)
    candidate = _load_wav_interleaved(candidate_surround_path)
    if int(baseline["sample_rate_hz"]) != int(candidate["sample_rate_hz"]):
        raise ValueError("Corrective filter QA requires matching sample rates.")

    baseline_fold = apply_downmix_matrix_deterministic(
        list(baseline["interleaved"]),
        source_layout_id=source_layout_id,
        target_layout_id="LAYOUT.2_0",
        sample_rate_hz=int(baseline["sample_rate_hz"]),
    )
    candidate_fold = apply_downmix_matrix_deterministic(
        list(candidate["interleaved"]),
        source_layout_id=source_layout_id,
        target_layout_id="LAYOUT.2_0",
        sample_rate_hz=int(candidate["sample_rate_hz"]),
    )
    metrics = _fallback_similarity_metrics(
        reference_stereo=list(baseline_fold["output_interleaved"]),
        candidate_stereo=list(candidate_fold["output_interleaved"]),
        sample_rate_hz=int(baseline["sample_rate_hz"]),
    )
    risk_level, notes = _evaluate_similarity_metrics(metrics)
    notes.append("Fallback corrective-filter QA path used sample-peak and RMS metrics.")
    return {
        "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
        "gate_version": "1.0.0",
        "source_layout_id": source_layout_id,
        "target_layout_id": "LAYOUT.2_0",
        "matrix_id": _coerce_str(baseline_fold.get("matrix_id")).strip(),
        "stereo_render_path": "",
        "surround_render_path": "",
        "metrics": metrics,
        "thresholds": dict(LFE_CORRECTIVE_QA_THRESHOLDS),
        "risk_level": risk_level,
        "passed": risk_level == "low",
        "notes": notes,
    }


def compare_filtered_output_to_baseline(
    *,
    baseline_surround_path: Path,
    candidate_surround_path: Path,
    source_layout_id: str,
) -> dict[str, Any]:
    return _compare_filtered_output_to_baseline_fallback(
        baseline_surround_path=baseline_surround_path,
        candidate_surround_path=candidate_surround_path,
        source_layout_id=source_layout_id,
    )


__all__ = [
    "LFE_CORRECTIVE_QA_THRESHOLDS",
    "append_note",
    "compare_filtered_output_to_baseline",
    "corrective_filter_candidates",
    "corrective_filter_spec_from_recommendation",
    "explicit_lfe_stem_ids",
    "is_lfe_corrective_action_id",
    "recommendation_targets_explicit_lfe",
    "stem_has_explicit_lfe",
    "write_filtered_lfe_wav",
]
