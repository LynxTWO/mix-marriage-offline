"""LFE channel content audit: band-limited energy, crest factor, out-of-band detection.

DoD 4.4.2 — LFE validation and musician-friendly guidance.
Requires numpy for FFT-based band analysis; gracefully skips if not available.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from mmo.dsp.channel_layout import (
    _FFMPEG_LAYOUT_KNOWN,
    positions_from_wav_mask,
)

# Default LFE band bounds (Hz)
LFE_DEFAULT_LOW_HZ: float = 20.0
LFE_DEFAULT_HIGH_HZ: float = 120.0

# Severity thresholds (informational defaults; overridden by strict mode)
_OUT_OF_BAND_THRESHOLD_DB: float = -40.0   # energy above LFE cutoff that triggers flag
_INFRASONIC_THRESHOLD_DB: float = -50.0    # energy below LFE floor that triggers flag
_PEAK_HEADROOM_CEIL_DBFS: float = -3.0     # peak above this → HEADROOM_LOW
_BAND_LEVEL_LOW_DBFS: float = -55.0        # in-band energy below this → BAND_LEVEL_LOW
_BAND_LEVEL_HIGH_DBFS: float = -6.0        # in-band energy above this → BAND_LEVEL_HIGH


def _is_lfe_token(token: str) -> bool:
    return str(token).strip().upper().startswith("LFE")


def detect_lfe_channel_indices(
    channels: int,
    channel_layout: Optional[str] = None,
    wav_channel_mask: Optional[int] = None,
) -> List[int]:
    """Return 0-based channel indices that are LFE, from layout and/or WAV mask.

    Returns empty list when LFE channels cannot be determined.
    """
    # WAV mask is authoritative when present and complete
    if wav_channel_mask is not None:
        positions = positions_from_wav_mask(wav_channel_mask)
        if len(positions) == channels:
            return [i for i, pos in enumerate(positions) if _is_lfe_token(pos)]

    # Fall back to ffprobe channel_layout string
    if channel_layout is not None:
        layout_lower = channel_layout.strip().lower()
        layout_positions = _FFMPEG_LAYOUT_KNOWN.get(layout_lower)
        if layout_positions and len(layout_positions) == channels:
            return [i for i, pos in enumerate(layout_positions) if _is_lfe_token(pos)]

    return []


def _compute_band_energy_db(
    samples: List[float],
    sample_rate_hz: int,
    low_hz: float,
    high_hz: float,
) -> float:
    """Compute mean band-limited energy in dB via FFT (requires numpy).

    Returns -inf when no energy or empty input.
    """
    import numpy as np  # noqa: WPS433

    if not samples:
        return float("-inf")

    arr = np.asarray(samples, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return float("-inf")

    fft_result = np.fft.rfft(arr)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)

    mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not np.any(mask):
        return float("-inf")

    # Mean power in band, normalised by total FFT length
    band_power = float(np.mean(np.abs(fft_result[mask]) ** 2) / n)
    if band_power <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(band_power)


def _compute_peak_dbfs(samples: List[float]) -> float:
    """Return sample peak in dBFS."""
    if not samples:
        return float("-inf")
    peak = max(abs(s) for s in samples)
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(peak)


def _compute_crest_factor_db(samples: List[float]) -> float:
    """Return crest factor in dB (peak / RMS)."""
    if not samples:
        return 0.0
    n = len(samples)
    rms = math.sqrt(sum(s * s for s in samples) / n)
    peak = max(abs(s) for s in samples)
    if rms <= 0.0 or peak <= 0.0:
        return 0.0
    return 20.0 * math.log10(peak / rms)


def _compute_true_peak_dbtp(samples: List[float], sample_rate_hz: int) -> float:
    """Return true-peak in dBTP using deterministic 4x oversampling."""
    if not samples:
        return float("-inf")
    import numpy as np  # noqa: WPS433
    from mmo.dsp.meters_truth import compute_true_peak_dbtp_float64  # noqa: WPS433

    array = np.asarray(samples, dtype=np.float64).reshape(-1, 1)
    return float(compute_true_peak_dbtp_float64(array, int(sample_rate_hz)))


def _extract_channel(
    interleaved: List[float], channels: int, channel_idx: int
) -> List[float]:
    """Extract mono samples for one channel from interleaved data."""
    if channels <= 0 or channel_idx < 0 or channel_idx >= channels:
        return []
    usable = len(interleaved) - (len(interleaved) % channels)
    return [interleaved[i * channels + channel_idx] for i in range(usable // channels)]


def audit_lfe_channel(
    lfe_samples: List[float],
    mains_samples: Optional[List[float]],
    sample_rate_hz: int,
    lfe_low_hz: float = LFE_DEFAULT_LOW_HZ,
    lfe_high_hz: float = LFE_DEFAULT_HIGH_HZ,
) -> Dict[str, Any]:
    """Run LFE content audit.  Returns a dict of audit metrics.

    Requires numpy for FFT band analysis; callers should import-guard.
    """
    nyquist = sample_rate_hz / 2.0
    effective_high = min(lfe_high_hz, nyquist - 1.0)
    effective_oob_high = min(nyquist, nyquist)  # up to nyquist

    inband_db = _compute_band_energy_db(lfe_samples, sample_rate_hz, lfe_low_hz, effective_high)
    oob_high_db = _compute_band_energy_db(
        lfe_samples, sample_rate_hz, lfe_high_hz, effective_oob_high
    )
    infrasonic_db = _compute_band_energy_db(lfe_samples, sample_rate_hz, 0.1, lfe_low_hz)
    peak_dbfs = _compute_peak_dbfs(lfe_samples)
    true_peak_dbtp = _compute_true_peak_dbtp(lfe_samples, sample_rate_hz)
    crest_db = _compute_crest_factor_db(lfe_samples)

    result: Dict[str, Any] = {
        "lfe_low_hz": lfe_low_hz,
        "lfe_high_hz": lfe_high_hz,
        "inband_energy_db": inband_db,
        "out_of_band_energy_db": oob_high_db,
        "infrasonic_energy_db": infrasonic_db,
        "peak_dbfs": peak_dbfs,
        "true_peak_dbtp": true_peak_dbtp,
        "crest_factor_db": crest_db,
        "out_of_band_high": (
            math.isfinite(oob_high_db) and oob_high_db > _OUT_OF_BAND_THRESHOLD_DB
        ),
        "infrasonic_rumble": (
            math.isfinite(infrasonic_db) and infrasonic_db > _INFRASONIC_THRESHOLD_DB
        ),
        "headroom_low": math.isfinite(peak_dbfs) and peak_dbfs > _PEAK_HEADROOM_CEIL_DBFS,
        "band_level_low": (
            not math.isfinite(inband_db) or inband_db < _BAND_LEVEL_LOW_DBFS
        ),
        "band_level_high": math.isfinite(inband_db) and inband_db > _BAND_LEVEL_HIGH_DBFS,
    }

    # LFE-to-mains ratio
    if mains_samples:
        mains_inband_db = _compute_band_energy_db(
            mains_samples, sample_rate_hz, lfe_low_hz, effective_high
        )
        result["mains_inband_energy_db"] = mains_inband_db
        if math.isfinite(inband_db) and math.isfinite(mains_inband_db):
            result["lfe_to_mains_ratio_db"] = inband_db - mains_inband_db
        else:
            result["lfe_to_mains_ratio_db"] = None
    else:
        result["mains_inband_energy_db"] = None
        result["lfe_to_mains_ratio_db"] = None

    return result


def _db_to_linear(value_db: float) -> float:
    if not math.isfinite(value_db):
        return 0.0
    return 10.0 ** (value_db / 10.0)


def _linear_to_db(value_linear: float) -> float:
    if value_linear <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(value_linear)


def classify_lfe_program_state(
    *,
    target_has_lfe: bool,
    source_has_lfe_program_content: bool,
    lfe_receipt: Optional[Dict[str, Any]] = None,
) -> str:
    """Classify LFE state for audits/reports: passthrough, derived, or empty."""
    if isinstance(lfe_receipt, dict):
        status = str(lfe_receipt.get("status") or "").strip().lower()
        if status in {"passthrough", "derived", "empty"}:
            return status

    if not target_has_lfe:
        return "not_applicable"
    if source_has_lfe_program_content:
        return "passthrough"
    return "empty"


def audit_lfe_channels(
    interleaved: List[float],
    *,
    channels: int,
    lfe_indices: List[int],
    sample_rate_hz: int,
    mains_samples: Optional[List[float]] = None,
    lfe_low_hz: float = LFE_DEFAULT_LOW_HZ,
    lfe_high_hz: float = LFE_DEFAULT_HIGH_HZ,
) -> Dict[str, Any]:
    """Audit multiple LFE channels and return per-channel rows + aggregate metrics."""
    rows: List[Dict[str, Any]] = []
    inband_linear_sum = 0.0
    out_of_band_linear_sum = 0.0
    out_of_band_any = False

    for lfe_index in sorted({int(index) for index in lfe_indices}):
        lfe_mono = _extract_channel(interleaved, channels, lfe_index)
        if not lfe_mono:
            continue
        audit = audit_lfe_channel(
            lfe_mono,
            mains_samples,
            sample_rate_hz,
            lfe_low_hz=lfe_low_hz,
            lfe_high_hz=lfe_high_hz,
        )
        inband_linear_sum += _db_to_linear(float(audit.get("inband_energy_db", float("-inf"))))
        out_of_band_linear_sum += _db_to_linear(
            float(audit.get("out_of_band_energy_db", float("-inf")))
        )
        out_of_band_any = out_of_band_any or bool(audit.get("out_of_band_high"))
        rows.append(
            {
                "channel_index": lfe_index,
                "inband_energy_db": audit.get("inband_energy_db"),
                "out_of_band_energy_db": audit.get("out_of_band_energy_db"),
                "true_peak_dbtp": audit.get("true_peak_dbtp"),
                "out_of_band_high": audit.get("out_of_band_high"),
                "audit_result": audit,
            }
        )

    return {
        "lfe_low_hz": lfe_low_hz,
        "lfe_high_hz": lfe_high_hz,
        "rows": rows,
        "summed_lfe_inband_energy_db": _linear_to_db(inband_linear_sum),
        "summed_lfe_out_of_band_energy_db": _linear_to_db(out_of_band_linear_sum),
        "out_of_band_high_any": out_of_band_any,
    }


def _safe_db(value: float, fallback: float = -200.0) -> float:
    return round(value, 2) if math.isfinite(value) else fallback


def build_lfe_audit_issues(
    stem_id: str,
    channel_index: int,
    audit_result: Dict[str, Any],
    *,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """Generate ISSUE.LFE.* issues from the audit_result dict.

    Uses DoD 4.4.2 issue IDs.  Never auto-applies filters; always recommends
    with explicit approval required.
    """
    issues: List[Dict[str, Any]] = []
    target: Dict[str, Any] = {
        "scope": "stem",
        "stem_id": stem_id,
        "channel_index": channel_index,
    }
    low_hz = audit_result.get("lfe_low_hz", LFE_DEFAULT_LOW_HZ)
    high_hz = audit_result.get("lfe_high_hz", LFE_DEFAULT_HIGH_HZ)

    def _ch_evidence() -> Dict[str, Any]:
        return {
            "evidence_id": "EVID.LFE.CHANNEL_INDEX",
            "value": channel_index,
            "unit_id": "UNIT.NONE",
        }

    # --- Out-of-band high ---
    if audit_result.get("out_of_band_high"):
        oob_db = audit_result.get("out_of_band_energy_db", float("-inf"))
        issues.append(
            {
                "issue_id": "ISSUE.LFE.OUT_OF_BAND_HIGH",
                "severity": 70 if strict else 50,
                "confidence": 0.9,
                "target": target,
                "evidence": [
                    {
                        "evidence_id": "EVID.LFE.OUT_OF_BAND_DB",
                        "value": _safe_db(oob_db),
                        "unit_id": "UNIT.DB",
                    },
                    _ch_evidence(),
                ],
                "message": (
                    f"LFE channel {channel_index} has significant energy above "
                    f"{high_hz:.0f} Hz ({_safe_db(oob_db):.1f} dB). "
                    "This wastes LFE bandwidth and can cause translation issues. "
                    "A low-pass filter is recommended — requires explicit approval."
                ),
            }
        )

    # --- Infrasonic rumble ---
    if audit_result.get("infrasonic_rumble"):
        infra_db = audit_result.get("infrasonic_energy_db", float("-inf"))
        issues.append(
            {
                "issue_id": "ISSUE.LFE.INFRASONIC_RUMBLE",
                "severity": 50 if strict else 30,
                "confidence": 0.85,
                "target": target,
                "evidence": [
                    {
                        "evidence_id": "EVID.LFE.INFRASONIC_DB",
                        "value": _safe_db(infra_db),
                        "unit_id": "UNIT.DB",
                    },
                    _ch_evidence(),
                ],
                "message": (
                    f"LFE channel {channel_index} has infrasonic rumble below "
                    f"{low_hz:.0f} Hz ({_safe_db(infra_db):.1f} dB). "
                    "This inaudible content wastes headroom. "
                    "A high-pass filter is recommended — requires explicit approval."
                ),
            }
        )

    # --- Headroom low ---
    if audit_result.get("headroom_low"):
        peak_db = audit_result.get("peak_dbfs", float("-inf"))
        issues.append(
            {
                "issue_id": "ISSUE.LFE.HEADROOM_LOW",
                "severity": 70,
                "confidence": 1.0,
                "target": target,
                "evidence": [
                    {
                        "evidence_id": "EVID.LFE.PEAK_DBFS",
                        "value": _safe_db(peak_db),
                        "unit_id": "UNIT.DBFS",
                    },
                    _ch_evidence(),
                ],
                "message": (
                    f"LFE channel {channel_index} peak is {_safe_db(peak_db):.1f} dBFS. "
                    "Consumer systems apply +10 dB LFE boost; this level is likely "
                    "to clip on reproduction. Reduce LFE gain to leave at least 3 dB "
                    "headroom — requires explicit approval."
                ),
            }
        )

    # --- Band level high ---
    if audit_result.get("band_level_high"):
        inband_db = audit_result.get("inband_energy_db", float("-inf"))
        issues.append(
            {
                "issue_id": "ISSUE.LFE.BAND_LEVEL_HIGH",
                "severity": 40,
                "confidence": 0.8,
                "target": target,
                "evidence": [
                    {
                        "evidence_id": "EVID.LFE.BAND_ENERGY_DB",
                        "value": _safe_db(inband_db),
                        "unit_id": "UNIT.DB",
                    },
                    _ch_evidence(),
                ],
                "message": (
                    f"LFE channel {channel_index} in-band level is high "
                    f"({_safe_db(inband_db):.1f} dB in {low_hz:.0f}–{high_hz:.0f} Hz). "
                    "LFE may dominate the low end. Check mix balance before rendering."
                ),
            }
        )

    # --- Band level low (inform-only) ---
    if audit_result.get("band_level_low"):
        inband_db = audit_result.get("inband_energy_db", float("-inf"))
        db_str = f"{inband_db:.1f}" if math.isfinite(inband_db) else "silent"
        issues.append(
            {
                "issue_id": "ISSUE.LFE.BAND_LEVEL_LOW",
                "severity": 20,
                "confidence": 0.75,
                "target": target,
                "evidence": [
                    {
                        "evidence_id": "EVID.LFE.BAND_ENERGY_DB",
                        "value": _safe_db(inband_db),
                        "unit_id": "UNIT.DB",
                    },
                    _ch_evidence(),
                ],
                "message": (
                    f"LFE channel {channel_index} in-band energy is low or silent "
                    f"({db_str} dB in {low_hz:.0f}–{high_hz:.0f} Hz). "
                    "This may be intentional (e.g. dialogue-only mix). Inform-only."
                ),
            }
        )

    return issues
