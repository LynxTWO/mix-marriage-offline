"""Stable, deterministic DashboardTelemetry fixtures for capture and testing.

These fixtures are synthetic — they do not require real audio stem files.
Both functions are pure and return the same value on every call.
"""

from __future__ import annotations

from dataclasses import replace

from mmo.gui.dashboard import DashboardTelemetry, default_dashboard_telemetry
from mmo.core.speaker_layout import LayoutStandard


def safe_dashboard_telemetry() -> DashboardTelemetry:
    """Return a stable telemetry snapshot representing a healthy mix run.

    - 5.1 surround layout (LAYOUT.5_1)
    - High confidence (0.84), good progress (0.72)
    - Low stereo-correlation risk (0.55 — safe zone)
    - Four object tokens so intent cards render
    """
    return replace(
        default_dashboard_telemetry(),
        layout_id="LAYOUT.5_1",
        layout_standard=LayoutStandard.SMPTE.value,
        progress=0.72,
        confidence=0.84,
        correlation=0.55,
        mood_line="Signal path stable. Confidence high across all stems.",
        explain_line=(
            "All stems aligned to SMPTE 5.1. "
            "Stereo correlation is healthy. Ready to render."
        ),
        object_tokens=("kick.wav", "bass.wav", "lead_vox.wav", "fx_reverb.wav"),
        live_what="Mapping stems to 5.1 output channels",
        live_why="Layout LAYOUT.5_1 selected; all required positions confirmed",
        live_where=("FL", "FR", "FC", "BL", "BR"),
    )


def extreme_dashboard_telemetry() -> DashboardTelemetry:
    """Return a stable telemetry snapshot representing a high-risk run state.

    - Stereo layout (LAYOUT.2_0) — narrower field
    - Low confidence (0.31), mid progress (0.50)
    - High negative correlation (-0.75) — red-zone risk
    - Object tokens present so intent cards fire with WATCH badges
    """
    return replace(
        default_dashboard_telemetry(),
        layout_id="LAYOUT.2_0",
        layout_standard=LayoutStandard.SMPTE.value,
        progress=0.50,
        confidence=0.31,
        correlation=-0.75,
        mood_line="Phase conflict detected. Correlation risk is high.",
        explain_line=(
            "Stereo correlation is negative (-0.75). "
            "Check phase alignment between stems before rendering."
        ),
        object_tokens=("kick.wav", "bass.wav", "pad.wav"),
        live_what="Detecting phase relationship across stems",
        live_why="Correlation below safe threshold; mix may cancel in mono",
        live_where=("FL", "FR"),
    )
