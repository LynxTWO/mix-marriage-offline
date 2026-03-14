from __future__ import annotations

import math
from typing import Any

import numpy as np

from mmo.dsp.buffer import AudioBufferF64

_GAIN_DB = 1.0
_GAIN_LINEAR = math.pow(10.0, _GAIN_DB / 20.0)


class PerChannelGainFixture:
    plugin_id = "PLUGIN.RENDERER.TEST.PER_CHANNEL_GAIN"

    def process_channel(
        self,
        channel: Any,
        sample_rate_hz: int,
        params: dict[str, Any],
        *,
        spk_id: str,
        process_ctx: Any,
    ) -> tuple[AudioBufferF64, dict[str, Any]]:
        del process_ctx
        if not isinstance(channel, AudioBufferF64):
            raise TypeError("PerChannelGainFixture requires AudioBufferF64 input.")
        if channel.sample_rate_hz != sample_rate_hz:
            raise ValueError("AudioBufferF64 sample_rate_hz must match sample_rate_hz.")
        target_channel_ids = {
            channel_id.strip()
            for channel_id in params.get("target_channel_ids", [])
            if isinstance(channel_id, str) and channel_id.strip()
        }
        rendered = channel.to_channel_matrix(np=np, dtype=np.float64)
        touched = spk_id in target_channel_ids
        if touched:
            rendered *= _GAIN_LINEAR
        return AudioBufferF64.from_channel_matrix(
            rendered,
            channel_order=channel.channel_order,
            sample_rate_hz=channel.sample_rate_hz,
        ), {
            "touched": touched,
            "channel_ids": [spk_id] if touched else [],
            "gain_db": _GAIN_DB,
            "buffer_type": type(channel).__name__,
            "buffer_channel_order": list(channel.channel_order),
        }
