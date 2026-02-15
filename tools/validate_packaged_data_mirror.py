"""Validate that src/mmo/data/ mirrors repo-root schemas/ontology/presets.

Compares file presence and SHA-256 content hashes between the repo-root
canonical folders and the packaged mirror under src/mmo/data/.

Outputs JSON on stdout:
    {
        "ok": true/false,
        "missing": [...],     # in source but not mirror
        "extra": [...],       # in mirror but not source
        "mismatched": [...],  # present in both but content differs
        "checked_count": N
    }

Exit code 0 when ok, 1 when drift is detected.

Usage:
    python tools/validate_packaged_data_mirror.py
"""

from __future__ import annotations

import hashlib
import json
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


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


def validate() -> dict:
    missing: list[str] = []
    extra: list[str] = []
    mismatched: list[str] = []
    checked = 0

    for src_rel, dst_rel in MIRROR_PAIRS:
        src_dir = REPO_ROOT / src_rel
        dst_dir = REPO_ROOT / dst_rel

        src_files = _relative_files(src_dir)
        dst_files = _relative_files(dst_dir)

        # Files in source but not in mirror.
        for rel in sorted(src_files - dst_files):
            missing.append(f"{src_rel}/{rel}")

        # Files in mirror but not in source.
        for rel in sorted(dst_files - src_files):
            extra.append(f"{dst_rel}/{rel}")

        # Files in both — compare hashes.
        for rel in sorted(src_files & dst_files):
            checked += 1
            src_hash = _sha256(src_dir / rel)
            dst_hash = _sha256(dst_dir / rel)
            if src_hash != dst_hash:
                mismatched.append(f"{src_rel}/{rel}")

    ok = len(missing) == 0 and len(extra) == 0 and len(mismatched) == 0
    return {
        "ok": ok,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "checked_count": checked,
    }


def main() -> None:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        parts: list[str] = []
        if result["missing"]:
            parts.append(f"{len(result['missing'])} missing in mirror")
        if result["extra"]:
            parts.append(f"{len(result['extra'])} extra in mirror")
        if result["mismatched"]:
            parts.append(f"{len(result['mismatched'])} content mismatches")
        print(
            f"FAIL: packaged-data mirror drift detected: {'; '.join(parts)}. "
            "Run: python tools/sync_packaged_data_mirror.py",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
