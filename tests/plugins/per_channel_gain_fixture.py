from __future__ import annotations

import math
from typing import Any

import numpy as np

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
    ) -> tuple[np.ndarray, dict[str, Any]]:
        del sample_rate_hz
        del process_ctx
        target_channel_ids = {
            channel_id.strip()
            for channel_id in params.get("target_channel_ids", [])
            if isinstance(channel_id, str) and channel_id.strip()
        }
        rendered = np.array(channel, copy=True)
        touched = spk_id in target_channel_ids
        if touched:
            rendered *= _GAIN_LINEAR
        return rendered, {
            "touched": touched,
            "channel_ids": [spk_id] if touched else [],
            "gain_db": _GAIN_DB,
        }
