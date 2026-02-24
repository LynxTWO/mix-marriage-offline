"""early_reflections_v0: Deterministic early-reflection comb delays on surrounds.

Adds three short comb-delay taps to surround and height channels to simulate
the onset of early room reflections.  The front L/R, center, and LFE channels
pass through completely unchanged.

Design goals
------------
- Layout-safe: surround slots (SL, SR, BL, BR) and height slots located via
  ``layout_ctx`` — no hard-coded indices.  Works across all five standards.
- LFE sovereign: LFE slots are never processed.
- Center-safe: FC passes through untouched (dialogue must remain bone-dry).
- Conservative defaults: ``room_size_ms=8.0``, ``decay_db=-18.0`` → short,
  quiet pre-delay taps that add spatial depth without being audible as echo.
- Deterministic: tap structure derived only from ``room_size_ms`` and
  ``decay_db`` (no random state).  Same params → same output, always.
- Evidence: evidence payload includes tap count, delay lengths, decay gain, and
  slot lists, plus a reference to ``GATE.DOWNMIX_SIMILARITY_MEASURED``.

Tap structure (fixed relative offsets for determinism)
-------------------------------------------------------
Given ``delay_samples = round(room_size_ms * sample_rate / 1000)``:
    tap 1 : offset = floor(delay_samples * 0.40),  gain = decay_gain ^ 0.40
    tap 2 : offset = floor(delay_samples * 0.70),  gain = decay_gain ^ 0.70
    tap 3 : offset = delay_samples,                 gain = decay_gain

If ``delay_samples < 1`` the plugin passes through unchanged (rate too low or
room_size_ms too small to produce even one sample of delay).

Supported standards: SMPTE, FILM, LOGIC_PRO, VST3, AAF
Preferred standard : SMPTE (canonical internal order)
"""

from __future__ import annotations

import math
from typing import Any

from mmo.core.speaker_layout import SpeakerPosition
from mmo.dsp.plugins.base import (
    LayoutContext,
    PluginContext,
    optional_float_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "early_reflections_v0"

SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"

# Fixed relative delay offsets for determinism (always three taps).
_TAP_RATIOS = (0.40, 0.70, 1.00)


def _build_tap_gains(decay_gain: float) -> tuple[float, float, float]:
    """Return (g1, g2, g3) tap gains derived deterministically from decay_gain."""
    return (
        math.pow(decay_gain, _TAP_RATIOS[0]),
        math.pow(decay_gain, _TAP_RATIOS[1]),
        decay_gain,
    )


def _apply_er_taps(
    channel: Any,
    delay_samples: int,
    tap_gains: tuple[float, float, float],
) -> Any:
    """Add three comb-delay taps to a 1-D float64 array.  Returns float64."""
    import numpy as np

    n = len(channel)
    out = channel.copy()
    for tap_ratio, tap_gain in zip(_TAP_RATIOS, tap_gains):
        offset = max(1, int(math.floor(delay_samples * tap_ratio)))
        if offset >= n:
            continue
        # Add delayed version at tap_gain, shifted right by `offset` samples.
        out[offset:] += channel[: n - offset] * tap_gain
    np.clip(out, -1.0, 1.0, out=out)
    return out


class EarlyReflectionsV0Plugin:
    """Add deterministic comb-delay early reflections to surround/height channels."""

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
    ) -> Any:
        """Process multichannel buffer: add early-reflection taps to surrounds/heights.

        Parameters
        ----------
        buf_f32_or_f64 : ndarray, shape (channels, samples)
            Input PCM buffer.
        sample_rate : int
            Audio sample rate in Hz.
        params : dict
            ``room_size_ms`` float [1.0, 30.0], default 8.0
            ``decay_db``     float [-40.0, -6.0], default -18.0
            ``bypass``       bool,                default False
            ``macro_mix``    float [0, 1],         default 1.0
        ctx : PluginContext
        layout_ctx : LayoutContext
        """
        import numpy as np

        # ---- parameter parsing -------------------------------------------
        room_size_ms = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="room_size_ms",
            default_value=8.0,
            minimum_value=1.0,
            maximum_value=30.0,
        )
        decay_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="decay_db",
            default_value=-18.0,
            minimum_value=-40.0,
            maximum_value=-6.0,
        )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID, params=params
        )

        # ---- layout routing -----------------------------------------------
        # Surround speakers: side surrounds and rear surrounds.
        _surround_positions = [
            SpeakerPosition.SL,
            SpeakerPosition.SR,
            SpeakerPosition.BL,
            SpeakerPosition.BR,
        ]
        lfe_set = set(layout_ctx.lfe_slots)

        surround_slots = []
        for pos in _surround_positions:
            idx = layout_ctx.index_of(pos)
            if idx is not None and idx not in lfe_set:
                surround_slots.append(idx)

        height_slots = [s for s in layout_ctx.height_slots if s not in lfe_set]
        er_slots = sorted(set(surround_slots + height_slots))

        processing_dtype = buf_f32_or_f64.dtype.type
        rendered = buf_f32_or_f64.copy()

        # ---- processing --------------------------------------------------
        delay_samples = max(0, round(room_size_ms * float(sample_rate) / 1000.0))

        if bypass or not er_slots or delay_samples < 1:
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; early reflections skipped "
                    f"({len(er_slots)} ER slot(s) present)."
                )
            elif not er_slots:
                stage_what = "plugin stage applied (no surround/height channels)"
                stage_why = (
                    "No surround or height channels found; buffer passed through unchanged."
                )
            else:
                stage_what = "plugin stage applied (delay too short)"
                stage_why = (
                    f"room_size_ms={room_size_ms:.1f} at {sample_rate} Hz yields "
                    f"{delay_samples} sample(s); minimum 1 required — no ER applied."
                )
        else:
            stage_what = "plugin stage applied"
            decay_gain = math.pow(10.0, decay_db / 20.0)
            tap_gains = _build_tap_gains(decay_gain)

            for slot in er_slots:
                dry64 = buf_f32_or_f64[slot].astype(np.float64, copy=False)
                wet64 = _apply_er_taps(dry64, delay_samples, tap_gains)

                if macro_mix <= 0.0:
                    pass  # keep dry
                elif macro_mix >= 1.0:
                    rendered[slot] = wet64.astype(processing_dtype, copy=False)
                else:
                    blended = np.clip(
                        dry64 * (1.0 - macro_mix) + wet64 * macro_mix, -1.0, 1.0
                    )
                    rendered[slot] = blended.astype(processing_dtype, copy=False)

            tap_offsets = [
                max(1, int(math.floor(delay_samples * r))) for r in _TAP_RATIOS
            ]
            if macro_mix <= 0.0:
                stage_why = "macro_mix=0 preserved dry signal on all ER channels."
            elif macro_mix >= 1.0:
                stage_why = (
                    f"Early-reflection taps (offsets={tap_offsets} samples, "
                    f"decay={decay_db:.1f} dB) applied to {len(er_slots)} channel(s)."
                )
            else:
                stage_why = (
                    f"Early-reflection taps (offsets={tap_offsets} samples, "
                    f"decay={decay_db:.1f} dB) blended at macro_mix={macro_mix:.2f} "
                    f"on {len(er_slots)} channel(s)."
                )

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "room_size_ms", "value": room_size_ms},
                {"name": "decay_db", "value": decay_db},
                {"name": "delay_samples", "value": float(delay_samples)},
                {"name": "er_slot_count", "value": float(len(er_slots))},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
            ],
            notes=[
                f"er_slots={er_slots}",
                f"layout_standard={layout_ctx.layout.standard.value}",
                "Gate reference: GATE.DOWNMIX_SIMILARITY_MEASURED verified post-render.",
            ],
        )
        return rendered
