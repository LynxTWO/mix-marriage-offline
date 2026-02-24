"""stereo_widener_v0: Conservative M/S stereo width adjustment for FL/FR pair.

Applies mid-side (M/S) encoding to the front left and front right channels to
adjust perceived stereo width.  All other channels — surrounds, heights, LFE,
center — pass through completely unchanged.

Design goals
------------
- Layout-safe: FL/FR slots located via ``layout_ctx.index_of(SpeakerPosition.FL/FR)``
  rather than hard-coded indices.  Works for SMPTE (slots 0,1), FILM (slots 0,2),
  LOGIC_PRO (slots 0,1), VST3 (slots 0,1), and AAF.
- Conservative default: ``width=1.2`` adds a subtle +20% side content — noticeable
  but not aggressive.  ``width=1.0`` is a bit-exact dry-pass.
- LFE sovereign and center-safe: only FL and FR are processed.
- Deterministic: no random state; same params + same audio → same output.
- Evidence: populates ``ctx.evidence_collector`` with FL/FR slot indices, the
  effective width scalar, and a reference to ``GATE.DOWNMIX_SIMILARITY_MEASURED``.

M/S mathematics
---------------
    M = (L + R)           (sum / mono)
    S = (L - R)           (difference / side)
    L_out = (M + S * w) / 2
    R_out = (M - S * w) / 2

    width=1.0  → identity (no change)
    width=0.0  → full mono (S zeroed)
    width=2.0  → maximum stereo expansion

Supported standards: SMPTE, FILM, LOGIC_PRO, VST3, AAF
Preferred standard : SMPTE (canonical internal order)
"""

from __future__ import annotations

from typing import Any

from mmo.core.speaker_layout import SpeakerPosition
from mmo.dsp.plugins.base import (
    LayoutContext,
    PluginContext,
    optional_float_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "stereo_widener_v0"

SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"


class StereoWidenerV0Plugin:
    """Adjust FL/FR stereo width using M/S processing; all other channels untouched."""

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
        """Process multichannel buffer: M/S width on FL/FR only.

        Parameters
        ----------
        buf_f32_or_f64 : ndarray, shape (channels, samples)
            Input PCM buffer.
        sample_rate : int
            Not used for this plugin; retained for protocol compliance.
        params : dict
            ``width``     float [0.0, 2.0], default 1.2  (1.0 = identity)
            ``bypass``    bool,              default False
            ``macro_mix`` float [0, 1],      default 1.0
        ctx : PluginContext
        layout_ctx : LayoutContext
        """
        import numpy as np

        del sample_rate  # not used

        # ---- parameter parsing -------------------------------------------
        width = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="width",
            default_value=1.2,
            minimum_value=0.0,
            maximum_value=2.0,
        )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID, params=params
        )

        # ---- layout routing -----------------------------------------------
        fl_slot = layout_ctx.index_of(SpeakerPosition.FL)
        fr_slot = layout_ctx.index_of(SpeakerPosition.FR)

        processing_dtype = buf_f32_or_f64.dtype.type
        rendered = buf_f32_or_f64.copy()

        can_process = fl_slot is not None and fr_slot is not None and fl_slot != fr_slot

        if bypass or not can_process:
            if bypass:
                stage_what = "plugin stage bypassed"
                stage_why = (
                    "Bypass enabled; FL/FR stereo width unchanged "
                    f"(fl_slot={fl_slot}, fr_slot={fr_slot})."
                )
            else:
                stage_what = "plugin stage applied (no FL/FR pair)"
                stage_why = (
                    f"FL/FR channel pair not found in layout "
                    f"(fl_slot={fl_slot}, fr_slot={fr_slot}); "
                    "buffer passed through unchanged."
                )
        else:
            stage_what = "plugin stage applied"
            dry_l = buf_f32_or_f64[fl_slot].astype(np.float64, copy=False)
            dry_r = buf_f32_or_f64[fr_slot].astype(np.float64, copy=False)

            # M/S encoding
            mid = dry_l + dry_r
            side = dry_l - dry_r

            # Apply width to side channel
            wet_l = (mid + side * float(width)) * 0.5
            wet_r = (mid - side * float(width)) * 0.5

            wet_l = np.clip(wet_l, -1.0, 1.0)
            wet_r = np.clip(wet_r, -1.0, 1.0)

            if macro_mix <= 0.0:
                stage_why = "macro_mix=0 preserved dry FL/FR signal."
            elif macro_mix >= 1.0:
                rendered[fl_slot] = wet_l.astype(processing_dtype, copy=False)
                rendered[fr_slot] = wet_r.astype(processing_dtype, copy=False)
                stage_why = (
                    f"M/S width={width:.2f} applied to FL (slot {fl_slot}) "
                    f"and FR (slot {fr_slot})."
                )
            else:
                blended_l = np.clip(
                    dry_l * (1.0 - macro_mix) + wet_l * macro_mix, -1.0, 1.0
                )
                blended_r = np.clip(
                    dry_r * (1.0 - macro_mix) + wet_r * macro_mix, -1.0, 1.0
                )
                rendered[fl_slot] = blended_l.astype(processing_dtype, copy=False)
                rendered[fr_slot] = blended_r.astype(processing_dtype, copy=False)
                stage_why = (
                    f"M/S width={width:.2f} blended at macro_mix={macro_mix:.2f} "
                    f"on FL (slot {fl_slot}) and FR (slot {fr_slot})."
                )

        ctx.evidence_collector.set(
            stage_what=stage_what,
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "width", "value": width},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 1.0 if bypass else 0.0},
                {"name": "fl_slot", "value": float(fl_slot) if fl_slot is not None else -1.0},
                {"name": "fr_slot", "value": float(fr_slot) if fr_slot is not None else -1.0},
            ],
            notes=[
                f"layout_standard={layout_ctx.layout.standard.value}",
                "Gate reference: GATE.DOWNMIX_SIMILARITY_MEASURED verified post-render.",
            ],
        )
        return rendered
