from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


FallbackApplyFn = Callable[[Any], tuple[Any, list[dict[str, Any]]]]
FallbackRenderFn = Callable[[Any], Any]
FallbackQaFn = Callable[[Any], dict[str, Any]]
FallbackPassFn = Callable[[dict[str, Any]], bool]
FallbackScoreFn = Callable[[dict[str, Any]], float]


@dataclass(frozen=True)
class FallbackStep:
    step_id: str
    apply: FallbackApplyFn


@dataclass(frozen=True)
class FallbackStopRule:
    max_steps: int
    improvement_epsilon: float
    stagnation_limit: int
    score_fn: FallbackScoreFn | None = None
    pass_fn: FallbackPassFn | None = None


def _coerce_bool(value: Any) -> bool:
    return value is True


def _default_pass_fn(qa_result: dict[str, Any]) -> bool:
    return _coerce_bool(qa_result.get("passed"))


def _default_score_fn(qa_result: dict[str, Any]) -> float:
    raw_score = qa_result.get("score")
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
        return float(raw_score)
    return 0.0 if _default_pass_fn(qa_result) else 1.0


def _normalize_stop_rule(stop_rule: FallbackStopRule | dict[str, Any]) -> FallbackStopRule:
    if isinstance(stop_rule, FallbackStopRule):
        return stop_rule
    if not isinstance(stop_rule, dict):
        raise TypeError("stop_rule must be a FallbackStopRule or dict.")
    max_steps = stop_rule.get("max_steps")
    if not isinstance(max_steps, int) or max_steps < 0:
        raise ValueError("stop_rule.max_steps must be a non-negative integer.")
    epsilon = stop_rule.get("improvement_epsilon", 0.0)
    if not isinstance(epsilon, (int, float)) or isinstance(epsilon, bool):
        raise ValueError("stop_rule.improvement_epsilon must be numeric.")
    stagnation_limit = stop_rule.get("stagnation_limit", 1)
    if not isinstance(stagnation_limit, int) or stagnation_limit < 1:
        raise ValueError("stop_rule.stagnation_limit must be a positive integer.")
    score_fn = stop_rule.get("score_fn")
    if score_fn is not None and not callable(score_fn):
        raise ValueError("stop_rule.score_fn must be callable.")
    pass_fn = stop_rule.get("pass_fn")
    if pass_fn is not None and not callable(pass_fn):
        raise ValueError("stop_rule.pass_fn must be callable.")
    return FallbackStopRule(
        max_steps=max_steps,
        improvement_epsilon=float(epsilon),
        stagnation_limit=stagnation_limit,
        score_fn=score_fn,
        pass_fn=pass_fn,
    )


def _normalize_steps(steps: Iterable[FallbackStep | dict[str, Any]]) -> list[FallbackStep]:
    normalized: list[FallbackStep] = []
    for step in steps:
        if isinstance(step, FallbackStep):
            normalized.append(step)
            continue
        if not isinstance(step, dict):
            raise TypeError("Fallback steps must be FallbackStep objects or dicts.")
        step_id = step.get("step_id")
        apply = step.get("apply")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Fallback step is missing step_id.")
        if not callable(apply):
            raise ValueError(f"Fallback step {step_id!r} is missing callable apply.")
        normalized.append(FallbackStep(step_id=step_id.strip(), apply=apply))
    return normalized


def run_fallback_sequence(
    render_fn: FallbackRenderFn,
    qa_fn: FallbackQaFn,
    initial_state: Any,
    steps: Sequence[FallbackStep | dict[str, Any]],
    stop_rule: FallbackStopRule | dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    normalized_steps = _normalize_steps(steps)
    normalized_rule = _normalize_stop_rule(stop_rule)
    pass_fn = normalized_rule.pass_fn or _default_pass_fn
    score_fn = normalized_rule.score_fn or _default_score_fn

    current_state = render_fn(initial_state)
    current_qa = qa_fn(current_state)
    attempts: list[dict[str, Any]] = []
    applied_steps: list[str] = []
    stagnation_count = 0
    stop_reason = "initial_pass" if pass_fn(current_qa) else "steps_exhausted"

    for step in normalized_steps:
        if len(applied_steps) >= normalized_rule.max_steps:
            stop_reason = "max_steps_reached"
            break
        next_state, changes = step.apply(current_state)
        if not changes:
            continue

        next_state = render_fn(next_state)
        qa_after = qa_fn(next_state)
        score_before = score_fn(current_qa)
        score_after = score_fn(qa_after)
        improvement = float(score_before) - float(score_after)

        if pass_fn(qa_after):
            result = "pass"
            stop_reason = "qa_pass"
            stagnation_count = 0
        elif improvement < normalized_rule.improvement_epsilon:
            result = "no_improvement"
            stagnation_count += 1
            stop_reason = "insufficient_improvement"
        else:
            result = "improved"
            stagnation_count = 0
            stop_reason = "steps_exhausted"

        attempts.append(
            {
                "step_id": step.step_id,
                "changes": changes,
                "qa_before": current_qa,
                "qa_after": qa_after,
                "result": result,
                "improvement": round(improvement, 6),
            }
        )
        applied_steps.append(step.step_id)
        current_state = next_state
        current_qa = qa_after

        if result == "pass":
            break
        if stagnation_count >= normalized_rule.stagnation_limit:
            break

    final_outcome = "pass" if pass_fn(current_qa) else "fail"
    if not attempts and pass_fn(current_qa):
        final_outcome = "not_needed"
    elif not attempts and not pass_fn(current_qa):
        stop_reason = "no_applicable_steps"

    return current_state, {
        "initial_qa": current_qa if not attempts and final_outcome == "not_needed" else (
            attempts[0]["qa_before"] if attempts else current_qa
        ),
        "fallback_applied": bool(applied_steps),
        "fallback_attempts": attempts,
        "fallback_final": {
            "applied_steps": applied_steps,
            "final_outcome": final_outcome,
            "stop_reason": stop_reason,
            "attempt_count": len(attempts),
            "final_qa": current_qa,
        },
    }
