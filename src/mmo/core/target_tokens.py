from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mmo.core.registries.layout_registry import LayoutRegistry, load_layout_registry
from mmo.core.registries.render_targets_registry import (
    RenderTargetsRegistry,
    load_render_targets_registry,
)
from mmo.core.render_targets import resolve_render_target_id

TargetSource = Literal["target_id", "layout_id", "shorthand", "alias"]

_SHORTHANDS: dict[str, tuple[str | None, str]] = {
    "stereo": ("TARGET.STEREO.2_0", "LAYOUT.2_0"),
    "2.0": ("TARGET.STEREO.2_0", "LAYOUT.2_0"),
    "2_0": ("TARGET.STEREO.2_0", "LAYOUT.2_0"),
    "5.1": ("TARGET.SURROUND.5_1", "LAYOUT.5_1"),
    "5_1": ("TARGET.SURROUND.5_1", "LAYOUT.5_1"),
    "7.1": ("TARGET.SURROUND.7_1", "LAYOUT.7_1"),
    "7_1": ("TARGET.SURROUND.7_1", "LAYOUT.7_1"),
    "7.1.4": ("TARGET.IMMERSIVE.7_1_4", "LAYOUT.7_1_4"),
    "7_1_4": ("TARGET.IMMERSIVE.7_1_4", "LAYOUT.7_1_4"),
    "binaural": (None, "LAYOUT.BINAURAL"),
}

_SHORTHAND_HELP = "stereo, 2.0, 5.1, 7.1, 7.1.4, binaural"


@dataclass(frozen=True)
class ResolvedTarget:
    target_id: str | None
    layout_id: str
    display_label: str
    source: TargetSource


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _normalize_alias_token(token: str) -> str:
    return "".join(token.split()).casefold()


def _target_ids_for_layout(
    layout_id: str,
    *,
    target_registry: RenderTargetsRegistry,
) -> list[str]:
    rows = target_registry.find_targets_for_layout(layout_id)
    return sorted(
        {
            _coerce_str(row.get("target_id")).strip()
            for row in rows
            if isinstance(row, dict)
            and _coerce_str(row.get("target_id")).strip()
        }
    )


def _single_target_id_for_layout(
    layout_id: str,
    *,
    target_registry: RenderTargetsRegistry,
) -> str | None:
    target_ids = _target_ids_for_layout(layout_id, target_registry=target_registry)
    if len(target_ids) == 1:
        return target_ids[0]
    return None


def _resolve_layout_id_casefold(
    token: str,
    *,
    layout_registry: LayoutRegistry,
) -> str:
    layout_ids = layout_registry.list_layout_ids()
    by_casefold = {layout_id.casefold(): layout_id for layout_id in layout_ids}
    matched = by_casefold.get(token.casefold())
    if matched is not None:
        return matched
    # Keep the registry error text deterministic.
    layout_registry.get_layout(token)
    raise AssertionError("layout_registry.get_layout must raise for unknown IDs.")


def _layout_display_label(
    layout_id: str,
    *,
    layout_registry: LayoutRegistry,
) -> str:
    payload = layout_registry.get_layout(layout_id)
    label = _coerce_str(payload.get("label")).strip()
    return label if label else layout_id


def _build_resolved_target(
    *,
    source: TargetSource,
    target_id: str | None,
    layout_id: str,
    layout_registry: LayoutRegistry,
) -> ResolvedTarget:
    layout_label = _layout_display_label(layout_id, layout_registry=layout_registry)
    display_label = (
        f"{target_id} ({layout_label})"
        if isinstance(target_id, str) and target_id.strip()
        else layout_label
    )
    return ResolvedTarget(
        target_id=target_id if isinstance(target_id, str) and target_id.strip() else None,
        layout_id=layout_id,
        display_label=display_label,
        source=source,
    )


def _raise_ambiguous(token: str, candidates: list[str]) -> None:
    sorted_candidates = sorted(
        {
            candidate.strip()
            for candidate in candidates
            if isinstance(candidate, str) and candidate.strip()
        }
    )
    raise ValueError(
        (
            f"Ambiguous target token: {token}. "
            f"Candidates: {', '.join(sorted_candidates)}"
        )
    )


def _layout_alias_map(*, layout_registry: LayoutRegistry) -> dict[str, list[str]]:
    aliases_by_token: dict[str, set[str]] = {}
    for layout_id in layout_registry.list_layout_ids():
        payload = layout_registry.get_layout(layout_id)
        alias_values: list[str] = []
        label = _coerce_str(payload.get("label")).strip()
        if label:
            alias_values.append(label)
        aliases = payload.get("aliases")
        if isinstance(aliases, list):
            alias_values.extend(
                alias.strip()
                for alias in aliases
                if isinstance(alias, str) and alias.strip()
            )
        for alias in alias_values:
            folded = _normalize_alias_token(alias)
            if not folded:
                continue
            aliases_by_token.setdefault(folded, set()).add(layout_id)
    return {
        folded: sorted(layout_ids)
        for folded, layout_ids in aliases_by_token.items()
    }


def resolve_target_token(token: str) -> ResolvedTarget:
    normalized_token = token.strip() if isinstance(token, str) else ""
    if not normalized_token:
        raise ValueError("Target token must be a non-empty string.")

    target_registry = load_render_targets_registry()
    layout_registry = load_layout_registry()
    upper_token = normalized_token.upper()

    # 1) Explicit TARGET.* token
    if upper_token.startswith("TARGET."):
        resolved_target_id = resolve_render_target_id(normalized_token)
        target_payload = target_registry.get_target(resolved_target_id)
        target_layout_id = _resolve_layout_id_casefold(
            _coerce_str(target_payload.get("layout_id")).strip(),
            layout_registry=layout_registry,
        )
        return _build_resolved_target(
            source="target_id",
            target_id=resolved_target_id,
            layout_id=target_layout_id,
            layout_registry=layout_registry,
        )

    # 2) Explicit LAYOUT.* token
    if upper_token.startswith("LAYOUT."):
        resolved_layout_id = _resolve_layout_id_casefold(
            normalized_token,
            layout_registry=layout_registry,
        )
        return _build_resolved_target(
            source="layout_id",
            target_id=_single_target_id_for_layout(
                resolved_layout_id,
                target_registry=target_registry,
            ),
            layout_id=resolved_layout_id,
            layout_registry=layout_registry,
        )

    # 3) Canonical shorthands
    shorthand_match = _SHORTHANDS.get(normalized_token.casefold())
    if shorthand_match is not None:
        shorthand_target_id, shorthand_layout_id = shorthand_match
        try:
            resolved_layout_id = _resolve_layout_id_casefold(
                shorthand_layout_id,
                layout_registry=layout_registry,
            )
        except ValueError as exc:
            if normalized_token.casefold() == "binaural":
                raise ValueError(
                    (
                        "Shorthand 'binaural' is not available yet. "
                        "LAYOUT.BINAURAL is not defined."
                    )
                ) from exc
            raise

        resolved_target_id: str | None = None
        if isinstance(shorthand_target_id, str):
            target_payload = target_registry.get_target(shorthand_target_id)
            target_layout_id = _resolve_layout_id_casefold(
                _coerce_str(target_payload.get("layout_id")).strip(),
                layout_registry=layout_registry,
            )
            resolved_target_id = shorthand_target_id
            resolved_layout_id = target_layout_id
        return _build_resolved_target(
            source="shorthand",
            target_id=resolved_target_id,
            layout_id=resolved_layout_id,
            layout_registry=layout_registry,
        )

    # 4) Target aliases, then layout aliases
    render_target_error: str | None = None
    try:
        alias_target_id = resolve_render_target_id(normalized_token)
    except ValueError as exc:
        render_target_error = str(exc)
        if render_target_error.startswith("Ambiguous render target token:"):
            # Preserve deterministic render-target ambiguity text.
            raise ValueError(render_target_error) from exc
    else:
        target_payload = target_registry.get_target(alias_target_id)
        target_layout_id = _resolve_layout_id_casefold(
            _coerce_str(target_payload.get("layout_id")).strip(),
            layout_registry=layout_registry,
        )
        return _build_resolved_target(
            source="alias",
            target_id=alias_target_id,
            layout_id=target_layout_id,
            layout_registry=layout_registry,
        )

    layout_aliases = _layout_alias_map(layout_registry=layout_registry)
    layout_matches = layout_aliases.get(_normalize_alias_token(normalized_token), [])
    if len(layout_matches) > 1:
        _raise_ambiguous(normalized_token, layout_matches)
    if len(layout_matches) == 1:
        resolved_layout_id = layout_matches[0]
        return _build_resolved_target(
            source="alias",
            target_id=_single_target_id_for_layout(
                resolved_layout_id,
                target_registry=target_registry,
            ),
            layout_id=resolved_layout_id,
            layout_registry=layout_registry,
        )

    if isinstance(render_target_error, str) and render_target_error.startswith(
        "Unknown render target token:"
    ):
        # Preserve deterministic render-target unknown text (sorted candidates).
        raise ValueError(render_target_error)

    raise ValueError(
        (
            f"Unknown target token: {normalized_token}. "
            "Use TARGET.* or LAYOUT.* IDs, or shorthands: "
            f"{_SHORTHAND_HELP}."
        )
    )


__all__ = ["ResolvedTarget", "resolve_target_token"]
