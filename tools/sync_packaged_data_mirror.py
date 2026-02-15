"""Sync repo-root data folders into src/mmo/data/ for wheel packaging.

Copies schemas/, ontology/, and presets/ from the repo root into
src/mmo/data/{schemas,ontology,presets}, creating directories as needed
and deleting stale files that no longer exist in the source.

Usage:
    python tools/sync_packaged_data_mirror.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MIRROR_PAIRS: tuple[tuple[str, str], ...] = (
    ("schemas", "src/mmo/data/schemas"),
    ("ontology", "src/mmo/data/ontology"),
    ("presets", "src/mmo/data/presets"),
)

IGNORED_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
    "__pycache__",
    "Thumbs.db",
})


def _relative_files(root: Path) -> set[Path]:
    """Return relative paths for all real files under *root*, ignoring junk."""
    result: set[Path] = set()
    if not root.is_dir():
        return result
    for item in root.rglob("*"):
        if any(part in IGNORED_NAMES for part in item.parts):
            continue
        if item.is_file():
            result.add(item.relative_to(root))
    return result


def sync(*, dry_run: bool = False) -> dict[str, list[str]]:
    """Perform the sync.  Returns a dict with 'copied' and 'deleted' lists."""
    copied: list[str] = []
    deleted: list[str] = []

    for src_rel, dst_rel in MIRROR_PAIRS:
        src_dir = REPO_ROOT / src_rel
        dst_dir = REPO_ROOT / dst_rel

        if not src_dir.is_dir():
            print(f"SKIP  source missing: {src_rel}/", file=sys.stderr)
            continue

        src_files = _relative_files(src_dir)
        dst_files = _relative_files(dst_dir)

        # Delete stale files in mirror that are no longer in source.
        for stale in sorted(dst_files - src_files):
            target = dst_dir / stale
            tag = f"DELETE {dst_rel}/{stale}"
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
            # Quick content compare to avoid unnecessary writes.
            if dst_file.exists() and dst_file.read_bytes() == src_file.read_bytes():
                continue
            tag = f"COPY  {src_rel}/{rel} -> {dst_rel}/{rel}"
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
