"""Deterministic visualization dashboard for the MMO desktop GUI.

The panel renders five live visual surfaces:
- musical-color spectrum
- vectorscope with confidence glow
- stereo correlation risk meter
- 3D speaker layout projection (layout-standard aware)
- object-placement preview
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from mmo.core.speaker_layout import (
    LayoutStandard,
    SpeakerLayout,
    SpeakerPosition,
    get_preset,
)

_THEME: dict[str, str] = {
    "bg": "#0A0A09",
    "surface": "#12110F",
    "surface_edge": "#2A2319",
    "panel": "#090908",
    "text": "#F2E8D2",
    "text_muted": "#B29F82",
    "accent_warm": "#D79B48",
    "accent_hot": "#F0B663",
    "accent_cool": "#5DA4A0",
    "risk_low": "#4FA06B",
    "risk_medium": "#D79B48",
    "risk_high": "#BE4D3D",
}

_THEME_GOLDEN_HOUR: dict[str, str] = {
    "bg": "#0D0900",
    "surface": "#160C00",
    "surface_edge": "#3C2C10",
    "panel": "#0A0600",
    "text": "#F8EDD0",
    "text_muted": "#C9A060",
    "accent_warm": "#E8A030",
    "accent_hot": "#F5C048",
    "accent_cool": "#A8B840",
    "risk_low": "#70A848",
    "risk_medium": "#E8A030",
    "risk_high": "#C84030",
}

_THEME_NEON_CLUB: dict[str, str] = {
    "bg": "#030308",
    "surface": "#080812",
    "surface_edge": "#181828",
    "panel": "#020206",
    "text": "#E8EEFF",
    "text_muted": "#7888CC",
    "accent_warm": "#FF6040",
    "accent_hot": "#FF8060",
    "accent_cool": "#40C8FF",
    "risk_low": "#40FF80",
    "risk_medium": "#FFCC00",
    "risk_high": "#FF2040",
}

THEMES: dict[str, dict[str, str]] = {
    "Golden Hour": _THEME_GOLDEN_HOUR,
    "Midnight Studio": _THEME,
    "Neon Club": _THEME_NEON_CLUB,
}


def get_theme(name: str) -> dict[str, str]:
    """Return a copy of the named theme dict; falls back to Midnight Studio."""
    return dict(THEMES.get(name, _THEME))


def list_theme_names() -> tuple[str, ...]:
    """Return sorted tuple of available theme names (stable, deterministic)."""
    return tuple(sorted(THEMES))


_CORRELATION_WARN_LTE = -0.2
_CORRELATION_ERROR_LTE = -0.6

_SPEAKER_WORLD: dict[SpeakerPosition, tuple[float, float, float]] = {
    SpeakerPosition.M: (0.0, 1.0, 0.0),
    SpeakerPosition.FL: (-1.0, 1.1, 0.0),
    SpeakerPosition.FR: (1.0, 1.1, 0.0),
    SpeakerPosition.FC: (0.0, 1.25, 0.05),
    SpeakerPosition.LFE: (0.0, 0.8, -0.45),
    SpeakerPosition.SL: (-1.25, 0.15, 0.05),
    SpeakerPosition.SR: (1.25, 0.15, 0.05),
    SpeakerPosition.BL: (-1.0, -0.9, 0.05),
    SpeakerPosition.BR: (1.0, -0.9, 0.05),
    SpeakerPosition.TFL: (-0.95, 1.05, 0.9),
    SpeakerPosition.TFR: (0.95, 1.05, 0.9),
    SpeakerPosition.TBL: (-0.95, -0.85, 0.9),
    SpeakerPosition.TBR: (0.95, -0.85, 0.9),
    SpeakerPosition.TFC: (0.0, 1.05, 0.9),
    SpeakerPosition.TBC: (0.0, -0.85, 0.9),
    SpeakerPosition.TC: (0.0, 0.1, 1.0),
    SpeakerPosition.FLW: (-1.35, 0.9, 0.0),
    SpeakerPosition.FRW: (1.35, 0.9, 0.0),
    SpeakerPosition.FLC: (-0.4, 1.2, 0.0),
    SpeakerPosition.FRC: (0.4, 1.2, 0.0),
    SpeakerPosition.BC: (0.0, -1.0, 0.0),
}

_SPEAKER_WORLD_BY_NAME: dict[str, tuple[float, float, float]] = {
    pos.name: coords for pos, coords in _SPEAKER_WORLD.items()
}


@dataclass(frozen=True)
class DashboardTelemetry:
    """Inputs used to deterministically synthesize dashboard visuals."""

    layout_id: str
    layout_standard: str
    progress: float
    confidence: float
    correlation: float
    mood_line: str
    explain_line: str
    object_tokens: tuple[str, ...]
    live_what: str = ""
    live_why: str = ""
    live_where: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpeakerProjection:
    speaker_id: str
    slot_index: int
    x: float
    y: float
    depth: float
    is_height: bool
    is_lfe: bool


@dataclass(frozen=True)
class ObjectProjection:
    object_id: str
    confidence: float
    x: float
    y: float
    depth: float


@dataclass(frozen=True)
class IntentCard:
    object_id: str
    what: str
    why: str
    where: tuple[str, ...]
    confidence: float
    badge: str


@dataclass(frozen=True)
class DashboardFrame:
    spectrum_levels: tuple[float, ...]
    vectorscope_points: tuple[tuple[float, float], ...]
    correlation: float
    correlation_risk: str
    speaker_points: tuple[SpeakerProjection, ...]
    object_points: tuple[ObjectProjection, ...]
    intent_cards: tuple[IntentCard, ...]
    mood_line: str
    explain_line: str


def default_dashboard_telemetry() -> DashboardTelemetry:
    return DashboardTelemetry(
        layout_id="LAYOUT.2_0",
        layout_standard=LayoutStandard.SMPTE.value,
        progress=0.0,
        confidence=0.0,
        correlation=0.2,
        mood_line="Signal path ready. The mix is breathing quietly.",
        explain_line="Awaiting live telemetry from the bounded pipeline.",
        object_tokens=(),
        live_what="",
        live_why="",
        live_where=(),
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(raw: Any, *, default: float) -> float:
    if isinstance(raw, (float, int)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except Exception:  # noqa: BLE001
        return float(default)


def _stable_seed(parts: Sequence[str]) -> int:
    data = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return int(digest[:16], 16)


def _normalize_standard(raw: str) -> str:
    candidate = str(raw).strip().upper()
    valid = {item.value for item in LayoutStandard}
    return candidate if candidate in valid else LayoutStandard.SMPTE.value


def _resolve_layout(layout_id: str, layout_standard: str) -> SpeakerLayout:
    standard = _normalize_standard(layout_standard)
    preset = get_preset(layout_id, standard)
    if preset is not None:
        return preset
    fallback = get_preset(layout_id, LayoutStandard.SMPTE.value)
    if fallback is not None:
        return fallback
    return get_preset("LAYOUT.2_0", LayoutStandard.SMPTE.value)  # type: ignore[return-value]


def _project_3d(x: float, y: float, z: float) -> tuple[float, float, float]:
    yaw = math.radians(32.0)
    pitch = math.radians(25.0)
    x_rot = (x * math.cos(yaw)) - (y * math.sin(yaw))
    y_rot = (x * math.sin(yaw)) + (y * math.cos(yaw))
    y_proj = (y_rot * math.cos(pitch)) - (z * math.sin(pitch))
    z_proj = (y_rot * math.sin(pitch)) + (z * math.cos(pitch))
    return (0.5 + (x_rot * 0.22), 0.54 - (y_proj * 0.18), z_proj)


def _resolve_label_positions(
    labels: list[tuple[float, float, float, float]],
    *,
    iterations: int = 18,
    repulsion: float = 1.4,
    canvas_w: float = 0.0,
    canvas_h: float = 0.0,
) -> list[tuple[float, float]]:
    """Force-directed nudge: push overlapping label bounding boxes apart.

    Each label is described as (cx, cy, w, h) — centre and full size.
    Returns final (cx, cy) positions in the same order as *labels*.

    Deterministic: no randomness; pairs are iterated in ascending index
    order so identical inputs always produce identical outputs.
    O(n²) per iteration — negligible for n ≤ 12 (max speakers per layout).
    """
    if not labels:
        return []
    positions: list[list[float]] = [[cx, cy] for cx, cy, _, _ in labels]
    sizes: list[tuple[float, float]] = [(w, h) for _, _, w, h in labels]
    n = len(positions)
    for _ in range(iterations):
        disp: list[list[float]] = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                min_dx = (sizes[i][0] + sizes[j][0]) * 0.5
                min_dy = (sizes[i][1] + sizes[j][1]) * 0.5
                ov_x = min_dx - abs(dx)
                ov_y = min_dy - abs(dy)
                if ov_x > 0.0 and ov_y > 0.0:
                    if ov_x <= ov_y:
                        push = ov_x * repulsion * 0.5
                        sign = 1.0 if dx >= 0.0 else -1.0
                        disp[i][0] -= sign * push
                        disp[j][0] += sign * push
                    else:
                        push = ov_y * repulsion * 0.5
                        sign = 1.0 if dy >= 0.0 else -1.0
                        disp[i][1] -= sign * push
                        disp[j][1] += sign * push
        for k in range(n):
            positions[k][0] += disp[k][0]
            positions[k][1] += disp[k][1]
    if canvas_w > 0.0 and canvas_h > 0.0:
        for k in range(n):
            hw = sizes[k][0] * 0.5
            hh = sizes[k][1] * 0.5
            positions[k][0] = max(hw, min(canvas_w - hw, positions[k][0]))
            positions[k][1] = max(hh, min(canvas_h - hh, positions[k][1]))
    return [(p[0], p[1]) for p in positions]


def _fallback_world(slot_index: int, count: int) -> tuple[float, float, float]:
    ring = max(1, count)
    theta = (2.0 * math.pi * slot_index) / float(ring)
    return (
        math.sin(theta) * 1.0,
        math.cos(theta) * 1.0,
        0.0,
    )


def build_speaker_projections(
    *,
    layout_id: str,
    layout_standard: str,
) -> tuple[SpeakerProjection, ...]:
    layout = _resolve_layout(layout_id, layout_standard)
    projections: list[SpeakerProjection] = []
    for slot_index, speaker in enumerate(layout.channel_order):
        world = _SPEAKER_WORLD.get(
            speaker,
            _fallback_world(slot_index, len(layout.channel_order)),
        )
        px, py, depth = _project_3d(*world)
        projections.append(
            SpeakerProjection(
                speaker_id=speaker.name,
                slot_index=slot_index,
                x=px,
                y=py,
                depth=depth,
                is_height=speaker in {
                    SpeakerPosition.TFL,
                    SpeakerPosition.TFR,
                    SpeakerPosition.TBL,
                    SpeakerPosition.TBR,
                    SpeakerPosition.TFC,
                    SpeakerPosition.TBC,
                    SpeakerPosition.TC,
                },
                is_lfe=speaker == SpeakerPosition.LFE,
            )
        )
    return tuple(sorted(projections, key=lambda row: (row.depth, row.slot_index, row.speaker_id)))


def build_object_projections(
    *,
    layout_id: str,
    layout_standard: str,
    object_tokens: Sequence[str],
) -> tuple[ObjectProjection, ...]:
    tokens = tuple(
        sorted(
            {
                token.strip()
                for token in object_tokens
                if isinstance(token, str) and token.strip()
            }
        )
    )
    if not tokens:
        tokens = ("CENTER FOCUS", "HEIGHT AIR", "LOW-END BED")

    rows: list[ObjectProjection] = []
    for token in tokens[:8]:
        seed = _stable_seed((layout_id, layout_standard, token))
        azimuth = ((seed % 3600) / 10.0) - 180.0
        distance = 0.35 + (((seed // 3600) % 400) / 1000.0)
        elevation = (((seed // 1440000) % 120) / 100.0) - 0.2
        confidence = 0.55 + (((seed // 1729) % 40) / 100.0)

        azimuth_rad = math.radians(azimuth)
        wx = math.sin(azimuth_rad) * distance
        wy = math.cos(azimuth_rad) * distance
        wz = elevation
        px, py, depth = _project_3d(wx, wy, wz)
        rows.append(
            ObjectProjection(
                object_id=token,
                confidence=_clamp(confidence, 0.0, 1.0),
                x=px,
                y=py,
                depth=depth,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.depth, row.object_id)))


_INTENT_WHY_VARIANTS: tuple[str, ...] = (
    "preserve center gravity while keeping width musical.",
    "maintain translation safety while lifting emotional motion.",
    "protect vocal focus without flattening the stereo scene.",
    "keep low-end anchors stable as height energy opens.",
)


def _intent_badge(confidence: float) -> str:
    if confidence >= 0.82:
        return "LOCKED"
    if confidence >= 0.68:
        return "READY"
    return "WATCH"


def _dedupe_tokens(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                token.strip()
                for token in tokens
                if isinstance(token, str) and token.strip()
            }
        )
    )


def _intent_where_slice(where_pool: Sequence[str], *, seed: int) -> tuple[str, ...]:
    if not where_pool:
        return ("signal-wide",)
    span = 1 + (seed % min(3, len(where_pool)))
    start = (seed // 11) % len(where_pool)
    return tuple(where_pool[(start + idx) % len(where_pool)] for idx in range(span))


def build_intent_cards(
    telemetry: DashboardTelemetry,
    *,
    object_points: Sequence[ObjectProjection],
) -> tuple[IntentCard, ...]:
    ranked = tuple(sorted(object_points, key=lambda row: (-row.confidence, row.object_id)))
    if not ranked:
        ranked = (
            ObjectProjection(
                object_id="CENTER FOCUS",
                confidence=_clamp(telemetry.confidence, 0.0, 1.0),
                x=0.5,
                y=0.5,
                depth=0.0,
            ),
        )
    where_pool = _dedupe_tokens(telemetry.live_where or telemetry.object_tokens)
    if not where_pool:
        where_pool = tuple(row.object_id for row in ranked[:4])

    what_root = telemetry.live_what.strip() or "Shape object intent"
    why_root = telemetry.live_why.strip()
    cards: list[IntentCard] = []
    for idx, row in enumerate(ranked[:4]):
        seed = _stable_seed(
            (
                telemetry.layout_id,
                telemetry.layout_standard,
                row.object_id,
                str(idx),
            )
        )
        confidence = _clamp((row.confidence * 0.72) + (telemetry.confidence * 0.28), 0.0, 1.0)
        why_tail = _INTENT_WHY_VARIANTS[seed % len(_INTENT_WHY_VARIANTS)]
        why_text = (
            f"{why_root.rstrip('.')} and {why_tail}"
            if why_root
            else f"Deterministic spatial steering to {why_tail}"
        )
        cards.append(
            IntentCard(
                object_id=row.object_id,
                what=f"{what_root}: {row.object_id}",
                why=why_text,
                where=_intent_where_slice(where_pool, seed=seed),
                confidence=confidence,
                badge=_intent_badge(confidence),
            )
        )
    return tuple(cards)


def _nearest_speaker_id(
    *,
    point: ObjectProjection,
    speakers: Sequence[SpeakerProjection],
) -> str | None:
    if not speakers:
        return None
    best_id: str | None = None
    best_dist = float("inf")
    for speaker in speakers:
        dx = point.x - speaker.x
        dy = point.y - speaker.y
        dz = point.depth - speaker.depth
        dist = (dx * dx) + (dy * dy) + (dz * dz)
        if dist < best_dist:
            best_dist = dist
            best_id = speaker.speaker_id
    return best_id


def _surface_snapshot_spectrum(frame: DashboardFrame) -> dict[str, Any]:
    points: list[list[Any]] = []
    bins = len(frame.spectrum_levels)
    stride = 1 if bins <= 80 else 2
    for idx, level in enumerate(frame.spectrum_levels):
        if idx % stride != 0 and idx != bins - 1:
            continue
        ratio = idx / float(max(1, bins - 1))
        points.append(
            [
                round(ratio, 4),
                round(1.0 - (0.84 * level), 4),
                _spectrum_color(idx, bins),
                round(_clamp(level * (0.6 + (0.4 * ratio)), 0.0, 1.0), 4),
            ]
        )
    return {
        "baseline": 0.92,
        "mood": frame.mood_line,
        "points": points,
    }


def _surface_snapshot_vectorscope(frame: DashboardFrame) -> dict[str, Any]:
    risk_color = {
        "low": _THEME["accent_cool"],
        "medium": _THEME["risk_medium"],
        "high": _THEME["risk_high"],
    }[frame.correlation_risk]
    points: list[list[float]] = []
    for idx, (x, y) in enumerate(frame.vectorscope_points):
        if idx % 4 == 0 or idx == len(frame.vectorscope_points) - 1:
            points.append([round(x, 4), round(y, 4)])
    return {
        "risk_color": risk_color,
        "points": points,
        "glow": round(_clamp(0.45 + (abs(frame.correlation) * 0.35), 0.0, 1.0), 4),
    }


def _surface_snapshot_correlation(frame: DashboardFrame) -> dict[str, Any]:
    return {
        "value": round(frame.correlation, 4),
        "risk": frame.correlation_risk,
        "zones": [
            {"name": "high", "start": -1.0, "end": _CORRELATION_ERROR_LTE},
            {"name": "medium", "start": _CORRELATION_ERROR_LTE, "end": _CORRELATION_WARN_LTE},
            {"name": "low", "start": _CORRELATION_WARN_LTE, "end": 1.0},
        ],
    }


def _surface_snapshot_spatial(frame: DashboardFrame) -> dict[str, Any]:
    active_speakers = {
        speaker_id
        for row in frame.object_points
        for speaker_id in [_nearest_speaker_id(point=row, speakers=frame.speaker_points)]
        if speaker_id is not None
    }
    speaker_rows = [
        {
            "speaker_id": row.speaker_id,
            "slot_index": row.slot_index,
            "x": round(row.x, 4),
            "y": round(row.y, 4),
            "depth": round(row.depth, 4),
            "active": row.speaker_id in active_speakers,
            "height": row.is_height,
            "lfe": row.is_lfe,
        }
        for row in frame.speaker_points
    ]
    object_rows = [
        {
            "object_id": row.object_id,
            "x": round(row.x, 4),
            "y": round(row.y, 4),
            "depth": round(row.depth, 4),
            "confidence": round(row.confidence, 4),
        }
        for row in frame.object_points
    ]
    return {
        "speakers": speaker_rows,
        "objects": object_rows,
    }


def _surface_snapshot_cards(frame: DashboardFrame) -> dict[str, Any]:
    cards = [
        {
            "object_id": card.object_id,
            "what": card.what,
            "why": card.why,
            "where": list(card.where),
            "confidence": round(card.confidence, 4),
            "badge": card.badge,
        }
        for card in frame.intent_cards
    ]
    return {"cards": cards}


def build_dashboard_surface_snapshot(frame: DashboardFrame) -> dict[str, Any]:
    return {
        "spectrum": _surface_snapshot_spectrum(frame),
        "vectorscope": _surface_snapshot_vectorscope(frame),
        "correlation": _surface_snapshot_correlation(frame),
        "spatial": _surface_snapshot_spatial(frame),
        "intent_cards": _surface_snapshot_cards(frame),
    }


def surface_snapshot_signature(frame: DashboardFrame) -> str:
    blob = json.dumps(
        build_dashboard_surface_snapshot(frame),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_spectrum_levels(
    telemetry: DashboardTelemetry,
    *,
    tick: int,
    bins: int = 56,
) -> tuple[float, ...]:
    bins_safe = max(8, int(bins))
    seed = _stable_seed(
        (
            telemetry.layout_id,
            telemetry.layout_standard,
            f"{telemetry.progress:.6f}",
            f"{telemetry.confidence:.6f}",
            f"{telemetry.correlation:.6f}",
        )
    )
    phase = (seed % 6283) / 1000.0
    tick_phase = float(tick) * 0.145
    energy = _clamp((telemetry.progress * 0.75) + (telemetry.confidence * 0.25), 0.08, 1.0)
    correlation_tilt = (1.0 - abs(_clamp(telemetry.correlation, -1.0, 1.0))) * 0.22

    levels: list[float] = []
    for idx in range(bins_safe):
        ratio = idx / float(max(1, bins_safe - 1))
        wave_a = 0.5 + (0.5 * math.sin(phase + tick_phase + (idx * 0.39)))
        wave_b = 0.5 + (0.5 * math.sin((phase * 0.63) + (tick_phase * 0.7) + (idx * 1.11)))
        musical_focus = 0.68 + (0.32 * math.sin(ratio * math.pi))
        value = ((0.57 * wave_a) + (0.43 * wave_b)) * musical_focus
        value = (value * energy) + (correlation_tilt * ratio)
        levels.append(_clamp(value, 0.0, 1.0))
    return tuple(levels)


def build_vectorscope_points(
    telemetry: DashboardTelemetry,
    *,
    tick: int,
    samples: int = 160,
) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    corr = _clamp(telemetry.correlation, -1.0, 1.0)
    phase_delta = (1.0 - corr) * (math.pi * 0.5)
    spin = float(tick) * 0.031
    amp = 0.65 + (0.3 * _clamp(telemetry.confidence, 0.0, 1.0))
    count = max(32, int(samples))

    for idx in range(count):
        theta = (2.0 * math.pi * idx) / float(count)
        left = amp * math.sin(theta + spin)
        right = amp * math.sin(theta + spin + phase_delta)
        x = _clamp((left + right) * 0.5, -1.0, 1.0)
        y = _clamp((left - right) * 0.5, -1.0, 1.0)
        points.append((x, y))
    return tuple(points)


def classify_correlation_risk(correlation: float) -> str:
    if correlation <= _CORRELATION_ERROR_LTE:
        return "high"
    if correlation <= _CORRELATION_WARN_LTE:
        return "medium"
    return "low"


def build_visualization_frame(
    telemetry: DashboardTelemetry,
    *,
    tick: int,
) -> DashboardFrame:
    corr = _clamp(telemetry.correlation, -1.0, 1.0)
    object_points = build_object_projections(
        layout_id=telemetry.layout_id,
        layout_standard=telemetry.layout_standard,
        object_tokens=telemetry.object_tokens,
    )
    return DashboardFrame(
        spectrum_levels=build_spectrum_levels(telemetry, tick=tick),
        vectorscope_points=build_vectorscope_points(telemetry, tick=tick),
        correlation=corr,
        correlation_risk=classify_correlation_risk(corr),
        speaker_points=build_speaker_projections(
            layout_id=telemetry.layout_id,
            layout_standard=telemetry.layout_standard,
        ),
        object_points=object_points,
        intent_cards=build_intent_cards(
            telemetry,
            object_points=object_points,
        ),
        mood_line=telemetry.mood_line,
        explain_line=telemetry.explain_line,
    )


def frame_signature(frame: DashboardFrame) -> str:
    payload = {
        "correlation": round(frame.correlation, 6),
        "correlation_risk": frame.correlation_risk,
        "spectrum_levels": [round(value, 6) for value in frame.spectrum_levels],
        "vectorscope_points": [
            [round(x, 6), round(y, 6)]
            for (x, y) in frame.vectorscope_points
        ],
        "speaker_points": [
            {
                "speaker_id": row.speaker_id,
                "slot_index": row.slot_index,
                "x": round(row.x, 6),
                "y": round(row.y, 6),
                "depth": round(row.depth, 6),
                "is_height": row.is_height,
                "is_lfe": row.is_lfe,
            }
            for row in frame.speaker_points
        ],
        "object_points": [
            {
                "object_id": row.object_id,
                "confidence": round(row.confidence, 6),
                "x": round(row.x, 6),
                "y": round(row.y, 6),
                "depth": round(row.depth, 6),
            }
            for row in frame.object_points
        ],
        "intent_cards": [
            {
                "object_id": row.object_id,
                "what": row.what,
                "why": row.why,
                "where": list(row.where),
                "confidence": round(row.confidence, 6),
                "badge": row.badge,
            }
            for row in frame.intent_cards
        ],
        "mood_line": frame.mood_line,
        "explain_line": frame.explain_line,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def derive_correlation_from_live_payload(
    payload: Mapping[str, Any],
    *,
    confidence: float,
    current: float,
) -> float:
    if isinstance(payload.get("correlation"), (float, int)):
        return _clamp(float(payload["correlation"]), -1.0, 1.0)

    why_text = str(payload.get("why", "")).strip().casefold()
    what_text = str(payload.get("what", "")).strip().casefold()
    inferred = _clamp((0.2 + (confidence * 0.8)), -1.0, 1.0)
    if "phase" in why_text or "phase" in what_text:
        inferred -= 0.45
    if "polarity" in why_text or "invert" in why_text:
        inferred -= 0.35
    if "warn" in why_text:
        inferred -= 0.2
    if "block" in why_text:
        inferred -= 0.25
    blended = (0.65 * inferred) + (0.35 * _clamp(current, -1.0, 1.0))
    return _clamp(blended, -1.0, 1.0)


def _mood_line(progress: float, correlation: float) -> str:
    if correlation <= _CORRELATION_ERROR_LTE:
        return "Phase risk is rising; center image drifting."
    if correlation <= _CORRELATION_WARN_LTE:
        return "Stereo tension detected; check width before print."
    if progress < 0.2:
        return "Session warming up. The mix is breathing."
    if progress < 0.6:
        return "Momentum building. Height air is rising."
    return "Render lane stable. Console glow is locked."


def _explain_line(
    *,
    what: str,
    why: str,
    confidence: float,
    where_items: Sequence[str],
) -> str:
    where_text = ", ".join(where_items[:4]) if where_items else "signal-wide"
    confidence_pct = int(round(_clamp(confidence, 0.0, 1.0) * 100.0))
    what_clean = what.strip() or "Live monitor update"
    why_clean = why.strip() or "deterministic telemetry synthesis"
    return (
        f"{what_clean} | why: {why_clean} | confidence: {confidence_pct}% | evidence: {where_text}"
    )


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    token = color.strip().lstrip("#")
    return (int(token[0:2], 16), int(token[2:4], 16), int(token[4:6], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{int(_clamp(channel, 0, 255)):02x}" for channel in rgb)


def _lerp_color(a: str, b: str, t: float) -> str:
    t_norm = _clamp(t, 0.0, 1.0)
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex(
        (
            int(round(ar + ((br - ar) * t_norm))),
            int(round(ag + ((bg - ag) * t_norm))),
            int(round(ab + ((bb - ab) * t_norm))),
        )
    )


def _spectrum_color(idx: int, total: int) -> str:
    ratio = idx / float(max(1, total - 1))
    if ratio <= 0.45:
        return _lerp_color("#8F4F1D", "#D79B48", ratio / 0.45)
    return _lerp_color("#D79B48", "#4FA6A0", (ratio - 0.45) / 0.55)


def _risk_color(risk: str) -> str:
    return {
        "low": _THEME["risk_low"],
        "medium": _THEME["risk_medium"],
        "high": _THEME["risk_high"],
    }.get(risk, _THEME["accent_cool"])


def _trim_text(text: str, max_len: int) -> str:
    cleaned = str(text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    if max_len <= 3:
        return cleaned[:max_len]
    return f"{cleaned[: max_len - 3]}..."


class VisualizationDashboardPanel:  # pragma: no cover - GUI runtime path
    def __init__(self, parent: Any, *, ctk_module: Any) -> None:
        import tkinter as _tk

        self._tk = _tk
        self._ctk = ctk_module
        self._tick = 0
        self._telemetry = default_dashboard_telemetry()
        self._last_live_payload: dict[str, Any] = {}
        self._engineer_mode = False
        self._active_theme_name: str = "Midnight Studio"
        self._active_theme: dict[str, str] = dict(_THEME)
        self._bus_plan_summary_text = (
            "Role counts:\n"
            "- (pending analyze)\n\n"
            "Bus tree:\n"
            "- (pending analyze)"
        )

        # Interactive 3D orbit state for speaker layout
        self._orbit_yaw: float = 32.0
        self._orbit_pitch: float = 25.0
        self._orbit_drag_start: tuple[int, int] | None = None
        self._orbit_drag_prev: tuple[float, float] = (32.0, 25.0)

        # Widget references for theme hot-swap
        self._canvas_frames: list[Any] = []
        self._canvas_widgets: list[Any] = []

        self.container = ctk_module.CTkFrame(
            parent,
            fg_color=_THEME["surface"],
            corner_radius=16,
            border_width=1,
            border_color=_THEME["surface_edge"],
        )
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_columnconfigure(1, weight=1)
        self.container.grid_rowconfigure(1, weight=1)
        self.container.grid_rowconfigure(2, weight=1)
        self.container.grid_rowconfigure(3, weight=1)
        self.container.grid_rowconfigure(4, weight=1)
        self._build_widgets()
        self._render_and_schedule()

    def grid(self, *args: Any, **kwargs: Any) -> None:
        self.container.grid(*args, **kwargs)

    def set_layout(self, *, layout_id: str, layout_standard: str) -> None:
        self._telemetry = replace(
            self._telemetry,
            layout_id=layout_id.strip() or "LAYOUT.2_0",
            layout_standard=_normalize_standard(layout_standard),
        )

    def set_progress(self, progress: float) -> None:
        self._telemetry = replace(self._telemetry, progress=_clamp(progress, 0.0, 1.0))

    def set_status_line(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._telemetry = replace(
            self._telemetry,
            mood_line=cleaned,
        )

    def set_bus_plan_summary(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            cleaned = "Role counts:\n- (none)\n\nBus tree:\n- (none)"
        self._bus_plan_summary_text = cleaned
        self._bus_plan_box.configure(state="normal")
        self._bus_plan_box.delete("1.0", "end")
        self._bus_plan_box.insert("end", cleaned)
        self._bus_plan_box.configure(state="disabled")

    def ingest_live_payload(self, payload: Mapping[str, Any]) -> None:
        confidence = _clamp(
            _safe_float(payload.get("confidence"), default=self._telemetry.confidence),
            0.0,
            1.0,
        )
        progress = _clamp(
            _safe_float(payload.get("progress"), default=self._telemetry.progress),
            0.0,
            1.0,
        )
        where_raw = payload.get("where")
        where_items: tuple[str, ...]
        if isinstance(where_raw, list):
            where_items = tuple(
                sorted(
                    {
                        item.strip()
                        for item in where_raw
                        if isinstance(item, str) and item.strip()
                    }
                )
            )
        else:
            where_items = self._telemetry.object_tokens
        correlation = derive_correlation_from_live_payload(
            payload,
            confidence=confidence,
            current=self._telemetry.correlation,
        )
        what_text = str(payload.get("what", "")).strip()
        why_text = str(payload.get("why", "")).strip()
        self._telemetry = replace(
            self._telemetry,
            progress=progress,
            confidence=confidence,
            correlation=correlation,
            mood_line=_mood_line(progress, correlation),
            explain_line=_explain_line(
                what=what_text,
                why=why_text,
                confidence=confidence,
                where_items=where_items,
            ),
            object_tokens=where_items,
            live_what=what_text,
            live_why=why_text,
            live_where=where_items,
        )
        self._last_live_payload = {
            "what": what_text,
            "why": why_text,
            "confidence": confidence,
            "progress": progress,
            "correlation": correlation,
            "where": list(where_items),
        }

    def set_theme(self, name: str) -> None:
        """Hot-swap active theme by name; next render frame picks up new colors."""
        self._active_theme_name = name if name in THEMES else "Midnight Studio"
        self._active_theme = get_theme(self._active_theme_name)
        self._apply_theme_to_widgets()

    def _apply_theme_to_widgets(self) -> None:
        theme = self._active_theme
        self.container.configure(
            fg_color=theme["surface"],
            border_color=theme["surface_edge"],
        )
        for frame in self._canvas_frames:
            frame.configure(
                fg_color=theme["surface"],
                border_color=theme["surface_edge"],
            )
        for canvas in self._canvas_widgets:
            canvas.configure(bg=theme["panel"])
        self._title.configure(text_color=theme["accent_hot"])
        self._bus_plan_box.configure(
            fg_color=theme["panel"],
            border_color=theme["surface_edge"],
            text_color=theme["text"],
        )

    def _theme_risk_color(self, risk: str) -> str:
        return {
            "low": self._active_theme["risk_low"],
            "medium": self._active_theme["risk_medium"],
            "high": self._active_theme["risk_high"],
        }.get(risk, self._active_theme["accent_cool"])

    def _project_speaker_3d(
        self, x: float, y: float, z: float
    ) -> tuple[float, float, float]:
        """Project world coords using current interactive orbit angles."""
        yaw = math.radians(self._orbit_yaw)
        pitch = math.radians(self._orbit_pitch)
        x_rot = (x * math.cos(yaw)) - (y * math.sin(yaw))
        y_rot = (x * math.sin(yaw)) + (y * math.cos(yaw))
        y_proj = (y_rot * math.cos(pitch)) - (z * math.sin(pitch))
        z_proj = (y_rot * math.sin(pitch)) + (z * math.cos(pitch))
        return (0.5 + (x_rot * 0.22), 0.54 - (y_proj * 0.18), z_proj)

    def _on_orbit_start(self, event: Any) -> None:
        self._orbit_drag_start = (event.x, event.y)
        self._orbit_drag_prev = (self._orbit_yaw, self._orbit_pitch)

    def _on_orbit_drag(self, event: Any) -> None:
        if self._orbit_drag_start is None:
            return
        dx = event.x - self._orbit_drag_start[0]
        dy = event.y - self._orbit_drag_start[1]
        self._orbit_yaw = self._orbit_drag_prev[0] + (dx * 0.5)
        self._orbit_pitch = max(-85.0, min(85.0, self._orbit_drag_prev[1] - (dy * 0.5)))

    def _on_orbit_end(self, event: Any) -> None:
        self._orbit_drag_start = None

    def _on_theme_change(self, name: str) -> None:
        self.set_theme(name)

    def _build_widgets(self) -> None:
        ctk = self._ctk
        self._title = ctk.CTkLabel(
            self.container,
            text="Visualization Dashboard v1.1 · StudioConsole Noir",
            font=("Space Grotesk", 18, "bold"),
            text_color=_THEME["accent_hot"],
        )
        self._title.grid(row=0, column=0, padx=(12, 6), pady=(10, 4), sticky="w")

        _ctrl_bar = ctk.CTkFrame(self.container, fg_color="transparent")
        _ctrl_bar.grid(row=0, column=1, padx=(6, 12), pady=(10, 4), sticky="e")

        self._theme_var = ctk.StringVar(value="Midnight Studio")
        ctk.CTkOptionMenu(
            _ctrl_bar,
            values=list(list_theme_names()),
            variable=self._theme_var,
            command=self._on_theme_change,
            fg_color="#1B1712",
            button_color=self._active_theme["accent_warm"],
            button_hover_color=self._active_theme["accent_hot"],
            dropdown_fg_color=self._active_theme["panel"],
            text_color=self._active_theme["text"],
            width=162,
            height=28,
            font=("Space Grotesk", 11),
        ).grid(row=0, column=0, padx=(0, 10), sticky="e")

        self._engineer_switch = ctk.CTkSwitch(
            _ctrl_bar,
            text="Engineer",
            command=self._toggle_engineer_mode,
            progress_color=self._active_theme["accent_hot"],
            button_color=self._active_theme["accent_hot"],
            button_hover_color=self._active_theme["accent_warm"],
            text_color=self._active_theme["text_muted"],
            font=("Space Grotesk", 12),
        )
        self._engineer_switch.grid(row=0, column=1, sticky="e")

        self._spectrum_canvas = self._create_canvas(
            title="Spectrum Analyzer · warm frequency bloom",
            row=1,
            column=0,
            columnspan=2,
            height=168,
        )
        self._vectorscope_canvas = self._create_canvas(
            title="Vectorscope · musical confidence glow",
            row=2,
            column=0,
            columnspan=1,
            height=188,
        )
        self._correlation_canvas = self._create_canvas(
            title="Correlation + phase meter · precision risk",
            row=2,
            column=1,
            columnspan=1,
            height=188,
        )
        self._speaker_canvas = self._create_canvas(
            title="Cinematic 3D layout · drag to orbit",
            row=3,
            column=0,
            columnspan=1,
            height=198,
        )
        self._speaker_canvas.bind("<ButtonPress-1>", self._on_orbit_start)
        self._speaker_canvas.bind("<B1-Motion>", self._on_orbit_drag)
        self._speaker_canvas.bind("<ButtonRelease-1>", self._on_orbit_end)

        self._objects_canvas = self._create_canvas(
            title="Object placement preview · confidence badges",
            row=3,
            column=1,
            columnspan=1,
            height=198,
        )
        self._intent_canvas = self._create_canvas(
            title="Intent cards · what / why / where / confidence",
            row=4,
            column=0,
            columnspan=2,
            height=170,
        )

        self._explain_label = ctk.CTkLabel(
            self.container,
            text=self._telemetry.explain_line,
            justify="left",
            wraplength=980,
            font=("Space Grotesk", 12),
            text_color=_THEME["text_muted"],
        )
        self._explain_label.grid(
            row=5,
            column=0,
            columnspan=2,
            padx=12,
            pady=(6, 8),
            sticky="w",
        )

        self._bus_plan_box = ctk.CTkTextbox(
            self.container,
            height=130,
            border_width=1,
            border_color=_THEME["surface_edge"],
            fg_color=_THEME["panel"],
            text_color=_THEME["text"],
            font=("JetBrains Mono", 11),
        )
        self._bus_plan_box.grid(
            row=6,
            column=0,
            columnspan=2,
            padx=12,
            pady=(0, 8),
            sticky="ew",
        )
        self._bus_plan_box.configure(state="normal")
        self._bus_plan_box.insert("end", self._bus_plan_summary_text)
        self._bus_plan_box.configure(state="disabled")

        self._engineer_box = ctk.CTkTextbox(
            self.container,
            height=108,
            border_width=1,
            border_color=_THEME["surface_edge"],
            fg_color=_THEME["panel"],
            text_color=_THEME["text"],
            font=("JetBrains Mono", 11),
        )
        self._engineer_box.grid_remove()

    def _create_canvas(
        self,
        *,
        title: str,
        row: int,
        column: int,
        columnspan: int,
        height: int,
    ) -> Any:
        ctk = self._ctk
        theme = self._active_theme
        frame = ctk.CTkFrame(
            self.container,
            fg_color=theme["surface"],
            corner_radius=14,
            border_width=1,
            border_color=theme["surface_edge"],
        )
        frame.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            padx=10,
            pady=6,
            sticky="nsew",
        )
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            frame,
            text=title,
            font=("Space Grotesk", 13, "bold"),
            text_color=theme["accent_warm"],
        ).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        canvas = self._tk.Canvas(
            frame,
            bg=theme["panel"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme["surface_edge"],
            height=height,
        )
        canvas.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._canvas_frames.append(frame)
        self._canvas_widgets.append(canvas)
        return canvas

    def _toggle_engineer_mode(self) -> None:
        self._engineer_mode = bool(self._engineer_switch.get())
        if self._engineer_mode:
            self._engineer_box.grid(
                row=7,
                column=0,
                columnspan=2,
                padx=12,
                pady=(0, 10),
                sticky="ew",
            )
        else:
            self._engineer_box.grid_remove()

    def _render_and_schedule(self) -> None:
        if not bool(self.container.winfo_exists()):
            return

        frame = build_visualization_frame(self._telemetry, tick=self._tick)
        self._draw_spectrum(frame)
        self._draw_vectorscope(frame)
        self._draw_correlation(frame)
        self._draw_speakers(frame)
        self._draw_objects(frame)
        self._draw_intent_cards(frame)
        self._explain_label.configure(text=frame.explain_line)

        if self._engineer_mode:
            surface_snapshot = build_dashboard_surface_snapshot(frame)
            snapshot = {
                "tick": self._tick,
                "layout_id": self._telemetry.layout_id,
                "layout_standard": self._telemetry.layout_standard,
                "mood": frame.mood_line,
                "correlation": round(frame.correlation, 4),
                "correlation_risk": frame.correlation_risk,
                "frame_signature": frame_signature(frame),
                "surface_signature": surface_snapshot_signature(frame),
                "surface_snapshot": surface_snapshot,
                "live_payload": self._last_live_payload,
            }
            self._engineer_box.delete("1.0", "end")
            self._engineer_box.insert("end", json.dumps(snapshot, indent=2, sort_keys=True))

        self._tick += 1
        self.container.after(90, self._render_and_schedule)

    def _canvas_size(self, canvas: Any, *, min_w: int, min_h: int) -> tuple[int, int]:
        width = int(canvas.winfo_width() or min_w)
        height = int(canvas.winfo_height() or min_h)
        return (max(min_w, width), max(min_h, height))

    def _draw_spectrum(self, frame: DashboardFrame) -> None:
        canvas = self._spectrum_canvas
        width, height = self._canvas_size(canvas, min_w=240, min_h=130)
        canvas.delete("all")
        baseline = height * 0.9
        bins = len(frame.spectrum_levels)
        for band_idx in range(10):
            y0 = (band_idx * height) / 10.0
            y1 = ((band_idx + 1) * height) / 10.0
            shade = _lerp_color("#070605", "#19140F", band_idx / 9.0)
            canvas.create_rectangle(0, y0, width, y1, fill=shade, outline="")
        canvas.create_line(0, baseline, width, baseline, fill="#3C2F21", width=1)

        points: list[float] = []
        for idx, level in enumerate(frame.spectrum_levels):
            ratio = idx / float(max(1, bins - 1))
            x = ratio * width
            y = baseline - (level * (height * 0.72))
            points.extend([x, y])

        if len(points) >= 4:
            area_poly = [0.0, baseline, *points, float(width), baseline, float(width), float(height), 0.0, float(height)]
            canvas.create_polygon(*area_poly, fill="#120F0B", outline="")
            for glow_width, glow_mix in ((9, 0.35), (6, 0.2), (4, 0.08)):
                glow_color = _lerp_color(self._active_theme["accent_hot"], "#FFF6E7", glow_mix)
                canvas.create_line(
                    *points,
                    fill=glow_color,
                    width=glow_width,
                    smooth=True,
                    splinesteps=22,
                )
            for idx in range(1, bins):
                x0 = ((idx - 1) / float(max(1, bins - 1))) * width
                x1 = (idx / float(max(1, bins - 1))) * width
                y0 = points[((idx - 1) * 2) + 1]
                y1 = points[(idx * 2) + 1]
                canvas.create_line(
                    x0,
                    y0,
                    x1,
                    y1,
                    fill=_spectrum_color(idx, bins),
                    width=2.2,
                    smooth=True,
                )
        for tick_label, tick_ratio in (("40Hz", 0.03), ("160Hz", 0.16), ("1k", 0.5), ("8k", 0.84), ("16k", 0.97)):
            x = tick_ratio * width
            canvas.create_line(x, baseline, x, baseline + 6, fill="#6C5B44", width=1)
            canvas.create_text(
                x,
                baseline + 12,
                text=tick_label,
                anchor="n",
                fill="#8C7A62",
                font=("JetBrains Mono", 8),
            )
        canvas.create_text(
            10,
            10,
            text=self._telemetry.mood_line,
            anchor="nw",
            fill=self._active_theme["text_muted"],
            font=("Space Grotesk", 11),
        )

    def _draw_vectorscope(self, frame: DashboardFrame) -> None:
        canvas = self._vectorscope_canvas
        width, height = self._canvas_size(canvas, min_w=180, min_h=150)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#090807", outline="")
        cx = width * 0.5
        cy = height * 0.5
        radius = min(width, height) * 0.42
        for ring in range(1, 5):
            ring_radius = radius * (ring / 4.0)
            canvas.create_oval(
                cx - ring_radius,
                cy - ring_radius,
                cx + ring_radius,
                cy + ring_radius,
                outline="#2A2319",
                width=1,
            )
        for angle_deg in range(0, 180, 30):
            radians = math.radians(angle_deg)
            dx = math.cos(radians) * radius
            dy = math.sin(radians) * radius
            canvas.create_line(cx - dx, cy - dy, cx + dx, cy + dy, fill="#241E16", width=1)

        coords: list[float] = []
        for x_norm, y_norm in frame.vectorscope_points:
            coords.extend(
                [
                    cx + (x_norm * radius),
                    cy - (y_norm * radius),
                ]
            )
        risk_color = self._theme_risk_color(frame.correlation_risk)
        confidence = _clamp(self._telemetry.confidence, 0.0, 1.0)
        for idx in range(4, 0, -1):
            glow_radius = radius * (0.25 + (confidence * 0.35) + (idx * 0.05))
            canvas.create_oval(
                cx - glow_radius,
                cy - glow_radius,
                cx + glow_radius,
                cy + glow_radius,
                outline=_lerp_color(risk_color, "#FFF6E7", 0.18 + (idx * 0.07)),
                width=1,
            )
        if len(coords) >= 4:
            canvas.create_line(*coords, fill="#1B1711", width=5, smooth=True, splinesteps=16)
            canvas.create_line(*coords, fill=risk_color, width=2, smooth=True, splinesteps=16)
        canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill="#E9DBC5", outline="")
        canvas.create_text(
            10,
            10,
            text=f"Confidence glow {int(round(confidence * 100.0))}%",
            anchor="nw",
            fill=self._active_theme["text_muted"],
            font=("Space Grotesk", 10),
        )

    def _draw_correlation(self, frame: DashboardFrame) -> None:
        canvas = self._correlation_canvas
        width, height = self._canvas_size(canvas, min_w=180, min_h=150)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#080706", outline="")
        risk_color = self._theme_risk_color(frame.correlation_risk)

        gauge_left = width * 0.14
        gauge_top = height * 0.08
        gauge_right = width * 0.86
        gauge_bottom = height * 0.65
        canvas.create_arc(
            gauge_left,
            gauge_top,
            gauge_right,
            gauge_bottom,
            start=180,
            extent=180,
            style="arc",
            outline="#2B2319",
            width=2,
        )
        for marker_corr in (-1.0, -0.6, -0.2, 0.0, 0.5, 1.0):
            ratio = (marker_corr + 1.0) * 0.5
            angle = math.radians(180.0 - (ratio * 180.0))
            cx = width * 0.5
            cy = gauge_bottom
            radius = (gauge_right - gauge_left) * 0.45
            x0 = cx + (math.cos(angle) * (radius - 4))
            y0 = cy - (math.sin(angle) * (radius - 4))
            x1 = cx + (math.cos(angle) * (radius + 7))
            y1 = cy - (math.sin(angle) * (radius + 7))
            canvas.create_line(x0, y0, x1, y1, fill="#403223", width=1)

        corr_ratio = (frame.correlation + 1.0) * 0.5
        corr_angle = math.radians(180.0 - (corr_ratio * 180.0))
        cx = width * 0.5
        cy = gauge_bottom
        needle_radius = (gauge_right - gauge_left) * 0.44
        nx = cx + (math.cos(corr_angle) * needle_radius)
        ny = cy - (math.sin(corr_angle) * needle_radius)
        canvas.create_line(cx, cy, nx, ny, fill="#20170F", width=5)
        canvas.create_line(cx, cy, nx, ny, fill=risk_color, width=2)
        canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#E8D9C2", outline="")

        bar_left = 20
        bar_right = width - 20
        bar_top = (height * 0.74) - 10
        bar_bottom = bar_top + 22
        canvas.create_rectangle(bar_left, bar_top, bar_right, bar_bottom, fill="#1A150F", outline="")
        warn_x = bar_left + ((bar_right - bar_left) * ((_CORRELATION_WARN_LTE + 1.0) / 2.0))
        error_x = bar_left + ((bar_right - bar_left) * ((_CORRELATION_ERROR_LTE + 1.0) / 2.0))
        canvas.create_rectangle(bar_left, bar_top, error_x, bar_bottom, fill="#4D1B16", outline="")
        canvas.create_rectangle(error_x, bar_top, warn_x, bar_bottom, fill="#5A3A19", outline="")
        canvas.create_rectangle(warn_x, bar_top, bar_right, bar_bottom, fill="#173223", outline="")
        bar_mid = (bar_left + bar_right) * 0.5
        canvas.create_line(bar_mid, bar_top - 6, bar_mid, bar_bottom + 6, fill="#564532", width=1)

        marker_x = bar_left + ((bar_right - bar_left) * ((frame.correlation + 1.0) / 2.0))
        canvas.create_oval(
            marker_x - 7,
            bar_top - 6,
            marker_x + 7,
            bar_bottom + 6,
            fill=risk_color,
            outline="",
        )
        canvas.create_text(
            width * 0.5,
            height * 0.26,
            text=f"Correlation {frame.correlation:+.2f}",
            fill=self._active_theme["text"],
            font=("Space Grotesk", 14, "bold"),
        )
        canvas.create_text(
            width * 0.5,
            height * 0.9,
            text=f"Phase risk: {frame.correlation_risk.upper()}",
            fill=self._active_theme["text_muted"],
            font=("Space Grotesk", 11),
        )

    def _draw_speakers(self, frame: DashboardFrame) -> None:
        canvas = self._speaker_canvas
        width, height = self._canvas_size(canvas, min_w=180, min_h=160)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#090807", outline="")
        canvas.create_oval(
            width * 0.18,
            height * 0.05,
            width * 0.82,
            height * 0.7,
            fill="#15100C",
            outline="",
        )
        canvas.create_oval(
            width * 0.28,
            height * 0.0,
            width * 0.72,
            height * 0.45,
            fill="#1C1610",
            outline="",
        )

        def sx(value: float) -> float:
            return value * width

        def sy(value: float) -> float:
            return value * height

        active_speakers = {
            speaker_id
            for row in frame.object_points
            for speaker_id in [_nearest_speaker_id(point=row, speakers=frame.speaker_points)]
            if speaker_id is not None
        }

        canvas.create_line(sx(0.1), sy(0.8), sx(0.9), sy(0.8), fill="#3A2D20", width=2)
        canvas.create_line(sx(0.2), sy(0.2), sx(0.5), sy(0.08), fill="#3A2D20", width=1)
        canvas.create_line(sx(0.8), sy(0.2), sx(0.5), sy(0.08), fill="#3A2D20", width=1)
        canvas.create_line(sx(0.2), sy(0.2), sx(0.2), sy(0.8), fill="#281F15", width=1)
        canvas.create_line(sx(0.8), sy(0.2), sx(0.8), sy(0.8), fill="#281F15", width=1)

        # Re-project speakers using interactive orbit angles for true 3D navigation
        orbit_speakers: list[tuple[float, Any, float, float]] = []
        for row in frame.speaker_points:
            world = _SPEAKER_WORLD_BY_NAME.get(row.speaker_id)
            if world is not None:
                ox, oy, odepth = self._project_speaker_3d(*world)
            else:
                ox, oy, odepth = row.x, row.y, row.depth
            orbit_speakers.append((odepth, row, ox, oy))
        orbit_speakers.sort(key=lambda t: t[0])

        # --- Pass 1: draw all speaker dots; collect data for label resolve ---
        speaker_dot_data: list[tuple[Any, float, float, float]] = []
        for odepth, row, ox, oy in orbit_speakers:
            fill = self._active_theme["accent_warm"]
            if row.is_lfe:
                fill = self._active_theme["risk_high"]
            elif row.is_height:
                fill = self._active_theme["accent_cool"]
            is_active = row.speaker_id in active_speakers
            fill = _lerp_color(fill, self._active_theme["accent_hot"], 0.22 if is_active else 0.0)
            radius = 4.0 + max(0.0, min(4.2, odepth + 1.1)) + (1.6 if is_active else 0.0)
            cx = sx(ox)
            cy = sy(oy)
            if is_active:
                for glow in (8.0, 5.5, 3.5):
                    canvas.create_oval(
                        cx - glow,
                        cy - glow,
                        cx + glow,
                        cy + glow,
                        outline=_lerp_color(fill, "#FFF3DE", 0.28),
                        width=1,
                    )
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=fill, outline="")
            speaker_dot_data.append((row, cx, cy, radius))

        # --- Resolve speaker ID label positions and draw with hairlines ---
        _ID_W, _ID_H = 52.0, 13.0
        id_anchors = [
            (cx, cy - (radius + 7.0), _ID_W, _ID_H)
            for _, cx, cy, radius in speaker_dot_data
        ]
        id_positions = _resolve_label_positions(
            id_anchors, canvas_w=float(width), canvas_h=float(height)
        )
        for k, (row, cx, cy, radius) in enumerate(speaker_dot_data):
            lx, ly = id_positions[k]
            if abs(lx - cx) > 4.0 or abs(ly - (cy - radius - 7.0)) > 4.0:
                canvas.create_line(cx, cy - radius, lx, ly, fill="#3D3126", width=1)
            canvas.create_text(
                lx,
                ly,
                text=f"{row.speaker_id}:{row.slot_index}",
                fill=self._active_theme["text_muted"],
                font=("Space Grotesk", 9),
            )

        # --- Pass 1: draw object point dots; collect badge data ---
        obj_spk_badge_data: list[tuple[Any, float, float]] = []
        for row in frame.object_points:
            x = sx(row.x)
            y = sy(row.y)
            color = _lerp_color(self._active_theme["accent_cool"], self._active_theme["accent_hot"], row.confidence)
            canvas.create_line(width * 0.5, height * 0.58, x, y, fill="#413223", width=1)
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
            obj_spk_badge_data.append((row, x, y))

        # --- Resolve object badge positions and draw with hairlines ---
        _OBJ_BW, _OBJ_BH = 46.0, 15.0
        obj_spk_anchors = [
            (x + 6.0 + _OBJ_BW * 0.5, y - 20.0 + _OBJ_BH * 0.5, _OBJ_BW, _OBJ_BH)
            for _, x, y in obj_spk_badge_data
        ]
        obj_spk_positions = _resolve_label_positions(
            obj_spk_anchors, canvas_w=float(width), canvas_h=float(height)
        )
        for k, (row, x, y) in enumerate(obj_spk_badge_data):
            bcx, bcy = obj_spk_positions[k]
            bx0 = bcx - _OBJ_BW * 0.5
            by0 = bcy - _OBJ_BH * 0.5
            anc_cx = x + 6.0 + _OBJ_BW * 0.5
            anc_cy = y - 20.0 + _OBJ_BH * 0.5
            if abs(bcx - anc_cx) > 4.0 or abs(bcy - anc_cy) > 4.0:
                canvas.create_line(x, y, bcx, bcy, fill="#3D3126", width=1)
            canvas.create_rectangle(bx0, by0, bx0 + _OBJ_BW, by0 + _OBJ_BH, fill="#16120D", outline="#4D3A28")
            canvas.create_text(
                bcx,
                bcy,
                text=f"{int(round(row.confidence * 100.0))}%",
                fill="#EADDC8",
                font=("JetBrains Mono", 8),
            )

        canvas.create_text(
            width - 6,
            height - 6,
            text=f"yaw {self._orbit_yaw:.0f}° pitch {self._orbit_pitch:.0f}°",
            anchor="se",
            fill=self._active_theme["text_muted"],
            font=("JetBrains Mono", 8),
        )

    def _draw_objects(self, frame: DashboardFrame) -> None:
        canvas = self._objects_canvas
        width, height = self._canvas_size(canvas, min_w=180, min_h=160)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#090807", outline="")
        cx = width * 0.5
        cy = height * 0.56
        max_radius = min(width, height) * 0.4
        for ring in range(1, 5):
            radius = max_radius * (ring / 4.0)
            canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline="#30271D",
                width=1,
            )
        canvas.create_line(cx - max_radius, cy, cx + max_radius, cy, fill="#2A2118", width=1)
        canvas.create_line(cx, cy - max_radius, cx, cy + max_radius, fill="#2A2118", width=1)

        def sx(value: float) -> float:
            return value * width

        def sy(value: float) -> float:
            return value * height

        for speaker in frame.speaker_points:
            x = sx(speaker.x)
            y = sy(speaker.y)
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#3B2F21", outline="")

        # --- Pass 1: draw all object dots; collect badge anchor data ---
        obj_data: list[tuple[Any, float, float, float]] = []
        for row in frame.object_points:
            x = sx(row.x)
            y = sy(row.y)
            radius = 4.0 + (row.confidence * 4.0)
            color = _lerp_color(self._active_theme["accent_cool"], self._active_theme["accent_hot"], row.confidence)
            canvas.create_line(cx, cy, x, y, fill="#3A2E22", width=1)
            for glow in (radius + 5, radius + 2):
                canvas.create_oval(
                    x - glow,
                    y - glow,
                    x + glow,
                    y + glow,
                    outline=_lerp_color(color, "#FFF2DD", 0.16),
                    width=1,
                )
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="")
            obj_data.append((row, x, y, radius))

        # --- Resolve badge positions and draw with hairlines ---
        _BW, _BH = 120.0, 16.0
        badge_anchors = [
            (x, y - (radius + 24.0) + _BH * 0.5, _BW, _BH)
            for _, x, y, radius in obj_data
        ]
        badge_positions = _resolve_label_positions(
            badge_anchors, canvas_w=float(width), canvas_h=float(height)
        )
        for k, (row, x, y, radius) in enumerate(obj_data):
            bcx, bcy = badge_positions[k]
            bx0 = bcx - _BW * 0.5
            by0 = bcy - _BH * 0.5
            anc_cy = y - (radius + 24.0) + _BH * 0.5
            if abs(bcx - x) > 4.0 or abs(bcy - anc_cy) > 4.0:
                canvas.create_line(x, y - radius, bcx, bcy, fill="#3D3126", width=1)
            canvas.create_rectangle(bx0, by0, bx0 + _BW, by0 + _BH, fill="#17120D", outline="#4E3B28")
            canvas.create_text(
                bcx,
                bcy,
                text=f"{_trim_text(row.object_id, 14)} · {int(round(row.confidence * 100.0))}%",
                fill=self._active_theme["text_muted"],
                font=("Space Grotesk", 9),
            )

    def _draw_intent_cards(self, frame: DashboardFrame) -> None:
        canvas = self._intent_canvas
        width, height = self._canvas_size(canvas, min_w=260, min_h=120)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#0A0908", outline="")

        cards = frame.intent_cards
        if not cards:
            canvas.create_text(
                12,
                12,
                text="Intent cards are waiting for live object evidence.",
                anchor="nw",
                fill=self._active_theme["text_muted"],
                font=("Space Grotesk", 11),
            )
            return

        cols = min(4, len(cards))
        if width < 980:
            cols = min(2, len(cards))
        rows = max(1, math.ceil(len(cards) / float(cols)))
        pad = 10.0
        card_w = (width - (pad * (cols + 1))) / float(cols)
        card_h = (height - (pad * (rows + 1))) / float(rows)

        for idx, card in enumerate(cards):
            row_idx = idx // cols
            col_idx = idx % cols
            x0 = pad + (col_idx * (card_w + pad))
            y0 = pad + (row_idx * (card_h + pad))
            x1 = x0 + card_w
            y1 = y0 + card_h

            accent = _lerp_color(self._active_theme["accent_cool"], self._active_theme["accent_hot"], card.confidence)
            canvas.create_rectangle(x0, y0, x1, y1, fill="#14100C", outline="#3A2D21", width=1)
            canvas.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y0 + 4, fill=accent, outline=accent)

            badge_w = 58
            badge_h = 16
            bx1 = x1 - 8
            bx0 = bx1 - badge_w
            by0 = y0 + 8
            canvas.create_rectangle(bx0, by0, bx1, by0 + badge_h, fill="#1D1711", outline="#4D3A28")
            canvas.create_text(
                (bx0 + bx1) / 2.0,
                by0 + (badge_h / 2.0),
                text=card.badge,
                fill="#F0DEBE",
                font=("JetBrains Mono", 8),
            )
            canvas.create_text(
                x0 + 8,
                y0 + 10,
                text=_trim_text(card.object_id, 18),
                anchor="nw",
                fill=self._active_theme["text"],
                font=("Space Grotesk", 11, "bold"),
            )
            canvas.create_text(
                x0 + 8,
                y0 + 28,
                text=f"what: {_trim_text(card.what, 54)}",
                anchor="nw",
                fill=_lerp_color(self._active_theme["text"], self._active_theme["text_muted"], 0.25),
                font=("Space Grotesk", 9),
            )
            canvas.create_text(
                x0 + 8,
                y0 + 46,
                text=f"why: {_trim_text(card.why, 56)}",
                anchor="nw",
                fill=_lerp_color(self._active_theme["text"], self._active_theme["text_muted"], 0.5),
                font=("Space Grotesk", 9),
            )
            canvas.create_text(
                x0 + 8,
                y0 + 64,
                text=f"where: {_trim_text(', '.join(card.where), 58)}",
                anchor="nw",
                fill=_lerp_color(self._active_theme["text"], self._active_theme["text_muted"], 0.7),
                font=("Space Grotesk", 9),
            )
            canvas.create_text(
                x0 + 8,
                y1 - 10,
                text=f"confidence {int(round(card.confidence * 100.0))}%",
                anchor="sw",
                fill=accent,
                font=("JetBrains Mono", 9),
            )
