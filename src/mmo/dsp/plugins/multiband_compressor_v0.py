"""Deterministic ``multiband_compressor_v0`` plugin implementation."""

from __future__ import annotations

from mmo.dsp.plugins._multiband_common import (
    OPERATION_COMPRESS,
    process_multiband_plugin,
)
from mmo.dsp.plugins.base import AudioBufferF64, PluginContext, ProcessContext

PLUGIN_ID = "multiband_compressor_v0"


class MultibandCompressorV0Plugin:
    """Apply deterministic slope-aware multiband compression."""

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
            operation_mode=OPERATION_COMPRESS,
            audio_buffer=audio_buffer,
            sample_rate=sample_rate,
            params=params,
            ctx=ctx,
            process_ctx=process_ctx,
        )
