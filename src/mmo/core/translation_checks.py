from __future__ import annotations

import json
import math
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from mmo.core.cache_keys import translation_cache_key
from mmo.core.cache_store import resolve_cache_dir
from mmo.dsp.correlation import OnlineCorrelationAccumulator
from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata

_CHUNK_FRAMES = 4096
_EPSILON = 1e-12
_SOURCE = "mmo.translation_checks"
_MONO_WINDOW_SIZE = 2048
_MONO_HOP_SIZE = 1024
_SPECTRAL_WINDOW_SIZE = 512
_SPECTRAL_HOP_SIZE = 512
_DEFAULT_SCORE_THRESHOLD = 70
_TRANSLATION_CHECKS_CACHE_VERSION = "translation_checks_v1"

_BANDS_HZ = {
    "sub": (0.0, 60.0),
    "low": (0.0, 120.0),
    "mid": (120.0, 2000.0),
    "presence": (2000.0, 6000.0),
    "phone": (300.0, 3400.0),
}


def _clip_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _score_ratio(score: int) -> float:
    return round(max(0.0, min(1.0, score / 100.0)), 6)


def _safe_db(value: float) -> float:
    return 20.0 * math.log10(max(value, _EPSILON))


def _rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in values) / float(len(values)))


def _weighted_penalty(value: float, threshold: float) -> float:
    if value <= threshold:
        return 0.0
    scale = max(abs(threshold), 1.0)
    return max(0.0, min(1.0, (value - threshold) / scale))


def _deficit_penalty(value: float, threshold: float) -> float:
    if value >= threshold:
        return 0.0
    scale = max(1.0 - threshold, 1e-6)
    return max(0.0, min(1.0, (threshold - value) / scale))


def _float_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _score_threshold(profile: dict[str, Any]) -> int:
    raw = profile.get("score_threshold")
    if not isinstance(raw, (int, float)):
        raw = profile.get("pass_threshold")
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, (int, float)):
        return _clip_score(float(raw))
    return _DEFAULT_SCORE_THRESHOLD


def _severity_from_score(score: int, threshold: int) -> int:
    gap = max(1, threshold - score)
    return max(50, min(90, 50 + gap))


def _iter_wav_float64_chunks(path: Path) -> tuple[int, int, Iterator[list[float]]]:
    metadata = read_wav_metadata(path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    audio_format = int(metadata.get("audio_format_resolved", 0) or 0)
    bits_per_sample = int(metadata.get("bits_per_sample", 0) or 0)

    if channels <= 0:
        raise ValueError(f"Invalid channel count in WAV: {path}")
    if channels > 2:
        raise ValueError(
            f"Translation checks require mono or stereo WAV input (1 or 2 channels), got {channels}."
        )
    if audio_format == 1 and bits_per_sample not in (16, 24, 32):
        raise ValueError(f"Unsupported PCM bits per sample: {bits_per_sample}")
    if audio_format == 3 and bits_per_sample not in (32, 64):
        raise ValueError(f"Unsupported IEEE float bits per sample: {bits_per_sample}")
    if audio_format not in (1, 3):
        raise ValueError(f"Unsupported WAV format for translation checks: {audio_format}")

    def _chunks() -> Iterator[list[float]]:
        try:
            with wave.open(str(path), "rb") as handle:
                while True:
                    frames = handle.readframes(_CHUNK_FRAMES)
                    if not frames:
                        break
                    if audio_format == 1:
                        ints = bytes_to_int_samples_pcm(frames, bits_per_sample, channels)
                        if not ints:
                            continue
                        yield pcm_int_to_float64(ints, bits_per_sample)
                    else:
                        floats = bytes_to_float_samples_ieee(frames, bits_per_sample, channels)
                        if not floats:
                            continue
                        yield floats
        except (OSError, wave.Error) as exc:
            raise ValueError(f"Failed to read WAV for translation checks: {path}") from exc

    return sample_rate_hz, channels, _chunks()


def _load_channels(path: Path) -> tuple[int, list[float], list[float]]:
    sample_rate_hz, channels, chunks = _iter_wav_float64_chunks(path)
    left: list[float] = []
    right: list[float] = []

    for chunk in chunks:
        if not isinstance(chunk, list) or not chunk:
            continue
        if channels == 1:
            left.extend(chunk)
            continue
        total = len(chunk) - (len(chunk) % 2)
        for index in range(0, total, 2):
            left.append(float(chunk[index]))
            right.append(float(chunk[index + 1]))

    if channels == 1:
        right = list(left)
    return sample_rate_hz, left, right


def _iter_windows(
    samples: list[float],
    *,
    window_size: int,
    hop_size: int,
) -> Iterator[tuple[int, list[float]]]:
    if window_size <= 0 or hop_size <= 0:
        raise ValueError("window_size and hop_size must be positive.")
    if not samples:
        yield (0, [0.0] * window_size)
        return

    start = 0
    n = len(samples)
    while True:
        end = min(n, start + window_size)
        window = list(samples[start:end])
        if len(window) < window_size:
            window.extend([0.0] * (window_size - len(window)))
        yield (start, window)
        if end >= n:
            break
        start += hop_size


def _coerce_scoring(profile: dict[str, Any]) -> dict[str, float]:
    scoring = profile.get("scoring")
    source = scoring if isinstance(scoring, dict) else {}
    return {
        "mono_compatibility": _float_value(source.get("mono_compatibility"), 0.0),
        "spectral_balance": _float_value(source.get("spectral_balance"), 0.0),
        "vocal_clarity": _float_value(source.get("vocal_clarity"), 0.0),
        "low_end_translation": _float_value(source.get("low_end_translation"), 0.0),
        "fatigue_risk": _float_value(source.get("fatigue_risk"), 0.0),
    }


def _coerce_thresholds(profile: dict[str, Any]) -> dict[str, float]:
    thresholds = profile.get("default_thresholds")
    source = thresholds if isinstance(thresholds, dict) else {}
    return {
        "max_lufs_delta": _float_value(source.get("max_lufs_delta"), 2.0),
        "max_spectral_delta_db": _float_value(source.get("max_spectral_delta_db"), 3.0),
        "min_mono_correlation": _float_value(source.get("min_mono_correlation"), 0.2),
        "max_transient_smear": _float_value(source.get("max_transient_smear"), 0.3),
        "max_hf_harshness_db": _float_value(source.get("max_hf_harshness_db"), 2.0),
    }


def _mono_loss_db(left: list[float], right: list[float]) -> float:
    mono = [(l_value + r_value) * 0.5 for l_value, r_value in zip(left, right)]
    mono_rms = _rms(mono)
    left_rms = _rms(left)
    right_rms = _rms(right)
    stereo_rms = math.sqrt(
        (left_rms * left_rms + right_rms * right_rms) * 0.5
    )
    return _safe_db(mono_rms) - _safe_db(stereo_rms)


def _compute_mono_metrics(
    left: list[float],
    right: list[float],
    *,
    sample_rate_hz: int,
) -> dict[str, Any]:
    corr_acc = OnlineCorrelationAccumulator()
    for l_value, r_value in zip(left, right):
        corr_acc.update(l_value, r_value)
    correlation = float(corr_acc.correlation())

    overall_loss_db = _mono_loss_db(left, right)

    worst_loss_db = float("inf")
    worst_start = 0
    worst_end = 0
    windows_l = _iter_windows(left, window_size=_MONO_WINDOW_SIZE, hop_size=_MONO_HOP_SIZE)
    windows_r = _iter_windows(right, window_size=_MONO_WINDOW_SIZE, hop_size=_MONO_HOP_SIZE)
    for (start, window_l), (_, window_r) in zip(windows_l, windows_r):
        window_loss_db = _mono_loss_db(window_l, window_r)
        if window_loss_db < worst_loss_db:
            worst_loss_db = window_loss_db
            worst_start = start
            worst_end = start + _MONO_WINDOW_SIZE

    if not math.isfinite(worst_loss_db):
        worst_loss_db = overall_loss_db

    return {
        "correlation": correlation,
        "mono_loss_db": float(overall_loss_db),
        "worst_segment": {
            "start_s": round(max(0.0, worst_start / float(max(sample_rate_hz, 1))), 6),
            "end_s": round(max(0.0, worst_end / float(max(sample_rate_hz, 1))), 6),
            "mono_loss_db": float(worst_loss_db),
        },
    }


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def _fft_power_spectrum_real(samples: list[float]) -> list[float]:
    size = len(samples)
    if size == 0:
        return []
    if not _is_power_of_two(size):
        raise ValueError("FFT window size must be a power of two.")

    data = [complex(sample, 0.0) for sample in samples]
    j = 0
    for index in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if index < j:
            data[index], data[j] = data[j], data[index]

    length = 2
    while length <= size:
        half = length // 2
        theta = -2.0 * math.pi / float(length)
        w_step = complex(math.cos(theta), math.sin(theta))
        for offset in range(0, size, length):
            w_value = 1.0 + 0.0j
            for idx in range(half):
                even = data[offset + idx]
                odd = data[offset + idx + half] * w_value
                data[offset + idx] = even + odd
                data[offset + idx + half] = even - odd
                w_value *= w_step
        length *= 2

    return [
        (value.real * value.real) + (value.imag * value.imag)
        for value in data[: (size // 2) + 1]
    ]


def _band_bins(
    sample_rate_hz: int,
    *,
    window_size: int,
) -> dict[str, list[int]]:
    bins: dict[str, list[int]] = {}
    nyquist = sample_rate_hz / 2.0
    for band_name, (low_hz, high_hz) in _BANDS_HZ.items():
        upper = min(high_hz, nyquist)
        indices: list[int] = []
        for bin_index in range((window_size // 2) + 1):
            freq_hz = bin_index * sample_rate_hz / float(window_size)
            if low_hz <= freq_hz < upper:
                indices.append(bin_index)
        bins[band_name] = indices
    return bins


def _mean_band_power(power: list[float], indices: list[int]) -> float:
    if not indices:
        return _EPSILON
    total = 0.0
    count = 0
    for idx in indices:
        if 0 <= idx < len(power):
            total += power[idx]
            count += 1
    if count <= 0:
        return _EPSILON
    return max(_EPSILON, total / float(count))


def _compute_spectral_metrics(
    left: list[float],
    right: list[float],
    *,
    sample_rate_hz: int,
) -> dict[str, float]:
    mono = [(l_value + r_value) * 0.5 for l_value, r_value in zip(left, right)]
    if not mono:
        mono = [0.0]

    window = [
        0.5 - 0.5 * math.cos((2.0 * math.pi * idx) / (_SPECTRAL_WINDOW_SIZE - 1))
        for idx in range(_SPECTRAL_WINDOW_SIZE)
    ]
    bins = _band_bins(sample_rate_hz, window_size=_SPECTRAL_WINDOW_SIZE)
    window_count = 0
    energy_total = {band_name: 0.0 for band_name in _BANDS_HZ.keys()}
    for _, samples in _iter_windows(
        mono,
        window_size=_SPECTRAL_WINDOW_SIZE,
        hop_size=_SPECTRAL_HOP_SIZE,
    ):
        windowed = [sample * window[idx] for idx, sample in enumerate(samples)]
        power = _fft_power_spectrum_real(windowed)
        for band_name, indices in bins.items():
            energy_total[band_name] += _mean_band_power(power, indices)
        window_count += 1

    window_count = max(1, window_count)
    for band_name in energy_total.keys():
        energy_total[band_name] = max(
            _EPSILON, energy_total[band_name] / float(window_count)
        )

    low_mid_db = _safe_db(energy_total["low"]) - _safe_db(energy_total["mid"])
    presence_mid_db = _safe_db(energy_total["presence"]) - _safe_db(energy_total["mid"])
    sub_mid_db = _safe_db(energy_total["sub"]) - _safe_db(energy_total["mid"])
    phone_mid_db = _safe_db(energy_total["phone"]) - _safe_db(energy_total["mid"])

    return {
        "low_mid_db": float(low_mid_db),
        "presence_mid_db": float(presence_mid_db),
        "sub_mid_db": float(sub_mid_db),
        "phone_mid_db": float(phone_mid_db),
    }


def _issue_score_low(
    *,
    profile_id: str,
    score: int,
    threshold: int,
    severity: int,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "issue_id": "ISSUE.TRANSLATION.PROFILE_SCORE_LOW",
        "severity": severity,
        "confidence": 1.0,
        "target": {"scope": "session"},
        "message": f"{profile_id} score {score} is below threshold {threshold}.",
        "evidence": evidence,
    }


def _mono_profile_result(
    *,
    profile_id: str,
    profile: dict[str, Any],
    mono_metrics: dict[str, Any],
) -> dict[str, Any]:
    thresholds = _coerce_thresholds(profile)
    scoring = _coerce_scoring(profile)
    score_threshold = _score_threshold(profile)

    correlation = _float_value(mono_metrics.get("correlation"), 0.0)
    mono_loss_db = _float_value(mono_metrics.get("mono_loss_db"), 0.0)
    worst_segment = mono_metrics.get("worst_segment")
    worst_segment_map = worst_segment if isinstance(worst_segment, dict) else {}
    worst_loss_db = _float_value(worst_segment_map.get("mono_loss_db"), mono_loss_db)

    corr_penalty = _deficit_penalty(correlation, thresholds["min_mono_correlation"])
    mono_loss_amount = max(0.0, -mono_loss_db)
    worst_loss_amount = max(0.0, -worst_loss_db)
    mono_loss_penalty = _weighted_penalty(
        mono_loss_amount, thresholds["max_spectral_delta_db"]
    )
    worst_loss_penalty = _weighted_penalty(
        worst_loss_amount, thresholds["max_spectral_delta_db"]
    )

    penalty = 100.0 * (
        scoring["mono_compatibility"] * corr_penalty
        + scoring["spectral_balance"] * mono_loss_penalty
        + scoring["vocal_clarity"] * worst_loss_penalty
        + scoring["low_end_translation"] * mono_loss_penalty * 0.5
        + scoring["fatigue_risk"] * corr_penalty * 0.5
    )
    score = _clip_score(100.0 - penalty)

    result: dict[str, Any] = {"profile_id": profile_id, "score": score}
    if score >= score_threshold:
        return result

    start_s = _float_value(worst_segment_map.get("start_s"), 0.0)
    end_s = _float_value(worst_segment_map.get("end_s"), 0.0)
    why = (
        "mono_loss_db below allowed threshold "
        f"(-{thresholds['max_spectral_delta_db']:.3f} dB) and/or "
        f"correlation below {thresholds['min_mono_correlation']:.3f}"
    )
    evidence = [
        {
            "evidence_id": "EVID.ISSUE.SCORE",
            "value": _score_ratio(score),
            "unit_id": "UNIT.RATIO",
            "source": _SOURCE,
            "why": f"profile score below threshold {score_threshold}",
        },
        {
            "evidence_id": "EVID.ISSUE.MEASURED_VALUE",
            "value": round(mono_loss_db, 6),
            "unit_id": "UNIT.DB",
            "source": _SOURCE,
            "why": why,
        },
        {
            "evidence_id": "EVID.SEGMENT.START_S",
            "value": round(max(0.0, start_s), 6),
            "unit_id": "UNIT.S",
            "source": _SOURCE,
            "where": {
                "start_s": round(max(0.0, start_s), 6),
                "end_s": round(max(0.0, end_s), 6),
            },
            "why": "start of worst mono-loss segment",
        },
        {
            "evidence_id": "EVID.SEGMENT.END_S",
            "value": round(max(0.0, end_s), 6),
            "unit_id": "UNIT.S",
            "source": _SOURCE,
            "where": {
                "start_s": round(max(0.0, start_s), 6),
                "end_s": round(max(0.0, end_s), 6),
            },
            "why": "end of worst mono-loss segment",
        },
    ]
    result["issues"] = [
        _issue_score_low(
            profile_id=profile_id,
            score=score,
            threshold=score_threshold,
            severity=_severity_from_score(score, score_threshold),
            evidence=evidence,
        )
    ]
    return result


def _device_metric_for_profile(profile_id: str) -> tuple[str, tuple[float, float], tuple[float, float], str]:
    if profile_id in {"TRANS.DEVICE.PHONE", "TRANS.DEVICE.SMALL_SPEAKER"}:
        return (
            "low_mid_db",
            _BANDS_HZ["low"],
            _BANDS_HZ["mid"],
            "low_vs_mid ratio exceeded profile threshold",
        )
    if profile_id == "TRANS.DEVICE.EARBUDS":
        return (
            "presence_mid_db",
            _BANDS_HZ["presence"],
            _BANDS_HZ["mid"],
            "presence_vs_mid ratio exceeded profile threshold",
        )
    return (
        "sub_mid_db",
        _BANDS_HZ["sub"],
        _BANDS_HZ["mid"],
        "sub_vs_mid ratio exceeded profile threshold",
    )


def _device_profile_result(
    *,
    profile_id: str,
    profile: dict[str, Any],
    mono_metrics: dict[str, Any],
    spectral_metrics: dict[str, float],
) -> dict[str, Any]:
    thresholds = _coerce_thresholds(profile)
    scoring = _coerce_scoring(profile)
    score_threshold = _score_threshold(profile)

    correlation = _float_value(mono_metrics.get("correlation"), 0.0)
    low_mid_db = _float_value(spectral_metrics.get("low_mid_db"), 0.0)
    presence_mid_db = _float_value(spectral_metrics.get("presence_mid_db"), 0.0)
    sub_mid_db = _float_value(spectral_metrics.get("sub_mid_db"), 0.0)
    phone_mid_db = _float_value(spectral_metrics.get("phone_mid_db"), 0.0)

    low_penalty = _weighted_penalty(low_mid_db, thresholds["max_spectral_delta_db"])
    harsh_penalty = _weighted_penalty(presence_mid_db, thresholds["max_hf_harshness_db"])
    sub_penalty = _weighted_penalty(sub_mid_db, thresholds["max_spectral_delta_db"])
    mono_penalty = _deficit_penalty(correlation, thresholds["min_mono_correlation"])
    phone_presence_penalty = _deficit_penalty(
        phone_mid_db,
        -thresholds["max_spectral_delta_db"],
    )

    if profile_id in {"TRANS.DEVICE.PHONE", "TRANS.DEVICE.SMALL_SPEAKER"}:
        profile_penalty = (
            scoring["low_end_translation"] * low_penalty
            + scoring["spectral_balance"] * low_penalty
            + scoring["vocal_clarity"] * phone_presence_penalty
            + scoring["mono_compatibility"] * mono_penalty * 0.5
        )
    elif profile_id == "TRANS.DEVICE.EARBUDS":
        profile_penalty = (
            scoring["fatigue_risk"] * harsh_penalty
            + scoring["spectral_balance"] * harsh_penalty
            + scoring["vocal_clarity"] * harsh_penalty * 0.5
            + scoring["mono_compatibility"] * mono_penalty * 0.5
        )
    else:
        profile_penalty = (
            scoring["low_end_translation"] * sub_penalty
            + scoring["spectral_balance"] * sub_penalty
            + scoring["vocal_clarity"] * low_penalty * 0.5
            + scoring["mono_compatibility"] * mono_penalty * 0.25
        )

    score = _clip_score(100.0 - (100.0 * profile_penalty))
    result: dict[str, Any] = {"profile_id": profile_id, "score": score}
    if score >= score_threshold:
        return result

    metric_name, numerator_band, denominator_band, metric_why = _device_metric_for_profile(profile_id)
    ratio_db = _float_value(spectral_metrics.get(metric_name), 0.0)
    threshold_db = (
        thresholds["max_hf_harshness_db"]
        if profile_id == "TRANS.DEVICE.EARBUDS"
        else thresholds["max_spectral_delta_db"]
    )

    evidence = [
        {
            "evidence_id": "EVID.ISSUE.SCORE",
            "value": _score_ratio(score),
            "unit_id": "UNIT.RATIO",
            "source": _SOURCE,
            "why": f"profile score below threshold {score_threshold}",
        },
        {
            "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB",
            "value": round(ratio_db, 6),
            "unit_id": "UNIT.DB",
            "source": _SOURCE,
            "where": {
                "ratio": f"{metric_name}",
                "numerator_band_hz": {
                    "low_hz": numerator_band[0],
                    "high_hz": numerator_band[1],
                },
                "denominator_band_hz": {
                    "low_hz": denominator_band[0],
                    "high_hz": denominator_band[1],
                },
            },
            "why": (
                f"{metric_why}; measured={ratio_db:.3f} dB, "
                f"threshold={threshold_db:.3f} dB"
            ),
        },
    ]
    result["issues"] = [
        _issue_score_low(
            profile_id=profile_id,
            score=score,
            threshold=score_threshold,
            severity=_severity_from_score(score, score_threshold),
            evidence=evidence,
        )
    ]
    return result


def _normalize_profile_ids(
    profile_ids: list[str],
    *,
    profiles: dict[str, Any],
) -> list[str]:
    if not isinstance(profile_ids, list):
        raise ValueError("profile_ids must be a list of profile identifiers.")
    normalized: list[str] = []
    seen: set[str] = set()
    for profile_id in profile_ids:
        if not isinstance(profile_id, str):
            continue
        token = profile_id.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    if not normalized:
        raise ValueError("At least one translation profile_id is required.")

    known_ids = sorted(profile_id for profile_id in profiles.keys() if isinstance(profile_id, str))
    known_set = set(known_ids)
    unknown = sorted(profile_id for profile_id in normalized if profile_id not in known_set)
    if unknown:
        unknown_label = ", ".join(unknown)
        known_label = ", ".join(known_ids)
        if known_label:
            raise ValueError(
                f"Unknown translation profile_id: {unknown_label}. Known profile_ids: {known_label}"
            )
        raise ValueError(
            f"Unknown translation profile_id: {unknown_label}. No translation profiles are available."
        )
    return normalized


def _translation_checks_cache_version(*, max_issues_per_profile: int) -> str:
    return f"{_TRANSLATION_CHECKS_CACHE_VERSION}.max_issues_{max_issues_per_profile}"


def _translation_result_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    profile_id = item.get("profile_id")
    profile_token = profile_id.strip() if isinstance(profile_id, str) else ""
    return (
        profile_token,
        json.dumps(item, sort_keys=True),
    )


def _order_translation_results(
    *,
    rows: list[dict[str, Any]],
    profile_ids: list[str],
) -> list[dict[str, Any]]:
    ordered_profile_ids = [item for item in profile_ids if isinstance(item, str) and item.strip()]
    seen_profile_ids: set[str] = set()
    canonical_profile_ids: list[str] = []
    for profile_id in ordered_profile_ids:
        if profile_id in seen_profile_ids:
            continue
        canonical_profile_ids.append(profile_id)
        seen_profile_ids.add(profile_id)

    by_profile: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for item in rows:
        profile_id = item.get("profile_id")
        if isinstance(profile_id, str) and profile_id not in by_profile:
            by_profile[profile_id] = dict(item)
        else:
            extras.append(dict(item))

    ordered: list[dict[str, Any]] = [
        by_profile[profile_id]
        for profile_id in canonical_profile_ids
        if profile_id in by_profile
    ]
    for profile_id, row in by_profile.items():
        if profile_id not in seen_profile_ids:
            extras.append(row)

    extras.sort(key=_translation_result_sort_key)
    return ordered + extras


def _translation_checks_cache_path(
    *,
    cache_dir: Path | None,
    cache_key_value: str,
) -> Path:
    cache_root = resolve_cache_dir(cache_dir)
    return cache_root / "translation_checks" / f"{cache_key_value}.json"


def _load_translation_checks_cache(
    *,
    cache_path: Path,
    profile_ids: list[str],
) -> list[dict[str, Any]] | None:
    if not cache_path.exists() or cache_path.is_dir():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    rows = [dict(item) for item in payload if isinstance(item, dict)]
    if len(rows) != len(payload):
        return None
    return _order_translation_results(rows=rows, profile_ids=profile_ids)


def _save_translation_checks_cache(
    *,
    cache_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    canonical_rows = [dict(item) for item in rows if isinstance(item, dict)]
    canonical_rows.sort(key=_translation_result_sort_key)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(canonical_rows, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def run_translation_checks(
    *,
    audio_path: Path,
    profiles: dict[str, Any],
    profile_ids: list[str],
    max_issues_per_profile: int = 3,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(audio_path, Path):
        raise ValueError("audio_path must be a pathlib.Path.")
    if not audio_path.exists():
        raise ValueError(f"Audio path does not exist: {audio_path}")
    if not audio_path.is_file():
        raise ValueError(f"Audio path must be a file: {audio_path}")
    if audio_path.suffix.lower() not in {".wav", ".wave"}:
        raise ValueError("Translation checks currently support WAV input only.")
    if not isinstance(profiles, dict):
        raise ValueError("profiles must be a mapping of profile_id to profile definition.")
    if (
        isinstance(max_issues_per_profile, bool)
        or not isinstance(max_issues_per_profile, int)
        or max_issues_per_profile < 0
    ):
        raise ValueError("max_issues_per_profile must be a non-negative integer.")
    if not isinstance(use_cache, bool):
        raise ValueError("use_cache must be a boolean.")
    if cache_dir is not None and not isinstance(cache_dir, Path):
        raise ValueError("cache_dir must be a pathlib.Path when provided.")

    resolved_profile_ids = _normalize_profile_ids(profile_ids, profiles=profiles)
    cache_path: Path | None = None
    if use_cache:
        cache_key_value = translation_cache_key(
            audio_path,
            resolved_profile_ids,
            _translation_checks_cache_version(
                max_issues_per_profile=max_issues_per_profile,
            ),
        )
        cache_path = _translation_checks_cache_path(
            cache_dir=cache_dir,
            cache_key_value=cache_key_value,
        )
        cached_results = _load_translation_checks_cache(
            cache_path=cache_path,
            profile_ids=resolved_profile_ids,
        )
        if isinstance(cached_results, list):
            return cached_results

    sample_rate_hz, left, right = _load_channels(audio_path)

    mono_metrics = _compute_mono_metrics(left, right, sample_rate_hz=sample_rate_hz)
    spectral_metrics = _compute_spectral_metrics(left, right, sample_rate_hz=sample_rate_hz)

    results: list[dict[str, Any]] = []
    for profile_id in resolved_profile_ids:
        profile_raw = profiles.get(profile_id)
        profile = profile_raw if isinstance(profile_raw, dict) else {}

        if profile_id == "TRANS.MONO.COLLAPSE":
            result = _mono_profile_result(
                profile_id=profile_id,
                profile=profile,
                mono_metrics=mono_metrics,
            )
        elif profile_id.startswith("TRANS.DEVICE."):
            result = _device_profile_result(
                profile_id=profile_id,
                profile=profile,
                mono_metrics=mono_metrics,
                spectral_metrics=spectral_metrics,
            )
        else:
            result = {"profile_id": profile_id, "score": 100}

        issues_raw = result.get("issues")
        if isinstance(issues_raw, list):
            issues = [item for item in issues_raw if isinstance(item, dict)]
            if max_issues_per_profile >= 0:
                issues = issues[:max_issues_per_profile]
            if issues:
                result["issues"] = issues
            elif "issues" in result:
                result.pop("issues", None)
        results.append(result)

    if use_cache and cache_path is not None:
        _save_translation_checks_cache(
            cache_path=cache_path,
            rows=results,
        )
    return results
