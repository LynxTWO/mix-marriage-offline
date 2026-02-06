from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

LOCKFILE_SCHEMA_VERSION = "0.1.0"
_IGNORED_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db", "Desktop.ini"})
_HASH_CHUNK_SIZE = 1024 * 1024


def _resolve_root_dir(root_dir: Path) -> Path:
    resolved = root_dir.resolve()
    if not resolved.exists():
        raise ValueError(f"Root directory does not exist: {root_dir}")
    if not resolved.is_dir():
        raise ValueError(f"Root directory is not a directory: {root_dir}")
    return resolved


def _rel_posix(root_dir: Path, file_path: Path) -> str:
    return file_path.relative_to(root_dir).as_posix()


def _is_ignored_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if ".git" in parts:
        return True
    return parts[-1] in _IGNORED_FILE_NAMES


def _iter_candidate_files(
    root_dir: Path,
    *,
    exclude_rel_paths: set[str] | None = None,
) -> list[Path]:
    excluded = set(exclude_rel_paths or set())
    files: list[Path] = []
    for path in root_dir.rglob("*"):
        if not path.is_file():
            continue
        rel_path = _rel_posix(root_dir, path)
        if rel_path in excluded:
            continue
        if _is_ignored_path(rel_path):
            continue
        files.append(path)
    files.sort(key=lambda item: _rel_posix(root_dir, item))
    return files


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_lockfile(
    root_dir: Path,
    *,
    exclude_rel_paths: set[str] | None = None,
) -> dict[str, Any]:
    resolved_root = _resolve_root_dir(root_dir)
    files_payload: list[dict[str, Any]] = []

    for file_path in _iter_candidate_files(
        resolved_root,
        exclude_rel_paths=exclude_rel_paths,
    ):
        rel_path = _rel_posix(resolved_root, file_path)
        files_payload.append(
            {
                "rel_path": rel_path,
                "size_bytes": file_path.stat().st_size,
                "sha256": _sha256_file(file_path),
            }
        )

    return {
        "schema_version": LOCKFILE_SCHEMA_VERSION,
        "root_dir": resolved_root.as_posix(),
        "files": files_payload,
    }


def _expected_sha_by_rel_path(lock: dict[str, Any]) -> dict[str, str]:
    raw_files = lock.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("Lockfile must contain a files array.")

    expected: dict[str, str] = {}
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ValueError(f"Lockfile files[{index}] must be an object.")
        rel_path = item.get("rel_path")
        sha256 = item.get("sha256")
        if not isinstance(rel_path, str) or not rel_path:
            raise ValueError(f"Lockfile files[{index}].rel_path must be a non-empty string.")
        if not isinstance(sha256, str) or not sha256:
            raise ValueError(f"Lockfile files[{index}].sha256 must be a non-empty string.")
        if rel_path in expected:
            raise ValueError(f"Lockfile contains duplicate rel_path: {rel_path}")
        expected[rel_path] = sha256
    return expected


def verify_lockfile(
    root_dir: Path,
    lock: dict[str, Any],
    *,
    exclude_rel_paths: set[str] | None = None,
) -> dict[str, Any]:
    excluded = set(exclude_rel_paths or set())
    expected_raw = _expected_sha_by_rel_path(lock)
    expected = {
        rel_path: sha256
        for rel_path, sha256 in expected_raw.items()
        if rel_path not in excluded
    }
    current_lock = build_lockfile(root_dir, exclude_rel_paths=excluded)
    current_files = current_lock.get("files", [])
    current: dict[str, str] = {}
    for item in current_files:
        if not isinstance(item, dict):
            continue
        rel_path = item.get("rel_path")
        sha256 = item.get("sha256")
        if isinstance(rel_path, str) and isinstance(sha256, str):
            current[rel_path] = sha256

    missing = sorted(rel for rel in expected if rel not in current)
    extra = sorted(rel for rel in current if rel not in expected)

    changed: list[dict[str, str]] = []
    for rel in sorted(rel for rel in expected if rel in current):
        expected_sha = expected[rel]
        actual_sha = current[rel]
        if expected_sha != actual_sha:
            changed.append(
                {
                    "rel": rel,
                    "expected_sha": expected_sha,
                    "actual_sha": actual_sha,
                }
            )

    ok = not missing and not extra and not changed
    return {
        "ok": ok,
        "missing": missing,
        "extra": extra,
        "changed": changed,
    }
