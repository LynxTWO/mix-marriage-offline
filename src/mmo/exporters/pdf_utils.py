from __future__ import annotations

import json
from typing import Any

_TRUNCATION_SUFFIX = "...(truncated)"


def truncate_value(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    suffix_len = len(_TRUNCATION_SUFFIX)
    return f"{value[: max(limit - suffix_len, 0)]}{_TRUNCATION_SUFFIX}"


def _truncate_json_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return truncate_value(value, limit)
    if isinstance(value, list):
        return [_truncate_json_strings(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_json_strings(val, limit) for key, val in value.items()}
    return value


def render_json(value: Any, limit: int, *, pretty: bool = False) -> str:
    payload = _truncate_json_strings(value, limit)
    if pretty:
        return json.dumps(payload, sort_keys=True, indent=2)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def render_maybe_json(value: Any, limit: int, *, pretty: bool = False) -> str:
    if isinstance(value, (dict, list)):
        return render_json(value, limit, pretty=pretty)
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return truncate_value(value, limit)
            return render_json(parsed, limit, pretty=pretty)
        return truncate_value(value, limit)
    return truncate_value(str(value), limit)
