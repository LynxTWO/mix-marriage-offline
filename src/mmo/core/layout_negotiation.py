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

Dual channel-ordering standard support
---------------------------------------
- ``get_channel_order()`` — return channel order for a specific standard
  (``"SMPTE"`` default, ``"FILM"``, etc.) using ``ordering_variants``.
- ``list_supported_standards()`` — list ordering standards for a layout.
- ``reorder_channels()`` — reorder channel data between two orderings.

Channel ordering standards
--------------------------
- **SMPTE / ITU-R** (default): the ordering baked into WAV, FLAC, WavPack,
  FFmpeg, and most DAW exports.  Example 5.1: L R C LFE Ls Rs.
- **Film / Cinema / Pro Tools**: the ordering used in pro mixing rooms.
  Example 5.1: L C R Ls Rs LFE.

The canonical ``channel_order`` in ``layouts.yaml`` is always SMPTE/ITU-R.
The ``ordering_variants`` block records alternative orderings for the same
physical speaker set.  All MMO file I/O defaults to SMPTE order.
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
# Dual channel-ordering standard API
# ---------------------------------------------------------------------------

#: Default channel ordering standard for all MMO file I/O.
DEFAULT_CHANNEL_STANDARD: str = "SMPTE"


def get_channel_order(
    layout_id: str,
    standard: str = DEFAULT_CHANNEL_STANDARD,
    path: Optional[Path] = None,
) -> Optional[List[str]]:
    """Return the channel order for a layout under the requested ordering standard.

    Looks up ``ordering_variants[standard]`` in the layout entry first; falls
    back to the canonical ``channel_order`` (always SMPTE/ITU-R) when the
    requested standard is not explicitly defined.

    Parameters
    ----------
    layout_id:
        Canonical ``LAYOUT.*`` ID.
    standard:
        Channel ordering standard to use.  ``"SMPTE"`` (the default) is the
        ordering used for WAV, FLAC, WavPack, and FFmpeg output.  ``"FILM"``
        is the ordering used in pro mixing rooms and most cinema dubbing
        stages.
    path:
        Optional override path to ``layouts.yaml``.

    Returns
    -------
    list[str] | None:
        Ordered list of ``SPK.*`` channel IDs, or ``None`` if the layout is
        not found.

    Examples
    --------
    >>> get_channel_order("LAYOUT.5_1", "SMPTE")
    ["SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"]
    >>> get_channel_order("LAYOUT.5_1", "FILM")
    ["SPK.L", "SPK.C", "SPK.R", "SPK.LS", "SPK.RS", "SPK.LFE"]
    """
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return None

    # Prefer the explicitly-declared ordering_variants entry.
    variants = entry.get("ordering_variants")
    if isinstance(variants, dict):
        variant = variants.get(str(standard))
        if isinstance(variant, list) and variant:
            return [ch for ch in variant if isinstance(ch, str)]

    # Fall back to the canonical channel_order (SMPTE default).
    canonical = entry.get("channel_order")
    if isinstance(canonical, list):
        return [ch for ch in canonical if isinstance(ch, str)]
    return None


def list_supported_standards(
    layout_id: str,
    path: Optional[Path] = None,
) -> List[str]:
    """Return a sorted list of ordering standards available for a layout.

    Always includes at least the canonical ``ordering_standard`` value from
    the layout entry (``"SMPTE"`` for most layouts).  Additional standards
    are read from the ``ordering_variants`` block.

    Returns an empty list when the layout is not found.

    Parameters
    ----------
    layout_id:
        Canonical ``LAYOUT.*`` ID.
    path:
        Optional override path to ``layouts.yaml``.
    """
    entry = get_layout_info(layout_id, path)
    if entry is None:
        return []
    standards: set[str] = set()
    canonical_std = entry.get("ordering_standard")
    if isinstance(canonical_std, str) and canonical_std:
        standards.add(canonical_std)
    else:
        standards.add(DEFAULT_CHANNEL_STANDARD)
    variants = entry.get("ordering_variants")
    if isinstance(variants, dict):
        standards.update(k for k in variants if isinstance(k, str) and k)
    return sorted(standards)


def reorder_channels(
    data: Any,
    from_order: List[str],
    to_order: List[str],
) -> Any:
    """Reorder channel data from one channel ordering to another.

    Works on any indexed sequence: ``list``, ``tuple``, and NumPy arrays
    (when NumPy is available).  Only channels present in both ``from_order``
    and ``to_order`` are included in the output; channels that appear in
    ``to_order`` but are absent from ``from_order`` are silently dropped.

    Parameters
    ----------
    data:
        Sequence of per-channel elements whose length matches
        ``len(from_order)``.  For example: a list of audio frames
        (one frame per channel), a list of gain values, or a 2-D NumPy
        array with shape ``(channels, samples)``.
    from_order:
        Source ``SPK.*`` channel-ID ordering (must match ``len(data)``).
    to_order:
        Target ``SPK.*`` channel-ID ordering.

    Returns
    -------
    Reordered sequence of the same type as ``data`` (list or NumPy array).

    Raises
    ------
    ValueError:
        If ``len(data)`` does not equal ``len(from_order)``.

    Examples
    --------
    Reorder 5.1 SMPTE → Film:

    >>> smpte = ["L", "R", "C", "LFE", "Ls", "Rs"]   # from_order
    >>> film  = ["L", "C", "R", "Ls", "Rs", "LFE"]   # to_order
    >>> reorder_channels([0, 1, 2, 3, 4, 5], smpte, film)
    [0, 2, 1, 4, 5, 3]
    """
    if len(data) != len(from_order):
        raise ValueError(
            f"reorder_channels: data length {len(data)} does not match "
            f"from_order length {len(from_order)}."
        )
    index_map: Dict[str, int] = {ch: i for i, ch in enumerate(from_order)}
    indices: List[int] = [
        index_map[ch] for ch in to_order if ch in index_map
    ]
    # NumPy fast-path (no hard dependency).
    try:
        import numpy as _np  # noqa: PLC0415

        if isinstance(data, _np.ndarray):
            return data[indices]
    except ImportError:
        pass
    # Generic sequence path.
    result = [data[i] for i in indices]
    if isinstance(data, tuple):
        return tuple(result)
    return result


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
