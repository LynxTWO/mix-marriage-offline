"""Loudness resolver: maps loudness/peak issues to corrective actions.

ISSUE.SAFETY.TRUEPEAK_OVER_CEILING
    → ACTION.DYN.LIMITER  (ceiling=-1.0 dBTP, lookahead=5ms, release=100ms)
      risk=medium, requires_approval=False
      Rationale: static ceiling reduction is deterministic and bounded; the
      renderer enforces a hard true-peak check and rejects any output that
      would clip.

ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE
    → ACTION.MASTER.NORMALIZE_LOUDNESS  (target LUFS + ceiling)
      risk=high, requires_approval=True
      Rationale: loudness targets are taste/platform-dependent and can affect
      punch and balance; always flag for human approval.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

_PLUGIN_ID = "PLUGIN.RESOLVER.LOUDNESS"

_DEFAULT_CEILING_DBTP = -1.0
_DEFAULT_LOOKAHEAD_MS = 5.0
_DEFAULT_RELEASE_MS = 100.0


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


def _extract_evidence_value(evidence: Any, evidence_id: str) -> Optional[float]:
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") == evidence_id:
            return _coerce_number(entry.get("value"))
    return None


def _stable_rec_id(stem_id: str, issue_id: str, action_id: str) -> str:
    name = f"{_PLUGIN_ID}.{issue_id}.{action_id}.{stem_id}"
    return f"REC.{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:16].upper()}"


class LoudnessResolver(ResolverPlugin):
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
            issue_id = _coerce_str(issue.get("issue_id"))
            target = issue.get("target") if isinstance(issue.get("target"), dict) else {}
            stem_id = _coerce_str(target.get("stem_id")).strip()
            evidence = issue.get("evidence", [])

            if issue_id == "ISSUE.SAFETY.TRUEPEAK_OVER_CEILING":
                dedup_key = f"limiter:{stem_id}"
                if dedup_key in seen_stems:
                    continue
                seen_stems.add(dedup_key)

                peak_dbtp = _extract_evidence_value(evidence, "EVID.METER.TRUEPEAK_DBTP")
                ceiling_dbtp = (
                    _extract_evidence_value(evidence, "EVID.DETECTOR.THRESHOLD_DBTP")
                    or _DEFAULT_CEILING_DBTP
                )
                gain_db = ceiling_dbtp - (peak_dbtp or 0.0)

                recommendations.append({
                    "recommendation_id": _stable_rec_id(stem_id, issue_id, "ACTION.DYN.LIMITER"),
                    "issue_id": issue_id,
                    "action_id": "ACTION.DYN.LIMITER",
                    "impact": "medium",
                    "risk": "medium",
                    "requires_approval": False,
                    "scope": {"stem_id": stem_id} if stem_id else {"global": True},
                    "params": [
                        {
                            "param_id": "PARAM.LIMIT.CEILING_DBFS",
                            "value": ceiling_dbtp,
                            "unit_id": "UNIT.DBTP",
                        },
                        {
                            "param_id": "PARAM.LIMIT.LOOKAHEAD_MS",
                            "value": _DEFAULT_LOOKAHEAD_MS,
                            "unit_id": "UNIT.MS",
                        },
                        {
                            "param_id": "PARAM.LIMIT.RELEASE_MS",
                            "value": _DEFAULT_RELEASE_MS,
                            "unit_id": "UNIT.MS",
                        },
                    ],
                    "notes": [
                        f"ceiling:{ceiling_dbtp:.1f}dBTP",
                        f"peak_input:{round(peak_dbtp, 2) if peak_dbtp is not None else 'n/a'}dBTP",
                        f"gain_headroom:{round(gain_db, 2)}dB",
                    ],
                    "evidence": evidence,
                })

            elif issue_id == "ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE":
                dedup_key = f"normalize:{stem_id}"
                if dedup_key in seen_stems:
                    continue
                seen_stems.add(dedup_key)

                lufs_i = _extract_evidence_value(evidence, "EVID.METER.LUFS_I")
                target_lufs = (
                    _extract_evidence_value(evidence, "EVID.DETECTOR.THRESHOLD_LUFS")
                    or -14.0
                )

                recommendations.append({
                    "recommendation_id": _stable_rec_id(
                        stem_id, issue_id, "ACTION.MASTER.NORMALIZE_LOUDNESS"
                    ),
                    "issue_id": issue_id,
                    "action_id": "ACTION.MASTER.NORMALIZE_LOUDNESS",
                    "impact": "high",
                    "risk": "high",
                    "requires_approval": True,
                    "scope": {"stem_id": stem_id} if stem_id else {"global": True},
                    "params": [
                        {
                            "param_id": "PARAM.TARGET.LOUDNESS_LUFS_I",
                            "value": target_lufs,
                            "unit_id": "UNIT.LUFS",
                        },
                        {
                            "param_id": "PARAM.TARGET.TRUEPEAK_DBTP",
                            "value": _DEFAULT_CEILING_DBTP,
                            "unit_id": "UNIT.DBTP",
                        },
                    ],
                    "notes": [
                        f"measured_lufs:{round(lufs_i, 1) if lufs_i is not None else 'n/a'}",
                        f"target_lufs:{target_lufs:.1f}",
                        f"delta_lufs:{round(target_lufs - lufs_i, 1) if lufs_i is not None else 'n/a'}dB",
                    ],
                    "evidence": evidence,
                })

        return recommendations
