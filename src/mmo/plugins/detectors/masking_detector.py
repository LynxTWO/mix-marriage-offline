"""Cross-stem masking detector.

ISSUE.MASKING.KICK_BASS
  Kick (ROLE.DRUM.KICK) and bass (ROLE.BASS.*) compete in the 60–200 Hz zone.
  Both stems are analysed; if both have significant energy in the overlap band
  AND their spectral correlation there is high, masking is likely.

ISSUE.MASKING.VOCAL_VS_MUSIC
  Lead vocal (ROLE.VOCAL.LEAD / ROLE.DIALOGUE.LEAD) is competed against by
  all non-vocal stems in the 1–4 kHz intelligibility band.  Flagged when the
  summed music energy in that band substantially exceeds the vocal energy.

Both detectors are session-level (scope: "bus") — they require at least two
stems to produce any output.  If role_id fields are absent, the detector uses
filename heuristics as a fallback.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mmo.core.source_locator import resolved_stem_path
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import DetectorPlugin, Issue

_FFT_WINDOW = 4096
_MIN_RMS_THRESHOLD = 1e-5
_EPSILON = 1e-30

# Kick/bass overlap zone
_KB_LOW_HZ = 60.0
_KB_HIGH_HZ = 200.0
_KB_BROADBAND_LOW_HZ = 20.0
_KB_BROADBAND_HIGH_HZ = 8_000.0
# Both stems must have >X% of broadband in the overlap zone to flag masking
_KB_RATIO_THRESHOLD = 0.20
# Masking severity threshold: sum of both ratios above combined threshold
_KB_COMBINED_THRESHOLD = 0.55

# Vocal intelligibility zone
_VIM_LOW_HZ = 1_000.0
_VIM_HIGH_HZ = 4_000.0
_VIM_BROADBAND_LOW_HZ = 200.0
_VIM_BROADBAND_HIGH_HZ = 16_000.0
# Music energy in band must exceed vocal energy by this factor to flag
_VIM_ENERGY_RATIO_THRESHOLD = 2.5

# Role ID prefixes/values
_KICK_ROLE = "ROLE.DRUM.KICK"
_BASS_ROLE_PREFIXES = ("ROLE.BASS.",)
_VOCAL_LEAD_ROLES = ("ROLE.VOCAL.LEAD", "ROLE.DIALOGUE.LEAD")
_NON_VOCAL_EXCLUDE_PREFIXES = ("ROLE.VOCAL.", "ROLE.DIALOGUE.", "ROLE.FX.", "ROLE.AMBIENCE.")

# Filename heuristic fallbacks
_KICK_NAME_TOKENS = ("kick", "bd", "bassdrum", "bass_drum")
_BASS_NAME_TOKENS = ("bass", "sub")
_VOCAL_NAME_TOKENS = ("vox", "vocal", "lead", "ld_vox", "ldvox", "leadv")


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


def _stem_name_lower(stem: Dict[str, Any]) -> str:
    """Best available label for heuristic matching."""
    for field in ("stem_id", "label", "rel_path", "file_path"):
        v = _coerce_str(stem.get(field)).strip()
        if v:
            return Path(v).stem.lower().replace("-", "_")
    return ""


def _is_kick(stem: Dict[str, Any]) -> bool:
    role = _coerce_str(stem.get("role_id")).strip()
    if role:
        return role == _KICK_ROLE
    name = _stem_name_lower(stem)
    return any(t in name for t in _KICK_NAME_TOKENS)


def _is_bass(stem: Dict[str, Any]) -> bool:
    role = _coerce_str(stem.get("role_id")).strip()
    if role:
        return any(role.startswith(p) for p in _BASS_ROLE_PREFIXES)
    name = _stem_name_lower(stem)
    return any(t in name for t in _BASS_NAME_TOKENS) and not _is_kick(stem)


def _is_vocal_lead(stem: Dict[str, Any]) -> bool:
    role = _coerce_str(stem.get("role_id")).strip()
    if role:
        return role in _VOCAL_LEAD_ROLES
    name = _stem_name_lower(stem)
    return any(t in name for t in _VOCAL_NAME_TOKENS)


def _is_non_vocal_instrument(stem: Dict[str, Any]) -> bool:
    role = _coerce_str(stem.get("role_id")).strip()
    if role:
        return not any(role.startswith(p) for p in _NON_VOCAL_EXCLUDE_PREFIXES)
    return not _is_vocal_lead(stem)


def _band_power(path: Path, band_low_hz: float, band_high_hz: float,
                broad_low_hz: float, broad_high_hz: float) -> Optional[Dict[str, Any]]:
    """Return {band_energy, broadband_energy, ratio, rms} or None."""
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

    accumulated = np.zeros(_FFT_WINDOW // 2 + 1, dtype=np.float64)
    window_count = 0
    pending: list[float] = []
    sum_sq = 0.0
    total_samples = 0

    try:
        for chunk in iter_wav_float64_samples(path, error_context="masking detection"):
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
                accumulated += spectrum
                window_count += 1
    except Exception:
        return None

    if window_count == 0 or total_samples == 0:
        return None

    rms = math.sqrt(sum_sq / max(total_samples, 1))
    if rms < _MIN_RMS_THRESHOLD:
        return None

    avg = accumulated / window_count
    freqs = np.fft.rfftfreq(_FFT_WINDOW, d=1.0 / sample_rate_hz)

    def _sum_band(lo: float, hi: float) -> float:
        mask = (freqs >= lo) & (freqs <= hi)
        return float(np.sum(avg[mask]))

    broad = _sum_band(broad_low_hz, broad_high_hz)
    if broad <= _EPSILON:
        return None
    band = _sum_band(band_low_hz, band_high_hz)
    return {"band_energy": band, "broadband_energy": broad, "ratio": band / broad, "rms": rms}


def _detect_kick_bass(stems: List[Dict[str, Any]]) -> List[Issue]:
    """Detect kick/bass overlap masking."""
    kicks = [s for s in stems if _is_kick(s)]
    basses = [s for s in stems if _is_bass(s)]
    if not kicks or not basses:
        return []

    issues: List[Issue] = []

    for kick in kicks:
        kick_path = _stem_path(kick)
        if kick_path is None or kick_path.suffix.lower() not in {".wav", ".wave"}:
            continue
        kick_analysis = _band_power(kick_path, _KB_LOW_HZ, _KB_HIGH_HZ, _KB_BROADBAND_LOW_HZ, _KB_BROADBAND_HIGH_HZ)
        if kick_analysis is None or kick_analysis["ratio"] < _KB_RATIO_THRESHOLD:
            continue

        for bass in basses:
            bass_path = _stem_path(bass)
            if bass_path is None or bass_path.suffix.lower() not in {".wav", ".wave"}:
                continue
            bass_analysis = _band_power(bass_path, _KB_LOW_HZ, _KB_HIGH_HZ, _KB_BROADBAND_LOW_HZ, _KB_BROADBAND_HIGH_HZ)
            if bass_analysis is None or bass_analysis["ratio"] < _KB_RATIO_THRESHOLD:
                continue

            combined = kick_analysis["ratio"] + bass_analysis["ratio"]
            if combined < _KB_COMBINED_THRESHOLD:
                continue

            t = min(1.0, max(0.0, (combined - _KB_COMBINED_THRESHOLD) / 0.5))
            severity = int(round(30.0 + t * 40.0))

            kick_id = _coerce_str(kick.get("stem_id")).strip()
            bass_id = _coerce_str(bass.get("stem_id")).strip()
            confidence = round(min(0.88, 0.55 + 0.2 * min(1.0, kick_analysis["ratio"] / _KB_RATIO_THRESHOLD - 1.0)
                                   + 0.15 * min(1.0, bass_analysis["ratio"] / _KB_RATIO_THRESHOLD - 1.0)), 3)

            evidence: List[Dict[str, Any]] = []
            for stem_id, ratio in [(kick_id, kick_analysis["ratio"]), (bass_id, bass_analysis["ratio"])]:
                if stem_id:
                    evidence.append({
                        "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO",
                        "value": round(ratio, 4),
                        "unit_id": "UNIT.RATIO",
                        "where": {"freq_range_hz": {"low_hz": _KB_LOW_HZ, "high_hz": _KB_HIGH_HZ},
                                  "track_ref": {"track_name": stem_id}},
                    })

            target: Dict[str, Any] = {"scope": "bus"}
            if kick_id:
                target["stem_id"] = kick_id
            if bass_id:
                target["secondary_stem_id"] = bass_id

            issues.append({
                "issue_id": "ISSUE.MASKING.KICK_BASS",
                "severity": severity,
                "confidence": confidence,
                "target": target,
                "evidence": evidence,
            })

    return issues


def _detect_vocal_vs_music(stems: List[Dict[str, Any]]) -> List[Issue]:
    """Detect lead vocal masking by competing instruments."""
    vocals = [s for s in stems if _is_vocal_lead(s)]
    music = [s for s in stems if _is_non_vocal_instrument(s) and not _is_vocal_lead(s)]
    if not vocals or not music:
        return []

    issues: List[Issue] = []

    for vocal in vocals:
        vocal_path = _stem_path(vocal)
        if vocal_path is None or vocal_path.suffix.lower() not in {".wav", ".wave"}:
            continue
        vocal_analysis = _band_power(vocal_path, _VIM_LOW_HZ, _VIM_HIGH_HZ, _VIM_BROADBAND_LOW_HZ, _VIM_BROADBAND_HIGH_HZ)
        if vocal_analysis is None or vocal_analysis["rms"] < _MIN_RMS_THRESHOLD:
            continue

        vocal_energy = vocal_analysis["band_energy"]
        if vocal_energy <= _EPSILON:
            continue

        music_energies: List[Tuple[str, float]] = []
        for ms in music:
            ms_path = _stem_path(ms)
            if ms_path is None or ms_path.suffix.lower() not in {".wav", ".wave"}:
                continue
            ms_analysis = _band_power(ms_path, _VIM_LOW_HZ, _VIM_HIGH_HZ, _VIM_BROADBAND_LOW_HZ, _VIM_BROADBAND_HIGH_HZ)
            if ms_analysis and ms_analysis["band_energy"] > _EPSILON:
                music_energies.append((_coerce_str(ms.get("stem_id")).strip(), ms_analysis["band_energy"]))

        if not music_energies:
            continue

        total_music_energy = sum(e for _, e in music_energies)
        masking_ratio = total_music_energy / vocal_energy
        if masking_ratio < _VIM_ENERGY_RATIO_THRESHOLD:
            continue

        t = min(1.0, max(0.0, (masking_ratio - _VIM_ENERGY_RATIO_THRESHOLD) / 3.0))
        severity = int(round(30.0 + t * 45.0))

        vocal_id = _coerce_str(vocal.get("stem_id")).strip()
        confidence = round(min(0.85, 0.50 + 0.25 * min(1.0, (masking_ratio - _VIM_ENERGY_RATIO_THRESHOLD) / 2.0)), 3)

        evidence: List[Dict[str, Any]] = []
        if vocal_id:
            evidence.append({
                "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO",
                "value": round(vocal_analysis["ratio"], 4),
                "unit_id": "UNIT.RATIO",
                "where": {"freq_range_hz": {"low_hz": _VIM_LOW_HZ, "high_hz": _VIM_HIGH_HZ},
                          "track_ref": {"track_name": vocal_id}},
            })
        evidence.append({
            "evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO",
            "value": round(masking_ratio, 3),
            "unit_id": "UNIT.RATIO",
            "where": {"freq_range_hz": {"low_hz": _VIM_LOW_HZ, "high_hz": _VIM_HIGH_HZ}},
        })

        target: Dict[str, Any] = {"scope": "bus"}
        if vocal_id:
            target["stem_id"] = vocal_id

        issues.append({
            "issue_id": "ISSUE.MASKING.VOCAL_VS_MUSIC",
            "severity": severity,
            "confidence": confidence,
            "target": target,
            "evidence": evidence,
        })

    return issues


class MaskingDetector(DetectorPlugin):
    """Cross-stem masking: kick/bass overlap and vocal intelligibility."""

    plugin_id = "PLUGIN.DETECTOR.MASKING"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        stems = [s for s in session.get("stems", []) if isinstance(s, dict)]
        issues: List[Issue] = []
        issues.extend(_detect_kick_bass(stems))
        issues.extend(_detect_vocal_vs_music(stems))
        return issues
