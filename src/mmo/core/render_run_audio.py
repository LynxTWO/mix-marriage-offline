"""Deterministic offline audio rendering for ``render-run``."""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import struct
import subprocess
import wave
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

from mmo.core.media_tags import TagBag, empty_tag_bag, merge_tag_bags, tag_bag_from_mapping
from mmo.core.portable_refs import is_absolute_posix_path, resolve_posix_ref
from mmo.core.render_execute import resolve_ffmpeg_version
from mmo.core.render_reporting import build_render_report_from_plan
from mmo.core.tag_export import build_ffmpeg_tag_export_args, metadata_receipt_mapping
from mmo.core.trace_metadata import build_trace_ixml_payload, build_trace_metadata, trace_tag_bag_from_metadata
from mmo.dsp.buffer import AudioBufferF64
from mmo.dsp.backends.ffmpeg_decode import (
    build_ffmpeg_decode_command,
    iter_ffmpeg_float64_samples,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import read_metadata
from mmo.dsp.io import read_wav_metadata, sha256_file, write_wav_ixml_chunk
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.plugins.base import (
    PluginContext,
    PluginEvidenceCollector,
    PluginValidationError,
)
from mmo.dsp.plugins.registry import get_stereo_plugin
from mmo.dsp.process_context import build_process_context
from mmo.plugins.runtime_contract import (
    PluginPurityViolationError,
    invoke_with_purity_guard,
    purity_contract_from_capabilities,
)
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
_FFMPEG_EXTENSIONS = frozenset({".flac", ".wv", ".aif", ".aiff", ".ape", ".m4a"})
_LOSSY_EXTENSIONS = frozenset({".mp3", ".aac", ".ogg", ".opus"})
_SOURCE_EXTENSIONS = _WAV_EXTENSIONS | _FFMPEG_EXTENSIONS | _LOSSY_EXTENSIONS
_BIT_DEPTHS = frozenset({16, 24, 32})
_INTERMEDIATE_ROOT = ".mmo_tmp/render_run"
_FLOAT_MAX = math.nextafter(1.0, 0.0)
_STEREO_CHANNEL_ORDER = ("SPK.L", "SPK.R")
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
ISSUE_RENDER_RUN_MIX_INPUT_SAMPLE_RATE_MISMATCH = (
    "ISSUE.RENDER.RUN.MIX_INPUT_SAMPLE_RATE_MISMATCH"
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

# Plugin IDs whose detector_mode param is validated statically (before numpy).
_DETECTOR_MODE_PLUGIN_IDS: frozenset[str] = frozenset({
    _SIMPLE_COMPRESSOR_V0_PLUGIN_ID,
    _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID,
    _MULTIBAND_EXPANDER_V0_PLUGIN_ID,
    _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID,
})

# Plugin IDs that require max_theoretical_quality=True when oversampling > 1.
_OVERSAMPLING_QUALITY_PLUGIN_IDS: frozenset[str] = frozenset({
    _MULTIBAND_COMPRESSOR_V0_PLUGIN_ID,
    _MULTIBAND_EXPANDER_V0_PLUGIN_ID,
    _MULTIBAND_DYNAMIC_AUTO_V0_PLUGIN_ID,
})


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
    from mmo.core.plugin_loader import (  # noqa: WPS433
        PLUGIN_DIR_ENV_VAR,
        default_user_plugins_dir,
    )
    from mmo.resources import plugins_dir as bundled_plugins_dir  # noqa: WPS433

    candidates: list[Path] = []

    candidates.append((Path.cwd() / "plugins").resolve())
    raw_external_plugins = os.environ.get(PLUGIN_DIR_ENV_VAR, "").strip()
    if raw_external_plugins:
        candidates.append(Path(raw_external_plugins).expanduser().resolve())
    else:
        candidates.append(default_user_plugins_dir().expanduser().resolve())

    bundled_plugins = bundled_plugins_dir()
    if bundled_plugins is not None:
        candidates.append(bundled_plugins)

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


def _plugin_purity_contract_for_impl(plugin_impl: Any) -> Any:
    contract = purity_contract_from_capabilities(
        getattr(plugin_impl, "plugin_capabilities", None),
    )
    if contract is not None:
        return contract
    return getattr(plugin_impl, "plugin_purity_contract", None)


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
    options = _coerce_dict(request_payload.get("options"))
    scene_anchor = _scene_anchor_root(
        request_scene_path=_coerce_str(request_payload.get("scene_path")),
        scene_path=scene_path,
    )
    report_dir = report_out_path.resolve().parent

    mix_inputs = _mix_inputs_from_request(request_payload)
    resolved_mix_inputs: list[dict[str, Any]] | None = None
    mix_inputs_report_notes: list[str] = []
    source_input_paths: list[Path] = []
    source_bit_depth: int | None = None
    source_channel_count: int | None = None
    source_tag_bag: TagBag = empty_tag_bag()

    if mix_inputs is None:
        source_path = _resolve_single_source_or_raise(
            scene_payload,
            scene_path=scene_path,
        )
        source_metadata = _read_source_metadata_or_raise(source_path)
        _validate_source_layout_or_raise(source_metadata)
        source_rate_hz = _coerce_int(source_metadata.get("sample_rate_hz")) or 0
        source_bit_depth = _coerce_int(source_metadata.get("bits_per_sample"))
        source_channel_count = (
            _coerce_int(source_metadata.get("channel_count"))
            or _coerce_int(source_metadata.get("channels"))
        )
        source_tag_bag = tag_bag_from_mapping(source_metadata.get("tags"))
        source_input_paths = [source_path.resolve()]
    else:
        (
            resolved_mix_inputs,
            source_rate_hz,
            source_bit_depth,
        ) = _resolve_mix_inputs_with_metadata_or_raise(
            mix_inputs=mix_inputs,
            scene_anchor=scene_anchor,
            report_dir=report_dir,
        )
        source_path = Path(resolved_mix_inputs[0]["path"])
        source_input_paths = [
            Path(mix_input["path"]).resolve()
            for mix_input in resolved_mix_inputs
            if isinstance(mix_input.get("path"), Path)
        ]
        source_tag_bag = merge_tag_bags(
            [
                mix_input.get("tag_bag", empty_tag_bag())
                for mix_input in resolved_mix_inputs
                if isinstance(mix_input.get("tag_bag"), TagBag)
            ]
        )
        mix_inputs_report_notes = _mix_inputs_report_notes(
            mix_inputs=resolved_mix_inputs,
            headroom_gain=_mix_inputs_headroom_gain(resolved_mix_inputs),
        )

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
        source_bit_depth=source_bit_depth,
    )
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
        trace_context = {
            **_coerce_dict(job),
            "request_payload": request_payload,
            "plan_payload": plan_payload,
            "scene_payload": scene_payload,
            "options": _coerce_dict(request_payload.get("options")),
        }
        trace_metadata = build_trace_metadata(trace_context)
        trace_tag_bag = trace_tag_bag_from_metadata(trace_metadata)
        trace_embedded_keys = sorted(trace_tag_bag.normalized.keys())
        metadata_plan_by_format: dict[str, dict[str, Any]] = {}
        for output_format in output_formats:
            export_tag_bag = (
                source_tag_bag
                if output_format == "wav"
                else merge_tag_bags((source_tag_bag, trace_tag_bag))
            )
            (
                ffmpeg_metadata_args,
                embedded_keys,
                skipped_keys,
                metadata_warnings,
            ) = build_ffmpeg_tag_export_args(export_tag_bag, output_format)
            metadata_plan_by_format[output_format] = {
                "ffmpeg_metadata_args": ffmpeg_metadata_args,
                "embedded_keys": embedded_keys,
                "skipped_keys": skipped_keys,
                "warnings": metadata_warnings,
            }

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
        mix_inputs_active = isinstance(resolved_mix_inputs, list)
        needs_ffmpeg_decode = (
            any(bool(mix_input.get("needs_ffmpeg_decode")) for mix_input in resolved_mix_inputs)
            if mix_inputs_active
            else (source_extension in _FFMPEG_EXTENSIONS)
        )
        needs_ffmpeg_encode = any(fmt != "wav" for fmt in output_formats)
        wav_metadata_args = list(
            metadata_plan_by_format.get("wav", {}).get("ffmpeg_metadata_args") or []
        )
        needs_ffmpeg_for_trace = keep_wav_output and capture_execute_trace
        needs_ffmpeg_for_wav_metadata = keep_wav_output and bool(wav_metadata_args)
        exact_copy_plugin_chain_wav = (
            plugin_chain_enabled
            and not mix_inputs_active
            and _plugin_chain_is_total_noop(plugin_chain)
            and source_extension in _WAV_EXTENSIONS
            and keep_wav_output
            and not needs_ffmpeg_encode
            and not capture_execute_trace
            and not wav_metadata_args
            and source_bit_depth == output_bit_depth
            and source_channel_count == 2
        )
        if (
            needs_ffmpeg_decode
            or needs_ffmpeg_encode
            or needs_ffmpeg_for_trace
            or needs_ffmpeg_for_wav_metadata
        ):
            ffmpeg_cmd_for_decode = resolve_ffmpeg_cmd()
            ffmpeg_cmd_for_encode = ffmpeg_cmd_for_decode
            if (
                ffmpeg_cmd_for_decode is None
                and (needs_ffmpeg_decode or needs_ffmpeg_encode or needs_ffmpeg_for_trace)
            ):
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
            if mix_inputs_active:
                if resolved_mix_inputs is None:
                    raise RenderRunRefusalError(
                        issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                        message="Internal mix_inputs normalization failed.",
                    )
                if capture_execute_trace:
                    ffmpeg_command_rows.extend(
                        _mix_inputs_decode_command_rows(
                            mix_inputs=resolved_mix_inputs,
                            ffmpeg_cmd_for_decode=ffmpeg_cmd_for_decode,
                        )
                    )
                mixed_interleaved, _ = _mix_inputs_interleaved_samples_or_raise(
                    mix_inputs=resolved_mix_inputs,
                    ffmpeg_cmd_for_decode=ffmpeg_cmd_for_decode,
                )
                if plugin_chain_enabled:
                    job_plugin_step_events = _render_wav_with_plugin_chain(
                        source_path=source_path,
                        output_path=wav_path,
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                        plugin_chain=plugin_chain,
                        ffmpeg_cmd_for_decode=ffmpeg_cmd_for_decode,
                        max_theoretical_quality=max_theoretical_quality,
                        force_float64_default=plugin_chain_force_float64,
                        source_samples_interleaved=mixed_interleaved,
                        source_evidence_paths=[
                            input_path.resolve().as_posix()
                            for input_path in source_input_paths
                        ],
                    )
                else:
                    _write_stereo_wav(
                        float_samples_iter=_iter_interleaved_stereo_chunks(
                            mixed_interleaved,
                        ),
                        output_path=wav_path,
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                    )
            elif plugin_chain_enabled:
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
                if exact_copy_plugin_chain_wav:
                    job_plugin_step_events = _copy_source_wav_for_noop_plugin_chain(
                        source_path=source_path,
                        output_path=wav_path,
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                        plugin_chain=plugin_chain,
                        max_theoretical_quality=max_theoretical_quality,
                        force_float64_default=plugin_chain_force_float64,
                    )
                else:
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
            wav_plan = metadata_plan_by_format.get("wav", {})
            wav_metadata_args = list(wav_plan.get("ffmpeg_metadata_args") or [])
            wav_embedded_keys = list(wav_plan.get("embedded_keys") or [])
            wav_skipped_keys = list(wav_plan.get("skipped_keys") or [])
            wav_warnings = list(wav_plan.get("warnings") or [])
            wav_trace_embedded_keys = (
                [] if plugin_chain_enabled else list(trace_embedded_keys)
            )

            if keep_wav_output and (capture_execute_trace or wav_metadata_args):
                if ffmpeg_cmd_for_encode is None:
                    if capture_execute_trace:
                        raise RenderRunRefusalError(
                            issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                            message=(
                                "ffmpeg is required to normalize WAV output metadata "
                                "for deterministic execution tracing."
                            ),
                        )
                    wav_skipped_keys.extend(wav_embedded_keys)
                    wav_embedded_keys = []
                    wav_warnings.append(
                        "WAV metadata embedding skipped: ffmpeg not available."
                    )
                else:
                    _normalize_wav_for_determinism(
                        ffmpeg_cmd=ffmpeg_cmd_for_encode,
                        wav_path=wav_path,
                        bit_depth=output_bit_depth,
                        command_rows=ffmpeg_command_rows,
                        metadata_args=wav_metadata_args,
                    )
            if keep_wav_output and not plugin_chain_enabled:
                write_wav_ixml_chunk(wav_path, build_trace_ixml_payload(trace_metadata))

            if keep_wav_output:
                output_files.append(
                    _output_file_payload(
                        output_path=wav_path,
                        output_format="wav",
                        sample_rate_hz=source_rate_hz,
                        bit_depth=output_bit_depth,
                        metadata_receipt=metadata_receipt_mapping(
                            output_container_format_id="wav",
                            embedded_keys=wav_embedded_keys + wav_trace_embedded_keys,
                            skipped_keys=wav_skipped_keys,
                            warnings=wav_warnings,
                        ),
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
                    metadata_plan = metadata_plan_by_format.get(output_format, {})
                    metadata_args = list(metadata_plan.get("ffmpeg_metadata_args") or [])
                    transcode_command_rows: list[list[str]] | None = []
                    if not capture_execute_trace:
                        transcode_command_rows = None
                    transcode_wav_to_format(
                        ffmpeg_cmd_for_encode,
                        wav_path,
                        target_path,
                        output_format,
                        metadata_args=metadata_args,
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
                        metadata_receipt=metadata_receipt_mapping(
                            output_container_format_id=output_format,
                            embedded_keys=list(
                                metadata_plan_by_format.get(output_format, {}).get(
                                    "embedded_keys",
                                )
                                or []
                            ),
                            skipped_keys=list(
                                metadata_plan_by_format.get(output_format, {}).get(
                                    "skipped_keys",
                                )
                                or []
                            ),
                            warnings=list(
                                metadata_plan_by_format.get(output_format, {}).get(
                                    "warnings",
                                )
                                or []
                            ),
                        ),
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
        report_notes = ["reason: rendered"]
        if mix_inputs_active:
            report_notes.append(f"source_files: {len(source_input_paths)}")
            report_notes.append("source_layout_id: LAYOUT.2_0")
            report_notes.append(f"target_layout_id: {target_layout_id}")
            report_notes.extend(mix_inputs_report_notes)
        else:
            report_notes.append(f"source_file: {source_path.resolve().as_posix()}")
            report_notes.append("source_layout_id: LAYOUT.2_0")
            report_notes.append(f"target_layout_id: {target_layout_id}")
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
                "input_paths": list(source_input_paths),
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
                    "input_paths": list(source_input_paths),
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


def _mix_inputs_from_request(
    request_payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    options = _coerce_dict(request_payload.get("options"))
    if "mix_inputs" not in options:
        return None

    raw_mix_inputs = options.get("mix_inputs")
    if not isinstance(raw_mix_inputs, list) or not raw_mix_inputs:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message="options.mix_inputs must be a non-empty array when provided.",
        )

    normalized: list[dict[str, Any]] = []
    allowed_keys = {"path", "gain_db", "pan", "mute", "role"}
    for index, raw_input in enumerate(raw_mix_inputs, start=1):
        if not isinstance(raw_input, dict):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=f"options.mix_inputs[{index}] must be an object.",
            )

        unknown_keys = sorted(set(raw_input.keys()) - allowed_keys)
        if unknown_keys:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=(
                    f"options.mix_inputs[{index}] has unknown key(s): "
                    f"{', '.join(unknown_keys)}."
                ),
            )

        path_text = _coerce_str(raw_input.get("path")).strip()
        if not path_text:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=f"options.mix_inputs[{index}].path is required.",
            )
        if "\\" in path_text:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=(
                    f"options.mix_inputs[{index}].path must use forward slashes only. "
                    f"path={path_text!r}"
                ),
            )

        gain_db_raw = raw_input.get("gain_db", 0.0)
        gain_db = _coerce_float(gain_db_raw)
        if gain_db is None or not math.isfinite(gain_db):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=f"options.mix_inputs[{index}].gain_db must be a finite number.",
            )

        pan_raw = raw_input.get("pan", 0.0)
        pan = _coerce_float(pan_raw)
        if pan is None or not math.isfinite(pan):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=f"options.mix_inputs[{index}].pan must be a finite number.",
            )
        if pan < -1.0 or pan > 1.0:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=(
                    f"options.mix_inputs[{index}].pan must be in [-1.0, 1.0]. "
                    f"pan={pan}"
                ),
            )

        mute_raw = raw_input.get("mute", False)
        if not isinstance(mute_raw, bool):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message=f"options.mix_inputs[{index}].mute must be a boolean.",
            )

        role: str | None = None
        if "role" in raw_input:
            role = _coerce_str(raw_input.get("role")).strip()
            if not role:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                    message=f"options.mix_inputs[{index}].role must be a non-empty string.",
                )
            invalid_chars = {
                char for char in role if char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._"
            }
            if invalid_chars:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                    message=(
                        f"options.mix_inputs[{index}].role must match [A-Z0-9_.]+. "
                        f"role={role!r}"
                    ),
                )

        normalized.append(
            {
                "path": path_text,
                "gain_db": gain_db,
                "pan": pan,
                "mute": mute_raw,
                "role": role,
            }
        )

    return normalized


def _resolve_request_input_path(
    *,
    raw_path: str,
    scene_anchor: Path | None,
    report_dir: Path,
    field_label: str,
) -> Path:
    normalized_raw = raw_path.strip()
    if not normalized_raw:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"{field_label} is missing.",
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


def _resolve_mix_inputs_with_metadata_or_raise(
    *,
    mix_inputs: list[dict[str, Any]],
    scene_anchor: Path | None,
    report_dir: Path,
) -> tuple[list[dict[str, Any]], int, int | None]:
    resolved_inputs: list[dict[str, Any]] = []
    expected_rate_hz: int | None = None
    expected_rate_path: str | None = None
    preferred_bit_depth: int | None = None

    for index, mix_input in enumerate(mix_inputs, start=1):
        input_path = _resolve_request_input_path(
            raw_path=_coerce_str(mix_input.get("path")),
            scene_anchor=scene_anchor,
            report_dir=report_dir,
            field_label=f"options.mix_inputs[{index}].path",
        )
        if not input_path.exists() or not input_path.is_file():
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_SOURCE_MISSING,
                message=(
                    "options.mix_inputs entry points to a missing source file. "
                    f"index={index}, path={input_path.resolve().as_posix()}"
                ),
            )

        metadata = _read_source_metadata_or_raise(input_path)
        _validate_source_layout_or_raise(metadata)
        sample_rate_hz = _coerce_int(metadata.get("sample_rate_hz"))
        if sample_rate_hz is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message=(
                    "options.mix_inputs entry is missing sample_rate_hz metadata. "
                    f"index={index}, path={input_path.resolve().as_posix()}"
                ),
            )

        if expected_rate_hz is None:
            expected_rate_hz = sample_rate_hz
            expected_rate_path = input_path.resolve().as_posix()
        elif sample_rate_hz != expected_rate_hz:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_MIX_INPUT_SAMPLE_RATE_MISMATCH,
                message=(
                    "options.mix_inputs sample rates must match exactly "
                    "(resampling is not supported). "
                    f"expected={expected_rate_hz} at {expected_rate_path}, "
                    f"found={sample_rate_hz} at {input_path.resolve().as_posix()}"
                ),
            )

        bit_depth = _coerce_int(metadata.get("bits_per_sample"))
        if preferred_bit_depth is None and bit_depth in _BIT_DEPTHS:
            preferred_bit_depth = bit_depth

        resolved_input = dict(mix_input)
        resolved_input["path"] = input_path
        resolved_input["sample_rate_hz"] = sample_rate_hz
        resolved_input["bits_per_sample"] = bit_depth
        resolved_input["needs_ffmpeg_decode"] = (
            input_path.suffix.lower() in _FFMPEG_EXTENSIONS
        )
        resolved_input["tag_bag"] = tag_bag_from_mapping(metadata.get("tags"))
        resolved_inputs.append(resolved_input)

    if expected_rate_hz is None:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message="options.mix_inputs must include at least one source entry.",
        )
    return resolved_inputs, expected_rate_hz, preferred_bit_depth


def _mix_input_channel_gains(
    *,
    gain_db: float,
    pan: float,
    mute: bool,
) -> tuple[float, float]:
    if mute:
        return 0.0, 0.0
    linear_gain = math.pow(10.0, gain_db / 20.0)
    pan_radians = (pan + 1.0) * (math.pi / 4.0)
    return (
        linear_gain * math.cos(pan_radians),
        linear_gain * math.sin(pan_radians),
    )


def _mix_inputs_headroom_gain(mix_inputs: list[dict[str, Any]]) -> float:
    left_sum = 0.0
    right_sum = 0.0
    for mix_input in mix_inputs:
        left_gain, right_gain = _mix_input_channel_gains(
            gain_db=float(mix_input.get("gain_db", 0.0)),
            pan=float(mix_input.get("pan", 0.0)),
            mute=bool(mix_input.get("mute", False)),
        )
        left_sum += abs(left_gain)
        right_sum += abs(right_gain)
    limiter = max(1.0, left_sum, right_sum)
    return 1.0 / limiter


def _read_stereo_source_interleaved_samples(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
) -> list[float]:
    extension = path.suffix.lower()
    float_samples_iter: Iterator[list[float]]
    if extension in _WAV_EXTENSIONS:
        float_samples_iter = iter_wav_float64_samples(
            path,
            error_context="render-run mix_inputs decode",
        )
    elif extension in _FFMPEG_EXTENSIONS:
        if ffmpeg_cmd is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required to decode non-WAV source audio.",
            )
        float_samples_iter = iter_ffmpeg_float64_samples(path, ffmpeg_cmd)
    else:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_FORMAT_UNSUPPORTED,
            message=(
                "Unsupported source extension for options.mix_inputs. "
                f"path={path.resolve().as_posix()}"
            ),
        )

    interleaved: list[float] = []
    for chunk in float_samples_iter:
        if len(chunk) % 2 != 0:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
                message="Decoded sample stream is not frame-aligned for stereo.",
            )
        if chunk:
            interleaved.extend(chunk)
    return interleaved


def _mix_inputs_interleaved_samples_or_raise(
    *,
    mix_inputs: list[dict[str, Any]],
    ffmpeg_cmd_for_decode: Sequence[str] | None,
) -> tuple[list[float], float]:
    mixed_interleaved: list[float] = []
    for mix_input in mix_inputs:
        input_path = mix_input.get("path")
        if not isinstance(input_path, Path):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message="Internal mix_inputs path normalization failed.",
            )
        source_interleaved = _read_stereo_source_interleaved_samples(
            input_path,
            ffmpeg_cmd=ffmpeg_cmd_for_decode,
        )
        if len(source_interleaved) > len(mixed_interleaved):
            mixed_interleaved.extend([0.0] * (len(source_interleaved) - len(mixed_interleaved)))

        left_gain, right_gain = _mix_input_channel_gains(
            gain_db=float(mix_input.get("gain_db", 0.0)),
            pan=float(mix_input.get("pan", 0.0)),
            mute=bool(mix_input.get("mute", False)),
        )
        for offset in range(0, len(source_interleaved), 2):
            mixed_interleaved[offset] += source_interleaved[offset] * left_gain
            mixed_interleaved[offset + 1] += source_interleaved[offset + 1] * right_gain

    headroom_gain = _mix_inputs_headroom_gain(mix_inputs)
    if headroom_gain < 1.0:
        for index, sample in enumerate(mixed_interleaved):
            mixed_interleaved[index] = sample * headroom_gain
    return mixed_interleaved, headroom_gain


def _iter_interleaved_stereo_chunks(
    float_samples: list[float],
    *,
    frames_per_chunk: int = 4096,
) -> Iterator[list[float]]:
    if frames_per_chunk <= 0:
        raise ValueError("frames_per_chunk must be positive.")
    chunk_size = frames_per_chunk * 2
    for start in range(0, len(float_samples), chunk_size):
        yield float_samples[start : start + chunk_size]


def _mix_inputs_decode_command_rows(
    *,
    mix_inputs: list[dict[str, Any]],
    ffmpeg_cmd_for_decode: Sequence[str] | None,
) -> list[dict[str, Any]]:
    command_rows: list[dict[str, Any]] = []
    for mix_input in mix_inputs:
        if not bool(mix_input.get("needs_ffmpeg_decode")):
            continue
        if ffmpeg_cmd_for_decode is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_FFMPEG_REQUIRED,
                message="ffmpeg is required to decode non-WAV source audio.",
            )
        input_path = mix_input.get("path")
        if not isinstance(input_path, Path):
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
                message="Internal mix_inputs path normalization failed.",
            )
        command_rows.append(
            {
                "args": build_ffmpeg_decode_command(
                    input_path,
                    ffmpeg_cmd_for_decode,
                ),
                "determinism_flags": [],
            }
        )
    return command_rows


def _mix_inputs_report_notes(
    *,
    mix_inputs: list[dict[str, Any]],
    headroom_gain: float,
) -> list[str]:
    notes: list[str] = [
        "mix_inputs_headroom_policy: max-channel-sum limiter (1 / max(1, sum(abs(channel_gain))))",
        f"mix_inputs_headroom_gain: {headroom_gain:.12f}",
    ]
    for index, mix_input in enumerate(mix_inputs, start=1):
        input_path = mix_input.get("path")
        if isinstance(input_path, Path):
            path_text = input_path.resolve().as_posix()
        else:
            path_text = _coerce_str(mix_input.get("path")).strip()
        gain_db = float(mix_input.get("gain_db", 0.0))
        pan = float(mix_input.get("pan", 0.0))
        mute = bool(mix_input.get("mute", False))
        role = _coerce_str(mix_input.get("role")).strip()
        note = (
            f"mix_input[{index}]: path={path_text}, "
            f"gain_db={gain_db:.6f}, pan={pan:.6f}, mute={str(mute).lower()}"
        )
        if role:
            note = f"{note}, role={role}"
        notes.append(note)
    return notes


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


def _prevalidate_plugin_chain_static(
    plugin_chain: list[dict[str, Any]],
    max_theoretical_quality: bool,
) -> None:
    """Validate plugin params that don't require numpy (runs before numpy guard).

    Checks detector_mode enum values and oversampling/quality coupling so that
    those errors are reported with their specific messages rather than the generic
    numpy-unavailable message.
    """
    from mmo.dsp.plugins._multiband_common import parse_detector_mode  # noqa: WPS433
    from mmo.dsp.plugins.base import PluginValidationError  # noqa: WPS433

    for stage in plugin_chain:
        plugin_id = _coerce_str(stage.get("plugin_id")).strip().lower()
        params = _coerce_dict(stage.get("params"))

        if plugin_id in _DETECTOR_MODE_PLUGIN_IDS:
            try:
                parse_detector_mode(plugin_id=plugin_id, params=params)
            except PluginValidationError as exc:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=str(exc),
                ) from exc

        if plugin_id in _OVERSAMPLING_QUALITY_PLUGIN_IDS:
            oversampling_raw = params.get("oversampling", 1)
            oversampling = oversampling_raw if isinstance(oversampling_raw, int) else 1
            if oversampling > 1 and not max_theoretical_quality:
                raise RenderRunRefusalError(
                    issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                    message=(
                        "Multiband oversampling > 1 requires "
                        "options.max_theoretical_quality=true."
                    ),
                )


def _plugin_stage_is_total_noop(stage: dict[str, Any]) -> bool:
    params = _coerce_dict(stage.get("params"))
    bypass = _coerce_bool(params.get("bypass"))
    if bypass is True:
        return True
    macro_mix = _coerce_float(params.get("macro_mix"))
    return macro_mix == 0.0


def _plugin_chain_is_total_noop(plugin_chain: list[dict[str, Any]]) -> bool:
    return bool(plugin_chain) and all(
        isinstance(stage, dict) and _plugin_stage_is_total_noop(stage)
        for stage in plugin_chain
    )


def _copy_source_wav_for_noop_plugin_chain(
    *,
    source_path: Path,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
    plugin_chain: list[dict[str, Any]],
    max_theoretical_quality: bool,
    force_float64_default: bool,
) -> list[dict[str, Any]]:
    try:
        __import__("numpy")
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "options.plugin_chain requires numpy runtime support. "
                "Reinstall MMO base deps or remove plugin_chain from the request."
            ),
        ) from exc

    with wave.open(str(source_path), "rb") as handle:
        channel_count = handle.getnchannels()
        frame_count = handle.getnframes()
        source_rate_hz = handle.getframerate()
        source_bit_depth = handle.getsampwidth() * 8

    if channel_count != 2 or source_rate_hz != sample_rate_hz or source_bit_depth != bit_depth:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "Plugin-chain no-op passthrough requires a stereo WAV source with "
                "matching sample rate and bit depth."
            ),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != output_path.resolve():
        shutil.copyfile(source_path, output_path)

    processing_dtype_name = (
        "float64" if (max_theoretical_quality or force_float64_default) else "float32"
    )
    process_ctx = build_process_context(
        _STEREO_LAYOUT_ID,
        sample_rate_hz=sample_rate_hz,
        seed=0,
    )
    source_where = [source_path.resolve().as_posix()]
    output_posix = output_path.resolve().as_posix()
    step_events: list[dict[str, Any]] = [
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain source loaded",
            "why": (
                "Plugin chain resolved to a no-op; preserved exact source WAV bytes "
                "without decode or re-encode."
            ),
            "where": source_where,
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.SOURCE_LOADED"],
                "paths": source_where,
                "metrics": [
                    {"name": "channel_count", "value": process_ctx.num_channels},
                    {"name": "frame_count", "value": frame_count},
                ],
            },
        },
    ]

    dummy_buffer = AudioBufferF64(
        data=[0.0] * process_ctx.num_channels,
        channels=process_ctx.num_channels,
        channel_order=tuple(process_ctx.channel_order),
        sample_rate_hz=sample_rate_hz,
    )
    for stage_index, stage in enumerate(plugin_chain, start=1):
        plugin_id = _coerce_str(stage.get("plugin_id")).strip().lower()
        params = _coerce_dict(stage.get("params"))

        plugin_impl = get_stereo_plugin(plugin_id)
        if plugin_impl is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    "Unsupported plugin_chain stage. "
                    f"stage={stage_index}, plugin_id={plugin_id or '(missing)'}"
                ),
            )

        evidence_collector = PluginEvidenceCollector()
        plugin_context = PluginContext(
            precision_mode=processing_dtype_name,
            max_theoretical_quality=max_theoretical_quality,
            evidence_collector=evidence_collector,
            stage_index=stage_index,
        )
        try:
            stage_output = invoke_with_purity_guard(
                plugin_id=plugin_id,
                purity_contract=_plugin_purity_contract_for_impl(plugin_impl),
                invoke=lambda: plugin_impl.process_stereo(
                    dummy_buffer,
                    sample_rate_hz,
                    params,
                    plugin_context,
                    process_ctx,
                ),
            )
            if not isinstance(stage_output, AudioBufferF64):
                raise PluginValidationError(
                    f"{plugin_id} must return AudioBufferF64 at the typed runtime boundary.",
                )
            if stage_output.sample_rate_hz != sample_rate_hz:
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched sample_rate_hz.",
                )
            if stage_output.channel_order != tuple(process_ctx.channel_order):
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched channel_order.",
                )
            if stage_output.channels != process_ctx.num_channels:
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched channel count.",
                )
        except PluginValidationError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=str(exc),
            ) from exc
        except PluginPurityViolationError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=str(exc),
            ) from exc

        stage_token = f"plugin_chain.stage.{stage_index:03d}.{plugin_id}"
        stage_evidence: dict[str, Any] = {
            "codes": ["RENDER.RUN.PLUGIN.STAGE_APPLIED"],
            "ids": [plugin_id],
            "metrics": evidence_collector.metrics,
        }
        if evidence_collector.notes:
            stage_evidence["notes"] = evidence_collector.notes
        step_events.append(
            {
                "kind": "action",
                "scope": "render",
                "what": evidence_collector.stage_what or "plugin stage applied",
                "why": (
                    evidence_collector.stage_why
                    or "Plugin stage resolved to a no-op and exact WAV bytes were preserved."
                ),
                "where": [*source_where, stage_token],
                "confidence": None,
                "evidence": stage_evidence,
            },
        )

    step_events.append(
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain output written",
            "why": (
                "Copied exact source WAV bytes because every plugin stage resolved "
                "to a no-op and no format conversion was required."
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
        },
    )
    return step_events


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
    source_samples_interleaved: list[float] | None = None,
    source_evidence_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    _prevalidate_plugin_chain_static(plugin_chain, max_theoretical_quality)
    try:
        __import__("numpy")
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "options.plugin_chain requires numpy runtime support. "
                "Reinstall MMO base deps or remove plugin_chain from the request."
            ),
        ) from exc

    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    processing_dtype_name = (
        "float64" if (max_theoretical_quality or force_float64_default) else "float32"
    )

    source_where: list[str] = []
    if source_samples_interleaved is None:
        rendered_buffer = _read_stereo_source_buffer(
            source_path,
            ffmpeg_cmd=ffmpeg_cmd_for_decode,
            sample_rate_hz=sample_rate_hz,
        )
        source_where = [source_path.resolve().as_posix()]
    else:
        rendered_buffer = _stereo_audio_buffer_from_interleaved_samples(
            source_samples_interleaved,
            sample_rate_hz=sample_rate_hz,
        )
        source_where = [
            _coerce_str(path).strip()
            for path in (source_evidence_paths or [])
            if _coerce_str(path).strip()
        ]
        if not source_where:
            source_where = [source_path.resolve().as_posix()]
    frame_count = rendered_buffer.frame_count

    output_posix = output_path.resolve().as_posix()
    process_ctx = build_process_context(
        _STEREO_LAYOUT_ID,
        sample_rate_hz=sample_rate_hz,
        seed=0,
    )
    step_events: list[dict[str, Any]] = [
        {
            "kind": "action",
            "scope": "render",
            "what": "plugin chain source loaded",
            "why": (
                "Loaded stereo source into "
                f"{processing_dtype_name} buffer for deterministic plugin execution."
            ),
            "where": source_where,
            "confidence": None,
            "evidence": {
                "codes": ["RENDER.RUN.PLUGIN.SOURCE_LOADED"],
                "paths": source_where,
                "metrics": [
                    {"name": "channel_count", "value": process_ctx.num_channels},
                    {"name": "frame_count", "value": frame_count},
                ],
            },
        },
    ]

    for stage_index, stage in enumerate(plugin_chain, start=1):
        plugin_id = _coerce_str(stage.get("plugin_id")).strip().lower()
        params = _coerce_dict(stage.get("params"))

        plugin_impl = get_stereo_plugin(plugin_id)
        if plugin_impl is None:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=(
                    "Unsupported plugin_chain stage. "
                    f"stage={stage_index}, plugin_id={plugin_id or '(missing)'}"
                ),
            )

        evidence_collector = PluginEvidenceCollector()
        plugin_context = PluginContext(
            precision_mode=processing_dtype_name,
            max_theoretical_quality=max_theoretical_quality,
            evidence_collector=evidence_collector,
            stage_index=stage_index,
        )
        try:
            rendered_buffer = invoke_with_purity_guard(
                plugin_id=plugin_id,
                purity_contract=_plugin_purity_contract_for_impl(plugin_impl),
                invoke=lambda: plugin_impl.process_stereo(
                    rendered_buffer,
                    sample_rate_hz,
                    params,
                    plugin_context,
                    process_ctx,
                ),
            )
            if not isinstance(rendered_buffer, AudioBufferF64):
                raise PluginValidationError(
                    f"{plugin_id} must return AudioBufferF64 at the typed runtime boundary.",
                )
            if rendered_buffer.sample_rate_hz != sample_rate_hz:
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched sample_rate_hz.",
                )
            if rendered_buffer.channel_order != tuple(process_ctx.channel_order):
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched channel_order.",
                )
            if rendered_buffer.channels != process_ctx.num_channels:
                raise PluginValidationError(
                    f"{plugin_id} returned AudioBufferF64 with mismatched channel count.",
                )
        except PluginValidationError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=str(exc),
            ) from exc
        except PluginPurityViolationError as exc:
            raise RenderRunRefusalError(
                issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
                message=str(exc),
            ) from exc

        stage_token = f"plugin_chain.stage.{stage_index:03d}.{plugin_id}"
        stage_evidence: dict[str, Any] = {
            "codes": ["RENDER.RUN.PLUGIN.STAGE_APPLIED"],
            "ids": [plugin_id],
            "metrics": evidence_collector.metrics,
        }
        if evidence_collector.notes:
            stage_evidence["notes"] = evidence_collector.notes
        step_events.append(
            {
                "kind": "action",
                "scope": "render",
                "what": evidence_collector.stage_what,
                "why": evidence_collector.stage_why,
                "where": [*source_where, stage_token],
                "confidence": None,
                "evidence": stage_evidence,
            },
        )

    _write_stereo_pcm_wav_from_audio_buffer(
        audio_buffer=rendered_buffer,
        output_path=output_path,
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
        },
    )
    return step_events


def _stereo_audio_buffer_from_interleaved_samples(
    float_samples: Sequence[float],
    *,
    sample_rate_hz: int,
) -> AudioBufferF64:
    try:
        return AudioBufferF64(
            data=[float(sample) for sample in float_samples],
            channels=2,
            channel_order=_STEREO_CHANNEL_ORDER,
            sample_rate_hz=sample_rate_hz,
        )
    except ValueError as exc:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_DECODE_FAILED,
            message="Decoded sample stream is not frame-aligned for stereo.",
        ) from exc


def _audio_buffer_to_numpy_frame_matrix(
    audio_buffer: AudioBufferF64,
    *,
    np: Any,
    dtype: Any,
) -> Any:
    requested_dtype = np.dtype(dtype)
    if requested_dtype not in {np.dtype(np.float32), np.dtype(np.float64)}:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=(
                "Unsupported plugin-chain processing dtype: "
                f"{requested_dtype.name}. Expected float32 or float64."
            ),
        )
    return np.asarray(audio_buffer.data, dtype=requested_dtype).reshape(
        audio_buffer.frame_count,
        audio_buffer.channels,
    )


def _numpy_frame_matrix_to_audio_buffer(
    frame_matrix: Any,
    *,
    np: Any,
    template: AudioBufferF64,
) -> AudioBufferF64:
    samples = np.asarray(frame_matrix)
    if samples.ndim != 2 or samples.shape[1] != template.channels:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "Plugin-chain runner expects a stereo float32/float64 sample matrix."
            ),
        )
    return AudioBufferF64(
        data=[float(sample) for sample in samples.reshape(-1)],
        channels=template.channels,
        channel_order=template.channel_order,
        sample_rate_hz=template.sample_rate_hz,
    )


def _read_stereo_source_buffer(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
    sample_rate_hz: int,
) -> AudioBufferF64:
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

    interleaved: list[float] = []
    for float_samples in float_samples_iter:
        if not float_samples:
            continue
        chunk_buffer = _stereo_audio_buffer_from_interleaved_samples(
            float_samples,
            sample_rate_hz=sample_rate_hz,
        )
        interleaved.extend(chunk_buffer.data)
    return _stereo_audio_buffer_from_interleaved_samples(
        interleaved,
        sample_rate_hz=sample_rate_hz,
    )


def _write_stereo_pcm_wav_from_audio_buffer(
    *,
    audio_buffer: AudioBufferF64,
    output_path: Path,
    bit_depth: int,
) -> None:
    if bit_depth not in _BIT_DEPTHS:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_OPTION_UNSUPPORTED,
            message=f"Unsupported output bit depth: {bit_depth}",
        )

    if audio_buffer.channels != 2:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_PLUGIN_CHAIN_INVALID,
            message=(
                "Plugin-chain runner expects a stereo float32/float64 sample matrix."
            ),
        )
    pcm_bytes = _float_samples_to_pcm_bytes(audio_buffer.data, bit_depth)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(audio_buffer.sample_rate_hz)
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


def _resolve_single_source_or_raise(
    scene_payload: dict[str, Any],
    *,
    scene_path: Path | None = None,
) -> Path:
    source_payload = scene_payload.get("source")
    if not isinstance(source_payload, dict):
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message="scene.source must be an object with stems_dir.",
        )
    stems_dir_text = _coerce_str(source_payload.get("stems_dir")).strip()
    if not stems_dir_text:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir must point at a source directory for PR52 render-run. "
                "stems_dir=(missing)"
            ),
        )
    if is_absolute_posix_path(stems_dir_text):
        stems_dir = Path(stems_dir_text)
    elif scene_path is not None:
        stems_dir = resolve_posix_ref(
            stems_dir_text,
            anchor_dir=scene_path.resolve().parent,
        )
    else:
        stems_dir = None
    if stems_dir is None:
        raise RenderRunRefusalError(
            issue_id=ISSUE_RENDER_RUN_SOURCE_STEMS_DIR_INVALID,
            message=(
                "scene.source.stems_dir is relative, but the scene path is unavailable for PR52 render-run. "
                f"stems_dir={stems_dir_text}"
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
    metadata_args: Sequence[str] | None = None,
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
        *(list(metadata_args) if metadata_args is not None else []),
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
    metadata_receipt: dict[str, Any],
) -> dict[str, Any]:
    sha256_hex = sha256_file(output_path)
    payload: dict[str, Any] = {
        "file_path": output_path.resolve().as_posix(),
        "format": output_format,
        "channel_count": 2,
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": bit_depth,
        "sha256": sha256_hex,
    }
    if metadata_receipt:
        payload["metadata_receipt"] = metadata_receipt
    return payload


def _output_sort_key(output_format: str) -> tuple[int, str]:
    try:
        return (_OUTPUT_FORMAT_ORDER.index(output_format), output_format)
    except ValueError:
        return (len(_OUTPUT_FORMAT_ORDER), output_format)
