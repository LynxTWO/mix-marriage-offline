"""reverb_safety_v0: Conservative ambience tail with safety gating.

Adds a subtle deterministic reverb tail on non-dialog program channels while
preserving center and LFE untouched.  Processing is gated by channel activity
and scaled by a headroom guard to remain translation-safe.
"""

from __future__ import annotations

import math
from typing import Any

from mmo.core.speaker_layout import SpeakerPosition
from mmo.dsp.plugins.base import (
    LayoutContext,
    ProcessContext,
    PluginContext,
    optional_float_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "reverb_safety_v0"

SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"

_EPSILON = 1e-12


def _dbfs_rms(samples: Any) -> float:
    mean_square = float((samples * samples).mean()) if samples.size else 0.0
    if mean_square <= _EPSILON:
        return float("-inf")
    return 10.0 * math.log10(mean_square)


def _dbfs_peak(samples: Any) -> float:
    peak = float(samples.max()) if samples.size else 0.0
    peak = max(peak, float((-samples).max()) if samples.size else 0.0)
    if peak <= _EPSILON:
        return float("-inf")
    return 20.0 * math.log10(peak)


def _safe_reverb_tail(
    channel: Any,
    *,
    sample_rate_hz: int,
    pre_delay_samples: int,
    decay_ms: float,
) -> Any:
    import numpy as np

    n = int(channel.shape[0])
    wet = np.zeros(n, dtype=np.float64)

    delay_a = max(1, int(round(sample_rate_hz * 0.013)))
    delay_b = max(1, int(round(sample_rate_hz * 0.021)))
    ref_delay = float(delay_a + delay_b) * 0.5
    decay_samples = max(1.0, decay_ms * float(sample_rate_hz) / 1000.0)
    feedback = math.exp(-ref_delay / decay_samples)
    previous = 0.0

    for index in range(n):
        src_a = index - pre_delay_samples - delay_a
        src_b = index - pre_delay_samples - delay_b
        tap_a = float(channel[src_a]) if src_a >= 0 else 0.0
        tap_b = float(channel[src_b]) if src_b >= 0 else 0.0
        mixed_tap = (tap_a + tap_b) * 0.5
        previous = mixed_tap + (previous * feedback)
        wet[index] = previous

    return np.clip(wet, -1.0, 1.0)


class ReverbSafetyV0Plugin:
    """Add a conservative gated ambience tail to non-protected channels."""

    plugin_id = PLUGIN_ID
    supported_standards = SUPPORTED_STANDARDS
    preferred_standard = PREFERRED_STANDARD

    def process_multichannel(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        layout_ctx: LayoutContext,
        process_ctx: ProcessContext | None = None,
    ) -> Any:
        del process_ctx
        import numpy as np

        pre_delay_ms = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="pre_delay_ms",
            default_value=10.0,
            minimum_value=0.0,
            maximum_value=40.0,
        )
        decay_ms = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="decay_ms",
            default_value=180.0,
            minimum_value=60.0,
            maximum_value=400.0,
        )
        wet_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="wet_db",
            default_value=-18.0,
            minimum_value=-30.0,
            maximum_value=-8.0,
        )
        gate_rms_dbfs = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="gate_rms_dbfs",
            default_value=-45.0,
            minimum_value=-80.0,
            maximum_value=-6.0,
        )
        headroom_guard_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="headroom_guard_db",
            default_value=2.0,
            minimum_value=0.5,
            maximum_value=6.0,
        )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID, params=params
        )

        center_slot = layout_ctx.index_of(SpeakerPosition.FC)
        protected_slots = set(layout_ctx.lfe_slots)
        if center_slot is not None:
            protected_slots.add(center_slot)

        process_slots = [
            slot for slot in range(layout_ctx.num_channels) if slot not in protected_slots
        ]

        wet_gain = math.pow(10.0, wet_db / 20.0)
        pre_delay_samples = int(round(pre_delay_ms * float(sample_rate) / 1000.0))

        rendered = buf_f32_or_f64.copy()
        processing_dtype = buf_f32_or_f64.dtype.type

        processed_count = 0
        gated_out_count = 0
        guarded_count = 0

        if bypass or not process_slots:
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = "Bypass enabled; conservative reverb safety stage skipped."
            else:
                stage_what = "plugin stage applied (no eligible channels)"
                stage_why = "Only protected channels (center/LFE) present; reverb safety did not process."
        else:
            stage_what = "plugin stage applied"
            for slot in process_slots:
                dry64 = buf_f32_or_f64[slot].astype(np.float64, copy=False)
                rms_dbfs = _dbfs_rms(dry64)
                if rms_dbfs < gate_rms_dbfs:
                    gated_out_count += 1
                    continue

                wet64 = _safe_reverb_tail(
                    dry64,
                    sample_rate_hz=sample_rate,
                    pre_delay_samples=pre_delay_samples,
                    decay_ms=decay_ms,
                )

                effective_mix = macro_mix
                dry_peak_dbfs = _dbfs_peak(dry64)
                if dry_peak_dbfs > (-1.0 * headroom_guard_db):
                    effective_mix = min(effective_mix, 0.30)
                    guarded_count += 1

                if effective_mix <= 0.0:
                    continue

                blended = np.clip(
                    dry64 + (wet64 * wet_gain * effective_mix),
                    -1.0,
                    1.0,
                )
                if effective_mix < 1.0:
                    blended = np.clip(
                        (dry64 * (1.0 - effective_mix)) + (blended * effective_mix),
                        -1.0,
                        1.0,
                    )
                rendered[slot] = blended.astype(processing_dtype, copy=False)
                processed_count += 1

            stage_why = (
                f"Conservative reverb processed {processed_count} channel(s), "
                f"gated {gated_out_count}, headroom-guarded {guarded_count}."
            )

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "pre_delay_ms", "value": pre_delay_ms},
                {"name": "decay_ms", "value": decay_ms},
                {"name": "wet_db", "value": wet_db},
                {"name": "gate_rms_dbfs", "value": gate_rms_dbfs},
                {"name": "headroom_guard_db", "value": headroom_guard_db},
                {"name": "processed_count", "value": float(processed_count)},
                {"name": "gated_out_count", "value": float(gated_out_count)},
                {"name": "guarded_count", "value": float(guarded_count)},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ],
            notes=[
                f"protected_slots={sorted(protected_slots)}",
                f"layout_standard={layout_ctx.layout.standard.value}",
                "Gate reference: GATE.NO_CLIP + GATE.DOWNMIX_SIMILARITY_MEASURED.",
            ],
        )
        return rendered
