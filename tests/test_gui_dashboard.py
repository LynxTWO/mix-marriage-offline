"""Determinism and layout-awareness tests for GUI visualization dashboard v1.1."""

from __future__ import annotations

from dataclasses import replace

from mmo.gui.dashboard import (
    DashboardTelemetry,
    build_object_projections,
    build_speaker_projections,
    build_visualization_frame,
    classify_correlation_risk,
    default_dashboard_telemetry,
    frame_signature,
)


def _fixed_telemetry() -> DashboardTelemetry:
    base = default_dashboard_telemetry()
    return replace(
        base,
        layout_id="LAYOUT.7_1_4",
        layout_standard="SMPTE",
        progress=0.63,
        confidence=0.81,
        correlation=0.42,
        object_tokens=("LEAD VOX", "FX WIDE", "HEIGHT AIR"),
        mood_line="The mix is breathing with stable center.",
        explain_line="Fixed telemetry for deterministic visualization tests.",
    )


def test_dashboard_frame_signature_is_deterministic_for_fixed_input() -> None:
    telemetry = _fixed_telemetry()
    frame_a = build_visualization_frame(telemetry, tick=24)
    frame_b = build_visualization_frame(telemetry, tick=24)
    assert frame_a == frame_b
    assert frame_signature(frame_a) == frame_signature(frame_b)
    assert frame_signature(frame_a) == "57eb6a447976ca11771d5643892f88eb318876061271f4e9b80a8824130958ca"


def test_dashboard_frame_changes_deterministically_across_ticks() -> None:
    telemetry = _fixed_telemetry()
    frame_a = build_visualization_frame(telemetry, tick=8)
    frame_b = build_visualization_frame(telemetry, tick=9)
    assert frame_signature(frame_a) != frame_signature(frame_b)


def test_speaker_projection_respects_layout_standard_slot_order() -> None:
    smpte = build_speaker_projections(layout_id="LAYOUT.5_1", layout_standard="SMPTE")
    film = build_speaker_projections(layout_id="LAYOUT.5_1", layout_standard="FILM")
    smpte_lfe_slot = next(row.slot_index for row in smpte if row.is_lfe)
    film_lfe_slot = next(row.slot_index for row in film if row.is_lfe)
    smpte_center_slot = next(row.slot_index for row in smpte if row.speaker_id == "FC")
    film_center_slot = next(row.slot_index for row in film if row.speaker_id == "FC")
    assert smpte_lfe_slot == 3
    assert film_lfe_slot == 5
    assert smpte_center_slot == 2
    assert film_center_slot == 1


def test_object_projection_is_sorted_unique_and_deterministic() -> None:
    objects_a = build_object_projections(
        layout_id="LAYOUT.7_1_4",
        layout_standard="SMPTE",
        object_tokens=("LEAD VOX", "FX WIDE", "LEAD VOX", "HEIGHT AIR"),
    )
    objects_b = build_object_projections(
        layout_id="LAYOUT.7_1_4",
        layout_standard="SMPTE",
        object_tokens=("FX WIDE", "HEIGHT AIR", "LEAD VOX"),
    )
    assert objects_a == objects_b
    assert [row.object_id for row in objects_a] == ["HEIGHT AIR", "FX WIDE", "LEAD VOX"]


def test_correlation_risk_thresholds_are_stable() -> None:
    assert classify_correlation_risk(-0.7) == "high"
    assert classify_correlation_risk(-0.2) == "medium"
    assert classify_correlation_risk(0.1) == "low"
