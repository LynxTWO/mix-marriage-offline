"""Helpers for export-facing channel layout behavior."""

from __future__ import annotations

from typing import Sequence

_SPK_TO_FFMPEG_TOKEN: dict[str, str] = {
    "SPK.L": "FL",
    "SPK.R": "FR",
    "SPK.C": "FC",
    "SPK.LFE": "LFE",
    "SPK.LFE2": "LFE2",
    "SPK.LS": "SL",
    "SPK.RS": "SR",
    "SPK.LRS": "BL",
    "SPK.RRS": "BR",
    "SPK.FLC": "FLC",
    "SPK.FRC": "FRC",
    "SPK.BC": "BC",
    "SPK.TC": "TC",
    "SPK.TFL": "TFL",
    "SPK.TFC": "TFC",
    "SPK.TFR": "TFR",
    "SPK.TRL": "TBL",
    "SPK.TBC": "TBC",
    "SPK.TRR": "TBR",
}

_DUAL_LFE_WARNING_DIRECTOUT = (
    "Dual-LFE WAV export uses conservative channel-mask strategy: "
    "WAVEFORMATEXTENSIBLE DIRECTOUT (mask=0)."
)
_DUAL_LFE_WARNING_COMPAT = (
    "Some playback/import tools cannot preserve LFE2 and may relabel or drop the second LFE."
)
_DUAL_LFE_VALIDATION_PREFIX = (
    "How to validate: compare render_report channel_order and ffprobe channel_layout"
)


def _normalized_channel_order(channel_order: Sequence[str] | None) -> list[str]:
    if channel_order is None:
        return []
    return [
        str(channel).strip()
        for channel in channel_order
        if isinstance(channel, str) and str(channel).strip()
    ]


def has_dual_lfe_channel_order(channel_order: Sequence[str] | None) -> bool:
    """Return True when channel order contains both LFE and LFE2."""
    normalized = _normalized_channel_order(channel_order)
    return "SPK.LFE" in normalized and "SPK.LFE2" in normalized


def ffmpeg_layout_string_from_channel_order(
    channel_order: Sequence[str] | None,
) -> str | None:
    """Return explicit FFmpeg ``-channel_layout`` string for a SPK.* order."""
    normalized = _normalized_channel_order(channel_order)
    if not normalized:
        return None
    tokens: list[str] = []
    for speaker_id in normalized:
        token = _SPK_TO_FFMPEG_TOKEN.get(speaker_id)
        if token is None:
            return None
        tokens.append(token)
    return "+".join(tokens)


def dual_lfe_wav_export_warnings(
    *,
    channel_order: Sequence[str] | None,
    ffmpeg_layout_string: str | None = None,
) -> list[str]:
    """Return deterministic dual-LFE WAV export warnings/instructions."""
    if not has_dual_lfe_channel_order(channel_order):
        return []
    warnings = [
        _DUAL_LFE_WARNING_DIRECTOUT,
        _DUAL_LFE_WARNING_COMPAT,
    ]
    normalized_layout = (ffmpeg_layout_string or "").strip()
    if normalized_layout:
        warnings.append(
            f"{_DUAL_LFE_VALIDATION_PREFIX}; expect: {normalized_layout}"
        )
    else:
        warnings.append(
            "How to validate: verify render_report channel_order includes both "
            "SPK.LFE and SPK.LFE2."
        )
    return warnings
