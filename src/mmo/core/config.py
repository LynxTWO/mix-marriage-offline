from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mmo.core.presets import load_preset_run_config
from mmo.core.run_config import load_run_config, merge_run_config, normalize_run_config
from mmo.resources import ontology_dir, presets_dir as _presets_dir, schemas_dir

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


PROJECT_SESSION_SCHEMA_VERSION = "0.1.0"
DEFAULT_PROJECT_SESSION_FILENAME = "project_session.json"

_PROJECT_SESSION_KEYS = {"schema_version", "scene", "history", "receipts"}
_PROJECT_SESSION_RECEIPT_KEYS = {"path", "payload"}

_PROJECT_SCENE_REL_PATH = Path("drafts/scene.draft.json")
_PROJECT_HISTORY_REL_PATH = Path("renders/event_log.jsonl")
_PROJECT_DEFAULT_RECEIPT_PATHS: tuple[Path, ...] = (
    Path("safe_render.dry_receipt.json"),
    Path("safe_render.receipt.json"),
    Path("renders/render_execute.json"),
    Path("renders/render_preflight.json"),
    Path("renders/render_qa.json"),
)

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:/")


def resolved_presets_dir() -> Path:
    """Resolve the canonical presets directory for config loading."""
    ontology_presets_dir = ontology_dir() / "presets"
    if (ontology_presets_dir / "index.json").is_file():
        return ontology_presets_dir
    return _presets_dir()


def load_effective_run_config(
    config_path: Path | None,
    cli_overrides: dict[str, Any],
    *,
    preset_id: str | None = None,
    presets_dir: Path | None = None,
) -> dict[str, Any]:
    """Load and merge preset + config file + CLI overrides deterministically."""
    if not isinstance(cli_overrides, dict):
        raise ValueError("cli_overrides must be an object.")

    merged_cfg: dict[str, Any] = {}
    normalized_preset_id = preset_id.strip() if isinstance(preset_id, str) else ""
    if normalized_preset_id:
        preset_root = presets_dir if presets_dir is not None else resolved_presets_dir()
        preset_cfg = load_preset_run_config(preset_root, normalized_preset_id)
        merged_cfg = merge_run_config(merged_cfg, preset_cfg)

    if config_path is not None:
        merged_cfg = merge_run_config(merged_cfg, load_run_config(config_path))

    merged_cfg = merge_run_config(merged_cfg, cli_overrides)

    if normalized_preset_id:
        merged_cfg["preset_id"] = normalized_preset_id
        return normalize_run_config(merged_cfg)
    return merged_cfg


def _project_session_schema_path() -> Path:
    return schemas_dir() / "project_session.schema.json"


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


def _validate_relative_posix_path(path_text: Any, *, field_name: str) -> str:
    if not isinstance(path_text, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = path_text.replace("\\", "/").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if normalized.startswith("/") or _WINDOWS_ABS_PATH_RE.match(normalized):
        raise ValueError(f"{field_name} must be a project-relative path.")

    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts:
        raise ValueError(f"{field_name} must be a project-relative path.")
    if any(part == ".." for part in parts):
        raise ValueError(f"{field_name} must not escape the project directory.")
    return "/".join(parts)


def _validate_project_session_schema(payload: dict[str, Any]) -> None:
    if jsonschema is None:
        return

    schema = _load_json_object(_project_session_schema_path(), label="Project session schema")
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    raise ValueError("Project session schema validation failed:\n" + "\n".join(lines))


def normalize_project_session(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Project session payload must be an object.")

    unknown = sorted(set(payload.keys()) - _PROJECT_SESSION_KEYS)
    if unknown:
        raise ValueError(f"Unknown project session field(s): {', '.join(unknown)}")

    schema_version = payload.get("schema_version")
    if schema_version != PROJECT_SESSION_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported project session schema_version: "
            f"{schema_version!r} (expected {PROJECT_SESSION_SCHEMA_VERSION!r})."
        )

    scene = payload.get("scene")
    if not isinstance(scene, dict):
        raise ValueError("Project session field 'scene' must be an object.")

    raw_history = payload.get("history")
    if not isinstance(raw_history, list):
        raise ValueError("Project session field 'history' must be an array.")
    history: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_history):
        if not isinstance(entry, dict):
            raise ValueError(f"Project session history[{index}] must be an object.")
        history.append(dict(entry))

    raw_receipts = payload.get("receipts")
    if not isinstance(raw_receipts, list):
        raise ValueError("Project session field 'receipts' must be an array.")

    receipts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(raw_receipts):
        if not isinstance(entry, dict):
            raise ValueError(f"Project session receipts[{index}] must be an object.")
        unknown_receipt_keys = sorted(set(entry.keys()) - _PROJECT_SESSION_RECEIPT_KEYS)
        if unknown_receipt_keys:
            raise ValueError(
                "Project session receipt has unknown field(s): "
                f"{', '.join(unknown_receipt_keys)}"
            )

        path_text = _validate_relative_posix_path(
            entry.get("path"),
            field_name=f"receipts[{index}].path",
        )
        if path_text in seen_paths:
            raise ValueError(f"Project session receipts contains duplicate path: {path_text}")

        receipt_payload = entry.get("payload")
        if not isinstance(receipt_payload, dict):
            raise ValueError(f"Project session receipts[{index}].payload must be an object.")

        seen_paths.add(path_text)
        receipts.append({"path": path_text, "payload": dict(receipt_payload)})

    receipts.sort(key=lambda item: item["path"])
    normalized = {
        "schema_version": PROJECT_SESSION_SCHEMA_VERSION,
        "scene": dict(scene),
        "history": history,
        "receipts": receipts,
    }
    _validate_project_session_schema(normalized)
    return normalized


def _read_history_jsonl(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.is_file():
        return []
    try:
        text = history_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read project history from {history_path}: {exc}") from exc

    entries: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Project history JSONL is not valid JSON at line {line_number}: {history_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"Project history JSONL line {line_number} must be an object: {history_path}"
            )
        entries.append(payload)
    return entries


def _write_history_jsonl(path: Path, history: list[dict[str, Any]]) -> None:
    lines = [json.dumps(entry, sort_keys=True) for entry in history]
    text = "\n".join(lines)
    if lines:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def default_project_session_path(project_dir: Path) -> Path:
    return (project_dir / DEFAULT_PROJECT_SESSION_FILENAME).resolve()


def build_project_session_payload(project_dir: Path) -> dict[str, Any]:
    resolved_project_dir = project_dir.resolve()
    scene_path = resolved_project_dir / _PROJECT_SCENE_REL_PATH
    if not scene_path.is_file():
        raise ValueError(
            "Project scene file is missing: "
            f"{scene_path.as_posix()} (run `mmo project init` first)."
        )

    scene_payload = _load_json_object(scene_path, label="Project scene")
    history_payload = _read_history_jsonl(resolved_project_dir / _PROJECT_HISTORY_REL_PATH)

    receipts: list[dict[str, Any]] = []
    for rel_path in sorted(path.as_posix() for path in _PROJECT_DEFAULT_RECEIPT_PATHS):
        full_path = resolved_project_dir / rel_path
        if not full_path.is_file():
            continue
        receipts.append(
            {
                "path": rel_path,
                "payload": _load_json_object(full_path, label=f"Project receipt ({rel_path})"),
            }
        )

    return normalize_project_session(
        {
            "schema_version": PROJECT_SESSION_SCHEMA_VERSION,
            "scene": scene_payload,
            "history": history_payload,
            "receipts": receipts,
        }
    )


def write_project_session(path: Path, project_session: dict[str, Any], *, force: bool) -> dict[str, Any]:
    normalized = normalize_project_session(project_session)
    if path.exists() and not force:
        raise ValueError(f"File exists (use --force to overwrite): {path.as_posix()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def load_project_session(path: Path) -> dict[str, Any]:
    return normalize_project_session(_load_json_object(path, label="Project session"))


def save_project_session(
    project_dir: Path,
    *,
    session_path: Path | None = None,
    force: bool,
) -> dict[str, Any]:
    resolved_project_dir = project_dir.resolve()
    if not resolved_project_dir.is_dir():
        raise ValueError(f"Project directory does not exist: {resolved_project_dir.as_posix()}")

    output_path = session_path.resolve() if session_path is not None else default_project_session_path(
        resolved_project_dir
    )
    payload = build_project_session_payload(resolved_project_dir)
    normalized = write_project_session(output_path, payload, force=force)
    return {
        "ok": True,
        "project_dir": resolved_project_dir.as_posix(),
        "session_path": output_path.as_posix(),
        "scene_path": (resolved_project_dir / _PROJECT_SCENE_REL_PATH).as_posix(),
        "history_count": len(normalized["history"]),
        "receipt_count": len(normalized["receipts"]),
        "written": [output_path.as_posix()],
    }


def load_project_session_into_project(
    project_dir: Path,
    *,
    session_path: Path,
    force: bool,
) -> dict[str, Any]:
    resolved_project_dir = project_dir.resolve()
    if not resolved_project_dir.is_dir():
        raise ValueError(f"Project directory does not exist: {resolved_project_dir.as_posix()}")

    normalized = load_project_session(session_path.resolve())
    scene_path = resolved_project_dir / _PROJECT_SCENE_REL_PATH
    history_path = resolved_project_dir / _PROJECT_HISTORY_REL_PATH

    target_paths: list[Path] = [scene_path, history_path]
    receipt_targets: list[tuple[Path, dict[str, Any], str]] = []
    for receipt in normalized["receipts"]:
        rel_path = _validate_relative_posix_path(
            receipt.get("path"),
            field_name="receipts.path",
        )
        target_path = resolved_project_dir / rel_path
        receipt_targets.append((target_path, dict(receipt["payload"]), rel_path))
        target_paths.append(target_path)

    seen_targets: set[Path] = set()
    for target_path in target_paths:
        resolved_target = target_path.resolve()
        if resolved_target in seen_targets:
            raise ValueError(f"Project session contains duplicate target path: {resolved_target.as_posix()}")
        seen_targets.add(resolved_target)

    if not force:
        for target_path in target_paths:
            if target_path.exists():
                raise ValueError(
                    f"File exists (use --force to overwrite): {target_path.as_posix()}"
                )

    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(
        json.dumps(normalized["scene"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    _write_history_jsonl(history_path, normalized["history"])

    written_rel_paths: set[str] = {
        _PROJECT_SCENE_REL_PATH.as_posix(),
        _PROJECT_HISTORY_REL_PATH.as_posix(),
    }
    for target_path, payload, rel_path in receipt_targets:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written_rel_paths.add(rel_path)

    return {
        "ok": True,
        "project_dir": resolved_project_dir.as_posix(),
        "session_path": session_path.resolve().as_posix(),
        "history_count": len(normalized["history"]),
        "receipt_count": len(normalized["receipts"]),
        "written": sorted(written_rel_paths),
    }
