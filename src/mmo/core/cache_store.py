from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.core.cache_keys import cache_key, hash_lockfile, hash_run_config
from mmo.resources import default_cache_dir

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None


def resolve_cache_dir(cache_dir: Path | str | None) -> Path:
    if cache_dir is None:
        return default_cache_dir()
    return Path(cache_dir).expanduser().resolve()


def _cache_identity(lock: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, str, str]:
    lock_hash = hash_lockfile(lock)
    cfg_hash = hash_run_config(cfg)
    return lock_hash, cfg_hash, cache_key(lock_hash, cfg_hash)


def cache_paths(
    cache_dir: Path | str | None,
    lock: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[Path, Path]:
    cache_root = resolve_cache_dir(cache_dir)
    _, _, key = _cache_identity(lock, cfg)
    report_path = cache_root / "reports" / f"{key}.report.json"
    metadata_path = cache_root / "metadata" / f"{key}.meta.json"
    return report_path, metadata_path


def try_load_cached_report(
    cache_dir: Path | str | None,
    lock: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    report_path, _ = cache_paths(cache_dir, lock, cfg)
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_cached_report(
    cache_dir: Path | str | None,
    lock: dict[str, Any],
    cfg: dict[str, Any],
    report: dict[str, Any],
) -> None:
    if not isinstance(report, dict):
        raise ValueError("report must be an object.")

    lock_hash, cfg_hash, key = _cache_identity(lock, cfg)
    report_path, metadata_path = cache_paths(cache_dir, lock, cfg)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    metadata_payload = {
        "cache_key": key,
        "lock_hash": lock_hash,
        "run_config_hash": cfg_hash,
    }
    metadata_path.write_text(
        json.dumps(metadata_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def report_schema_is_valid(report: dict[str, Any], schema_path: Path) -> bool:
    if not isinstance(report, dict):
        return False
    if jsonschema is None:
        return False
    try:
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
    except ImportError:  # pragma: no cover - environment issue
        return False

    try:
        root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(root_schema, dict):
        return False

    registry = Registry()
    for schema_file in sorted(schema_path.parent.glob("*.schema.json")):
        try:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(schema, dict):
            return False
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)

    validator = jsonschema.Draft202012Validator(root_schema, registry=registry)
    return next(validator.iter_errors(report), None) is None


def rewrite_report_stems_dir(report: dict[str, Any], stems_dir: Path) -> dict[str, Any]:
    rewritten = json.loads(json.dumps(report))
    session = rewritten.get("session")
    if isinstance(session, dict):
        session["stems_dir"] = stems_dir.resolve().as_posix()
    return rewritten


def report_has_time_cap_stop_condition(report: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False

    for flag in ("time_cap_stop", "max_seconds_reached", "stopped_early"):
        if report.get(flag) is True:
            return True

    downmix_qa = report.get("downmix_qa")
    if not isinstance(downmix_qa, dict):
        return False

    log_payload_raw = downmix_qa.get("log")
    if not isinstance(log_payload_raw, str) or not log_payload_raw:
        return False
    try:
        log_payload = json.loads(log_payload_raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(log_payload, dict):
        return False

    seconds_available = log_payload.get("seconds_available")
    seconds_compared = log_payload.get("seconds_compared")
    max_seconds = log_payload.get("max_seconds")
    if not isinstance(seconds_available, (int, float)):
        return False
    if not isinstance(seconds_compared, (int, float)):
        return False
    if not isinstance(max_seconds, (int, float)):
        return False
    if max_seconds <= 0:
        return False
    return float(seconds_compared) < float(seconds_available)
