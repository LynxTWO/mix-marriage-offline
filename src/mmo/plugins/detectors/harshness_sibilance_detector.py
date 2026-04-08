"""Harshness and sibilance detectors — shared FFT band analysis.

Harshness:  2–5 kHz upper-mid fatigue zone  → ISSUE.SPECTRAL.HARSHNESS
Sibilance: 5–10 kHz sibilant zone           → ISSUE.SPECTRAL.SIBILANCE

Same windowed-FFT approach as the mud detector: accumulate average power
spectrum, then compare target band energy to broadband (200 Hz–16 kHz).
The two classes share _analyse_band(); each sets its own thresholds.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.core.source_locator import resolved_stem_path
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import DetectorPlugin, Issue

_BROADBAND_LOW_HZ = 200.0
_BROADBAND_HIGH_HZ = 16_000.0
_MIN_RMS_THRESHOLD = 1e-5
_FFT_WINDOW = 4096
_EPSILON = 1e-30

# Per-band config: (low_hz, high_hz, ratio_threshold, ratio_ceiling, issue_id)
_HARSHNESS_CFG = (2_000.0, 5_000.0, 0.26, 0.50, "ISSUE.SPECTRAL.HARSHNESS")
_SIBILANCE_CFG = (5_000.0, 10_000.0, 0.22, 0.45, "ISSUE.SPECTRAL.SIBILANCE")


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _stem_path(stem: Dict[str, Any]) -> Optional[Path]:
    path = resolved_stem_path(stem)
    if path is not None:
        return path
    raw = stem.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    return None


def _band_energy(power_spectrum: Any, freqs: Any, low_hz: float, high_hz: float) -> float:
    import numpy as np  # noqa: PLC0415
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return float(np.sum(power_spectrum[mask]))


def _analyse_band(
    path: Path,
    band_low_hz: float,
    band_high_hz: float,
) -> Optional[Dict[str, Any]]:
    """Return {ratio, band_db, rms, sample_rate_hz} or None."""
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return None

    try:
        meta = read_wav_metadata(path)
    except Exception:
        return None

    channels = meta.get("channels")
    sample_rate_hz = meta.get("sample_rate_hz")
    if not isinstance(channels, int) or channels < 1:
        return None
    if not isinstance(sample_rate_hz, int) or sample_rate_hz < 8000:
        return None
    # Need Nyquist above band ceiling
    if sample_rate_hz / 2.0 < band_high_hz * 0.9:
        return None

    accumulated_power = np.zeros(_FFT_WINDOW // 2 + 1, dtype=np.float64)
    window_count = 0
    pending: list[float] = []
    sum_sq = 0.0
    total_samples = 0

    try:
        for chunk in iter_wav_float64_samples(path, error_context="harshness/sibilance detection"):
            pending.extend(chunk)
            total_samples += len(chunk) // channels
            needed = _FFT_WINDOW * channels
            while len(pending) >= needed:
                block = pending[:needed]
                pending = pending[needed:]
                arr = np.array(block, dtype=np.float64).reshape(-1, channels)
                mono = arr.mean(axis=1)
                sum_sq += float(np.sum(mono ** 2))
                spectrum = np.abs(np.fft.rfft(mono, n=_FFT_WINDOW)) ** 2
                accumulated_power += spectrum
                window_count += 1
    except Exception:
        return None

    if window_count == 0 or total_samples == 0:
        return None

    rms = math.sqrt(sum_sq / max(total_samples, 1))
    if rms < _MIN_RMS_THRESHOLD:
        return None

    avg_power = accumulated_power / window_count
    freqs = np.fft.rfftfreq(_FFT_WINDOW, d=1.0 / sample_rate_hz)

    broadband = _band_energy(avg_power, freqs, _BROADBAND_LOW_HZ, _BROADBAND_HIGH_HZ)
    if broadband <= _EPSILON:
        return None

    band_energy = _band_energy(avg_power, freqs, band_low_hz, band_high_hz)
    ratio = band_energy / broadband
    band_db = (
        10.0 * math.log10(max(band_energy, _EPSILON))
        - 10.0 * math.log10(broadband)
    )
    return {"ratio": ratio, "band_db": band_db, "rms": rms, "sample_rate_hz": sample_rate_hz}


def _build_issue(
    stem: Dict[str, Any],
    analysis: Dict[str, Any],
    issue_id: str,
    band_low_hz: float,
    band_high_hz: float,
    ratio_threshold: float,
    ratio_ceiling: float,
) -> Issue:
    ratio = analysis["ratio"]
    band_db = analysis["band_db"]

    t = min(1.0, max(0.0, (ratio - ratio_threshold) / (ratio_ceiling - ratio_threshold)))
    severity = int(round(30.0 + t * 40.0))

    rms_conf = min(1.0, analysis["rms"] / 0.01)
    ratio_margin = (ratio - ratio_threshold) / ratio_threshold
    confidence = round(min(0.92, 0.52 + 0.3 * min(1.0, ratio_margin) + 0.15 * rms_conf), 3)

    stem_id = stem.get("stem_id")
    target: Dict[str, Any] = {"scope": "stem"}
    if isinstance(stem_id, str) and stem_id:
        target["stem_id"] = stem_id

    evidence: List[Dict[str, Any]] = []
    file_path = _coerce_str(stem.get("file_path")).strip()
    if file_path:
        evidence.append({"evidence_id": "EVID.FILE.PATH", "value": file_path})
    evidence.append({
        "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO",
        "value": round(ratio, 4),
        "unit_id": "UNIT.RATIO",
        "where": {"freq_range_hz": {"low_hz": band_low_hz, "high_hz": band_high_hz}},
    })
    evidence.append({
        "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB",
        "value": round(band_db, 2),
        "unit_id": "UNIT.DB",
        "where": {"freq_range_hz": {"low_hz": band_low_hz, "high_hz": band_high_hz}},
    })

    return {
        "issue_id": issue_id,
        "severity": severity,
        "confidence": confidence,
        "target": target,
        "evidence": evidence,
    }


def _detect_band(
    session: Dict[str, Any],
    band_low_hz: float,
    band_high_hz: float,
    ratio_threshold: float,
    ratio_ceiling: float,
    issue_id: str,
) -> List[Issue]:
    issues: List[Issue] = []
    for stem in session.get("stems", []):
        if not isinstance(stem, dict):
            continue
        path = _stem_path(stem)
        if path is None or path.suffix.lower() not in {".wav", ".wave"}:
            continue
        analysis = _analyse_band(path, band_low_hz, band_high_hz)
        if analysis is None:
            continue
        if analysis["ratio"] >= ratio_threshold:
            issues.append(_build_issue(stem, analysis, issue_id, band_low_hz, band_high_hz, ratio_threshold, ratio_ceiling))
    return issues


class HarshnessDetector(DetectorPlugin):
    """Detect upper-mid harshness (2–5 kHz)."""

    plugin_id = "PLUGIN.DETECTOR.HARSHNESS"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        low, high, thresh, ceil, issue_id = _HARSHNESS_CFG
        return _detect_band(session, low, high, thresh, ceil, issue_id)


class SibilanceDetector(DetectorPlugin):
    """Detect sibilant energy excess (5–10 kHz)."""

    plugin_id = "PLUGIN.DETECTOR.SIBILANCE"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        low, high, thresh, ceil, issue_id = _SIBILANCE_CFG
        return _detect_band(session, low, high, thresh, ceil, issue_id)
