from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


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


def _validate_event_schema(payload: dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate event logs.")

    from mmo.core.schema_registry import build_schema_registry, load_json_schema  # noqa: WPS433

    schema_path = _event_schema_path()
    schema = load_json_schema(schema_path)
    registry = build_schema_registry(schema_path.parent)
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    lines: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.path) or "$"
        lines.append(f"- {path}: {error.message}")
    raise ValueError("Event schema validation failed:\n" + "\n".join(lines))


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
