from __future__ import annotations

from typing import Any, Dict, List

from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

ISSUE_ID = "ISSUE.IMAGING.NEGATIVE_CORRELATION_PAIR"
ACTION_ID = "ACTION.DIAGNOSTIC.CHECK_POLARITY"

EVIDENCE_IDS = {
    "EVID.IMAGE.CORRELATION.FL_FR",
    "EVID.IMAGE.CORRELATION.SL_SR",
    "EVID.IMAGE.CORRELATION.BL_BR",
    "EVID.IMAGE.CORRELATION_PAIRS_LOG",
    "EVID.TRACK.CHANNELS",
    "EVID.FILE.PATH",
}

NOTES = (
    "Negative correlation in one or more channel pairs. Check routing, mic polarity, "
    "cabling, and mono compatibility. In surround stems, fix at the source or track "
    "routing rather than inverting entire stem polarity."
)


def _copy_target(target: Any) -> Dict[str, Any]:
    if isinstance(target, dict):
        copied = dict(target)
    else:
        copied = {}
    if "scope" not in copied:
        copied["scope"] = "stem"
    return copied


class PolarityCheckGuidanceResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.POLARITY_CHECK_GUIDANCE"

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        index = 1
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if issue.get("issue_id") != ISSUE_ID:
                continue

            evidence_out: List[Dict[str, Any]] = []
            evidence = issue.get("evidence")
            if isinstance(evidence, list):
                for entry in evidence:
                    if not isinstance(entry, dict):
                        continue
                    evidence_id = entry.get("evidence_id")
                    if evidence_id in EVIDENCE_IDS:
                        evidence_out.append(entry)

            recommendations.append(
                {
                    "recommendation_id": f"REC.DIAGNOSTIC.CHECK_POLARITY.{index:03d}",
                    "issue_id": ISSUE_ID,
                    "action_id": ACTION_ID,
                    "risk": "low",
                    "requires_approval": False,
                    "target": _copy_target(issue.get("target")),
                    "params": [],
                    "evidence": evidence_out,
                    "notes": NOTES,
                }
            )
            index += 1

        return recommendations
