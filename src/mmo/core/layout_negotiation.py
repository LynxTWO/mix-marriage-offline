"""Layout negotiation: load and query canonical layouts, speaker positions, and downmix paths.

This module provides the Objective Core API for layout information and downmix
availability checks. It is the primary consumer of ``ontology/layouts.yaml``
and ``ontology/downmix.yaml``.

Exported public API
-------------------
- ``load_layouts_registry()`` — load all layout entries from layouts.yaml.
- ``get_layout_info()`` — return info dict for a single layout ID.
- ``list_supported_layouts()`` — sorted list of all known layout IDs.
- ``get_layout_speaker_positions()`` — per-channel positions from the layout's
  ``speaker_positions`` block (uses layouts.yaml azimuth convention).
- ``get_layout_lfe_policy()`` — LFE policy dict for a given layout.
- ``load_downmix_contract()`` — load the canonical ``ontology/downmix.yaml``.
- ``is_downmix_path_available()`` — whether a conversion path exists.
- ``get_channel_count()`` — channel count for a layout.
- ``has_lfe()`` — whether a layout has an LFE channel.
- ``get_lfe_channels()`` — list of LFE channel SPK IDs in a layout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.resources import ontology_dir

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - environment issue
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_yaml() -> Any:
    if _yaml is None:
        raise RuntimeError(
            "PyYAML is required for layout_negotiation.  "
            "Install it with: pip install PyYAML"
        )
    return _yaml


def _load_yaml(path: Path) -> Dict[str, Any]:
    yaml = _require_yaml()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except OSError as exc:
        raise ValueError(f"Failed to read YAML from {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _default_layouts_path() -> Path:
    return ontology_dir() / "layouts.yaml"


def _default_downmix_path() -> Path:
    return ontology_dir() / "downmix.yaml"


# ---------------------------------------------------------------------------
# Layouts API
# ---------------------------------------------------------------------------


def load_layouts_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load layouts.yaml and return all layout entries (``_meta`` excluded).

    Returns a ``dict`` mapping ``LAYOUT.*`` IDs to their entry dicts.
    The result is sorted by layout ID for determinism.
    """
    resolved = path or _default_layouts_path()
    data = _load_yaml(resolved)
    layouts_raw = data.get("layouts")
    if not isinstance(layouts_raw, dict):
        raise ValueError(f"layouts.yaml missing 'layouts' mapping: {resolved}")
    return {
        k: v
        for k, v in sorted(layouts_raw.items())
        if k != "_meta" and isinstance(v, dict)
    }


def get_layout_info(
    layout_id: str,
    path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Return the info dict for a single layout ID, or ``None`` if not found."""
    if not isinstance(layout_id, str) or not layout_id.strip():
        return None
    layouts = load_layouts_registry(path)
    entry = layouts.get(layout_id.strip())
    if not isinstance(entry, dict):
        return None
    return dict(entry)


def list_supported_layouts(path: Optional[Path] = None) -> List[str]:
    """Return a sorted list of all known layout IDs."""
    return list(load_layouts_registry(path).keys())


def get_channel_count(
    layout_id: str,
    path: Optional[Path] = None,
) -> Optional[int]:
    """Return the channel count for a layout, or ``None`` if not found."""
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return None
    count = entry.get("channel_count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


def has_lfe(
    layout_id: str,
    path: Optional[Path] = None,
) -> bool:
    """Return whether a layout has an LFE channel."""
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return False
    return bool(entry.get("has_lfe", False))


def get_lfe_channels(
    layout_id: str,
    path: Optional[Path] = None,
) -> List[str]:
    """Return the list of LFE channel SPK IDs in a layout.

    Returns an empty list for layouts without LFE or unknown layouts.
    """
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return []
    policy = entry.get("lfe_policy")
    if not isinstance(policy, dict):
        # Fall back to channel_order scan
        channel_order = entry.get("channel_order", [])
        _lfe_ids = frozenset({"SPK.LFE", "SPK.LFE1", "SPK.LFE2"})
        return [ch for ch in channel_order if isinstance(ch, str) and ch in _lfe_ids]
    lfe_channels = policy.get("lfe_channels", [])
    return [ch for ch in lfe_channels if isinstance(ch, str)]


def get_layout_lfe_policy(
    layout_id: str,
    path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Return the ``lfe_policy`` dict for a layout, or ``None`` if absent."""
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return None
    policy = entry.get("lfe_policy")
    if not isinstance(policy, dict):
        return None
    return dict(policy)


def get_layout_speaker_positions(
    layout_id: str,
    path: Optional[Path] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return per-channel speaker positions from the layout's ``speaker_positions`` block.

    Each entry is ``{"spk_id": str, "azimuth_deg": float, "elevation_deg": float}``.
    Coordinate convention: ``azimuth_deg`` 0=front center, +=left, -=right
    (as declared in ``ontology/speakers.yaml``).

    Returns ``None`` if the layout is unknown or has no ``speaker_positions`` block.
    """
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return None
    positions = entry.get("speaker_positions")
    if not isinstance(positions, list):
        return None
    result: List[Dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        spk_id = item.get("spk_id")
        az = item.get("azimuth_deg")
        el = item.get("elevation_deg")
        if (
            not isinstance(spk_id, str)
            or isinstance(az, bool)
            or not isinstance(az, (int, float))
            or isinstance(el, bool)
            or not isinstance(el, (int, float))
        ):
            continue
        result.append(
            {
                "spk_id": spk_id,
                "azimuth_deg": float(az),
                "elevation_deg": float(el),
            }
        )
    return result if result else None


def get_layout_channel_order(
    layout_id: str,
    path: Optional[Path] = None,
) -> Optional[List[str]]:
    """Return the canonical channel_order list for a layout, or ``None`` if not found."""
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return None
    order = entry.get("channel_order")
    if not isinstance(order, list):
        return None
    return [ch for ch in order if isinstance(ch, str)]


# ---------------------------------------------------------------------------
# Downmix contract API
# ---------------------------------------------------------------------------


def load_downmix_contract(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and return ``ontology/downmix.yaml`` as a dict.

    Raises :class:`ValueError` if the file cannot be loaded or is malformed.
    """
    resolved = path or _default_downmix_path()
    data = _load_yaml(resolved)
    downmix = data.get("downmix")
    if not isinstance(downmix, dict):
        raise ValueError(f"downmix.yaml missing 'downmix' mapping: {resolved}")
    return data


def is_downmix_path_available(
    source_layout_id: str,
    target_layout_id: str,
    *,
    policy_id: Optional[str] = None,
) -> bool:
    """Return ``True`` if a downmix path exists between the two layouts.

    Delegates to :func:`mmo.core.downmix.layout_negotiation_available`.
    Returns ``False`` on any error (layout not found, no policy, etc.).
    """
    try:
        from mmo.core.downmix import layout_negotiation_available  # noqa: PLC0415

        result = layout_negotiation_available(
            source_layout_id,
            target_layout_id,
            policy_id=policy_id,
            warn_on_composed_path=False,
        )
        return bool(result.get("available", False))
    except Exception:  # pragma: no cover - best-effort
        return False


def get_downmix_lfe_routing(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the ``lfe_routing`` section from ``downmix.yaml``, or ``None``."""
    try:
        data = load_downmix_contract(path)
    except (ValueError, FileNotFoundError):
        return None
    downmix = data.get("downmix", {})
    routing = downmix.get("lfe_routing")
    if not isinstance(routing, dict):
        return None
    return dict(routing)


def get_downmix_similarity_policy(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the ``similarity_policy`` section from ``downmix.yaml``, or ``None``."""
    try:
        data = load_downmix_contract(path)
    except (ValueError, FileNotFoundError):
        return None
    downmix = data.get("downmix", {})
    policy = downmix.get("similarity_policy")
    if not isinstance(policy, dict):
        return None
    return dict(policy)
