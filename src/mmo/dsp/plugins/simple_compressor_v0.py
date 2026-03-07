"""Deterministic ``simple_compressor_v0`` plugin implementation."""

from __future__ import annotations

import math
from typing import Any

from mmo.dsp.plugins.base import (
    ProcessContext,
    PluginContext,
    PluginValidationError,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
    require_finite_float_param,
)

PLUGIN_ID = "simple_compressor_v0"
_DETECTOR_MODE_RMS = "rms"
_DETECTOR_MODE_PEAK = "peak"
_DETECTOR_MODE_LUFS_SHORTTERM = "lufs_shortterm"
_DETECTOR_MODES = frozenset(
    {
        _DETECTOR_MODE_RMS,
        _DETECTOR_MODE_PEAK,
        _DETECTOR_MODE_LUFS_SHORTTERM,
    },
)


def _parse_detector_mode(*, params: dict[str, Any]) -> str:
    raw_mode = params.get("detector_mode")
    if raw_mode is None:
        return _DETECTOR_MODE_RMS
    if not isinstance(raw_mode, str):
        raise PluginValidationError(
            f"{PLUGIN_ID} requires string params.detector_mode. "
            f"Allowed: {', '.join(sorted(_DETECTOR_MODES))}.",
        )
    mode = raw_mode.strip().lower()
    if mode in _DETECTOR_MODES:
        return mode
    raise PluginValidationError(
        f"{PLUGIN_ID} requires params.detector_mode in "
        f"{', '.join(sorted(_DETECTOR_MODES))}.",
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
    import numpy as np

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
        if detector_mode == _DETECTOR_MODE_PEAK:
            detector_linear = float(np.max(abs_frame))
            detector_db = _db_from_linear_level(detector_linear)
        else:
            detector_linear = math.sqrt(float(np.mean(abs_frame * abs_frame)))
            detector_db = _db_from_linear_level(detector_linear)
            if detector_mode == _DETECTOR_MODE_LUFS_SHORTTERM:
                detector_db -= 0.691

        detector_coeff = attack_coeff if detector_db > envelope_db else release_coeff
        envelope_db = (detector_coeff * envelope_db) + ((1.0 - detector_coeff) * detector_db)

        over_db = envelope_db - threshold_db
        gain_reduction_db = 0.0
        if over_db > 0.0 and safe_ratio > 1.0:
            gain_reduction_db = over_db * (1.0 - (1.0 / safe_ratio))

        if gain_reduction_db > 0.0:
            gain_reduction_sum_db += gain_reduction_db
            gain_reduction_count += 1

        gain_scalar = makeup_scalar * float(math.pow(10.0, -gain_reduction_db / 20.0))
        wet64[frame_index, :] = np.clip(frame * gain_scalar, -1.0, 1.0)

    gr_approx_db = (
        gain_reduction_sum_db / float(gain_reduction_count)
        if gain_reduction_count
        else 0.0
    )
    return wet64.astype(output_dtype, copy=False), gr_approx_db


class SimpleCompressorV0Plugin:
    """Apply deterministic feed-forward compression (no lookahead)."""

    plugin_id = PLUGIN_ID

    def process_stereo(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        process_ctx: ProcessContext | None = None,
    ) -> Any:
        del process_ctx
        import numpy as np

        threshold_db = require_finite_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="threshold_db",
        )
        ratio = require_finite_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="ratio",
        )
        attack_ms = require_finite_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="attack_ms",
        )
        release_ms = require_finite_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="release_ms",
        )
        makeup_db = require_finite_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="makeup_db",
        )
        detector_mode = _parse_detector_mode(params=params)
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID,
            params=params,
        )

        processing_dtype = buf_f32_or_f64.dtype.type
        rendered = buf_f32_or_f64
        gr_approx_db = 0.0
        if bypass:
            stage_what = "plugin stage bypassed"
            stage_why = (
                "Bypass enabled; preserved dry stereo "
                f"{ctx.precision_mode} buffer without compression."
            )
        else:
            stage_what = "plugin stage applied"
            wet, gr_approx_db = _apply_simple_compressor_v0(
                signal=rendered,
                sample_rate_hz=sample_rate,
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
                stage_why = "Applied feed-forward compression (no lookahead) with full wet mix."
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

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "threshold_db", "value": threshold_db},
                {"name": "ratio", "value": ratio},
                {"name": "attack_ms", "value": attack_ms},
                {"name": "release_ms", "value": release_ms},
                {"name": "makeup_db", "value": makeup_db},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
                {"name": "gr_approx_db", "value": gr_approx_db},
            ],
            notes=[f"detector_mode={detector_mode}"],
        )
        return rendered
