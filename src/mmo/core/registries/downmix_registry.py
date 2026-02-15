"""Downmix registry loader for ontology/policies/downmix.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

_DEFAULT_DOWNMIX_PATH = Path("ontology/policies/downmix.yaml")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return _repo_root() / _DEFAULT_DOWNMIX_PATH
    if path.is_absolute():
        return path
    return _repo_root() / path


class DownmixRegistry:
    """Immutable, deterministically ordered downmix policy registry."""

    def __init__(
        self,
        policies: dict[str, dict[str, Any]],
        conversions: list[dict[str, Any]],
        default_policy_by_source_layout: dict[str, str],
        composition_paths: list[dict[str, Any]],
        meta: dict[str, Any] | None,
    ) -> None:
        self._policies = policies
        self._conversions = conversions
        self._defaults = default_policy_by_source_layout
        self._composition_paths = composition_paths
        self._meta = meta

    @property
    def meta(self) -> dict[str, Any] | None:
        return dict(self._meta) if self._meta else None

    def list_policy_ids(self) -> list[str]:
        """Return policy IDs in deterministic sorted order."""
        return list(self._policies.keys())

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        """Return a policy entry by ID.

        Raises ValueError with a deterministic message listing known IDs
        if the policy_id is not found.
        """
        normalized = policy_id.strip() if isinstance(policy_id, str) else ""
        if not normalized:
            raise ValueError("policy_id must be a non-empty string.")

        policy = self._policies.get(normalized)
        if policy is not None:
            return dict(policy)

        known_ids = self.list_policy_ids()
        if known_ids:
            raise ValueError(
                f"Unknown policy_id: {normalized}. "
                f"Known policy_ids: {', '.join(known_ids)}"
            )
        raise ValueError(
            f"Unknown policy_id: {normalized}. No policies are available."
        )

    def default_policy_for_source(self, source_layout_id: str) -> str | None:
        """Return the default policy ID for a source layout, or None."""
        return self._defaults.get(source_layout_id)

    def resolve(
        self,
        policy_id: str | None,
        from_layout_id: str,
        to_layout_id: str,
    ) -> dict[str, Any]:
        """Resolve a downmix conversion for a layout pair.

        Returns a dict with source_layout_id, target_layout_id, policy_id,
        and either matrix_id (direct conversion) or steps (composition path).

        When multiple candidates match, selection is deterministic (sorted
        by policy_id then matrix_id for direct, by stringified steps for
        composition paths).

        Raises ValueError with a deterministic message if no conversion
        is found.
        """
        effective_policy = policy_id
        if effective_policy is None:
            effective_policy = self._defaults.get(from_layout_id)

        # Search direct conversions.
        candidates: list[dict[str, Any]] = []
        for entry in self._conversions:
            if entry.get("source_layout_id") != from_layout_id:
                continue
            if entry.get("target_layout_id") != to_layout_id:
                continue
            entry_policy = entry.get("policy_id")
            if effective_policy is not None and entry_policy != effective_policy:
                continue
            candidates.append(entry)

        if candidates:
            candidates.sort(
                key=lambda e: (e.get("policy_id", ""), e.get("matrix_id", ""))
            )
            winner = candidates[0]
            return {
                "source_layout_id": from_layout_id,
                "target_layout_id": to_layout_id,
                "policy_id": winner.get("policy_id", effective_policy),
                "matrix_id": winner["matrix_id"],
            }

        # Search composition paths.
        comp_candidates: list[dict[str, Any]] = []
        for entry in self._composition_paths:
            if entry.get("source_layout_id") != from_layout_id:
                continue
            if entry.get("target_layout_id") != to_layout_id:
                continue
            comp_candidates.append(entry)

        if comp_candidates:
            comp_candidates.sort(
                key=lambda e: str(
                    sorted(
                        str(s.get("matrix_id", ""))
                        for s in (e.get("steps") or [])
                    )
                )
            )
            winner = comp_candidates[0]
            return {
                "source_layout_id": from_layout_id,
                "target_layout_id": to_layout_id,
                "policy_id": effective_policy,
                "steps": [dict(s) for s in winner.get("steps", [])],
            }

        # Deterministic error listing known source layouts.
        known_sources = sorted(
            {
                e.get("source_layout_id", "")
                for e in self._conversions
                if e.get("source_layout_id")
            }
            | {
                e.get("source_layout_id", "")
                for e in self._composition_paths
                if e.get("source_layout_id")
            }
        )

        raise ValueError(
            f"No conversion found: {from_layout_id} -> {to_layout_id}. "
            f"Known source layouts: {', '.join(known_sources)}"
        )

    def __len__(self) -> int:
        return len(self._policies)


def load_downmix_registry(path: Path | None = None) -> DownmixRegistry:
    """Load and validate the downmix registry from YAML.

    Returns a DownmixRegistry with policies sorted by policy_id.
    """
    if yaml is None:
        raise RuntimeError("PyYAML is required to load downmix registry.")

    resolved_path = _resolve_registry_path(path)

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(
            f"Failed to read downmix registry YAML from {resolved_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Downmix registry YAML is not valid: {resolved_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Downmix registry YAML root must be a mapping: {resolved_path}"
        )

    downmix = payload.get("downmix")
    if not isinstance(downmix, dict):
        raise ValueError(
            f"Downmix registry missing 'downmix' mapping: {resolved_path}"
        )

    meta = downmix.get("_meta")
    if meta is not None and not isinstance(meta, dict):
        meta = None

    # Extract and validate policies.
    policies_map = downmix.get("policies")
    if not isinstance(policies_map, dict):
        raise ValueError(
            f"Downmix registry missing 'policies' mapping: {resolved_path}"
        )

    policies: dict[str, dict[str, Any]] = {}
    for policy_id in sorted(policies_map.keys()):
        entry = policies_map[policy_id]
        if not isinstance(entry, dict):
            raise ValueError(f"Policy entry must be a mapping: {policy_id}")
        policies[policy_id] = dict(entry)

    # Extract default_policy_by_source_layout.
    defaults_map = downmix.get("default_policy_by_source_layout")
    if not isinstance(defaults_map, dict):
        defaults_map = {}
    defaults: dict[str, str] = {}
    for layout_id in sorted(defaults_map.keys()):
        policy_id_val = defaults_map[layout_id]
        if not isinstance(policy_id_val, str):
            raise ValueError(
                f"default_policy_by_source_layout[{layout_id}] must be a string."
            )
        if policy_id_val not in policies:
            raise ValueError(
                f"default_policy_by_source_layout[{layout_id}] references "
                f"unknown policy: {policy_id_val}. "
                f"Known policy_ids: {', '.join(sorted(policies.keys()))}"
            )
        defaults[layout_id] = policy_id_val

    # Extract conversions.
    conversions_raw = downmix.get("conversions")
    if conversions_raw is None:
        conversions_raw = []
    if not isinstance(conversions_raw, list):
        raise ValueError(
            f"Downmix registry 'conversions' must be a list: {resolved_path}"
        )
    conversions: list[dict[str, Any]] = []
    for i, entry in enumerate(conversions_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Conversion entry [{i}] must be a mapping.")
        for field in ("source_layout_id", "target_layout_id", "matrix_id"):
            if not isinstance(entry.get(field), str):
                raise ValueError(
                    f"Conversion entry [{i}] missing required string field: {field}"
                )
        conversions.append(dict(entry))

    # Extract composition_paths.
    comp_raw = downmix.get("composition_paths")
    if comp_raw is None:
        comp_raw = []
    if not isinstance(comp_raw, list):
        raise ValueError(
            f"Downmix registry 'composition_paths' must be a list: {resolved_path}"
        )
    composition_paths: list[dict[str, Any]] = []
    for i, entry in enumerate(comp_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Composition path [{i}] must be a mapping.")
        for field in ("source_layout_id", "target_layout_id"):
            if not isinstance(entry.get(field), str):
                raise ValueError(
                    f"Composition path [{i}] missing required string field: {field}"
                )
        steps = entry.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(
                f"Composition path [{i}] missing or empty steps list."
            )
        composition_paths.append(dict(entry))

    return DownmixRegistry(
        policies=policies,
        conversions=conversions,
        default_policy_by_source_layout=defaults,
        composition_paths=composition_paths,
        meta=dict(meta) if meta else None,
    )
