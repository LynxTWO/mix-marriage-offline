"""Deterministic plugin UI contract linting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

from mmo.core.pipeline import load_plugins
from mmo.core.ui_hints import (
    build_ui_hints_lint_payload,
    extract_ui_hints_rows,
)
from mmo.core.ui_layout import (
    build_ui_layout_snapshot,
    snapshot_has_violations,
)
from mmo.resources import schemas_dir

PLUGIN_UI_CONTRACT_SCHEMA_VERSION = "0.1.0"
_DEFAULT_SNAPSHOT_VIEWPORT_WIDTH_PX = 1280
_DEFAULT_SNAPSHOT_VIEWPORT_HEIGHT_PX = 720
_DEFAULT_SNAPSHOT_SCALE = 1.0
_CONFIG_SCHEMA_JSON_POINTER = "/config_schema"
_UI_LAYOUT_MANIFEST_FIELD = "ui_layout"
_HINT_POINTER_SUFFIX = "/x_mmo_ui"
_PARAM_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")

_ISSUE_LAYOUT_FIELD_INVALID = "ISSUE.UI.PLUGIN.LAYOUT_FIELD_INVALID"
_ISSUE_LAYOUT_LOAD_FAILED = "ISSUE.UI.PLUGIN.LAYOUT_LOAD_FAILED"
_ISSUE_LAYOUT_SCHEMA_INVALID = "ISSUE.UI.PLUGIN.LAYOUT_SCHEMA_INVALID"
_ISSUE_LAYOUT_SNAPSHOT_INVALID = "ISSUE.UI.PLUGIN.LAYOUT_SNAPSHOT_INVALID"
_ISSUE_LAYOUT_VIOLATION = "ISSUE.UI.PLUGIN.LAYOUT_VIOLATION"
_ISSUE_CONFIG_SCHEMA_REQUIRED = "ISSUE.UI.PLUGIN.CONFIG_SCHEMA_REQUIRED"
_ISSUE_CONFIG_SCHEMA_INVALID = "ISSUE.UI.PLUGIN.CONFIG_SCHEMA_INVALID"
_ISSUE_WIDGET_PARAM_REF_REQUIRED = "ISSUE.UI.PLUGIN.WIDGET_PARAM_REF_REQUIRED"
_ISSUE_WIDGET_PARAM_REF_UNKNOWN = "ISSUE.UI.PLUGIN.WIDGET_PARAM_REF_UNKNOWN"
_ISSUE_WIDGET_PARAM_REF_AMBIGUOUS = "ISSUE.UI.PLUGIN.WIDGET_PARAM_REF_AMBIGUOUS"
_ISSUE_HINT_SCHEMA_INVALID = "ISSUE.UI.PLUGIN.HINT_SCHEMA_INVALID"
_ISSUE_HINT_PARAM_REF_UNKNOWN = "ISSUE.UI.PLUGIN.HINT_PARAM_REF_UNKNOWN"
_ISSUE_LAYOUT_PARAM_HINT_MISSING = "ISSUE.UI.PLUGIN.LAYOUT_PARAM_HINT_MISSING"

_SEVERITY_RANK = {"error": 0, "warn": 1}


@dataclass(frozen=True)
class _ParameterRef:
    pointer: str
    name: str
    canonical_name: str


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _json_pointer_join(pointer: str, token: str) -> str:
    escaped = _escape_json_pointer_token(token)
    if pointer:
        return f"{pointer}/{escaped}"
    return f"/{escaped}"


def _normalize_param_token(value: str) -> str:
    collapsed = _PARAM_TOKEN_RE.sub("_", value).strip("_")
    return collapsed.upper()


def _issue(
    *,
    plugin_id: str,
    issue_id: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "plugin_id": plugin_id,
        "issue_id": issue_id,
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def _issue_sort_key(issue: dict[str, Any]) -> tuple[int, str, str, str, str]:
    severity = _coerce_str(issue.get("severity")).strip()
    return (
        _SEVERITY_RANK.get(severity, 99),
        _coerce_str(issue.get("plugin_id")).strip(),
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("message")).strip(),
        json.dumps(issue.get("evidence", {}), sort_keys=True, separators=(",", ":")),
    )


def _sorted_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=_issue_sort_key)


def _issue_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warn_count = sum(1 for issue in issues if issue.get("severity") == "warn")
    return {"error": error_count, "warn": warn_count}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path.as_posix()}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path.as_posix()}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path.as_posix()}")
    return payload


def _validate_json_payload(
    payload: dict[str, Any],
    *,
    schema_basename: str,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate plugin UI payloads.")

    from mmo.core.schema_registry import (  # noqa: WPS433
        build_draft202012_validator,
        build_schema_registry,
        load_json_schema,
    )

    schema_path = schemas_dir() / schema_basename
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    validator = build_draft202012_validator(
        schema,
        registry=registry,
        schemas_dir=schema_path.parent,
    )
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _validate_plugins_dir(plugins_dir: Path) -> Path:
    resolved_plugins_dir = plugins_dir.resolve()
    if not resolved_plugins_dir.exists():
        raise ValueError(
            f"Plugins directory does not exist: {resolved_plugins_dir.as_posix()}"
        )
    if not resolved_plugins_dir.is_dir():
        raise ValueError(
            f"Plugins path is not a directory: {resolved_plugins_dir.as_posix()}"
        )
    return resolved_plugins_dir


def _resolve_manifest_relative_file(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    field_name: str,
) -> Path | None:
    raw_value = manifest.get(field_name)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError(
            f"Manifest field '{field_name}' must be a string: {manifest_path.as_posix()}"
        )
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError(
            (
                f"Manifest field '{field_name}' must be a non-empty relative path: "
                f"{manifest_path.as_posix()}"
            )
        )
    candidate_rel = Path(normalized)
    if candidate_rel.is_absolute():
        raise ValueError(
            (
                f"Manifest field '{field_name}' must be a relative path: "
                f"{manifest_path.as_posix()}"
            )
        )

    plugin_dir = manifest_path.resolve().parent
    candidate = (plugin_dir / candidate_rel).resolve()
    # UI contract files stay inside the plugin directory so a manifest cannot
    # lint or snapshot arbitrary local files.
    try:
        candidate.relative_to(plugin_dir)
    except ValueError as exc:
        raise ValueError(
            (
                f"Manifest field '{field_name}' must resolve inside the plugin directory: "
                f"{manifest_path.as_posix()}"
            )
        ) from exc
    if not candidate.exists():
        raise ValueError(
            (
                f"Manifest field '{field_name}' references a missing file: "
                f"{candidate.as_posix()}"
            )
        )
    if not candidate.is_file():
        raise ValueError(
            (
                f"Manifest field '{field_name}' must reference a file: "
                f"{candidate.as_posix()}"
            )
        )
    return candidate


def _collect_parameter_rows(
    value: Any,
    *,
    pointer: str,
    rows: list[_ParameterRef],
) -> None:
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            properties_pointer = _json_pointer_join(pointer, "properties")
            for property_name in sorted(properties.keys()):
                property_schema = properties.get(property_name)
                if (
                    not isinstance(property_name, str)
                    or not property_name
                    or not isinstance(property_schema, dict)
                ):
                    continue
                property_pointer = _json_pointer_join(properties_pointer, property_name)
                rows.append(
                    _ParameterRef(
                        pointer=property_pointer,
                        name=property_name,
                        canonical_name=_normalize_param_token(property_name),
                    )
                )
                _collect_parameter_rows(
                    property_schema,
                    pointer=property_pointer,
                    rows=rows,
                )

        for key in sorted(value.keys()):
            if key == "properties":
                continue
            if not isinstance(key, str):
                continue
            child_pointer = _json_pointer_join(pointer, key)
            _collect_parameter_rows(
                value.get(key),
                pointer=child_pointer,
                rows=rows,
            )
        return

    if isinstance(value, list):
        for index, nested in enumerate(value):
            child_pointer = _json_pointer_join(pointer, str(index))
            _collect_parameter_rows(
                nested,
                pointer=child_pointer,
                rows=rows,
            )


def _parameter_sort_key(row: _ParameterRef) -> tuple[str, str]:
    return (row.pointer, row.name)


def _parameter_rows(config_schema: dict[str, Any]) -> list[_ParameterRef]:
    rows: list[_ParameterRef] = []
    _collect_parameter_rows(config_schema, pointer="", rows=rows)
    rows.sort(key=_parameter_sort_key)
    return rows


@dataclass(frozen=True)
class _ParameterIndex:
    by_pointer: dict[str, _ParameterRef]
    by_name_lower: dict[str, list[_ParameterRef]]
    by_canonical: dict[str, list[_ParameterRef]]


def _build_parameter_index(rows: list[_ParameterRef]) -> _ParameterIndex:
    by_pointer: dict[str, _ParameterRef] = {}
    by_name_lower: dict[str, list[_ParameterRef]] = {}
    by_canonical: dict[str, list[_ParameterRef]] = {}
    for row in rows:
        by_pointer[row.pointer] = row
        name_key = row.name.lower()
        by_name_lower.setdefault(name_key, []).append(row)
        by_canonical.setdefault(row.canonical_name, []).append(row)
    return _ParameterIndex(
        by_pointer=by_pointer,
        by_name_lower=by_name_lower,
        by_canonical=by_canonical,
    )


def _resolve_param_ref(
    param_ref: str,
    *,
    index: _ParameterIndex,
) -> tuple[_ParameterRef | None, str]:
    normalized = param_ref.strip()
    if not normalized:
        return None, "missing"

    if normalized.startswith("/"):
        resolved = index.by_pointer.get(normalized)
        return (resolved, "ok" if resolved is not None else "missing")

    # Accept exact names first, then canonicalized tail tokens, so copied
    # layouts remain readable without making ambiguous shortcuts succeed.
    by_name = index.by_name_lower.get(normalized.lower(), [])
    if len(by_name) == 1:
        return by_name[0], "ok"
    if len(by_name) > 1:
        return None, "ambiguous"

    tail_token = normalized.split(".")[-1]
    canonical = _normalize_param_token(tail_token)
    if not canonical:
        return None, "missing"
    by_canonical = index.by_canonical.get(canonical, [])
    if len(by_canonical) == 1:
        return by_canonical[0], "ok"
    if len(by_canonical) > 1:
        return None, "ambiguous"
    return None, "missing"


def _hint_param_pointer(hint_pointer: str) -> str | None:
    if not hint_pointer.endswith(_HINT_POINTER_SUFFIX):
        return None
    return hint_pointer[: -len(_HINT_POINTER_SUFFIX)]


def _lint_plugin(plugin: Any) -> dict[str, Any]:
    plugin_id = _coerce_str(getattr(plugin, "plugin_id", "")).strip()
    plugin_type = _coerce_str(getattr(plugin, "plugin_type", "")).strip()
    version = _coerce_str(getattr(plugin, "version", "")).strip()
    manifest_path = getattr(plugin, "manifest_path", Path(""))
    resolved_manifest_path = manifest_path.resolve()
    manifest = plugin.manifest if isinstance(getattr(plugin, "manifest", None), dict) else {}

    issues: list[dict[str, Any]] = []
    # Keep collecting issues for one plugin so authors can fix schema, hint, and
    # layout drift in one pass instead of chasing one failure at a time.
    config_schema = manifest.get("config_schema")
    has_config_schema = isinstance(config_schema, dict)
    if "config_schema" in manifest and config_schema is not None and not has_config_schema:
        issues.append(
            _issue(
                plugin_id=plugin_id,
                issue_id=_ISSUE_CONFIG_SCHEMA_INVALID,
                severity="error",
                message="Manifest config_schema must be an object when present.",
                evidence={"manifest_path": _path_to_posix(resolved_manifest_path)},
            )
        )

    parameter_rows = _parameter_rows(config_schema) if has_config_schema else []
    parameter_index = _build_parameter_index(parameter_rows)

    hint_rows = extract_ui_hints_rows(config_schema) if has_config_schema else []
    hint_param_pointers: set[str] = set()
    if has_config_schema:
        hint_lint_payload = build_ui_hints_lint_payload(
            config_schema=config_schema,
            schema_path=resolved_manifest_path,
        )
        for row in hint_lint_payload.get("errors", []):
            if not isinstance(row, dict):
                continue
            hint_pointer = _coerce_str(row.get("json_pointer")).strip()
            hint_path = _coerce_str(row.get("path")).strip()
            message = _coerce_str(row.get("message")).strip()
            if not message:
                continue
            pointer_with_path = hint_pointer if hint_path == "/" else f"{hint_pointer}{hint_path}"
            issues.append(
                _issue(
                    plugin_id=plugin_id,
                    issue_id=_ISSUE_HINT_SCHEMA_INVALID,
                    severity="error",
                    message=f"UI hint schema invalid at '{pointer_with_path}': {message}",
                    evidence={
                        "manifest_path": _path_to_posix(resolved_manifest_path),
                        "json_pointer": hint_pointer,
                        "path": hint_path,
                    },
                )
            )

        for row in hint_rows:
            if not isinstance(row, dict):
                continue
            hint_pointer = _coerce_str(row.get("json_pointer")).strip()
            if not hint_pointer:
                continue
            param_pointer = _hint_param_pointer(hint_pointer)
            if not param_pointer or param_pointer not in parameter_index.by_pointer:
                issues.append(
                    _issue(
                        plugin_id=plugin_id,
                        issue_id=_ISSUE_HINT_PARAM_REF_UNKNOWN,
                        severity="error",
                        message=(
                            f"UI hint '{hint_pointer}' does not reference a known "
                            "config parameter."
                        ),
                        evidence={
                            "manifest_path": _path_to_posix(resolved_manifest_path),
                            "json_pointer": hint_pointer,
                        },
                    )
                )
                continue
            hint_param_pointers.add(param_pointer)

    layout_path: Path | None = None
    try:
        layout_path = _resolve_manifest_relative_file(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
            field_name=_UI_LAYOUT_MANIFEST_FIELD,
        )
    except ValueError as exc:
        issues.append(
            _issue(
                plugin_id=plugin_id,
                issue_id=_ISSUE_LAYOUT_FIELD_INVALID,
                severity="error",
                message=str(exc),
                evidence={"manifest_path": _path_to_posix(resolved_manifest_path)},
            )
        )

    layout_param_pointers: set[str] = set()
    layout_snapshot_violations = 0
    if layout_path is not None:
        if not has_config_schema:
            issues.append(
                _issue(
                    plugin_id=plugin_id,
                    issue_id=_ISSUE_CONFIG_SCHEMA_REQUIRED,
                    severity="error",
                    message=(
                        "ui_layout requires manifest config_schema to resolve widget "
                        "parameter references."
                    ),
                    evidence={
                        "manifest_path": _path_to_posix(resolved_manifest_path),
                        "layout_path": _path_to_posix(layout_path),
                        "config_schema_pointer": _CONFIG_SCHEMA_JSON_POINTER,
                    },
                )
            )

        try:
            layout_payload = _load_json_object(layout_path, label="UI layout")
        except ValueError as exc:
            issues.append(
                _issue(
                    plugin_id=plugin_id,
                    issue_id=_ISSUE_LAYOUT_LOAD_FAILED,
                    severity="error",
                    message=str(exc),
                    evidence={
                        "manifest_path": _path_to_posix(resolved_manifest_path),
                        "layout_path": _path_to_posix(layout_path),
                    },
                )
            )
        else:
            try:
                _validate_json_payload(
                    layout_payload,
                    schema_basename="ui_layout.schema.json",
                    payload_name="UI layout",
                )
            except ValueError as exc:
                issues.append(
                    _issue(
                        plugin_id=plugin_id,
                        issue_id=_ISSUE_LAYOUT_SCHEMA_INVALID,
                        severity="error",
                        message=str(exc),
                        evidence={
                            "manifest_path": _path_to_posix(resolved_manifest_path),
                            "layout_path": _path_to_posix(layout_path),
                        },
                    )
                )
            else:
                snapshot_payload = build_ui_layout_snapshot(
                    layout_payload,
                    layout_path=layout_path,
                    viewport_width_px=_DEFAULT_SNAPSHOT_VIEWPORT_WIDTH_PX,
                    viewport_height_px=_DEFAULT_SNAPSHOT_VIEWPORT_HEIGHT_PX,
                    scale=_DEFAULT_SNAPSHOT_SCALE,
                )
                try:
                    _validate_json_payload(
                        snapshot_payload,
                        schema_basename="ui_layout_snapshot.schema.json",
                        payload_name="UI layout snapshot",
                    )
                except ValueError as exc:
                    issues.append(
                        _issue(
                            plugin_id=plugin_id,
                            issue_id=_ISSUE_LAYOUT_SNAPSHOT_INVALID,
                            severity="error",
                            message=str(exc),
                            evidence={
                                "manifest_path": _path_to_posix(resolved_manifest_path),
                                "layout_path": _path_to_posix(layout_path),
                            },
                        )
                    )
                else:
                    violations = snapshot_payload.get("violations")
                    if isinstance(violations, list):
                        layout_snapshot_violations = len(violations)
                    if snapshot_has_violations(snapshot_payload):
                        for violation in snapshot_payload.get("violations", []):
                            if not isinstance(violation, dict):
                                continue
                            issues.append(
                                _issue(
                                    plugin_id=plugin_id,
                                    issue_id=_ISSUE_LAYOUT_VIOLATION,
                                    severity="error",
                                    message=_coerce_str(violation.get("message")).strip()
                                    or "ui_layout snapshot reported a violation.",
                                    evidence={
                                        "manifest_path": _path_to_posix(
                                            resolved_manifest_path
                                        ),
                                        "layout_path": _path_to_posix(layout_path),
                                        "issue_id": _coerce_str(
                                            violation.get("issue_id")
                                        ).strip(),
                                        "severity": _coerce_str(
                                            violation.get("severity")
                                        ).strip(),
                                        "violation_evidence": violation.get(
                                            "evidence", {}
                                        ),
                                    },
                                )
                            )

                    for widget in snapshot_payload.get("widgets", []):
                        if not isinstance(widget, dict):
                            continue
                        widget_id = _coerce_str(widget.get("widget_id")).strip()
                        param_ref = widget.get("param_ref")
                        normalized_param_ref = (
                            param_ref.strip()
                            if isinstance(param_ref, str) and param_ref.strip()
                            else ""
                        )
                        if not normalized_param_ref:
                            issues.append(
                                _issue(
                                    plugin_id=plugin_id,
                                    issue_id=_ISSUE_WIDGET_PARAM_REF_REQUIRED,
                                    severity="error",
                                    message=(
                                        f"Widget '{widget_id}' must declare a non-empty "
                                        "param_ref."
                                    ),
                                    evidence={
                                        "manifest_path": _path_to_posix(
                                            resolved_manifest_path
                                        ),
                                        "layout_path": _path_to_posix(layout_path),
                                        "widget_id": widget_id,
                                    },
                                )
                            )
                            continue
                        if not has_config_schema:
                            continue
                        resolved_param, status = _resolve_param_ref(
                            normalized_param_ref,
                            index=parameter_index,
                        )
                        if status == "ok" and resolved_param is not None:
                            layout_param_pointers.add(resolved_param.pointer)
                            continue
                        if status == "ambiguous":
                            issues.append(
                                _issue(
                                    plugin_id=plugin_id,
                                    issue_id=_ISSUE_WIDGET_PARAM_REF_AMBIGUOUS,
                                    severity="error",
                                    message=(
                                        f"Widget '{widget_id}' param_ref "
                                        f"'{normalized_param_ref}' is ambiguous."
                                    ),
                                    evidence={
                                        "manifest_path": _path_to_posix(
                                            resolved_manifest_path
                                        ),
                                        "layout_path": _path_to_posix(layout_path),
                                        "widget_id": widget_id,
                                        "param_ref": normalized_param_ref,
                                    },
                                )
                            )
                            continue
                        issues.append(
                            _issue(
                                plugin_id=plugin_id,
                                issue_id=_ISSUE_WIDGET_PARAM_REF_UNKNOWN,
                                severity="error",
                                message=(
                                    f"Widget '{widget_id}' param_ref "
                                    f"'{normalized_param_ref}' does not match any "
                                    "config parameter."
                                ),
                                evidence={
                                    "manifest_path": _path_to_posix(resolved_manifest_path),
                                    "layout_path": _path_to_posix(layout_path),
                                    "widget_id": widget_id,
                                    "param_ref": normalized_param_ref,
                                },
                            )
                        )

    if has_config_schema and layout_param_pointers:
        missing_hints = sorted(layout_param_pointers - hint_param_pointers)
        for param_pointer in missing_hints:
            param_row = parameter_index.by_pointer.get(param_pointer)
            param_name = param_row.name if param_row is not None else ""
            # Missing hints are warnings rather than hard errors because the
            # layout can still render, but the UI loses schema-backed display
            # metadata that authors are expected to provide.
            issues.append(
                _issue(
                    plugin_id=plugin_id,
                    issue_id=_ISSUE_LAYOUT_PARAM_HINT_MISSING,
                    severity="warn",
                    message=(
                        f"Layout parameter '{param_name or param_pointer}' has no "
                        "x_mmo_ui widget hint."
                    ),
                    evidence={
                        "manifest_path": _path_to_posix(resolved_manifest_path),
                        "param_pointer": param_pointer,
                        "param_name": param_name,
                    },
                )
            )

    plugin_issues = _sorted_issues(issues)
    return {
        "plugin_id": plugin_id,
        "plugin_type": plugin_type,
        "version": version,
        "manifest_path": _path_to_posix(resolved_manifest_path),
        "config_schema": {
            "present": has_config_schema,
            "pointer": _CONFIG_SCHEMA_JSON_POINTER,
            "parameter_count": len(parameter_rows),
        },
        "ui_layout": {
            "present": layout_path is not None,
            "path": _path_to_posix(layout_path) if layout_path is not None else None,
            "snapshot_violations": layout_snapshot_violations,
        },
        "ui_hints": {
            "hint_count": len(hint_rows),
        },
        "issue_counts": _issue_counts(plugin_issues),
        "issues": plugin_issues,
    }


def build_plugin_ui_contract_lint_payload(*, plugins_dir: Path) -> dict[str, Any]:
    resolved_plugins_dir = _validate_plugins_dir(plugins_dir)
    plugin_rows = [_lint_plugin(plugin) for plugin in load_plugins(resolved_plugins_dir)]
    # Stable plugin ordering keeps lint snapshots diffable across runs and roots.
    plugin_rows.sort(
        key=lambda row: (
            _coerce_str(row.get("plugin_id")).strip(),
            _coerce_str(row.get("plugin_type")).strip(),
            _coerce_str(row.get("version")).strip(),
            _coerce_str(row.get("manifest_path")).strip(),
        )
    )

    issues: list[dict[str, Any]] = []
    for row in plugin_rows:
        plugin_issues = row.get("issues")
        if isinstance(plugin_issues, list):
            issues.extend(item for item in plugin_issues if isinstance(item, dict))
    sorted_issues = _sorted_issues(issues)
    issue_counts = _issue_counts(sorted_issues)
    return {
        "schema_version": PLUGIN_UI_CONTRACT_SCHEMA_VERSION,
        "plugins_dir": _path_to_posix(resolved_plugins_dir),
        "plugin_count": len(plugin_rows),
        "issue_counts": issue_counts,
        "ok": issue_counts["error"] == 0,
        "plugins": plugin_rows,
        "issues": sorted_issues,
    }


def plugin_ui_contract_has_errors(payload: dict[str, Any]) -> bool:
    issue_counts = payload.get("issue_counts")
    if not isinstance(issue_counts, dict):
        return False
    error_count = issue_counts.get("error")
    return isinstance(error_count, int) and error_count > 0


__all__ = [
    "PLUGIN_UI_CONTRACT_SCHEMA_VERSION",
    "build_plugin_ui_contract_lint_payload",
    "plugin_ui_contract_has_errors",
]
