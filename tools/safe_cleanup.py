"""Allowlist-only cleanup for repo-local temp directories.

This script removes ONLY the canonical temp dirs listed in CLAUDE.md.
It never uses pattern matching, regex, name-length heuristics, or root sweeps.

Usage:
    python tools/safe_cleanup.py [--repo-root <path>] [--dry-run]

Output:
    Deterministic JSON summary of what was removed and what was skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Canonical allowlist — must match CLAUDE.md exactly.
# These are the ONLY dirs this script will ever delete.
ALLOWLISTED_DIRS: tuple[str, ...] = (
    ".pytest_cache",
    ".tmp_claude",
    ".tmp_codex",
    ".tmp_pytest",
    "sandbox_tmp",
)

# Glob prefix for pytest-cache-files-* (repo root only).
PYTEST_CACHE_FILES_PREFIX = "pytest-cache-files-"


def _on_rm_error(func, path, _exc_info):  # noqa: ANN001
    """Handle read-only files during rmtree (common on Windows/OneDrive)."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _safe_rmtree(target: Path) -> None:
    """Remove a directory tree, handling read-only files."""
    shutil.rmtree(target, onerror=_on_rm_error)


def find_pytest_cache_dirs(repo_root: Path) -> list[Path]:
    """Return sorted list of pytest-cache-files-* dirs at repo root."""
    matches: list[Path] = []
    try:
        for entry in repo_root.iterdir():
            if (
                entry.is_dir()
                and entry.name.startswith(PYTEST_CACHE_FILES_PREFIX)
            ):
                matches.append(entry)
    except OSError:
        pass
    matches.sort(key=lambda p: p.name)
    return matches


def run_cleanup(
    *,
    repo_root: Path,
    dry_run: bool = False,
) -> dict[str, object]:
    """Remove allowlisted temp dirs and return a deterministic summary."""
    removed: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    # Fixed-name dirs
    for name in ALLOWLISTED_DIRS:
        target = repo_root / name
        if not target.exists():
            skipped.append(name)
            continue
        if not target.is_dir():
            skipped.append(name)
            continue
        if dry_run:
            removed.append(name)
            continue
        try:
            _safe_rmtree(target)
            removed.append(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}".replace("\\", "/"))

    # pytest-cache-files-* dirs (repo root only)
    for target in find_pytest_cache_dirs(repo_root):
        rel = target.name
        if dry_run:
            removed.append(rel)
            continue
        try:
            _safe_rmtree(target)
            removed.append(rel)
        except OSError as exc:
            errors.append(f"{rel}: {exc}".replace("\\", "/"))

    return {
        "dry_run": dry_run,
        "removed": removed,
        "skipped": skipped,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Allowlist-only cleanup for repo-local temp directories.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root (default: auto-detected from script location).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed without deleting anything.",
    )
    args = parser.parse_args()

    result = run_cleanup(
        repo_root=Path(args.repo_root),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
