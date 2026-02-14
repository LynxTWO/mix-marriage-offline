from __future__ import annotations

from typing import Any

from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config

__all__ = [
    "_downmix_qa_run_config",
]


def _downmix_qa_run_config(
    *,
    profile_id: str,
    meters: str,
    max_seconds: float,
    truncate_values: int,
    source_layout_id: str,
    target_layout_id: str,
    policy_id: str | None,
    preset_id: str | None = None,
    base_run_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(base_run_config or {})
    downmix_payload: dict[str, Any] = {
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
    }
    if policy_id is not None:
        downmix_payload["policy_id"] = policy_id
    payload["schema_version"] = RUN_CONFIG_SCHEMA_VERSION
    payload["profile_id"] = profile_id
    payload["meters"] = meters
    payload["max_seconds"] = max_seconds
    payload["truncate_values"] = truncate_values
    payload["downmix"] = downmix_payload
    if preset_id is not None:
        payload["preset_id"] = preset_id
    return normalize_run_config(payload)
