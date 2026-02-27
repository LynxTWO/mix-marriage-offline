from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

PEAK_EVIDENCE_IDS = [
    "EVID.METER.PEAK_DBFS",
    "EVID.METER.SAMPLE_PEAK_DBFS",
]


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_peak_dbfs(evidence: Any) -> Optional[float]:
    if not isinstance(evidence, list):
        return None
    for evidence_id in PEAK_EVIDENCE_IDS:
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            if entry.get("evidence_id") != evidence_id:
                continue
            value = _coerce_number(entry.get("value"))
            if value is not None:
                return value
    return None


def _stem_target(stem_id: Any) -> Dict[str, Any]:
    target: Dict[str, Any] = {"scope": "stem"}
    if isinstance(stem_id, str) and stem_id:
        target["stem_id"] = stem_id
    return target


class HeadroomGainResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.HEADROOM_GAIN"

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        for index, issue in enumerate(issues, start=1):
            if not isinstance(issue, dict):
                continue
            issue_id = issue.get("issue_id")
            target = issue.get("target") if isinstance(issue.get("target"), dict) else {}
            stem_id = target.get("stem_id")

            if issue_id == "ISSUE.SAFETY.CLIPPING_SAMPLES":
                gain_db = -3.0
            elif issue_id == "ISSUE.SAFETY.INSUFFICIENT_HEADROOM":
                peak_dbfs = _extract_peak_dbfs(issue.get("evidence"))
                if peak_dbfs is None:
                    continue
                gain_db = min(0.0, -1.0 - peak_dbfs)
                gain_db = round(gain_db, 2)
                if gain_db < -12.0:
                    gain_db = -12.0
            else:
                continue

            recommendations.append(
                {
                    "recommendation_id": f"REC.HEADROOM_GAIN.{index:03d}",
                    "issue_id": issue_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "target": _stem_target(stem_id),
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": gain_db,
                            "unit_id": "UNIT.DB",
                        }
                    ],
                }
            )

        return recommendations
