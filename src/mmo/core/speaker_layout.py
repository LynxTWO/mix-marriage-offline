"""Speaker layout: semantic multichannel audio routing for deterministic offline mixing.

Why two worlds collide every day in real studios
-------------------------------------------------
Every modern studio audio workflow lives in one of two universes:

1. **SMPTE / ITU-R (broadcast/streaming/delivery)**
   The ordering baked into WAV (via WAVEFORMATEXTENSIBLE channel mask), FLAC,
   WavPack, Dolby Atmos bed inputs, and FFmpeg defaults.  Delivery format for
   Netflix, streaming, broadcast, and DCP (SMPTE 428-12).
   Canonical: L R C LFE Ls Rs [Lrs Rrs] [TFL TFR TBL TBR]

2. **Film / Cinema / Pro Tools (dub stage, theatrical)**
   The ordering used in pro mixing rooms, cinema dubbing stages, and most
   feature film pipelines.  Pro Tools internal tracks, metering, and panning
   all use this order.  Left Center Right Ls Rs LFE.
   Canonical: L C R Ls Rs LFE [Lrs Rrs] [TFL TFR TBL TBR]

When a Post-production engineer exports a 5.1 mix from Pro Tools and imports it
into a delivery chain that expects SMPTE order without remapping, the result is
dialogue in the surrounds and LFE as the front right speaker.  This happens in
real pipelines dozens of times per week across the industry.

Additionally, two more variants appear constantly at import time:

3. **Logic Pro / DTS (Apple ecosystem / older broadcast)**
   5.1: L R Ls Rs C LFE   (surrounds before center, LFE last)
   7.1: L R Lrs Rrs Ls Rs C LFE  (rear surrounds before sides, then center, LFE last)

4. **Steinberg VST3 (Cubase/Nuendo) for 7.1+**
   Puts rear surrounds (Lrs/Rrs) at slots 5-6 and side surrounds (Lss/Rss) at
   slots 7-8, opposite to SMPTE.  VST3 plugin speaker-arrangement IDs must be
   honoured or third-party plugins will apply wrong panning and EQ curves.

**Internal canonical: always SMPTE.**
All MMO processing uses SMPTE order internally.  Import from Film/Logic/VST3
remaps to SMPTE at the boundary.  Export remaps from SMPTE back to the target
standard at the write boundary.  This module is the single source of truth for
that remapping.

Public API
----------
- ``SpeakerPosition`` — str-enum of canonical speaker positions (values = SPK.* IDs
  used in ontology/layouts.yaml, so enum members can be compared directly with strings).
- ``LayoutStandard`` — str-enum of supported channel ordering standards.
- ``SpeakerLayout`` — immutable dataclass tying a layout ID, standard, and channel
  order together.  Use ``.index_of()`` to locate a speaker by semantic name; never
  hard-code slot indices.
- ``SMPTE_*`` / ``FILM_*`` / ``LOGIC_PRO_*`` / ``VST3_*`` — preset ``SpeakerLayout``
  constants for every supported channel count under each standard.
- ``remap_channels_fill()`` — reorder channel data between two ``SpeakerLayout``
  instances, zero-filling channels that are present in the target but absent from
  the source.  Prefer this over ``layout_negotiation.reorder_channels()`` at
  plugin I/O and file format boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# SpeakerPosition enum
# ---------------------------------------------------------------------------


class SpeakerPosition(str, Enum):
    """Canonical semantic speaker positions.

    Attribute names are the industry-standard abbreviations used in the SMPTE,
    Film, ITU-R, VST3, and AAF/OMF worlds.  Values are the ``SPK.*`` IDs used
    in ``ontology/layouts.yaml``, so enum members compare equal to their string
    equivalents::

        SpeakerPosition.FL == "SPK.L"   # True
        "SPK.L" == SpeakerPosition.FL   # True

    Mapping notes
    -------------
    - SL/SR  correspond to "side" surrounds at ~90-110° (ontology: SPK.LS/SPK.RS).
    - BL/BR  correspond to "rear/back" surrounds at ~135-150° (ontology: SPK.LRS/SPK.RRS).
    - TBL/TBR correspond to top-back/top-rear height speakers (ontology: SPK.TRL/SPK.TRR).
      The two naming conventions (Back vs Rear for heights) are industry aliases.
    - FLC/FRC are the "front left/right of center" positions used in SDDS cinema.
    - TFC/TBC/TC are reserved for 7.1.6 / 9.1.6 and future formats; channels at
      these positions are zeroed gracefully when not present in the input.
    """

    # Mono
    M = "SPK.M"         # Single mono channel

    # Front stereo pair
    FL = "SPK.L"        # Front Left
    FR = "SPK.R"        # Front Right

    # Center — dialogue anchor; never fold into LFE
    FC = "SPK.C"        # Front Center

    # LFE — low-frequency effects; always excluded from program loudness (ITU-R BS.1770)
    LFE = "SPK.LFE"     # Low Frequency Effects (subwoofer)

    # Side surrounds — at ear level, approximately 90-110°
    SL = "SPK.LS"       # Side Left Surround
    SR = "SPK.RS"       # Side Right Surround

    # Rear/back surrounds — behind listener, approximately 135-150°
    # Called "BL/BR" (Back Left/Right) in SMPTE notation and
    # "Lrs/Rrs" (Left Rear Surround / Right Rear Surround) in Film notation.
    BL = "SPK.LRS"      # Back Left (Rear Surround Left)
    BR = "SPK.RRS"      # Back Right (Rear Surround Right)

    # Height channels — top front pair
    TFL = "SPK.TFL"     # Top Front Left
    TFR = "SPK.TFR"     # Top Front Right

    # Height channels — top back/rear pair
    # Called "TBL/TBR" (Top Back Left/Right) in WAVEFORMATEXTENSIBLE and
    # "TRL/TRR" (Top Rear Left/Right) in the MMO ontology.  Same physical speakers.
    TBL = "SPK.TRL"     # Top Back/Rear Left
    TBR = "SPK.TRR"     # Top Back/Rear Right

    # Wide fronts — used in some cinema and broadcast workflows (~60°)
    FLW = "SPK.LW"      # Front Left Wide
    FRW = "SPK.RW"      # Front Right Wide

    # Front left/right of center — used in SDDS cinema (8-channel screen)
    FLC = "SPK.FLC"     # Front Left of Center  (~22.5°)
    FRC = "SPK.FRC"     # Front Right of Center (~-22.5°)

    # Back center — used in some 6.1 and legacy surround formats
    BC = "SPK.BC"       # Back Center

    # ----------------------------------------------------------------
    # Future / placeholder positions (7.1.6, 9.1.6, and beyond)
    # When a file or plugin declares one of these speakers and no mapping
    # exists in the active layout, the channel is zeroed gracefully.
    # ----------------------------------------------------------------
    TFC = "SPK.TFC"     # Top Front Center  (7.1.6 / 9.1.6 height ring)
    TBC = "SPK.TBC"     # Top Back Center   (7.1.6 / 9.1.6 height ring)
    TC = "SPK.TC"       # Top Center        (some 5.1.2 / Auro-3D configs)


# ---------------------------------------------------------------------------
# LayoutStandard enum
# ---------------------------------------------------------------------------


class LayoutStandard(str, Enum):
    """Channel ordering standards for multichannel PCM audio.

    The ordering standard determines the physical slot assignment of channels
    in a PCM buffer.  Two files with identical speaker content but different
    ordering standards will route audio to the wrong speakers if the mismatch
    is not detected and corrected.

    **SMPTE is always the internal canonical standard for MMO.**
    Import from other standards must remap to SMPTE.
    Export to other standards must remap from SMPTE.
    """

    SMPTE = "SMPTE"
    """SMPTE / ITU-R BS.775 / SMPTE 428-12.
    Used by: WAV (WAVEFORMATEXTENSIBLE), FLAC, WavPack, FFmpeg defaults,
    Dolby Atmos bed inputs, Netflix delivery, DCP.
    5.1: L R C LFE Ls Rs
    7.1: L R C LFE Ls Rs Lrs Rrs
    """

    FILM = "FILM"
    """Film / Cinema / Pro Tools internal.
    Used by: Pro Tools internal tracks and metering, cinema dubbing stages,
    most theatrical feature-film pipelines.
    5.1: L C R Ls Rs LFE
    7.1: L C R Ls Rs Lrs Rrs LFE
    """

    LOGIC_PRO = "LOGIC_PRO"
    """Logic Pro / DTS native.
    Very common in Apple ecosystem and older broadcast.
    5.1: L R Ls Rs C LFE   (surrounds before center, LFE at end)
    7.1: L R Lrs Rrs Ls Rs C LFE  (rear surrounds before sides)
    Tip: when a Logic Pro project bounces to multichannel WAV without
    remapping, this is the order you receive — even though the WAV header
    may claim "5.1" without a channel mask.
    """

    VST3 = "VST3"
    """Steinberg VST3 (Cubase / Nuendo) for 7.1 and above.
    Follows WAVEFORMATEXTENSIBLE for ≤5.1 (same as SMPTE), but for 7.1+
    puts rear surrounds (Lrs/Rrs) at slots 5-6 and side surrounds (Lss/Rss)
    at slots 7-8, opposite to SMPTE.
    7.1.4: L R C LFE Lrs Rrs Lss Rss TFL TFR TBL TBR
    VST3 plugins report speaker arrangement IDs (kSpeakerArr5_1, etc.) —
    the DSP chain must honour or remap those enums at plugin I/O.
    """

    AAF = "AAF"
    """AAF / OMF / XML interchange.
    These container formats typically carry explicit per-channel speaker labels
    or a channel mask; the ordering must be read from the metadata, not assumed.
    Use this standard tag when a layout was inferred from AAF metadata.
    """


# ---------------------------------------------------------------------------
# SpeakerLayout dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeakerLayout:
    """Fully specified speaker layout: layout ID, ordering standard, and channel slots.

    Every buffer, every plugin, every render path must carry a ``SpeakerLayout``
    so that no code downstream needs to guess channel indices from raw position
    numbers.  Use ``.index_of()`` to locate a speaker semantically.

    Parameters
    ----------
    layout_id:
        Canonical ``LAYOUT.*`` ID (matches ``ontology/layouts.yaml``).
        E.g. ``"LAYOUT.5_1"``, ``"LAYOUT.7_1_4"``.
    standard:
        Channel ordering standard for this buffer.
    channel_order:
        Ordered tuple of ``SpeakerPosition`` values, one per channel slot.
        Position at index *i* is the semantic speaker occupying PCM slot *i*.

    Examples
    --------
    >>> layout = SMPTE_5_1
    >>> layout.index_of(SpeakerPosition.LFE)
    3
    >>> layout.index_of(SpeakerPosition.FC)
    2
    >>> layout.is_lfe_channel(3)
    True
    """

    layout_id: str
    standard: LayoutStandard
    channel_order: tuple[SpeakerPosition, ...]

    @property
    def num_channels(self) -> int:
        """Number of channels in this layout."""
        return len(self.channel_order)

    def index_of(self, position: SpeakerPosition) -> int | None:
        """Return the 0-based PCM slot index of a speaker, or ``None`` if absent.

        Always use this instead of hard-coding indices like ``channel[3]``.
        """
        for i, pos in enumerate(self.channel_order):
            if pos == position:
                return i
        return None

    def is_lfe_channel(self, slot: int) -> bool:
        """Return ``True`` if the channel at ``slot`` is an LFE channel."""
        if 0 <= slot < len(self.channel_order):
            return self.channel_order[slot] == SpeakerPosition.LFE
        return False

    @property
    def lfe_slots(self) -> list[int]:
        """Return sorted list of all LFE PCM slot indices in this layout."""
        return [i for i, pos in enumerate(self.channel_order) if pos == SpeakerPosition.LFE]

    @property
    def height_slots(self) -> list[int]:
        """Return sorted list of height-channel PCM slot indices."""
        _height = {
            SpeakerPosition.TFL, SpeakerPosition.TFR,
            SpeakerPosition.TBL, SpeakerPosition.TBR,
            SpeakerPosition.TFC, SpeakerPosition.TBC,
            SpeakerPosition.TC,
        }
        return [i for i, pos in enumerate(self.channel_order) if pos in _height]

    def __repr__(self) -> str:
        ch_names = " ".join(pos.name for pos in self.channel_order)
        return (
            f"SpeakerLayout({self.layout_id!r}, {self.standard.value!r}, "
            f"[{ch_names}])"
        )


# ---------------------------------------------------------------------------
# Preset constants — SMPTE / ITU-R
# ---------------------------------------------------------------------------
#
# Slot assignments per SMPTE 428-12 / ITU-R BS.775 / BS.2051-3 / BS.2159.
# These are the orderings baked into WAV (WAVEFORMATEXTENSIBLE channel mask),
# FLAC, WavPack, FFmpeg defaults, and Dolby Atmos bed inputs.
#
# For a Dolby Atmos bed renderer, deviating from SMPTE order will route
# dialogue to the ceiling and LFE to the surrounds — Dolby's own integration
# guide is explicit about this.  Use these constants at the renderer boundary.

SMPTE_2_0 = SpeakerLayout(
    "LAYOUT.2_0",
    LayoutStandard.SMPTE,
    (SpeakerPosition.FL, SpeakerPosition.FR),
)

SMPTE_2_1 = SpeakerLayout(
    "LAYOUT.2_1",
    LayoutStandard.SMPTE,
    # 2.1: LFE slot is position 3; LFE is NEVER promoted to program audio.
    (SpeakerPosition.FL, SpeakerPosition.FR, SpeakerPosition.LFE),
)

SMPTE_5_1 = SpeakerLayout(
    "LAYOUT.5_1",
    LayoutStandard.SMPTE,
    # L=0 R=1 C=2 LFE=3 Ls=4 Rs=5
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
    ),
)

SMPTE_7_1 = SpeakerLayout(
    "LAYOUT.7_1",
    LayoutStandard.SMPTE,
    # L=0 R=1 C=2 LFE=3 Ls=4 Rs=5 Lrs=6 Rrs=7
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
    ),
)

SMPTE_5_1_2 = SpeakerLayout(
    "LAYOUT.5_1_2",
    LayoutStandard.SMPTE,
    # 5.1 bed + Top Front L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
    ),
)

SMPTE_5_1_4 = SpeakerLayout(
    "LAYOUT.5_1_4",
    LayoutStandard.SMPTE,
    # 5.1 bed + Top Front L/R + Top Rear L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    ),
)

SMPTE_7_1_2 = SpeakerLayout(
    "LAYOUT.7_1_2",
    LayoutStandard.SMPTE,
    # 7.1 bed + Top Front L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
    ),
)

SMPTE_7_1_4 = SpeakerLayout(
    "LAYOUT.7_1_4",
    LayoutStandard.SMPTE,
    # L=0 R=1 C=2 LFE=3 Ls=4 Rs=5 Lrs=6 Rrs=7 TFL=8 TFR=9 TBL=10 TBR=11
    # This is the strict Dolby Atmos bed order. Any deviation will misroute audio.
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    ),
)


# ---------------------------------------------------------------------------
# Preset constants — Film / Cinema / Pro Tools
# ---------------------------------------------------------------------------
#
# Pro Tools internal tracks, metering, and panning always use Film order.
# Pro Tools exports multichannel WAV in SMPTE order for ≤5.1, but can export
# in Film order for some workflows.  Always detect via channel mask on import.

FILM_2_0 = SpeakerLayout(
    "LAYOUT.2_0",
    LayoutStandard.FILM,
    (SpeakerPosition.FL, SpeakerPosition.FR),
)

FILM_2_1 = SpeakerLayout(
    "LAYOUT.2_1",
    LayoutStandard.FILM,
    # 2.1 Film: same as SMPTE — LFE is always last in small formats
    (SpeakerPosition.FL, SpeakerPosition.FR, SpeakerPosition.LFE),
)

FILM_5_1 = SpeakerLayout(
    "LAYOUT.5_1",
    LayoutStandard.FILM,
    # L=0 C=1 R=2 Ls=3 Rs=4 LFE=5
    # Centre (dialogue) moves to slot 1; LFE moves to the end.
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR, SpeakerPosition.LFE,
    ),
)

FILM_7_1 = SpeakerLayout(
    "LAYOUT.7_1",
    LayoutStandard.FILM,
    # L=0 C=1 R=2 Ls=3 Rs=4 Lrs=5 Rrs=6 LFE=7
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.LFE,
    ),
)

FILM_5_1_2 = SpeakerLayout(
    "LAYOUT.5_1_2",
    LayoutStandard.FILM,
    # Film 5.1 bed + Top Front L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR, SpeakerPosition.LFE,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
    ),
)

FILM_5_1_4 = SpeakerLayout(
    "LAYOUT.5_1_4",
    LayoutStandard.FILM,
    # Film 5.1 bed + Top Front L/R + Top Rear L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR, SpeakerPosition.LFE,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    ),
)

FILM_7_1_2 = SpeakerLayout(
    "LAYOUT.7_1_2",
    LayoutStandard.FILM,
    # Film 7.1 bed + Top Front L/R
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR, SpeakerPosition.LFE,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
    ),
)

FILM_7_1_4 = SpeakerLayout(
    "LAYOUT.7_1_4",
    LayoutStandard.FILM,
    # L=0 C=1 R=2 Ls=3 Rs=4 Lrs=5 Rrs=6 LFE=7 TFL=8 TFR=9 TBL=10 TBR=11
    (
        SpeakerPosition.FL, SpeakerPosition.FC, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.BL, SpeakerPosition.BR, SpeakerPosition.LFE,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    ),
)


# ---------------------------------------------------------------------------
# Preset constants — Logic Pro / DTS
# ---------------------------------------------------------------------------
#
# Logic Pro bounces and DTS-native files use this order.
# Extremely common in Apple-ecosystem workflows.  A "5.1 WAV" from Logic
# with no channel mask is very likely in LOGIC_PRO order.

LOGIC_PRO_5_1 = SpeakerLayout(
    "LAYOUT.5_1",
    LayoutStandard.LOGIC_PRO,
    # L=0 R=1 Ls=2 Rs=3 C=4 LFE=5
    # Surrounds come before center; LFE is at the very end.
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
    ),
)

LOGIC_PRO_7_1 = SpeakerLayout(
    "LAYOUT.7_1",
    LayoutStandard.LOGIC_PRO,
    # L=0 R=1 Lrs=2 Rrs=3 Ls=4 Rs=5 C=6 LFE=7
    # Rear surrounds precede side surrounds; center and LFE are at the end.
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
    ),
)


# ---------------------------------------------------------------------------
# Preset constants — Steinberg VST3 (Cubase / Nuendo) for 7.1+
# ---------------------------------------------------------------------------
#
# VST3 follows WAVEFORMATEXTENSIBLE for ≤5.1 (identical to SMPTE).
# For 7.1+, rear surrounds (Lrs/Rrs) occupy slots 5-6 and side surrounds
# (Lss/Rss) occupy slots 7-8 — the reverse of SMPTE slot assignment.
# VST3 plugin manifests report kSpeakerArr71 etc.; the host must convert
# or the surround panning will be inverted front-to-back.

VST3_7_1 = SpeakerLayout(
    "LAYOUT.7_1",
    LayoutStandard.VST3,
    # L=0 R=1 C=2 LFE=3 Lrs=4 Rrs=5 Lss=6 Rss=7
    # Note: Lrs/Rrs (rear) precede Lss/Rss (side) — opposite of SMPTE.
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.SL, SpeakerPosition.SR,
    ),
)

VST3_7_1_4 = SpeakerLayout(
    "LAYOUT.7_1_4",
    LayoutStandard.VST3,
    # L=0 R=1 C=2 LFE=3 Lrs=4 Rrs=5 Lss=6 Rss=7 TFL=8 TFR=9 TBL=10 TBR=11
    # Heights are the same as SMPTE; only the bed surrounds differ.
    (
        SpeakerPosition.FL, SpeakerPosition.FR,
        SpeakerPosition.FC, SpeakerPosition.LFE,
        SpeakerPosition.BL, SpeakerPosition.BR,
        SpeakerPosition.SL, SpeakerPosition.SR,
        SpeakerPosition.TFL, SpeakerPosition.TFR,
        SpeakerPosition.TBL, SpeakerPosition.TBR,
    ),
)


# ---------------------------------------------------------------------------
# Lookup table: layout_id × standard → SpeakerLayout preset
# ---------------------------------------------------------------------------
#
# Provides fast O(1) lookup when both layout_id and standard are known strings.
# ``get_preset()`` is the recommended entry point for code that loads layout
# information from a render contract.

_PRESET_TABLE: dict[tuple[str, str], SpeakerLayout] = {
    # SMPTE
    ("LAYOUT.2_0",   "SMPTE"):     SMPTE_2_0,
    ("LAYOUT.2_1",   "SMPTE"):     SMPTE_2_1,
    ("LAYOUT.5_1",   "SMPTE"):     SMPTE_5_1,
    ("LAYOUT.7_1",   "SMPTE"):     SMPTE_7_1,
    ("LAYOUT.5_1_2", "SMPTE"):     SMPTE_5_1_2,
    ("LAYOUT.5_1_4", "SMPTE"):     SMPTE_5_1_4,
    ("LAYOUT.7_1_2", "SMPTE"):     SMPTE_7_1_2,
    ("LAYOUT.7_1_4", "SMPTE"):     SMPTE_7_1_4,
    # FILM
    ("LAYOUT.2_0",   "FILM"):      FILM_2_0,
    ("LAYOUT.2_1",   "FILM"):      FILM_2_1,
    ("LAYOUT.5_1",   "FILM"):      FILM_5_1,
    ("LAYOUT.7_1",   "FILM"):      FILM_7_1,
    ("LAYOUT.5_1_2", "FILM"):      FILM_5_1_2,
    ("LAYOUT.5_1_4", "FILM"):      FILM_5_1_4,
    ("LAYOUT.7_1_2", "FILM"):      FILM_7_1_2,
    ("LAYOUT.7_1_4", "FILM"):      FILM_7_1_4,
    # LOGIC_PRO
    ("LAYOUT.5_1",   "LOGIC_PRO"): LOGIC_PRO_5_1,
    ("LAYOUT.7_1",   "LOGIC_PRO"): LOGIC_PRO_7_1,
    # VST3
    ("LAYOUT.7_1",   "VST3"):      VST3_7_1,
    ("LAYOUT.7_1_4", "VST3"):      VST3_7_1_4,
}


def get_preset(layout_id: str, standard: str | LayoutStandard) -> SpeakerLayout | None:
    """Return the preset ``SpeakerLayout`` for a layout × standard pair, or ``None``.

    Parameters
    ----------
    layout_id:
        Canonical ``LAYOUT.*`` ID.
    standard:
        Channel ordering standard as a ``LayoutStandard`` enum or string.
        ``"SMPTE"`` is the default; ``"FILM"``, ``"LOGIC_PRO"``, ``"VST3"``,
        and ``"AAF"`` are also supported.

    Returns
    -------
    ``SpeakerLayout`` preset if the combination is registered, else ``None``.
    """
    std_key = standard.value if isinstance(standard, LayoutStandard) else str(standard).upper()
    return _PRESET_TABLE.get((layout_id, std_key))


# ---------------------------------------------------------------------------
# Channel remapping
# ---------------------------------------------------------------------------


def remap_channels_fill(
    data: Any,
    from_layout: SpeakerLayout,
    to_layout: SpeakerLayout,
    *,
    fill_value: float = 0.0,
) -> Any:
    """Remap audio channel data between two ``SpeakerLayout`` instances.

    Unlike :func:`mmo.core.layout_negotiation.reorder_channels`, which silently
    **drops** channels present in ``to_order`` but absent from ``from_order``,
    this function **zero-fills** those slots.  This is the correct behaviour at:

    - Plugin I/O boundaries (the plugin always receives the expected slot count)
    - Upmix operations (e.g. 2.1 → 5.1: new speakers are silent, not missing)
    - DAW round-trip export (target layout slots must be populated)

    Identity fast path: if ``from_layout == to_layout``, ``data`` is returned
    unchanged (zero allocation, zero copy).

    Parameters
    ----------
    data:
        Per-channel data.  Supported types:

        * **NumPy array, shape** ``(channels,)`` — one value per channel.
        * **NumPy array, shape** ``(channels, samples)`` — full audio buffer.
        * **list** or **tuple** — one element per channel.

        Length (or first dimension) must equal ``from_layout.num_channels``.
    from_layout:
        Source ``SpeakerLayout``.
    to_layout:
        Target ``SpeakerLayout``.
    fill_value:
        Value inserted for channels present in ``to_layout`` but absent from
        ``from_layout``.  Default ``0.0`` (silence).  Use ``float("nan")``
        to detect unintended fills during testing.

    Returns
    -------
    Reordered / zero-filled data with length matching ``to_layout.num_channels``.
    Type matches the input: NumPy array → NumPy array, list → list, tuple → tuple.

    Raises
    ------
    ValueError
        If ``len(data)`` does not equal ``from_layout.num_channels``.

    Examples
    --------
    SMPTE 2.0 upmix to SMPTE 5.1 (FC, LFE, SL, SR are silent):

    >>> import numpy as np
    >>> stereo = np.ones((2, 1000))   # L and R channels
    >>> out = remap_channels_fill(stereo, SMPTE_2_0, SMPTE_5_1)
    >>> out.shape
    (6, 1000)
    >>> out[2].sum()   # FC is zero-filled
    0.0

    LFE pinning — LFE slot in target stays LFE; never promotes to program audio:

    >>> lfe_idx_src = SMPTE_2_1.index_of(SpeakerPosition.LFE)   # 2
    >>> out = remap_channels_fill(np.ones((3, 1000)), SMPTE_2_1, SMPTE_5_1)
    >>> lfe_idx_dst = SMPTE_5_1.index_of(SpeakerPosition.LFE)   # 3
    >>> out[lfe_idx_dst].sum() == 1000.0   # LFE preserved at its semantic slot
    True
    """
    if len(data) != from_layout.num_channels:
        raise ValueError(
            f"remap_channels_fill: data length {len(data)} does not match "
            f"from_layout.num_channels {from_layout.num_channels}."
        )

    # Identity fast path: same layout object or same channel order + standard.
    if from_layout == to_layout:
        return data

    from_positions = from_layout.channel_order
    to_positions = to_layout.channel_order

    # Build source index map: SpeakerPosition → source slot index.
    src_index: dict[SpeakerPosition, int] = {
        pos: i for i, pos in enumerate(from_positions)
    }

    # NumPy fast path — supports both (channels,) and (channels, samples).
    try:
        import numpy as _np  # noqa: PLC0415

        if isinstance(data, _np.ndarray):
            n_to = len(to_positions)
            if data.ndim == 2:
                n_samples = data.shape[1]
                out = _np.full((n_to, n_samples), fill_value, dtype=data.dtype)
                for dst_idx, pos in enumerate(to_positions):
                    src_idx = src_index.get(pos)
                    if src_idx is not None:
                        out[dst_idx] = data[src_idx]
            else:
                out = _np.full(n_to, fill_value, dtype=data.dtype)
                for dst_idx, pos in enumerate(to_positions):
                    src_idx = src_index.get(pos)
                    if src_idx is not None:
                        out[dst_idx] = data[src_idx]
            return out
    except ImportError:
        pass

    # Generic sequence path (list / tuple).
    result: list = []
    for pos in to_positions:
        src_idx = src_index.get(pos)
        if src_idx is not None:
            result.append(data[src_idx])
        else:
            result.append(fill_value)

    if isinstance(data, tuple):
        return tuple(result)
    return result
