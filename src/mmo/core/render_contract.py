"""Per-target render contracts: layout and downmix specifications.

A render contract captures everything needed to execute one render job:
the target layout, channel configuration, downmix route (if required),
policies, and output format settings.

It is the bridge between the scene's source layout and the canonical ontology
definitions for layouts (``ontology/layouts.yaml``) and downmix paths.

Dual channel-ordering standard support
---------------------------------------
Every contract records which channel-ordering standard was requested via the
``layout_standard`` field (default ``"SMPTE"``).  The ``channel_order`` list
in the contract reflects that standard's ordering, sourced from the layout's
``ordering_variants`` block where available.

- **SMPTE / ITU-R** (default): WAV, FLAC, WavPack, FFmpeg, broadcast order.
  Example 5.1: L R C LFE Ls Rs.
- **Film / Cinema / Pro Tools**: pro mixing room order.
  Example 5.1: L C R Ls Rs LFE.

Exported public API
-------------------
- ``RENDER_CONTRACT_SCHEMA_VERSION`` — version tag.
- ``DEFAULT_LAYOUT_STANDARD`` — default channel ordering standard ("SMPTE").
- ``build_render_contract()`` — build a deterministic per-target contract.
- ``contracts_to_render_targets()`` — convert contracts to a render_targets
  payload suitable for :func:`mmo.core.render_plan.build_render_plan`.
"""

from __future__ import annotations

from typing import Any

from mmo.core.downmix import layout_negotiation_available
from mmo.core.layout_negotiation import get_channel_order as _get_channel_order
from mmo.resources import ontology_dir

#: Default channel ordering standard for MMO file I/O.
DEFAULT_LAYOUT_STANDARD: str = "SMPTE"

RENDER_CONTRACT_SCHEMA_VERSION = "0.1.0"

_OUTPUT_FORMAT_ORDER = ("wav", "flac", "wv", "aiff", "alac")
_VALID_OUTPUT_FORMATS: frozenset[str] = frozenset(_OUTPUT_FORMAT_ORDER)
_BINAURAL_LAYOUT_ID = "LAYOUT.BINAURAL"
_BINAURAL_SOURCE_HEIGHT = "LAYOUT.7_1_4"
_BINAURAL_SOURCE_SURROUND = "LAYOUT.5_1"
_BINAURAL_SOURCE_STEREO = "LAYOUT.2_0"

# Module-level layout cache: populated on first use, stable for the process.
_LAYOUTS_CACHE: dict[str, Any] = {}


def _load_layouts_yaml() -> dict[str, Any]:
    """Load and return the layouts registry from the ontology."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyYAML is required for render contracts.") from exc
    path = ontology_dir() / "layouts.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data.get("layouts") or {}


def _ensure_layouts_cache() -> None:
    if not _LAYOUTS_CACHE:
        _LAYOUTS_CACHE.update(_load_layouts_yaml())


def _get_layout_entry(layout_id: str) -> dict[str, Any]:
    """Return the layout entry for ``layout_id``, or raise ``ValueError``."""
    _ensure_layouts_cache()
    entry = _LAYOUTS_CACHE.get(layout_id)
    if not isinstance(entry, dict):
        raise ValueError(
            f"Layout {layout_id!r} not found in ontology/layouts.yaml."
        )
    return entry


def _normalize_formats(value: Any) -> list[str]:
    """Return a deduplicated, canonically ordered subset of lossless formats."""
    if not isinstance(value, list) or not value:
        return ["wav"]
    selected: set[str] = set()
    for item in value:
        normalized = str(item).strip().lower() if item else ""
        if normalized in _VALID_OUTPUT_FORMATS:
            selected.add(normalized)
    if not selected:
        return ["wav"]
    return [fmt for fmt in _OUTPUT_FORMAT_ORDER if fmt in selected]


def _select_binaural_source_layout(source_layout_id: str | None) -> str:
    clean_source = str(source_layout_id).strip() if source_layout_id else ""
    if not clean_source:
        return _BINAURAL_SOURCE_STEREO
    try:
        layout_entry = _get_layout_entry(clean_source)
    except ValueError:
        return _BINAURAL_SOURCE_STEREO

    height_speakers = layout_entry.get("height_speakers")
    if isinstance(height_speakers, list):
        if any(isinstance(item, str) and item.strip() for item in height_speakers):
            return _BINAURAL_SOURCE_HEIGHT

    channel_count = int(layout_entry.get("channel_count") or 0)
    if channel_count > 2:
        return _BINAURAL_SOURCE_SURROUND
    return _BINAURAL_SOURCE_STEREO


def build_render_contract(
    target_id: str,
    target_layout_id: str,
    *,
    source_layout_id: str | None = None,
    downmix_policy_id: str | None = None,
    gates_policy_id: str | None = None,
    output_formats: list[str] | None = None,
    sample_rate_hz: int = 48000,
    bit_depth: int = 24,
    layout_standard: str = DEFAULT_LAYOUT_STANDARD,
) -> dict[str, Any]:
    """Build a deterministic render contract for a single render target.

    Parameters
    ----------
    target_id:
        Canonical ``TARGET.*`` identifier for this render target.
    target_layout_id:
        Canonical ``LAYOUT.*`` identifier for the output channel layout.
    source_layout_id:
        Source ``LAYOUT.*`` identifier (from the scene).  When provided and
        different from ``target_layout_id``, a downmix route is resolved via
        the ontology.
    downmix_policy_id:
        ``POLICY.DOWNMIX.*`` to use for the fold.  If omitted the ontology
        default for the conversion path is used.
    gates_policy_id:
        ``POLICY.GATES.*`` for QA threshold lookup.
    output_formats:
        Lossless format list; defaults to ``["wav"]``.
    sample_rate_hz:
        Target sample rate in Hz; defaults to 48 000.
    bit_depth:
        Target bit depth; defaults to 24.
    layout_standard:
        Channel ordering standard for the output: ``"SMPTE"`` (default,
        matches WAV/FLAC/FFmpeg byte order) or ``"FILM"`` (pro mixing room
        order).  The ``channel_order`` in the returned contract reflects this
        standard when an ``ordering_variants`` entry is available.

    Returns
    -------
    dict:
        Deterministic render contract payload.

    Raises
    ------
    ValueError:
        If ``target_id`` or ``target_layout_id`` are empty, or if
        ``target_layout_id`` is not present in the layout ontology.
    """
    target_id = str(target_id).strip()
    target_layout_id = str(target_layout_id).strip()
    if not target_id:
        raise ValueError("target_id must be a non-empty string.")
    if not target_layout_id:
        raise ValueError("target_layout_id must be a non-empty string.")

    clean_standard = str(layout_standard).strip().upper() if layout_standard else DEFAULT_LAYOUT_STANDARD
    if not clean_standard:
        clean_standard = DEFAULT_LAYOUT_STANDARD

    layout_entry = _get_layout_entry(target_layout_id)

    # Resolve channel_order for the requested standard.
    ordered = _get_channel_order(target_layout_id, clean_standard)
    channel_order: list[str] = ordered if ordered else list(
        layout_entry.get("channel_order") or []
    )
    channel_count: int = int(
        layout_entry.get("channel_count") or len(channel_order)
    )
    family: str = str(layout_entry.get("family") or "unknown")
    has_lfe: bool = bool(layout_entry.get("has_lfe", False))
    normalized_formats: list[str] = _normalize_formats(output_formats)

    # Resolve downmix route when source and target layouts differ.
    downmix_route: dict[str, Any] | None = None
    notes: list[str] = []

    clean_source = str(source_layout_id).strip() if source_layout_id else ""
    if (
        clean_source
        and clean_source != target_layout_id
        and target_layout_id != _BINAURAL_LAYOUT_ID
    ):
        negotiation = layout_negotiation_available(
            clean_source,
            target_layout_id,
            policy_id=downmix_policy_id or None,
            warn_on_composed_path=True,
        )
        if negotiation["available"]:
            route: dict[str, Any] = {
                "from_layout_id": clean_source,
                "to_layout_id": target_layout_id,
                "policy_id": downmix_policy_id or "",
                "kind": "composed" if negotiation["composed"] else "direct",
            }
            if negotiation.get("warning"):
                notes.append(negotiation["warning"])
            downmix_route = route
        else:
            error_msg = str(negotiation.get("error") or "No downmix path available.")
            notes.append(
                f"No downmix path: {clean_source} \u2192 {target_layout_id}: {error_msg}"
            )

    contract: dict[str, Any] = {
        "schema_version": RENDER_CONTRACT_SCHEMA_VERSION,
        "target_id": target_id,
        "target_layout_id": target_layout_id,
        "channel_count": channel_count,
        "channel_order": channel_order,
        "family": family,
        "has_lfe": has_lfe,
        "layout_standard": clean_standard,
        "output_formats": normalized_formats,
        "sample_rate_hz": int(sample_rate_hz),
        "bit_depth": int(bit_depth),
    }
    if downmix_route is not None:
        contract["downmix_route"] = downmix_route
    if downmix_policy_id:
        contract["downmix_policy_id"] = str(downmix_policy_id).strip()
    if gates_policy_id:
        contract["gates_policy_id"] = str(gates_policy_id).strip()
    if notes:
        contract["notes"] = notes

    if target_layout_id == _BINAURAL_LAYOUT_ID:
        virtual_source_layout_id = _select_binaural_source_layout(clean_source or None)
        contract["binaural_virtualization"] = {
            "enabled": True,
            "source_layout_id": virtual_source_layout_id,
            "method": "conservative_ild_itd_rms_gated",
            "renderer_id": "PLUGIN.RENDERER.BINAURAL_PREVIEW_V0",
        }
        contract.setdefault("notes", [])
        contract["notes"].append(
            "Binaural virtualization deliverable using conservative ILD/ITD + gating."
        )
        contract["notes"].append(
            f"Binaural virtualization source layout: {virtual_source_layout_id}."
        )

    return contract


def contracts_to_render_targets(
    contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert render contracts to a ``render_targets`` payload.

    Converts the contracts list into the dict structure expected by
    :func:`mmo.core.render_plan.build_render_plan`.

    Parameters
    ----------
    contracts:
        List of render contract dicts as returned by
        :func:`build_render_contract`.

    Returns
    -------
    dict:
        ``{"targets": [...]}`` payload with one entry per contract.
    """
    targets: list[dict[str, Any]] = []
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        target_id = str(contract.get("target_id") or "").strip()
        layout_id = str(contract.get("target_layout_id") or "").strip()
        if not target_id or not layout_id:
            continue
        row: dict[str, Any] = {
            "target_id": target_id,
            "layout_id": layout_id,
        }
        downmix_policy_id = str(contract.get("downmix_policy_id") or "").strip()
        if downmix_policy_id:
            row["downmix_policy_id"] = downmix_policy_id
        gates_policy_id = str(contract.get("gates_policy_id") or "").strip()
        if gates_policy_id:
            row["safety_policy_id"] = gates_policy_id
        targets.append(row)
    return {"targets": targets}
