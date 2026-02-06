from __future__ import annotations

from typing import Any

LOW = "low"
MEDIUM = "medium"
HIGH = "high"

MASKING_SCORE_LOW_MAX = 0.45
MASKING_SCORE_MEDIUM_MAX = 0.75

DOWNMIX_QA_DELTA_GATE_IDS = {
    "GATE.DOWNMIX_QA_LUFS_DELTA_LIMIT",
    "GATE.DOWNMIX_QA_TRUE_PEAK_DELTA_LIMIT",
    "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT",
}
DOWNMIX_QA_DELTA_ISSUE_IDS = {
    "ISSUE.DOWNMIX.QA.LUFS_MISMATCH",
    "ISSUE.DOWNMIX.QA.TRUE_PEAK_MISMATCH",
    "ISSUE.DOWNMIX.QA.CORRELATION_MISMATCH",
}

DENSITY_HIGH_NOTE = (
    "Lots of layers hitting at once. Make space with arrangement or gentle carving."
)
MASKING_HIGH_NOTE = (
    "Midrange is crowded. Decide what leads and let the rest support."
)
TRANSLATION_HIGH_NOTE = (
    "Translation risk is elevated. Fix clipping/lossy files and check mono."
)


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _density_level(density_mean: float | None) -> str:
    if density_mean is None:
        return LOW
    if density_mean < 2.0:
        return LOW
    if density_mean <= 4.0:
        return MEDIUM
    return HIGH


def _masking_pair_count(mix_complexity: dict[str, Any]) -> int | None:
    explicit_count = _numeric(mix_complexity.get("top_masking_pairs_count"))
    if explicit_count is not None:
        return max(0, int(explicit_count))

    masking_risk = mix_complexity.get("masking_risk")
    if isinstance(masking_risk, dict):
        pair_count = _numeric(masking_risk.get("pair_count"))
        if pair_count is not None:
            return max(0, int(pair_count))
    return None


def _max_masking_score(mix_complexity: dict[str, Any]) -> float | None:
    max_score: float | None = None
    top_pairs = mix_complexity.get("top_masking_pairs")
    if isinstance(top_pairs, list):
        for pair in _iter_dict_list(top_pairs):
            score = _numeric(pair.get("score"))
            if score is None:
                continue
            score = max(0.0, min(1.0, score))
            if max_score is None or score > max_score:
                max_score = score

    masking_risk = mix_complexity.get("masking_risk")
    if isinstance(masking_risk, dict):
        raw_top_pairs = masking_risk.get("top_pairs")
        if isinstance(raw_top_pairs, list):
            for pair in _iter_dict_list(raw_top_pairs):
                score = _numeric(pair.get("score"))
                if score is None:
                    continue
                score = max(0.0, min(1.0, score))
                if max_score is None or score > max_score:
                    max_score = score
    return max_score


def _masking_level_from_count(pair_count: int) -> str:
    if pair_count <= 1:
        return LOW
    if pair_count <= 4:
        return MEDIUM
    return HIGH


def _masking_level_from_score(max_score: float) -> str:
    if max_score <= MASKING_SCORE_LOW_MAX:
        return LOW
    if max_score <= MASKING_SCORE_MEDIUM_MAX:
        return MEDIUM
    return HIGH


def _masking_level(mix_complexity: dict[str, Any]) -> str:
    pair_count = _masking_pair_count(mix_complexity)
    if pair_count is not None:
        return _masking_level_from_count(pair_count)

    max_score = _max_masking_score(mix_complexity)
    if max_score is None:
        return LOW
    return _masking_level_from_score(max_score)


def _iter_issue_ids(report: dict[str, Any]) -> list[str]:
    issue_ids: list[str] = []
    for issue in _iter_dict_list(report.get("issues")):
        issue_id = issue.get("issue_id")
        if isinstance(issue_id, str) and issue_id:
            issue_ids.append(issue_id)

    downmix_qa = report.get("downmix_qa")
    if isinstance(downmix_qa, dict):
        for issue in _iter_dict_list(downmix_qa.get("issues")):
            issue_id = issue.get("issue_id")
            if isinstance(issue_id, str) and issue_id:
                issue_ids.append(issue_id)

    for translation in _iter_dict_list(report.get("translation_results")):
        for issue in _iter_dict_list(translation.get("issues")):
            issue_id = issue.get("issue_id")
            if isinstance(issue_id, str) and issue_id:
                issue_ids.append(issue_id)

    return issue_ids


def _has_downmix_qa_delta_gate_fail(report: dict[str, Any]) -> bool:
    for recommendation in _iter_dict_list(report.get("recommendations")):
        for gate_result in _iter_dict_list(recommendation.get("gate_results")):
            gate_id = gate_result.get("gate_id")
            outcome = gate_result.get("outcome")
            if (
                isinstance(gate_id, str)
                and gate_id in DOWNMIX_QA_DELTA_GATE_IDS
                and outcome == "reject"
            ):
                return True
    return False


def _extreme_count(report: dict[str, Any]) -> int:
    count = 0
    for recommendation in _iter_dict_list(report.get("recommendations")):
        if recommendation.get("extreme") is True:
            count += 1
    return count


def _translation_risk_level(report: dict[str, Any]) -> str:
    issue_ids = _iter_issue_ids(report)
    if any("LOSSY" in issue_id for issue_id in issue_ids):
        return HIGH
    if any(("CLIP" in issue_id or "HEADROOM" in issue_id) for issue_id in issue_ids):
        return HIGH
    if any(issue_id in DOWNMIX_QA_DELTA_ISSUE_IDS for issue_id in issue_ids):
        return HIGH
    if _has_downmix_qa_delta_gate_fail(report):
        return HIGH
    if _extreme_count(report) > 0:
        return MEDIUM
    return LOW


def derive_vibe_signals(report: dict[str, Any]) -> dict[str, Any]:
    mix_complexity = report.get("mix_complexity")
    mix_complexity_payload = mix_complexity if isinstance(mix_complexity, dict) else {}
    density_mean = _numeric(mix_complexity_payload.get("density_mean"))

    density_level = _density_level(density_mean)
    masking_level = _masking_level(mix_complexity_payload)
    translation_risk = _translation_risk_level(report)

    notes: list[str] = []
    if density_level == HIGH:
        notes.append(DENSITY_HIGH_NOTE)
    if masking_level == HIGH:
        notes.append(MASKING_HIGH_NOTE)
    if translation_risk == HIGH:
        notes.append(TRANSLATION_HIGH_NOTE)

    return {
        "density_level": density_level,
        "masking_level": masking_level,
        "translation_risk": translation_risk,
        "notes": notes,
    }
