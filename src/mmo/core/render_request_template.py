"""Build a minimal, schema-valid render_request.json template."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from mmo.core.registries.layout_registry import LayoutRegistry, load_layout_registry

_RENDER_REQUEST_SCHEMA_VERSION = "0.1.0"
_DEFAULT_DOWNMIX_POLICY_ID = "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"
_DEFAULT_GATES_POLICY_ID = "POLICY.GATES.CORE_V0"


def _to_posix(path_str: str) -> str:
    """Normalize a path string to forward slashes only.

    Raises ValueError if the result would be empty.
    """
    posix = PurePosixPath(path_str.replace("\\", "/")).as_posix()
    if not posix:
        raise ValueError(f"Path normalizes to empty string: {path_str!r}")
    return posix


def build_render_request_template(
    target_layout_id: str,
    *,
    scene_path: str | None = None,
    routing_plan_path: str | None = None,
    layout_registry: LayoutRegistry | None = None,
) -> dict[str, Any]:
    """Build a deterministic, minimal render_request template.

    Args:
        target_layout_id: A LAYOUT.* ID that must exist in the registry.
        scene_path: Optional scene JSON path (will be POSIX-normalized).
        routing_plan_path: Optional routing plan path (will be POSIX-normalized).
        layout_registry: Pre-loaded registry; loads default if None.

    Returns:
        A dict that validates against render_request.schema.json.

    Raises:
        ValueError: If target_layout_id is unknown (message lists known IDs sorted).
    """
    registry = layout_registry or load_layout_registry()

    # Validates and raises ValueError with sorted known IDs on miss.
    registry.get_layout(target_layout_id)

    resolved_scene = _to_posix(scene_path) if scene_path else "scene.json"

    payload: dict[str, Any] = {
        "schema_version": _RENDER_REQUEST_SCHEMA_VERSION,
        "target_layout_id": target_layout_id,
        "scene_path": resolved_scene,
        "options": {
            "downmix_policy_id": _DEFAULT_DOWNMIX_POLICY_ID,
            "dry_run": True,
            "gates_policy_id": _DEFAULT_GATES_POLICY_ID,
        },
    }

    if routing_plan_path is not None:
        payload["routing_plan_path"] = _to_posix(routing_plan_path)

    return payload
