"""height_air_v0: Conservative air-band high-shelf polish for height channels.

Applies a gentle high-shelf EQ boost to height speakers only (TFL, TFR, TBL,
TBR, TFC, TBC, TC).  All other channels — including the LFE — pass through
unchanged.

Design goals
------------
- Layout-safe: channel routing via ``layout_ctx.height_slots`` (never hard-coded
  indices).  Works identically for SMPTE, FILM, LOGIC_PRO, VST3, and AAF orders.
- LFE sovereign: LFE channels are never touched, even if accidentally declared
  as height in a malformed layout.
- Conservative: default shelf gain is +1.5 dB — enough to add "air" without
  audible EQ artifacts on a first pass.
- Deterministic: same params + same audio → same output, no random state.
- Evidence: populates ``ctx.evidence_collector`` with shelf frequency, gain,
  height slot list, and a reference to ``GATE.DOWNMIX_SIMILARITY_MEASURED``
  so post-render QA can validate translation fidelity.

Supported standards: SMPTE, FILM, LOGIC_PRO, VST3, AAF
Preferred standard : SMPTE (canonical internal order)
"""

from __future__ import annotations

import math
from typing import Any

from mmo.dsp.plugins.base import (
    LayoutContext,
    ProcessContext,
    PluginContext,
    PluginValidationError,
    coerce_float,
    optional_float_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "height_air_v0"

# Supported channel ordering standards — declared here for registry introspection.
SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"


# ---------------------------------------------------------------------------
# Biquad helpers (high-shelf)
# ---------------------------------------------------------------------------


def _high_shelf_coeffs(
    *,
    sample_rate_hz: int,
    shelf_hz: float,
    gain_db: float,
) -> tuple[float, float, float, float, float]:
    """Return normalised biquad coefficients (b0, b1, b2, a1, a2) for a high shelf."""
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


def _apply_biquad_1d(
    signal: Any,
    coeffs: tuple[float, float, float, float, float],
) -> Any:
    """Apply biquad filter to a 1-D float64 numpy array.  Returns float64 array."""
    import numpy as np

    b0, b1, b2, a1, a2 = coeffs
    out = np.empty(len(signal), dtype=np.float64)
    z1 = 0.0
    z2 = 0.0
    for i in range(len(signal)):
        x = float(signal[i])
        y = b0 * x + z1
        z1 = b1 * x - a1 * y + z2
        z2 = b2 * x - a2 * y
        out[i] = y
    return out


# ---------------------------------------------------------------------------
# Plugin implementation
# ---------------------------------------------------------------------------


class HeightAirV0Plugin:
    """Apply air-band high-shelf boost to height channels; pass all others through."""

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
        """Process multichannel buffer: air-band shelf on height channels only.

        Parameters
        ----------
        buf_f32_or_f64 : ndarray, shape (channels, samples)
            Input PCM buffer.  Channel count must match ``layout_ctx.num_channels``.
        sample_rate : int
            Audio sample rate in Hz.
        params : dict
            ``air_shelf_hz``  float [4000, 20000], default 10000.0
            ``air_gain_db``   float [0.0, 3.0],    default 1.5
            ``bypass``        bool,                 default False
            ``macro_mix``     float [0, 1],         default 1.0
        ctx : PluginContext
        layout_ctx : LayoutContext
        """
        del process_ctx
        import numpy as np

        # ---- parameter parsing -------------------------------------------
        air_shelf_hz = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="air_shelf_hz",
            default_value=10000.0,
            minimum_value=4000.0,
            maximum_value=20000.0,
        )
        air_gain_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="air_gain_db",
            default_value=1.5,
            minimum_value=0.0,
            maximum_value=3.0,
        )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID, params=params
        )

        # ---- layout routing -----------------------------------------------
        # Use layout_ctx — never hard-code indices.
        height_slots = layout_ctx.height_slots
        lfe_slots_set = set(layout_ctx.lfe_slots)
        # Guard: never apply shelf to LFE even if layout declares it as height.
        safe_height_slots = [s for s in height_slots if s not in lfe_slots_set]

        processing_dtype = buf_f32_or_f64.dtype.type
        rendered = buf_f32_or_f64.copy()

        if bypass or not safe_height_slots:
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    f"Bypass enabled; height air-band shelf skipped "
                    f"({len(safe_height_slots)} height slot(s) present)."
                )
            else:
                stage_what = "plugin stage applied (no height channels)"
                stage_why = (
                    "No height channels found in layout; buffer passed through unchanged."
                )
        else:
            stage_what = "plugin stage applied"
            nyquist = max(1.0, float(sample_rate) / 2.0)
            bounded_shelf_hz = min(max(air_shelf_hz, 4000.0), nyquist - 1.0)
            coeffs = _high_shelf_coeffs(
                sample_rate_hz=sample_rate,
                shelf_hz=bounded_shelf_hz,
                gain_db=air_gain_db,
            )

            for slot in safe_height_slots:
                dry64 = buf_f32_or_f64[slot].astype(np.float64, copy=False)
                wet64 = _apply_biquad_1d(dry64, coeffs)
                wet64 = np.clip(wet64, -1.0, 1.0)

                if macro_mix <= 0.0:
                    pass  # keep dry
                elif macro_mix >= 1.0:
                    rendered[slot] = wet64.astype(processing_dtype, copy=False)
                else:
                    blended = (
                        dry64 * (1.0 - macro_mix) + wet64 * macro_mix
                    )
                    rendered[slot] = np.clip(blended, -1.0, 1.0).astype(
                        processing_dtype, copy=False
                    )

            if macro_mix <= 0.0:
                stage_why = "macro_mix=0 preserved dry signal on all height channels."
            elif macro_mix >= 1.0:
                stage_why = (
                    f"Air-band high-shelf (+{air_gain_db:.1f} dB at "
                    f"{bounded_shelf_hz:.0f} Hz) applied to "
                    f"{len(safe_height_slots)} height channel(s)."
                )
            else:
                stage_why = (
                    f"Air-band high-shelf (+{air_gain_db:.1f} dB at "
                    f"{bounded_shelf_hz:.0f} Hz) blended at macro_mix={macro_mix:.2f} "
                    f"on {len(safe_height_slots)} height channel(s)."
                )

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "air_shelf_hz", "value": air_shelf_hz},
                {"name": "air_gain_db", "value": air_gain_db},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
                {"name": "height_slot_count", "value": float(len(safe_height_slots))},
            ],
            notes=[
                f"height_slots={safe_height_slots}",
                "Gate reference: GATE.DOWNMIX_SIMILARITY_MEASURED verified post-render.",
            ],
        )
        return rendered
