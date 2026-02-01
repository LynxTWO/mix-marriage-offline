from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

CORRELATION_EVIDENCE_ID = "EVID.IMAGE.CORRELATION"


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_correlation(evidence: Any) -> Optional[float]:
    if not isinstance(evidence, list):
        return None
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        if entry.get("evidence_id") != CORRELATION_EVIDENCE_ID:
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


class PolarityInvertResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.POLARITY_INVERT"

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
            if issue.get("issue_id") != "ISSUE.IMAGING.NEGATIVE_CORRELATION":
                continue
            target = issue.get("target") if isinstance(issue.get("target"), dict) else {}
            stem_id = target.get("stem_id")
            evidence: List[Dict[str, Any]] = []

            correlation = _extract_correlation(issue.get("evidence"))
            if correlation is not None:
                evidence.append(
                    {
                        "evidence_id": CORRELATION_EVIDENCE_ID,
                        "value": correlation,
                        "unit_id": "UNIT.CORRELATION",
                    }
                )

            recommendations.append(
                {
                    "recommendation_id": f"REC.POLARITY_INVERT.{index:03d}",
                    "issue_id": "ISSUE.IMAGING.NEGATIVE_CORRELATION",
                    "action_id": "ACTION.UTILITY.POLARITY_INVERT",
                    "risk": "medium",
                    "requires_approval": True,
                    "target": _stem_target(stem_id),
                    "params": [],
                    "evidence": evidence,
                }
            )

        return recommendations
