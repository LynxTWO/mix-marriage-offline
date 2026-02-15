from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.resources import data_root, ontology_dir, schemas_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

INTENT_PARAMS_SCHEMA_VERSION = "0.1.0"
ISSUE_SCENE_INTENT_PARAM_UNKNOWN = "ISSUE.VALIDATION.SCENE_INTENT_PARAM_UNKNOWN"
ISSUE_SCENE_INTENT_PARAM_TYPE_INVALID = (
    "ISSUE.VALIDATION.SCENE_INTENT_PARAM_TYPE_INVALID"
)
ISSUE_SCENE_INTENT_PARAM_OUT_OF_RANGE = (
    "ISSUE.VALIDATION.SCENE_INTENT_PARAM_OUT_OF_RANGE"
)
ISSUE_SCENE_INTENT_ENUM_INVALID = "ISSUE.VALIDATION.SCENE_INTENT_ENUM_INVALID"

_ADVISORY_SEVERITY = 40
_OBJECT_PARAM_MAP = {
    "width": "INTENT.WIDTH",
    "depth": "INTENT.DEPTH",
    "loudness_bias": "INTENT.LOUDNESS_BIAS",
    "confidence": "INTENT.CONFIDENCE",
}
_BED_PARAM_MAP = {
    "confidence": "INTENT.CONFIDENCE",
}


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "intent_params.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load intent parameter registries.")
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
        raise RuntimeError("jsonschema is required to validate intent parameter registries.")

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


def _params_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    params = payload.get("params")
    if not isinstance(params, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for param_id in sorted(params.keys()):
        raw_param = params.get(param_id)
        if not isinstance(param_id, str) or not isinstance(raw_param, dict):
            continue
        normalized[param_id] = dict(raw_param)
    return normalized


def load_intent_params(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="Intent params registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "intent_params.schema.json",
        payload_name="Intent params registry",
    )
    return {
        "schema_version": payload.get("schema_version"),
        "params": _params_map(payload),
    }


def _entry_id(entry: dict[str, Any], *, id_key: str, prefix: str, index: int) -> str:
    value = entry.get(id_key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"{prefix}.{index:03d}"


def _entry_target(scope: str, entry_id: str, param_id: str) -> dict[str, Any]:
    target: dict[str, Any] = {"scope": scope, "param_id": param_id}
    if scope == "object":
        target["object_id"] = entry_id
    elif scope == "bed":
        target["bed_id"] = entry_id
    return target


def _issue(
    *,
    issue_id: str,
    scope: str,
    entry_id: str,
    param_id: str,
    message: str,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": _ADVISORY_SEVERITY,
        "confidence": 1.0,
        "target": _entry_target(scope, entry_id, param_id),
        "message": message,
    }


def _validate_number_param(
    value: Any,
    *,
    param_id: str,
    param_spec: dict[str, Any],
    scope: str,
    entry_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(
            _issue(
                issue_id=ISSUE_SCENE_INTENT_PARAM_TYPE_INVALID,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=f"Scene intent value for {param_id} must be a number.",
            )
        )
        return issues

    numeric_value = float(value)
    min_value = param_spec.get("min")
    max_value = param_spec.get("max")
    if isinstance(min_value, (int, float)) and numeric_value < float(min_value):
        issues.append(
            _issue(
                issue_id=ISSUE_SCENE_INTENT_PARAM_OUT_OF_RANGE,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=(
                    f"Scene intent value for {param_id} is below minimum "
                    f"{float(min_value)}: {numeric_value}."
                ),
            )
        )
        return issues

    if isinstance(max_value, (int, float)) and numeric_value > float(max_value):
        issues.append(
            _issue(
                issue_id=ISSUE_SCENE_INTENT_PARAM_OUT_OF_RANGE,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=(
                    f"Scene intent value for {param_id} exceeds maximum "
                    f"{float(max_value)}: {numeric_value}."
                ),
            )
        )
    return issues


def _validate_enum_param(
    value: Any,
    *,
    param_id: str,
    param_spec: dict[str, Any],
    scope: str,
    entry_id: str,
) -> list[dict[str, Any]]:
    allowed_values = param_spec.get("values")
    if not isinstance(allowed_values, list):
        return [
            _issue(
                issue_id=ISSUE_SCENE_INTENT_PARAM_UNKNOWN,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=f"Intent parameter {param_id} is missing enum values.",
            )
        ]

    normalized_values = [
        item for item in allowed_values if isinstance(item, str) and item
    ]
    if not isinstance(value, str) or value not in normalized_values:
        allowed_label = ", ".join(normalized_values)
        return [
            _issue(
                issue_id=ISSUE_SCENE_INTENT_ENUM_INVALID,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=(
                    f"Scene intent value for {param_id} must be one of "
                    f"[{allowed_label}]."
                ),
            )
        ]
    return []


def _validate_param_value(
    *,
    value: Any,
    scope: str,
    entry_id: str,
    param_id: str,
    intent_params: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    param_spec = intent_params.get(param_id)
    if not isinstance(param_spec, dict):
        return [
            _issue(
                issue_id=ISSUE_SCENE_INTENT_PARAM_UNKNOWN,
                scope=scope,
                entry_id=entry_id,
                param_id=param_id,
                message=f"Scene intent parameter is not defined in registry: {param_id}.",
            )
        ]

    param_type = param_spec.get("type")
    if param_type == "number":
        return _validate_number_param(
            value,
            param_id=param_id,
            param_spec=param_spec,
            scope=scope,
            entry_id=entry_id,
        )
    if param_type == "enum":
        return _validate_enum_param(
            value,
            param_id=param_id,
            param_spec=param_spec,
            scope=scope,
            entry_id=entry_id,
        )
    return [
        _issue(
            issue_id=ISSUE_SCENE_INTENT_PARAM_UNKNOWN,
            scope=scope,
            entry_id=entry_id,
            param_id=param_id,
            message=f"Scene intent parameter {param_id} has unsupported type {param_type!r}.",
        )
    ]


def _collect_intent_issues_for_entries(
    entries: Any,
    *,
    scope: str,
    id_key: str,
    base_param_map: dict[str, str],
    intent_params: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    issues: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        intent = entry.get("intent")
        if not isinstance(intent, dict):
            continue
        entry_id = _entry_id(entry, id_key=id_key, prefix=scope.upper(), index=index)

        for field, param_id in base_param_map.items():
            if field in intent:
                issues.extend(
                    _validate_param_value(
                        value=intent.get(field),
                        scope=scope,
                        entry_id=entry_id,
                        param_id=param_id,
                        intent_params=intent_params,
                    )
                )

        position = intent.get("position")
        if isinstance(position, dict) and "azimuth_deg" in position:
            issues.extend(
                _validate_param_value(
                    value=position.get("azimuth_deg"),
                    scope=scope,
                    entry_id=entry_id,
                    param_id="INTENT.POSITION.AZIMUTH_DEG",
                    intent_params=intent_params,
                )
            )

    return issues


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    target = issue.get("target")
    target_map = target if isinstance(target, dict) else {}
    return (
        str(issue.get("issue_id", "")),
        str(target_map.get("scope", "")),
        str(target_map.get("object_id", "")),
        str(target_map.get("bed_id", "")),
        str(target_map.get("param_id", "")),
        str(issue.get("message", "")),
    )


def validate_scene_intent(
    scene: dict[str, Any],
    intent_params: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object.")
    if not isinstance(intent_params, dict):
        raise ValueError("intent_params must be an object.")

    params = intent_params.get("params")
    if not isinstance(params, dict):
        raise ValueError("intent_params.params must be an object.")

    normalized_params = {
        param_id: dict(param_spec)
        for param_id, param_spec in params.items()
        if isinstance(param_id, str) and isinstance(param_spec, dict)
    }

    issues = _collect_intent_issues_for_entries(
        scene.get("objects"),
        scope="object",
        id_key="object_id",
        base_param_map=_OBJECT_PARAM_MAP,
        intent_params=normalized_params,
    )
    issues.extend(
        _collect_intent_issues_for_entries(
            scene.get("beds"),
            scope="bed",
            id_key="bed_id",
            base_param_map=_BED_PARAM_MAP,
            intent_params=normalized_params,
        )
    )
    issues.sort(key=_issue_sort_key)
    return issues
