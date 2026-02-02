from __future__ import annotations

from typing import Dict, List, Tuple

# Keep these tables identical to the ones previously in meters_truth.py
_CHANNEL_MASK_BITS: tuple[tuple[int, str], ...] = (
    (0x00000001, "FL"),
    (0x00000002, "FR"),
    (0x00000004, "FC"),
    (0x00000008, "LFE"),
    (0x00000010, "BL"),
    (0x00000020, "BR"),
    (0x00000040, "FLC"),
    (0x00000080, "FRC"),
    (0x00000100, "BC"),
    (0x00000200, "SL"),
    (0x00000400, "SR"),
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

    if positions is not None:
        order_csv = ",".join(positions) if positions else "unknown"
        return (
            positions,
            order_csv,
            "mask_known" if mask_detail != "mask_trimmed" else "mask_known_mask_trimmed",
            diag,
        )

    if channel_layout is None:
        return None, "unknown", "fallback_layout_missing", diag

    layout_positions, layout_detail = parse_ffmpeg_layout_to_positions(channel_layout, channels)
    diag["layout_detail"] = layout_detail

    if layout_positions is None:
        return None, "unknown", f"fallback_{layout_detail}", diag

    order_csv = ",".join(layout_positions) if layout_positions else "unknown"
    mode_str = f"ffmpeg_layout_known_{layout_detail}"
    if layout_detail in ("layout_trimmed", "layout_list_trimmed"):
        mode_str = f"{mode_str}_layout_trimmed"
    return layout_positions, order_csv, mode_str, diag
