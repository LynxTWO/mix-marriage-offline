from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.core.registries.render_targets_registry import load_render_targets_registry


def load_render_targets(path: Path | None = None) -> dict[str, Any]:
    """Load render targets as a deterministic payload."""
    return load_render_targets_registry(path).to_payload()


def list_render_targets(path: Path | None = None) -> list[dict[str, Any]]:
    """List render targets in deterministic target_id order."""
    registry = load_render_targets_registry(path)
    return [
        registry.get_target(target_id)
        for target_id in registry.list_target_ids()
    ]


def get_render_target(target_id: str, path: Path | None = None) -> dict[str, Any] | None:
    """Return a single render target by ID, or ``None`` if not found."""
    try:
        return load_render_targets_registry(path).get_target(target_id)
    except ValueError:
        return None


def resolve_render_target_id(token: str, path: Path | None = None) -> str:
    """Resolve a render target token to a canonical TARGET.* ID."""
    normalized_token = token.strip() if isinstance(token, str) else ""
    if not normalized_token:
        raise ValueError("Render target token must be a non-empty string.")

    registry = load_render_targets_registry(path)
    target_ids = registry.list_target_ids()

    if normalized_token in target_ids:
        return normalized_token

    folded_lookup = {target_id.casefold(): target_id for target_id in target_ids}
    matched = folded_lookup.get(normalized_token.casefold())
    if matched is not None:
        return matched

    if target_ids:
        raise ValueError(
            f"Unknown render target token: {normalized_token}. "
            f"Available targets: {', '.join(target_ids)}"
        )
    raise ValueError(
        f"Unknown render target token: {normalized_token}. "
        "No render targets are available."
    )
