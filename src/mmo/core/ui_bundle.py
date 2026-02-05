from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UI_BUNDLE_SCHEMA_VERSION = "0.1.0"
TOP_ISSUE_LIMIT = 5


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _top_issues(report: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for issue in _iter_dict_list(report.get("issues")):
        issue_id = issue.get("issue_id")
        severity = issue.get("severity")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        if not isinstance(severity, int) or isinstance(severity, bool):
            continue
        message = issue.get("message")
        ranked.append(
            {
                "issue_id": issue_id,
                "severity": severity,
                "summary": message if isinstance(message, str) else "",
            }
        )
    ranked.sort(key=lambda item: (-item["severity"], item["issue_id"], item["summary"]))
    return ranked[:limit]


def _recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    return _iter_dict_list(report.get("recommendations"))


def _list_length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _renderer_manifests(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    return _iter_dict_list(manifest.get("renderer_manifests"))


def _count_if_true(recommendations: list[dict[str, Any]], field: str) -> int:
    return sum(1 for rec in recommendations if rec.get(field) is True)


def _count_if_not_true(recommendations: list[dict[str, Any]], field: str) -> int:
    return sum(1 for rec in recommendations if rec.get(field) is not True)


def _profile_id(report: dict[str, Any]) -> str:
    profile = report.get("profile_id")
    if isinstance(profile, str):
        return profile
    run_config = report.get("run_config")
    if isinstance(run_config, dict):
        run_profile = run_config.get("profile_id")
        if isinstance(run_profile, str):
            return run_profile
    return ""


def _collect_downmix_metric_values(downmix_qa: dict[str, Any], evidence_id: str) -> list[float]:
    values: list[float] = []
    for measurement in _iter_dict_list(downmix_qa.get("measurements")):
        if measurement.get("evidence_id") != evidence_id:
            continue
        numeric = _numeric_value(measurement.get("value"))
        if numeric is not None:
            values.append(numeric)

    for issue in _iter_dict_list(downmix_qa.get("issues")):
        for evidence in _iter_dict_list(issue.get("evidence")):
            if evidence.get("evidence_id") != evidence_id:
                continue
            numeric = _numeric_value(evidence.get("value"))
            if numeric is not None:
                values.append(numeric)
    return values


def _downmix_qa_summary(report: dict[str, Any]) -> dict[str, Any]:
    downmix_qa = report.get("downmix_qa")
    if not isinstance(downmix_qa, dict):
        return {
            "has_issues": False,
            "max_delta_lufs": None,
            "max_delta_true_peak": None,
            "min_corr": None,
        }

    issue_count = len(_iter_dict_list(downmix_qa.get("issues")))
    lufs_delta_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.LUFS_DELTA")
    true_peak_delta_values = _collect_downmix_metric_values(
        downmix_qa, "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA"
    )
    corr_fold_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.CORR_FOLD")
    corr_ref_values = _collect_downmix_metric_values(downmix_qa, "EVID.DOWNMIX.QA.CORR_REF")
    corr_values = corr_fold_values + corr_ref_values
    return {
        "has_issues": issue_count > 0,
        "max_delta_lufs": max((abs(value) for value in lufs_delta_values), default=None),
        "max_delta_true_peak": max(
            (abs(value) for value in true_peak_delta_values), default=None
        ),
        "min_corr": min(corr_values, default=None),
    }


def _apply_summary(report: dict[str, Any], apply_manifest: dict[str, Any]) -> dict[str, int]:
    recommendations = _recommendations(report)
    renderer_manifests = _renderer_manifests(apply_manifest)
    return {
        "eligible_count": _count_if_true(recommendations, "eligible_auto_apply"),
        "blocked_count": _count_if_not_true(recommendations, "eligible_auto_apply"),
        "outputs_count": sum(
            _list_length(manifest.get("outputs")) for manifest in renderer_manifests
        ),
        "skipped_count": sum(
            _list_length(manifest.get("skipped")) for manifest in renderer_manifests
        ),
    }


def build_ui_bundle(
    report: dict[str, Any],
    render_manifest: dict[str, Any] | None,
    apply_manifest: dict[str, Any] | None = None,
    applied_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommendations = _recommendations(report)
    dashboard = {
        "profile_id": _profile_id(report),
        "top_issues": _top_issues(report, limit=TOP_ISSUE_LIMIT),
        "eligible_counts": {
            "auto_apply": _count_if_true(recommendations, "eligible_auto_apply"),
            "render": _count_if_true(recommendations, "eligible_render"),
        },
        "blocked_counts": {
            "auto_apply": _count_if_not_true(recommendations, "eligible_auto_apply"),
            "render": _count_if_not_true(recommendations, "eligible_render"),
        },
        "extreme_count": _count_if_true(recommendations, "extreme"),
        "downmix_qa": _downmix_qa_summary(report),
    }
    if apply_manifest is not None:
        dashboard["apply"] = _apply_summary(report, apply_manifest)

    payload: dict[str, Any] = {
        "schema_version": UI_BUNDLE_SCHEMA_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "report": report,
        "dashboard": dashboard,
    }
    if render_manifest is not None:
        payload["render_manifest"] = render_manifest
    if apply_manifest is not None:
        payload["apply_manifest"] = apply_manifest
    if applied_report is not None:
        payload["applied_report"] = applied_report
    return payload
