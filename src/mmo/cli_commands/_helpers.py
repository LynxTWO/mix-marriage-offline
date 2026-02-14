"""Shared utilities used across CLI subcommand modules.

Layer 0 — no cli_commands imports; only imports from mmo.core / stdlib.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from mmo.core.presets import load_preset_run_config
from mmo.core.routing import apply_routing_plan_to_report
from mmo.core.run_config import (
    RUN_CONFIG_SCHEMA_VERSION,
    load_run_config,
    merge_run_config,
    normalize_run_config,
)
from mmo.core.timeline import load_timeline
from mmo.dsp.transcode import LOSSLESS_OUTPUT_FORMATS

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

# ── Constants shared by parser setup (cli.py) AND handler modules ──

_BASELINE_RENDER_TARGET_ID = "TARGET.STEREO.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_FORMAT_SET_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_PRESET_PREVIEW_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_PRESET_PREVIEW_DEFAULT_METERS = "truth"
_PRESET_PREVIEW_DEFAULT_MAX_SECONDS = 120.0
_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID = "LAYOUT.2_0"
_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S = 30.0

__all__ = [
    # constants
    "_BASELINE_RENDER_TARGET_ID",
    "_OUTPUT_FORMAT_ORDER",
    "_FORMAT_SET_NAME_RE",
    "_PRESET_PREVIEW_DEFAULT_PROFILE_ID",
    "_PRESET_PREVIEW_DEFAULT_METERS",
    "_PRESET_PREVIEW_DEFAULT_MAX_SECONDS",
    "_PRESET_PREVIEW_DEFAULT_TARGET_LAYOUT_ID",
    "_DEFAULT_RENDER_MANY_TRANSLATION_AUDITION_SEGMENT_S",
    "RUN_CONFIG_SCHEMA_VERSION",
    # functions
    "_load_json_object",
    "_load_report",
    "_load_timeline_payload",
    "_render_timeline_text",
    "_load_json_schema",
    "_build_schema_registry",
    "_write_json_file",
    "_flag_present",
    "_set_nested",
    "_rel_path_if_under_root",
    "_load_and_merge_run_config",
    "_config_string",
    "_config_optional_string",
    "_config_float",
    "_config_int",
    "_config_nested_optional_string",
    "_parse_output_formats_csv",
    "_parse_output_format_set",
    "_parse_output_format_sets",
    "_config_nested_output_formats",
    "_stamp_report_run_config",
    "_validate_json_payload",
    "_validate_render_manifest",
    "_validate_apply_manifest",
    "_coerce_str",
]


# ── JSON I/O ──────────────────────────────────────────────────────


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return data


def _load_report(report_path: Path) -> dict[str, Any]:
    return _load_json_object(report_path, label="Report")


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ── Timeline helpers ──────────────────────────────────────────────


def _load_timeline_payload(timeline_path: Path | None) -> dict[str, Any] | None:
    if timeline_path is None:
        return None
    return load_timeline(timeline_path)


def _render_timeline_text(timeline: dict[str, Any]) -> str:
    lines = [f"schema_version: {timeline.get('schema_version', '')}", "sections:"]
    raw_sections = timeline.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        lines.append("- (none)")
        return "\n".join(lines)

    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id", "")
        label = section.get("label", "")
        start_s = section.get("start_s", "")
        end_s = section.get("end_s", "")
        lines.append(f"- {section_id}  {label}  {start_s}..{end_s}")
    return "\n".join(lines)


# ── Schema loading + validation ───────────────────────────────────


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - environment issue
        raise ValueError(
            "jsonschema referencing support is unavailable; cannot validate schema refs."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = _load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _validate_json_payload(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        print(
            f"jsonschema is not installed; cannot validate {payload_name}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        schema = _load_json_schema(schema_path)
        registry = _build_schema_registry(schema_path.parent)
    except ValueError as exc:
        print(
            str(exc),
            file=sys.stderr,
        )
        raise SystemExit(1)

    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    print(f"{payload_name} schema validation failed:", file=sys.stderr)
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        print(f"- {path}: {err.message}", file=sys.stderr)
    raise SystemExit(1)


def _validate_render_manifest(render_manifest: dict[str, Any], schema_path: Path) -> None:
    _validate_json_payload(
        render_manifest,
        schema_path=schema_path,
        payload_name="Render manifest",
    )


def _validate_apply_manifest(apply_manifest: dict[str, Any], schema_path: Path) -> None:
    _validate_json_payload(
        apply_manifest,
        schema_path=schema_path,
        payload_name="Apply manifest",
    )


# ── Config extraction ─────────────────────────────────────────────


def _flag_present(raw_argv: list[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in raw_argv)


def _set_nested(path: list[str], payload: dict[str, Any], value: Any) -> None:
    target = payload
    for part in path[:-1]:
        existing = target.get(part)
        if not isinstance(existing, dict):
            existing = {}
            target[part] = existing
        target = existing
    target[path[-1]] = value


def _rel_path_if_under_root(root_dir: Path, target_path: Path) -> str | None:
    resolved_root = root_dir.resolve()
    resolved_target = target_path.resolve()
    try:
        rel_path = resolved_target.relative_to(resolved_root)
    except ValueError:
        return None
    return rel_path.as_posix()


def _load_and_merge_run_config(
    config_path: str | None,
    cli_overrides: dict[str, Any],
    *,
    preset_id: str | None = None,
    presets_dir: Path | None = None,
) -> dict[str, Any]:
    merged_cfg: dict[str, Any] = {}
    if preset_id:
        if presets_dir is None:
            raise ValueError("presets_dir is required when preset_id is provided.")
        preset_cfg = load_preset_run_config(presets_dir, preset_id)
        merged_cfg = merge_run_config(merged_cfg, preset_cfg)
    if config_path:
        file_cfg = load_run_config(Path(config_path))
        merged_cfg = merge_run_config(merged_cfg, file_cfg)
    merged_cfg = merge_run_config(merged_cfg, cli_overrides)
    if preset_id:
        merged_cfg["preset_id"] = preset_id.strip()
        return normalize_run_config(merged_cfg)
    return merged_cfg


def _config_string(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key)
    if isinstance(value, str) and value:
        return value
    return default


def _config_optional_string(
    config: dict[str, Any],
    key: str,
    default: str | None,
) -> str | None:
    value = config.get(key)
    if isinstance(value, str):
        return value
    return default


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    value = config.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _config_nested_optional_string(
    config: dict[str, Any],
    section: str,
    key: str,
    default: str | None,
) -> str | None:
    section_data = config.get(section)
    if isinstance(section_data, dict):
        value = section_data.get(key)
        if isinstance(value, str):
            return value
    return default


# ── Output format parsing ─────────────────────────────────────────


def _parse_output_formats_csv(raw_value: str) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("output formats must be a comma-separated string.")

    selected: set[str] = set()
    for item in raw_value.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if normalized not in _OUTPUT_FORMAT_ORDER:
            allowed = ",".join(_OUTPUT_FORMAT_ORDER)
            raise ValueError(
                f"Unsupported output format {normalized!r}. Allowed: {allowed}."
            )
        selected.add(normalized)

    if not selected:
        raise ValueError("output formats must include at least one value.")

    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _parse_output_format_set(raw_value: str) -> tuple[str, list[str]]:
    if not isinstance(raw_value, str):
        raise ValueError("format-set must use <name>:<csv> syntax.")

    name_raw, separator, formats_raw = raw_value.partition(":")
    if separator != ":":
        raise ValueError("format-set must use <name>:<csv> syntax.")

    name = name_raw.strip().lower()
    if not name:
        raise ValueError("format-set name is required.")
    if _FORMAT_SET_NAME_RE.fullmatch(name) is None:
        raise ValueError("format-set name must match ^[a-z0-9_]+$.")

    return (name, _parse_output_formats_csv(formats_raw))


def _parse_output_format_sets(values: list[str]) -> list[tuple[str, list[str]]]:
    normalized: list[tuple[str, list[str]]] = []
    seen_names: set[str] = set()
    for raw in values:
        name, output_formats = _parse_output_format_set(raw)
        if name in seen_names:
            raise ValueError(f"Duplicate format-set name {name!r}.")
        seen_names.add(name)
        normalized.append((name, output_formats))
    return normalized


def _config_nested_output_formats(
    config: dict[str, Any],
    section: str,
    default: list[str] | None = None,
) -> list[str]:
    fallback = list(default) if isinstance(default, list) and default else ["wav"]
    section_data = config.get(section)
    if not isinstance(section_data, dict):
        return fallback
    value = section_data.get("output_formats")
    if not isinstance(value, list):
        return fallback
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            normalized.append(item)
    if not normalized:
        return fallback
    return normalized


# ── Report stamping ───────────────────────────────────────────────


def _stamp_report_run_config(report_path: Path, run_config: dict[str, Any]) -> None:
    report = _load_report(report_path)
    normalized_run_config = normalize_run_config(run_config)
    report["run_config"] = normalized_run_config
    apply_routing_plan_to_report(report, normalized_run_config)
    _write_json_file(report_path, report)


# ── Coercion helpers ──────────────────────────────────────────────


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""
