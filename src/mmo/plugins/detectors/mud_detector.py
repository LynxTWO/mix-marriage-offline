"""Mud detector: flags low-mid energy buildup (200-500 Hz) per stem.

Approach: compute the average power spectrum over the entire file using
non-overlapping FFT windows, then compare band energy in the mud zone to
broadband (20–16 kHz).  Silent or unreadable files are silently skipped.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.core.source_locator import resolved_stem_path
from mmo.dsp.io import read_wav_metadata


def _stem_path(stem: Dict[str, Any]) -> Optional[Path]:
    """Resolve stem path: try resolved_path first, then file_path if absolute."""
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
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import DetectorPlugin, Issue

# Detection zone
_MUD_LOW_HZ = 200.0
_MUD_HIGH_HZ = 500.0
_BROADBAND_LOW_HZ = 20.0
_BROADBAND_HIGH_HZ = 16_000.0

# Threshold: fraction of broadband energy in the mud band that triggers detection
_MUD_RATIO_THRESHOLD = 0.28

# Severity: linear scale from threshold to ceiling (ceiling → severity 70)
_MUD_RATIO_CEILING = 0.55

# Minimum RMS to consider a file loud enough to analyse meaningfully
_MIN_RMS_THRESHOLD = 1e-5

# FFT window size (power of 2 for speed; 4096 @ 48 kHz ≈ 85 ms resolution)
_FFT_WINDOW = 4096

_EPSILON = 1e-30


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _band_energy(power_spectrum: Any, freqs: Any, low_hz: float, high_hz: float) -> float:
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    import numpy as np  # noqa: PLC0415 — lazy import to allow missing numpy
    return float(np.sum(power_spectrum[mask]))


def _analyse_mud(path: Path) -> Optional[Dict[str, Any]]:
    """Return mud analysis dict or None if the file cannot be analysed."""
    try:
        import numpy as np  # noqa: PLC0415 — lazy import to allow missing numpy
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

    # Accumulate power spectrum across non-overlapping windows (mono mix).
    accumulated_power = np.zeros(_FFT_WINDOW // 2 + 1, dtype=np.float64)
    window_count = 0
    pending: list[float] = []
    sum_sq = 0.0
    total_samples = 0

    try:
        for chunk in iter_wav_float64_samples(path, error_context="mud detection"):
            pending.extend(chunk)
            total_samples += len(chunk) // channels

            # Process complete windows
            needed = _FFT_WINDOW * channels
            while len(pending) >= needed:
                block = pending[:needed]
                pending = pending[needed:]

                # Mix to mono
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
    mud_energy = _band_energy(avg_power, freqs, _MUD_LOW_HZ, _MUD_HIGH_HZ)
    mud_ratio = mud_energy / broadband

    # dB of mud band vs broadband
    mud_band_db = 10.0 * math.log10(max(mud_energy, _EPSILON)) - 10.0 * math.log10(broadband)

    return {
        "mud_ratio": mud_ratio,
        "mud_band_db": mud_band_db,
        "rms": rms,
        "sample_rate_hz": sample_rate_hz,
    }


def _build_issue(stem: Dict[str, Any], analysis: Dict[str, Any]) -> Issue:
    mud_ratio = analysis["mud_ratio"]
    mud_band_db = analysis["mud_band_db"]

    # Severity: linear ramp from threshold (30) to ceiling (70)
    t = min(1.0, max(0.0, (mud_ratio - _MUD_RATIO_THRESHOLD) / (_MUD_RATIO_CEILING - _MUD_RATIO_THRESHOLD)))
    severity = int(round(30.0 + t * 40.0))

    # Confidence: higher when ratio is clearly above threshold and RMS is healthy
    rms_conf = min(1.0, analysis["rms"] / 0.01)
    ratio_margin = (mud_ratio - _MUD_RATIO_THRESHOLD) / _MUD_RATIO_THRESHOLD
    confidence = round(min(0.95, 0.55 + 0.3 * min(1.0, ratio_margin) + 0.15 * rms_conf), 3)

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
        "value": round(mud_ratio, 4),
        "unit_id": "UNIT.RATIO",
        "where": {"freq_range_hz": {"low_hz": _MUD_LOW_HZ, "high_hz": _MUD_HIGH_HZ}},
    })
    evidence.append({
        "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB",
        "value": round(mud_band_db, 2),
        "unit_id": "UNIT.DB",
        "where": {"freq_range_hz": {"low_hz": _MUD_LOW_HZ, "high_hz": _MUD_HIGH_HZ}},
    })

    return {
        "issue_id": "ISSUE.SPECTRAL.MUD",
        "severity": severity,
        "confidence": confidence,
        "target": target,
        "evidence": evidence,
    }


class MudDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.MUD"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        stems = session.get("stems", [])
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            path = _stem_path(stem)
            if path is None:
                continue
            if path.suffix.lower() not in {".wav", ".wave"}:
                continue
            analysis = _analyse_mud(path)
            if analysis is None:
                continue
            if analysis["mud_ratio"] >= _MUD_RATIO_THRESHOLD:
                issues.append(_build_issue(stem, analysis))
        return issues
