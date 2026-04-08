"""Sibilance resolver: maps ISSUE.SPECTRAL.SIBILANCE → ACTION.EQ.BELL_CUT.

Strategy:
  A bell cut centred in the sibilance band (5–10 kHz).  Cut depth is scaled
  to the band ratio overhang, clamped to a safe range.  Because sibilance cuts
  affect vocal air and consonant intelligibility, all recommendations are
  medium-risk and require approval — even modest cuts should be auditioned.

  NOTE: This resolver emits ACTION.EQ.BELL_CUT as a static corrective action.
  A future ACTION.DYN.DEESSER renderer would provide a more transparent
  frequency-adaptive alternative; this can be added without changing this
  resolver by adding a SibilanceDeEsserResolver alongside it.

One recommendation per stem (deduplication on stem_id).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

_PLUGIN_ID = "PLUGIN.RESOLVER.SIBILANCE"

# Band centre and shape for the sibilance zone (5–10 kHz)
_SIBILANCE_CENTER_HZ = 7_500.0   # mid-point of the 5–10 kHz sibilance zone
_SIBILANCE_Q = 1.20              # moderate Q — sibilance is spectrally broad

# Cut limits
_MIN_CUT_DB = -1.0               # lightest cut recommended
_MAX_CUT_DB = -4.5               # hardest cut this resolver will propose

# Ratio thresholds matching the detector's _SIBILANCE_CFG
_RATIO_THRESH = 0.22
_RATIO_CEIL = 0.45


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _stem_id_from_issue(issue: Dict[str, Any]) -> Optional[str]:
    target = issue.get("target")
    if not isinstance(target, dict):
        return None
    stem_id = target.get("stem_id")
    return stem_id if isinstance(stem_id, str) and stem_id else None


def _band_ratio_from_issue(issue: Dict[str, Any]) -> Optional[float]:
    evidence = issue.get("evidence")
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") == "EVID.SPECTRAL.BAND_ENERGY_RATIO":
            return _coerce_float(entry.get("value"))
    return None


def _scale_cut_db(ratio: Optional[float]) -> float:
    """Map ratio overhang to a proportional cut depth."""
    if ratio is None or ratio <= _RATIO_THRESH:
        return _MIN_CUT_DB
    t = min(1.0, (ratio - _RATIO_THRESH) / (_RATIO_CEIL - _RATIO_THRESH))
    cut = _MIN_CUT_DB + (_MAX_CUT_DB - _MIN_CUT_DB) * t
    return max(_MAX_CUT_DB, min(_MIN_CUT_DB, cut))


def _make_rec_id(stem_id: str) -> str:
    name = f"SIBILANCE:{stem_id}:ACTION.EQ.BELL_CUT:{_SIBILANCE_CENTER_HZ}"
    return f"REC.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


def _sibilance_recommendation(issue: Dict[str, Any]) -> Optional[Recommendation]:
    stem_id = _stem_id_from_issue(issue)
    if stem_id is None:
        return None

    ratio = _band_ratio_from_issue(issue)
    cut_db = _scale_cut_db(ratio)
    ratio_str = f"{ratio:.3f}" if ratio is not None else "n/a"

    rec_id = _make_rec_id(stem_id)

    return {
        "recommendation_id": rec_id,
        "issue_id": _coerce_str(issue.get("issue_id")),
        "action_id": "ACTION.EQ.BELL_CUT",
        "impact": "moderate",
        "risk": "medium",
        "requires_approval": True,
        "scope": {"scope": "stem", "stem_id": stem_id},
        "params": [
            {"param_id": "PARAM.EQ.FREQ_HZ", "value": _SIBILANCE_CENTER_HZ},
            {"param_id": "PARAM.EQ.Q", "value": _SIBILANCE_Q},
            {"param_id": "PARAM.EQ.GAIN_DB", "value": round(cut_db, 2)},
        ],
        "notes": (
            f"Sibilance bell cut at {_SIBILANCE_CENTER_HZ:.0f} Hz "
            f"({cut_db:+.2f} dB, Q {_SIBILANCE_Q}). "
            f"Band/broadband ratio: {ratio_str}. "
            "Audition carefully — high-frequency cuts affect air and clarity. "
            "A dynamic de-esser may be more transparent for vocal stems."
        ),
        "evidence": issue.get("evidence") or [],
    }


class SibilanceResolver(ResolverPlugin):
    plugin_id = _PLUGIN_ID

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        seen_stems: set[str] = set()

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if _coerce_str(issue.get("issue_id")) != "ISSUE.SPECTRAL.SIBILANCE":
                continue
            stem_id = _stem_id_from_issue(issue)
            if stem_id is None or stem_id in seen_stems:
                continue
            rec = _sibilance_recommendation(issue)
            if rec is not None:
                seen_stems.add(stem_id)
                recommendations.append(rec)

        return recommendations
