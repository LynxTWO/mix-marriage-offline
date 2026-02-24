from __future__ import annotations

from typing import Dict, List, Tuple

# WAVEFORMATEXTENSIBLE channel mask bit assignments (dwChannelMask field).
# Each tuple is (bit_mask, short_label).
# Bit order follows the Microsoft specification exactly; do NOT reorder.
# Labels map to canonical SPK.* IDs via _WAV_MASK_LABEL_TO_SPK_ID below.
#
# Height-channel bits (0x800–0x20000) were added to support 7.1.2, 5.1.4,
# 7.1.4 and future immersive formats.  Without them, positions_from_wav_mask()
# would silently truncate height channels in any file that carries them.
_CHANNEL_MASK_BITS: tuple[tuple[int, str], ...] = (
    (0x00000001, "FL"),   # Front Left
    (0x00000002, "FR"),   # Front Right
    (0x00000004, "FC"),   # Front Center
    (0x00000008, "LFE"),  # Low Frequency Effects
    (0x00000010, "BL"),   # Back Left  (rear surround in 5.1/7.1)
    (0x00000020, "BR"),   # Back Right
    (0x00000040, "FLC"),  # Front Left of Center  (SDDS screen channel)
    (0x00000080, "FRC"),  # Front Right of Center
    (0x00000100, "BC"),   # Back Center
    (0x00000200, "SL"),   # Side Left   (side surround in 7.1)
    (0x00000400, "SR"),   # Side Right
    # Height channels — added for 5.1.2 / 5.1.4 / 7.1.2 / 7.1.4 / future:
    (0x00000800, "TC"),   # Top Center
    (0x00001000, "TFL"),  # Top Front Left
    (0x00002000, "TFC"),  # Top Front Center
    (0x00004000, "TFR"),  # Top Front Right
    (0x00008000, "TBL"),  # Top Back Left   (a.k.a. Top Rear Left  / TRL)
    (0x00010000, "TBC"),  # Top Back Center
    (0x00020000, "TBR"),  # Top Back Right  (a.k.a. Top Rear Right / TRR)
)

_FFMPEG_LAYOUT_TOKENS: Dict[str, str] = {
    "fl": "FL",
    "fr": "FR",
    "fc": "FC",
    "lfe": "LFE",
    "bl": "BL",
    "br": "BR",
    "sl": "SL",
    "sr": "SR",
    "flc": "FLC",
    "frc": "FRC",
    "bc": "BC",
    # Height channel tokens (as reported by FFmpeg for immersive layouts):
    "tc": "TC",
    "tfl": "TFL",
    "tfc": "TFC",
    "tfr": "TFR",
    "tbl": "TBL",
    "tbc": "TBC",
    "tbr": "TBR",
}

# Map from WAVEFORMATEXTENSIBLE / FFmpeg short label → canonical SPK.* ID.
# Bridges the short-label namespace used in this module to the ontology IDs
# used in layouts.yaml and mmo.core.speaker_layout.SpeakerPosition.
_WAV_MASK_LABEL_TO_SPK_ID: Dict[str, str] = {
    "FL":  "SPK.L",
    "FR":  "SPK.R",
    "FC":  "SPK.C",
    "LFE": "SPK.LFE",
    "BL":  "SPK.LRS",  # Back Left  = Rear Surround Left
    "BR":  "SPK.RRS",  # Back Right = Rear Surround Right
    "FLC": "SPK.FLC",
    "FRC": "SPK.FRC",
    "BC":  "SPK.BC",
    "SL":  "SPK.LS",   # Side Left
    "SR":  "SPK.RS",   # Side Right
    "TC":  "SPK.TC",
    "TFL": "SPK.TFL",
    "TFC": "SPK.TFC",
    "TFR": "SPK.TFR",
    "TBL": "SPK.TRL",  # Top Back Left  = Top Rear Left  (same speaker, two names)
    "TBC": "SPK.TBC",
    "TBR": "SPK.TRR",  # Top Back Right = Top Rear Right
}

# Expand carefully. Keep existing keys and behavior stable.
_FFMPEG_LAYOUT_KNOWN: Dict[str, List[str]] = {
    # existing:
    "mono": ["FC"],
    "stereo": ["FL", "FR"],
    "2.1": ["FL", "FR", "LFE"],
    "quad": ["FL", "FR", "BL", "BR"],
    "4.0": ["FL", "FR", "FC", "BC"],
    "5.1": ["FL", "FR", "FC", "LFE", "BL", "BR"],
    "5.1(side)": ["FL", "FR", "FC", "LFE", "SL", "SR"],
    "7.1": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    "7.1(wide)": ["FL", "FR", "FC", "LFE", "FLC", "FRC", "SL", "SR"],

    # new: common FFmpeg layouts seen in the wild
    "3.0": ["FL", "FR", "FC"],
    "3.0(back)": ["FL", "FR", "BC"],
    "3.1": ["FL", "FR", "FC", "LFE"],
    "quad(side)": ["FL", "FR", "SL", "SR"],
    "4.1": ["FL", "FR", "FC", "LFE", "BC"],
    "5.0": ["FL", "FR", "FC", "BL", "BR"],
    "5.0(side)": ["FL", "FR", "FC", "SL", "SR"],
    "6.0": ["FL", "FR", "FC", "BC", "SL", "SR"],
    "6.0(front)": ["FL", "FR", "FLC", "FRC", "SL", "SR"],
    # 6.1 is ambiguous in practice. Provide a mapping for continuity,
    # but the validator will warn if "6.1" appears without a mask.
    "6.1": ["FL", "FR", "FC", "LFE", "BC", "SL", "SR"],
    "7.0": ["FL", "FR", "FC", "BL", "BR", "SL", "SR"],
    "7.0(front)": ["FL", "FR", "FC", "FLC", "FRC", "SL", "SR"],
    "7.1(wide-side)": ["FL", "FR", "FC", "LFE", "FLC", "FRC", "SL", "SR"],
    # tolerant alias: treat as 7.1
    "7.1(side)": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
}


def positions_from_wav_mask(channel_mask: int) -> List[str]:
    """Return positions in canonical mask-bit order (not padded to channel count)."""
    positions: List[str] = []
    for bit, label in _CHANNEL_MASK_BITS:
        if channel_mask & bit:
            positions.append(label)
    return positions


def sanitize_ffmpeg_layout_token(normalized_layout: str) -> str:
    """
    Preserve existing token behavior from meters_truth:
      - remove dots
      - (side)->_side, (wide)->_wide
    Add stable handling for other parenthetical modifiers by converting
    '(' and ')' to underscores and collapsing repeats.
    """
    token = normalized_layout.replace(".", "")
    token = token.replace("(side)", "_side").replace("(wide)", "_wide")
    token = token.replace("(", "_").replace(")", "")
    token = token.replace("-", "_")
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def channel_positions_from_mask(
    channel_mask: int | None, channels: int
) -> Tuple[List[str] | None, str]:
    """
    Returns (positions, mode_detail).
    positions is aligned to channel indices, or None if ambiguous.
    mode_detail matches existing tokens: mask_missing|mask_underspecified|mask_known|mask_trimmed
    """
    if not channel_mask:
        return None, "mask_missing"

    positions = positions_from_wav_mask(int(channel_mask))
    if len(positions) < channels:
        return None, "mask_underspecified"

    mode_detail = "mask_known"
    if len(positions) > channels:
        positions = positions[:channels]
        mode_detail = "mask_trimmed"
    return positions, mode_detail


def parse_ffmpeg_layout_to_positions(
    channel_layout: str, channels: int
) -> Tuple[List[str] | None, str]:
    """
    Returns (positions, layout_detail).
    layout_detail must preserve existing token strings for existing tests.
    """
    normalized = channel_layout.strip().lower()
    if not normalized:
        return None, "layout_missing"
    if normalized == "unknown":
        return None, "layout_unknown"

    if "+" in normalized:
        tokens = [t for t in normalized.split("+") if t]
        if not tokens:
            return None, "layout_unmapped"
        positions: List[str] = []
        for token in tokens:
            label = _FFMPEG_LAYOUT_TOKENS.get(token)
            if label is None:
                return None, "layout_unmapped"
            positions.append(label)
        if len(positions) < channels:
            return None, "layout_list_underspecified"
        if len(positions) > channels:
            return positions[:channels], "layout_list_trimmed"
        return positions, "layout_list_exact"

    positions = _FFMPEG_LAYOUT_KNOWN.get(normalized)
    if positions is None:
        return None, "layout_unmapped"
    if len(positions) < channels:
        return None, "layout_list_underspecified"
    if len(positions) > channels:
        return positions[:channels], "layout_trimmed"
    return list(positions), sanitize_ffmpeg_layout_token(normalized)


def lufs_weighting_order_and_mode(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None,
) -> tuple[list[str] | None, str, str]:
    """
    Return (positions_or_none, order_csv, mode_str) matching meters_truth tokens.
    """
    positions, mode_detail = channel_positions_from_mask(wav_channel_mask, channels)

    if positions is None:
        if channel_layout is None:
            return None, "unknown", "fallback_layout_missing"
        layout_positions, layout_detail = parse_ffmpeg_layout_to_positions(
            channel_layout, channels
        )
        if layout_positions is None:
            return None, "unknown", f"fallback_{layout_detail}"
        positions = layout_positions
        mode_prefix = "ffmpeg_layout_known"
        mode_trimmed = layout_detail in ("layout_trimmed", "layout_list_trimmed")
        mode_str = f"{mode_prefix}_{layout_detail}"
        use_layout = True
    else:
        mode_prefix = "mask_known"
        mode_trimmed = mode_detail == "mask_trimmed"
        mode_str = mode_prefix
        use_layout = False

    order_csv = ",".join(positions) if positions else "unknown"
    pos_set = set(positions)

    has_sl_sr = "SL" in pos_set or "SR" in pos_set
    if not use_layout:
        suffix = ""
        if has_sl_sr and channels >= 8:
            suffix = "71_sl_sr_surround_blbr_rear"
        elif not has_sl_sr and channels == 6 and ("BL" in pos_set or "BR" in pos_set):
            suffix = "51_blbr_surround"
        if suffix:
            mode_str = f"{mode_prefix}_{suffix}"
    else:
        if mode_str.startswith("ffmpeg_layout_known_layout_list_"):
            pass
        elif has_sl_sr:
            if channels == 6 and "LFE" in pos_set:
                mode_str = "ffmpeg_layout_known_51_sl_sr_surround"
            elif channels >= 8 and ("BL" in pos_set or "BR" in pos_set):
                mode_str = "ffmpeg_layout_known_71_sl_sr_surround_blbr_rear"

    if mode_trimmed:
        mode_str = f"{mode_str}_layout_trimmed" if use_layout else f"{mode_str}_mask_trimmed"

    return positions, order_csv, mode_str


def infer_lufs_order_and_mode(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None,
) -> Tuple[List[str] | None, str, str, dict]:
    """
    Shared inference for meters + validators.
    Returns:
      positions_or_none, order_csv, mode_str, diag
    diag is validator-friendly, NumPy-free.
    """
    diag: dict = {
        "channels": channels,
        "wav_channel_mask": wav_channel_mask,
        "channel_layout": channel_layout,
    }

    positions, mask_detail = channel_positions_from_mask(wav_channel_mask, channels)
    diag["mask_detail"] = mask_detail
    if channel_layout is not None:
        _, layout_detail = parse_ffmpeg_layout_to_positions(channel_layout, channels)
        diag["layout_detail"] = layout_detail

    positions, order_csv, mode_str = lufs_weighting_order_and_mode(
        channels, wav_channel_mask, channel_layout
    )
    return positions, order_csv, mode_str, diag
