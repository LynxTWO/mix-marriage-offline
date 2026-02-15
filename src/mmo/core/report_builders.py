from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from mmo.resources import ontology_dir

from mmo import __version__ as engine_version
from mmo.core.gates import apply_gates_to_report

REPORT_SCHEMA_VERSION = "0.1.0"
DEFAULT_GENERATED_AT = "2000-01-01T00:00:00Z"
DOWNMIX_QA_LUFS_DELTA_GATE_ID = "GATE.DOWNMIX_QA_LUFS_DELTA_LIMIT"
DOWNMIX_QA_TRUE_PEAK_DELTA_GATE_ID = "GATE.DOWNMIX_QA_TRUE_PEAK_DELTA_LIMIT"
DOWNMIX_QA_CORR_DELTA_GATE_ID = "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"
DOWNMIX_QA_DELTA_GATE_IDS = {
    DOWNMIX_QA_LUFS_DELTA_GATE_ID,
    DOWNMIX_QA_TRUE_PEAK_DELTA_GATE_ID,
    DOWNMIX_QA_CORR_DELTA_GATE_ID,
}


def _load_ontology_version(path: Path) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot load ontology version.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    ontology = data.get("ontology", {}) if isinstance(data, dict) else {}
    version = ontology.get("ontology_version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"Missing ontology_version in {path}")
    return version


def _hash_report_payload(downmix_qa: Dict[str, Any]) -> str:
    payload = json.dumps(downmix_qa, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _issue_where_signature(issue: Dict[str, Any]) -> str | None:
    evidence = issue.get("evidence", [])
    if not isinstance(evidence, list):
        return None
    where_items: List[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        where = item.get("where")
        if isinstance(where, dict):
            where_items.append(_canonical_json(where))
    if not where_items:
        return None
    return "|".join(sorted(where_items))


def _issue_evidence_fingerprint(issue: Dict[str, Any]) -> str | None:
    evidence = issue.get("evidence", [])
    if not isinstance(evidence, list):
        return None
    normalized: List[Dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        normalized_item: Dict[str, Any] = {}
        for key in [
            "evidence_id",
            "value",
            "unit_id",
            "confidence",
            "source",
            "where",
            "why",
        ]:
            if key in item:
                normalized_item[key] = item[key]
        normalized.append(normalized_item)
    if not normalized:
        return None
    normalized.sort(
        key=lambda entry: (
            str(entry.get("evidence_id", "")),
            _canonical_json(entry.get("value")),
            str(entry.get("unit_id", "")),
        )
    )
    return _canonical_json(normalized)


def merge_downmix_qa_issues_into_report(report: Dict[str, Any]) -> None:
    downmix_qa = report.get("downmix_qa", {})
    if not isinstance(downmix_qa, dict):
        return
    incoming = downmix_qa.get("issues", [])
    if not isinstance(incoming, list) or not incoming:
        return

    report_issues = report.get("issues")
    if not isinstance(report_issues, list):
        report_issues = []
        report["issues"] = report_issues

    seen: Dict[str, Dict[str, set[str]]] = {}
    for issue in report_issues:
        if not isinstance(issue, dict):
            continue
        issue_id = issue.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        entry = seen.setdefault(issue_id, {"where": set(), "evidence": set()})
        where_sig = _issue_where_signature(issue)
        evidence_fp = _issue_evidence_fingerprint(issue)
        if where_sig:
            entry["where"].add(where_sig)
        if evidence_fp:
            entry["evidence"].add(evidence_fp)

    to_add: List[Dict[str, Any]] = []
    for issue in incoming:
        if not isinstance(issue, dict):
            continue
        issue_id = issue.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        where_sig = _issue_where_signature(issue)
        evidence_fp = _issue_evidence_fingerprint(issue)
        entry = seen.get(issue_id)
        if entry:
            if where_sig and where_sig in entry["where"]:
                continue
            if evidence_fp and evidence_fp in entry["evidence"]:
                continue
        copied = copy.deepcopy(issue)
        to_add.append(copied)
        entry = seen.setdefault(issue_id, {"where": set(), "evidence": set()})
        if where_sig:
            entry["where"].add(where_sig)
        if evidence_fp:
            entry["evidence"].add(evidence_fp)

    if not to_add:
        return
    to_add.sort(key=lambda item: (str(item.get("issue_id", "")), str(item.get("message", ""))))
    report_issues.extend(to_add)


def enrich_blocked_downmix_render_diagnostics(report: dict) -> dict:
    recommendations = report.get("recommendations")
    if not isinstance(recommendations, list):
        return report

    saw_qa_delta_render_reject = False
    saw_reference_level_reject = False
    saw_corr_reject = False

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        if rec.get("action_id") != "ACTION.DOWNMIX.RENDER":
            continue
        if rec.get("eligible_render") is not False:
            continue
        gate_results = rec.get("gate_results")
        if not isinstance(gate_results, list):
            continue

        rejected_gate_ids = {
            result.get("gate_id")
            for result in gate_results
            if isinstance(result, dict)
            and result.get("context") == "render"
            and result.get("outcome") == "reject"
            and isinstance(result.get("gate_id"), str)
        }
        qa_delta_rejected_gate_ids = rejected_gate_ids.intersection(DOWNMIX_QA_DELTA_GATE_IDS)
        if not qa_delta_rejected_gate_ids:
            continue

        saw_qa_delta_render_reject = True
        if (
            DOWNMIX_QA_LUFS_DELTA_GATE_ID in qa_delta_rejected_gate_ids
            or DOWNMIX_QA_TRUE_PEAK_DELTA_GATE_ID in qa_delta_rejected_gate_ids
        ):
            saw_reference_level_reject = True
        if DOWNMIX_QA_CORR_DELTA_GATE_ID in qa_delta_rejected_gate_ids:
            saw_corr_reject = True

    if not saw_qa_delta_render_reject:
        return report

    existing_ids = {
        rec.get("recommendation_id")
        for rec in recommendations
        if isinstance(rec, dict) and isinstance(rec.get("recommendation_id"), str)
    }
    diagnostics: List[tuple[str, str, str]] = [
        (
            "REC.DIAGNOSTIC.REVIEW_POLICY_MATRIX.001",
            "ACTION.DIAGNOSTIC.REVIEW_DOWNMIX_POLICY_MATRIX",
            "Review policy_id/matrix_id/target_layout_id mapping before retrying render.",
        )
    ]
    if saw_reference_level_reject:
        diagnostics.append(
            (
                "REC.DIAGNOSTIC.CHECK_REFERENCE_LEVELS.001",
                "ACTION.DIAGNOSTIC.CHECK_REFERENCE_LEVELS",
                "Verify folded/reference LUFS and true-peak alignment and calibration.",
            )
        )
    if saw_corr_reject:
        diagnostics.append(
            (
                "REC.DIAGNOSTIC.CHECK_PHASE_CORRELATION.001",
                "ACTION.DIAGNOSTIC.CHECK_PHASE_CORRELATION",
                "Inspect phase correlation and routing/polarity before retrying render.",
            )
        )

    for rec_id, action_id, notes in diagnostics:
        if rec_id in existing_ids:
            continue
        recommendations.append(
            {
                "recommendation_id": rec_id,
                "action_id": action_id,
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "session"},
                "params": [],
                "notes": notes,
            }
        )
        existing_ids.add(rec_id)

    return report


def build_minimal_report_for_downmix_qa(
    *,
    repo_root: Path | None = None,
    qa_payload: dict,
    profile_id: str | None = None,
    profiles_path: Path | None = None,
) -> dict:
    downmix_qa_raw = qa_payload.get("downmix_qa", {})
    if not isinstance(downmix_qa_raw, dict):
        downmix_qa_raw = {}

    issues_raw = downmix_qa_raw.get("issues", [])
    if not isinstance(issues_raw, list):
        issues_raw = []
    issues = [i for i in issues_raw if isinstance(i, dict)]

    measurements = downmix_qa_raw.get("measurements", [])
    if not isinstance(measurements, list):
        measurements = []

    downmix_qa = dict(downmix_qa_raw)
    downmix_qa["issues"] = issues
    downmix_qa["measurements"] = measurements
    downmix_qa.setdefault("src_path", "")
    downmix_qa.setdefault("ref_path", "")
    downmix_qa.setdefault("log", "")

    report_id = _hash_report_payload(downmix_qa)
    ontology_version = _load_ontology_version(ontology_dir() / "ontology.yaml")

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_id": report_id,
        "project_id": report_id,
        "generated_at": DEFAULT_GENERATED_AT,
        "registry_file": "ontology",
        "engine_version": engine_version,
        "ontology_version": ontology_version,
        "session": {
            "session_id": "SESSION.DOWNMIX.QA",
            "stems": [],
        },
        "issues": [],
        "recommendations": [],
        "downmix_qa": downmix_qa,
    }
    if isinstance(profile_id, str) and profile_id.strip():
        report["profile_id"] = profile_id.strip()
    merge_downmix_qa_issues_into_report(report)
    if issues:
        recommendations = report["recommendations"]
        rec_id = "REC.DIAGNOSTIC.CHECK_DOWNMIX_QA.001"
        has_rec = any(
            isinstance(rec, dict) and rec.get("recommendation_id") == rec_id
            for rec in recommendations
        )
        measurement_map: Dict[str, Dict[str, Any]] = {}
        for item in measurements:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id:
                measurement_map[evidence_id] = item

        param_specs = [
            ("EVID.DOWNMIX.QA.LUFS_DELTA", "PARAM.DOWNMIX.QA.LUFS_DELTA", "UNIT.LUFS"),
            (
                "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                "PARAM.DOWNMIX.QA.TRUE_PEAK_DELTA",
                "UNIT.DBTP",
            ),
            ("EVID.DOWNMIX.QA.CORR_DELTA", "PARAM.DOWNMIX.QA.CORR_DELTA", "UNIT.CORRELATION"),
        ]
        delta_params: List[Dict[str, Any]] = []
        for evidence_id, param_id, unit_id in param_specs:
            measurement = measurement_map.get(evidence_id)
            if not measurement:
                continue
            param_entry = {"param_id": param_id, "value": measurement.get("value")}
            unit_value = measurement.get("unit_id") or unit_id
            if unit_value:
                param_entry["unit_id"] = unit_value
            delta_params.append(param_entry)

        if not has_rec:
            recommendations.append(
                {
                    "recommendation_id": rec_id,
                    "action_id": "ACTION.DIAGNOSTIC.CHECK_DOWNMIX_QA",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {"scope": "session"},
                    "params": list(delta_params),
                    "notes": (
                        "Downmix QA deltas exceeded thresholds; review matrix/policy/export."
                    ),
                }
            )

        render_rec_id = "REC.DOWNMIX.RENDER.001"
        has_render = any(
            isinstance(rec, dict) and rec.get("recommendation_id") == render_rec_id
            for rec in recommendations
        )
        policy_id = downmix_qa_raw.get("policy_id")
        if isinstance(policy_id, str) and policy_id.strip() and not has_render:
            target_layout_id = "LAYOUT.2_0"
            log_payload = downmix_qa_raw.get("log")
            parsed_log = None
            if isinstance(log_payload, str) and log_payload:
                try:
                    parsed_log = json.loads(log_payload)
                except json.JSONDecodeError:
                    parsed_log = None
            elif isinstance(log_payload, dict):
                parsed_log = log_payload
            if isinstance(parsed_log, dict):
                candidate = parsed_log.get("target_layout_id")
                if isinstance(candidate, str) and candidate:
                    target_layout_id = candidate

            render_params: List[Dict[str, Any]] = [
                {"param_id": "PARAM.DOWNMIX.POLICY_ID", "value": policy_id},
                {"param_id": "PARAM.DOWNMIX.TARGET_LAYOUT_ID", "value": target_layout_id},
            ]
            render_params.extend(delta_params)
            recommendations.append(
                {
                    "recommendation_id": render_rec_id,
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {"scope": "session"},
                    "params": render_params,
                }
            )

        apply_gates_to_report(
            report,
            policy_path=ontology_dir() / "policies" / "gates.yaml",
            profile_id=profile_id,
            profiles_path=profiles_path,
        )
        enrich_blocked_downmix_render_diagnostics(report)
    return report
