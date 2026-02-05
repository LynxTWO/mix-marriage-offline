from __future__ import annotations

import copy
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


def load_authority_profiles(policy_path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load authority profiles.")
    with policy_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Authority profiles policy must be a mapping: {policy_path}")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError(f"Authority profiles policy missing profiles mapping: {policy_path}")
    return profiles


def _deep_merge_profile_overrides(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged: Dict[str, Any] = {}

        for key, base_value in base.items():
            if key in override:
                merged[key] = _deep_merge_profile_overrides(base_value, override[key])
            else:
                merged[key] = copy.deepcopy(base_value)

        for key in sorted(key for key in override.keys() if key not in base):
            merged[key] = copy.deepcopy(override[key])

        return merged

    if isinstance(override, list):
        return copy.deepcopy(override)

    return copy.deepcopy(override)


def apply_profile_overrides(
    gates_policy: Dict[str, Any],
    profile_id: str,
    profiles_policy: Dict[str, Any],
) -> Dict[str, Any]:
    profile = profiles_policy.get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(f"Unknown authority profile id: {profile_id}")

    overrides = profile.get("overrides")
    if not isinstance(overrides, dict) or not overrides:
        return copy.deepcopy(gates_policy)

    gates_overrides = overrides.get("gates")
    if not isinstance(gates_overrides, dict) or not gates_overrides:
        return copy.deepcopy(gates_policy)

    return _deep_merge_profile_overrides(gates_policy, gates_overrides)


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


def _read_limit_value(limits: Dict[str, Any], limit_key: str) -> float | None:
    raw_limit = limits.get(limit_key)
    if isinstance(raw_limit, dict):
        return _coerce_number(raw_limit.get("value"))
    return _coerce_number(raw_limit)


def _resolve_param_limit(
    limits: Dict[str, Any],
    context: str,
    *,
    fallback_context: str | None = None,
) -> tuple[float | None, str | None, bool]:
    abs_key = f"{context}_abs_max"
    abs_value = _read_limit_value(limits, abs_key)
    if abs_value is not None:
        return abs_value, abs_key, True

    max_key = f"{context}_max"
    max_value = _read_limit_value(limits, max_key)
    if max_value is not None:
        return max_value, max_key, False

    if fallback_context is None:
        return None, None, False

    fallback_abs_key = f"{fallback_context}_abs_max"
    fallback_abs_value = _read_limit_value(limits, fallback_abs_key)
    if fallback_abs_value is not None:
        return fallback_abs_value, fallback_abs_key, True

    fallback_max_key = f"{fallback_context}_max"
    fallback_max_value = _read_limit_value(limits, fallback_max_key)
    if fallback_max_value is not None:
        return fallback_max_value, fallback_max_key, False

    return None, None, False


def _resolve_count_limit(
    limits: Dict[str, Any],
    context: str,
    *,
    fallback_context: str | None = None,
) -> tuple[float | None, str | None]:
    limit_key = f"{context}_max"
    limit_value = _read_limit_value(limits, limit_key)
    if limit_value is not None:
        return limit_value, limit_key

    if fallback_context is None:
        return None, None

    fallback_key = f"{fallback_context}_max"
    fallback_value = _read_limit_value(limits, fallback_key)
    if fallback_value is not None:
        return fallback_value, fallback_key

    return None, None


def _gate_result_details_for_param(
    *,
    param_id: str,
    value: float,
    limit_value: float,
    limit_kind: str,
    use_abs: bool,
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "param_id": param_id,
        "value": value,
        "limit": limit_value,
        "limit_kind": limit_kind,
        "use_abs": use_abs,
    }
    if use_abs:
        details["abs_value"] = abs(value)
    return details


def _sort_gate_results(
    gate_results: List[GateResult],
    contexts: Sequence[Context],
) -> List[GateResult]:
    context_order = {context: index for index, context in enumerate(contexts)}

    def _sort_key(result: GateResult) -> tuple[int, str, str]:
        context = _coerce_str(result.get("context")) or ""
        gate_id = _coerce_str(result.get("gate_id")) or ""
        details = result.get("details")
        param_id = ""
        if isinstance(details, dict):
            param_id = _coerce_str(details.get("param_id")) or ""
        return (context_order.get(context, len(context_order)), gate_id, param_id)

    return sorted(gate_results, key=_sort_key)


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

    hard_limit, hard_limit_kind, hard_use_abs = _resolve_param_limit(limits, "hard")
    suggest_limit, _, _ = _resolve_param_limit(limits, "suggest")
    auto_apply_limit, _, _ = _resolve_param_limit(limits, "auto_apply")
    render_limit, _, _ = _resolve_param_limit(
        limits,
        "render",
        fallback_context="auto_apply",
    )
    if (
        hard_limit is None
        and suggest_limit is None
        and auto_apply_limit is None
        and render_limit is None
    ):
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

        if (
            hard_limit is not None
            and hard_limit_kind is not None
            and (abs(value) if hard_use_abs else value) > hard_limit
        ):
            for context in contexts:
                if context not in {"suggest", "auto_apply", "render"}:
                    continue
                results.append(
                    {
                        "gate_id": gate_id,
                        "context": context,
                        "outcome": "reject",
                        "reason_id": reason_id,
                        "details": _gate_result_details_for_param(
                            param_id=param_id,
                            value=value,
                            limit_value=hard_limit,
                            limit_kind=hard_limit_kind,
                            use_abs=hard_use_abs,
                        ),
                    }
                )
            continue

        for context in contexts:
            limit_value: float | None
            limit_kind: str | None
            use_abs: bool

            if context == "suggest":
                limit_value, limit_kind, use_abs = _resolve_param_limit(limits, "suggest")
                outcome = "suggest_only"
            elif context == "auto_apply":
                limit_value, limit_kind, use_abs = _resolve_param_limit(limits, "auto_apply")
                outcome = "suggest_only"
            elif context == "render":
                limit_value, limit_kind, use_abs = _resolve_param_limit(
                    limits,
                    "render",
                    fallback_context="auto_apply",
                )
                outcome = "reject"
            else:
                continue

            if limit_value is None or limit_kind is None:
                continue

            comparison_value = abs(value) if use_abs else value
            if comparison_value <= limit_value:
                continue

            results.append(
                {
                    "gate_id": gate_id,
                    "context": context,
                    "outcome": outcome,
                    "reason_id": reason_id,
                    "details": _gate_result_details_for_param(
                        param_id=param_id,
                        value=value,
                        limit_value=limit_value,
                        limit_kind=limit_kind,
                        use_abs=use_abs,
                    ),
                }
            )

    return _sort_gate_results(results, contexts)


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

    hard_value, hard_limit_kind = _resolve_count_limit(limits, "hard")
    suggest_value, _ = _resolve_count_limit(limits, "suggest")
    auto_apply_value, _ = _resolve_count_limit(limits, "auto_apply")
    render_value, _ = _resolve_count_limit(
        limits,
        "render",
        fallback_context="auto_apply",
    )
    if (
        hard_value is None
        and suggest_value is None
        and auto_apply_value is None
        and render_value is None
    ):
        return []

    count = sum(
        1 for param in _iter_params(rec) if param.get("param_id") == "PARAM.EQ.GAIN_DB"
    )

    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    if hard_value is not None and hard_limit_kind is not None and count > hard_value:
        for context in contexts:
            if context not in {"suggest", "auto_apply", "render"}:
                continue
            results.append(
                {
                    "gate_id": gate_id,
                    "context": context,
                    "outcome": "reject",
                    "reason_id": reason_id,
                    "details": {
                        "param_id": "PARAM.EQ.GAIN_DB",
                        "value": count,
                        "limit": hard_value,
                        "limit_kind": hard_limit_kind,
                    },
                }
            )
        return _sort_gate_results(results, contexts)

    for context in contexts:
        limit_value: float | None
        limit_kind: str | None
        if context == "suggest":
            limit_value, limit_kind = _resolve_count_limit(limits, "suggest")
            outcome = "suggest_only"
        elif context == "auto_apply":
            limit_value, limit_kind = _resolve_count_limit(limits, "auto_apply")
            outcome = "suggest_only"
        elif context == "render":
            limit_value, limit_kind = _resolve_count_limit(
                limits,
                "render",
                fallback_context="auto_apply",
            )
            outcome = "reject"
        else:
            continue

        if limit_value is None or limit_kind is None or count <= limit_value:
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

    return _sort_gate_results(results, contexts)


def _evaluate_action_prefix_limit(
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
    matched_prefix = None
    for prefix in prefixes:
        if action_id.startswith(prefix):
            matched_prefix = prefix
            break
    if matched_prefix is None:
        return []

    enforcement = gate.get("enforcement")
    if not isinstance(enforcement, dict):
        return []
    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for context in contexts:
        outcome = enforcement.get(context)
        if outcome is None or outcome == "allow":
            continue
        results.append(
            {
                "gate_id": gate_id,
                "context": context,
                "outcome": outcome,
                "reason_id": reason_id,
                "details": {
                    "action_id": action_id,
                    "matched_prefix": matched_prefix,
                },
            }
        )
    return results


def _evaluate_metric_delta_limit(
    rec: Dict[str, Any],
    gate_id: str,
    gate: Dict[str, Any],
    contexts: Sequence[Context],
) -> List[GateResult]:
    applies_to_actions = gate.get("applies_to_actions")
    if isinstance(applies_to_actions, list):
        applies = {action_id for action_id in applies_to_actions if isinstance(action_id, str)}
        if applies:
            action_id = _coerce_str(rec.get("action_id"))
            if action_id is None or action_id not in applies:
                return []

    config = gate.get("config")
    if not isinstance(config, dict):
        return []

    param_config = config.get("param_id")
    if isinstance(param_config, dict):
        param_id = _coerce_str(param_config.get("value"))
    else:
        param_id = _coerce_str(param_config)
    if not param_id:
        return []

    def _read_limit(limit_key: str) -> float | None:
        limit_value = config.get(limit_key)
        if isinstance(limit_value, dict):
            return _coerce_number(limit_value.get("value"))
        return _coerce_number(limit_value)

    warn_abs_max = _read_limit("warn_abs_max")
    fail_abs_max = _read_limit("fail_abs_max")
    if warn_abs_max is None and fail_abs_max is None:
        return []

    param_value = None
    for param in _iter_params(rec):
        if param.get("param_id") != param_id:
            continue
        param_value = _coerce_number(param.get("value"))
        break
    if param_value is None:
        return []

    abs_value = abs(param_value)
    level = None
    if fail_abs_max is not None and abs_value > fail_abs_max:
        level = "fail"
    elif warn_abs_max is not None and abs_value > warn_abs_max:
        level = "warn"

    if level is None:
        return []

    enforcement = gate.get("enforcement")
    if not isinstance(enforcement, dict):
        return []
    level_enforcement = enforcement.get(level)
    if not isinstance(level_enforcement, dict):
        return []

    reason_id = gate.get("violation_reason_id")
    results: List[GateResult] = []
    for context in contexts:
        outcome = level_enforcement.get(context)
        if outcome is None or outcome == "allow":
            continue
        results.append(
            {
                "gate_id": gate_id,
                "context": context,
                "outcome": outcome,
                "reason_id": reason_id,
                "details": {
                    "param_id": param_id,
                    "value": param_value,
                    "abs_value": abs_value,
                    "warn_abs_max": warn_abs_max,
                    "fail_abs_max": fail_abs_max,
                    "level": level,
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
        if kind == "action_prefix_limit":
            gate_results.extend(
                _evaluate_action_prefix_limit(rec, gate_id, gate, contexts)
            )
            continue
        if kind == "metric_delta_limit":
            gate_results.extend(
                _evaluate_metric_delta_limit(rec, gate_id, gate, contexts)
            )
            continue
        if gate_id == "GATE.DOWNMIX_POLICY_EXISTS":
            if policy_path is None:
                continue
            gate_results.extend(
                _evaluate_downmix_policy_exists(rec, gate_id, gate, contexts, policy_path)
            )
            continue
        # Other gates are currently stubbed (deterministic allow)

    gate_results = _sort_gate_results(gate_results, contexts)

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
    profile_id: str | None = None,
    profiles_path: Path | None = None,
) -> None:
    policy = load_gates_policy(policy_path)
    selected_profile_id = _coerce_str(profile_id)
    if selected_profile_id:
        resolved_profiles_path = profiles_path or (policy_path.parent / "authority_profiles.yaml")
        profiles_policy = load_authority_profiles(resolved_profiles_path)
        policy = apply_profile_overrides(policy, selected_profile_id, profiles_policy)
        report["profile_id"] = selected_profile_id
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
