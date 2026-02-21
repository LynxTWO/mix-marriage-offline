"""Deterministic ``multiband_dynamic_auto_v0`` plugin implementation."""

from __future__ import annotations

from typing import Any

from mmo.dsp.plugins._multiband_common import (
    OPERATION_AUTO,
    process_multiband_plugin,
)
from mmo.dsp.plugins.base import PluginContext

PLUGIN_ID = "multiband_dynamic_auto_v0"


class MultibandDynamicAutoV0Plugin:
    """Apply deterministic slope-aware multiband dynamics auto mode."""

    plugin_id = PLUGIN_ID

    def process_stereo(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
    ) -> Any:
        return process_multiband_plugin(
            plugin_id=PLUGIN_ID,
            operation_mode=OPERATION_AUTO,
            buf_f32_or_f64=buf_f32_or_f64,
            sample_rate=sample_rate,
            params=params,
            ctx=ctx,
        )

