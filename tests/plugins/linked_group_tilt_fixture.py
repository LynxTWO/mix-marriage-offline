from __future__ import annotations

import math
from typing import Any

import numpy as np

from mmo.dsp.buffer import AudioBufferF64


class LinkedGroupTiltFixture:
    plugin_id = "PLUGIN.RENDERER.TEST.LINKED_GROUP_TILT"

    def process_linked_group(
        self,
        grouped_channels: Any,
        sample_rate_hz: int,
        params: dict[str, Any],
        *,
        group_name: str,
        channel_ids: tuple[str, ...],
        process_ctx: Any,
    ) -> tuple[AudioBufferF64, dict[str, Any]]:
        del process_ctx
        if not isinstance(grouped_channels, AudioBufferF64):
            raise TypeError("LinkedGroupTiltFixture requires AudioBufferF64 input.")
        if grouped_channels.sample_rate_hz != sample_rate_hz:
            raise ValueError(
                "AudioBufferF64 sample_rate_hz must match sample_rate_hz.",
            )
        gain_db = float(params.get("gain_db", 0.0))
        gain_linear = math.pow(10.0, gain_db / 20.0)
        rendered = grouped_channels.to_channel_matrix(np=np, dtype=np.float64)
        rendered *= gain_linear
        return AudioBufferF64.from_channel_matrix(
            rendered,
            channel_order=grouped_channels.channel_order,
            sample_rate_hz=grouped_channels.sample_rate_hz,
        ), {
            "group_name": group_name,
            "channel_ids": list(channel_ids),
            "gain_db": gain_db,
            "buffer_type": type(grouped_channels).__name__,
            "buffer_channel_order": list(grouped_channels.channel_order),
        }
