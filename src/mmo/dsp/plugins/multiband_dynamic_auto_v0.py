"""Deterministic ``multiband_dynamic_auto_v0`` plugin implementation."""

from __future__ import annotations

from mmo.dsp.plugins._multiband_common import (
    OPERATION_AUTO,
    process_multiband_plugin,
)
from mmo.dsp.plugins.base import AudioBufferF64, PluginContext, ProcessContext

PLUGIN_ID = "multiband_dynamic_auto_v0"


class MultibandDynamicAutoV0Plugin:
    """Apply deterministic slope-aware multiband dynamics auto mode."""

    plugin_id = PLUGIN_ID

    def process_stereo(
        self,
        audio_buffer: AudioBufferF64,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        process_ctx: ProcessContext | None = None,
    ) -> AudioBufferF64:
        return process_multiband_plugin(
            plugin_id=PLUGIN_ID,
            operation_mode=OPERATION_AUTO,
            audio_buffer=audio_buffer,
            sample_rate=sample_rate,
            params=params,
            ctx=ctx,
            process_ctx=process_ctx,
        )
