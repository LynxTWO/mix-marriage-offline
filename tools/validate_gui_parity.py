"""Validate docs/gui_parity.md required plans, links, and checklist items."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Primary Plan",
    "## Fallback Plan Until Parity",
    "## Required Links",
    "## Required Screens",
    "## Required Behaviors",
    "## Exit Rule",
)

REQUIRED_LINK_PATHS: tuple[str, ...] = (
    "docs/06-roadmap.md",
    "PROJECT_WHEN_COMPLETE.md",
    "gui/desktop-tauri/README.md",
    "docs/manual/10-gui-walkthrough.md",
)

REQUIRED_SCREENS: tuple[str, ...] = (
    "Validate",
    "Analyze",
    "Scene",
    "Render",
    "Results",
    "Compare",
)

REQUIRED_BEHAVIORS: tuple[str, ...] = (
    "A/B loudness-comp compare",
    "Scene locks edit",
)

_SECTION_RE = re.compile(
    r"(?ms)^## (?P<title>[^\n]+)\n(?P<body>.*?)(?=^## |\Z)"
)
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?P<target>[^)\s]+(?:#[^)]+)?)\)")


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_repo_relative(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for match in _SECTION_RE.finditer(text):
        title = match.group("title").strip()
        body = match.group("body").strip()
        sections[f"## {title}"] = body
    return sections


def _extract_repo_relative_links(*, text: str, doc_path: Path, repo_root: Path) -> set[str]:
    links: set[str] = set()
    for match in _MARKDOWN_LINK_RE.finditer(text):
        raw_target = match.group("target").strip()
        target = raw_target.split("#", 1)[0].strip()
        if not target:
            continue
        if "://" in target or target.startswith("mailto:"):
            continue
        resolved = _resolve_path(target, repo_root=doc_path.parent)
        links.add(_normalize_repo_relative(resolved, repo_root=repo_root))
    return links


def _find_checkbox_state(text: str, label: str) -> bool | None:
    pattern = re.compile(
        rf"(?m)^- \[(?P<checked>[ xX])\] {re.escape(label)}(?:\b|:)"
    )
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("checked").strip().lower() == "x"


def validate_gui_parity(*, repo_root: Path, parity_doc: Path) -> dict[str, Any]:
    errors: list[str] = []
    display_path = _display_path(parity_doc, repo_root=repo_root)

    if not parity_doc.is_file():
        errors.append(f"GUI parity doc is missing: {display_path}")
        return {
            "ok": False,
            "path": display_path,
            "missing_headings": list(REQUIRED_HEADINGS),
            "missing_links": list(REQUIRED_LINK_PATHS),
            "missing_screens": list(REQUIRED_SCREENS),
            "missing_behaviors": list(REQUIRED_BEHAVIORS),
            "screen_states": {},
            "behavior_states": {},
            "plan_errors": [],
            "errors": errors,
        }

    try:
        text = parity_doc.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Failed to read GUI parity doc {display_path}: {exc}")
        return {
            "ok": False,
            "path": display_path,
            "missing_headings": list(REQUIRED_HEADINGS),
            "missing_links": list(REQUIRED_LINK_PATHS),
            "missing_screens": list(REQUIRED_SCREENS),
            "missing_behaviors": list(REQUIRED_BEHAVIORS),
            "screen_states": {},
            "behavior_states": {},
            "plan_errors": [],
            "errors": errors,
        }

    sections = _extract_sections(text)
    missing_headings = [heading for heading in REQUIRED_HEADINGS if heading not in sections]

    links = _extract_repo_relative_links(text=text, doc_path=parity_doc, repo_root=repo_root)
    missing_links = [path for path in REQUIRED_LINK_PATHS if path not in links]
    broken_links = [
        path for path in REQUIRED_LINK_PATHS if path in links and not (repo_root / path).is_file()
    ]

    screen_states = {
        label: _find_checkbox_state(text, label) for label in REQUIRED_SCREENS
    }
    behavior_states = {
        label: _find_checkbox_state(text, label) for label in REQUIRED_BEHAVIORS
    }
    missing_screens = [
        label for label, state in screen_states.items() if state is None
    ]
    missing_behaviors = [
        label for label, state in behavior_states.items() if state is None
    ]

    plan_errors: list[str] = []
    primary_text = sections.get("## Primary Plan", "")
    fallback_text = sections.get("## Fallback Plan Until Parity", "")
    exit_rule_text = sections.get("## Exit Rule", "")
    if primary_text and "Tauri" not in primary_text:
        plan_errors.append("Primary Plan must name Tauri as the primary GUI plan.")
    if primary_text and "primary GUI plan" not in primary_text:
        plan_errors.append(
            "Primary Plan must explicitly say it is the primary GUI plan."
        )
    if fallback_text and "CustomTkinter" not in fallback_text:
        plan_errors.append(
            "Fallback Plan Until Parity must name CustomTkinter as the fallback."
        )
    if fallback_text and "deprecated after parity lands" not in fallback_text:
        plan_errors.append(
            "Fallback Plan Until Parity must say CustomTkinter is deprecated after parity lands."
        )
    if exit_rule_text and "Tauri" not in exit_rule_text:
        plan_errors.append("Exit Rule must state that parity lands in the Tauri app.")

    for heading in missing_headings:
        errors.append(f"Missing required heading: {heading}")
    for path in missing_links:
        errors.append(f"Missing required link target: {path}")
    for path in broken_links:
        errors.append(f"Required link target does not exist in repo: {path}")
    for label in missing_screens:
        errors.append(f"Missing required screen checklist item: {label}")
    for label in missing_behaviors:
        errors.append(f"Missing required behavior checklist item: {label}")
    errors.extend(plan_errors)
    errors = sorted(errors)

    return {
        "ok": not errors,
        "path": display_path,
        "missing_headings": missing_headings,
        "missing_links": missing_links,
        "missing_screens": missing_screens,
        "missing_behaviors": missing_behaviors,
        "screen_states": screen_states,
        "behavior_states": behavior_states,
        "plan_errors": plan_errors,
        "errors": errors,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate the canonical GUI parity checklist."
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing docs/gui_parity.md.",
    )
    parser.add_argument(
        "--parity-doc",
        default="docs/gui_parity.md",
        help="Path to the GUI parity markdown file.",
    )
    args = parser.parse_args()

    root = Path(args.repo_root)
    parity_doc = _resolve_path(args.parity_doc, repo_root=root)
    result = validate_gui_parity(repo_root=root, parity_doc=parity_doc)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
