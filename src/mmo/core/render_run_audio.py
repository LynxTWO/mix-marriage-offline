"""Deterministic offline audio rendering for ``render-run``."""

from __future__ import annotations

import json
import math
import random
import struct
import subprocess
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

from mmo.core.render_execute import resolve_ffmpeg_version
from mmo.core.render_reporting import build_render_report_from_plan
from mmo.dsp.backends.ffmpeg_decode import (
    build_ffmpeg_decode_command,
    iter_ffmpeg_float64_samples,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import read_metadata
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.transcode import (
    LOSSLESS_OUTPUT_FORMATS,
    ffmpeg_determinism_flags,
    transcode_wav_to_format,
)

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_OUTPUT_FORMAT_ORDER = tuple(LOSSLESS_OUTPUT_FORMATS)
_WAV_EXTENSIONS = frozenset({".wav", ".wave"})
_FFMPEG_EXTENSIONS = frozenset({".flac", ".wv", ".aif", ".aiff", ".m4a"})
_LOSSY_EXTENSIONS = frozenset({".mp3", ".aac", ".ogg", ".opus"})
_SOURCE_EXTENSIONS = _WAV_EXTENSIONS | _FFMPEG_EXTENSIONS | _LOSSY_EXTENSIONS
_BIT_DEPTHS = frozenset({16, 24, 32})
_INTERMEDIATE_ROOT = ".mmo_tmp/render_run"
_FLOAT_MAX = math.nextafter(1.0, 0.0)
_GAIN_V0_PLUGIN_ID = "gain_v0"
_TILT_EQ_V0_PLUGIN_ID = "tilt_eq_v0"
_SIMPLE_COMPRESSOR_V0_PLUGIN_ID = "simple_compressor_v0"
_MULTIBAND_COMPRESSOR_V0_PLUGIN_ID = "multiband_compressor_v0"
_MULTIBAND_EXPANDER_V0_PLUGIN_ID = "multiband_expander_v0"
_MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID = "multiband_dynamic_auto_v0"
_SIMPLE_COMPRESSOR_DETECTOR_MODE_RMS = "rms"
_SIMPLE_COMPRESSOR_DETECTOR_MODE_PEAK = "peak"
_SIMPLE_COMPRESSOR_DETECTOR_MODE_LUFS_SHORTTERM = "lufs_shortterm"
_SIMPLE_COMPRESSOR_DETECTOR_MODES = frozenset(
    {
        _SIMPLE_COMPRESSOR_DETECTOR_MODE_RMS,
        _SIMPLE_COMPRESSOR_DETECTOR_MODE_PEAK,
        _SIMPLE_COMPRESSOR_DETECTOR_MODE_LUFS_SHORTTERM,
    }
)
_MULTIBAND_OPERATION_COMPRESS = "compress"
_MULTIBAND_OPERATION_EXPAND = "expand"
_MULTIBAND_OPERATION_AUTO = "auto"
_MULTIBAND_DETECTOR_MODES = _SIMPLE_COMPRESSOR_DETECTOR_MODES
_MULTIBAND_MIN_BANDS = 2
_MULTIBAND_MAX_BANDS = 8
_MULTIBAND_WINDOW_SIZE = 2048
_MULTIBAND_HOP_SIZE = 512
_MULTIBAND_MAX_LOOKAHEAD_MS = 20.0
_MULTIBAND_MAX_OVERSAMPLING = 2
_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ: tuple[float, ...] = (
    16.0,
    20.0,
    25.0,
    31.5,
    40.0,
    50.0,
    63.0,
    80.0,
    100.0,
    125.0,
    160.0,
    200.0,
    250.0,
    315.0,
    400.0,
    500.0,
    630.0,
    800.0,
    1000.0,
    1250.0,
    1600.0,
    2000.0,
    2500.0,
    3150.0,
    4000.0,
    5000.0,
    6300.0,
    8000.0,
    10000.0,
    12500.0,
    16000.0,
    20000.0,
)

ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED = "ISSUE.RENDER.RUN.DOWNMIX_SCOPE_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID = "ISSUE.RENDER.RUN.SOURCE_STEMS_DIR_INVALID"
ISSUE_RENDER_RUN_SOURCE_MISSING = "ISSUE.RENDER.RUN.SOURCE_MISSING"
ISSUE_RENDER_RUN_SOURCE_COUNT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_COUNT_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_FORMAT_UNSUPPORTED"
ISSUE_RENDER_RUN_SOURCE_LAYOUT_UNSUPPORTED = "ISSUE.RENDER.RUN.SOURCE_LAYOUT_UNSUPPORTED"
ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED = "ISSUE.RENDER.RUN.OUTPUT_FORMAT_UNSUPPORTED"
ISSUE_RENDER_RUN_OPTION_UNSUPPORTED = "ISSUE.RENDER.RUN.OPTION_UNSUPPORTED"
ISSUE_RENDER_RUN_FFMPEG_REQUIRED = "ISSUE.RENDER.RUN.FFMPEG_REQUIRED"
ISSUE_RENDER_RUN_DECODE_FAILED = "ISSUE.RENDER.RUN.DECODE_FAILED"
ISSUE_RENDER_RUN_ENCODE_FAILED = "ISSUE.RENDER.RUN.ENCODE_FAILED"
ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID = "ISSUE.RENDER.RUN.PLUGIN_CHAIN_INVALID"
ISSUE_RENDER_RUN_PLUGIN_SOURCE_FORMAT_UNSUPPORTED = (
    "ISSUE.RENDER.RUN.PLUGIN_SOURCE_FORMAT_UNSUPPORTED"
)

_PLUGIN_CHAIN_CONFIG_SCHEMA_FALLBACKS_BY_ID: dict[str, dict[str, Any]] = {
    _GAIN_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "gain_db": {"type": "number", "minimum": -24, "maximum": 24},
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
    _TILT_EQ_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tilt_db": {"type": "number", "minimum": -6, "maximum": 6},
            "pivot_hz": {"type": "number", "minimum": 200, "maximum": 2000},
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
    _SIMPLE_COMPRESSOR_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "threshold_db": {"type": "number", "minimum": -60, "maximum": 0},
            "ratio": {"type": "number", "minimum": 1, "maximum": 20},
            "attack_ms": {"type": "number", "minimum": 0.1, "maximum": 250},
            "release_ms": {"type": "number", "minimum": 5, "maximum": 2000},
            "makeup_db": {"type": "number", "minimum": -12, "maximum": 24},
            "detector_mode": {
                "type": "string",
                "enum": sorted(_SIMPLE_COMPRESSOR_DETECTOR_MODES),
            },
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
    _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "threshold_db": {"type": "number", "minimum": -60, "maximum": 0},
            "ratio": {"type": "number", "minimum": 1, "maximum": 20},
            "attack_ms": {"type": "number", "minimum": 0.1, "maximum": 250},
            "release_ms": {"type": "number", "minimum": 5, "maximum": 2000},
            "makeup_db": {"type": "number", "minimum": -12, "maximum": 24},
            "lookahead_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": _MULTIBAND_MAX_LOOKAHEAD_MS,
            },
            "detector_mode": {
                "type": "string",
                "enum": sorted(_MULTIBAND_DETECTOR_MODES),
            },
            "slope_sensitivity": {"type": "number", "minimum": 0, "maximum": 1},
            "min_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "max_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "oversampling": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MULTIBAND_MAX_OVERSAMPLING,
            },
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
    _MULTIBAND_EXPANDER_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "threshold_db": {"type": "number", "minimum": -60, "maximum": 0},
            "ratio": {"type": "number", "minimum": 1, "maximum": 20},
            "attack_ms": {"type": "number", "minimum": 0.1, "maximum": 250},
            "release_ms": {"type": "number", "minimum": 5, "maximum": 2000},
            "makeup_db": {"type": "number", "minimum": -12, "maximum": 24},
            "lookahead_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": _MULTIBAND_MAX_LOOKAHEAD_MS,
            },
            "detector_mode": {
                "type": "string",
                "enum": sorted(_MULTIBAND_DETECTOR_MODES),
            },
            "slope_sensitivity": {"type": "number", "minimum": 0, "maximum": 1},
            "min_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "max_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "oversampling": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MULTIBAND_MAX_OVERSAMPLING,
            },
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
    _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID: {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "threshold_db": {"type": "number", "minimum": -60, "maximum": 0},
            "ratio": {"type": "number", "minimum": 1, "maximum": 20},
            "attack_ms": {"type": "number", "minimum": 0.1, "maximum": 250},
            "release_ms": {"type": "number", "minimum": 5, "maximum": 2000},
            "makeup_db": {"type": "number", "minimum": -12, "maximum": 24},
            "lookahead_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": _MULTIBAND_MAX_LOOKAHEAD_MS,
            },
            "detector_mode": {
                "type": "string",
                "enum": sorted(_MULTIBAND_DETECTOR_MODES),
            },
            "slope_sensitivity": {"type": "number", "minimum": 0, "maximum": 1},
            "min_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "max_band_count": {
                "type": "integer",
                "minimum": _MULTIBAND_MIN_BANDS,
                "maximum": _MULTIBAND_MAX_BANDS,
            },
            "oversampling": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MULTIBAND_MAX_OVERSAMPLING,
            },
            "macro_mix": {"type": "number", "minimum": 0, "maximum": 100},
            "bypass": {"type": "boolean"},
        },
    },
}
_PLUGIN_CHAIN_RUNTIME_REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    _GAIN_V0_PLUGIN_ID: ("gain_db",),
    _TILT_EQ_V0_PLUGIN_ID: ("tilt_db", "pivot_hz"),
    _SIMPLE_COMPRESSOR_V0_PLUGIN_ID: (
        "threshold_db",
        "ratio",
        "attack_ms",
        "release_ms",
        "makeup_db",
    ),
    _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID: (
        "threshold_db",
        "ratio",
        "attack_ms",
        "release_ms",
        "makeup_db",
    ),
    _MULTIBAND_EXPANDER_V0_PLUGIN_ID: (
        "threshold_db",
        "ratio",
        "attack_ms",
        "release_ms",
        "makeup_db",
    ),
    _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID: (
        "threshold_db",
        "ratio",
        "attack_ms",
        "release_ms",
        "makeup_db",
    ),
}
_PLUGIN_CHAIN_CONFIG_SCHEMA_CACHE: dict[str, dict[str, Any]] | None = None


def _clone_json_payload(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _normalize_plugin_id_alias(value: str) -> str:
    cleaned = [
        (char.lower() if char.isalnum() else "_")
        for char in value
    ]
    collapsed = "".join(cleaned).strip("_")
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    return collapsed


def _plugin_manifest_aliases(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> list[str]:
    aliases: set[str] = set()

    file_stem = manifest_path.stem
    if file_stem.endswith(".plugin"):
        file_stem = file_stem[:-7]
    stem_alias = _normalize_plugin_id_alias(file_stem)
    if stem_alias:
        aliases.add(stem_alias)

    raw_plugin_id = _coerce_str(manifest.get("plugin_id")).strip()
    if raw_plugin_id:
        full_alias = _normalize_plugin_id_alias(raw_plugin_id.replace(".", "_"))
        if full_alias:
            aliases.add(full_alias)
        tail_alias = _normalize_plugin_id_alias(raw_plugin_id.split(".")[-1])
        if tail_alias:
            aliases.add(tail_alias)

    return sorted(aliases)


def _plugins_search_roots() -> list[Path]:
    candidates: list[Path] = []

    try:
        from mmo.resources import _repo_checkout_root  # noqa: WPS433
    except Exception:  # pragma: no cover - defensive fallback
        _repo_checkout_root = None

    if callable(_repo_checkout_root):
        repo_root = _repo_checkout_root()
        if repo_root is not None:
            candidates.append((repo_root / "plugins").resolve())

    candidates.append((Path.cwd() / "plugins").resolve())

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = candidate.as_posix()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        roots.append(candidate)
    return roots


def _load_yaml_mapping(path: Path) -> dict[str, Any] | None:
    if yaml is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError:
        return None
    except Exception:  # pragma: no cover - yaml errors differ by version
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _collect_plugin_chain_config_schemas() -> dict[str, dict[str, Any]]:
    schemas_by_alias: dict[str, dict[str, Any]] = {}

    manifest_patterns = ("plugin.yaml", "plugin.yml", "*.plugin.yaml")
    for plugins_root in _plugins_search_roots():
        if not plugins_root.is_dir():
            continue

        manifest_paths: set[Path] = set()
        for pattern in manifest_patterns:
            for candidate in plugins_root.rglob(pattern):
                if candidate.is_file():
                    manifest_paths.add(candidate.resolve())

        for manifest_path in sorted(manifest_paths, key=lambda path: path.as_posix()):
            manifest = _load_yaml_mapping(manifest_path)
            if not isinstance(manifest, dict):
                continue
            config_schema = manifest.get("config_schema")
            if not isinstance(config_schema, dict):
                continue
            for alias in _plugin_manifest_aliases(
                manifest_path=manifest_path,
                manifest=manifest,
            ):
                schemas_by_alias.setdefault(alias, _clone_json_payload(config_schema))

    for alias, schema_payload in _PLUGIN_CHAIN_CONFIG_SCHEMA_FALLBACKS_BY_ID.items():
        schemas_by_alias.setdefault(alias, _clone_json_payload(schema_payload))

    return schemas_by_alias


def _plugin_chain_config_schemas() -> dict[str, dict[str, Any]]:
    global _PLUGIN_CHAIN_CONFIG_SCHEMA_CACHE  # noqa: PLW0603

    if _PLUGIN_CHAIN_CONFIG_SCHEMA_CACHE is None:
        _PLUGIN_CHAIN_CONFIG_SCHEMA_CACHE = _collect_plugin_chain_config_schemas()
    return _PLUGIN_CHAIN_CONFIG_SCHEMA_CACHE


def _plugin_config_schema_for_id(plugin_id: str) -> dict[str, Any] | None:
    schema_payload = _plugin_chain_config_schemas().get(plugin_id)
    if not isinstance(schema_payload, dict):
        return None
    return _clone_json_payload(schema_payload)


def _schema_types(schema: dict[str, Any]) -> tuple[str, ...]:
    raw_type = schema.get("type")
    if isinstance(raw_type, str) and raw_type.strip():
        return (raw_type.strip(),)
    if isinstance(raw_type, list):
        normalized = sorted(
            {
                item.strip()
                for item in raw_type
                if isinstance(item, str) and item.strip()
            }
        )
        return tuple(normalized)
    return ()


def _json_type_name(types: tuple[str, ...]) -> str:
    names = {
        "array": "an array",
        "boolean": "a boolean",
        "integer": "an integer",
        "null": "null",
        "number": "a number",
        "object": "an object",
        "string": "a string",
    }
    if not types:
        return "a valid value"
    if len(types) == 1:
        return names.get(types[0], f"a {types[0]}")
    rendered = ", ".join(sorted(names.get(item, item) for item in types))
    return f"one of: {rendered}"


def _matches_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "null":
        return value is None
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "string":
        return isinstance(value, str)
    return True


def _value_is_schema_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _coerce_schema_bound(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
    return None


def _format_note_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _clamp_number(
    *,
    value: float,
    minimum: float | None,
    maximum: float | None,
) -> tuple[float, str | None]:
    clamped = value
    note_kind: str | None = None
    if minimum is not None and clamped < minimum:
        clamped = minimum
        note_kind = "minimum"
    if maximum is not None and clamped > maximum:
        clamped = maximum
        note_kind = "maximum"
    return clamped, note_kind


def _normalize_plugin_stage_params(
    *,
    chain_label: str,
    stage_index: int,
    plugin_id: str,
    params: dict[str, Any],
    config_schema: dict[str, Any],
    lenient_numeric_bounds: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    stage_prefix = f"{chain_label}[{stage_index}]"
    normalized_params: dict[str, Any] = {}
    errors: list[str] = []
    notes: list[str] = []

    properties_payload = config_schema.get("properties")
    properties = (
        {
            key: value
            for key, value in properties_payload.items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        if isinstance(properties_payload, dict)
        else {}
    )
    unknown_keys = sorted(
        key
        for key in params
        if key not in properties
    )
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        errors.append(f"{stage_prefix}.params has unknown key(s): {joined}.")

    runtime_required = _PLUGIN_CHAIN_RUNTIME_REQUIRED_PARAMS.get(plugin_id, ())
    for required_param in sorted(runtime_required):
        if required_param not in params:
            errors.append(f"{stage_prefix}.params.{required_param} is required.")

    for param_name in sorted(params):
        raw_value = params[param_name]
        param_schema = properties.get(param_name)
        if param_schema is None:
            continue

        param_path = f"{stage_prefix}.params.{param_name}"
        expected_types = _schema_types(param_schema)
        if expected_types and not any(
            _matches_schema_type(raw_value, schema_type)
            for schema_type in expected_types
        ):
            errors.append(f"{param_path} must be {_json_type_name(expected_types)}.")
            continue

        normalized_value = raw_value
        minimum_value = _coerce_schema_bound(param_schema.get("minimum"))
        maximum_value = _coerce_schema_bound(param_schema.get("maximum"))
        numeric_type_expected = bool({"integer", "number"} & set(expected_types))

        if numeric_type_expected and _value_is_schema_number(raw_value):
            numeric_value = float(raw_value)
            if lenient_numeric_bounds:
                clamped_value, note_kind = _clamp_number(
                    value=numeric_value,
                    minimum=minimum_value,
                    maximum=maximum_value,
                )
                if clamped_value != numeric_value:
                    expects_integer_only = (
                        "integer" in expected_types and "number" not in expected_types
                    )
                    if expects_integer_only:
                        normalized_value = int(round(clamped_value))
                    elif isinstance(raw_value, int) and float(clamped_value).is_integer():
                        normalized_value = int(clamped_value)
                    else:
                        normalized_value = float(clamped_value)

                    if note_kind == "minimum":
                        bound_details = f"minimum={_format_note_value(minimum_value)}"
                    elif note_kind == "maximum":
                        bound_details = f"maximum={_format_note_value(maximum_value)}"
                    else:
                        bound_details = (
                            "bounds="
                            f"{_format_note_value(minimum_value)}.."
                            f"{_format_note_value(maximum_value)}"
                        )
                    notes.append(
                        (
                            f"{param_path} clamped from {_format_note_value(raw_value)} "
                            f"to {_format_note_value(normalized_value)} using {bound_details}."
                        )
                    )
            else:
                if minimum_value is not None and numeric_value < minimum_value:
                    errors.append(
                        f"{param_path} must be >= {_format_note_value(minimum_value)}.",
                    )
                    continue
                if maximum_value is not None and numeric_value > maximum_value:
                    errors.append(
                        f"{param_path} must be <= {_format_note_value(maximum_value)}.",
                    )
                    continue

        normalized_params[param_name] = normalized_value

    return normalized_params, errors, notes


def validate_and_normalize_plugin_chain(
    raw_chain: Any,
    *,
    chain_label: str,
    lenient_numeric_bounds: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_chain, list) or not raw_chain:
        raise ValueError(f"{chain_label} must be a non-empty list when provided.")

    normalized_chain: list[dict[str, Any]] = []
    ordered_errors: list[str] = []
    ordered_notes: list[str] = []

    for stage_index, raw_stage in enumerate(raw_chain, start=1):
        stage_prefix = f"{chain_label}[{stage_index}]"
        if not isinstance(raw_stage, dict):
            ordered_errors.append(f"{stage_prefix} must be an object.")
            continue

        plugin_id = _coerce_str(raw_stage.get("plugin_id")).strip().lower()
        if not plugin_id:
            ordered_errors.append(
                f"{stage_prefix}.plugin_id must be a non-empty string.",
            )
            continue

        raw_params = raw_stage.get("params")
        if raw_params is None:
            params = {}
        elif isinstance(raw_params, dict):
            params = dict(raw_params)
        else:
            ordered_errors.append(
                f"{stage_prefix}.params must be an object when provided.",
            )
            continue

        config_schema = _plugin_config_schema_for_id(plugin_id)
        if not isinstance(config_schema, dict):
            ordered_errors.append(
                (
                    f"{stage_prefix}.plugin_id references an unsupported plugin: "
                    f"{plugin_id}."
                ),
            )
            continue

        normalized_params, stage_errors, stage_notes = _normalize_plugin_stage_params(
            chain_label=chain_label,
            stage_index=stage_index,
            plugin_id=plugin_id,
            params=params,
            config_schema=config_schema,
            lenient_numeric_bounds=lenient_numeric_bounds,
        )
        if stage_errors:
            ordered_errors.extend(stage_errors)
            continue

        normalized_stage: dict[str, Any] = {"plugin_id": plugin_id}
        if "params" in raw_stage:
            normalized_stage["params"] = normalized_params
        normalized_chain.append(normalized_stage)
        ordered_notes.extend(stage_notes)

    if ordered_errors:
        details = "; ".join(ordered_errors)
        raise ValueError(f"{chain_label} validation failed: {details}")

    return normalized_chain, ordered_notes


class RenderRunRefusalError(ValueError):
    """Raised when ``render-run`` audio execution must refuse a request."""

    def __init__(self, *, issue_id: str, message: str) -> None:
        self.issue_id = issue_id
        super().__init__(f"{issue_id}: {message}")


def request_dry_run_enabled(request_payload: dict[str, Any]) -> bool:
    """Return True unless options explicitly opt into execution."""
    options = request_payload.get("options")
    if not isinstance(options, dict):
        return True
    dry_run = options.get("dry_run")
    if isinstance(dry_run, bool):
        return dry_run
    return True


def build_render_report_with_audio(
    *,
    plan_payload: dict[str, Any],
    request_payload: dict[str, Any],
    scene_payload: dict[str, Any],
    scene_path: Path,
    report_out_path: Path,
    capture_execute_trace: bool = False,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Render stereo deliverables and return report/execute/plugin/qa trace payloads."""
    jobs = _stereo_jobs_or_raise(plan_payload)
    source_path = _resolve_single_source_or_raise(scene_payload)
    source_metadata = _read_source_metadata_or_raise(source_path)
    _validate_source_layout_or_raise(source_metadata)

    options = _coerce_dict(request_payload.get("options"))
    requested_max_theoretical_quality = options.get("max_theoretical_quality")
    max_theoretical_quality = _coerce_bool(requested_max_theoretical_quality)
    if (
        requested_max_theoretical_quality is not None
        and max_theoretical_quality is None
    ):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "options.max_theoretical_quality must be a boolean "
                "(true or false) when provided."
            ),
        )
    max_theoretical_quality = bool(max_theoretical_quality)
    source_rate_hz = _coerce_int(source_metadata.get("sample_rate_hz")) or 0
    requested_rate_hz = _coerce_int(options.get("sample_rate_hz"))
    if requested_rate_hz is not None and requested_rate_hz != source_rate_hz:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "sample_rate_hz override is not supported for PR52 render-run. "
                f"requested={requested_rate_hz}, source={source_rate_hz}"
            ),
        )

    output_bit_depth = _resolve_output_bit_depth(
        requested_bit_depth=_coerce_int(options.get("bit_depth")),
        source_bit_depth=_coerce_int(source_metadata.get("bits_per_sample")),
    )
    scene_anchor = _scene_anchor_root(
        request_scene_path=_coerce_str(request_payload.get("scene_path")),
        scene_path=scene_path,
    )
    report_dir = report_out_path.resolve().parent
    plugin_chain, plugin_chain_notes = _plugin_chain_from_request(request_payload)
    plugin_chain_enabled = bool(plugin_chain)
    plugin_chain_force_float64 = any(
        isinstance(stage, dict)
        and _coerce_str(stage.get("plugin_id")).strip().lower()
        in {
            _SIMPLE_COMPRESSOR_V0_PLUGIN_ID,
            _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID,
            _MULTIBAND_EXPANDER_V0_PLUGIN_ID,
            _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID,
        }
        for stage in plugin_chain
    )
    report_payload = build_render_report_from_plan(
        plan_payload,
        status="completed",
        reason="rendered",
    )
    report_jobs = report_payload.get("jobs")
    if not isinstance(report_jobs, list):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message="Expected report jobs list for stereo render-run execution.",
        )
    report_jobs_by_id: dict[str, dict[str, Any]] = {}
    for report_job in report_jobs:
        if not isinstance(report_job, dict):
            continue
        report_job_id = _coerce_str(report_job.get("job_id")).strip()
        if not report_job_id:
            continue
        report_jobs_by_id[report_job_id] = report_job

    execute_job_rows: list[dict[str, Any]] = []
    qa_job_rows: list[dict[str, Any]] = []
    plugin_step_events: list[dict[str, Any]] = []
    seen_output_paths: set[str] = set()

    for job in jobs:
        job_id = _coerce_str(job.get("job_id")).strip() or "JOB.001"
        output_formats = _job_output_formats_or_raise(job)
        planned_outputs = _planned_outputs_by_format(job)

        wav_path: Path
        keep_wav_output = "wav" in output_formats
        wav_candidate = planned_outputs.get("wav")
        if isinstance(wav_candidate, str) and wav_candidate:
            wav_path = _resolve_output_path(
                raw_path=wav_candidate,
                scene_anchor=scene_anchor,
                report_dir=report_dir,
            )
        elif keep_wav_output:
            wav_path = _fallback_output_path(
                report_dir=report_dir,
                job_id=job_id,
                output_format="wav",
            )
        else:
            wav_path = _intermediate_wav_path(
                report_dir=report_dir,
                job_id=job_id,
            )

        ffmpeg_cmd_for_decode: Sequence[str] | None = None
        ffmpeg_cmd_for_encode: Sequence[str] | None = None
        source_extension = source_path.suffix.lower()
        needs_ffmpeg_decode = source_extension in _FFMPEG_EXTENSIONS
        needs_ffmpeg_encode = any(fmt != "wav" for fmt in output_formats)
        needs_ffmpeg_for_trace = keep_wav_output and capture_execute_trace
        if needs_ffmpeg_decode or needs_ffmpeg_encode or needs_ffmpeg_for_trace:
            ffmpeg_cmd_for_decode = resolve_ffmpeg_cmd()
            ffmpeg_cmd_for_encode = ffmpeg_cmd_for_decode
            if ffmpeg_cmd_for_decode is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                    message=(
                        "ffmpeg is required for requested render-run operation "
                        "(decode and/or encode lossless non-WAV audio, "
                        "or deterministic execution tracing)."
                    ),
                )

        ffmpeg_command_rows: list[dict[str, Any]] = []
        job_plugin_step_events: list[dict[str, Any]] = []

        try:
            if plugin_chain_enabled:
                if capture_execute_trace and source_extension in _FFMPEG_EXTENSIONS:
                    if ffmpeg_cmd_for_decode is None:
                        raise RenderRunRefusalError(
                            issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                            message="ffmpeg is required to decode non-WAV source audio.",
                        )
                    ffmpeg_command_rows.append(
                        {
                            "args": build_ffmpeg_decode_command(
                                source_path,
                                ffmpeg_cmd_for_decode,
                            ),
                            "determinism_flags": [],
                        }
                    )
                job_plugin_step_events = _render_wav_with_plugin_chain(
                    source_path=source_path,
                    output_path=wav_path,
                    sample_rate_hz=source_rate_hz,
                    bit_depth=output_bit_depth,
                    plugin_chain=plugin_chain,
                    ffmpeg_cmd_for_decode=ffmpeg_cmd_for_decode,
                    max_theoretical_quality=max_theoretical_quality,
                    force_float64_default=plugin_chain_force_float64,
                )
            else:
                float_samples_iter: Iterator[list[float]]
                if source_extension in _WAV_EXTENSIONS:
                    float_samples_iter = iter_wav_float64_samples(
                        source_path,
                        error_context="render-run stereo downmix",
                    )
                else:
                    if ffmpeg_cmd_for_decode is None:
                        raise RenderRunRefusalError(
                            issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                            message="ffmpeg is required to decode non-WAV source audio.",
                        )
                    if capture_execute_trace:
                        ffmpeg_command_rows.append(
                            {
                                "args": build_ffmpeg_decode_command(
                                    source_path,
                                    ffmpeg_cmd_for_decode,
                                ),
                                "determinism_flags": [],
                            }
                        )
                    float_samples_iter = iter_ffmpeg_float64_samples(
                        source_path,
                        ffmpeg_cmd_for_decode,
                    )

                _write_stereo_wav(
                    float_samples_iter=float_samples_iter,
                    output_path=wav_path,
                    sample_rate_hz=source_rate_hz,
                    bit_depth=output_bit_depth,
                )
        except RenderRunRefusalError:
            raise
        except ValueError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=f"Failed to decode and render source audio: {exc}",
            ) from exc

        output_files: list[dict[str, Any]] = []
        try:
            if keep_wav_output and capture_execute_trace:
                if ffmpeg_cmd_for_encode is None:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                        message=(
                            "ffmpeg is required to normalize WAV output metadata "
                            "for deterministic execution tracing."
                        ),
                    )
                _normalize_wav_for_determinism(
                    ffmpeg_cmd=ffmpeg_cmd_for_encode,
                    wav_path=wav_path,
                    bit_depth=output_bit_depth,
                    command_rows=ffmpeg_command_rows,
                )

            if keep_wav_output:
                output_files.append(
                    _output_file_payload(
                        output_path=wav_path,
                        output_format="wav",
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                    )
                )

            for output_format in output_formats:
                if output_format == "wav":
                    continue
                target_path = _resolve_output_path(
                    raw_path=planned_outputs.get(output_format, ""),
                    scene_anchor=scene_anchor,
                    report_dir=report_dir,
                    fallback=_fallback_output_path(
                        report_dir=report_dir,
                        job_id=job_id,
                        output_format=output_format,
                    ),
                )
                try:
                    if ffmpeg_cmd_for_encode is None:
                        raise RenderRunRefusalError(
                            issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                            message="ffmpeg is required to encode non-WAV deliverables.",
                        )
                    transcode_command_rows: list[list[str]] | None = []
                    if not capture_execute_trace:
                        transcode_command_rows = None
                    transcode_wav_to_format(
                        ffmpeg_cmd_for_encode,
                        wav_path,
                        target_path,
                        output_format,
                        command_recorder=transcode_command_rows,
                    )
                    if transcode_command_rows:
                        ffmpeg_command_rows.append(
                            {
                                "args": transcode_command_rows[-1],
                                "determinism_flags": list(
                                    ffmpeg_determinism_flags(for_wav=False)
                                ),
                            }
                        )
                except RenderRunRefusalError:
                    raise
                except ValueError as exc:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                        message=f"Failed to encode {output_format} deliverable: {exc}",
                    ) from exc
                output_files.append(
                    _output_file_payload(
                        output_path=target_path,
                        output_format=output_format,
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                    )
                )
        finally:
            if not keep_wav_output:
                try:
                    if wav_path.exists():
                        wav_path.unlink()
                except OSError:
                    # Keep deterministic behavior: refusal path should be from prior stable error.
                    pass

        output_files.sort(key=lambda item: _output_sort_key(_coerce_str(item.get("format"))))
        output_paths = _output_paths_from_rows(output_files)
        if not output_paths:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                message="No output paths were produced for render-run execution.",
            )
        for output_path in output_paths:
            output_path_key = output_path.resolve().as_posix()
            if output_path_key in seen_output_paths:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                    message=(
                        "render-run requires distinct output paths across stereo jobs. "
                        f"duplicate_output_path={output_path_key}"
                    ),
                )
            seen_output_paths.add(output_path_key)

        report_job = report_jobs_by_id.get(job_id)
        if not isinstance(report_job, dict):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message=(
                    "Render report is missing a job entry for executed stereo job. "
                    f"job_id={job_id}"
                ),
            )
        report_job["status"] = "completed"
        report_job["output_files"] = output_files
        target_layout_id = _coerce_str(job.get("target_layout_id")).strip() or _STEREO_LAYOUT_ID
        report_notes = [
            "reason: rendered",
            f"source_file: {source_path.resolve().as_posix()}",
            "source_layout_id: LAYOUT.2_0",
            f"target_layout_id: {target_layout_id}",
        ]
        if plugin_chain_enabled:
            report_notes.append("macro_mix applied as linear blend.")
            precision_mode = (
                "float64"
                if (max_theoretical_quality or plugin_chain_force_float64)
                else "float32"
            )
            report_notes.append(f"plugin_chain_precision_mode: {precision_mode}")
        for note in plugin_chain_notes:
            report_notes.append(f"plugin_chain_note: {note}")
        report_job["notes"] = report_notes

        qa_job_rows.append(
            {
                "job_id": job_id,
                "input_paths": [source_path.resolve()],
                "output_paths": output_paths,
            }
        )
        if capture_execute_trace:
            ffmpeg_cmd_for_trace = ffmpeg_cmd_for_encode or ffmpeg_cmd_for_decode
            if ffmpeg_cmd_for_trace is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                    message="ffmpeg is required to capture deterministic execute traces.",
                )
            execute_job_rows.append(
                {
                    "job_id": job_id,
                    "input_paths": [source_path.resolve()],
                    "output_paths": output_paths,
                    "ffmpeg_version": resolve_ffmpeg_version(ffmpeg_cmd_for_trace),
                    "ffmpeg_commands": ffmpeg_command_rows,
                }
            )
        plugin_step_events.extend(job_plugin_step_events)

    return report_payload, execute_job_rows, plugin_step_events, qa_job_rows


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, float) and value in (0.0, 1.0):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


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


def _plugin_chain_from_request(
    request_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    options = _coerce_dict(request_payload.get("options"))
    if "plugin_chain" not in options:
        return [], []

    raw_chain = options.get("plugin_chain")
    try:
        normalized_chain, notes = validate_and_normalize_plugin_chain(
            raw_chain,
            chain_label="options.plugin_chain",
            lenient_numeric_bounds=True,
        )
    except ValueError as exc:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=str(exc),
        ) from exc
    return normalized_chain, notes


def _render_wav_with_plugin_chain(
    *,
    source_path: Path,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
    plugin_chain: list[dict[str, Any]],
    ffmpeg_cmd_for_decode: Sequence[str] | None,
    max_theoretical_quality: bool,
    force_float64_default: bool,
) -> list[dict[str, Any]]:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "options.plugin_chain requires numpy runtime support. "
                "Install numpy or remove plugin_chain from the request."
            ),
        ) from exc

    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    use_float64_processing = bool(max_theoretical_quality or force_float64_default)
    processing_dtype_name = "float64" if use_float64_processing else "float32"
    processing_dtype = np.float64 if use_float64_processing else np.float32

    stereo_samples = _read_stereo_source_samples(
        source_path,
        ffmpeg_cmd=ffmpeg_cmd_for_decode,
        dtype=processing_dtype,
    )
    frame_count = int(stereo_samples.shape[0])

    source_posix = source_path.resolve().as_posix()
    output_posix = output_path.resolve().as_posix()
    step_events: list[dict[str, Any]] = [
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain source loaded",
            "why": (
                "Loaded stereo source into "
                f"{processing_dtype_name} buffer for deterministic plugin execution."
            ),
            "where": [source_posix],
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.SOURCE_LOADED"],
                "paths": [source_posix],
                "metrics": [
                    {"name": "channel_count", "value": 2},
                    {"name": "frame_count", "value": frame_count},
                ],
            },
        },
    ]

    def _parse_bypass_for_stage(
        *,
        plugin_id: str,
        params: dict[str, Any],
    ) -> bool:
        bypass_raw = params.get("bypass")
        if bypass_raw is None:
            return False
        bypass_value = _coerce_bool(bypass_raw)
        if bypass_value is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{plugin_id} requires boolean params.bypass when provided.",
            )
        return bypass_value

    def _parse_macro_mix_for_stage(
        *,
        plugin_id: str,
        params: dict[str, Any],
    ) -> tuple[float, float]:
        raw_macro_mix = params.get("macro_mix")
        if raw_macro_mix is None:
            return 1.0, 1.0
        macro_mix_input = _coerce_float(raw_macro_mix)
        if macro_mix_input is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    f"{plugin_id} requires numeric params.macro_mix "
                    "in [0.0, 1.0] or [0.0, 100.0]."
                ),
            )
        if 0.0 <= macro_mix_input <= 1.0:
            return macro_mix_input, macro_mix_input
        if 0.0 <= macro_mix_input <= 100.0:
            return macro_mix_input / 100.0, macro_mix_input
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                f"{plugin_id} requires params.macro_mix "
                "in [0.0, 1.0] or [0.0, 100.0]."
            ),
        )

    def _require_finite_float_param(
        *,
        plugin_id: str,
        params: dict[str, Any],
        param_name: str,
    ) -> float:
        value = _coerce_float(params.get(param_name))
        if value is None or not math.isfinite(value):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{plugin_id} requires numeric params.{param_name}.",
            )
        return float(value)

    def _parse_simple_compressor_detector_mode(
        *,
        plugin_id: str,
        params: dict[str, Any],
    ) -> str:
        raw_mode = params.get("detector_mode")
        if raw_mode is None:
            return _SIMPLE_COMPRESSOR_DETECTOR_MODE_RMS
        if not isinstance(raw_mode, str):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    f"{plugin_id} requires string params.detector_mode. "
                    f"Allowed: {', '.join(sorted(_SIMPLE_COMPRESSOR_DETECTOR_MODES))}."
                ),
            )
        mode = raw_mode.strip().lower()
        if mode in _SIMPLE_COMPRESSOR_DETECTOR_MODES:
            return mode
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                f"{plugin_id} requires params.detector_mode in "
                f"{', '.join(sorted(_SIMPLE_COMPRESSOR_DETECTOR_MODES))}."
            ),
        )

    def _db_from_linear_level(linear_level: float) -> float:
        if linear_level <= 1e-12:
            return -120.0
        return 20.0 * math.log10(linear_level)

    def _apply_simple_compressor_v0(
        *,
        signal: Any,
        sample_rate_hz: int,
        threshold_db: float,
        ratio: float,
        attack_ms: float,
        release_ms: float,
        makeup_db: float,
        detector_mode: str,
        output_dtype: Any,
    ) -> tuple[Any, float]:
        dry64 = signal.astype(np.float64, copy=False)
        wet64 = np.empty_like(dry64, dtype=np.float64)

        safe_sample_rate_hz = max(float(sample_rate_hz), 1.0)
        safe_attack_ms = max(float(attack_ms), 0.001)
        safe_release_ms = max(float(release_ms), 0.001)
        safe_ratio = max(float(ratio), 1.0)

        attack_seconds = max(safe_attack_ms / 1000.0, 1.0 / safe_sample_rate_hz)
        release_seconds = max(safe_release_ms / 1000.0, 1.0 / safe_sample_rate_hz)
        attack_coeff = math.exp(-1.0 / (attack_seconds * safe_sample_rate_hz))
        release_coeff = math.exp(-1.0 / (release_seconds * safe_sample_rate_hz))
        makeup_scalar = float(math.pow(10.0, float(makeup_db) / 20.0))

        envelope_db = -120.0
        gain_reduction_sum_db = 0.0
        gain_reduction_count = 0
        frame_count_local = int(dry64.shape[0])

        for frame_index in range(frame_count_local):
            frame = dry64[frame_index, :]
            abs_frame = np.abs(frame)
            if detector_mode == _SIMPLE_COMPRESSOR_DETECTOR_MODE_PEAK:
                detector_linear = float(np.max(abs_frame))
                detector_db = _db_from_linear_level(detector_linear)
            else:
                detector_linear = math.sqrt(float(np.mean(abs_frame * abs_frame)))
                detector_db = _db_from_linear_level(detector_linear)
                if detector_mode == _SIMPLE_COMPRESSOR_DETECTOR_MODE_LUFS_SHORTTERM:
                    detector_db -= 0.691

            detector_coeff = (
                attack_coeff if detector_db > envelope_db else release_coeff
            )
            envelope_db = (detector_coeff * envelope_db) + (
                (1.0 - detector_coeff) * detector_db
            )

            over_db = envelope_db - threshold_db
            gain_reduction_db = 0.0
            if over_db > 0.0 and safe_ratio > 1.0:
                gain_reduction_db = over_db * (1.0 - (1.0 / safe_ratio))

            if gain_reduction_db > 0.0:
                gain_reduction_sum_db += gain_reduction_db
                gain_reduction_count += 1

            gain_scalar = makeup_scalar * float(
                math.pow(10.0, -gain_reduction_db / 20.0)
            )
            wet64[frame_index, :] = np.clip(frame * gain_scalar, -1.0, 1.0)

        gr_approx_db = (
            gain_reduction_sum_db / float(gain_reduction_count)
            if gain_reduction_count
            else 0.0
        )
        return wet64.astype(output_dtype, copy=False), gr_approx_db

    def _optional_int_param(
        *,
        plugin_id: str,
        params: dict[str, Any],
        param_name: str,
        default_value: int,
        minimum_value: int,
        maximum_value: int,
    ) -> int:
        raw_value = params.get(param_name)
        if raw_value is None:
            return default_value
        if isinstance(raw_value, bool):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{plugin_id} requires integer params.{param_name}.",
            )
        value = _coerce_int(raw_value)
        if value is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{plugin_id} requires integer params.{param_name}.",
            )
        if value < minimum_value or value > maximum_value:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    f"{plugin_id} requires params.{param_name} in "
                    f"[{minimum_value}, {maximum_value}]."
                ),
            )
        return value

    def _optional_float_param(
        *,
        plugin_id: str,
        params: dict[str, Any],
        param_name: str,
        default_value: float,
        minimum_value: float,
        maximum_value: float,
    ) -> float:
        raw_value = params.get(param_name)
        if raw_value is None:
            return default_value
        value = _coerce_float(raw_value)
        if value is None or not math.isfinite(value):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=f"{plugin_id} requires numeric params.{param_name}.",
            )
        if value < minimum_value or value > maximum_value:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    f"{plugin_id} requires params.{param_name} in "
                    f"[{minimum_value}, {maximum_value}]."
                ),
            )
        return float(value)

    def _parse_multiband_detector_mode(
        *,
        plugin_id: str,
        params: dict[str, Any],
    ) -> str:
        raw_mode = params.get("detector_mode")
        if raw_mode is None:
            return _SIMPLE_COMPRESSOR_DETECTOR_MODE_RMS
        if not isinstance(raw_mode, str):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    f"{plugin_id} requires string params.detector_mode. "
                    f"Allowed: {', '.join(sorted(_MULTIBAND_DETECTOR_MODES))}."
                ),
            )
        mode = raw_mode.strip().lower()
        if mode in _MULTIBAND_DETECTOR_MODES:
            return mode
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                f"{plugin_id} requires params.detector_mode in "
                f"{', '.join(sorted(_MULTIBAND_DETECTOR_MODES))}."
            ),
        )

    def _spectral_band_edges(centers_hz: Sequence[float]) -> list[tuple[float, float]]:
        edges: list[tuple[float, float]] = []
        if not centers_hz:
            return edges
        for index, center_hz in enumerate(centers_hz):
            if index == 0:
                low_hz = center_hz / math.sqrt(2.0)
            else:
                low_hz = math.sqrt(centers_hz[index - 1] * center_hz)
            if index == len(centers_hz) - 1:
                high_hz = center_hz * math.sqrt(2.0)
            else:
                high_hz = math.sqrt(center_hz * centers_hz[index + 1])
            edges.append((low_hz, high_hz))
        return edges

    def _adjacent_slopes_db_per_oct(
        *,
        centers_hz: Sequence[float],
        levels_db: Sequence[float | None],
    ) -> list[float | None]:
        slopes: list[float | None] = []
        for index in range(len(centers_hz) - 1):
            low_hz = float(centers_hz[index])
            high_hz = float(centers_hz[index + 1])
            low_level = levels_db[index]
            high_level = levels_db[index + 1]
            if (
                low_level is None
                or high_level is None
                or low_hz <= 0.0
                or high_hz <= low_hz
            ):
                slopes.append(None)
                continue
            octaves = math.log2(high_hz / low_hz)
            if abs(octaves) <= 1e-12:
                slopes.append(None)
                continue
            slope = float(high_level - low_level) / float(octaves)
            slopes.append(slope if math.isfinite(slope) else None)
        return slopes

    def _compute_multiband_levels_and_slopes(
        *,
        signal: Any,
        sample_rate_hz: int,
        window_size: int,
        hop_size: int,
    ) -> tuple[list[float | None], list[float | None]]:
        dry64 = signal.astype(np.float64, copy=False)
        if dry64.size <= 0:
            empty_levels = [None for _ in _MULTIBAND_SPECTRAL_BAND_CENTERS_HZ]
            empty_slopes = [None for _ in range(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ) - 1)]
            return empty_levels, empty_slopes

        mono = np.mean(dry64, axis=1)
        if mono.size <= 0 or sample_rate_hz <= 0:
            empty_levels = [None for _ in _MULTIBAND_SPECTRAL_BAND_CENTERS_HZ]
            empty_slopes = [None for _ in range(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ) - 1)]
            return empty_levels, empty_slopes

        effective_window = min(max(int(window_size), 256), int(max(mono.shape[0], 256)))
        effective_hop = max(1, min(int(hop_size), effective_window // 2))
        if effective_window <= 1:
            empty_levels = [None for _ in _MULTIBAND_SPECTRAL_BAND_CENTERS_HZ]
            empty_slopes = [None for _ in range(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ) - 1)]
            return empty_levels, empty_slopes

        if mono.shape[0] <= effective_window:
            frame_total = 1
        else:
            frame_total = 1 + (mono.shape[0] - effective_window) // effective_hop

        window = np.hanning(effective_window).astype(np.float64)
        freqs_hz = np.fft.rfftfreq(effective_window, d=1.0 / float(sample_rate_hz))
        band_edges = _spectral_band_edges(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ)
        band_masks = [
            (freqs_hz >= low_hz) & (freqs_hz < high_hz)
            for low_hz, high_hz in band_edges
        ]
        band_power = np.zeros(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ), dtype=np.float64)
        band_counts = np.zeros(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ), dtype=np.int64)

        for frame_index in range(frame_total):
            start = frame_index * effective_hop
            frame = mono[start : start + effective_window]
            if frame.shape[0] < effective_window:
                padded = np.zeros(effective_window, dtype=np.float64)
                padded[: frame.shape[0]] = frame
                frame = padded
            spectrum = np.fft.rfft(frame * window)
            power = (spectrum.real * spectrum.real) + (spectrum.imag * spectrum.imag)
            for band_index, mask in enumerate(band_masks):
                if not np.any(mask):
                    continue
                value = float(np.mean(power[mask]))
                if value <= 0.0:
                    continue
                band_power[band_index] += value
                band_counts[band_index] += 1

        levels_db: list[float | None] = []
        for band_index in range(len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ)):
            if int(band_counts[band_index]) <= 0:
                levels_db.append(None)
                continue
            mean_power = float(band_power[band_index]) / float(band_counts[band_index])
            levels_db.append(_db_from_linear_level(math.sqrt(max(mean_power, 0.0))))
        slopes = _adjacent_slopes_db_per_oct(
            centers_hz=_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ,
            levels_db=levels_db,
        )
        return levels_db, slopes

    def _derive_multiband_split_indices(
        *,
        slopes_db_per_oct: Sequence[float | None],
        min_band_count: int,
        max_band_count: int,
        slope_sensitivity: float,
    ) -> tuple[list[int], float]:
        valid_slopes = [
            abs(float(value))
            for value in slopes_db_per_oct
            if value is not None and math.isfinite(float(value))
        ]
        slope_activity = (
            float(sum(valid_slopes)) / float(len(valid_slopes))
            if valid_slopes
            else 0.0
        )
        clamped_sensitivity = min(max(float(slope_sensitivity), 0.0), 1.0)
        span = max(0, max_band_count - min_band_count)
        normalized_activity = min(1.0, (slope_activity / 8.0) * (0.5 + (0.5 * clamped_sensitivity)))
        target_band_count = min_band_count + int(round(span * normalized_activity))
        target_band_count = max(min_band_count, min(max_band_count, target_band_count))
        split_count = max(0, target_band_count - 1)
        if split_count <= 0:
            return [], slope_activity

        candidate_rows: list[tuple[float, int]] = []
        for index, slope_value in enumerate(slopes_db_per_oct):
            if slope_value is None or not math.isfinite(float(slope_value)):
                continue
            score = abs(float(slope_value)) * (0.5 + (0.5 * clamped_sensitivity))
            if score <= 0.0:
                continue
            candidate_rows.append((score, index))
        candidate_rows.sort(key=lambda item: (-item[0], item[1]))

        selected: list[int] = []
        min_spacing = 2
        for _, index in candidate_rows:
            if any(abs(index - other_index) < min_spacing for other_index in selected):
                continue
            selected.append(index)
            if len(selected) >= split_count:
                break

        if len(selected) < split_count:
            total_boundaries = len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ) - 1
            for boundary_rank in range(1, split_count + 1):
                candidate = int(round((boundary_rank * total_boundaries) / float(split_count + 1)))
                candidate = max(0, min(total_boundaries - 1, candidate))
                if candidate not in selected:
                    selected.append(candidate)
                if len(selected) >= split_count:
                    break

        selected = sorted(set(selected))
        if len(selected) > split_count:
            selected = selected[:split_count]
        return selected, slope_activity

    def _build_multiband_ranges(
        *,
        split_indices: Sequence[int],
        levels_db: Sequence[float | None],
        slopes_db_per_oct: Sequence[float | None],
        slope_sensitivity: float,
        operation_mode: str,
    ) -> list[dict[str, Any]]:
        edges = _spectral_band_edges(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ)
        bucket_last_index = len(_MULTIBAND_SPECTRAL_BAND_CENTERS_HZ) - 1
        boundaries = sorted({int(index) for index in split_indices if 0 <= int(index) < bucket_last_index})

        median_levels = sorted(
            float(level)
            for level in levels_db
            if level is not None and math.isfinite(float(level))
        )
        level_median = (
            median_levels[len(median_levels) // 2]
            if median_levels
            else -24.0
        )
        clamped_sensitivity = min(max(float(slope_sensitivity), 0.0), 1.0)
        auto_slope_threshold = 0.75 + ((1.0 - clamped_sensitivity) * 1.25)

        band_rows: list[dict[str, Any]] = []
        start_bucket = 0
        for boundary in boundaries + [bucket_last_index]:
            end_bucket = int(boundary)
            if end_bucket < start_bucket:
                continue
            low_hz = float(edges[start_bucket][0])
            high_hz = float(edges[end_bucket][1])

            local_slopes = [
                float(value)
                for value in slopes_db_per_oct[start_bucket:end_bucket]
                if value is not None and math.isfinite(float(value))
            ]
            local_levels = [
                float(value)
                for value in levels_db[start_bucket : end_bucket + 1]
                if value is not None and math.isfinite(float(value))
            ]
            band_slope = (
                float(sum(local_slopes)) / float(len(local_slopes))
                if local_slopes
                else 0.0
            )
            band_level = (
                float(sum(local_levels)) / float(len(local_levels))
                if local_levels
                else level_median
            )

            if operation_mode == _MULTIBAND_OPERATION_AUTO:
                if band_slope >= auto_slope_threshold:
                    band_operation = _MULTIBAND_OPERATION_COMPRESS
                elif band_slope <= -auto_slope_threshold:
                    band_operation = _MULTIBAND_OPERATION_EXPAND
                elif band_level >= level_median:
                    band_operation = _MULTIBAND_OPERATION_COMPRESS
                else:
                    band_operation = _MULTIBAND_OPERATION_EXPAND
            else:
                band_operation = operation_mode

            band_rows.append(
                {
                    "low_hz": low_hz,
                    "high_hz": high_hz,
                    "slope_db_per_oct": band_slope,
                    "mean_level_db": band_level,
                    "operation": band_operation,
                }
            )
            start_bucket = end_bucket + 1

        if not band_rows:
            band_rows.append(
                {
                    "low_hz": float(edges[0][0]),
                    "high_hz": float(edges[-1][1]),
                    "slope_db_per_oct": 0.0,
                    "mean_level_db": level_median,
                    "operation": operation_mode,
                }
            )
        return band_rows

    def _apply_multiband_dynamics_v0(
        *,
        signal: Any,
        sample_rate_hz: int,
        threshold_db: float,
        ratio: float,
        attack_ms: float,
        release_ms: float,
        makeup_db: float,
        lookahead_ms: float,
        detector_mode: str,
        slope_sensitivity: float,
        min_band_count: int,
        max_band_count: int,
        operation_mode: str,
        oversampling: int,
        max_theoretical_quality: bool,
        output_dtype: Any,
    ) -> tuple[Any, dict[str, Any]]:
        if oversampling > 1 and not max_theoretical_quality:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    "Multiband oversampling > 1 requires options.max_theoretical_quality=true."
                ),
            )

        dry64 = signal.astype(np.float64, copy=False)
        if dry64.size == 0:
            return dry64.astype(output_dtype, copy=False), {
                "band_count": 1.0,
                "slope_activity_db_per_oct": 0.0,
                "gr_approx_db": 0.0,
                "band_gr_approx_db": [0.0],
                "lookahead_samples": 0.0,
                "oversampling": float(oversampling),
                "operation_counts": {
                    _MULTIBAND_OPERATION_COMPRESS: 0.0,
                    _MULTIBAND_OPERATION_EXPAND: 0.0,
                },
            }

        analysis_window = _MULTIBAND_WINDOW_SIZE * max(1, int(oversampling))
        analysis_hop = _MULTIBAND_HOP_SIZE * max(1, int(oversampling))
        levels_db, slopes_db_per_oct = _compute_multiband_levels_and_slopes(
            signal=dry64,
            sample_rate_hz=sample_rate_hz,
            window_size=analysis_window,
            hop_size=analysis_hop,
        )
        split_indices, slope_activity = _derive_multiband_split_indices(
            slopes_db_per_oct=slopes_db_per_oct,
            min_band_count=min_band_count,
            max_band_count=max_band_count,
            slope_sensitivity=slope_sensitivity,
        )
        band_rows = _build_multiband_ranges(
            split_indices=split_indices,
            levels_db=levels_db,
            slopes_db_per_oct=slopes_db_per_oct,
            slope_sensitivity=slope_sensitivity,
            operation_mode=operation_mode,
        )

        sample_count = int(dry64.shape[0])
        channel_count = int(dry64.shape[1])
        window_size = min(max(analysis_window, 256), max(sample_count, 256))
        hop_size = max(1, min(analysis_hop, window_size // 2))
        if sample_count <= window_size:
            frame_total = 1
        else:
            frame_total = 1 + (sample_count - window_size) // hop_size

        window = np.hanning(window_size).astype(np.float64)
        freq_bins_hz = np.fft.rfftfreq(window_size, d=1.0 / float(sample_rate_hz))
        nyquist_hz = float(sample_rate_hz) * 0.5
        band_masks = []
        for band in band_rows:
            low_hz = max(0.0, float(band["low_hz"]))
            high_hz = min(nyquist_hz, float(band["high_hz"]))
            if high_hz <= low_hz:
                mask = np.zeros(freq_bins_hz.shape[0], dtype=bool)
            else:
                mask = (freq_bins_hz >= low_hz) & (freq_bins_hz < high_hz)
            band_masks.append(mask)

        detector_db = np.full((frame_total, len(band_rows)), -120.0, dtype=np.float64)
        for frame_index in range(frame_total):
            start = frame_index * hop_size
            frame_channels = np.zeros((channel_count, window_size), dtype=np.float64)
            available = max(0, min(window_size, sample_count - start))
            if available > 0:
                frame_channels[:, :available] = dry64[start : start + available, :].T
            spectrum = np.fft.rfft(frame_channels * window[np.newaxis, :], axis=1)
            magnitude = np.abs(spectrum)
            power = magnitude * magnitude
            for band_index, mask in enumerate(band_masks):
                if not np.any(mask):
                    continue
                if detector_mode == _SIMPLE_COMPRESSOR_DETECTOR_MODE_PEAK:
                    channel_values = np.max(magnitude[:, mask], axis=1)
                    linked_linear = float(np.max(channel_values))
                else:
                    channel_values = np.sqrt(np.mean(power[:, mask], axis=1))
                    linked_linear = float(np.max(channel_values))
                band_db = _db_from_linear_level(linked_linear)
                if detector_mode == _SIMPLE_COMPRESSOR_DETECTOR_MODE_LUFS_SHORTTERM:
                    band_db -= 0.691
                detector_db[frame_index, band_index] = band_db

        lookahead_samples = int(
            round(
                min(max(lookahead_ms, 0.0), _MULTIBAND_MAX_LOOKAHEAD_MS)
                * float(sample_rate_hz)
                / 1000.0
            )
        )
        lookahead_frames = (
            int(round(float(lookahead_samples) / float(hop_size)))
            if hop_size > 0
            else 0
        )

        safe_ratio = max(float(ratio), 1.0)
        safe_attack_seconds = max(float(attack_ms) / 1000.0, 1.0 / float(sample_rate_hz))
        safe_release_seconds = max(float(release_ms) / 1000.0, 1.0 / float(sample_rate_hz))
        frame_seconds = float(hop_size) / float(sample_rate_hz)
        attack_coeff = math.exp(-frame_seconds / safe_attack_seconds)
        release_coeff = math.exp(-frame_seconds / safe_release_seconds)

        band_envelope_db = np.full(len(band_rows), -120.0, dtype=np.float64)
        band_gain_linear = np.ones((frame_total, len(band_rows)), dtype=np.float64)
        band_gr_sum = np.zeros(len(band_rows), dtype=np.float64)
        band_gr_count = np.zeros(len(band_rows), dtype=np.int64)
        operation_counts = {
            _MULTIBAND_OPERATION_COMPRESS: 0.0,
            _MULTIBAND_OPERATION_EXPAND: 0.0,
        }
        for frame_index in range(frame_total):
            detector_index = min(frame_total - 1, frame_index + lookahead_frames)
            for band_index, band in enumerate(band_rows):
                detector_value = float(detector_db[detector_index, band_index])
                previous_env = float(band_envelope_db[band_index])
                coeff = attack_coeff if detector_value > previous_env else release_coeff
                envelope_db = (coeff * previous_env) + ((1.0 - coeff) * detector_value)
                band_envelope_db[band_index] = envelope_db

                band_slope = float(band.get("slope_db_per_oct", 0.0))
                slope_strength = min(1.0, (abs(band_slope) / 8.0) * max(0.0, slope_sensitivity))
                band_threshold_db = float(threshold_db) - (6.0 * slope_strength)
                band_ratio = min(20.0, max(1.0, safe_ratio * (1.0 + (0.5 * slope_strength))))
                band_operation = _coerce_str(band.get("operation")).strip().lower()
                attenuation_db = 0.0
                if band_operation == _MULTIBAND_OPERATION_COMPRESS:
                    over_db = envelope_db - band_threshold_db
                    if over_db > 0.0 and band_ratio > 1.0:
                        attenuation_db = over_db * (1.0 - (1.0 / band_ratio))
                    operation_counts[_MULTIBAND_OPERATION_COMPRESS] += 1.0
                elif band_operation == _MULTIBAND_OPERATION_EXPAND:
                    below_db = band_threshold_db - envelope_db
                    if below_db > 0.0 and band_ratio > 1.0:
                        attenuation_db = below_db * (1.0 - (1.0 / band_ratio))
                    operation_counts[_MULTIBAND_OPERATION_EXPAND] += 1.0

                if attenuation_db > 0.0:
                    band_gr_sum[band_index] += attenuation_db
                    band_gr_count[band_index] += 1
                gain_db = float(makeup_db) - attenuation_db
                band_gain_linear[frame_index, band_index] = float(math.pow(10.0, gain_db / 20.0))

        rendered = np.zeros((channel_count, sample_count + window_size), dtype=np.float64)
        norm = np.zeros(sample_count + window_size, dtype=np.float64)
        for frame_index in range(frame_total):
            start = frame_index * hop_size
            frame_channels = np.zeros((channel_count, window_size), dtype=np.float64)
            available = max(0, min(window_size, sample_count - start))
            if available > 0:
                frame_channels[:, :available] = dry64[start : start + available, :].T
            spectrum = np.fft.rfft(frame_channels * window[np.newaxis, :], axis=1)
            for band_index, mask in enumerate(band_masks):
                if not np.any(mask):
                    continue
                spectrum[:, mask] *= band_gain_linear[frame_index, band_index]
            frame_output = np.fft.irfft(spectrum, n=window_size, axis=1)
            rendered[:, start : start + window_size] += frame_output * window[np.newaxis, :]
            norm[start : start + window_size] += window * window

        norm_safe = np.where(norm > 1e-12, norm, 1.0)
        wet = (rendered[:, :sample_count] / norm_safe[:sample_count]).T
        wet = np.clip(wet, -1.0, 1.0).astype(output_dtype, copy=False)

        band_gr_approx_db: list[float] = []
        for band_index in range(len(band_rows)):
            count = int(band_gr_count[band_index])
            if count <= 0:
                band_gr_approx_db.append(0.0)
            else:
                band_gr_approx_db.append(float(band_gr_sum[band_index] / float(count)))
        if band_gr_approx_db:
            gr_approx_db = float(sum(band_gr_approx_db) / float(len(band_gr_approx_db)))
        else:
            gr_approx_db = 0.0

        summary: dict[str, Any] = {
            "band_count": float(len(band_rows)),
            "slope_activity_db_per_oct": float(slope_activity),
            "gr_approx_db": float(gr_approx_db),
            "band_gr_approx_db": [float(value) for value in band_gr_approx_db],
            "lookahead_samples": float(lookahead_samples),
            "oversampling": float(oversampling),
            "operation_counts": operation_counts,
            "bands": band_rows,
        }
        return wet, summary

    def _shelf_biquad_coefficients(
        *,
        sample_rate_hz: int,
        pivot_hz: float,
        gain_db: float,
        high_shelf: bool,
    ) -> tuple[float, float, float, float, float]:
        amplitude = float(math.pow(10.0, gain_db / 40.0))
        omega = (2.0 * math.pi * pivot_hz) / float(sample_rate_hz)
        cosine = math.cos(omega)
        sine = math.sin(omega)
        alpha = (sine / 2.0) * math.sqrt(2.0)
        beta = 2.0 * math.sqrt(amplitude) * alpha
        if high_shelf:
            b0 = amplitude * ((amplitude + 1.0) + ((amplitude - 1.0) * cosine) + beta)
            b1 = -2.0 * amplitude * ((amplitude - 1.0) + ((amplitude + 1.0) * cosine))
            b2 = amplitude * ((amplitude + 1.0) + ((amplitude - 1.0) * cosine) - beta)
            a0 = (amplitude + 1.0) - ((amplitude - 1.0) * cosine) + beta
            a1 = 2.0 * ((amplitude - 1.0) - ((amplitude + 1.0) * cosine))
            a2 = (amplitude + 1.0) - ((amplitude - 1.0) * cosine) - beta
        else:
            b0 = amplitude * ((amplitude + 1.0) - ((amplitude - 1.0) * cosine) + beta)
            b1 = 2.0 * amplitude * ((amplitude - 1.0) - ((amplitude + 1.0) * cosine))
            b2 = amplitude * ((amplitude + 1.0) - ((amplitude - 1.0) * cosine) - beta)
            a0 = (amplitude + 1.0) + ((amplitude - 1.0) * cosine) + beta
            a1 = -2.0 * ((amplitude - 1.0) + ((amplitude + 1.0) * cosine))
            a2 = (amplitude + 1.0) + ((amplitude - 1.0) * cosine) - beta
        inv_a0 = 1.0 / a0
        return (
            b0 * inv_a0,
            b1 * inv_a0,
            b2 * inv_a0,
            a1 * inv_a0,
            a2 * inv_a0,
        )

    def _apply_biquad_mono_float64(
        *,
        signal: Any,
        coefficients: tuple[float, float, float, float, float],
    ) -> Any:
        b0, b1, b2, a1, a2 = coefficients
        rendered_signal = np.empty_like(signal, dtype=np.float64)
        z1 = 0.0
        z2 = 0.0
        for sample_index in range(int(signal.shape[0])):
            x0 = float(signal[sample_index])
            y0 = (b0 * x0) + z1
            z1 = (b1 * x0) - (a1 * y0) + z2
            z2 = (b2 * x0) - (a2 * y0)
            rendered_signal[sample_index] = y0
        return rendered_signal

    def _apply_tilt_eq_v0(
        *,
        signal: Any,
        sample_rate_hz: int,
        tilt_db: float,
        pivot_hz: float,
        output_dtype: Any,
    ) -> Any:
        nyquist_hz = max(1.0, float(sample_rate_hz) / 2.0)
        bounded_pivot_hz = min(max(float(pivot_hz), 20.0), max(20.0, nyquist_hz - 1.0))
        low_shelf_gain_db = -0.5 * float(tilt_db)
        high_shelf_gain_db = 0.5 * float(tilt_db)
        low_coefficients = _shelf_biquad_coefficients(
            sample_rate_hz=sample_rate_hz,
            pivot_hz=bounded_pivot_hz,
            gain_db=low_shelf_gain_db,
            high_shelf=False,
        )
        high_coefficients = _shelf_biquad_coefficients(
            sample_rate_hz=sample_rate_hz,
            pivot_hz=bounded_pivot_hz,
            gain_db=high_shelf_gain_db,
            high_shelf=True,
        )
        dry64 = signal.astype(np.float64, copy=False)
        wet64 = np.empty_like(dry64, dtype=np.float64)
        for channel_index in range(int(dry64.shape[1])):
            low_passed = _apply_biquad_mono_float64(
                signal=dry64[:, channel_index],
                coefficients=low_coefficients,
            )
            wet64[:, channel_index] = _apply_biquad_mono_float64(
                signal=low_passed,
                coefficients=high_coefficients,
            )
        wet64 = np.clip(wet64, -1.0, 1.0)
        return wet64.astype(output_dtype, copy=False)

    rendered = stereo_samples
    for stage_index, stage in enumerate(plugin_chain, start=1):
        plugin_id = _coerce_str(stage.get("plugin_id")).strip().lower()
        params = _coerce_dict(stage.get("params"))
        stage_evidence_notes: list[str] | None = None

        if plugin_id == _GAIN_V0_PLUGIN_ID:
            gain_db = _coerce_float(params.get("gain_db"))
            if gain_db is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=f"{_GAIN_V0_PLUGIN_ID} requires numeric params.gain_db.",
                )
            bypass = _parse_bypass_for_stage(plugin_id=plugin_id, params=params)
            macro_mix, macro_mix_input = _parse_macro_mix_for_stage(
                plugin_id=plugin_id,
                params=params,
            )
            linear_gain = float(math.pow(10.0, gain_db / 20.0))
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; preserved dry stereo "
                    f"{processing_dtype_name} buffer without gain "
                    "or wet/dry mixing."
                )
            else:
                stage_what = "plugin stage applied"
                wet = np.multiply(
                    rendered,
                    processing_dtype(linear_gain),
                    dtype=processing_dtype,
                )
                wet = np.clip(wet, -1.0, 1.0).astype(processing_dtype, copy=False)
                if macro_mix <= 0.0:
                    stage_why = "macro_mix=0 selected dry signal path (linear blend endpoint)."
                elif macro_mix >= 1.0:
                    rendered = wet
                    stage_why = "macro_mix=1 selected fully wet signal path."
                else:
                    dry = rendered
                    rendered = np.add(
                        np.multiply(
                            dry,
                            processing_dtype(1.0 - macro_mix),
                            dtype=processing_dtype,
                        ),
                        np.multiply(
                            wet,
                            processing_dtype(macro_mix),
                            dtype=processing_dtype,
                        ),
                        dtype=processing_dtype,
                    )
                    rendered = np.clip(rendered, -1.0, 1.0).astype(
                        processing_dtype,
                        copy=False,
                    )
                    stage_why = (
                        "Applied gain_v0 wet path and macro_mix as a linear dry/wet blend."
                    )
            stage_metrics = [
                {"name": "stage_index", "value": stage_index},
                {"name": "gain_db", "value": gain_db},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ]
        elif plugin_id == _TILT_EQ_V0_PLUGIN_ID:
            tilt_db = _coerce_float(params.get("tilt_db"))
            if tilt_db is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=f"{_TILT_EQ_V0_PLUGIN_ID} requires numeric params.tilt_db.",
                )
            pivot_hz = _coerce_float(params.get("pivot_hz"))
            if pivot_hz is None:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=f"{_TILT_EQ_V0_PLUGIN_ID} requires numeric params.pivot_hz.",
                )
            bypass = _parse_bypass_for_stage(plugin_id=plugin_id, params=params)
            macro_mix, macro_mix_input = _parse_macro_mix_for_stage(
                plugin_id=plugin_id,
                params=params,
            )
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; preserved dry stereo "
                    f"{processing_dtype_name} buffer without tilt EQ "
                    "or wet/dry mixing."
                )
            else:
                stage_what = "plugin stage applied"
                wet = _apply_tilt_eq_v0(
                    signal=rendered,
                    sample_rate_hz=sample_rate_hz,
                    tilt_db=tilt_db,
                    pivot_hz=pivot_hz,
                    output_dtype=processing_dtype,
                )
                if macro_mix <= 0.0:
                    stage_why = "macro_mix=0 selected dry signal path (linear blend endpoint)."
                elif macro_mix >= 1.0:
                    rendered = wet
                    stage_why = "macro_mix=1 selected fully wet tilt_eq_v0 signal path."
                else:
                    dry = rendered
                    rendered = np.add(
                        np.multiply(
                            dry,
                            processing_dtype(1.0 - macro_mix),
                            dtype=processing_dtype,
                        ),
                        np.multiply(
                            wet,
                            processing_dtype(macro_mix),
                            dtype=processing_dtype,
                        ),
                        dtype=processing_dtype,
                    )
                    rendered = np.clip(rendered, -1.0, 1.0).astype(
                        processing_dtype,
                        copy=False,
                    )
                    stage_why = (
                        "Applied tilt_eq_v0 wet path and macro_mix as a linear dry/wet blend."
                    )
            stage_metrics = [
                {"name": "stage_index", "value": stage_index},
                {"name": "tilt_db", "value": tilt_db},
                {"name": "pivot_hz", "value": pivot_hz},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ]
        elif plugin_id == _SIMPLE_COMPRESSOR_V0_PLUGIN_ID:
            threshold_db = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="threshold_db",
            )
            ratio = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="ratio",
            )
            attack_ms = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="attack_ms",
            )
            release_ms = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="release_ms",
            )
            makeup_db = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="makeup_db",
            )
            detector_mode = _parse_simple_compressor_detector_mode(
                plugin_id=plugin_id,
                params=params,
            )
            bypass = _parse_bypass_for_stage(plugin_id=plugin_id, params=params)
            macro_mix, macro_mix_input = _parse_macro_mix_for_stage(
                plugin_id=plugin_id,
                params=params,
            )

            gr_approx_db = 0.0
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; preserved dry stereo "
                    f"{processing_dtype_name} buffer without compression."
                )
            else:
                stage_what = "plugin stage applied"
                wet, gr_approx_db = _apply_simple_compressor_v0(
                    signal=rendered,
                    sample_rate_hz=sample_rate_hz,
                    threshold_db=threshold_db,
                    ratio=ratio,
                    attack_ms=attack_ms,
                    release_ms=release_ms,
                    makeup_db=makeup_db,
                    detector_mode=detector_mode,
                    output_dtype=processing_dtype,
                )
                if macro_mix <= 0.0:
                    stage_why = (
                        "macro_mix=0 selected dry signal path after computing "
                        "feed-forward compression (no lookahead)."
                    )
                elif macro_mix >= 1.0:
                    rendered = wet
                    stage_why = (
                        "Applied feed-forward compression (no lookahead) with full wet mix."
                    )
                else:
                    dry = rendered
                    rendered = np.add(
                        np.multiply(
                            dry,
                            processing_dtype(1.0 - macro_mix),
                            dtype=processing_dtype,
                        ),
                        np.multiply(
                            wet,
                            processing_dtype(macro_mix),
                            dtype=processing_dtype,
                        ),
                        dtype=processing_dtype,
                    )
                    rendered = np.clip(rendered, -1.0, 1.0).astype(
                        processing_dtype,
                        copy=False,
                    )
                    stage_why = (
                        "Applied feed-forward compressor wet path and macro_mix as a "
                        "linear dry/wet blend (no lookahead)."
                    )

            stage_metrics = [
                {"name": "stage_index", "value": stage_index},
                {"name": "threshold_db", "value": threshold_db},
                {"name": "ratio", "value": ratio},
                {"name": "attack_ms", "value": attack_ms},
                {"name": "release_ms", "value": release_ms},
                {"name": "makeup_db", "value": makeup_db},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
                {"name": "gr_approx_db", "value": gr_approx_db},
            ]
            stage_evidence_notes = [f"detector_mode={detector_mode}"]
        elif plugin_id in {
            _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID,
            _MULTIBAND_EXPANDER_V0_PLUGIN_ID,
            _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID,
        }:
            threshold_db = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="threshold_db",
            )
            ratio = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="ratio",
            )
            attack_ms = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="attack_ms",
            )
            release_ms = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="release_ms",
            )
            makeup_db = _require_finite_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="makeup_db",
            )
            lookahead_ms = _optional_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="lookahead_ms",
                default_value=0.0,
                minimum_value=0.0,
                maximum_value=_MULTIBAND_MAX_LOOKAHEAD_MS,
            )
            slope_sensitivity = _optional_float_param(
                plugin_id=plugin_id,
                params=params,
                param_name="slope_sensitivity",
                default_value=0.7,
                minimum_value=0.0,
                maximum_value=1.0,
            )
            min_band_count = _optional_int_param(
                plugin_id=plugin_id,
                params=params,
                param_name="min_band_count",
                default_value=3,
                minimum_value=_MULTIBAND_MIN_BANDS,
                maximum_value=_MULTIBAND_MAX_BANDS,
            )
            max_band_count = _optional_int_param(
                plugin_id=plugin_id,
                params=params,
                param_name="max_band_count",
                default_value=6,
                minimum_value=_MULTIBAND_MIN_BANDS,
                maximum_value=_MULTIBAND_MAX_BANDS,
            )
            if max_band_count < min_band_count:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=(
                        f"{plugin_id} requires params.max_band_count >= params.min_band_count."
                    ),
                )
            oversampling = _optional_int_param(
                plugin_id=plugin_id,
                params=params,
                param_name="oversampling",
                default_value=1,
                minimum_value=1,
                maximum_value=_MULTIBAND_MAX_OVERSAMPLING,
            )
            detector_mode = _parse_multiband_detector_mode(
                plugin_id=plugin_id,
                params=params,
            )
            bypass = _parse_bypass_for_stage(plugin_id=plugin_id, params=params)
            macro_mix, macro_mix_input = _parse_macro_mix_for_stage(
                plugin_id=plugin_id,
                params=params,
            )

            if plugin_id == _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID:
                operation_mode = _MULTIBAND_OPERATION_COMPRESS
            elif plugin_id == _MULTIBAND_EXPANDER_V0_PLUGIN_ID:
                operation_mode = _MULTIBAND_OPERATION_EXPAND
            else:
                operation_mode = _MULTIBAND_OPERATION_AUTO

            multiband_summary: dict[str, Any] = {
                "band_count": 1.0,
                "slope_activity_db_per_oct": 0.0,
                "gr_approx_db": 0.0,
                "band_gr_approx_db": [0.0],
                "lookahead_samples": 0.0,
                "oversampling": float(oversampling),
                "operation_counts": {
                    _MULTIBAND_OPERATION_COMPRESS: 0.0,
                    _MULTIBAND_OPERATION_EXPAND: 0.0,
                },
                "bands": [],
            }
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; preserved dry stereo "
                    f"{processing_dtype_name} buffer without multiband dynamics."
                )
            else:
                stage_what = "plugin stage applied"
                wet, multiband_summary = _apply_multiband_dynamics_v0(
                    signal=rendered,
                    sample_rate_hz=sample_rate_hz,
                    threshold_db=threshold_db,
                    ratio=ratio,
                    attack_ms=attack_ms,
                    release_ms=release_ms,
                    makeup_db=makeup_db,
                    lookahead_ms=lookahead_ms,
                    detector_mode=detector_mode,
                    slope_sensitivity=slope_sensitivity,
                    min_band_count=min_band_count,
                    max_band_count=max_band_count,
                    operation_mode=operation_mode,
                    oversampling=oversampling,
                    max_theoretical_quality=max_theoretical_quality,
                    output_dtype=processing_dtype,
                )
                if macro_mix <= 0.0:
                    stage_why = (
                        "macro_mix=0 selected dry signal path after multiband analysis."
                    )
                elif macro_mix >= 1.0:
                    rendered = wet
                    stage_why = (
                        "Applied multiband dynamics with full wet mix using slope-driven bands."
                    )
                else:
                    dry = rendered
                    rendered = np.add(
                        np.multiply(
                            dry,
                            processing_dtype(1.0 - macro_mix),
                            dtype=processing_dtype,
                        ),
                        np.multiply(
                            wet,
                            processing_dtype(macro_mix),
                            dtype=processing_dtype,
                        ),
                        dtype=processing_dtype,
                    )
                    rendered = np.clip(rendered, -1.0, 1.0).astype(
                        processing_dtype,
                        copy=False,
                    )
                    stage_why = (
                        "Applied multiband dynamics wet path and macro_mix as a "
                        "linear dry/wet blend."
                    )

            stage_metrics = [
                {"name": "stage_index", "value": stage_index},
                {"name": "threshold_db", "value": threshold_db},
                {"name": "ratio", "value": ratio},
                {"name": "attack_ms", "value": attack_ms},
                {"name": "release_ms", "value": release_ms},
                {"name": "makeup_db", "value": makeup_db},
                {"name": "lookahead_ms", "value": lookahead_ms},
                {"name": "slope_sensitivity", "value": slope_sensitivity},
                {"name": "min_band_count", "value": float(min_band_count)},
                {"name": "max_band_count", "value": float(max_band_count)},
                {"name": "band_count", "value": float(multiband_summary.get("band_count", 1.0))},
                {
                    "name": "slope_activity_db_per_oct",
                    "value": float(multiband_summary.get("slope_activity_db_per_oct", 0.0)),
                },
                {"name": "gr_approx_db", "value": float(multiband_summary.get("gr_approx_db", 0.0))},
                {"name": "lookahead_samples", "value": float(multiband_summary.get("lookahead_samples", 0.0))},
                {"name": "oversampling", "value": float(multiband_summary.get("oversampling", float(oversampling)))},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ]
            band_gr_metrics = multiband_summary.get("band_gr_approx_db")
            if isinstance(band_gr_metrics, list):
                for band_index, band_value in enumerate(band_gr_metrics, start=1):
                    if not isinstance(band_value, (int, float)):
                        continue
                    stage_metrics.append(
                        {
                            "name": f"band_{band_index:02d}_gr_approx_db",
                            "value": float(band_value),
                        }
                    )
            stage_evidence_notes = [
                f"detector_mode={detector_mode}",
                f"operation_mode={operation_mode}",
                (
                    "operation_counts="
                    f"compress:{float(multiband_summary.get('operation_counts', {}).get(_MULTIBAND_OPERATION_COMPRESS, 0.0)):.0f},"
                    f"expand:{float(multiband_summary.get('operation_counts', {}).get(_MULTIBAND_OPERATION_EXPAND, 0.0)):.0f}"
                ),
            ]
        else:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    "Unsupported plugin_chain stage. "
                    f"stage={stage_index}, plugin_id={plugin_id or '(missing)'}"
                ),
            )
        stage_token = f"plugin_chain.stage.{stage_index:03d}.{plugin_id}"
        stage_evidence: dict[str, Any] = {
            "codes": ["RENDER.RUN.PLUGIN.STAGE_APPLIED"],
            "ids": [plugin_id],
            "metrics": stage_metrics,
        }
        if stage_evidence_notes:
            stage_evidence["notes"] = stage_evidence_notes
        step_events.append(
            {
                "kind": "action",
                "scope": "render",
                "what": stage_what,
                "why": stage_why,
                "where": [source_posix, stage_token],
                "confidence": None,
                "evidence": stage_evidence,
            }
        )

    _write_stereo_pcm_wav_from_float_samples(
        float_samples=rendered,
        output_path=output_path,
        sample_rate_hz=sample_rate_hz,
        bit_depth=bit_depth,
    )
    step_events.append(
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain output written",
            "why": (
                "Wrote deterministic PCM WAV from plugin-chain "
                f"{processing_dtype_name} output buffer."
            ),
            "where": [output_posix],
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.OUTPUT_WRITTEN"],
                "paths": [output_posix],
                "metrics": [
                    {"name": "bit_depth", "value": bit_depth},
                    {"name": "frame_count", "value": frame_count},
                    {"name": "stage_count", "value": len(plugin_chain)},
                ],
            },
        }
    )
    return step_events


def _read_stereo_source_samples(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
    dtype: Any,
) -> Any:
    import numpy as np

    requested_dtype = np.dtype(dtype)
    if requested_dtype not in {np.dtype(np.float32), np.dtype(np.float64)}:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "Unsupported plugin-chain processing dtype: "
                f"{requested_dtype.name}. Expected float32 or float64."
            ),
        )

    source_extension = path.suffix.lower()
    float_samples_iter: Iterator[list[float]]
    if source_extension in _WAV_EXTENSIONS:
        float_samples_iter = iter_wav_float64_samples(
            path,
            error_context="render-run plugin-chain decode",
        )
    else:
        if ffmpeg_cmd is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required to decode non-WAV source audio.",
            )
        float_samples_iter = iter_ffmpeg_float64_samples(path, ffmpeg_cmd)

    chunks: list[Any] = []
    for float_samples in float_samples_iter:
        if len(float_samples) % 2 != 0:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message="Decoded sample stream is not frame-aligned for stereo.",
            )
        if not float_samples:
            continue
        chunk = np.asarray(float_samples, dtype=requested_dtype).reshape(-1, 2)
        chunks.append(chunk)
    if not chunks:
        return np.zeros((0, 2), dtype=requested_dtype)
    return np.concatenate(chunks, axis=0).astype(requested_dtype, copy=False)


def _write_stereo_pcm_wav_from_float_samples(
    *,
    float_samples: Any,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
) -> None:
    import numpy as np

    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    samples = np.asarray(float_samples, dtype=np.float64)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "Plugin-chain runner expects a stereo float32/float64 sample matrix."
            ),
        )
    interleaved = samples.reshape(-1)
    pcm_bytes = _float_samples_to_pcm_bytes(interleaved, bit_depth)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm_bytes)


def _float_samples_to_pcm_bytes(float_samples: Any, bit_depth: int) -> bytes:
    import numpy as np

    samples64 = np.asarray(float_samples, dtype=np.float64)

    if bit_depth == 16:
        scaled = np.rint(samples64 * float(2**15))
        clamped = np.clip(scaled, -32768.0, 32767.0).astype("<i2")
        return clamped.tobytes()
    if bit_depth == 24:
        scaled = np.rint(samples64 * float(2**23))
        clamped = np.clip(scaled, -8388608.0, 8388607.0).astype(np.int32)
        unsigned = (clamped & 0xFFFFFF).astype(np.uint32)
        data = np.empty(unsigned.size * 3, dtype=np.uint8)
        data[0::3] = (unsigned & 0xFF).astype(np.uint8)
        data[1::3] = ((unsigned >> 8) & 0xFF).astype(np.uint8)
        data[2::3] = ((unsigned >> 16) & 0xFF).astype(np.uint8)
        return data.tobytes()
    if bit_depth == 32:
        scaled = np.rint(samples64 * float(2**31))
        clamped = np.clip(scaled, -2147483648.0, 2147483647.0).astype("<i4")
        return clamped.tobytes()
    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
        message=f"Unsupported output bit depth: {bit_depth}",
    )


def _stereo_jobs_or_raise(plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = plan_payload.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        job_count = len(jobs) if isinstance(jobs, list) else 0
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
            message=(
                "PR71 render-run requires at least one stereo job. "
                f"job_count={job_count}"
            ),
        )

    normalized_jobs: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message="PR71 render-run supports only object job entries.",
            )
        job_id = _coerce_str(job.get("job_id")).strip() or f"JOB.{index:03d}"

        target_layout_id = _coerce_str(job.get("target_layout_id")).strip()
        if target_layout_id != _STEREO_LAYOUT_ID:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message=(
                    "PR71 render-run only supports stereo target variants. "
                    f"job_id={job_id}, target_layout_id={target_layout_id or '(missing)'}"
                ),
            )

        routing_plan_path = _coerce_str(job.get("routing_plan_path")).strip()
        if routing_plan_path:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                message=(
                    "PR71 render-run does not support routing_plan_path yet. "
                    f"job_id={job_id}, routing_plan_path={routing_plan_path}"
                ),
            )

        downmix_routes = job.get("downmix_routes")
        if isinstance(downmix_routes, list) and downmix_routes:
            first_route = downmix_routes[0]
            if not isinstance(first_route, dict):
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                    message="PR71 render-run requires object downmix_routes entries.",
                )
            route_from = _coerce_str(first_route.get("from_layout_id")).strip()
            route_to = _coerce_str(first_route.get("to_layout_id")).strip()
            route_kind = _coerce_str(first_route.get("kind")).strip()
            if route_from != _STEREO_LAYOUT_ID or route_to != _STEREO_LAYOUT_ID:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                    message=(
                        "PR71 render-run supports only identity stereo routes. "
                        f"job_id={job_id}, route={route_from or '(missing)'}->{route_to or '(missing)'}"
                    ),
                )
            if route_kind and route_kind != "direct":
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DOWNMIX_SCOPE_UNSUPPORTED,
                    message=(
                        "PR71 render-run supports only direct stereo routes. "
                        f"job_id={job_id}, route_kind={route_kind}"
                    ),
                )
        normalized_jobs.append(job)

    normalized_jobs.sort(key=lambda item: _coerce_str(item.get("job_id")).strip())
    return normalized_jobs


def _resolve_single_source_or_raise(scene_payload: dict[str, Any]) -> Path:
    source_payload = scene_payload.get("source")
    if not isinstance(source_payload, dict):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message="scene.source must be an object with stems_dir.",
        )
    stems_dir_text = _coerce_str(source_payload.get("stems_dir")).strip()
    stems_dir = Path(stems_dir_text) if stems_dir_text else None
    if stems_dir is None or not stems_dir.is_absolute():
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir must be an absolute path for PR52 render-run. "
                f"stems_dir={stems_dir_text or '(missing)'}"
            ),
        )
    if not stems_dir.exists() or not stems_dir.is_dir():
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir must exist and be a directory. "
                f"stems_dir={stems_dir.resolve().as_posix()}"
            ),
        )

    candidates = _audio_source_candidates(stems_dir)
    if not candidates:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_MISSING,
            message=(
                "No source audio files were found in stems_dir for PR52 render-run. "
                f"stems_dir={stems_dir.resolve().as_posix()}"
            ),
        )
    if len(candidates) != 1:
        rel_paths = [item.relative_to(stems_dir).as_posix() for item in candidates]
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_COUNT_UNSUPPORTED,
            message=(
                "PR52 render-run requires exactly one source audio file in stems_dir. "
                f"found={len(candidates)} files: {', '.join(rel_paths)}"
            ),
        )
    return candidates[0]


def _audio_source_candidates(stems_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for item in stems_dir.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix.lower() in _SOURCE_EXTENSIONS:
            candidates.append(item)
    candidates.sort(key=lambda path: path.relative_to(stems_dir).as_posix())
    return candidates


def _read_source_metadata_or_raise(source_path: Path) -> dict[str, Any]:
    extension = source_path.suffix.lower()
    if extension in _LOSSY_EXTENSIONS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
            message=(
                "PR52 render-run supports only lossless source audio "
                "(wav/flac/wv/aiff/alac). "
                f"source={source_path.resolve().as_posix()}"
            ),
        )
    if extension in _WAV_EXTENSIONS:
        try:
            return read_wav_metadata(source_path)
        except ValueError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=f"Failed to read WAV metadata: {exc}",
            ) from exc
    if extension in _FFMPEG_EXTENSIONS:
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required for non-WAV source decoding.",
            )
        try:
            metadata = read_metadata(source_path)
        except (NotImplementedError, ValueError) as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=f"Failed to read source metadata: {exc}",
            ) from exc
        if extension == ".m4a":
            codec_name = _coerce_str(metadata.get("codec_name")).strip().lower()
            if codec_name != "alac":
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
                    message=(
                        "PR52 render-run only supports lossless ALAC for .m4a inputs. "
                        f"codec_name={codec_name or '(missing)'}"
                    ),
                )
        return metadata

    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
        message=(
            "Unsupported source extension for PR52 render-run. "
            f"source={source_path.resolve().as_posix()}"
        ),
    )


def _validate_source_layout_or_raise(source_metadata: dict[str, Any]) -> None:
    channels = _coerce_int(source_metadata.get("channels"))
    if channels != 2:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_LAYOUT_UNSUPPORTED,
            message=(
                "PR52 render-run requires a stereo source (2 channels). "
                f"source_channels={channels if channels is not None else '(missing)'}"
            ),
        )

    sample_rate_hz = _coerce_int(source_metadata.get("sample_rate_hz"))
    if sample_rate_hz is None or sample_rate_hz <= 0:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
            message="Source metadata is missing a valid sample_rate_hz.",
        )


def _resolve_output_bit_depth(
    *,
    requested_bit_depth: int | None,
    source_bit_depth: int | None,
) -> int:
    if requested_bit_depth is not None and requested_bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "Requested bit_depth is unsupported for PR52 render-run. "
                f"bit_depth={requested_bit_depth}"
            ),
        )
    if requested_bit_depth in _BIT_DEPTHS:
        return requested_bit_depth
    if source_bit_depth in _BIT_DEPTHS:
        return source_bit_depth
    return 24


def _job_output_formats_or_raise(job: dict[str, Any]) -> list[str]:
    raw_output_formats = job.get("output_formats")
    selected: set[str] = set()
    if isinstance(raw_output_formats, list):
        for item in raw_output_formats:
            normalized = _coerce_str(item).strip().lower()
            if not normalized:
                continue
            if normalized not in _OUTPUT_FORMAT_ORDER:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED,
                    message=(
                        "Unsupported output format requested in render plan job. "
                        f"output_format={normalized}"
                    ),
                )
            selected.add(normalized)
    if not selected:
        selected.add("wav")
    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _planned_outputs_by_format(job: dict[str, Any]) -> dict[str, str]:
    outputs = job.get("outputs")
    if not isinstance(outputs, list):
        return {}
    by_format: dict[str, str] = {}
    normalized_rows: list[tuple[str, str]] = []
    for row in outputs:
        if not isinstance(row, dict):
            continue
        output_format = _coerce_str(row.get("format")).strip().lower()
        output_path = _coerce_str(row.get("path")).strip()
        if not output_format or not output_path:
            continue
        normalized_rows.append((output_format, output_path))
    normalized_rows.sort(key=lambda item: (item[0], item[1]))
    for output_format, output_path in normalized_rows:
        by_format.setdefault(output_format, output_path)
    return by_format


def _scene_anchor_root(*, request_scene_path: str, scene_path: Path) -> Path | None:
    raw = request_scene_path.strip()
    if not raw:
        return None
    if _is_absolute_posix_path(raw):
        return None
    parts = PurePosixPath(raw).parts
    anchor = scene_path.resolve()
    for _ in parts:
        parent = anchor.parent
        if parent == anchor:
            return None
        anchor = parent
    return anchor


def _is_absolute_posix_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    return len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/"


def _resolve_output_path(
    *,
    raw_path: str,
    scene_anchor: Path | None,
    report_dir: Path,
    fallback: Path | None = None,
) -> Path:
    normalized_raw = raw_path.strip()
    if not normalized_raw:
        if fallback is not None:
            return fallback
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OUTPUT_FORMAT_UNSUPPORTED,
            message="Render plan output path is missing.",
        )

    normalized = normalized_raw.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if _is_absolute_posix_path(normalized):
        return Path(normalized)

    relative_parts = [part for part in pure.parts if part not in {"", "."}]
    relative_path = Path(*relative_parts) if relative_parts else Path("mix.wav")
    if scene_anchor is not None:
        return scene_anchor / relative_path
    return report_dir / relative_path


def _fallback_output_path(
    *,
    report_dir: Path,
    job_id: str,
    output_format: str,
) -> Path:
    suffix_by_format = {
        "wav": "wav",
        "flac": "flac",
        "wv": "wv",
        "aiff": "aiff",
        "alac": "m4a",
    }
    suffix = suffix_by_format.get(output_format, output_format)
    slug = job_id.replace(".", "_").lower()
    return report_dir / "render_outputs" / slug / f"mix.{suffix}"


def _intermediate_wav_path(*, report_dir: Path, job_id: str) -> Path:
    slug = job_id.replace(".", "_").lower()
    return report_dir / _INTERMEDIATE_ROOT / f"{slug}.wav"


def _write_stereo_wav(
    *,
    float_samples_iter: Iterator[list[float]],
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
) -> None:
    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)

        for float_samples in float_samples_iter:
            if len(float_samples) % 2 != 0:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                    message="Decoded sample stream is not frame-aligned for stereo.",
                )
            int_samples = _dithered_pcm_samples(float_samples, bit_depth, rng)
            handle.writeframes(_int_samples_to_bytes(int_samples, bit_depth))


def _dithered_pcm_samples(
    float_samples: list[float],
    bit_depth: int,
    rng: random.Random,
) -> list[int]:
    divisor = float(2 ** (bit_depth - 1))
    min_value = -int(divisor)
    max_value = int(divisor) - 1
    output: list[int] = []
    for sample in float_samples:
        noise = (rng.random() - rng.random()) / divisor
        value = _clamp_sample(sample + noise)
        scaled = int(round(value * divisor))
        if scaled < min_value:
            scaled = min_value
        elif scaled > max_value:
            scaled = max_value
        output.append(scaled)
    return output


def _clamp_sample(sample: float) -> float:
    if sample < -1.0:
        return -1.0
    if sample > _FLOAT_MAX:
        return _FLOAT_MAX
    return sample


def _int_samples_to_bytes(samples: list[int], bit_depth: int) -> bytes:
    if bit_depth == 16:
        return struct.pack(f"<{len(samples)}h", *samples)
    if bit_depth == 24:
        data = bytearray(len(samples) * 3)
        for index, sample in enumerate(samples):
            value = sample & 0xFFFFFF
            offset = index * 3
            data[offset : offset + 3] = bytes(
                (
                    value & 0xFF,
                    (value >> 8) & 0xFF,
                    (value >> 16) & 0xFF,
                )
            )
        return bytes(data)
    if bit_depth == 32:
        return struct.pack(f"<{len(samples)}i", *samples)
    raise RenderRunRefusalError(
        issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
        message=f"Unsupported output bit depth: {bit_depth}",
    )


def _path_arg(path: Path) -> str:
    return path.resolve().as_posix()


def _wav_codec_for_bit_depth(bit_depth: int) -> str:
    codecs = {
        16: "pcm_s16le",
        24: "pcm_s24le",
        32: "pcm_s32le",
    }
    codec = codecs.get(bit_depth)
    if codec is None:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )
    return codec


def _normalize_wav_for_determinism(
    *,
    ffmpeg_cmd: Sequence[str],
    wav_path: Path,
    bit_depth: int,
    command_rows: list[dict[str, Any]],
) -> None:
    deterministic_flags = list(ffmpeg_determinism_flags(for_wav=True))
    tmp_path = wav_path.with_suffix(wav_path.suffix + ".tmp")
    command = list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        _path_arg(wav_path),
        *deterministic_flags,
        "-f",
        "wav",
        "-c:a",
        _wav_codec_for_bit_depth(bit_depth),
        _path_arg(tmp_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        if message:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
                message=f"ffmpeg WAV normalization failed: {message}",
            )
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
            message=f"ffmpeg WAV normalization failed with exit code {completed.returncode}",
        )

    try:
        tmp_path.replace(wav_path)
    except OSError as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_ENCODE_FAILED,
            message=f"Failed to finalize deterministic WAV output: {exc}",
        ) from exc
    command_rows.append(
        {
            "args": command,
            "determinism_flags": deterministic_flags,
        }
    )


def _output_paths_from_rows(output_files: list[dict[str, Any]]) -> list[Path]:
    deduped: dict[str, Path] = {}
    for row in output_files:
        if not isinstance(row, dict):
            continue
        raw_path = _coerce_str(row.get("file_path")).strip()
        if not raw_path:
            continue
        resolved = Path(raw_path).resolve()
        deduped.setdefault(resolved.as_posix(), resolved)
    return [deduped[path] for path in sorted(deduped.keys())]


def _output_file_payload(
    *,
    output_path: Path,
    output_format: str,
    sample_rate_hz: int,
    bit_depth: int,
) -> dict[str, Any]:
    sha256_hex = sha256_file(output_path)
    return {
        "file_path": output_path.resolve().as_posix(),
        "format": output_format,
        "channel_count": 2,
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": bit_depth,
        "sha256": sha256_hex,
    }


def _output_sort_key(output_format: str) -> tuple[int, str]:
    try:
        return (_OUTPUT_FORMAT_ORDER.index(output_format), output_format)
    except ValueError:
        return (len(_OUTPUT_FORMAT_ORDER), output_format)
