"""Shared canonical-state screenshot inventory for MMO manual tooling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CanonicalScreenshot:
    """One committed manual screenshot baseline."""

    filename: str
    state_name: str
    chapter_location: str


CANONICAL_SCREENSHOTS: tuple[CanonicalScreenshot, ...] = (
    CanonicalScreenshot(
        filename="tauri_session_ready.png",
        state_name="Validate screen, session-ready empty state",
        chapter_location="Desktop GUI walkthrough / Validate",
    ),
    CanonicalScreenshot(
        filename="tauri_session_loaded_compact.png",
        state_name="Session shell, loaded compact workspace mode",
        chapter_location="Desktop GUI walkthrough / Shared session shell",
    ),
    CanonicalScreenshot(
        filename="tauri_scene_loaded.png",
        state_name="Scene screen, loaded with lock context",
        chapter_location="Desktop GUI walkthrough / Scene",
    ),
    CanonicalScreenshot(
        filename="tauri_scene_locks_editor.png",
        state_name="Scene screen, lock editor open",
        chapter_location="Desktop GUI walkthrough / Scene",
    ),
    CanonicalScreenshot(
        filename="tauri_results_loaded.png",
        state_name="Results screen, loaded default state",
        chapter_location="Desktop GUI walkthrough / Results",
    ),
    CanonicalScreenshot(
        filename="tauri_compare_loaded.png",
        state_name="Compare screen, loaded loudness-matched state",
        chapter_location="Desktop GUI walkthrough / Compare",
    ),
)

TEXT_ONLY_CANONICAL_STATES: tuple[CanonicalScreenshot, ...] = (
    CanonicalScreenshot(
        filename="not-committed",
        state_name="Results screen, secondary inspection expanded",
        chapter_location="Desktop GUI walkthrough / Results",
    ),
)

DEFAULT_BASELINE_DIR = Path("docs/manual/assets/screenshots")
WALKTHROUGH_PATH = Path("docs/manual/10-gui-walkthrough.md")
SCREENSHOT_POLICY_PATH = DEFAULT_BASELINE_DIR / "README.md"


def canonical_filenames() -> tuple[str, ...]:
    """Return committed canonical screenshot filenames in stable order."""

    return tuple(item.filename for item in CANONICAL_SCREENSHOTS)


def format_screenshot_inventory(*, include_locations: bool = False, bullet: str = "  - ") -> str:
    """Render the committed canonical screenshot list for CLI help/output."""

    lines: list[str] = []
    for item in CANONICAL_SCREENSHOTS:
        line = f"{bullet}{item.filename} — {item.state_name}"
        if include_locations:
            line += f" ({item.chapter_location})"
        lines.append(line)
    return "\n".join(lines)


def format_text_only_inventory(*, include_locations: bool = False, bullet: str = "  - ") -> str:
    """Render named canonical states that stay text-only."""

    lines: list[str] = []
    for item in TEXT_ONLY_CANONICAL_STATES:
        line = f"{bullet}{item.state_name}"
        if include_locations:
            line += f" ({item.chapter_location})"
        lines.append(line)
    return "\n".join(lines)
