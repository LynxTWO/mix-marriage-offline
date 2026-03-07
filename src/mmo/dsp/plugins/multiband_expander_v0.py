"""Deterministic ``multiband_expander_v0`` plugin implementation."""

from __future__ import annotations

from typing import Any

from mmo.dsp.plugins._multiband_common import (
    OPERATION_EXPAND,
    process_multiband_plugin,
)
from mmo.dsp.plugins.base import PluginContext, ProcessContext

PLUGIN_ID = "multiband_expander_v0"


class MultibandExpanderV0Plugin:
    """Apply deterministic slope-aware multiband expansion."""

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
        return process_multiband_plugin(
            plugin_id=PLUGIN_ID,
            operation_mode=OPERATION_EXPAND,
            buf_f32_or_f64=buf_f32_or_f64,
            sample_rate=sample_rate,
            params=params,
            ctx=ctx,
        )
