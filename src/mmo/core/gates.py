from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


Context = str
GateResult = Dict[str, Any]


def load_gates_policy(policy_path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load gate policies.")
    with policy_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Gates policy must be a mapping: {policy_path}")
    gates = data.get("gates")
    if not isinstance(gates, dict):
        raise ValueError(f"Gates policy missing gates mapping: {policy_path}")
    return gates


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _iter_params(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = rec.get("params")
    if isinstance(params, list):
        return [param for param in params if isinstance(param, dict)]
    return []


def _contexts_from_policy(gates: Dict[str, Any]) -> List[Context]:
    meta = gates.get("_meta")
    if isinstance(meta, dict):
        contexts = meta.get("contexts")
        if isinstance(contexts, list) and all(isinstance(c, str) for c in contexts):
            return list(contexts)
    return ["suggest", "auto_apply", "render"]


def _resolve_registry_path(policy_path: Path, registry_value: str) -> Path:
    candidate = policy_path.parent / registry_value
    if candidate.exists():
        return candidate
    candidate = policy_path.parent.parent / registry_value
    return candidate


def _load_downmix_policy_ids(policy_path: Path, registry_value: str) -> set[str]:
    registry_path = _resolve_registry_path(policy_path, registry_value)
    if yaml is None:
        raise RuntimeError("PyYAML is required to load downmix policies.")
    with registry_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        return set()
    downmix = data.get("downmix")
    if not isinstance(downmix, dict):
        return set()
    policies = downmix.get("policies")
    if not isinstance(policies, dict):
        return set()
    return {str(policy_id) for policy_id in policies.keys() if policy_id}


def _evaluate_requires_approval(
    rec: Dict[str, Any],
    gate_id: str,
    gate: Dict[str, Any],
    contexts: Sequence[Context],
    approvals: set[str] | None,
) -> List[GateResult]:
    requires_approval = bool(rec.get("requires_approval"))
    if not requires_approval:
        return []
    rec_id = _coerce_str(rec.get("recommendation_id"))
    if approvals is not None and rec_id and rec_id in approvals:
        return []
    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for context in contexts:
        if context == "suggest":
            continue
        results.append(
            {
                "gate_id": gate_id,
                "context": context,
                "outcome": "reject",
                "reason_id": reason_id,
                "details": {"requires_approval": True},
            }
        )
    return results


def _limit_values_for_gate(
    limits: Dict[str, Any],
    *,
    use_abs: bool,
) -> Tuple[float | None, float | None]:
    if use_abs:
        auto_apply_key = "auto_apply_abs_max"
        hard_key = "hard_abs_max"
    else:
        auto_apply_key = "auto_apply_max"
        hard_key = "hard_max"
    auto_apply = limits.get(auto_apply_key, {})
    hard = limits.get(hard_key, {})
    auto_apply_value = _coerce_number(auto_apply.get("value")) if isinstance(auto_apply, dict) else None
    hard_value = _coerce_number(hard.get("value")) if isinstance(hard, dict) else None
    return auto_apply_value, hard_value


def _evaluate_param_limits(
    rec: Dict[str, Any],
    gate_id: str,
    gate: Dict[str, Any],
    contexts: Sequence[Context],
) -> List[GateResult]:
    applies_to_params = gate.get("applies_to_params")
    if not isinstance(applies_to_params, list):
        return []
    applies = {param_id for param_id in applies_to_params if isinstance(param_id, str)}
    if not applies:
        return []
    limits = gate.get("limits")
    if not isinstance(limits, dict):
        return []

    use_abs = any(key.endswith("_abs_max") for key in limits.keys())
    auto_apply_limit, hard_limit = _limit_values_for_gate(limits, use_abs=use_abs)
    if auto_apply_limit is None and hard_limit is None:
        return []

    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for param in _iter_params(rec):
        param_id = _coerce_str(param.get("param_id"))
        if not param_id or param_id not in applies:
            continue
        value = _coerce_number(param.get("value"))
        if value is None:
            continue
        value_comp = abs(value) if use_abs else value
        limit_kind = None
        outcome = None
        limit_value = None
        if hard_limit is not None and value_comp > hard_limit:
            outcome = "reject"
            limit_value = hard_limit
            limit_kind = "hard_abs_max" if use_abs else "hard_max"
        elif auto_apply_limit is not None and value_comp > auto_apply_limit:
            outcome = "suggest_only"
            limit_value = auto_apply_limit
            limit_kind = "auto_apply_abs_max" if use_abs else "auto_apply_max"

        if outcome is None:
            continue

        for context in contexts:
            if outcome == "suggest_only" and context == "suggest":
                continue
            results.append(
                {
                    "gate_id": gate_id,
                    "context": context,
                    "outcome": outcome,
                    "reason_id": reason_id,
                    "details": {
                        "param_id": param_id,
                        "value": value,
                        "limit": limit_value,
                        "limit_kind": limit_kind,
                    },
                }
            )
    return results


def _evaluate_count_limit(
    rec: Dict[str, Any],
    gate_id: str,
    gate: Dict[str, Any],
    contexts: Sequence[Context],
) -> List[GateResult]:
    prefixes = gate.get("applies_to_actions_prefixes")
    if not isinstance(prefixes, list):
        return []
    prefixes = [prefix for prefix in prefixes if isinstance(prefix, str)]
    if not prefixes:
        return []
    action_id = _coerce_str(rec.get("action_id")) or ""
    if not any(action_id.startswith(prefix) for prefix in prefixes):
        return []
    limits = gate.get("limits")
    if not isinstance(limits, dict):
        return []

    auto_apply_limit = limits.get("auto_apply_max")
    hard_limit = limits.get("hard_max")
    auto_apply_value = _coerce_number(auto_apply_limit.get("value")) if isinstance(auto_apply_limit, dict) else None
    hard_value = _coerce_number(hard_limit.get("value")) if isinstance(hard_limit, dict) else None
    if auto_apply_value is None and hard_value is None:
        return []

    count = sum(
        1 for param in _iter_params(rec) if param.get("param_id") == "PARAM.EQ.GAIN_DB"
    )
    outcome = None
    limit_kind = None
    limit_value = None
    if hard_value is not None and count > hard_value:
        outcome = "reject"
        limit_kind = "hard_max"
        limit_value = hard_value
    elif auto_apply_value is not None and count > auto_apply_value:
        outcome = "suggest_only"
        limit_kind = "auto_apply_max"
        limit_value = auto_apply_value

    if outcome is None:
        return []

    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for context in contexts:
        if outcome == "suggest_only" and context == "suggest":
            continue
        results.append(
            {
                "gate_id": gate_id,
                "context": context,
                "outcome": outcome,
                "reason_id": reason_id,
                "details": {
                    "param_id": "PARAM.EQ.GAIN_DB",
                    "value": count,
                    "limit": limit_value,
                    "limit_kind": limit_kind,
                },
            }
        )
    return results


def _evaluate_downmix_policy_exists(
    rec: Dict[str, Any],
    gate_id: str,
    gate: Dict[str, Any],
    contexts: Sequence[Context],
    policy_path: Path,
) -> List[GateResult]:
    params = _iter_params(rec)
    policy_param = None
    for param in params:
        if param.get("param_id") == "PARAM.DOWNMIX.POLICY_ID":
            policy_param = param
            break
    if policy_param is None:
        return []
    policy_id = _coerce_str(policy_param.get("value"))
    if not policy_id:
        return []
    config = gate.get("config")
    registry_value = None
    if isinstance(config, dict):
        registry = config.get("registry_file")
        if isinstance(registry, dict):
            registry_value = _coerce_str(registry.get("value"))
    if not registry_value:
        return []
    policy_ids = _load_downmix_policy_ids(policy_path, registry_value)
    if policy_id in policy_ids:
        return []

    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for context in contexts:
        if context == "suggest":
            continue
        results.append(
            {
                "gate_id": gate_id,
                "context": context,
                "outcome": "reject",
                "reason_id": reason_id,
                "details": {
                    "param_id": "PARAM.DOWNMIX.POLICY_ID",
                    "value": policy_id,
                    "registry_file": registry_value,
                },
            }
        )
    return results


def evaluate_recommendation_gates(
    rec: Dict[str, Any],
    policy: Dict[str, Any],
    *,
    approvals: set[str] | None = None,
    policy_path: Path | None = None,
) -> Tuple[List[GateResult], bool, bool]:
    contexts = _contexts_from_policy(policy)
    gate_results: List[GateResult] = []
    for gate_id, gate in policy.items():
        if gate_id == "_meta":
            continue
        if not isinstance(gate, dict):
            continue
        if gate.get("default_enabled") is False:
            continue

        kind = gate.get("kind")
        if gate_id == "GATE.REQUIRES_APPROVAL" or kind == "authority":
            gate_results.extend(
                _evaluate_requires_approval(rec, gate_id, gate, contexts, approvals)
            )
            continue
        if kind == "param_limit":
            gate_results.extend(_evaluate_param_limits(rec, gate_id, gate, contexts))
            continue
        if kind == "count_limit":
            gate_results.extend(_evaluate_count_limit(rec, gate_id, gate, contexts))
            continue
        if gate_id == "GATE.DOWNMIX_POLICY_EXISTS":
            if policy_path is None:
                continue
            gate_results.extend(
                _evaluate_downmix_policy_exists(rec, gate_id, gate, contexts, policy_path)
            )
            continue
        # Other gates are currently stubbed (deterministic allow)

    eligible_auto_apply = True
    eligible_render = True
    for result in gate_results:
        if result.get("context") == "auto_apply" and result.get("outcome") != "allow":
            eligible_auto_apply = False
        if result.get("context") == "render" and result.get("outcome") != "allow":
            eligible_render = False

    return gate_results, eligible_auto_apply, eligible_render


def apply_gates_to_report(
    report: Dict[str, Any],
    *,
    policy_path: Path,
    approvals: set[str] | None = None,
) -> None:
    policy = load_gates_policy(policy_path)
    recommendations = report.get("recommendations")
    if not isinstance(recommendations, list):
        return
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        gate_results, eligible_auto_apply, eligible_render = evaluate_recommendation_gates(
            rec,
            policy,
            approvals=approvals,
            policy_path=policy_path,
        )
        rec["gate_results"] = gate_results
        rec["eligible_auto_apply"] = eligible_auto_apply
        rec["eligible_render"] = eligible_render
