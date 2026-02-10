from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.dsp.downmix import load_layouts

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

RENDER_TARGETS_SCHEMA_VERSION = "0.1.0"
_DEFAULT_TARGETS_PATH = Path("ontology/render_targets.yaml")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return _repo_root() / _DEFAULT_TARGETS_PATH
    if path.is_absolute():
        return path
    return _repo_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load render targets.")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(f"Failed to read {label} YAML from {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} YAML is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} YAML root must be a mapping: {path}")
    return payload


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _validate_payload_against_schema(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate render targets.")

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _targets_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return []
    return [item for item in targets if isinstance(item, dict)]


def _validate_target_order(targets: list[dict[str, Any]], *, path: Path) -> None:
    target_ids = [item.get("target_id") for item in targets]
    if any(not isinstance(target_id, str) for target_id in target_ids):
        return
    sorted_ids = sorted(target_ids)
    if target_ids != sorted_ids:
        raise ValueError(f"Render targets must be sorted by target_id: {path}")


def _validate_layout_ids(targets: list[dict[str, Any]], *, path: Path) -> None:
    layouts_path = _repo_root() / "ontology" / "layouts.yaml"
    try:
        layouts = load_layouts(layouts_path)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"Failed to load layouts from {layouts_path}: {exc}") from exc

    unknown_layout_rows: list[str] = []
    for target in targets:
        target_id = target.get("target_id")
        layout_id = target.get("layout_id")
        if not isinstance(target_id, str) or not isinstance(layout_id, str):
            continue
        if layout_id not in layouts:
            unknown_layout_rows.append(f"{target_id} -> {layout_id}")
    if not unknown_layout_rows:
        return

    details = ", ".join(sorted(unknown_layout_rows))
    raise ValueError(f"Render target layout_id is unknown in {path}: {details}")


def _validate_speaker_positions(targets: list[dict[str, Any]], *, path: Path) -> None:
    for target in targets:
        target_id = target.get("target_id", "<unknown>")
        positions = target.get("speaker_positions")
        if not isinstance(positions, list):
            continue

        channels: list[int] = []
        for position in positions:
            if not isinstance(position, dict):
                continue
            ch = position.get("ch")
            if isinstance(ch, bool) or not isinstance(ch, int):
                continue
            channels.append(ch)

        if channels != sorted(channels):
            raise ValueError(
                "Render target speaker_positions must be sorted by ch: "
                f"{target_id} ({path})"
            )
        if len(channels) != len(set(channels)):
            raise ValueError(
                "Render target speaker_positions must be deterministic "
                f"(duplicate ch values): {target_id} ({path})"
            )


def load_render_targets(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Render targets registry")
    _validate_payload_against_schema(
        payload,
        schema_path=_repo_root() / "schemas" / "render_targets.schema.json",
        payload_name="Render targets registry",
    )

    targets = _targets_list(payload)
    _validate_target_order(targets, path=resolved_path)
    _validate_layout_ids(targets, path=resolved_path)
    _validate_speaker_positions(targets, path=resolved_path)
    return payload


def list_render_targets(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_render_targets(path)
    targets = _targets_list(payload)
    return sorted(
        [dict(item) for item in targets],
        key=lambda item: str(item.get("target_id", "")),
    )


def get_render_target(target_id: str, path: Path | None = None) -> dict[str, Any] | None:
    normalized_target_id = target_id.strip() if isinstance(target_id, str) else ""
    if not normalized_target_id:
        return None
    for target in list_render_targets(path):
        if target.get("target_id") == normalized_target_id:
            return dict(target)
    return None
