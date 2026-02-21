"""Deterministic ``gain_v0`` plugin implementation."""

from __future__ import annotations

import math
from typing import Any

from mmo.dsp.plugins.base import (
    PluginContext,
    PluginValidationError,
    coerce_float,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "gain_v0"


class GainV0Plugin:
    """Apply fixed gain with deterministic linear dry/wet blend."""

    plugin_id = PLUGIN_ID

    def process_stereo(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
    ) -> Any:
        del sample_rate
        import numpy as np

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
        processing_dtype = buf_f32_or_f64.dtype.type
        linear_gain = float(math.pow(10.0, gain_db / 20.0))

        rendered = buf_f32_or_f64
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
        return rendered

