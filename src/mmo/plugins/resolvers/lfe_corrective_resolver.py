from __future__ import annotations

from typing import Any, Dict, List, Mapping

from mmo.core.lfe_corrective import append_note, explicit_lfe_stem_ids
from mmo.plugins.interfaces import Issue, Recommendation, ResolverPlugin

_BASE_NOTES = (
    "Explicit approval required. Safe-render re-runs downmix similarity, "
    "phase-risk, and loudness QA after applying, then steps down or refuses "
    "the filter if translation worsens."
)
_EXPLICIT_LFE_NOTE = (
    "Explicit LFE stem detected; MMO will not silently fold or reroute this "
    "content into mains."
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _target_copy(target: Any) -> dict[str, Any]:
    copied = dict(target) if isinstance(target, Mapping) else {}
    copied.setdefault("scope", "stem")
    copied.setdefault("speaker_id", "SPK.LFE")
    return copied


def _scope_for_target(target: Mapping[str, Any]) -> dict[str, Any]:
    stem_id = _coerce_str(target.get("stem_id")).strip()
    if stem_id:
        return {"stem_id": stem_id}
    bus_id = _coerce_str(target.get("bus_id")).strip()
    if bus_id:
        return {"bus_id": bus_id}
    return {"global": True}


def _param(param_id: str, value: Any, unit_id: str = "UNIT.NONE") -> dict[str, Any]:
    return {
        "param_id": param_id,
        "value": value,
        "unit_id": unit_id,
    }


def _delta(param_id: str, value: Any, unit: str) -> dict[str, Any]:
    return {
        "param_id": param_id,
        "from": None,
        "to": value,
        "unit": unit,
        "confidence": 0.9,
    }


def _recommendation_payload(issue_id: str) -> dict[str, Any] | None:
    if issue_id == "ISSUE.LFE.OUT_OF_BAND_HIGH":
        return {
            "filter_type": "low_pass",
            "cutoff_hz": 120.0,
            "slope_db_oct": 24.0,
            "q": 0.707,
            "gain_db": 0.0,
            "phase_mode": "minimum_phase",
        }
    if issue_id == "ISSUE.LFE.INFRASONIC_RUMBLE":
        return {
            "filter_type": "high_pass",
            "cutoff_hz": 20.0,
            "slope_db_oct": 24.0,
            "q": 0.707,
            "gain_db": 0.0,
            "phase_mode": "minimum_phase",
        }
    if issue_id == "ISSUE.LFE.MAINS_RATIO_EXCESS":
        return {
            "filter_type": "bell",
            "cutoff_hz": 60.0,
            "slope_db_oct": 12.0,
            "q": 0.707,
            "gain_db": -3.0,
            "phase_mode": "minimum_phase",
        }
    return None


class LfeCorrectiveResolver(ResolverPlugin):
    plugin_id = "PLUGIN.RESOLVER.LFE_CORRECTIVE"

    def resolve(
        self,
        session: Dict[str, Any],
        features: Dict[str, Any],
        issues: List[Issue],
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []
        explicit_lfe_ids = set(explicit_lfe_stem_ids(session))
        index = 1
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            issue_id = _coerce_str(issue.get("issue_id")).strip()
            filter_payload = _recommendation_payload(issue_id)
            if filter_payload is None:
                continue

            target = _target_copy(issue.get("target"))
            scope = _scope_for_target(target)
            notes = _BASE_NOTES
            stem_id = _coerce_str(scope.get("stem_id")).strip()
            if stem_id and stem_id in explicit_lfe_ids:
                notes = append_note(notes, _EXPLICIT_LFE_NOTE)

            params = [
                _param("PARAM.EQ.TYPE", filter_payload["filter_type"]),
                _param("PARAM.EQ.FREQ_HZ", filter_payload["cutoff_hz"], "UNIT.HZ"),
                _param(
                    "PARAM.EQ.SLOPE_DB_PER_OCT",
                    filter_payload["slope_db_oct"],
                    "UNIT.DB_PER_OCT",
                ),
                _param("PARAM.EQ.Q", filter_payload["q"], "UNIT.Q"),
                _param("PARAM.EQ.GAIN_DB", filter_payload["gain_db"], "UNIT.DB"),
                _param("PARAM.EQ.PHASE_MODE", filter_payload["phase_mode"]),
                _param("PARAM.SURROUND.SPEAKER_ID", "SPK.LFE"),
            ]
            deltas = [
                _delta("PARAM.EQ.TYPE", filter_payload["filter_type"], "UNIT.NONE"),
                _delta("PARAM.EQ.FREQ_HZ", filter_payload["cutoff_hz"], "UNIT.HZ"),
                _delta(
                    "PARAM.EQ.SLOPE_DB_PER_OCT",
                    filter_payload["slope_db_oct"],
                    "UNIT.DB_PER_OCT",
                ),
                _delta("PARAM.EQ.Q", filter_payload["q"], "UNIT.Q"),
                _delta("PARAM.EQ.GAIN_DB", filter_payload["gain_db"], "UNIT.DB"),
                _delta("PARAM.EQ.PHASE_MODE", filter_payload["phase_mode"], "UNIT.NONE"),
                _delta("PARAM.SURROUND.SPEAKER_ID", "SPK.LFE", "UNIT.NONE"),
            ]
            recommendations.append(
                {
                    "recommendation_id": f"REC.LFE.CORRECTIVE_FILTER.{index:03d}",
                    "issue_id": issue_id,
                    "action_id": "ACTION.LFE.CORRECTIVE_FILTER",
                    "impact": "high",
                    "risk": "high",
                    "requires_approval": True,
                    "target": target,
                    "scope": scope,
                    "params": params,
                    "deltas": deltas,
                    "rollback": [
                        {
                            "action": "remove_filter",
                            "details": "Remove the approved LFE corrective filter.",
                        },
                        {
                            "action": "restore_routing",
                            "details": (
                                "Restore prior LFE routing; do not silently fold or reroute "
                                "the explicit LFE program into mains."
                            ),
                        },
                    ],
                    "notes": notes,
                    "evidence": [
                        entry
                        for entry in issue.get("evidence", [])
                        if isinstance(entry, Mapping)
                    ],
                }
            )
            index += 1
        return recommendations
