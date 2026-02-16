"""Sync shared agent specs from docs/claude_agents/ into .claude/agents/.

Copy-only, allowlist-only, deterministic.  Copies each file from the
canonical source (docs/claude_agents/) to the local workspace
(.claude/agents/) so that every contributor gets the same agent
definitions after a single sync command.

Usage:
    python tools/sync_claude_agents.py
    python tools/sync_claude_agents.py --dry-run
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SRC_DIR = REPO_ROOT / "docs" / "claude_agents"
DST_DIR = REPO_ROOT / ".claude" / "agents"

# Allowlist: only these filenames are synced.  Deterministic sorted order.
AGENT_FILES: tuple[str, ...] = tuple(sorted((
    "mmo-contracts-guardian.md",
    "mmo-core-coder.md",
    "mmo-docs-editor.md",
    "mmo-planner.md",
    "mmo-reviewer.md",
    "mmo-test-engineer.md",
)))


def sync(*, dry_run: bool = False) -> dict[str, list[str]]:
    """Copy allowlisted agent specs to .claude/agents/.

    Returns a dict with ``"copied"`` (files that changed) and
    ``"skipped"`` (already identical) lists, both sorted.
    """
    copied: list[str] = []
    skipped: list[str] = []

    if not SRC_DIR.is_dir():
        print(
            f"Source directory missing: {SRC_DIR.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return {"copied": copied, "skipped": skipped}

    for filename in AGENT_FILES:
        src = SRC_DIR / filename
        dst = DST_DIR / filename

        if not src.is_file():
            print(
                f"SKIP  allowlisted file missing in source: {filename}",
                file=sys.stderr,
            )
            continue

        # Content-compare: skip if already identical.
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            skipped.append(filename)
            continue

        if dry_run:
            print(f"  [dry-run] COPY {filename}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        copied.append(filename)

    return {"copied": sorted(copied), "skipped": sorted(skipped)}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args()

    result = sync(dry_run=args.dry_run)
    n_copied = len(result["copied"])
    n_skipped = len(result["skipped"])

    if n_copied == 0:
        print(f"Agents are already up to date ({n_skipped} file(s) checked).")
    else:
        print(f"Copied {n_copied} file(s), {n_skipped} already up to date.")


if __name__ == "__main__":
    main()
