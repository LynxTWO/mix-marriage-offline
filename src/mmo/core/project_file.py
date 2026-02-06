from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mmo.core.run_config import normalize_run_config

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


PROJECT_SCHEMA_VERSION = "0.1.0"
_PROJECT_ID_CLEAN_RE = re.compile(r"[^A-Za-z0-9]+")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _project_schema_path() -> Path:
    return _repo_root() / "schemas" / "project.schema.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _build_schema_registry(schemas_dir: Path) -> Any:
    try:
        from referencing import Registry, Resource  # noqa: WPS433
        from referencing.jsonschema import DRAFT202012  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "jsonschema referencing support is unavailable; cannot validate project files."
        ) from exc

    registry = Registry()
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        schema = _load_json_schema(schema_file)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema_file.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _validate_project_payload(payload: dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate project files.")

    schema_path = _project_schema_path()
    schema = _load_json_schema(schema_path)
    registry = _build_schema_registry(schema_path.parent)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.path) or "$"
        lines.append(f"- {path}: {error.message}")
    raise ValueError("Project schema validation failed:\n" + "\n".join(lines))


def _normalize_project_id(stems_dir: Path) -> str:
    stem_name = stems_dir.resolve().name.strip() or "PROJECT"
    cleaned = _PROJECT_ID_CLEAN_RE.sub("_", stem_name).strip("_").upper()
    if not cleaned:
        cleaned = "PROJECT"
    return f"PROJECT.{cleaned}"


def _normalize_last_run(last_run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(last_run, dict):
        raise ValueError("last_run must be an object.")

    normalized: dict[str, Any] = {}
    mode = last_run.get("mode")
    out_dir = last_run.get("out_dir")
    if isinstance(mode, str):
        normalized["mode"] = mode
    if isinstance(out_dir, str):
        normalized["out_dir"] = out_dir

    for key in (
        "deliverables_index_path",
        "listen_pack_path",
        "variant_plan_path",
        "variant_result_path",
    ):
        value = last_run.get(key)
        if isinstance(value, str):
            normalized[key] = value
    return normalized


def _normalized_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(project, dict):
        raise ValueError("Project payload must be an object.")

    normalized = dict(project)
    if "last_run" in normalized:
        normalized["last_run"] = _normalize_last_run(normalized["last_run"])

    run_config_defaults = normalized.get("run_config_defaults")
    if isinstance(run_config_defaults, dict):
        normalized["run_config_defaults"] = normalize_run_config(run_config_defaults)
    return normalized


def new_project(stems_dir: Path, *, notes: str | None) -> dict[str, Any]:
    resolved_stems_dir = stems_dir.resolve()
    now = _utc_now_iso()
    project: dict[str, Any] = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project_id": _normalize_project_id(resolved_stems_dir),
        "created_at_utc": now,
        "updated_at_utc": now,
        "stems_dir": resolved_stems_dir.as_posix(),
    }
    if notes is not None:
        project["notes"] = notes

    normalized = _normalized_project_payload(project)
    _validate_project_payload(normalized)
    return normalized


def update_project_last_run(project: dict[str, Any], last_run: dict[str, Any]) -> dict[str, Any]:
    updated = _normalized_project_payload(dict(project))
    updated["last_run"] = _normalize_last_run(last_run)
    updated["updated_at_utc"] = _utc_now_iso()
    _validate_project_payload(updated)
    return updated


def write_project(path: Path, project: dict[str, Any]) -> None:
    normalized = _normalized_project_payload(project)
    _validate_project_payload(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_project(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path, label="Project")
    normalized = _normalized_project_payload(payload)
    _validate_project_payload(normalized)
    return normalized
