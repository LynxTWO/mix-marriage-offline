from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.core.registries.render_targets_registry import load_render_targets_registry
from mmo.resources import data_root, ontology_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


_FALLBACK_TARGET_ALIASES_BY_ID: dict[str, tuple[str, ...]] = {
    "TARGET.STEREO.2_0": (
        "Stereo (streaming)",
        "Stereo",
    ),
    "TARGET.SURROUND.5_1": (
        "5.1 (home theater)",
        "5.1",
    ),
    "TARGET.SURROUND.7_1": (
        "7.1 (cinematic)",
        "7.1",
    ),
}


def _normalize_target_token(token: str) -> str:
    # Alias matching ignores whitespace and is case-insensitive.
    return "".join(token.split()).casefold()


def _resolve_targets_yaml_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "render_targets.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


def _fallback_aliases_for_target_id(target_id: str) -> tuple[str, ...]:
    return _FALLBACK_TARGET_ALIASES_BY_ID.get(target_id, ())


def _coerce_alias_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    aliases: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized:
            aliases.append(normalized)
    return aliases


def _collect_target_ids_and_aliases_from_yaml(
    path: Path | None,
) -> tuple[list[str], dict[str, list[str]]]:
    if yaml is None:
        return ([], {})

    resolved_path = _resolve_targets_yaml_path(path)
    try:
        payload = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ([], {})

    if not isinstance(payload, dict):
        return ([], {})
    targets_raw = payload.get("targets")
    if not isinstance(targets_raw, list):
        return ([], {})

    target_ids: list[str] = []
    alias_to_target_ids: dict[str, set[str]] = {}

    for row in targets_raw:
        if not isinstance(row, dict):
            continue
        target_id_raw = row.get("target_id")
        if not isinstance(target_id_raw, str):
            continue
        target_id = target_id_raw.strip()
        if not target_id:
            continue
        target_ids.append(target_id)

        alias_candidates: list[str] = []
        label = row.get("label")
        if isinstance(label, str):
            normalized_label = label.strip()
            if normalized_label:
                alias_candidates.append(normalized_label)
        alias_candidates.extend(_coerce_alias_list(row.get("aliases")))
        alias_candidates.extend(_fallback_aliases_for_target_id(target_id))

        for alias in alias_candidates:
            folded = _normalize_target_token(alias)
            if not folded:
                continue
            alias_to_target_ids.setdefault(folded, set()).add(target_id)

    unique_sorted_target_ids = sorted(set(target_ids))
    normalized_alias_map: dict[str, list[str]] = {
        folded: sorted(ids)
        for folded, ids in alias_to_target_ids.items()
    }
    return (unique_sorted_target_ids, normalized_alias_map)


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

    target_ids: list[str] = []
    alias_map: dict[str, list[str]] = {}

    try:
        registry = load_render_targets_registry(path)
    except ValueError:
        registry = None
    else:
        target_ids = registry.list_target_ids()
        for target_id in target_ids:
            target_payload = registry.get_target(target_id)
            alias_candidates: list[str] = []
            label = target_payload.get("label")
            if isinstance(label, str):
                normalized_label = label.strip()
                if normalized_label:
                    alias_candidates.append(normalized_label)
            alias_candidates.extend(_coerce_alias_list(target_payload.get("aliases")))
            alias_candidates.extend(_fallback_aliases_for_target_id(target_id))
            for alias in alias_candidates:
                folded_alias = _normalize_target_token(alias)
                if not folded_alias:
                    continue
                alias_map.setdefault(folded_alias, [])
                if target_id not in alias_map[folded_alias]:
                    alias_map[folded_alias].append(target_id)

        alias_map = {
            folded: sorted(set(ids))
            for folded, ids in alias_map.items()
        }

    if not target_ids:
        target_ids, alias_map = _collect_target_ids_and_aliases_from_yaml(path)

    if normalized_token in target_ids:
        return normalized_token

    folded_lookup = {target_id.casefold(): target_id for target_id in target_ids}
    matched = folded_lookup.get(normalized_token.casefold())
    if matched is not None:
        return matched

    folded_token = _normalize_target_token(normalized_token)
    alias_matches = alias_map.get(folded_token, [])
    if len(alias_matches) == 1:
        return alias_matches[0]
    if len(alias_matches) > 1:
        raise ValueError(
            (
                f"Ambiguous render target token: {normalized_token}. "
                f"Matching targets: {', '.join(alias_matches)}"
            )
        )

    if target_ids:
        raise ValueError(
            f"Unknown render target token: {normalized_token}. "
            f"Available targets: {', '.join(target_ids)}"
        )
    raise ValueError(
        f"Unknown render target token: {normalized_token}. "
        "No render targets are available."
    )
