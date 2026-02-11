from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.core.render_targets import list_render_targets

_BASELINE_TARGET_ID = "TARGET.STEREO.2_0"
_SURROUND_LAYOUT_TO_TARGET_ID = {
    "LAYOUT.5_1": "TARGET.SURROUND.5_1",
    "LAYOUT.7_1": "TARGET.SURROUND.7_1",
}
_PRIORITY_ROUTING = 0
_PRIORITY_DOWNMIX = 1
_PRIORITY_SCENE = 2
_CONFIDENCE_BASELINE = 1.0
_CONFIDENCE_ROUTING = 0.92
_CONFIDENCE_DOWNMIX = 0.84
_CONFIDENCE_SCENE_5_1 = 0.74
_CONFIDENCE_SCENE_7_1 = 0.70
_DIFFUSE_5_1_THRESHOLD = 0.75
_DIFFUSE_7_1_THRESHOLD = 0.85


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _resolved_render_targets_path(repo_root: Path, render_targets_path: Path | None) -> Path:
    if render_targets_path is None:
        return repo_root / "ontology" / "render_targets.yaml"
    if render_targets_path.is_absolute():
        return render_targets_path
    return repo_root / render_targets_path


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _layout_to_target_id_index(target_rows: list[dict[str, Any]]) -> dict[str, str]:
    layout_to_target: dict[str, str] = {}
    for row in target_rows:
        layout_id = _coerce_str(row.get("layout_id")).strip()
        target_id = _coerce_str(row.get("target_id")).strip()
        if not layout_id or not target_id or layout_id in layout_to_target:
            continue
        layout_to_target[layout_id] = target_id
    return layout_to_target


def _target_id_for_layout(
    layout_id: str,
    layout_to_target: dict[str, str],
    available_target_ids: set[str],
) -> str | None:
    canonical_target_id = _SURROUND_LAYOUT_TO_TARGET_ID.get(layout_id)
    if canonical_target_id is not None and canonical_target_id in available_target_ids:
        return canonical_target_id
    resolved_target_id = layout_to_target.get(layout_id)
    if isinstance(resolved_target_id, str) and resolved_target_id:
        return resolved_target_id
    return None


def _add_signal_candidate(
    *,
    candidates: dict[str, dict[str, Any]],
    target_id: str,
    reason: str,
    priority: int,
    confidence: float,
    available_target_ids: set[str],
) -> None:
    if target_id not in available_target_ids:
        return
    normalized_reason = reason.strip()
    if not normalized_reason:
        return
    normalized_confidence = _clamp_confidence(confidence)

    existing = candidates.get(target_id)
    if existing is None or int(existing.get("priority", 99)) > priority:
        candidates[target_id] = {
            "priority": priority,
            "confidence": normalized_confidence,
            "reasons": {normalized_reason},
        }
        return

    if int(existing.get("priority", 99)) != priority:
        return

    reasons = existing.get("reasons")
    if isinstance(reasons, set):
        reasons.add(normalized_reason)
    else:
        existing["reasons"] = {normalized_reason}
    existing["confidence"] = max(
        _clamp_confidence(_coerce_number(existing.get("confidence")) or 0.0),
        normalized_confidence,
    )


def _format_threshold_reason(*, bed_id: str, diffuse: float, threshold: float) -> str:
    return (
        f"Bed {bed_id} intent.diffuse={diffuse:.2f} >= {threshold:.2f} "
        "signals diffuse surround intent."
    )


def recommend_render_targets(
    *,
    repo_root: Path,
    render_targets_path: Path | None = None,
    report: dict[str, Any] | None = None,
    scene: dict[str, Any] | None = None,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    if max_results <= 0:
        raise ValueError("max_results must be greater than 0.")

    target_rows = list_render_targets(
        _resolved_render_targets_path(repo_root, render_targets_path),
    )
    available_target_ids = {
        _coerce_str(row.get("target_id")).strip()
        for row in target_rows
        if isinstance(row, dict)
    }
    available_target_ids.discard("")

    if _BASELINE_TARGET_ID not in available_target_ids:
        raise ValueError(
            f"Render target registry is missing required baseline target: {_BASELINE_TARGET_ID}"
        )

    layout_to_target = _layout_to_target_id_index(target_rows)
    candidates: dict[str, dict[str, Any]] = {}

    report_payload = _coerce_dict(report)
    routing_plan = _coerce_dict(report_payload.get("routing_plan"))
    routing_layout_id = _coerce_str(routing_plan.get("target_layout_id")).strip()
    routing_target_id = _target_id_for_layout(
        routing_layout_id,
        layout_to_target,
        available_target_ids,
    )
    if routing_target_id is not None:
        _add_signal_candidate(
            candidates=candidates,
            target_id=routing_target_id,
            reason=f"Routing plan targets {routing_layout_id}",
            priority=_PRIORITY_ROUTING,
            confidence=_CONFIDENCE_ROUTING,
            available_target_ids=available_target_ids,
        )

    run_config = _coerce_dict(report_payload.get("run_config"))
    downmix = _coerce_dict(run_config.get("downmix"))
    downmix_layout_id = _coerce_str(downmix.get("target_layout_id")).strip()
    downmix_target_id = _target_id_for_layout(
        downmix_layout_id,
        layout_to_target,
        available_target_ids,
    )
    if downmix_target_id is not None:
        _add_signal_candidate(
            candidates=candidates,
            target_id=downmix_target_id,
            reason=f"Run config downmix targets {downmix_layout_id}",
            priority=_PRIORITY_DOWNMIX,
            confidence=_CONFIDENCE_DOWNMIX,
            available_target_ids=available_target_ids,
        )

    scene_payload = _coerce_dict(scene)
    bed_rows = sorted(
        _coerce_dict_list(scene_payload.get("beds")),
        key=lambda row: _coerce_str(row.get("bed_id")).strip(),
    )
    for bed in bed_rows:
        bed_id = _coerce_str(bed.get("bed_id")).strip() or "<unknown>"
        intent = _coerce_dict(bed.get("intent"))
        diffuse = _coerce_number(intent.get("diffuse"))
        if diffuse is None:
            continue
        if diffuse >= _DIFFUSE_5_1_THRESHOLD:
            target_id_5_1 = _target_id_for_layout(
                "LAYOUT.5_1",
                layout_to_target,
                available_target_ids,
            )
            if target_id_5_1 is not None:
                _add_signal_candidate(
                    candidates=candidates,
                    target_id=target_id_5_1,
                    reason=_format_threshold_reason(
                        bed_id=bed_id,
                        diffuse=diffuse,
                        threshold=_DIFFUSE_5_1_THRESHOLD,
                    ),
                    priority=_PRIORITY_SCENE,
                    confidence=_CONFIDENCE_SCENE_5_1,
                    available_target_ids=available_target_ids,
                )
        if diffuse >= _DIFFUSE_7_1_THRESHOLD:
            target_id_7_1 = _target_id_for_layout(
                "LAYOUT.7_1",
                layout_to_target,
                available_target_ids,
            )
            if target_id_7_1 is not None:
                _add_signal_candidate(
                    candidates=candidates,
                    target_id=target_id_7_1,
                    reason=_format_threshold_reason(
                        bed_id=bed_id,
                        diffuse=diffuse,
                        threshold=_DIFFUSE_7_1_THRESHOLD,
                    ),
                    priority=_PRIORITY_SCENE,
                    confidence=_CONFIDENCE_SCENE_7_1,
                    available_target_ids=available_target_ids,
                )

    recommended_rows: list[dict[str, Any]] = [
        {
            "target_id": _BASELINE_TARGET_ID,
            "rank": 1,
            "confidence": _CONFIDENCE_BASELINE,
            "reasons": ["Baseline stereo reality check."],
        }
    ]

    extras: list[dict[str, Any]] = []
    for target_id, payload in sorted(
        candidates.items(),
        key=lambda item: (
            -_clamp_confidence(_coerce_number(item[1].get("confidence")) or 0.0),
            item[0],
        ),
    ):
        if target_id == _BASELINE_TARGET_ID:
            continue
        reasons = payload.get("reasons")
        reason_rows = sorted(
            reason for reason in reasons if isinstance(reason, str) and reason.strip()
        ) if isinstance(reasons, set) else []
        extras.append(
            {
                "target_id": target_id,
                "rank": 0,
                "confidence": _clamp_confidence(
                    _coerce_number(payload.get("confidence")) or 0.0
                ),
                "reasons": reason_rows,
            }
        )

    recommended_rows.extend(extras)
    limited = recommended_rows[:max_results]
    for index, row in enumerate(limited, start=1):
        row["rank"] = index
    return sorted(
        limited,
        key=lambda row: (int(row.get("rank", 0)), _coerce_str(row.get("target_id")).strip()),
    )
