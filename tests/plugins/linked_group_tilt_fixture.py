from __future__ import annotations

import math
from typing import Any

import numpy as np


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
    ) -> tuple[np.ndarray, dict[str, Any]]:
        del sample_rate_hz
        del process_ctx
        gain_db = float(params.get("gain_db", 0.0))
        gain_linear = math.pow(10.0, gain_db / 20.0)
        rendered = np.array(grouped_channels, copy=True)
        rendered *= gain_linear
        return rendered, {
            "group_name": group_name,
            "channel_ids": list(channel_ids),
            "gain_db": gain_db,
        }
