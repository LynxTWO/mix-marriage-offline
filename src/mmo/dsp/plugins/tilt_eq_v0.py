"""Deterministic ``tilt_eq_v0`` plugin implementation."""

from __future__ import annotations

import math
from typing import Any

from mmo.dsp.plugins.base import (
    AudioBufferF64,
    ProcessContext,
    PluginContext,
    PluginValidationError,
    coerce_audio_buffer_for_process_context,
    coerce_float,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
    precision_mode_numpy_dtype,
)

PLUGIN_ID = "tilt_eq_v0"


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
    import numpy as np

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
    import numpy as np

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


class TiltEqV0Plugin:
    """Apply deterministic two-shelf tilt EQ with linear dry/wet blend."""

    plugin_id = PLUGIN_ID

    def process_stereo(
        self,
        audio_buffer: AudioBufferF64,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        process_ctx: ProcessContext | None = None,
    ) -> AudioBufferF64:
        if process_ctx is None:
            raise PluginValidationError(f"{PLUGIN_ID} requires ProcessContext.")
        import numpy as np

        source_buffer = coerce_audio_buffer_for_process_context(
            value=audio_buffer,
            plugin_id=PLUGIN_ID,
            sample_rate_hz=sample_rate,
            process_ctx=process_ctx,
        )
        tilt_db = coerce_float(params.get("tilt_db"))
        if tilt_db is None:
            raise PluginValidationError(
                f"{PLUGIN_ID} requires numeric params.tilt_db.",
            )
        pivot_hz = coerce_float(params.get("pivot_hz"))
        if pivot_hz is None:
            raise PluginValidationError(
                f"{PLUGIN_ID} requires numeric params.pivot_hz.",
            )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID,
            params=params,
        )
        processing_dtype = precision_mode_numpy_dtype(
            np=np,
            precision_mode=ctx.precision_mode,
        )
        rendered = source_buffer.to_frame_matrix(np=np, dtype=processing_dtype)
        if bypass:
            stage_what = "plugin stage bypassed"
            stage_why = (
                "Bypass enabled; preserved dry stereo "
                f"{ctx.precision_mode} buffer without tilt EQ "
                "or wet/dry mixing."
            )
        else:
            stage_what = "plugin stage applied"
            wet = _apply_tilt_eq_v0(
                signal=rendered,
                sample_rate_hz=sample_rate,
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

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "tilt_db", "value": tilt_db},
                {"name": "pivot_hz", "value": pivot_hz},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ],
        )
        return AudioBufferF64.from_frame_matrix(
            rendered,
            channel_order=source_buffer.channel_order,
            sample_rate_hz=source_buffer.sample_rate_hz,
        )
