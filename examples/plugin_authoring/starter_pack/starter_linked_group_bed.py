from __future__ import annotations

import math
from typing import Any

import numpy as np

from mmo.dsp.buffer import AudioBufferF64


class StarterLinkedGroupBed:
    plugin_id = "PLUGIN.RENDERER.STARTER.LINKED_GROUP_BED"

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
            raise TypeError("StarterLinkedGroupBed requires AudioBufferF64 input.")
        if grouped_channels.sample_rate_hz != sample_rate_hz:
            raise ValueError(
                "AudioBufferF64 sample_rate_hz must match sample_rate_hz.",
            )

        # Linked-group mode sees one lawful speaker group at a time. The host
        # uses that to enforce bed-only scope before plugin code runs.
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
            "restriction_hint": "bed_only",
            "buffer_type": type(grouped_channels).__name__,
            "buffer_channel_order": list(grouped_channels.channel_order),
        }

    def render(  # type: ignore[no-untyped-def]
        self,
        session,
        recommendations,
        output_dir=None,
    ):
        del session, output_dir
        # The manifest notes and skipped rows from run_renderers carry the real
        # bed-only audit trail. This receipt only echoes what reached the plugin.
        received_ids = sorted(
            {
                rec.get("recommendation_id")
                for rec in recommendations
                if isinstance(rec, dict) and isinstance(rec.get("recommendation_id"), str)
            }
        )
        return {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "received_recommendation_ids": received_ids,
            "notes": "starter_example:linked_group_bed_receipt_only",
        }
