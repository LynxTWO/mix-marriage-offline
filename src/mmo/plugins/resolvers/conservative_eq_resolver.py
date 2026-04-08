"""Conservative EQ resolver: maps spectral issues to low-risk EQ actions.

Maps:
  ISSUE.SPECTRAL.MUD       → ACTION.EQ.BELL_CUT  @ ~300 Hz, -2.5 dB, Q 0.7
  ISSUE.SPECTRAL.RESONANCE → ACTION.EQ.NOTCH_CUT @ detected freq, -6 dB, Q 4.0

Rules:
  - Only emits low-risk, non-approval-required recommendations.
  - Cut depth is capped at _MAX_BELL_CUT_DB and _MAX_NOTCH_CUT_DB.
  - One recommendation per (stem_id, issue_id) pair — no duplicates.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

# EQ cut limits (negative dB)
_MAX_BELL_CUT_DB = -4.0     # mud bell cut max depth
_MAX_NOTCH_CUT_DB = -8.0    # resonance notch cut max depth

# Default EQ params for mud
_MUD_FREQ_HZ = 300.0
_MUD_GAIN_DB = -2.5
_MUD_Q = 0.7

# Default EQ params for resonance notch
_RESONANCE_GAIN_DB = -6.0
_RESONANCE_Q = 4.0

# Min/max freq for notch suggestions (outside this range, skip)
_NOTCH_MIN_HZ = 60.0
_NOTCH_MAX_HZ = 14_000.0


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


def _centroid_from_issue(issue: Dict[str, Any]) -> Optional[float]:
    evidence = issue.get("evidence")
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") == "EVID.SPECTRAL.CENTROID_HZ":
            return _coerce_float(entry.get("value"))
    return None


def _make_recommendation_id(prefix: str, stem_id: str, action_id: str) -> str:
    # Deterministic: use stem_id + action_id hash; uuid5 gives a stable UUID
    name = f"{prefix}:{stem_id}:{action_id}"
    return f"REC.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


def _mud_recommendation(issue: Dict[str, Any]) -> Optional[Recommendation]:
    stem_id = _stem_id_from_issue(issue)
    if stem_id is None:
        return None

    gain_db = max(_MAX_BELL_CUT_DB, _MUD_GAIN_DB)
    action_id = "ACTION.EQ.BELL_CUT"
    rec_id = _make_recommendation_id("MUD", stem_id, action_id)

    return {
        "recommendation_id": rec_id,
        "issue_id": _coerce_str(issue.get("issue_id")),
        "action_id": action_id,
        "impact": "moderate",
        "risk": "low",
        "requires_approval": False,
        "scope": {"scope": "stem", "stem_id": stem_id},
        "params": [
            {"param_id": "PARAM.EQ.FREQ_HZ", "value": _MUD_FREQ_HZ},
            {"param_id": "PARAM.EQ.Q", "value": _MUD_Q},
            {"param_id": "PARAM.EQ.GAIN_DB", "value": gain_db},
        ],
        "notes": (
            f"Conservative mud cut at {_MUD_FREQ_HZ:.0f} Hz ({gain_db:+.1f} dB, Q {_MUD_Q}). "
            "Audition before committing."
        ),
        "evidence": issue.get("evidence") or [],
    }


def _resonance_recommendation(issue: Dict[str, Any]) -> Optional[Recommendation]:
    stem_id = _stem_id_from_issue(issue)
    if stem_id is None:
        return None

    freq_hz = _centroid_from_issue(issue)
    if freq_hz is None or not (_NOTCH_MIN_HZ <= freq_hz <= _NOTCH_MAX_HZ):
        return None

    gain_db = max(_MAX_NOTCH_CUT_DB, _RESONANCE_GAIN_DB)
    action_id = "ACTION.EQ.NOTCH_CUT"
    rec_id = _make_recommendation_id("RESONANCE", stem_id, f"{action_id}:{freq_hz:.1f}")

    return {
        "recommendation_id": rec_id,
        "issue_id": _coerce_str(issue.get("issue_id")),
        "action_id": action_id,
        "impact": "moderate",
        "risk": "low",
        "requires_approval": False,
        "scope": {"scope": "stem", "stem_id": stem_id},
        "params": [
            {"param_id": "PARAM.EQ.FREQ_HZ", "value": round(freq_hz, 1)},
            {"param_id": "PARAM.EQ.Q", "value": _RESONANCE_Q},
            {"param_id": "PARAM.EQ.GAIN_DB", "value": gain_db},
        ],
        "notes": (
            f"Narrow notch at {freq_hz:.1f} Hz ({gain_db:+.1f} dB, Q {_RESONANCE_Q}). "
            "Verify on bypass before committing."
        ),
        "evidence": issue.get("evidence") or [],
    }


class ConservativeEqResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.CONSERVATIVE_EQ"

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        # Deduplicate: one mud rec per stem, one notch per (stem, freq)
        mud_stems_seen: set[str] = set()

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = _coerce_str(issue.get("issue_id"))

            if issue_id == "ISSUE.SPECTRAL.MUD":
                stem_id = _stem_id_from_issue(issue)
                if stem_id is None or stem_id in mud_stems_seen:
                    continue
                rec = _mud_recommendation(issue)
                if rec is not None:
                    mud_stems_seen.add(stem_id)
                    recommendations.append(rec)

            elif issue_id == "ISSUE.SPECTRAL.RESONANCE":
                rec = _resonance_recommendation(issue)
                if rec is not None:
                    recommendations.append(rec)

        return recommendations
