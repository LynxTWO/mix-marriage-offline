"""Deterministic ``gain_v0`` plugin implementation."""

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

PLUGIN_ID = "gain_v0"


class GainV0Plugin:
    """Apply fixed gain with deterministic linear dry/wet blend."""

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
        gain_db = coerce_float(params.get("gain_db"))
        if gain_db is None:
            raise PluginValidationError(
                f"{PLUGIN_ID} requires numeric params.gain_db.",
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
        linear_gain = float(math.pow(10.0, gain_db / 20.0))

        if bypass:
            stage_what = "plugin stage bypassed"
            stage_why = (
                "Bypass enabled; preserved dry stereo "
                f"{ctx.precision_mode} buffer without gain "
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

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "gain_db", "value": gain_db},
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
