"""Determinism + visual snapshot tests for GUI visualization dashboard v1.1."""

from __future__ import annotations

from dataclasses import replace

from mmo.gui.dashboard import (
    DashboardTelemetry,
    build_dashboard_surface_snapshot,
    build_object_projections,
    build_speaker_projections,
    build_visualization_frame,
    classify_correlation_risk,
    default_dashboard_telemetry,
    frame_signature,
    surface_snapshot_signature,
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
        live_what="Tighten depth contour",
        live_why="Phase-safe spatial polish",
        live_where=("LEAD VOX", "FX WIDE", "HEIGHT AIR"),
    )


def test_dashboard_frame_signature_is_deterministic_for_fixed_input() -> None:
    telemetry = _fixed_telemetry()
    frame_a = build_visualization_frame(telemetry, tick=24)
    frame_b = build_visualization_frame(telemetry, tick=24)
    assert frame_a == frame_b
    assert frame_signature(frame_a) == frame_signature(frame_b)
    assert frame_signature(frame_a) == "2db5a09e6613385483afbaa2cfc7231ff685efd741d2b42e1fa44b91a256d40c"


def test_dashboard_surface_snapshot_signature_is_deterministic() -> None:
    telemetry = _fixed_telemetry()
    frame = build_visualization_frame(telemetry, tick=24)
    snapshot_a = build_dashboard_surface_snapshot(frame)
    snapshot_b = build_dashboard_surface_snapshot(frame)
    assert snapshot_a == snapshot_b
    assert surface_snapshot_signature(frame) == "311043d2e1e511d04e56a03cb2149c3284c5213187af899ffcee98b75116d9b5"


def test_dashboard_frame_changes_deterministically_across_ticks() -> None:
    telemetry = _fixed_telemetry()
    frame_a = build_visualization_frame(telemetry, tick=8)
    frame_b = build_visualization_frame(telemetry, tick=9)
    assert frame_signature(frame_a) != frame_signature(frame_b)
    assert surface_snapshot_signature(frame_a) != surface_snapshot_signature(frame_b)


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


def test_intent_cards_have_explainability_fields() -> None:
    telemetry = _fixed_telemetry()
    frame = build_visualization_frame(telemetry, tick=24)
    assert len(frame.intent_cards) == 3
    for row in frame.intent_cards:
        assert row.what
        assert row.why
        assert row.where
        assert 0.0 <= row.confidence <= 1.0
        assert row.badge in {"LOCKED", "READY", "WATCH"}


def test_correlation_risk_thresholds_are_stable() -> None:
    assert classify_correlation_risk(-0.7) == "high"
    assert classify_correlation_risk(-0.2) == "medium"
    assert classify_correlation_risk(0.1) == "low"
