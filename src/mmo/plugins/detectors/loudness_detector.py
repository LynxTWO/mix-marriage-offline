"""Loudness detector: per-stem LUFS and true-peak safety checks.

Reads pre-computed measurements from session stems (populated during the scan
pass) and emits issues when values fall outside safety or translation targets.

Emits:
  ISSUE.SAFETY.TRUEPEAK_OVER_CEILING  — true peak exceeds the hard ceiling
  ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE — integrated LUFS outside target range
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import DetectorPlugin, Issue

_PLUGIN_ID = "PLUGIN.DETECTOR.LOUDNESS"

# Evidence IDs (already registered in ontology/evidence.yaml)
_EVID_LUFS_I = "EVID.METER.LUFS_I"
_EVID_TRUEPEAK = "EVID.METER.TRUEPEAK_DBTP"
_EVID_THRESHOLD_DBTP = "EVID.DETECTOR.THRESHOLD_DBTP"
_EVID_THRESHOLD_LUFS = "EVID.DETECTOR.THRESHOLD_LUFS"
_EVID_EXPECTED_RANGE = "EVID.ISSUE.EXPECTED_RANGE"

# Default true-peak ceiling (dBTP) — standard delivery safety ceiling
_DEFAULT_CEILING_DBTP = -1.0

# LUFS target profiles: {profile_id: (target_lufs, warn_low, warn_high)}
# warn_low/warn_high are inclusive bounds; outside that range → issue
_LUFS_PROFILES: dict[str, tuple[float, float, float]] = {
    "streaming": (-14.0, -16.0, -11.0),
    "broadcast": (-23.0, -25.0, -21.0),
    "theatrical": (-24.0, -26.0, -22.0),
    "stems": (-18.0, -35.0, -6.0),  # wide: just catch extreme outliers
}
_DEFAULT_PROFILE = "stems"


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _index_measurements(stem: Dict[str, Any]) -> Dict[str, Any]:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        return {}
    index: Dict[str, Any] = {}
    for meas in measurements:
        if not isinstance(meas, dict):
            continue
        ev_id = meas.get("evidence_id")
        if isinstance(ev_id, str) and ev_id:
            index[ev_id] = meas.get("value")
    return index


def _stable_issue_id(stem_id: str, issue_type: str) -> str:
    name = f"{_PLUGIN_ID}.{issue_type}.{stem_id}"
    return f"ISSUE.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


class LoudnessDetector(DetectorPlugin):
    plugin_id = _PLUGIN_ID

    def detect(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
    ) -> List[Issue]:
        options = session.get("detector_options") or {}
        ceiling_dbtp = _coerce_number(options.get("loudness_ceiling_dbtp")) or _DEFAULT_CEILING_DBTP
        profile_id = _coerce_str(options.get("loudness_profile_id")).strip() or _DEFAULT_PROFILE
        lufs_profile = _LUFS_PROFILES.get(profile_id, _LUFS_PROFILES[_DEFAULT_PROFILE])
        target_lufs, warn_low, warn_high = lufs_profile

        issues: List[Issue] = []
        stems: list = session.get("stems") or []

        for stem in stems:
            if not isinstance(stem, dict):
                continue
            stem_id = _coerce_str(stem.get("stem_id")).strip()
            measurements = _index_measurements(stem)

            true_peak = _coerce_number(measurements.get(_EVID_TRUEPEAK))
            lufs_i = _coerce_number(measurements.get(_EVID_LUFS_I))

            # True-peak ceiling check
            if true_peak is not None and true_peak > ceiling_dbtp:
                issues.append({
                    "issue_id": "ISSUE.SAFETY.TRUEPEAK_OVER_CEILING",
                    "target": {"stem_id": stem_id},
                    "severity": "error",
                    "summary": (
                        f"True peak {true_peak:+.2f} dBTP exceeds ceiling "
                        f"{ceiling_dbtp:+.2f} dBTP."
                    ),
                    "evidence": [
                        {
                            "evidence_id": _EVID_TRUEPEAK,
                            "value": round(true_peak, 3),
                            "unit_id": "UNIT.DBTP",
                        },
                        {
                            "evidence_id": _EVID_THRESHOLD_DBTP,
                            "value": ceiling_dbtp,
                            "unit_id": "UNIT.DBTP",
                        },
                    ],
                    "detector_id": _PLUGIN_ID,
                })

            # LUFS range check (only when measurement is available)
            if lufs_i is not None and (lufs_i < warn_low or lufs_i > warn_high):
                issues.append({
                    "issue_id": "ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE",
                    "target": {"stem_id": stem_id},
                    "severity": "warn",
                    "summary": (
                        f"Integrated loudness {lufs_i:.1f} LUFS is outside "
                        f"expected range [{warn_low:.0f}, {warn_high:.0f}] LUFS "
                        f"for profile '{profile_id}'."
                    ),
                    "evidence": [
                        {
                            "evidence_id": _EVID_LUFS_I,
                            "value": round(lufs_i, 2),
                            "unit_id": "UNIT.LUFS",
                        },
                        {
                            "evidence_id": _EVID_THRESHOLD_LUFS,
                            "value": target_lufs,
                            "unit_id": "UNIT.LUFS",
                        },
                        {
                            "evidence_id": _EVID_EXPECTED_RANGE,
                            "value": f"{warn_low:.0f} to {warn_high:.0f} LUFS",
                            "unit_id": "UNIT.LUFS",
                        },
                    ],
                    "detector_id": _PLUGIN_ID,
                })

        return issues
