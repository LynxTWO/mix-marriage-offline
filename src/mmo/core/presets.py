from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

_INDEX_REQUIRED_KEYS = {"schema_version", "presets"}
_PRESET_REQUIRED_KEYS = {"preset_id", "file", "label", "description"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return raw


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    schema = _load_json_object(schema_path, label="Schema")
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
        return

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(part) for part in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _validate_preset_index_basic(index: dict[str, Any], *, index_path: Path) -> dict[str, Any]:
    unknown = sorted(set(index.keys()) - _INDEX_REQUIRED_KEYS)
    if unknown:
        raise ValueError(f"Unknown preset index field(s): {', '.join(unknown)}")

    missing = sorted(_INDEX_REQUIRED_KEYS - set(index.keys()))
    if missing:
        raise ValueError(f"Missing preset index field(s): {', '.join(missing)}")

    schema_version = index.get("schema_version")
    if not isinstance(schema_version, str) or schema_version.strip() != RUN_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported preset index schema_version: "
            f"{schema_version!r} (expected {RUN_CONFIG_SCHEMA_VERSION!r})."
        )

    presets = index.get("presets")
    if not isinstance(presets, list):
        raise ValueError("Preset index field 'presets' must be a list.")

    normalized_presets: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for item in presets:
        if not isinstance(item, dict):
            raise ValueError("Each preset index entry must be an object.")

        unknown_item = sorted(set(item.keys()) - _PRESET_REQUIRED_KEYS)
        if unknown_item:
            raise ValueError(f"Unknown preset field(s): {', '.join(unknown_item)}")

        missing_item = sorted(_PRESET_REQUIRED_KEYS - set(item.keys()))
        if missing_item:
            raise ValueError(f"Missing preset field(s): {', '.join(missing_item)}")

        preset_id = item.get("preset_id")
        file_name = item.get("file")
        label = item.get("label")
        description = item.get("description")
        values = {
            "preset_id": preset_id,
            "file": file_name,
            "label": label,
            "description": description,
        }
        for key, value in values.items():
            if not isinstance(value, str):
                raise ValueError(f"Preset field {key} must be a string.")
            if not value.strip():
                raise ValueError(f"Preset field {key} must not be empty.")

        normalized_id = str(preset_id).strip()
        normalized_file = str(file_name).strip()
        normalized_label = str(label).strip()
        normalized_description = str(description).strip()

        file_path = Path(normalized_file)
        if file_path.is_absolute():
            raise ValueError(f"Preset file path must be relative: {normalized_file}")
        if ".." in file_path.parts:
            raise ValueError(f"Preset file path must not escape presets/: {normalized_file}")

        if normalized_id in seen_ids:
            raise ValueError(f"Duplicate preset_id in preset index: {normalized_id}")
        if normalized_file in seen_files:
            raise ValueError(f"Duplicate preset file in preset index: {normalized_file}")
        seen_ids.add(normalized_id)
        seen_files.add(normalized_file)

        normalized_presets.append(
            {
                "preset_id": normalized_id,
                "file": normalized_file,
                "label": normalized_label,
                "description": normalized_description,
            }
        )

    sorted_ids = sorted(item["preset_id"] for item in normalized_presets)
    actual_ids = [item["preset_id"] for item in normalized_presets]
    if actual_ids != sorted_ids:
        raise ValueError(f"Preset index must be sorted by preset_id: {index_path}")

    return {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "presets": normalized_presets,
    }


def load_preset_index(presets_dir: Path) -> dict[str, Any]:
    index_path = presets_dir / "index.json"
    index = _load_json_object(index_path, label="Preset index")
    normalized = _validate_preset_index_basic(index, index_path=index_path)
    _validate_payload_against_schema(
        normalized,
        schema_path=_repo_root() / "schemas" / "presets_index.schema.json",
        payload_name="Preset index",
    )
    return normalized


def list_presets(presets_dir: Path) -> list[dict[str, Any]]:
    index = load_preset_index(presets_dir)
    presets = index.get("presets", [])
    if not isinstance(presets, list):
        return []
    return sorted(
        [dict(item) for item in presets if isinstance(item, dict)],
        key=lambda item: str(item.get("preset_id", "")),
    )


def load_preset_run_config(presets_dir: Path, preset_id: str) -> dict[str, Any]:
    normalized_preset_id = preset_id.strip() if isinstance(preset_id, str) else ""
    if not normalized_preset_id:
        raise ValueError("preset_id must be a non-empty string.")

    preset_entry = next(
        (
            item
            for item in list_presets(presets_dir)
            if item.get("preset_id") == normalized_preset_id
        ),
        None,
    )
    if preset_entry is None:
        available = ", ".join(item["preset_id"] for item in list_presets(presets_dir))
        if available:
            raise ValueError(
                f"Unknown preset_id: {normalized_preset_id}. Available presets: {available}"
            )
        raise ValueError(
            f"Unknown preset_id: {normalized_preset_id}. No presets are available."
        )

    preset_file = presets_dir / str(preset_entry["file"])
    preset_payload = _load_json_object(
        preset_file,
        label=f"Preset run config ({normalized_preset_id})",
    )
    _validate_payload_against_schema(
        preset_payload,
        schema_path=_repo_root() / "schemas" / "run_config.schema.json",
        payload_name=f"Preset run config ({normalized_preset_id})",
    )

    normalized = normalize_run_config(preset_payload)
    normalized["preset_id"] = normalized_preset_id
    return normalize_run_config(normalized)
