from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUN_CONFIG_SCHEMA_VERSION = "0.1.0"

_TOP_LEVEL_KEYS = {
    "schema_version",
    "preset_id",
    "profile_id",
    "meters",
    "max_seconds",
    "truncate_values",
    "downmix",
    "render",
}
_DOWNMIX_KEYS = {"source_layout_id", "target_layout_id", "policy_id"}
_RENDER_KEYS = {"out_dir"}


def _coerce_non_negative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number.")
    if isinstance(value, (int, float)):
        coerced = float(value)
    elif isinstance(value, str):
        try:
            coerced = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number.") from exc
    else:
        raise ValueError(f"{field_name} must be a number.")
    if coerced < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return coerced


def _coerce_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        coerced = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field_name} must be an integer.")
        coerced = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} must be an integer.")
        try:
            coerced = int(stripped)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
    else:
        raise ValueError(f"{field_name} must be an integer.")
    if coerced < 0:
        raise ValueError(f"{field_name} must be >= 0.")
    return coerced


def _coerce_optional_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_downmix(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("downmix must be an object.")

    unknown = sorted(set(value.keys()) - _DOWNMIX_KEYS)
    if unknown:
        raise ValueError(f"Unknown downmix field(s): {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for key in sorted(value.keys()):
        if value[key] is None:
            continue
        normalized[key] = _coerce_optional_string(value[key])
    return normalized


def _normalize_render(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("render must be an object.")

    unknown = sorted(set(value.keys()) - _RENDER_KEYS)
    if unknown:
        raise ValueError(f"Unknown render field(s): {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for key in sorted(value.keys()):
        if value[key] is None:
            continue
        normalized[key] = _coerce_optional_string(value[key])
    return normalized


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in sorted(set(base.keys()).union(override.keys())):
        base_value = base.get(key)
        override_value = override.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge(base_value, override_value)
            continue
        if key in override:
            merged[key] = override_value
            continue
        merged[key] = base_value
    return merged


def _validate_normalized(cfg: dict[str, Any]) -> None:
    unknown = sorted(set(cfg.keys()) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"Unknown run config field(s): {', '.join(unknown)}")

    schema_version = cfg.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError("run config must include schema_version.")
    if schema_version != RUN_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported run config schema_version: "
            f"{schema_version!r} (expected {RUN_CONFIG_SCHEMA_VERSION!r})."
        )

    profile_id = cfg.get("profile_id")
    if profile_id is not None and not isinstance(profile_id, str):
        raise ValueError("profile_id must be a string.")

    preset_id = cfg.get("preset_id")
    if preset_id is not None and not isinstance(preset_id, str):
        raise ValueError("preset_id must be a string.")

    meters = cfg.get("meters")
    if meters is not None and not isinstance(meters, str):
        raise ValueError("meters must be a string.")

    max_seconds = cfg.get("max_seconds")
    if max_seconds is not None:
        _coerce_non_negative_float(max_seconds, "max_seconds")

    truncate_values = cfg.get("truncate_values")
    if truncate_values is not None:
        _coerce_non_negative_int(truncate_values, "truncate_values")

    downmix = cfg.get("downmix")
    if downmix is not None and not isinstance(downmix, dict):
        raise ValueError("downmix must be an object.")

    render = cfg.get("render")
    if render is not None and not isinstance(render, dict):
        raise ValueError("render must be an object.")


def normalize_run_config(cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise ValueError("Run config must be a JSON object.")

    unknown = sorted(set(cfg.keys()) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"Unknown run config field(s): {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    for key in sorted(cfg.keys()):
        value = cfg[key]
        if value is None:
            continue
        if key == "schema_version":
            normalized[key] = _coerce_optional_string(value)
        elif key == "preset_id":
            if not isinstance(value, str):
                raise ValueError("preset_id must be a string.")
            preset_id = value.strip()
            if preset_id:
                normalized[key] = preset_id
        elif key == "profile_id":
            normalized[key] = _coerce_optional_string(value)
        elif key == "meters":
            normalized[key] = _coerce_optional_string(value)
        elif key == "max_seconds":
            normalized[key] = _coerce_non_negative_float(value, "max_seconds")
        elif key == "truncate_values":
            normalized[key] = _coerce_non_negative_int(value, "truncate_values")
        elif key == "downmix":
            downmix = _normalize_downmix(value)
            if downmix:
                normalized[key] = downmix
        elif key == "render":
            render = _normalize_render(value)
            if render:
                normalized[key] = render

    _validate_normalized(normalized)
    return normalized


def load_run_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read run config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Run config is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Run config JSON must be an object.")
    return normalize_run_config(raw)


def merge_run_config(base_cfg: dict[str, Any], cli_overrides: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(base_cfg, dict):
        raise ValueError("base_cfg must be an object.")
    if not isinstance(cli_overrides, dict):
        raise ValueError("cli_overrides must be an object.")

    base_normalized = normalize_run_config(
        {**base_cfg, "schema_version": base_cfg.get("schema_version", RUN_CONFIG_SCHEMA_VERSION)}
    )
    overrides_normalized = normalize_run_config(
        {
            **cli_overrides,
            "schema_version": cli_overrides.get(
                "schema_version",
                base_normalized.get("schema_version", RUN_CONFIG_SCHEMA_VERSION),
            ),
        }
    )
    merged = _deep_merge(base_normalized, overrides_normalized)
    merged["schema_version"] = merged.get("schema_version", RUN_CONFIG_SCHEMA_VERSION)
    return normalize_run_config(merged)


def _flatten_run_config_paths(
    payload: dict[str, Any],
    *,
    path_prefix: str = "",
) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key in sorted(payload.keys()):
        value = payload[key]
        key_path = f"{path_prefix}.{key}" if path_prefix else key
        if isinstance(value, dict):
            flattened.update(_flatten_run_config_paths(value, path_prefix=key_path))
            continue
        flattened[key_path] = value
    return flattened


def diff_run_config(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(before, dict):
        raise ValueError("before must be an object.")
    if not isinstance(after, dict):
        raise ValueError("after must be an object.")

    before_flat = _flatten_run_config_paths(before)
    after_flat = _flatten_run_config_paths(after)
    key_paths = sorted(set(before_flat.keys()).union(after_flat.keys()))

    diffs: list[dict[str, Any]] = []
    for key_path in key_paths:
        before_value = before_flat.get(key_path)
        after_value = after_flat.get(key_path)
        if before_value == after_value:
            continue
        diffs.append(
            {
                "key_path": key_path,
                "before": before_value,
                "after": after_value,
            }
        )
    return diffs
