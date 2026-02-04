from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from run_fixtures import discover_fixtures, evaluate_fixture, load_yaml
except Exception as exc:  # pragma: no cover - environment issue
    discover_fixtures = None
    evaluate_fixture = None
    load_yaml = None
    RUN_FIXTURES_IMPORT_ERROR = exc
else:
    RUN_FIXTURES_IMPORT_ERROR = None

from mmo.core.pipeline import load_plugins, run_detectors, run_resolvers


def _require_fixtures_runner() -> None:
    if RUN_FIXTURES_IMPORT_ERROR is not None:
        pytest.skip(f"run_fixtures unavailable: {RUN_FIXTURES_IMPORT_ERROR}")


def test_session_fixtures() -> None:
    _require_fixtures_runner()
    fixtures_dir = ROOT_DIR / "fixtures" / "sessions"
    fixture_paths = discover_fixtures(fixtures_dir)
    assert fixture_paths, f"No fixtures found in {fixtures_dir}"

    for fixture_path in fixture_paths:
        fixture = load_yaml(fixture_path)
        expected_issue_ids, actual_issue_ids = evaluate_fixture(fixture_path, fixture)
        assert actual_issue_ids == expected_issue_ids, (
            f"{fixture_path}: expected {expected_issue_ids}, got {actual_issue_ids}"
        )


def _sort_issues(issues: list[Dict[str, Any]]) -> None:
    for issue in issues:
        evidence = issue.get("evidence")
        if isinstance(evidence, list):
            evidence.sort(
                key=lambda item: (item.get("evidence_id", ""), str(item.get("value")))
            )
    issues.sort(
        key=lambda issue: (
            issue.get("issue_id", ""),
            (issue.get("target") or {}).get("scope", ""),
            (issue.get("target") or {}).get("stem_id") or "",
            issue.get("message") or "",
        )
    )


def _sort_recommendations(recommendations: list[Dict[str, Any]]) -> None:
    recommendations.sort(
        key=lambda rec: (rec.get("recommendation_id", ""), rec.get("action_id", ""))
    )


def _normalize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(report)
    issues = normalized.get("issues") or []
    if isinstance(issues, list):
        _sort_issues(issues)
        normalized["issues"] = issues
    recommendations = normalized.get("recommendations") or []
    if isinstance(recommendations, list):
        _sort_recommendations(recommendations)
        normalized["recommendations"] = recommendations
    return normalized


def test_pipeline_fixture() -> None:
    fixtures_dir = ROOT_DIR / "fixtures" / "pipeline"
    report_input_path = fixtures_dir / "report.input.json"
    report_expected_path = fixtures_dir / "report.expected.json"

    report = json.loads(report_input_path.read_text(encoding="utf-8"))
    expected = json.loads(report_expected_path.read_text(encoding="utf-8"))

    plugins_dir = fixtures_dir / "plugins"
    plugins = load_plugins(plugins_dir)
    run_detectors(report, plugins)
    run_resolvers(report, plugins)

    assert _normalize_report(report) == _normalize_report(expected)
