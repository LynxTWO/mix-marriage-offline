"""Sync repo-root data folders into src/mmo/data/ for wheel packaging.

Copies selected repo-root folders into src/mmo/data/, creating directories as
needed and deleting stale files that no longer exist in source.

Usage:
    python tools/sync_packaged_data_mirror.py
"""

from __future__ import annotations

import fnmatch
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PLUGIN_MANIFEST_ALLOWLIST: tuple[str, ...] = (
    "**/*.plugin.yaml",
    "**/*.plugin.yml",
    "**/plugin.yaml",
    "**/plugin.yml",
)


@dataclass(frozen=True)
class MirrorPair:
    src_rel: str
    dst_rel: str
    include_patterns: tuple[str, ...] | None = None
    include_prefixes: tuple[str, ...] | None = None


MIRROR_PAIRS: tuple[MirrorPair, ...] = (
    MirrorPair("schemas", "src/mmo/data/schemas"),
    MirrorPair("ontology", "src/mmo/data/ontology"),
    MirrorPair(
        "plugins",
        "src/mmo/data/plugins",
        include_patterns=PLUGIN_MANIFEST_ALLOWLIST,
        include_prefixes=("detectors/", "resolvers/", "renderers/"),
    ),
)
# Packaged plugin mirrors stay manifest-only on purpose. Shipping source modules
# here would create a second plugin authority root inside the wheel.

IGNORED_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
    "__pycache__",
    "Thumbs.db",
})


def _matches_include_patterns(
    rel_path: Path,
    include_patterns: tuple[str, ...] | None,
) -> bool:
    if include_patterns is None:
        return True

    rel_text = rel_path.as_posix()
    for pattern in include_patterns:
        normalized_pattern = pattern.replace("\\", "/")
        if fnmatch.fnmatch(rel_text, normalized_pattern):
            return True
        if normalized_pattern.startswith("**/") and fnmatch.fnmatch(
            rel_text,
            normalized_pattern[3:],
        ):
            return True
    return False


def _matches_include_prefixes(
    rel_path: Path,
    include_prefixes: tuple[str, ...] | None,
) -> bool:
    if include_prefixes is None:
        return True
    rel_text = rel_path.as_posix()
    return any(rel_text.startswith(prefix) for prefix in include_prefixes)


def _relative_files(
    root: Path,
    include_patterns: tuple[str, ...] | None = None,
    include_prefixes: tuple[str, ...] | None = None,
) -> set[Path]:
    """Return relative paths for all real files under *root*, ignoring junk."""
    result: set[Path] = set()
    if not root.is_dir():
        return result
    for item in root.rglob("*"):
        if any(part in IGNORED_NAMES for part in item.parts):
            continue
        if item.is_file():
            rel_path = item.relative_to(root)
            if _matches_include_patterns(rel_path, include_patterns):
                if _matches_include_prefixes(rel_path, include_prefixes):
                    result.add(rel_path)
    return result


def sync(*, dry_run: bool = False) -> dict[str, list[str]]:
    """Perform the sync. Returns a dict with 'copied' and 'deleted' lists."""
    copied: list[str] = []
    deleted: list[str] = []

    for pair in MIRROR_PAIRS:
        src_dir = REPO_ROOT / pair.src_rel
        dst_dir = REPO_ROOT / pair.dst_rel

        if not src_dir.is_dir():
            print(f"SKIP  source missing: {pair.src_rel}/", file=sys.stderr)
            continue

        src_files = _relative_files(
            src_dir,
            pair.include_patterns,
            pair.include_prefixes,
        )
        dst_files = _relative_files(
            dst_dir,
            pair.include_patterns,
            pair.include_prefixes,
        )
        disallowed_dst_files: set[Path] = set()
        if pair.include_prefixes is not None:
            dst_pattern_files = _relative_files(dst_dir, pair.include_patterns, None)
            disallowed_dst_files = {
                rel
                for rel in dst_pattern_files
                if not _matches_include_prefixes(rel, pair.include_prefixes)
            }

        # Delete stale files in mirror that are no longer in source.
        for stale in sorted((dst_files - src_files) | disallowed_dst_files):
            target = dst_dir / stale
            tag = f"DELETE {pair.dst_rel}/{stale}"
            if dry_run:
                print(f"  [dry-run] {tag}")
            else:
                target.unlink()
                # Remove empty parent dirs up to dst_dir.
                parent = target.parent
                while parent != dst_dir:
                    if not any(parent.iterdir()):
                        parent.rmdir()
                    else:
                        break
                    parent = parent.parent
            deleted.append(str(stale))

        # Copy new or changed files.
        for rel in sorted(src_files):
            src_file = src_dir / rel
            dst_file = dst_dir / rel
            # Skip byte-identical files so release packaging does not churn the
            # mirror and mask real packaged-data drift.
            if dst_file.exists() and dst_file.read_bytes() == src_file.read_bytes():
                continue
            tag = f"COPY  {pair.src_rel}/{rel} -> {pair.dst_rel}/{rel}"
            if dry_run:
                print(f"  [dry-run] {tag}")
            else:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(dst_file))
            copied.append(str(rel))

    return {"copied": copied, "deleted": deleted}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing."
    )
    args = parser.parse_args()

    result = sync(dry_run=args.dry_run)
    n_copied = len(result["copied"])
    n_deleted = len(result["deleted"])

    if n_copied == 0 and n_deleted == 0:
        print("Mirror is already up to date.")
    else:
        if n_copied:
            print(f"Copied {n_copied} file(s).")
        if n_deleted:
            print(f"Deleted {n_deleted} stale file(s).")


if __name__ == "__main__":
    main()
