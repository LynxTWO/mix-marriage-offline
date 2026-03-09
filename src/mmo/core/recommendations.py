from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

IMPACT_LEVELS: tuple[str, ...] = ("low", "medium", "high")
_IMPACT_SET = set(IMPACT_LEVELS)
_APPROVAL_IMPACTS = {"medium", "high"}
_SCOPE_KEYS = ("stem_id", "bus_id", "layout_id", "global")
_SYNTHETIC_ACTION_DELTAS: dict[str, tuple[dict[str, Any], ...]] = {
    "ACTION.UTILITY.POLARITY_INVERT": (
        {
            "param_id": "PARAM.POLARITY.INVERT",
            "from": None,
            "to": True,
            "unit": "UNIT.NONE",
        },
    ),
}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = sorted(
        {
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        }
    )
    return normalized


def recommendation_impact(rec: Mapping[str, Any]) -> str:
    for key in ("impact", "risk"):
        candidate = _coerce_str(rec.get(key)).strip().lower()
        if candidate in _IMPACT_SET:
            return candidate
    if bool(rec.get("requires_approval")):
        return "medium"
    return "low"


def recommendation_requires_user_approval(rec: Mapping[str, Any]) -> bool:
    action_id = _coerce_str(rec.get("action_id")).strip()
    if action_id:
        from mmo.core.lfe_corrective import is_lfe_corrective_action_id  # noqa: WPS433

        if is_lfe_corrective_action_id(action_id):
            return True
    return bool(rec.get("requires_approval")) or recommendation_impact(rec) in _APPROVAL_IMPACTS


def _normalize_scope(raw_scope: Any) -> dict[str, Any] | None:
    if not isinstance(raw_scope, Mapping):
        return None
    for key in ("stem_id", "bus_id", "layout_id"):
        value = _coerce_str(raw_scope.get(key)).strip()
        if value:
            return {key: value}
    if raw_scope.get("global") is True:
        return {"global": True}
    return None


def normalize_recommendation_scope(rec: Mapping[str, Any]) -> dict[str, Any]:
    scope = _normalize_scope(rec.get("scope"))
    if scope is not None:
        return scope

    target = rec.get("target")
    if isinstance(target, Mapping):
        for key in ("stem_id", "bus_id", "layout_id"):
            value = _coerce_str(target.get(key)).strip()
            if value:
                return {key: value}
        target_scope = _coerce_str(target.get("scope")).strip().lower()
        if target_scope in {"global", "project", "session"}:
            return {"global": True}

    return {"global": True}


def legacy_target_from_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    stem_id = _coerce_str(scope.get("stem_id")).strip()
    if stem_id:
        return {"scope": "stem", "stem_id": stem_id}

    bus_id = _coerce_str(scope.get("bus_id")).strip()
    if bus_id:
        return {"scope": "bus", "bus_id": bus_id}

    layout_id = _coerce_str(scope.get("layout_id")).strip()
    if layout_id:
        return {"scope": "layout", "layout_id": layout_id}

    return {"scope": "session"}


def _default_evidence_ref(rec: Mapping[str, Any]) -> str | None:
    evidence = rec.get("evidence")
    if isinstance(evidence, list):
        for entry in evidence:
            if not isinstance(entry, Mapping):
                continue
            evidence_id = _coerce_str(entry.get("evidence_id")).strip()
            if evidence_id:
                return evidence_id

    issue_id = _coerce_str(rec.get("issue_id")).strip()
    if issue_id:
        return issue_id

    recommendation_id = _coerce_str(rec.get("recommendation_id")).strip()
    if recommendation_id:
        return recommendation_id

    return None


def _default_confidence(rec: Mapping[str, Any]) -> float:
    raw_confidence = rec.get("confidence")
    confidence = _coerce_float(raw_confidence)
    if confidence is not None:
        return max(0.0, min(confidence, 1.0))
    evidence = rec.get("evidence")
    if isinstance(evidence, list) and evidence:
        return 0.8
    return 1.0


def _params_by_id(rec: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    param_values: dict[str, Any] = {}
    param_units: dict[str, Any] = {}
    params = rec.get("params")
    if not isinstance(params, list):
        return param_values, param_units

    for param in params:
        if not isinstance(param, Mapping):
            continue
        param_id = _coerce_str(param.get("param_id")).strip()
        if not param_id:
            continue
        param_values[param_id] = deepcopy(param.get("value"))
        unit_id = _coerce_str(param.get("unit_id")).strip()
        if unit_id:
            param_units[param_id] = unit_id
    return param_values, param_units


def _normalize_delta(
    raw_delta: Mapping[str, Any],
    *,
    param_values: Mapping[str, Any],
    param_units: Mapping[str, Any],
    default_confidence: float,
    default_evidence_ref: str | None,
) -> dict[str, Any] | None:
    param_id = _coerce_str(raw_delta.get("param_id")).strip()
    if not param_id:
        return None

    normalized: dict[str, Any] = {
        "param_id": param_id,
        "from": deepcopy(raw_delta.get("from")) if "from" in raw_delta else None,
        "to": (
            deepcopy(raw_delta.get("to"))
            if "to" in raw_delta
            else deepcopy(param_values.get(param_id))
        ),
        "unit": (
            _coerce_str(raw_delta.get("unit")).strip()
            or _coerce_str(raw_delta.get("unit_id")).strip()
            or _coerce_str(param_units.get(param_id)).strip()
            or "UNIT.NONE"
        ),
        "confidence": default_confidence,
        "evidence_ref": default_evidence_ref,
    }

    confidence = _coerce_float(raw_delta.get("confidence"))
    if confidence is not None:
        normalized["confidence"] = max(0.0, min(confidence, 1.0))

    evidence_ref = _coerce_str(raw_delta.get("evidence_ref")).strip()
    if evidence_ref:
        normalized["evidence_ref"] = evidence_ref

    return normalized


def normalize_recommendation_deltas(rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    param_values, param_units = _params_by_id(rec)
    default_confidence = _default_confidence(rec)
    default_evidence_ref = _default_evidence_ref(rec)

    normalized: list[dict[str, Any]] = []
    raw_deltas = rec.get("deltas")
    if isinstance(raw_deltas, list):
        for raw_delta in raw_deltas:
            if not isinstance(raw_delta, Mapping):
                continue
            delta = _normalize_delta(
                raw_delta,
                param_values=param_values,
                param_units=param_units,
                default_confidence=default_confidence,
                default_evidence_ref=default_evidence_ref,
            )
            if delta is not None:
                normalized.append(delta)
        if normalized:
            return normalized

    params = rec.get("params")
    if isinstance(params, list):
        for param in params:
            if not isinstance(param, Mapping):
                continue
            param_id = _coerce_str(param.get("param_id")).strip()
            if not param_id:
                continue
            normalized.append(
                {
                    "param_id": param_id,
                    "from": None,
                    "to": deepcopy(param.get("value")),
                    "unit": _coerce_str(param.get("unit_id")).strip() or "UNIT.NONE",
                    "confidence": default_confidence,
                    "evidence_ref": default_evidence_ref,
                }
            )
        if normalized:
            return normalized

    action_id = _coerce_str(rec.get("action_id")).strip()
    for synthetic_delta in _SYNTHETIC_ACTION_DELTAS.get(action_id, ()):
        delta = _normalize_delta(
            synthetic_delta,
            param_values=param_values,
            param_units=param_units,
            default_confidence=default_confidence,
            default_evidence_ref=default_evidence_ref,
        )
        if delta is not None:
            normalized.append(delta)

    return normalized


def _scope_label(scope: Mapping[str, Any]) -> str:
    for key in ("stem_id", "bus_id", "layout_id"):
        value = _coerce_str(scope.get(key)).strip()
        if value:
            return f"{key}={value}"
    return "global"


def _normalize_rollback_entry(raw_rollback: Any) -> dict[str, str] | None:
    if not isinstance(raw_rollback, Mapping):
        return None
    action = _coerce_str(raw_rollback.get("action")).strip()
    details = _coerce_str(raw_rollback.get("details")).strip()
    if not action or not details:
        return None
    return {"action": action, "details": details}


def _default_rollback(
    *,
    action_id: str,
    scope: Mapping[str, Any],
    deltas: list[dict[str, Any]],
) -> list[dict[str, str]]:
    scope_label = _scope_label(scope)
    rollback: list[dict[str, str]] = []
    for delta in deltas:
        param_id = _coerce_str(delta.get("param_id")).strip()
        if not param_id:
            continue
        from_value = delta.get("from")
        if from_value is None:
            rollback.append(
                {
                    "action": "capture_and_restore_parameter",
                    "details": (
                        f"Capture the current value of {param_id} on {scope_label} before "
                        "applying this change, then restore it to roll back."
                    ),
                }
            )
            continue
        rollback.append(
            {
                "action": "restore_parameter",
                "details": (
                    f"Restore {param_id} on {scope_label} to "
                    f"{json.dumps(from_value, sort_keys=True)}."
                ),
            }
        )

    if rollback:
        return rollback

    return [
        {
            "action": "disable_action",
            "details": f"Disable {action_id or 'the approved action'} on {scope_label}.",
        }
    ]


def normalize_recommendation_contract(rec: dict[str, Any]) -> dict[str, Any]:
    impact = recommendation_impact(rec)
    scope = normalize_recommendation_scope(rec)
    deltas = normalize_recommendation_deltas(rec)

    rec["impact"] = impact
    rec["risk"] = impact
    rec["requires_approval"] = recommendation_requires_user_approval(rec)
    rec["scope"] = scope
    rec["deltas"] = deltas

    target = rec.get("target")
    if not isinstance(target, Mapping):
        rec["target"] = legacy_target_from_scope(scope)

    rollback: list[dict[str, str]] = []
    raw_rollback = rec.get("rollback")
    if isinstance(raw_rollback, list):
        for entry in raw_rollback:
            normalized_entry = _normalize_rollback_entry(entry)
            if normalized_entry is not None:
                rollback.append(normalized_entry)

    if recommendation_requires_user_approval(rec) and not rollback:
        rollback = _default_rollback(
            action_id=_coerce_str(rec.get("action_id")).strip(),
            scope=scope,
            deltas=deltas,
        )

    if rollback:
        rec["rollback"] = rollback

    return rec


def recommendation_gate_summary(rec: Mapping[str, Any]) -> str:
    gate_results = rec.get("gate_results")
    if not isinstance(gate_results, list):
        return ""

    selected: Mapping[str, Any] | None = None
    for preferred_context in ("render", "auto_apply", "suggest"):
        for result in gate_results:
            if not isinstance(result, Mapping):
                continue
            if _coerce_str(result.get("context")).strip().lower() != preferred_context:
                continue
            if _coerce_str(result.get("outcome")).strip().lower() == "allow":
                continue
            selected = result
            break
        if selected is not None:
            break

    if selected is None:
        return ""

    reason_id = _coerce_str(selected.get("reason_id")).strip()
    gate_id = _coerce_str(selected.get("gate_id")).strip()
    if reason_id in {
        "REASON.APPROVAL_REQUIRED",
        "REASON.SPATIAL_LOCK_OR_APPROVAL_REQUIRED",
    } and rec.get("spatial_change") is True:
        required_lock_ids = _string_list(rec.get("required_lock_ids"))
        if required_lock_ids:
            return f"{reason_id} ({gate_id}; add lock or approve)"
        return f"{reason_id} ({gate_id}; spatial change)"
    if reason_id and gate_id:
        return f"{reason_id} ({gate_id})"
    return reason_id or gate_id


def recommendation_snapshot(rec: Mapping[str, Any]) -> dict[str, Any]:
    scope = normalize_recommendation_scope(rec)
    deltas = normalize_recommendation_deltas(rec)
    snapshot: dict[str, Any] = {
        "recommendation_id": _coerce_str(rec.get("recommendation_id")).strip(),
        "action_id": _coerce_str(rec.get("action_id")).strip(),
        "impact": recommendation_impact(rec),
        "risk": recommendation_impact(rec),
        "requires_approval": recommendation_requires_user_approval(rec),
        "scope": deepcopy(scope),
        "deltas": deepcopy(deltas),
        "rollback": deepcopy(rec.get("rollback")) if isinstance(rec.get("rollback"), list) else [],
        "gate_summary": recommendation_gate_summary(rec),
    }

    issue_id = _coerce_str(rec.get("issue_id")).strip()
    if issue_id:
        snapshot["issue_id"] = issue_id

    notes = _coerce_str(rec.get("notes")).strip()
    if notes:
        snapshot["notes"] = notes

    for key in ("eligible_auto_apply", "eligible_render", "approved_by_user"):
        if isinstance(rec.get(key), bool):
            snapshot[key] = bool(rec.get(key))

    if rec.get("spatial_change") is True:
        snapshot["spatial_change"] = True
        snapshot["required_lock_ids"] = _string_list(rec.get("required_lock_ids"))

    return snapshot


__all__ = [
    "IMPACT_LEVELS",
    "legacy_target_from_scope",
    "normalize_recommendation_contract",
    "normalize_recommendation_deltas",
    "normalize_recommendation_scope",
    "recommendation_gate_summary",
    "recommendation_impact",
    "recommendation_requires_user_approval",
    "recommendation_snapshot",
]
