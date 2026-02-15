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
_INDEX_OPTIONAL_KEYS = {"packs"}
_PRESET_REQUIRED_KEYS = {"preset_id", "file", "label", "description"}
_PRESET_OPTIONAL_STRING_KEYS = {"category", "help_id", "overlay"}
_PRESET_OPTIONAL_STRING_LIST_KEYS = ("tags", "goals", "warnings")
_PRESET_ALLOWED_KEYS = (
    _PRESET_REQUIRED_KEYS
    | _PRESET_OPTIONAL_STRING_KEYS
    | set(_PRESET_OPTIONAL_STRING_LIST_KEYS)
)
_PACK_REQUIRED_KEYS = {"pack_id", "label", "description", "preset_ids"}
from mmo.resources import presets_dir as _presets_dir, schemas_dir

_PACK_ALLOWED_KEYS = _PACK_REQUIRED_KEYS


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


def _normalize_optional_string_field(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Preset field {key} must be a string when present.")
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"Preset field {key} must not be empty when present.")
    return normalized_value


def _normalize_optional_string_list_field(item: dict[str, Any], key: str) -> list[str] | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"Preset field {key} must be an array of strings when present.")

    normalized_items: list[str] = []
    for idx, list_item in enumerate(value):
        if not isinstance(list_item, str):
            raise ValueError(
                f"Preset field {key}[{idx}] must be a string when {key} is present."
            )
        normalized_item = list_item.strip()
        if not normalized_item:
            raise ValueError(f"Preset field {key}[{idx}] must not be empty.")
        normalized_items.append(normalized_item)
    return normalized_items


def _validate_preset_index_basic(index: dict[str, Any], *, index_path: Path) -> dict[str, Any]:
    unknown = sorted(set(index.keys()) - (_INDEX_REQUIRED_KEYS | _INDEX_OPTIONAL_KEYS))
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

    normalized_presets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for item in presets:
        if not isinstance(item, dict):
            raise ValueError("Each preset index entry must be an object.")

        unknown_item = sorted(set(item.keys()) - _PRESET_ALLOWED_KEYS)
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

        normalized_preset: dict[str, Any] = {
            "preset_id": normalized_id,
            "file": normalized_file,
            "label": normalized_label,
            "description": normalized_description,
        }
        for key in _PRESET_OPTIONAL_STRING_KEYS:
            normalized_value = _normalize_optional_string_field(item, key)
            if normalized_value is not None:
                normalized_preset[key] = normalized_value
        for key in _PRESET_OPTIONAL_STRING_LIST_KEYS:
            normalized_values = _normalize_optional_string_list_field(item, key)
            if normalized_values is not None:
                normalized_preset[key] = normalized_values
        normalized_presets.append(normalized_preset)

    sorted_ids = sorted(item["preset_id"] for item in normalized_presets)
    actual_ids = [item["preset_id"] for item in normalized_presets]
    if actual_ids != sorted_ids:
        raise ValueError(f"Preset index must be sorted by preset_id: {index_path}")

    normalized_index: dict[str, Any] = {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "presets": normalized_presets,
    }

    packs = index.get("packs")
    if packs is None:
        return normalized_index
    if not isinstance(packs, list):
        raise ValueError("Preset index field 'packs' must be a list when present.")

    known_preset_ids = {item["preset_id"] for item in normalized_presets}
    normalized_packs: list[dict[str, Any]] = []
    seen_pack_ids: set[str] = set()
    for item in packs:
        if not isinstance(item, dict):
            raise ValueError("Each preset pack entry must be an object.")

        unknown_pack = sorted(set(item.keys()) - _PACK_ALLOWED_KEYS)
        if unknown_pack:
            raise ValueError(f"Unknown preset pack field(s): {', '.join(unknown_pack)}")

        missing_pack = sorted(_PACK_REQUIRED_KEYS - set(item.keys()))
        if missing_pack:
            raise ValueError(f"Missing preset pack field(s): {', '.join(missing_pack)}")

        pack_id = item.get("pack_id")
        label = item.get("label")
        description = item.get("description")
        values = {
            "pack_id": pack_id,
            "label": label,
            "description": description,
        }
        for key, value in values.items():
            if not isinstance(value, str):
                raise ValueError(f"Preset pack field {key} must be a string.")
            if not value.strip():
                raise ValueError(f"Preset pack field {key} must not be empty.")

        normalized_pack_id = str(pack_id).strip()
        if normalized_pack_id in seen_pack_ids:
            raise ValueError(f"Duplicate pack_id in preset index: {normalized_pack_id}")
        seen_pack_ids.add(normalized_pack_id)

        preset_ids = item.get("preset_ids")
        if not isinstance(preset_ids, list):
            raise ValueError("Preset pack field preset_ids must be a list.")

        normalized_preset_ids: list[str] = []
        seen_preset_ids: set[str] = set()
        for idx, preset_id in enumerate(preset_ids):
            if not isinstance(preset_id, str):
                raise ValueError(
                    "Preset pack field preset_ids"
                    f"[{idx}] must be a string."
                )
            normalized_preset_id = preset_id.strip()
            if not normalized_preset_id:
                raise ValueError(
                    "Preset pack field preset_ids"
                    f"[{idx}] must not be empty."
                )
            if normalized_preset_id in seen_preset_ids:
                raise ValueError(
                    "Preset pack field preset_ids contains duplicates: "
                    f"{normalized_preset_id}"
                )
            if normalized_preset_id not in known_preset_ids:
                raise ValueError(
                    "Preset pack field preset_ids references unknown preset_id: "
                    f"{normalized_preset_id}"
                )
            seen_preset_ids.add(normalized_preset_id)
            normalized_preset_ids.append(normalized_preset_id)

        if not normalized_preset_ids:
            raise ValueError("Preset pack field preset_ids must not be empty.")

        normalized_packs.append(
            {
                "pack_id": normalized_pack_id,
                "label": str(label).strip(),
                "description": str(description).strip(),
                "preset_ids": normalized_preset_ids,
            }
        )

    sorted_pack_ids = sorted(item["pack_id"] for item in normalized_packs)
    actual_pack_ids = [item["pack_id"] for item in normalized_packs]
    if actual_pack_ids != sorted_pack_ids:
        raise ValueError(f"Preset index packs must be sorted by pack_id: {index_path}")

    normalized_index["packs"] = normalized_packs
    return normalized_index


def load_preset_index(presets_dir: Path) -> dict[str, Any]:
    index_path = presets_dir / "index.json"
    index = _load_json_object(index_path, label="Preset index")
    normalized = _validate_preset_index_basic(index, index_path=index_path)
    _validate_payload_against_schema(
        normalized,
        schema_path=schemas_dir() / "presets_index.schema.json",
        payload_name="Preset index",
    )
    return normalized


def _normalize_filter_value(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized or None


def _matches_preset_filters(
    item: dict[str, Any],
    *,
    normalized_tag: str | None,
    normalized_category: str | None,
) -> bool:
    if normalized_category is not None:
        category_value = item.get("category")
        if not isinstance(category_value, str):
            return False
        if category_value.casefold() != normalized_category:
            return False

    if normalized_tag is not None:
        tags_value = item.get("tags")
        if not isinstance(tags_value, list):
            return False
        tag_values = {
            tag.casefold()
            for tag in tags_value
            if isinstance(tag, str) and tag.strip()
        }
        if normalized_tag not in tag_values:
            return False

    return True


def list_presets(
    presets_dir: Path,
    *,
    tag: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    index = load_preset_index(presets_dir)
    presets = index.get("presets", [])
    if not isinstance(presets, list):
        return []

    normalized_tag = _normalize_filter_value(tag)
    normalized_category = _normalize_filter_value(category)
    return sorted(
        [
            dict(item)
            for item in presets
            if isinstance(item, dict)
            and _matches_preset_filters(
                item,
                normalized_tag=normalized_tag,
                normalized_category=normalized_category,
            )
        ],
        key=lambda item: str(item.get("preset_id", "")),
    )


def get_preset_help_id(preset_id: str) -> str | None:
    normalized_preset_id = preset_id.strip() if isinstance(preset_id, str) else ""
    if not normalized_preset_id:
        return None

    presets_dir = _presets_dir()
    try:
        presets = list_presets(presets_dir)
    except ValueError:
        return None

    for item in presets:
        if item.get("preset_id") != normalized_preset_id:
            continue
        help_id = item.get("help_id")
        if not isinstance(help_id, str):
            return None
        normalized_help_id = help_id.strip()
        return normalized_help_id or None
    return None


def list_preset_packs(presets_dir: Path) -> list[dict[str, Any]]:
    index = load_preset_index(presets_dir)
    packs = index.get("packs", [])
    if not isinstance(packs, list):
        return []
    return sorted(
        [dict(item) for item in packs if isinstance(item, dict)],
        key=lambda item: str(item.get("pack_id", "")),
    )


def load_preset_pack(presets_dir: Path, pack_id: str) -> dict[str, Any]:
    normalized_pack_id = pack_id.strip() if isinstance(pack_id, str) else ""
    if not normalized_pack_id:
        raise ValueError("pack_id must be a non-empty string.")

    packs = list_preset_packs(presets_dir)
    pack_entry = next(
        (
            item
            for item in packs
            if item.get("pack_id") == normalized_pack_id
        ),
        None,
    )
    if pack_entry is None:
        available = ", ".join(item["pack_id"] for item in packs)
        if available:
            raise ValueError(
                f"Unknown pack_id: {normalized_pack_id}. Available packs: {available}"
            )
        raise ValueError(f"Unknown pack_id: {normalized_pack_id}. No packs are available.")
    return dict(pack_entry)


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
        schema_path=schemas_dir() / "run_config.schema.json",
        payload_name=f"Preset run config ({normalized_preset_id})",
    )

    normalized = normalize_run_config(preset_payload)
    normalized["preset_id"] = normalized_preset_id
    return normalize_run_config(normalized)
