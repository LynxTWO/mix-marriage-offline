"""Resonance detector: finds narrow persistent spectral peaks per stem.

Approach: compute the average magnitude spectrum using non-overlapping FFT
windows, then locate peaks that protrude > _PEAK_PROMINENCE_DB above their
local spectral neighbourhood.  Only peaks that appear in a majority of windows
(high persistence) are reported, limiting false positives from transients.

At most _MAX_ISSUES resonances are emitted per stem, sorted by prominence.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# Frequency range to search for resonances
_SEARCH_LOW_HZ = 80.0
_SEARCH_HIGH_HZ = 12_000.0

# A peak must protrude this many dB above its neighbourhood to be flagged
_PEAK_PROMINENCE_DB = 8.0

# Neighbourhood half-width in octave fractions (~1/3 octave each side)
_NEIGHBOURHOOD_HALF_OCTAVE = 0.33

# Minimum RMS for the analysis to be meaningful
_MIN_RMS_THRESHOLD = 1e-5

# FFT window size.  Larger window → finer frequency resolution.
# 8192 @ 48 kHz → ~5.9 Hz/bin (good for sub-1 kHz resonances)
_FFT_WINDOW = 8192

# A candidate must be visible in at least this fraction of windows
_PERSISTENCE_THRESHOLD = 0.6

# Maximum resonances to report per stem
_MAX_ISSUES = 3

# Narrow band half-width reported in evidence
_EVIDENCE_HALF_WIDTH_HZ = 30.0

_EPSILON = 1e-30


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _local_floor_db(
    power_db: Any, bin_idx: int, freqs: Any, half_octave: float
) -> float:
    """Return the median dB level in the neighbourhood of bin_idx."""
    import numpy as np  # noqa: PLC0415
    center_hz = freqs[bin_idx]
    low_hz = center_hz * (2.0 ** -half_octave)
    high_hz = center_hz * (2.0 ** half_octave)
    mask = (freqs >= low_hz) & (freqs <= high_hz) & (np.arange(len(freqs)) != bin_idx)
    neighbours = power_db[mask]
    if len(neighbours) < 3:
        return float(power_db[bin_idx])
    return float(np.median(neighbours))


def _find_peaks(
    avg_power_db: Any, freqs: Any
) -> List[Tuple[int, float]]:
    """Return list of (bin_index, prominence_db) for prominent peaks."""
    import numpy as np  # noqa: PLC0415
    search_mask = (freqs >= _SEARCH_LOW_HZ) & (freqs <= _SEARCH_HIGH_HZ)
    search_indices = np.where(search_mask)[0]

    candidates: List[Tuple[int, float]] = []
    n = len(avg_power_db)
    for idx in search_indices:
        # Simple local maximum check: higher than immediate neighbours
        if idx == 0 or idx >= n - 1:
            continue
        if not (avg_power_db[idx] > avg_power_db[idx - 1] and avg_power_db[idx] > avg_power_db[idx + 1]):
            continue
        floor_db = _local_floor_db(avg_power_db, idx, freqs, _NEIGHBOURHOOD_HALF_OCTAVE)
        prominence = float(avg_power_db[idx]) - floor_db
        if prominence >= _PEAK_PROMINENCE_DB:
            candidates.append((int(idx), round(prominence, 2)))

    # Sort by prominence descending
    candidates.sort(key=lambda c: -c[1])
    # Suppress duplicates within same neighbourhood
    merged: List[Tuple[int, float]] = []
    suppressed_bins: set[int] = set()
    for idx, prominence in candidates:
        if idx in suppressed_bins:
            continue
        merged.append((idx, prominence))
        center_hz = freqs[idx]
        low_hz = center_hz * (2.0 ** -_NEIGHBOURHOOD_HALF_OCTAVE)
        high_hz = center_hz * (2.0 ** _NEIGHBOURHOOD_HALF_OCTAVE)
        for other_idx in range(len(freqs)):
            if low_hz <= freqs[other_idx] <= high_hz:
                suppressed_bins.add(other_idx)
    return merged


def _analyse_resonance(path: Path) -> Optional[Dict[str, Any]]:
    """Return resonance analysis dict or None if file cannot be analysed."""
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

    accumulated_power = np.zeros(_FFT_WINDOW // 2 + 1, dtype=np.float64)
    window_count = 0
    pending: list[float] = []
    sum_sq = 0.0
    total_samples = 0

    # Per-window peak presence tracking (for persistence check)
    # We'll do a simple approach: collect individual window peak sets
    window_peak_sets: List[set[int]] = []

    try:
        for chunk in iter_wav_float64_samples(path, error_context="resonance detection"):
            pending.extend(chunk)
            total_samples += len(chunk) // channels

            needed = _FFT_WINDOW * channels
            while len(pending) >= needed:
                block = pending[:needed]
                pending = pending[needed:]

                arr = np.array(block, dtype=np.float64).reshape(-1, channels)
                mono = arr.mean(axis=1)
                sum_sq += float(np.sum(mono ** 2))

                power = np.abs(np.fft.rfft(mono, n=_FFT_WINDOW)) ** 2
                accumulated_power += power
                window_count += 1

                # Track which bins are local maxima in this window (crude)
                power_db = 10.0 * np.log10(np.maximum(power, _EPSILON))
                local_maxima: set[int] = set()
                for i in range(1, len(power_db) - 1):
                    if power_db[i] > power_db[i - 1] and power_db[i] > power_db[i + 1]:
                        local_maxima.add(i)
                window_peak_sets.append(local_maxima)
    except Exception:
        return None

    if window_count == 0 or total_samples == 0:
        return None

    rms = math.sqrt(sum_sq / max(total_samples, 1))
    if rms < _MIN_RMS_THRESHOLD:
        return None

    avg_power = accumulated_power / window_count
    avg_power_db = 10.0 * np.log10(np.maximum(avg_power, _EPSILON))
    freqs = np.fft.rfftfreq(_FFT_WINDOW, d=1.0 / sample_rate_hz)

    candidates = _find_peaks(avg_power_db, freqs)
    if not candidates:
        return None

    # Filter by persistence: peak must be a local max in >= threshold fraction of windows
    persistent: List[Dict[str, Any]] = []
    for bin_idx, prominence in candidates:
        if window_count < 2:
            persistence = 1.0
        else:
            present_count = sum(1 for ws in window_peak_sets if bin_idx in ws)
            persistence = present_count / window_count
        if persistence >= _PERSISTENCE_THRESHOLD:
            center_hz = float(freqs[bin_idx])
            persistent.append({
                "freq_hz": center_hz,
                "prominence_db": prominence,
                "persistence": round(persistence, 3),
            })
        if len(persistent) >= _MAX_ISSUES:
            break

    if not persistent:
        return None

    return {
        "peaks": persistent,
        "rms": rms,
        "sample_rate_hz": sample_rate_hz,
    }


def _build_issue(stem: Dict[str, Any], peak: Dict[str, Any]) -> Issue:
    freq_hz = peak["freq_hz"]
    prominence_db = peak["prominence_db"]
    persistence = peak["persistence"]

    # Severity: 30 at threshold, 70 for very prominent peaks
    sev_t = min(1.0, max(0.0, (prominence_db - _PEAK_PROMINENCE_DB) / 12.0))
    severity = int(round(30.0 + sev_t * 40.0))

    confidence = round(min(0.92, 0.55 + 0.3 * persistence + 0.07 * min(1.0, (prominence_db - _PEAK_PROMINENCE_DB) / 8.0)), 3)

    stem_id = stem.get("stem_id")
    target: Dict[str, Any] = {"scope": "stem"}
    if isinstance(stem_id, str) and stem_id:
        target["stem_id"] = stem_id

    low_hz = max(20.0, freq_hz - _EVIDENCE_HALF_WIDTH_HZ)
    high_hz = freq_hz + _EVIDENCE_HALF_WIDTH_HZ

    evidence: List[Dict[str, Any]] = []
    file_path = _coerce_str(stem.get("file_path")).strip()
    if file_path:
        evidence.append({"evidence_id": "EVID.FILE.PATH", "value": file_path})
    evidence.append({
        "evidence_id": "EVID.SPECTRAL.CENTROID_HZ",
        "value": round(freq_hz, 1),
        "unit_id": "UNIT.HZ",
    })
    evidence.append({
        "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB",
        "value": round(prominence_db, 2),
        "unit_id": "UNIT.DB",
        "where": {"freq_range_hz": {"low_hz": round(low_hz, 1), "high_hz": round(high_hz, 1)}},
    })

    return {
        "issue_id": "ISSUE.SPECTRAL.RESONANCE",
        "severity": severity,
        "confidence": confidence,
        "target": target,
        "evidence": evidence,
    }


class ResonanceDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.RESONANCE"

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
            analysis = _analyse_resonance(path)
            if analysis is None:
                continue
            for peak in analysis["peaks"]:
                issues.append(_build_issue(stem, peak))
        return issues
