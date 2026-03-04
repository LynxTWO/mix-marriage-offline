from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


ISSUE_EVENT_LOG_INVALID_JSON = "ISSUE.EVENT_LOG.INVALID_JSON"
ISSUE_EVENT_LOG_NOT_OBJECT = "ISSUE.EVENT_LOG.NOT_OBJECT"
ISSUE_EVENT_LOG_SCHEMA_INVALID = "ISSUE.EVENT_LOG.SCHEMA_INVALID"


def _event_schema_path() -> Path:
    from mmo.resources import schemas_dir

    return schemas_dir() / "event.schema.json"


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _event_sort_key(event: dict[str, Any]) -> tuple[str, ...]:
    confidence = event.get("confidence")
    confidence_key = ""
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        confidence_key = f"{float(confidence):.12g}"
    return (
        str(event.get("event_id", "")),
        str(event.get("scope", "")),
        str(event.get("kind", "")),
        str(event.get("what", "")),
        str(event.get("why", "")),
        _canonical_json(event.get("where", [])),
        confidence_key,
        _canonical_json(event.get("evidence", {})),
        str(event.get("ts_utc", "")),
    )


def new_event_id(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Event payload must be an object.")

    canonical_payload = dict(payload)
    canonical_payload.pop("event_id", None)
    digest = hashlib.sha256(_canonical_json(canonical_payload).encode("utf-8")).hexdigest()
    return f"EVT.{digest[:12]}"


def _build_event_validator() -> Any:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate event logs.")

    from mmo.core.schema_registry import (  # noqa: WPS433
        build_draft202012_validator,
        build_schema_registry,
        load_json_schema,
    )

    schema_path = _event_schema_path()
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    return build_draft202012_validator(
        schema,
        registry=registry,
        schemas_dir=schema_path.parent,
    )


def _error_path(error: Any) -> str:
    return ".".join(str(item) for item in error.path) or "$"


def _validate_event_schema(payload: dict[str, Any]) -> None:
    validator = _build_event_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for error in errors:
        path = _error_path(error)
        lines.append(f"- {path}: {error.message}")
    raise ValueError("Event schema validation failed:\n" + "\n".join(lines))


def _event_log_issue_sort_key(issue: dict[str, Any]) -> tuple[int, str, str]:
    line = issue.get("line")
    line_no = line if isinstance(line, int) else 0
    issue_id = issue.get("issue_id")
    issue_id_text = issue_id if isinstance(issue_id, str) else ""
    message = issue.get("message")
    message_text = message if isinstance(message, str) else ""
    return (line_no, issue_id_text, message_text)


def validate_event_log_jsonl(path: Path) -> dict[str, Any]:
    target_path = Path(path)
    try:
        lines = target_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(
            f"Failed to read event log JSONL from {target_path.as_posix()}: {exc}"
        ) from exc

    validator = _build_event_validator()
    issues: list[dict[str, Any]] = []
    non_empty_lines = 0
    valid_events = 0

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        non_empty_lines += 1

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            issues.append(
                {
                    "line": line_no,
                    "issue_id": ISSUE_EVENT_LOG_INVALID_JSON,
                    "message": "Line is not valid JSON.",
                }
            )
            continue

        if not isinstance(payload, dict):
            issues.append(
                {
                    "line": line_no,
                    "issue_id": ISSUE_EVENT_LOG_NOT_OBJECT,
                    "message": "Line JSON value must be an object.",
                }
            )
            continue

        errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
        if errors:
            for error in errors:
                issues.append(
                    {
                        "line": line_no,
                        "issue_id": ISSUE_EVENT_LOG_SCHEMA_INVALID,
                        "message": (
                            f"Schema violation at {_error_path(error)} "
                            f"(rule: {error.validator})."
                        ),
                    }
                )
            continue

        valid_events += 1

    sorted_issues = sorted(issues, key=_event_log_issue_sort_key)
    return {
        "ok": not sorted_issues,
        "in_path": target_path.resolve().as_posix(),
        "issues": sorted_issues,
        "summary": {
            "lines_total": len(lines),
            "lines_non_empty": non_empty_lines,
            "valid_events": valid_events,
            "invalid_events": len(sorted_issues),
        },
    }


def write_event_log(events: Iterable[dict[str, Any]], out_path: Path, *, force: bool) -> None:
    target_path = Path(out_path)
    if target_path.exists() and not force:
        raise ValueError(f"File exists (use --force to overwrite): {target_path.as_posix()}")

    normalized_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"events[{index}] must be an object.")
        normalized = json.loads(_canonical_json(event))
        if not isinstance(normalized, dict):
            raise ValueError(f"events[{index}] must be an object.")
        _validate_event_schema(normalized)
        normalized_events.append(normalized)

    ordered_events = sorted(normalized_events, key=_event_sort_key)
    lines = [_canonical_json(event) for event in ordered_events]
    payload = "\n".join(lines)
    if payload:
        payload += "\n"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(payload, encoding="utf-8")
