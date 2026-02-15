"""Layout registry loader for ontology/layouts.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

_DEFAULT_LAYOUTS_PATH = Path("ontology/layouts.yaml")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return _repo_root() / _DEFAULT_LAYOUTS_PATH
    if path.is_absolute():
        return path
    return _repo_root() / path


class LayoutRegistry:
    """Immutable, deterministically ordered layout registry."""

    def __init__(
        self,
        layouts: dict[str, dict[str, Any]],
        meta: dict[str, Any] | None,
    ) -> None:
        self._layouts = layouts
        self._meta = meta

    @property
    def meta(self) -> dict[str, Any] | None:
        return dict(self._meta) if self._meta else None

    def list_layout_ids(self) -> list[str]:
        """Return layout IDs in deterministic sorted order."""
        return list(self._layouts.keys())

    def get_layout(self, layout_id: str) -> dict[str, Any]:
        """Return a layout entry by ID.

        Raises ValueError with a deterministic message listing known IDs
        if the layout_id is not found.
        """
        normalized = layout_id.strip() if isinstance(layout_id, str) else ""
        if not normalized:
            raise ValueError("layout_id must be a non-empty string.")

        layout = self._layouts.get(normalized)
        if layout is not None:
            return dict(layout)

        known_ids = self.list_layout_ids()
        if known_ids:
            raise ValueError(
                f"Unknown layout_id: {normalized}. "
                f"Known layout_ids: {', '.join(known_ids)}"
            )
        raise ValueError(
            f"Unknown layout_id: {normalized}. No layouts are available."
        )

    def __len__(self) -> int:
        return len(self._layouts)

    def __contains__(self, layout_id: str) -> bool:
        return layout_id in self._layouts


def load_layout_registry(path: Path | None = None) -> LayoutRegistry:
    """Load and validate the layout registry from YAML.

    Returns a LayoutRegistry with entries sorted by layout_id.
    """
    if yaml is None:
        raise RuntimeError("PyYAML is required to load layout registry.")

    resolved_path = _resolve_registry_path(path)

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(
            f"Failed to read layout registry YAML from {resolved_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Layout registry YAML is not valid: {resolved_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Layout registry YAML root must be a mapping: {resolved_path}"
        )

    layouts_map = payload.get("layouts")
    if not isinstance(layouts_map, dict):
        raise ValueError(
            f"Layout registry missing 'layouts' mapping: {resolved_path}"
        )

    meta = layouts_map.get("_meta")
    if meta is not None and not isinstance(meta, dict):
        meta = None

    entries: dict[str, dict[str, Any]] = {}
    for layout_id in sorted(layouts_map.keys()):
        if layout_id == "_meta":
            continue
        entry = layouts_map[layout_id]
        if not isinstance(entry, dict):
            raise ValueError(f"Layout entry must be a mapping: {layout_id}")
        channel_order = entry.get("channel_order")
        if not isinstance(channel_order, list) or not channel_order:
            raise ValueError(
                f"Layout {layout_id} missing or empty channel_order list."
            )
        seen: set[str] = set()
        duplicates: list[str] = []
        for ch in channel_order:
            if ch in seen:
                duplicates.append(ch)
            seen.add(ch)
        if duplicates:
            raise ValueError(
                f"Layout {layout_id} has duplicate channels in channel_order: "
                f"{', '.join(sorted(set(duplicates)))}"
            )
        entries[layout_id] = dict(entry)

    return LayoutRegistry(
        layouts=entries,
        meta=dict(meta) if meta else None,
    )
