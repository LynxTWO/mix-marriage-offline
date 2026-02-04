from __future__ import annotations

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


def _sorted_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(issue: Dict[str, Any]) -> tuple:
        severity = issue.get("severity", 0)
        if not isinstance(severity, (int, float)):
            severity = 0
        return (-severity, str(issue.get("issue_id", "")), str(issue.get("message", "")))

    return sorted(issues, key=sort_key)


def _hash_report_payload(downmix_qa: Dict[str, Any]) -> str:
    payload = json.dumps(downmix_qa, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    sorted_issues = _sorted_issues([i for i in issues_raw if isinstance(i, dict)])

    measurements = downmix_qa_raw.get("measurements", [])
    if not isinstance(measurements, list):
        measurements = []

    downmix_qa = dict(downmix_qa_raw)
    downmix_qa["issues"] = sorted_issues
    downmix_qa["measurements"] = measurements
    downmix_qa.setdefault("src_path", "")
    downmix_qa.setdefault("ref_path", "")
    downmix_qa.setdefault("log", "")

    report_id = _hash_report_payload(downmix_qa)
    ontology_version = _load_ontology_version(repo_root / "ontology" / "ontology.yaml")

    return {
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
        "issues": sorted_issues,
        "recommendations": [],
        "downmix_qa": downmix_qa,
    }
