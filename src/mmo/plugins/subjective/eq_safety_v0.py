"""eq_safety_v0: Conservative multichannel EQ polish with safety gating.

Applies a gentle low-mid peaking cut plus high-shelf trim on program channels
while preserving dialogue center and LFE untouched.  Processing is gated by
channel RMS activity and capped by a headroom guard to stay conservative.

Design goals
------------
- Layout-safe: channel routing uses ``LayoutContext`` + semantic speaker lookup.
- Bounded authority: center and LFE are never modified.
- Conservative defaults: mild subtractive EQ only (no boosts).
- Gated: channels below ``gate_rms_dbfs`` are left dry.
- Safety guard: when a channel is already near full-scale, wet influence is
  automatically reduced.
- Deterministic: same params + same input -> same output.
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

PLUGIN_ID = "eq_safety_v0"

SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"

_EPSILON = 1e-12


def _dbfs_peak(samples: Any) -> float:
    peak = float(samples.max()) if samples.size else 0.0
    peak = max(peak, float((-samples).max()) if samples.size else 0.0)
    if peak <= _EPSILON:
        return float("-inf")
    return 20.0 * math.log10(peak)


def _dbfs_rms(samples: Any) -> float:
    mean_square = float((samples * samples).mean()) if samples.size else 0.0
    if mean_square <= _EPSILON:
        return float("-inf")
    return 10.0 * math.log10(mean_square)


def _peaking_coeffs(
    *,
    sample_rate_hz: int,
    center_hz: float,
    q_value: float,
    gain_db: float,
) -> tuple[float, float, float, float, float]:
    amplitude = math.pow(10.0, gain_db / 40.0)
    omega = (2.0 * math.pi * center_hz) / float(sample_rate_hz)
    sine = math.sin(omega)
    cosine = math.cos(omega)
    alpha = sine / (2.0 * q_value)

    b0 = 1.0 + (alpha * amplitude)
    b1 = -2.0 * cosine
    b2 = 1.0 - (alpha * amplitude)
    a0 = 1.0 + (alpha / amplitude)
    a1 = -2.0 * cosine
    a2 = 1.0 - (alpha / amplitude)

    inv_a0 = 1.0 / a0
    return (b0 * inv_a0, b1 * inv_a0, b2 * inv_a0, a1 * inv_a0, a2 * inv_a0)


def _high_shelf_coeffs(
    *,
    sample_rate_hz: int,
    shelf_hz: float,
    gain_db: float,
) -> tuple[float, float, float, float, float]:
    amplitude = math.pow(10.0, gain_db / 40.0)
    omega = (2.0 * math.pi * shelf_hz) / float(sample_rate_hz)
    cosine = math.cos(omega)
    sine = math.sin(omega)
    alpha = (sine / 2.0) * math.sqrt(2.0)
    beta = 2.0 * math.sqrt(amplitude) * alpha
    b0 = amplitude * ((amplitude + 1.0) + ((amplitude - 1.0) * cosine) + beta)
    b1 = -2.0 * amplitude * ((amplitude - 1.0) + ((amplitude + 1.0) * cosine))
    b2 = amplitude * ((amplitude + 1.0) + ((amplitude - 1.0) * cosine) - beta)
    a0 = (amplitude + 1.0) - ((amplitude - 1.0) * cosine) + beta
    a1 = 2.0 * ((amplitude - 1.0) - ((amplitude + 1.0) * cosine))
    a2 = (amplitude + 1.0) - ((amplitude - 1.0) * cosine) - beta
    inv_a0 = 1.0 / a0
    return (b0 * inv_a0, b1 * inv_a0, b2 * inv_a0, a1 * inv_a0, a2 * inv_a0)


def _apply_biquad(
    signal: Any,
    coeffs: tuple[float, float, float, float, float],
) -> Any:
    import numpy as np

    b0, b1, b2, a1, a2 = coeffs
    out = np.empty(signal.shape[0], dtype=np.float64)
    z1 = 0.0
    z2 = 0.0
    for sample_index in range(int(signal.shape[0])):
        x0 = float(signal[sample_index])
        y0 = (b0 * x0) + z1
        z1 = (b1 * x0) - (a1 * y0) + z2
        z2 = (b2 * x0) - (a2 * y0)
        out[sample_index] = y0
    return out


class EqSafetyV0Plugin:
    """Conservative subtractive EQ with RMS gate + headroom guard."""

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

        low_mid_center_hz = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="low_mid_center_hz",
            default_value=320.0,
            minimum_value=120.0,
            maximum_value=800.0,
        )
        low_mid_trim_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="low_mid_trim_db",
            default_value=-1.5,
            minimum_value=-4.0,
            maximum_value=0.0,
        )
        high_shelf_hz = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="high_shelf_hz",
            default_value=8500.0,
            minimum_value=4000.0,
            maximum_value=18000.0,
        )
        high_shelf_trim_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="high_shelf_trim_db",
            default_value=-0.8,
            minimum_value=-3.0,
            maximum_value=0.0,
        )
        gate_rms_dbfs = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="gate_rms_dbfs",
            default_value=-42.0,
            minimum_value=-80.0,
            maximum_value=-6.0,
        )
        headroom_guard_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="headroom_guard_db",
            default_value=1.5,
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

        rendered = buf_f32_or_f64.copy()
        processing_dtype = buf_f32_or_f64.dtype.type

        nyquist = max(1.0, float(sample_rate) / 2.0)
        bounded_high_shelf_hz = min(max(high_shelf_hz, 4000.0), max(4000.0, nyquist - 1.0))
        peak_coeffs = _peaking_coeffs(
            sample_rate_hz=sample_rate,
            center_hz=low_mid_center_hz,
            q_value=0.8,
            gain_db=low_mid_trim_db,
        )
        shelf_coeffs = _high_shelf_coeffs(
            sample_rate_hz=sample_rate,
            shelf_hz=bounded_high_shelf_hz,
            gain_db=high_shelf_trim_db,
        )

        gated_out_count = 0
        guarded_count = 0
        processed_count = 0

        if bypass or not process_slots:
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = "Bypass enabled; conservative EQ safety stage skipped."
            else:
                stage_what = "plugin stage applied (no eligible channels)"
                stage_why = "Only protected channels (center/LFE) present; EQ safety did not process."
        else:
            stage_what = "plugin stage applied"
            for slot in process_slots:
                dry64 = buf_f32_or_f64[slot].astype(np.float64, copy=False)
                rms_dbfs = _dbfs_rms(dry64)
                if rms_dbfs < gate_rms_dbfs:
                    gated_out_count += 1
                    continue

                wet64 = _apply_biquad(dry64, peak_coeffs)
                wet64 = _apply_biquad(wet64, shelf_coeffs)
                wet64 = np.clip(wet64, -1.0, 1.0)

                effective_mix = macro_mix
                peak_dbfs = _dbfs_peak(dry64)
                if peak_dbfs > (-1.0 * headroom_guard_db):
                    effective_mix = min(effective_mix, 0.35)
                    guarded_count += 1

                if effective_mix <= 0.0:
                    continue
                if effective_mix >= 1.0:
                    rendered[slot] = wet64.astype(processing_dtype, copy=False)
                else:
                    blended = np.clip(
                        (dry64 * (1.0 - effective_mix)) + (wet64 * effective_mix),
                        -1.0,
                        1.0,
                    )
                    rendered[slot] = blended.astype(processing_dtype, copy=False)
                processed_count += 1

            stage_why = (
                f"Conservative subtractive EQ processed {processed_count} channel(s), "
                f"gated {gated_out_count}, headroom-guarded {guarded_count}."
            )

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "low_mid_center_hz", "value": low_mid_center_hz},
                {"name": "low_mid_trim_db", "value": low_mid_trim_db},
                {"name": "high_shelf_hz", "value": bounded_high_shelf_hz},
                {"name": "high_shelf_trim_db", "value": high_shelf_trim_db},
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
