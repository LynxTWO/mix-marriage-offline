from __future__ import annotations

import math
from typing import Any

import numpy as np

from mmo.dsp.buffer import AudioBufferF64

_CHECKSUM_TONE_DBFS = -60.0
_CHECKSUM_TONE_LINEAR = math.pow(10.0, _CHECKSUM_TONE_DBFS / 20.0)


class TrueMultichannelSumcheckFixture:
    plugin_id = "PLUGIN.RENDERER.TEST.TRUE_MULTICHANNEL_SUMCHECK"

    def process_true_multichannel(
        self,
        matrix: Any,
        sample_rate_hz: int,
        params: dict[str, Any],
        *,
        process_ctx: Any,
    ) -> tuple[AudioBufferF64, dict[str, Any]]:
        if not isinstance(matrix, AudioBufferF64):
            raise TypeError("TrueMultichannelSumcheckFixture requires AudioBufferF64 input.")
        if matrix.sample_rate_hz != sample_rate_hz:
            raise ValueError("AudioBufferF64 sample_rate_hz must match sample_rate_hz.")
        rendered = matrix.to_channel_matrix(np=np, dtype=np.float64)
        expected_sum_min = float(params["expected_sum_min"])
        expected_sum_max = float(params["expected_sum_max"])
        target_channel_id = str(params["target_channel_id"]).strip()
        channel_index = process_ctx.index_of(target_channel_id)
        checksum = float(np.sum(rendered, dtype=np.float64))
        checksum_matched = expected_sum_min <= checksum <= expected_sum_max
        tone_written = False

        if checksum_matched and channel_index is not None:
            phase = 2.0 * math.pi * ((process_ctx.seed % 1024) / 1024.0)
            frame_count = rendered.shape[1]
            positions = np.arange(frame_count, dtype=np.float64)
            tone = _CHECKSUM_TONE_LINEAR * np.sin(
                (2.0 * math.pi * positions / max(frame_count, 1)) + phase,
            )
            rendered[channel_index] = rendered[channel_index] + tone
            tone_written = True
        else:
            phase = 0.0

        return AudioBufferF64.from_channel_matrix(
            rendered,
            channel_order=matrix.channel_order,
            sample_rate_hz=matrix.sample_rate_hz,
        ), {
            "channel_ids_seen": list(process_ctx.channel_order),
            "checksum": checksum,
            "expected_sum_min": expected_sum_min,
            "expected_sum_max": expected_sum_max,
            "checksum_matched": checksum_matched,
            "tone_written": tone_written,
            "tone_channel_id": target_channel_id,
            "checksum_tone_dbfs": _CHECKSUM_TONE_DBFS,
            "phase_radians": phase,
            "seed": process_ctx.seed,
            "buffer_type": type(matrix).__name__,
            "buffer_channel_order": list(matrix.channel_order),
        }
