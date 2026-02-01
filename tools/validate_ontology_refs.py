"""Ontology referential integrity validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


ISSUE_ONTOLOGY_REF_MISSING = "ISSUE.VALIDATION.ONTOLOGY_REF_MISSING"
ISSUE_POLICY_REF_MISSING = "ISSUE.VALIDATION.POLICY_REF_MISSING"
ISSUE_POLICY_PARSE_ERROR = "ISSUE.VALIDATION.POLICY_PARSE_ERROR"
ISSUE_POLICY_SCHEMA_INVALID = "ISSUE.VALIDATION.POLICY_SCHEMA_INVALID"


ROLE_FIELDS = (
    "role_ids",
    "roles",
    "target_role_ids",
    "target_roles",
    "typical_role_ids",
    "typical_roles",
)
FEATURE_FIELDS = (
    "feature_ids",
    "features",
    "target_feature_ids",
    "target_features",
    "typical_feature_ids",
    "typical_features",
    "required_feature_ids",
    "required_features",
)
PARAM_FIELDS = (
    "param_ids",
    "params",
    "required_params",
    "optional_params",
    "typical_param_ids",
    "typical_params",
)


def _add_issue(
    issues: List[Dict[str, Any]],
    issue_id: Optional[str],
    severity_label: str,
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    item: Dict[str, Any] = {
        "severity_label": severity_label,
        "message": message,
    }
    if issue_id:
        item["issue_id"] = issue_id
    if evidence:
        item["evidence"] = evidence
    issues.append(item)


def _issue_id_if_present(issue_id: str, known_ids: Set[str]) -> Optional[str]:
    return issue_id if issue_id in known_ids else None


def _load_yaml(
    path: Path,
    issues: List[Dict[str, Any]],
    parse_issue_id: Optional[str],
) -> Optional[Any]:
    if yaml is None:
        _add_issue(
            issues,
            parse_issue_id,
            "error",
            "PyYAML is not installed; cannot parse YAML files.",
            {"file_path": str(path)},
        )
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:  # pragma: no cover - parse failures vary
        _add_issue(
            issues,
            parse_issue_id,
            "error",
            f"Failed to parse YAML: {exc}",
            {"file_path": str(path)},
        )
        return None


def _load_registry(
    path: Path,
    root_key: str,
    issues: List[Dict[str, Any]],
    parse_issue_id: Optional[str],
    schema_issue_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not path.exists():
        _add_issue(
            issues,
            schema_issue_id,
            "error",
            "Ontology registry file is missing.",
            {"file_path": str(path)},
        )
        return None
    data = _load_yaml(path, issues, parse_issue_id)
    if data is None:
        return None
    if not isinstance(data, dict) or root_key not in data:
        _add_issue(
            issues,
            schema_issue_id,
            "error",
            f"{path.name} is missing the root {root_key} map.",
            {"file_path": str(path)},
        )
        return None
    registry = data.get(root_key)
    if not isinstance(registry, dict):
        _add_issue(
            issues,
            schema_issue_id,
            "error",
            f"{root_key} must be a map.",
            {"file_path": str(path)},
        )
        return None
    return registry


def _registry_ids(registry: Dict[str, Any]) -> Set[str]:
    return {
        key
        for key in registry.keys()
        if isinstance(key, str) and not key.startswith("_")
    }


def _check_reference_list(
    issues: List[Dict[str, Any]],
    *,
    issue_id: str,
    field_name: str,
    values: Any,
    known_set: Optional[Set[str]],
    missing_issue_id: Optional[str],
    schema_issue_id: Optional[str],
    registry_label: str,
) -> None:
    if values is None:
        return
    if not isinstance(values, list):
        _add_issue(
            issues,
            schema_issue_id,
            "error",
            f"{issue_id}.{field_name} must be a list.",
            {"issue_id": issue_id, "field": field_name},
        )
        return

    if known_set is None:
        if values:
            _add_issue(
                issues,
                missing_issue_id,
                "error",
                f"{registry_label} registry is missing; cannot validate {field_name}.",
                {"issue_id": issue_id, "field": field_name},
            )
        return

    for value in values:
        if not isinstance(value, str) or value not in known_set:
            _add_issue(
                issues,
                missing_issue_id,
                "error",
                f"{issue_id} references unknown {registry_label} id.",
                {
                    "issue_id": issue_id,
                    "field": field_name,
                    "missing_id": value,
                },
            )


def validate_ontology(ontology_dir: Path) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    issues_path = ontology_dir / "issues.yaml"
    issues_registry = _load_registry(
        issues_path, "issues", issues, None, None
    )
    issues_set = _registry_ids(issues_registry) if issues_registry else set()

    parse_issue_id = _issue_id_if_present(ISSUE_POLICY_PARSE_ERROR, issues_set)
    schema_issue_id = _issue_id_if_present(ISSUE_POLICY_SCHEMA_INVALID, issues_set)
    missing_ref_issue_id = _issue_id_if_present(ISSUE_ONTOLOGY_REF_MISSING, issues_set)
    if missing_ref_issue_id is None:
        missing_ref_issue_id = _issue_id_if_present(ISSUE_POLICY_REF_MISSING, issues_set)

    evidence_path = ontology_dir / "evidence.yaml"
    evidence_registry = _load_registry(
        evidence_path, "evidence", issues, parse_issue_id, schema_issue_id
    )
    evidence_ids = _registry_ids(evidence_registry) if evidence_registry else None

    actions_ids: Optional[Set[str]] = None
    actions_path = ontology_dir / "actions.yaml"
    if actions_path.exists():
        actions_registry = _load_registry(
            actions_path, "actions", issues, parse_issue_id, schema_issue_id
        )
        actions_ids = _registry_ids(actions_registry) if actions_registry else None

    params_ids: Optional[Set[str]] = None
    params_path = ontology_dir / "params.yaml"
    if params_path.exists():
        params_registry = _load_registry(
            params_path, "params", issues, parse_issue_id, schema_issue_id
        )
        params_ids = _registry_ids(params_registry) if params_registry else None

    roles_ids: Optional[Set[str]] = None
    roles_path = ontology_dir / "roles.yaml"
    if roles_path.exists():
        roles_registry = _load_registry(
            roles_path, "roles", issues, parse_issue_id, schema_issue_id
        )
        roles_ids = _registry_ids(roles_registry) if roles_registry else None

    features_ids: Optional[Set[str]] = None
    features_path = ontology_dir / "features.yaml"
    if features_path.exists():
        features_registry = _load_registry(
            features_path, "features", issues, parse_issue_id, schema_issue_id
        )
        features_ids = _registry_ids(features_registry) if features_registry else None

    if issues_registry:
        for issue_id, issue_entry in issues_registry.items():
            if not isinstance(issue_id, str) or issue_id.startswith("_"):
                continue
            if not issue_id.startswith("ISSUE."):
                continue
            if not isinstance(issue_entry, dict):
                _add_issue(
                    issues,
                    schema_issue_id,
                    "error",
                    "Issue entry must be a map.",
                    {"issue_id": issue_id},
                )
                continue

            _check_reference_list(
                issues,
                issue_id=issue_id,
                field_name="typical_evidence_ids",
                values=issue_entry.get("typical_evidence_ids"),
                known_set=evidence_ids,
                missing_issue_id=missing_ref_issue_id,
                schema_issue_id=schema_issue_id,
                registry_label="evidence",
            )

            _check_reference_list(
                issues,
                issue_id=issue_id,
                field_name="suggested_actions",
                values=issue_entry.get("suggested_actions"),
                known_set=actions_ids,
                missing_issue_id=missing_ref_issue_id,
                schema_issue_id=schema_issue_id,
                registry_label="actions",
            )

            for field_name in ROLE_FIELDS:
                if field_name in issue_entry:
                    _check_reference_list(
                        issues,
                        issue_id=issue_id,
                        field_name=field_name,
                        values=issue_entry.get(field_name),
                        known_set=roles_ids,
                        missing_issue_id=missing_ref_issue_id,
                        schema_issue_id=schema_issue_id,
                        registry_label="roles",
                    )

            for field_name in FEATURE_FIELDS:
                if field_name in issue_entry:
                    _check_reference_list(
                        issues,
                        issue_id=issue_id,
                        field_name=field_name,
                        values=issue_entry.get(field_name),
                        known_set=features_ids,
                        missing_issue_id=missing_ref_issue_id,
                        schema_issue_id=schema_issue_id,
                        registry_label="features",
                    )

            for field_name in PARAM_FIELDS:
                if field_name in issue_entry:
                    _check_reference_list(
                        issues,
                        issue_id=issue_id,
                        field_name=field_name,
                        values=issue_entry.get(field_name),
                        known_set=params_ids,
                        missing_issue_id=missing_ref_issue_id,
                        schema_issue_id=schema_issue_id,
                        registry_label="params",
                    )

    error_count = sum(1 for issue in issues if issue.get("severity_label") == "error")
    warn_count = sum(1 for issue in issues if issue.get("severity_label") == "warn")

    return {
        "registry_file": str(ontology_dir),
        "ok": error_count == 0,
        "issue_counts": {"error": error_count, "warn": warn_count},
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ontology registry references."
    )
    parser.add_argument(
        "--ontology",
        dest="ontology",
        default="ontology",
        help="Path to the ontology directory.",
    )
    args = parser.parse_args()

    ontology_dir = Path(args.ontology)
    result = validate_ontology(ontology_dir)
    print(json.dumps(result, indent=2))
    return 1 if result["issue_counts"]["error"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
