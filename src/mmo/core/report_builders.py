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

from mmo import __version__ as engine_version

REPORT_SCHEMA_VERSION = "0.1.0"
DEFAULT_GENERATED_AT = "2000-01-01T00:00:00Z"


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


def build_minimal_report_for_downmix_qa(
    *,
    repo_root: Path,
    qa_payload: dict,
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
    ontology_version = _load_ontology_version(repo_root / "ontology" / "ontology.yaml")

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
    merge_downmix_qa_issues_into_report(report)
    return report
