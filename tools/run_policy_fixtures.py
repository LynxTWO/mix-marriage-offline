"""Run policy-validation fixtures for downmix policies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_policies import validate_registry  # noqa: E402


def _load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot parse YAML fixtures.")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _count_issues(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"error": 0, "warn": 0}
    for issue in issues:
        label = issue.get("severity_label")
        if label in counts:
            counts[label] += 1
    return counts


def _must_include_counts(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for issue in issues:
        issue_id = issue.get("issue_id")
        severity = issue.get("severity_label")
        if not issue_id or not severity:
            continue
        key = f"{issue_id}:{severity}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_fixtures(fixtures_dir: Path) -> int:
    fixture_files = sorted(fixtures_dir.glob("*.yaml"))
    if not fixture_files:
        print(f"No fixtures found in {fixtures_dir}", file=sys.stderr)
        return 1

    failures = 0
    for fixture_path in fixture_files:
        try:
            fixture = _load_yaml(fixture_path)
        except Exception as exc:
            print(f"{fixture_path}: failed to load fixture: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not isinstance(fixture, dict):
            print(f"{fixture_path}: fixture must be a map", file=sys.stderr)
            failures += 1
            continue

        if fixture.get("fixture_type") != "policy_validation":
            print(f"{fixture_path}: fixture_type must be policy_validation", file=sys.stderr)
            failures += 1
            continue

        registry_file = fixture.get("inputs", {}).get("registry_file")
        if not isinstance(registry_file, str):
            print(f"{fixture_path}: inputs.registry_file missing", file=sys.stderr)
            failures += 1
            continue

        repo_root = Path(__file__).resolve().parents[1]
        result = validate_registry((repo_root / registry_file).resolve())
        expected_counts = fixture.get("expected", {}).get("issue_counts", {})
        expected_error = expected_counts.get("error")
        expected_warn = expected_counts.get("warn")

        actual_counts = _count_issues(result["issues"])
        fixture_failed = False

        if expected_error is not None and actual_counts["error"] != expected_error:
            print(
                f"{fixture_path}: expected {expected_error} errors, got {actual_counts['error']}",
                file=sys.stderr,
            )
            fixture_failed = True

        if expected_warn is not None and actual_counts["warn"] != expected_warn:
            print(
                f"{fixture_path}: expected {expected_warn} warns, got {actual_counts['warn']}",
                file=sys.stderr,
            )
            fixture_failed = True

        must_include = fixture.get("expected", {}).get("must_include", [])
        counts_by_issue = _must_include_counts(result["issues"])
        for requirement in must_include:
            if not isinstance(requirement, dict):
                continue
            issue_id = requirement.get("issue_id")
            severity = requirement.get("severity_label")
            count_min = requirement.get("count_min", 1)
            key = f"{issue_id}:{severity}"
            if counts_by_issue.get(key, 0) < count_min:
                print(
                    f"{fixture_path}: missing {issue_id} ({severity}) >= {count_min}",
                    file=sys.stderr,
                )
                fixture_failed = True

        if fixture_failed:
            failures += 1
        else:
            print(f"{fixture_path}: OK")

    if failures:
        print(f"Fixture failures: {failures}", file=sys.stderr)
        return 1
    print("All policy fixtures passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run policy-validation fixtures for downmix registries/packs."
    )
    parser.add_argument(
        "fixtures_dir",
        nargs="?",
        default=None,
        help="Directory containing policy validation fixtures.",
    )
    parser.add_argument(
        "--fixtures",
        dest="fixtures",
        default=None,
        help=(
            "Optional explicit path to the fixtures directory. "
            "If provided, this overrides the positional fixtures_dir."
        ),
    )
    args = parser.parse_args()

    fixtures_value = args.fixtures or args.fixtures_dir or "fixtures/policies/downmix"
    fixtures_dir = Path(fixtures_value)
    return run_fixtures(fixtures_dir)


if __name__ == "__main__":
    raise SystemExit(main())
