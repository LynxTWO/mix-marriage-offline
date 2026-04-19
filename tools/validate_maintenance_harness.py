"""Validate anti-dark-code maintenance assets and narrow drift checks."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_FILE_SNIPPETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        ".github/pull_request_template.md",
        (
            "# PR Checklist",
            "## Plain Change Record",
            "- What changed:",
            "- Why it changed:",
            "- What remains unclear:",
            "- Risk changed:",
            "- Approval needed:",
            "- Docs updated:",
            "- Tests or checks run:",
            "- Repo evidence reviewed:",
            "docs/STATUS.md",
            "docs/milestones.yaml",
            "CHANGELOG.md",
            "python tools/validate_contracts.py",
        ),
    ),
    (
        "docs/contributing/ai-workflow.md",
        (
            "# MMO AI Workflow",
            "## Start From Repo Truth",
            "AGENTS.md",
            "docs/architecture/system-map.md",
            "docs/architecture/coverage-ledger.md",
            "docs/security/logging-audit.md",
            "docs/review/adversarial-pass.md",
            "docs/review/scenario-stress-test.md",
            "## Keep Unknowns Visible",
            "## Respect Approval Gates",
            "## Re-check Anti-Dark-Code Comments",
        ),
    ),
    (
        "docs/review/maintenance-harness.md",
        (
            "# Maintenance Harness",
            "## Hard Gates",
            "## Reviewer Checks Only",
            "## Doc Triggers",
            "## Protected Areas Requiring Approval",
            "## Logging And Telemetry Checks",
            "## Remaining Human-Review Limits",
        ),
    ),
    (
        "docs/unknowns/maintenance-harness.md",
        (
            "# Maintenance Harness Unknowns",
            "| Area or file | Concern | Why it matters |",
            ".github/pull_request_template.md",
            ".github/workflows/release.yml",
            ".claude/agents/",
            "tools/validate_maintenance_harness.py",
        ),
    ),
    (
        "docs/README.md",
        (
            "## Contribution Workflow",
            "contributing/ai-workflow.md",
            ".github/pull_request_template.md",
        ),
    ),
)

SCAN_ROOTS: tuple[str, ...] = ("src", "gui", "tools", "tests", "examples", ".github")
SCAN_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".mjs",
    ".js",
    ".cjs",
    ".ts",
    ".tsx",
    ".rs",
    ".sh",
    ".ps1",
    ".cmd",
    ".yml",
    ".yaml",
)
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
}

LOGGING_CALL_RE = re.compile(
    r"(console\.(?:log|error|warn)|logger\.[A-Za-z_][A-Za-z0-9_]*|logging\.[A-Za-z_][A-Za-z0-9_]*|print\s*\()"
)
SENSITIVE_MARKER_RE = re.compile(
    r"password|passwd|secret|api[ _-]?key|authorization|cookie|session[ _-]?id|"
    r"access[ _-]?token|refresh[ _-]?token|signed[ _-]?url|connection string|private key",
    re.IGNORECASE,
)
LIMIT_NOTE = (
    "This is an obvious-drift check only. It does not cover stderr forwarding, "
    "JSON stdout, trace uploads, or artifact sharing."
)


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _check_required_files(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    details: list[dict[str, Any]] = []
    errors: list[str] = []

    for relative_path, snippets in REQUIRED_FILE_SNIPPETS:
        path = repo_root / relative_path
        file_details: dict[str, Any] = {
            "path": relative_path,
            "ok": True,
            "missing_snippets": [],
        }
        if not path.is_file():
            file_details["ok"] = False
            errors.append(f"Required maintenance asset is missing: {relative_path}")
            details.append(file_details)
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            file_details["ok"] = False
            file_details["read_error"] = str(exc)
            errors.append(f"Failed to read maintenance asset {relative_path}: {exc}")
            details.append(file_details)
            continue

        missing_snippets = [snippet for snippet in snippets if snippet not in text]
        file_details["missing_snippets"] = missing_snippets
        if missing_snippets:
            file_details["ok"] = False
            for snippet in missing_snippets:
                errors.append(
                    f"{relative_path} is missing required snippet: {snippet!r}"
                )
        details.append(file_details)

    return details, sorted(errors)


def _iter_scan_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            files.append(path)
    return sorted(files)


def _scan_for_sensitive_logging(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    matches: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in _iter_scan_files(repo_root):
        display_path = _display_path(path, repo_root=repo_root)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            errors.append(f"Failed to read scan target {display_path}: {exc}")
            continue

        for line_number, line in enumerate(lines, start=1):
            if LOGGING_CALL_RE.search(line) is None:
                continue
            marker_match = SENSITIVE_MARKER_RE.search(line)
            if marker_match is None:
                continue
            matches.append(
                {
                    "path": display_path,
                    "line": line_number,
                    "marker": marker_match.group(0),
                    "text": line.strip(),
                }
            )

    for match in matches:
        errors.append(
            "Obvious sensitive logging pattern found at "
            f"{match['path']}:{match['line']} (marker: {match['marker']})."
        )

    return {
        "ok": not matches,
        "scan_roots": list(SCAN_ROOTS),
        "matches": matches,
        "limit_note": LIMIT_NOTE,
    }, errors


def validate_maintenance_harness(*, repo_root: Path) -> dict[str, Any]:
    required_files, file_errors = _check_required_files(repo_root)
    logging_scan, logging_errors = _scan_for_sensitive_logging(repo_root)
    errors = sorted([*file_errors, *logging_errors])

    return {
        "ok": not errors,
        "required_files": required_files,
        "logging_scan": logging_scan,
        "errors": errors,
        "warnings": [LIMIT_NOTE],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate anti-dark-code maintenance assets."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root containing docs/, tools/, and .github/.",
    )
    args = parser.parse_args()

    result = validate_maintenance_harness(repo_root=Path(args.repo_root))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
