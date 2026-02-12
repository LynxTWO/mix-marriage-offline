from __future__ import annotations

import json
from typing import Any


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_score(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        score = int(round(float(value)))
        return max(0, min(100, score))
    return 0


def _coerce_threshold(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        threshold = int(round(float(value)))
        return max(0, min(100, threshold))
    return default


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _status_from_score(*, score: int, warn_below: int, fail_below: int) -> str:
    if score < fail_below:
        return "fail"
    if score < warn_below:
        return "warn"
    return "pass"


def _short_reason(
    *,
    result: dict[str, Any],
    score: int,
    warn_below: int,
    fail_below: int,
) -> str:
    issues = _iter_dict_list(result.get("issues"))
    if not issues:
        return "Score meets threshold."

    issue_id = _coerce_str(issues[0].get("issue_id")).strip() or "ISSUE.UNKNOWN"
    return (
        f"{issue_id}: score={score} fail<{fail_below} warn<{warn_below}."
    )


def build_translation_summary(
    translation_results: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    profiles_map = profiles if isinstance(profiles, dict) else {}

    for result in translation_results:
        if not isinstance(result, dict):
            continue
        profile_id = _coerce_str(result.get("profile_id")).strip()
        if not profile_id:
            continue

        profile_payload = profiles_map.get(profile_id)
        profile = profile_payload if isinstance(profile_payload, dict) else {}
        score = _coerce_score(result.get("score"))
        warn_below = _coerce_threshold(profile.get("score_warn_below"), default=70)
        fail_below = _coerce_threshold(profile.get("score_fail_below"), default=50)
        fail_below = min(fail_below, warn_below)
        label = _coerce_str(profile.get("label")).strip() or profile_id

        rows.append(
            {
                "profile_id": profile_id,
                "status": _status_from_score(
                    score=score,
                    warn_below=warn_below,
                    fail_below=fail_below,
                ),
                "score": score,
                "label": label,
                "short_reason": _short_reason(
                    result=result,
                    score=score,
                    warn_below=warn_below,
                    fail_below=fail_below,
                ),
            }
        )

    rows.sort(
        key=lambda item: (
            _coerce_str(item.get("profile_id")).strip(),
            json.dumps(item, sort_keys=True),
        )
    )
    return rows
