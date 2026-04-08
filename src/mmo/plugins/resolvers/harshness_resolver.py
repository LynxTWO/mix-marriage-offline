"""Harshness resolver: maps ISSUE.SPECTRAL.HARSHNESS → ACTION.EQ.BELL_CUT.

Strategy:
  A broad bell cut centred in the harshness band (2–5 kHz).  Cut depth is
  scaled to the band_db overhang extracted from issue evidence, clamped to a
  safe range.  Cuts ≤ 2 dB are low-risk / auto-apply; deeper cuts are
  medium-risk / require approval.

One recommendation per stem (deduplication on stem_id).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

_PLUGIN_ID = "PLUGIN.RESOLVER.HARSHNESS"

# Band centre and shape
_HARSHNESS_CENTER_HZ = 3_200.0   # mid-point of the 2–5 kHz problem zone
_HARSHNESS_Q = 0.90              # broad enough to cover the whole zone

# Cut limits
_AUTO_APPLY_MAX_CUT_DB = -2.0    # deeper than this → medium risk / approval
_MEDIUM_MAX_CUT_DB = -5.0        # hard cap for this resolver
_BASE_CUT_DB = -1.5              # starting cut for a mild excess

# Risk / approval thresholds
_LOW_RISK_THRESHOLD_DB = -2.0    # cuts shallower than this are low-risk


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


def _band_energy_db_from_issue(issue: Dict[str, Any]) -> Optional[float]:
    """Extract the EVID.SPECTRAL.BAND_ENERGY_DB value from issue evidence."""
    evidence = issue.get("evidence")
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") == "EVID.SPECTRAL.BAND_ENERGY_DB":
            return _coerce_float(entry.get("value"))
    return None


def _band_ratio_from_issue(issue: Dict[str, Any]) -> Optional[float]:
    """Extract the EVID.SPECTRAL.BAND_ENERGY_RATIO value from issue evidence."""
    evidence = issue.get("evidence")
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") == "EVID.SPECTRAL.BAND_ENERGY_RATIO":
            return _coerce_float(entry.get("value"))
    return None


def _scale_cut_db(ratio: Optional[float], band_db: Optional[float]) -> float:
    """Derive a proportional cut depth from the ratio overhang.

    _HARSHNESS_CFG threshold is 0.26, ceiling 0.50.  We map the ratio into a
    cut range of [_BASE_CUT_DB .. _MEDIUM_MAX_CUT_DB].
    """
    _RATIO_THRESH = 0.26
    _RATIO_CEIL = 0.50
    if ratio is not None and ratio > _RATIO_THRESH:
        t = min(1.0, (ratio - _RATIO_THRESH) / (_RATIO_CEIL - _RATIO_THRESH))
        raw = _BASE_CUT_DB + (_MEDIUM_MAX_CUT_DB - _BASE_CUT_DB) * t
        return max(_MEDIUM_MAX_CUT_DB, min(_BASE_CUT_DB, raw))
    # Fall back to band_db-based estimate
    if band_db is not None and band_db > -6.0:
        # Modest cut proportional to how high above floor the band sits
        overhang = min(6.0, max(0.0, band_db + 6.0))
        raw = _BASE_CUT_DB - overhang * 0.4
        return max(_MEDIUM_MAX_CUT_DB, min(_BASE_CUT_DB, raw))
    return _BASE_CUT_DB


def _make_rec_id(stem_id: str) -> str:
    name = f"HARSHNESS:{stem_id}:ACTION.EQ.BELL_CUT:{_HARSHNESS_CENTER_HZ}"
    return f"REC.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


def _harshness_recommendation(issue: Dict[str, Any]) -> Optional[Recommendation]:
    stem_id = _stem_id_from_issue(issue)
    if stem_id is None:
        return None

    ratio = _band_ratio_from_issue(issue)
    band_db = _band_energy_db_from_issue(issue)
    cut_db = _scale_cut_db(ratio, band_db)

    # Risk and approval based on depth
    if cut_db >= _LOW_RISK_THRESHOLD_DB:
        risk = "low"
        requires_approval = False
    else:
        risk = "medium"
        requires_approval = True

    rec_id = _make_rec_id(stem_id)
    ratio_str = f"{ratio:.3f}" if ratio is not None else "n/a"

    return {
        "recommendation_id": rec_id,
        "issue_id": _coerce_str(issue.get("issue_id")),
        "action_id": "ACTION.EQ.BELL_CUT",
        "impact": "moderate",
        "risk": risk,
        "requires_approval": requires_approval,
        "scope": {"scope": "stem", "stem_id": stem_id},
        "params": [
            {"param_id": "PARAM.EQ.FREQ_HZ", "value": _HARSHNESS_CENTER_HZ},
            {"param_id": "PARAM.EQ.Q", "value": _HARSHNESS_Q},
            {"param_id": "PARAM.EQ.GAIN_DB", "value": round(cut_db, 2)},
        ],
        "notes": (
            f"Harshness bell cut at {_HARSHNESS_CENTER_HZ:.0f} Hz "
            f"({cut_db:+.2f} dB, Q {_HARSHNESS_Q}). "
            f"Band/broadband ratio: {ratio_str}. "
            "Audition carefully — upper-mid cuts affect presence and bite."
        ),
        "evidence": issue.get("evidence") or [],
    }


class HarshnessResolver(ResolverPlugin):
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
            if _coerce_str(issue.get("issue_id")) != "ISSUE.SPECTRAL.HARSHNESS":
                continue
            stem_id = _stem_id_from_issue(issue)
            if stem_id is None or stem_id in seen_stems:
                continue
            rec = _harshness_recommendation(issue)
            if rec is not None:
                seen_stems.add(stem_id)
                recommendations.append(rec)

        return recommendations
