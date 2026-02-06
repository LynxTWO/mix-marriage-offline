from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.core.presets import list_presets

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
UNKNOWN = "unknown"

_CANDIDATE_PRESET_IDS: tuple[str, ...] = (
    "PRESET.SAFE_CLEANUP",
    "PRESET.VIBE.TRANSLATION_SAFE",
    "PRESET.VIBE.PUNCHY_TIGHT",
    "PRESET.VIBE.DENSE_GLUE",
    "PRESET.VIBE.LIVE_YOU_ARE_THERE",
    "PRESET.VIBE.VOCAL_FORWARD",
    "PRESET.VIBE.WIDE_CINEMATIC",
    "PRESET.VIBE.WARM_INTIMATE",
    "PRESET.VIBE.BRIGHT_AIRY",
    "PRESET.TURBO_DRAFT",
)

_RULE_TRANSLATION_HIGH = "translation_high"
_RULE_MASKING_HIGH = "masking_high"
_RULE_DENSITY_HIGH = "density_high"
_RULE_DENSITY_LOW_SPACIOUS = "density_low_spacious"
_RULE_LIVE_BALANCED_MEDIUM = "live_balanced_medium"
_RULE_GUIDE_PROFILE_LIVE = "guide_profile_live"
_RULE_EXTREME_AGGRESSIVE_PROFILE = "extreme_aggressive_profile"

_RULE_REASON_TEXT: dict[str, str] = {
    _RULE_TRANSLATION_HIGH: (
        "Translation risk is high. This keeps things safe before you chase vibe."
    ),
    _RULE_MASKING_HIGH: (
        "Midrange feels crowded. This helps you pick a lead and clear space."
    ),
    _RULE_DENSITY_HIGH: (
        "Lots of layers at once. This nudges you toward glue without guesswork."
    ),
    _RULE_DENSITY_LOW_SPACIOUS: (
        "There is room in the arrangement. This can add width and emotion cleanly."
    ),
    _RULE_LIVE_BALANCED_MEDIUM: (
        "Density and risk look moderate. This can keep a live feel without over-processing."
    ),
    _RULE_GUIDE_PROFILE_LIVE: (
        "Guide profile is active. This aligns with review-first, dynamics-preserving decisions."
    ),
    _RULE_EXTREME_AGGRESSIVE_PROFILE: (
        "Aggressive mode plus extremes showed up. This is a safer reset pass."
    ),
}

_PRESET_REASON_TEXT: dict[str, str] = {
    "PRESET.SAFE_CLEANUP": (
        "Use this first when you want stability before committing to bigger moves."
    ),
    "PRESET.VIBE.TRANSLATION_SAFE": (
        "It favors phone-to-speaker consistency so your balances survive playback changes."
    ),
    "PRESET.VIBE.PUNCHY_TIGHT": (
        "Great when you want tighter low end and clearer transient impact."
    ),
    "PRESET.VIBE.DENSE_GLUE": (
        "Useful for binding layered parts into one controlled center of gravity."
    ),
    "PRESET.VIBE.LIVE_YOU_ARE_THERE": (
        "Use this when preserving transients and room feel matters more than loudness."
    ),
    "PRESET.VIBE.VOCAL_FORWARD": (
        "It helps a lead vocal hold focus when the mids are fighting."
    ),
    "PRESET.VIBE.WIDE_CINEMATIC": (
        "Choose this when the song can afford extra width and depth."
    ),
    "PRESET.VIBE.WARM_INTIMATE": (
        "This leans toward closeness and body when the mix feels too exposed."
    ),
    "PRESET.VIBE.BRIGHT_AIRY": (
        "Good for opening the top end when a mix feels closed in."
    ),
    "PRESET.TURBO_DRAFT": (
        "Fast option for rough direction passes when safety risk is low."
    ),
}


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _risk_level(value: Any) -> str:
    if value in {LOW, MEDIUM, HIGH}:
        return str(value)
    return UNKNOWN


def _signal_snapshot(report: dict[str, Any]) -> tuple[dict[str, str], bool]:
    vibe_signals = report.get("vibe_signals")
    has_vibe_signals = isinstance(vibe_signals, dict)
    payload = vibe_signals if isinstance(vibe_signals, dict) else {}
    return (
        {
            "density_level": _risk_level(payload.get("density_level")),
            "masking_level": _risk_level(payload.get("masking_level")),
            "translation_risk": _risk_level(payload.get("translation_risk")),
        },
        has_vibe_signals,
    )


def _current_profile_id(report: dict[str, Any]) -> str:
    profile_id = report.get("profile_id")
    if isinstance(profile_id, str):
        normalized = profile_id.strip()
        if normalized:
            return normalized
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        run_profile_id = run_config.get("profile_id")
        if isinstance(run_profile_id, str):
            normalized = run_profile_id.strip()
            if normalized:
                return normalized
    return ""


def _current_preset_id(report: dict[str, Any]) -> str:
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        preset_id = run_config.get("preset_id")
        if isinstance(preset_id, str):
            normalized = preset_id.strip()
            if normalized:
                return normalized
    return ""


def _extreme_count(report: dict[str, Any]) -> int:
    count = 0
    for recommendation in _iter_dict_list(report.get("recommendations")):
        if recommendation.get("extreme") is True:
            count += 1
    return count


def _add_points(
    scores: dict[str, int],
    rule_hits: dict[str, list[str]],
    preset_id: str,
    points: int,
    *,
    rule_id: str,
) -> None:
    if preset_id not in scores:
        return
    scores[preset_id] += points
    if points > 0:
        rule_hits[preset_id].append(rule_id)


def _build_reasons(
    preset_id: str,
    *,
    rule_hits: list[str],
    signals: dict[str, str],
) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()

    for rule_id in (
        _RULE_TRANSLATION_HIGH,
        _RULE_MASKING_HIGH,
        _RULE_DENSITY_HIGH,
        _RULE_DENSITY_LOW_SPACIOUS,
        _RULE_LIVE_BALANCED_MEDIUM,
        _RULE_GUIDE_PROFILE_LIVE,
        _RULE_EXTREME_AGGRESSIVE_PROFILE,
    ):
        if rule_id not in rule_hits:
            continue
        text = _RULE_REASON_TEXT[rule_id]
        if text not in seen:
            reasons.append(text)
            seen.add(text)

    preset_reason = _PRESET_REASON_TEXT.get(preset_id)
    if preset_reason and preset_reason not in seen:
        reasons.append(preset_reason)
        seen.add(preset_reason)

    if len(reasons) < 2:
        signal_reason = (
            "Signals snapshot: "
            f"density={signals['density_level']}, "
            f"masking={signals['masking_level']}, "
            f"translation={signals['translation_risk']}."
        )
        if signal_reason not in seen:
            reasons.append(signal_reason)
            seen.add(signal_reason)

    if not reasons:
        reasons.append("No strong flags triggered. Treat this as a neutral audition option.")
    return reasons[:4]


def _candidate_entries(presets_dir: Path) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for preset in list_presets(presets_dir):
        if not isinstance(preset, dict):
            continue
        preset_id = preset.get("preset_id")
        if isinstance(preset_id, str) and preset_id:
            by_id[preset_id] = preset
    return [
        by_id[preset_id]
        for preset_id in _CANDIDATE_PRESET_IDS
        if preset_id in by_id
    ]


def derive_preset_recommendations(
    report: dict[str, Any],
    presets_dir: Path,
    *,
    n: int = 3,
) -> list[dict[str, Any]]:
    if n <= 0:
        return []

    candidates = _candidate_entries(presets_dir)
    if not candidates:
        return []

    signals, has_signal_source = _signal_snapshot(report)
    density_level = signals["density_level"]
    masking_level = signals["masking_level"]
    translation_risk = signals["translation_risk"]
    current_profile_id = _current_profile_id(report)
    current_preset_id = _current_preset_id(report)
    extreme_count = _extreme_count(report)

    scores: dict[str, int] = {
        str(item.get("preset_id")): 0
        for item in candidates
        if isinstance(item.get("preset_id"), str)
    }
    rule_hits: dict[str, list[str]] = {
        preset_id: []
        for preset_id in scores
    }

    if translation_risk == HIGH:
        _add_points(
            scores,
            rule_hits,
            "PRESET.SAFE_CLEANUP",
            10,
            rule_id=_RULE_TRANSLATION_HIGH,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.TRANSLATION_SAFE",
            10,
            rule_id=_RULE_TRANSLATION_HIGH,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.TURBO_DRAFT",
            -10,
            rule_id=_RULE_TRANSLATION_HIGH,
        )

    if masking_level == HIGH:
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.VOCAL_FORWARD",
            8,
            rule_id=_RULE_MASKING_HIGH,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.PUNCHY_TIGHT",
            6,
            rule_id=_RULE_MASKING_HIGH,
        )

    if density_level == HIGH:
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.DENSE_GLUE",
            8,
            rule_id=_RULE_DENSITY_HIGH,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.PUNCHY_TIGHT",
            4,
            rule_id=_RULE_DENSITY_HIGH,
        )

    if density_level == LOW and masking_level in {LOW, MEDIUM} and translation_risk != HIGH:
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.WIDE_CINEMATIC",
            6,
            rule_id=_RULE_DENSITY_LOW_SPACIOUS,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.WARM_INTIMATE",
            4,
            rule_id=_RULE_DENSITY_LOW_SPACIOUS,
        )

    if density_level == MEDIUM and masking_level != HIGH and translation_risk != HIGH:
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.LIVE_YOU_ARE_THERE",
            3,
            rule_id=_RULE_LIVE_BALANCED_MEDIUM,
        )

    if current_profile_id == "PROFILE.GUIDE":
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.LIVE_YOU_ARE_THERE",
            2,
            rule_id=_RULE_GUIDE_PROFILE_LIVE,
        )

    if extreme_count > 0 and current_profile_id in {"PROFILE.TURBO", "PROFILE.FULL_SEND"}:
        _add_points(
            scores,
            rule_hits,
            "PRESET.SAFE_CLEANUP",
            8,
            rule_id=_RULE_EXTREME_AGGRESSIVE_PROFILE,
        )
        _add_points(
            scores,
            rule_hits,
            "PRESET.VIBE.TRANSLATION_SAFE",
            6,
            rule_id=_RULE_EXTREME_AGGRESSIVE_PROFILE,
        )

    ranked_candidates = sorted(
        candidates,
        key=lambda item: (
            -scores.get(str(item.get("preset_id")), 0),
            str(item.get("preset_id", "")),
        ),
    )

    if current_preset_id:
        without_current = [
            item
            for item in ranked_candidates
            if item.get("preset_id") != current_preset_id
        ]
        if len(without_current) >= n:
            ranked_candidates = without_current

    positive = [
        item
        for item in ranked_candidates
        if scores.get(str(item.get("preset_id")), 0) > 0
    ]
    selected: list[dict[str, Any]] = positive[:n]

    if len(selected) < n:
        zero_scored = [
            item
            for item in ranked_candidates
            if scores.get(str(item.get("preset_id")), 0) == 0
            and item not in selected
        ]
        selected.extend(zero_scored[: n - len(selected)])

    recommendations: list[dict[str, Any]] = []
    for item in selected:
        preset_id = item.get("preset_id")
        if not isinstance(preset_id, str):
            continue
        recommendation: dict[str, Any] = {
            "preset_id": preset_id,
            "score": float(scores.get(preset_id, 0)),
            "reasons": _build_reasons(
                preset_id,
                rule_hits=rule_hits.get(preset_id, []),
                signals=signals,
            ),
        }

        overlay = item.get("overlay")
        if isinstance(overlay, str) and overlay.strip():
            recommendation["overlay"] = overlay.strip()

        help_id = item.get("help_id")
        if isinstance(help_id, str) and help_id.strip():
            recommendation["help_id"] = help_id.strip()

        if has_signal_source:
            recommendation["signals"] = dict(signals)

        recommendations.append(recommendation)

    return recommendations
