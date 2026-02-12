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

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

STEMS_OVERRIDES_VERSION = "0.1.0"
UNKNOWN_ROLE_ID = "ROLE.OTHER.UNKNOWN"


@dataclass(frozen=True)
class _CompiledOverride:
    override_id: str
    role_id: str
    rel_path: str | None
    regex: str | None
    compiled_regex: re.Pattern[str] | None
    note: str | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load stems overrides.")
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
        raise RuntimeError("jsonschema is required to validate stems overrides.")

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: (list(err.path), err.message),
    )
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _overrides_rows(overrides: Any) -> list[dict[str, Any]]:
    if isinstance(overrides, dict):
        rows = overrides.get("overrides")
    else:
        rows = overrides
    if not isinstance(rows, list):
        raise ValueError("Stems overrides must include an overrides list.")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"Override entry at index {idx} must be an object.")
        normalized.append(dict(item))
    return normalized


def _extract_match(entry: dict[str, Any], *, override_id: str) -> tuple[str | None, str | None]:
    match = entry.get("match")
    if not isinstance(match, dict):
        raise ValueError(f"Override {override_id} must include a match object.")

    rel_path = match.get("rel_path")
    regex = match.get("regex")
    has_rel_path = isinstance(rel_path, str) and bool(rel_path.strip())
    has_regex = isinstance(regex, str) and bool(regex.strip())
    if has_rel_path == has_regex:
        raise ValueError(
            f"Override {override_id} must include exactly one of match.rel_path or match.regex."
        )
    if has_rel_path:
        return rel_path.strip().replace("\\", "/"), None
    return None, regex.strip()  # type: ignore[arg-type]


def _compile_overrides(
    rows: list[dict[str, Any]],
    *,
    enforce_sorted_order: bool,
    source_label: str,
) -> list[_CompiledOverride]:
    override_ids: list[str] = []
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    invalid_patterns: list[str] = []
    compiled: list[_CompiledOverride] = []

    for idx, entry in enumerate(rows):
        override_id = entry.get("override_id")
        role_id = entry.get("role_id")
        if not isinstance(override_id, str) or not override_id.strip():
            raise ValueError(f"Override entry at index {idx} must include a non-empty override_id.")
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError(f"Override {override_id} must include a non-empty role_id.")

        normalized_override_id = override_id.strip()
        override_ids.append(normalized_override_id)
        if normalized_override_id in seen_ids:
            duplicate_ids.add(normalized_override_id)
        seen_ids.add(normalized_override_id)

        rel_path, regex = _extract_match(entry, override_id=normalized_override_id)
        compiled_regex: re.Pattern[str] | None = None
        if isinstance(regex, str):
            try:
                compiled_regex = re.compile(regex)
            except re.error:
                invalid_patterns.append(f"{normalized_override_id}: {regex}")

        note_value = entry.get("note")
        note = note_value.strip() if isinstance(note_value, str) and note_value.strip() else None
        compiled.append(
            _CompiledOverride(
                override_id=normalized_override_id,
                role_id=role_id.strip(),
                rel_path=rel_path,
                regex=regex,
                compiled_regex=compiled_regex,
                note=note,
            )
        )

    if duplicate_ids:
        raise ValueError(
            "Stems overrides override_id values must be unique: "
            + ", ".join(sorted(duplicate_ids))
        )
    if enforce_sorted_order and override_ids != sorted(override_ids):
        raise ValueError(f"Stems overrides must be sorted by override_id: {source_label}")
    if invalid_patterns:
        raise ValueError(
            "Stems overrides regex patterns failed to compile: "
            + ", ".join(sorted(invalid_patterns))
        )
    return sorted(compiled, key=lambda item: item.override_id)


def _sorted_counts(values: dict[str, int]) -> dict[str, int]:
    return {key: values[key] for key in sorted(values.keys())}


def _summary_for_assignments(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    counts_by_role: dict[str, int] = {}
    counts_by_bus_group: dict[str, int] = {}
    unknown_files = 0

    for assignment in assignments:
        role_id = assignment.get("role_id")
        if isinstance(role_id, str) and role_id:
            counts_by_role[role_id] = counts_by_role.get(role_id, 0) + 1
            if role_id == UNKNOWN_ROLE_ID:
                unknown_files += 1

        bus_group = assignment.get("bus_group")
        if isinstance(bus_group, str) and bus_group:
            counts_by_bus_group[bus_group] = counts_by_bus_group.get(bus_group, 0) + 1

    return {
        "counts_by_role": _sorted_counts(counts_by_role),
        "counts_by_bus_group": _sorted_counts(counts_by_bus_group),
        "unknown_files": unknown_files,
    }


def _override_reasons(existing: Any, *, override_id: str) -> list[str]:
    reasons: list[str] = []
    if isinstance(existing, list):
        reasons = [
            item
            for item in existing
            if isinstance(item, str) and item and not item.startswith("override:")
        ]
    reasons.append(f"override:{override_id}")
    return reasons


def load_stems_overrides(path: Path) -> dict[str, Any]:
    payload = _load_yaml_object(path, label="Stems overrides")
    _validate_payload_against_schema(
        payload,
        schema_path=_repo_root() / "schemas" / "stems_overrides.schema.json",
        payload_name="Stems overrides",
    )
    rows = _overrides_rows(payload)
    compiled = _compile_overrides(
        rows,
        enforce_sorted_order=True,
        source_label=str(path),
    )

    normalized_overrides: list[dict[str, Any]] = []
    for item in compiled:
        row: dict[str, Any] = {
            "override_id": item.override_id,
            "match": (
                {"rel_path": item.rel_path}
                if item.rel_path is not None
                else {"regex": item.regex}
            ),
            "role_id": item.role_id,
        }
        if item.note is not None:
            row["note"] = item.note
        normalized_overrides.append(row)

    return {
        "version": STEMS_OVERRIDES_VERSION,
        "overrides": normalized_overrides,
    }


def apply_overrides(
    stems_map: dict[str, Any],
    overrides: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(stems_map, dict):
        raise ValueError("Stems map payload must be an object.")
    assignments_value = stems_map.get("assignments")
    if not isinstance(assignments_value, list):
        raise ValueError("Stems map payload must include an assignments list.")

    compiled_overrides = _compile_overrides(
        _overrides_rows(overrides),
        enforce_sorted_order=False,
        source_label="overrides",
    )

    patched_assignments: list[dict[str, Any]] = []
    for item in assignments_value:
        if not isinstance(item, dict):
            raise ValueError("Stems map assignments entries must be objects.")
        assignment = dict(item)

        rel_path = assignment.get("rel_path")
        normalized_rel_path = rel_path if isinstance(rel_path, str) else ""
        selected_override: _CompiledOverride | None = None

        for candidate in compiled_overrides:
            if candidate.rel_path is not None and normalized_rel_path == candidate.rel_path:
                selected_override = candidate
                break
            if (
                candidate.compiled_regex is not None
                and candidate.compiled_regex.search(normalized_rel_path)
            ):
                selected_override = candidate
                break

        if selected_override is None:
            patched_assignments.append(assignment)
            continue

        assignment["role_id"] = selected_override.role_id
        assignment["reasons"] = _override_reasons(
            assignment.get("reasons"),
            override_id=selected_override.override_id,
        )
        patched_assignments.append(assignment)

    patched_map = dict(stems_map)
    patched_map["assignments"] = patched_assignments

    summary = stems_map.get("summary")
    normalized_summary = dict(summary) if isinstance(summary, dict) else {}
    normalized_summary.update(_summary_for_assignments(patched_assignments))
    patched_map["summary"] = normalized_summary
    return patched_map
