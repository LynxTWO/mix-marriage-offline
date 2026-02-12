from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config
from mmo.dsp.io import sha256_file


def _hash_json_payload(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def hash_lockfile(lock: dict[str, Any]) -> str:
    if not isinstance(lock, dict):
        raise ValueError("lock must be an object.")

    raw_files = lock.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("lock.files must be an array.")

    canonical_files: list[dict[str, str]] = []
    seen_rel_paths: set[str] = set()
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ValueError(f"lock.files[{index}] must be an object.")
        rel_path = item.get("rel_path")
        sha256 = item.get("sha256")
        if not isinstance(rel_path, str) or not rel_path:
            raise ValueError(f"lock.files[{index}].rel_path must be a non-empty string.")
        if not isinstance(sha256, str) or not sha256:
            raise ValueError(f"lock.files[{index}].sha256 must be a non-empty string.")
        if rel_path in seen_rel_paths:
            raise ValueError(f"lock.files contains duplicate rel_path: {rel_path}")
        seen_rel_paths.add(rel_path)
        canonical_files.append({"rel_path": rel_path, "sha256": sha256})

    canonical_files.sort(key=lambda item: item["rel_path"])
    return _hash_json_payload({"files": canonical_files})


def hash_run_config(cfg: dict[str, Any]) -> str:
    if not isinstance(cfg, dict):
        raise ValueError("cfg must be an object.")
    normalized = normalize_run_config(
        {
            **cfg,
            "schema_version": cfg.get("schema_version", RUN_CONFIG_SCHEMA_VERSION),
        }
    )
    return _hash_json_payload(normalized)


def cache_key(lock_hash: str, cfg_hash: str) -> str:
    if not isinstance(lock_hash, str) or not lock_hash:
        raise ValueError("lock_hash must be a non-empty string.")
    if not isinstance(cfg_hash, str) or not cfg_hash:
        raise ValueError("cfg_hash must be a non-empty string.")
    return f"LOCK.{lock_hash[:8]}__CFG.{cfg_hash[:8]}"


def _normalize_profile_ids_for_cache(profile_ids: list[str]) -> list[str]:
    if not isinstance(profile_ids, list):
        raise ValueError("profile_ids must be a list of profile identifiers.")

    normalized: set[str] = set()
    for profile_id in profile_ids:
        if not isinstance(profile_id, str):
            continue
        token = profile_id.strip()
        if token:
            normalized.add(token)
    if not normalized:
        raise ValueError("At least one translation profile_id is required.")
    return sorted(normalized)


def translation_cache_key(
    audio_path: Path,
    profile_ids: list[str],
    version_str: str,
) -> str:
    if not isinstance(audio_path, Path):
        raise ValueError("audio_path must be a pathlib.Path.")
    if not audio_path.exists():
        raise ValueError(f"Audio path does not exist: {audio_path}")
    if not audio_path.is_file():
        raise ValueError(f"Audio path must be a file: {audio_path}")
    if not isinstance(version_str, str) or not version_str.strip():
        raise ValueError("version_str must be a non-empty string.")

    payload = {
        "audio_sha256": sha256_file(audio_path),
        "profile_ids": _normalize_profile_ids_for_cache(profile_ids),
        "version": version_str.strip(),
    }
    return _hash_json_payload(payload)
