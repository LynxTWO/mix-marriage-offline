from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.sax.saxutils import escape

from mmo import __version__ as _MMO_VERSION
from mmo.core.downmix import MATRIX_VERSION
from mmo.core.media_tags import (
    RawTag,
    TagBag,
    canonicalize_tag_bag,
    merge_tag_bags,
    tag_bag_from_mapping,
    tag_bag_to_mapping,
)
from mmo.core.render_contract import RENDER_CONTRACT_SCHEMA_VERSION
from mmo.core.scene_builder import build_scene_from_session
from mmo.resources import ontology_dir

_TRACE_FIELD_ORDER: tuple[str, ...] = (
    "mmo_version",
    "scene_sha256",
    "render_contract_version",
    "downmix_policy_version",
    "layout_id",
    "profile_id",
    "export_profile_id",
    "seed",
)
_LAYOUT_UNKNOWN = "LAYOUT.UNKNOWN"
_PROFILE_UNKNOWN = "PROFILE.UNKNOWN"


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _first_nonempty_string(*values: Any) -> str:
    for value in values:
        text = _coerce_str(value).strip()
        if text:
            return text
    return ""


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Keys whose values are filesystem refs where only the basename is meaningful for hashing.
_SCENE_HASH_BASENAME_KEYS: frozenset[str] = frozenset(
    {"bus_plan_ref", "stems_map_ref", "stems_index_ref"}
)
# Placeholder used in place of absolute stems_dir values so the hash is runner-agnostic.
_STEMS_DIR_HASH_TOKEN = "<stems_dir>"


def _canonicalize_scene_for_hash(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: _canonicalize_scene_for_hash(child, parent_key=key)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _canonicalize_scene_for_hash(child, parent_key=parent_key)
            for child in value
        ]
    if isinstance(value, str):
        if parent_key in _SCENE_HASH_BASENAME_KEYS:
            # Normalize OS separators then extract basename so Windows and POSIX
            # paths with the same logical filename hash identically.
            return PurePosixPath(value.replace("\\", "/")).name
        if parent_key == "stems_dir":
            # Absolute stems_dir is runner-specific; replace with stable token.
            return _STEMS_DIR_HASH_TOKEN
        if parent_key == "file_path":
            # Normalize OS path separators; reduce absolute paths to basename.
            normalized = value.replace("\\", "/")
            # Detect absolute: POSIX (/...) or Windows drive (C:/...)
            is_absolute = normalized.startswith("/") or (
                len(normalized) >= 2 and normalized[1] == ":"
            )
            if is_absolute:
                return PurePosixPath(normalized).name
            return normalized
    return value


@lru_cache(maxsize=1)
def _downmix_registry_snapshot() -> tuple[str, dict[str, str]]:
    registry_path = ontology_dir() / "policies" / "downmix.yaml"
    try:
        import yaml
    except ImportError:
        return MATRIX_VERSION, {}

    try:
        registry_payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except OSError:
        return MATRIX_VERSION, {}
    if not isinstance(registry_payload, dict):
        return MATRIX_VERSION, {}

    downmix = registry_payload.get("downmix")
    if not isinstance(downmix, dict):
        return MATRIX_VERSION, {}

    meta = downmix.get("_meta")
    registry_version = (
        _coerce_str(meta.get("downmix_registry_version")).strip()
        if isinstance(meta, dict)
        else ""
    ) or MATRIX_VERSION

    policies = downmix.get("policies")
    if not isinstance(policies, dict):
        return registry_version, {}

    versions: dict[str, str] = {}
    for policy_id in sorted(policies.keys()):
        raw_policy = policies.get(policy_id)
        if not isinstance(raw_policy, dict):
            continue
        file_name = _coerce_str(raw_policy.get("file")).strip()
        if not file_name:
            continue
        pack_path = registry_path.parent / file_name
        try:
            pack_payload = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not isinstance(pack_payload, dict):
            continue
        pack = pack_payload.get("downmix_policy_pack")
        if not isinstance(pack, dict):
            continue
        pack_version = _coerce_str(pack.get("pack_version")).strip()
        if pack_version:
            versions[_coerce_str(policy_id).strip()] = pack_version
    return registry_version, versions


def _downmix_policy_version(policy_id: str) -> str:
    registry_version, versions = _downmix_registry_snapshot()
    normalized = policy_id.strip()
    if normalized:
        return versions.get(normalized, registry_version)
    return registry_version


def _candidate_scene_payload(job: Mapping[str, Any]) -> dict[str, Any] | None:
    direct_candidates = (
        job.get("scene_payload"),
        job.get("scene"),
        job.get("render_scene"),
    )
    for candidate in direct_candidates:
        if isinstance(candidate, dict):
            return candidate

    for container_key in ("session", "request_payload", "plan_payload", "report"):
        container = job.get(container_key)
        if not isinstance(container, Mapping):
            continue
        nested = _candidate_scene_payload(container)
        if nested is not None:
            return nested

    if "stems_dir" in job and "stems" in job:
        try:
            scene = build_scene_from_session(dict(job))
        except (KeyError, TypeError, ValueError):
            return None
        if isinstance(scene, dict):
            return scene
    return None


def _scene_sha256(job: Mapping[str, Any]) -> str:
    explicit = _first_nonempty_string(
        job.get("scene_sha256"),
        _coerce_dict(job.get("trace_metadata")).get("scene_sha256"),
    )
    if explicit:
        return explicit

    scene_payload = _candidate_scene_payload(job)
    if isinstance(scene_payload, dict):
        return _canonical_sha256(_canonicalize_scene_for_hash(scene_payload))

    fallback_payload = {}
    for key in ("scene_id", "stems_dir", "stems", "target_layout_id", "profile_id"):
        if key in job:
            fallback_payload[key] = job.get(key)
    if fallback_payload:
        return _canonical_sha256(fallback_payload)
    return _canonical_sha256({})


def _profile_id(job: Mapping[str, Any]) -> str:
    session = _coerce_dict(job.get("session"))
    scene_payload = _candidate_scene_payload(job)
    scene_metadata = _coerce_dict(scene_payload.get("metadata")) if isinstance(scene_payload, dict) else {}
    run_config = _coerce_dict(job.get("run_config")) or _coerce_dict(session.get("run_config"))
    options = _coerce_dict(job.get("options")) or _coerce_dict(session.get("options"))
    return (
        _first_nonempty_string(
            job.get("profile_id"),
            session.get("profile_id"),
            scene_metadata.get("profile_id"),
            run_config.get("profile_id"),
            options.get("profile_id"),
        )
        or _PROFILE_UNKNOWN
    )


def _export_profile_id(job: Mapping[str, Any], *, profile_id: str) -> str:
    session = _coerce_dict(job.get("session"))
    export_options = _coerce_dict(job.get("render_export_options")) or _coerce_dict(
        session.get("render_export_options")
    )
    run_config = _coerce_dict(job.get("run_config")) or _coerce_dict(session.get("run_config"))
    return (
        _first_nonempty_string(
            job.get("export_profile_id"),
            session.get("export_profile_id"),
            export_options.get("export_profile_id"),
            run_config.get("export_profile_id"),
        )
        or profile_id
    )


def _layout_id(job: Mapping[str, Any]) -> str:
    session = _coerce_dict(job.get("session"))
    resolved = _coerce_dict(job.get("resolved"))
    metadata = _coerce_dict(job.get("metadata"))
    return (
        _first_nonempty_string(
            job.get("layout_id"),
            job.get("target_layout_id"),
            session.get("layout_id"),
            session.get("target_layout_id"),
            resolved.get("target_layout_id"),
            metadata.get("layout_id"),
        )
        or _LAYOUT_UNKNOWN
    )


def _seed(job: Mapping[str, Any]) -> str:
    session = _coerce_dict(job.get("session"))
    options = _coerce_dict(job.get("options")) or _coerce_dict(session.get("options"))
    for candidate in (
        job.get("seed"),
        job.get("render_seed"),
        session.get("seed"),
        session.get("render_seed"),
        options.get("render_seed"),
    ):
        resolved = _coerce_int(candidate)
        if resolved is not None:
            return str(resolved)
    return "0"


def _render_contract_version(job: Mapping[str, Any]) -> str:
    render_contract = _coerce_dict(job.get("render_contract"))
    return (
        _first_nonempty_string(
            job.get("render_contract_version"),
            render_contract.get("schema_version"),
        )
        or RENDER_CONTRACT_SCHEMA_VERSION
    )


def _downmix_policy_id(job: Mapping[str, Any]) -> str:
    session = _coerce_dict(job.get("session"))
    policies = _coerce_dict(job.get("policies")) or _coerce_dict(session.get("policies"))
    options = _coerce_dict(job.get("options")) or _coerce_dict(session.get("options"))
    resolved = _coerce_dict(job.get("resolved")) or _coerce_dict(session.get("resolved"))
    return _first_nonempty_string(
        job.get("downmix_policy_id"),
        session.get("downmix_policy_id"),
        policies.get("downmix_policy_id"),
        options.get("downmix_policy_id"),
        resolved.get("downmix_policy_id"),
    )


def _git_commit(job: Mapping[str, Any]) -> str:
    session = _coerce_dict(job.get("session"))
    return _first_nonempty_string(
        job.get("git_commit"),
        job.get("build_git_commit"),
        session.get("git_commit"),
        session.get("build_git_commit"),
        os.environ.get("MMO_GIT_COMMIT"),
    )


def build_trace_metadata(job: Mapping[str, Any]) -> dict[str, str]:
    profile_id = _profile_id(job)
    payload: dict[str, str] = {
        "mmo_version": _MMO_VERSION,
        "scene_sha256": _scene_sha256(job),
        "render_contract_version": _render_contract_version(job),
        "downmix_policy_version": _downmix_policy_version(_downmix_policy_id(job)),
        "layout_id": _layout_id(job),
        "profile_id": profile_id,
        "export_profile_id": _export_profile_id(job, profile_id=profile_id),
        "seed": _seed(job),
    }
    git_commit = _git_commit(job)
    if git_commit:
        payload["git_commit"] = git_commit
    return payload


def trace_tag_bag_from_metadata(metadata: Mapping[str, str]) -> TagBag:
    raw_tags: list[RawTag] = []
    for index, key in enumerate((*_TRACE_FIELD_ORDER, "git_commit")):
        value = _coerce_str(metadata.get(key)).strip()
        if not value:
            continue
        raw_tags.append(
            RawTag(
                source="format",
                container="trace",
                scope="mmo_trace",
                key=key,
                value=value,
                index=index,
            )
        )
    return canonicalize_tag_bag(raw_tags)


def build_trace_tag_bag(job: Mapping[str, Any]) -> TagBag:
    return trace_tag_bag_from_metadata(build_trace_metadata(job))


def merge_trace_tag_bag(
    metadata: Mapping[str, Any] | None,
    trace_tag_bag: TagBag,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    existing = tag_bag_from_mapping(payload.get("tag_bag"))
    payload["tag_bag"] = tag_bag_to_mapping(merge_tag_bags((existing, trace_tag_bag)))
    return payload


def add_trace_metadata(
    metadata: Mapping[str, Any] | None,
    job: Mapping[str, Any],
) -> dict[str, Any]:
    trace_metadata = build_trace_metadata(job)
    merged = merge_trace_tag_bag(metadata, trace_tag_bag_from_metadata(trace_metadata))
    merged["trace_metadata"] = trace_metadata
    return merged


def build_trace_ixml_payload(metadata: Mapping[str, str]) -> str:
    rows = ['<?xml version="1.0" encoding="UTF-8"?>', "<BWFXML><MMO_TRACE>"]
    for key in (*_TRACE_FIELD_ORDER, "git_commit"):
        value = _coerce_str(metadata.get(key)).strip()
        if not value:
            continue
        xml_key = key.upper()
        rows.append(f"<{xml_key}>{escape(value)}</{xml_key}>")
    rows.append("</MMO_TRACE></BWFXML>")
    return "".join(rows)
