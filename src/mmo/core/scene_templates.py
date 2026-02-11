from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mmo.core.scene_locks import load_scene_locks

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

SCENE_TEMPLATES_SCHEMA_VERSION = "0.1.0"
_DEFAULT_SCENE_TEMPLATES_PATH = Path("ontology/scene_templates.yaml")
_HARD_LOCK_SEVERITY = "hard"
_OBJECT_SCOPE = "object"
_BED_SCOPE = "bed"
_SCENE_SCOPE = "scene"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return _repo_root() / _DEFAULT_SCENE_TEMPLATES_PATH
    if path.is_absolute():
        return path
    return _repo_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load scene templates registries.")
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
        raise RuntimeError("jsonschema is required to validate scene templates registries.")

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


def _templates_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = payload.get("templates")
    if not isinstance(templates, dict):
        return {}
    return {
        template_id: dict(template_payload)
        for template_id, template_payload in templates.items()
        if isinstance(template_id, str) and isinstance(template_payload, dict)
    }


def _validate_template_order(templates: dict[str, dict[str, Any]], *, path: Path) -> None:
    template_ids = [template_id for template_id in templates.keys() if isinstance(template_id, str)]
    sorted_template_ids = sorted(template_ids)
    if template_ids != sorted_template_ids:
        raise ValueError(f"Scene templates must be sorted by template_id: {path}")


def _validate_patch_regexes(templates: dict[str, dict[str, Any]], *, path: Path) -> None:
    for template_id, template_payload in templates.items():
        patches = template_payload.get("patches")
        if not isinstance(patches, list):
            continue
        for index, patch in enumerate(patches):
            if not isinstance(patch, dict):
                continue
            match = patch.get("match")
            if not isinstance(match, dict):
                continue
            label_regex = match.get("label_regex")
            if not isinstance(label_regex, str) or not label_regex:
                continue
            try:
                re.compile(label_regex)
            except re.error as exc:
                raise ValueError(
                    "Scene template label_regex failed to compile: "
                    f"{template_id} patch[{index}] ({path}): {exc}"
                ) from exc


def load_scene_templates(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Scene templates registry")
    _validate_payload_against_schema(
        payload,
        schema_path=_repo_root() / "schemas" / "scene_templates.schema.json",
        payload_name="Scene templates registry",
    )

    templates = _templates_map(payload)
    _validate_template_order(templates, path=resolved_path)
    _validate_patch_regexes(templates, path=resolved_path)
    normalized_payload = dict(payload)
    normalized_payload["templates"] = {
        template_id: dict(templates[template_id])
        for template_id in sorted(templates.keys())
    }
    return normalized_payload


def list_scene_templates(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_scene_templates(path)
    templates = _templates_map(payload)
    rows: list[dict[str, Any]] = []
    for template_id in sorted(templates.keys()):
        row = {"template_id": template_id}
        row.update(dict(templates[template_id]))
        rows.append(row)
    return rows


def get_scene_template(
    template_id: str,
    path: Path | None = None,
) -> dict[str, Any] | None:
    normalized_template_id = template_id.strip() if isinstance(template_id, str) else ""
    if not normalized_template_id:
        return None
    for template in list_scene_templates(path):
        if template.get("template_id") == normalized_template_id:
            return dict(template)
    return None


def _clone_scene(scene: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")
    return json.loads(json.dumps(scene))


def _sorted_entry_rows(rows: Any, *, id_key: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = [dict(item) for item in rows if isinstance(item, dict)]
    normalized.sort(key=lambda item: str(item.get(id_key, "")))
    return normalized


def _normalize_scene_order(scene: dict[str, Any]) -> None:
    scene["objects"] = _sorted_entry_rows(scene.get("objects"), id_key="object_id")
    scene["beds"] = _sorted_entry_rows(scene.get("beds"), id_key="bed_id")


def _lock_ids_from_intent(intent: Any) -> set[str]:
    if not isinstance(intent, dict):
        return set()
    locks = intent.get("locks")
    if not isinstance(locks, list):
        return set()
    return {
        lock_id.strip()
        for lock_id in locks
        if isinstance(lock_id, str) and lock_id.strip()
    }


def _hard_lock_ids(scene_locks_registry: dict[str, Any]) -> set[str]:
    locks = scene_locks_registry.get("locks")
    if not isinstance(locks, dict):
        return set()
    hard_ids: set[str] = set()
    for lock_id, lock_payload in locks.items():
        if not isinstance(lock_id, str) or not isinstance(lock_payload, dict):
            continue
        severity = lock_payload.get("severity")
        if isinstance(severity, str) and severity == _HARD_LOCK_SEVERITY:
            hard_ids.add(lock_id)
    return hard_ids


def _target_has_hard_lock(
    *,
    scene_lock_ids: set[str],
    target_lock_ids: set[str],
    hard_lock_ids: set[str],
) -> bool:
    if not hard_lock_ids:
        return False
    return bool((scene_lock_ids | target_lock_ids) & hard_lock_ids)


def _ensure_scene_intent(scene: dict[str, Any]) -> dict[str, Any]:
    intent = scene.get("intent")
    if isinstance(intent, dict):
        return intent
    created_intent = {"confidence": 0.0, "locks": []}
    scene["intent"] = created_intent
    return created_intent


def _ensure_entry_intent(entry: dict[str, Any]) -> dict[str, Any]:
    intent = entry.get("intent")
    if isinstance(intent, dict):
        return intent
    created_intent = {"confidence": 0.0, "locks": []}
    entry["intent"] = created_intent
    return created_intent


def _apply_set_payload(
    *,
    target: dict[str, Any],
    set_payload: dict[str, Any],
    force: bool,
) -> None:
    for key, value in set_payload.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if isinstance(existing, dict):
                _apply_set_payload(target=existing, set_payload=value, force=force)
                continue
            if key in target and not force:
                continue
            new_target: dict[str, Any] = {}
            target[key] = new_target
            _apply_set_payload(target=new_target, set_payload=value, force=force)
            continue
        if force or key not in target:
            target[key] = value


def _copy_json_value(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _preview_source(*, template_id: str, patch_index: int) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "patch_index": patch_index,
    }


def _preview_sort_key(row: dict[str, Any]) -> tuple[str, str, int]:
    path = _coerce_str(row.get("path")).strip()
    source = row.get("source")
    template_id = ""
    patch_index = 0
    if isinstance(source, dict):
        template_id = _coerce_str(source.get("template_id")).strip()
        patch_index_value = source.get("patch_index")
        if isinstance(patch_index_value, int):
            patch_index = patch_index_value
    return (path, template_id, patch_index)


def _sort_preview_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
    normalized_rows.sort(key=_preview_sort_key)
    return normalized_rows


def _ensure_intent_for_preview(
    *,
    target: dict[str, Any],
    changes: list[dict[str, Any]],
    source: dict[str, Any],
) -> dict[str, Any]:
    intent = target.get("intent")
    if isinstance(intent, dict):
        return intent
    created_intent = {"confidence": 0.0, "locks": []}
    target["intent"] = created_intent
    changes.append(
        {
            "path": "intent.confidence",
            "before": None,
            "after": 0.0,
            "reason": "set_missing",
            "source": dict(source),
        }
    )
    changes.append(
        {
            "path": "intent.locks",
            "before": None,
            "after": [],
            "reason": "set_missing",
            "source": dict(source),
        }
    )
    return created_intent


def _preview_apply_set_payload(
    *,
    target: dict[str, Any],
    set_payload: dict[str, Any],
    force: bool,
    source: dict[str, Any],
    changes: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    path_prefix: str,
) -> None:
    for key, value in set_payload.items():
        path = f"{path_prefix}.{key}" if path_prefix else key
        if isinstance(value, dict):
            existing = target.get(key)
            if isinstance(existing, dict):
                _preview_apply_set_payload(
                    target=existing,
                    set_payload=value,
                    force=force,
                    source=source,
                    changes=changes,
                    skipped=skipped,
                    path_prefix=path,
                )
                continue
            if key in target and not force:
                skipped.append(
                    {
                        "path": path,
                        "reason": "existing_value",
                        "source": dict(source),
                    }
                )
                continue
            new_target: dict[str, Any] = {}
            target[key] = new_target
            _preview_apply_set_payload(
                target=new_target,
                set_payload=value,
                force=force,
                source=source,
                changes=changes,
                skipped=skipped,
                path_prefix=path,
            )
            continue

        has_existing = key in target
        if has_existing and not force:
            skipped.append(
                {
                    "path": path,
                    "reason": "existing_value",
                    "source": dict(source),
                }
            )
            continue

        before = _copy_json_value(target.get(key)) if has_existing else None
        after = _copy_json_value(value)
        target[key] = after
        changes.append(
            {
                "path": path,
                "before": before,
                "after": after,
                "reason": "overwrite" if has_existing else "set_missing",
                "source": dict(source),
            }
        )


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _match_scene_patch(scene: dict[str, Any], match_payload: dict[str, Any]) -> bool:
    scene_id = _coerce_str(match_payload.get("scene_id")).strip()
    if scene_id:
        return _coerce_str(scene.get("scene_id")).strip() == scene_id
    return True


def _match_object_patch(entry: dict[str, Any], match_payload: dict[str, Any]) -> bool:
    object_id = _coerce_str(match_payload.get("object_id")).strip()
    if object_id and _coerce_str(entry.get("object_id")).strip() != object_id:
        return False

    label_regex = match_payload.get("label_regex")
    if isinstance(label_regex, str) and label_regex:
        label = _coerce_str(entry.get("label"))
        return re.search(label_regex, label) is not None
    return True


def _match_bed_patch(entry: dict[str, Any], match_payload: dict[str, Any]) -> bool:
    bed_id = _coerce_str(match_payload.get("bed_id")).strip()
    if bed_id and _coerce_str(entry.get("bed_id")).strip() != bed_id:
        return False

    bed_kind = _coerce_str(match_payload.get("bed_kind")).strip()
    if bed_kind and _coerce_str(entry.get("kind")).strip() != bed_kind:
        return False
    return True


def _resolve_template_ids(
    template_ids: list[str],
    *,
    templates: dict[str, dict[str, Any]],
) -> list[str]:
    normalized_template_ids: list[str] = []
    for template_id in template_ids:
        normalized = template_id.strip() if isinstance(template_id, str) else ""
        if normalized:
            normalized_template_ids.append(normalized)
    if not normalized_template_ids:
        raise ValueError("At least one template_id is required.")

    unknown = sorted(
        {
            template_id
            for template_id in normalized_template_ids
            if template_id not in templates
        }
    )
    if unknown:
        available = ", ".join(sorted(templates.keys()))
        unknown_label = ", ".join(unknown)
        if available:
            raise ValueError(
                f"Unknown template_id: {unknown_label}. Available templates: {available}"
            )
        raise ValueError(
            f"Unknown template_id: {unknown_label}. No scene templates are available."
        )
    return normalized_template_ids


def apply_scene_templates(
    scene: dict[str, Any],
    template_ids: list[str],
    *,
    force: bool = False,
    scene_templates_path: Path | None = None,
    scene_locks_path: Path | None = None,
) -> dict[str, Any]:
    edited = _clone_scene(scene)
    registry = load_scene_templates(scene_templates_path)
    templates = _templates_map(registry)
    ordered_template_ids = _resolve_template_ids(template_ids, templates=templates)

    scene_locks_registry = load_scene_locks(scene_locks_path)
    hard_lock_ids = _hard_lock_ids(scene_locks_registry)
    scene_lock_ids = _lock_ids_from_intent(edited.get("intent"))
    scene_hard_locked = bool(scene_lock_ids & hard_lock_ids)

    for template_id in ordered_template_ids:
        template_payload = templates.get(template_id)
        if not isinstance(template_payload, dict):
            continue
        patches = template_payload.get("patches")
        if not isinstance(patches, list):
            continue
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            scope = _coerce_str(patch.get("scope")).strip()
            match_payload = patch.get("match")
            set_payload = patch.get("set")
            if not isinstance(match_payload, dict) or not isinstance(set_payload, dict):
                continue

            if scope == _SCENE_SCOPE:
                if scene_hard_locked:
                    continue
                if not _match_scene_patch(edited, match_payload):
                    continue
                scene_intent = _ensure_scene_intent(edited)
                _apply_set_payload(
                    target=scene_intent,
                    set_payload=set_payload,
                    force=force,
                )
                continue

            if scope == _OBJECT_SCOPE:
                objects = edited.get("objects")
                if not isinstance(objects, list):
                    continue
                for entry in objects:
                    if not isinstance(entry, dict):
                        continue
                    if not _match_object_patch(entry, match_payload):
                        continue
                    if _target_has_hard_lock(
                        scene_lock_ids=scene_lock_ids,
                        target_lock_ids=_lock_ids_from_intent(entry.get("intent")),
                        hard_lock_ids=hard_lock_ids,
                    ):
                        continue
                    entry_intent = _ensure_entry_intent(entry)
                    _apply_set_payload(
                        target=entry_intent,
                        set_payload=set_payload,
                        force=force,
                    )
                continue

            if scope == _BED_SCOPE:
                beds = edited.get("beds")
                if not isinstance(beds, list):
                    continue
                for entry in beds:
                    if not isinstance(entry, dict):
                        continue
                    if not _match_bed_patch(entry, match_payload):
                        continue
                    if _target_has_hard_lock(
                        scene_lock_ids=scene_lock_ids,
                        target_lock_ids=_lock_ids_from_intent(entry.get("intent")),
                        hard_lock_ids=hard_lock_ids,
                    ):
                        continue
                    entry_intent = _ensure_entry_intent(entry)
                    _apply_set_payload(
                        target=entry_intent,
                        set_payload=set_payload,
                        force=force,
                    )

    _normalize_scene_order(edited)
    return edited


def preview_scene_templates(
    scene: dict[str, Any],
    template_ids: list[str],
    *,
    force: bool = False,
    scene_templates_path: Path | None = None,
    scene_locks_path: Path | None = None,
) -> dict[str, Any]:
    preview_scene = _clone_scene(scene)
    registry = load_scene_templates(scene_templates_path)
    templates = _templates_map(registry)
    ordered_template_ids = _resolve_template_ids(template_ids, templates=templates)

    scene_locks_registry = load_scene_locks(scene_locks_path)
    hard_lock_ids = _hard_lock_ids(scene_locks_registry)
    scene_lock_ids = _lock_ids_from_intent(preview_scene.get("intent"))
    scene_hard_locked = bool(scene_lock_ids & hard_lock_ids)

    scene_preview: dict[str, Any] = {
        "hard_locked": scene_hard_locked,
        "changes": [],
        "skipped": [],
    }

    object_targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    objects = preview_scene.get("objects")
    if isinstance(objects, list):
        for entry in objects:
            if not isinstance(entry, dict):
                continue
            object_targets.append(
                (
                    entry,
                    {
                        "object_id": _coerce_str(entry.get("object_id")).strip(),
                        "label": _coerce_str(entry.get("label")).strip(),
                        "hard_locked": _target_has_hard_lock(
                            scene_lock_ids=scene_lock_ids,
                            target_lock_ids=_lock_ids_from_intent(entry.get("intent")),
                            hard_lock_ids=hard_lock_ids,
                        ),
                        "changes": [],
                        "skipped": [],
                    },
                )
            )

    bed_targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    beds = preview_scene.get("beds")
    if isinstance(beds, list):
        for entry in beds:
            if not isinstance(entry, dict):
                continue
            bed_targets.append(
                (
                    entry,
                    {
                        "bed_id": _coerce_str(entry.get("bed_id")).strip(),
                        "kind": _coerce_str(entry.get("kind")).strip(),
                        "hard_locked": _target_has_hard_lock(
                            scene_lock_ids=scene_lock_ids,
                            target_lock_ids=_lock_ids_from_intent(entry.get("intent")),
                            hard_lock_ids=hard_lock_ids,
                        ),
                        "changes": [],
                        "skipped": [],
                    },
                )
            )

    for template_id in ordered_template_ids:
        template_payload = templates.get(template_id)
        if not isinstance(template_payload, dict):
            continue
        patches = template_payload.get("patches")
        if not isinstance(patches, list):
            continue
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, dict):
                continue
            scope = _coerce_str(patch.get("scope")).strip()
            match_payload = patch.get("match")
            set_payload = patch.get("set")
            if not isinstance(match_payload, dict) or not isinstance(set_payload, dict):
                continue
            source = _preview_source(template_id=template_id, patch_index=patch_index)

            if scope == _SCENE_SCOPE:
                if scene_hard_locked:
                    continue
                if not _match_scene_patch(preview_scene, match_payload):
                    continue
                scene_intent = _ensure_intent_for_preview(
                    target=preview_scene,
                    changes=scene_preview["changes"],
                    source=source,
                )
                _preview_apply_set_payload(
                    target=scene_intent,
                    set_payload=set_payload,
                    force=force,
                    source=source,
                    changes=scene_preview["changes"],
                    skipped=scene_preview["skipped"],
                    path_prefix="intent",
                )
                continue

            if scope == _OBJECT_SCOPE:
                for entry, preview_payload in object_targets:
                    if not _match_object_patch(entry, match_payload):
                        continue
                    if bool(preview_payload.get("hard_locked")):
                        continue
                    entry_intent = _ensure_intent_for_preview(
                        target=entry,
                        changes=preview_payload["changes"],
                        source=source,
                    )
                    _preview_apply_set_payload(
                        target=entry_intent,
                        set_payload=set_payload,
                        force=force,
                        source=source,
                        changes=preview_payload["changes"],
                        skipped=preview_payload["skipped"],
                        path_prefix="intent",
                    )
                continue

            if scope == _BED_SCOPE:
                for entry, preview_payload in bed_targets:
                    if not _match_bed_patch(entry, match_payload):
                        continue
                    if bool(preview_payload.get("hard_locked")):
                        continue
                    entry_intent = _ensure_intent_for_preview(
                        target=entry,
                        changes=preview_payload["changes"],
                        source=source,
                    )
                    _preview_apply_set_payload(
                        target=entry_intent,
                        set_payload=set_payload,
                        force=force,
                        source=source,
                        changes=preview_payload["changes"],
                        skipped=preview_payload["skipped"],
                        path_prefix="intent",
                    )

    scene_preview["changes"] = _sort_preview_rows(scene_preview["changes"])
    scene_preview["skipped"] = _sort_preview_rows(scene_preview["skipped"])

    object_rows = [preview_payload for _, preview_payload in object_targets]
    for row in object_rows:
        row["changes"] = _sort_preview_rows(row["changes"])
        row["skipped"] = _sort_preview_rows(row["skipped"])
    object_rows.sort(key=lambda row: _coerce_str(row.get("object_id")).strip())

    bed_rows = [preview_payload for _, preview_payload in bed_targets]
    for row in bed_rows:
        row["changes"] = _sort_preview_rows(row["changes"])
        row["skipped"] = _sort_preview_rows(row["skipped"])
    bed_rows.sort(key=lambda row: _coerce_str(row.get("bed_id")).strip())

    return {
        "scene_id": _coerce_str(preview_scene.get("scene_id")).strip(),
        "template_ids": ordered_template_ids,
        "force": bool(force),
        "scene": scene_preview,
        "objects": object_rows,
        "beds": bed_rows,
    }
