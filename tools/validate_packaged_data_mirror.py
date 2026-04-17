"""Validate that src/mmo/data/ mirrors selected repo-root source folders.

Compares file presence and SHA-256 content hashes between canonical source
folders and the packaged mirror under src/mmo/data/.

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

import fnmatch
import hashlib
import json
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
# Validation matches the sync allowlist exactly. Drift between the two would
# make release checks disagree with the mirror tool that fixes them.

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


def validate() -> dict[str, object]:
    missing: list[str] = []
    extra: list[str] = []
    mismatched: list[str] = []
    checked = 0

    for pair in MIRROR_PAIRS:
        src_dir = REPO_ROOT / pair.src_rel
        dst_dir = REPO_ROOT / pair.dst_rel

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

        # Files in source but not in mirror.
        for rel in sorted(src_files - dst_files):
            missing.append(f"{pair.src_rel}/{rel}")

        # Files in mirror but not in source.
        for rel in sorted(dst_files - src_files):
            extra.append(f"{pair.dst_rel}/{rel}")
        for rel in sorted(disallowed_dst_files):
            extra.append(f"{pair.dst_rel}/{rel}")

        # Files in both compare hashes.
        for rel in sorted(src_files & dst_files):
            checked += 1
            src_hash = _sha256(src_dir / rel)
            dst_hash = _sha256(dst_dir / rel)
            if src_hash != dst_hash:
                # Hash mismatches are release blockers because packaged data has
                # drifted even though both files exist.
                mismatched.append(f"{pair.src_rel}/{rel}")

    ok = len(missing) == 0 and len(extra) == 0 and len(mismatched) == 0
    return {
        "ok": ok,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "checked_count": checked,
        "mirror_pairs": [
            {
                "source": pair.src_rel,
                "mirror": pair.dst_rel,
                "include_patterns": (
                    list(pair.include_patterns)
                    if pair.include_patterns is not None
                    else []
                ),
            }
            for pair in MIRROR_PAIRS
        ],
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
