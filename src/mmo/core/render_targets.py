from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.core.speaker_positions import load_speaker_positions
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


def _speaker_positions_layouts() -> dict[str, dict[str, Any]]:
    registry_path = _repo_root() / "ontology" / "speaker_positions.yaml"
    try:
        registry = load_speaker_positions(registry_path)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(
            f"Failed to load speaker positions from {registry_path}: {exc}"
        ) from exc
    layouts = registry.get("layouts")
    if not isinstance(layouts, dict):
        return {}
    return {
        layout_id: dict(layout)
        for layout_id, layout in layouts.items()
        if isinstance(layout_id, str) and isinstance(layout, dict)
    }


def _normalize_speaker_positions(
    positions: list[dict[str, Any]],
    *,
    target_id: str,
    path: Path,
) -> list[dict[str, Any]]:
    channels: list[int] = []
    normalized: list[dict[str, Any]] = []
    for position in positions:
        ch = position.get("ch")
        azimuth_deg = position.get("azimuth_deg")
        elevation_deg = position.get("elevation_deg")
        if (
            isinstance(ch, bool)
            or not isinstance(ch, int)
            or isinstance(azimuth_deg, bool)
            or not isinstance(azimuth_deg, (int, float))
            or isinstance(elevation_deg, bool)
            or not isinstance(elevation_deg, (int, float))
        ):
            continue
        channels.append(ch)
        normalized.append(
            {
                "ch": ch,
                "azimuth_deg": float(azimuth_deg),
                "elevation_deg": float(elevation_deg),
            }
        )

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

    normalized.sort(key=lambda item: int(item["ch"]))
    return normalized


def _resolve_target_speaker_positions(
    target: dict[str, Any],
    *,
    speaker_layouts: dict[str, dict[str, Any]],
    path: Path,
) -> list[dict[str, Any]]:
    target_id = target.get("target_id")
    layout_id = target.get("layout_id")
    normalized_target_id = target_id if isinstance(target_id, str) else "<unknown>"
    normalized_layout_id = layout_id.strip() if isinstance(layout_id, str) else ""

    speaker_positions_ref = target.get("speaker_positions_ref")
    if isinstance(speaker_positions_ref, str) and speaker_positions_ref.strip():
        ref_layout_id = speaker_positions_ref.strip()
        if normalized_layout_id and ref_layout_id != normalized_layout_id:
            raise ValueError(
                "Render target speaker_positions_ref must match layout_id: "
                f"{normalized_target_id} ({path})"
            )

        ref_layout = speaker_layouts.get(ref_layout_id)
        if not isinstance(ref_layout, dict):
            raise ValueError(
                "Render target speaker_positions_ref is unknown: "
                f"{normalized_target_id} -> {ref_layout_id} ({path})"
            )

        channels = ref_layout.get("channels")
        if not isinstance(channels, list):
            raise ValueError(
                "Speaker positions registry entry must include channels: "
                f"{ref_layout_id} ({path})"
            )

        resolved_positions: list[dict[str, Any]] = []
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            resolved_positions.append(
                {
                    "ch": channel.get("ch"),
                    "azimuth_deg": channel.get("azimuth_deg"),
                    "elevation_deg": channel.get("elevation_deg"),
                }
            )
        return _normalize_speaker_positions(
            resolved_positions,
            target_id=normalized_target_id,
            path=path,
        )

    speaker_positions = target.get("speaker_positions")
    if isinstance(speaker_positions, list):
        return _normalize_speaker_positions(
            [item for item in speaker_positions if isinstance(item, dict)],
            target_id=normalized_target_id,
            path=path,
        )

    raise ValueError(
        "Render target must define speaker_positions or speaker_positions_ref: "
        f"{normalized_target_id} ({path})"
    )


def _resolve_speaker_positions(
    targets: list[dict[str, Any]],
    *,
    path: Path,
) -> list[dict[str, Any]]:
    speaker_layouts = _speaker_positions_layouts()
    resolved_targets: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        resolved_target = dict(target)
        resolved_target["speaker_positions"] = _resolve_target_speaker_positions(
            target,
            speaker_layouts=speaker_layouts,
            path=path,
        )
        resolved_target.pop("speaker_positions_ref", None)
        resolved_targets.append(resolved_target)
    return resolved_targets


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
    normalized_payload = dict(payload)
    normalized_payload["targets"] = _resolve_speaker_positions(
        targets,
        path=resolved_path,
    )
    return normalized_payload


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
