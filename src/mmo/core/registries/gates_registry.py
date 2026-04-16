"""Gates policy registry loader for ontology/policies/gates.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from mmo.resources import data_root, ontology_dir


def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "policies" / "gates.yaml"
    if path.is_absolute():
        return path
    return data_root() / path


class GatesRegistry:
    """Immutable, deterministically ordered gates policy registry.

    The registry wraps ``ontology/policies/gates.yaml`` and exposes the
    single policy (identified by ``_meta.policy_id``) plus its individual
    gate entries.
    """

    def __init__(
        self,
        policy_id: str,
        gates: dict[str, dict[str, Any]],
        meta: dict[str, Any] | None,
    ) -> None:
        self._policy_id = policy_id
        self._gates = gates
        self._meta = meta

    @property
    def meta(self) -> dict[str, Any] | None:
        return dict(self._meta) if self._meta else None

    def get_policy_ids(self) -> list[str]:
        """Return policy IDs in deterministic sorted order."""
        return [self._policy_id]

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        """Return a policy entry by ID.

        The returned dict contains ``policy_id``, ``gates`` (sorted gate
        entries), and ``meta``.

        Raises ValueError with a deterministic message listing known IDs
        if the policy_id is not found.
        """
        normalized = policy_id.strip() if isinstance(policy_id, str) else ""
        if not normalized:
            raise ValueError("policy_id must be a non-empty string.")

        if normalized == self._policy_id:
            return {
                "policy_id": self._policy_id,
                "gates": {
                    gate_id: dict(entry)
                    for gate_id, entry in self._gates.items()
                },
                "meta": dict(self._meta) if self._meta else None,
            }

        known_ids = self.get_policy_ids()
        if known_ids:
            raise ValueError(
                f"Unknown policy_id: {normalized}. "
                f"Known policy_ids: {', '.join(known_ids)}"
            )
        raise ValueError(
            f"Unknown policy_id: {normalized}. No policies are available."
        )

    def get_gate_ids(self) -> list[str]:
        """Return gate IDs in deterministic sorted order."""
        return list(self._gates.keys())

    def get_gate(self, gate_id: str) -> dict[str, Any]:
        """Return a single gate entry by ID.

        Raises ValueError with a deterministic message listing known IDs
        if the gate_id is not found.
        """
        normalized = gate_id.strip() if isinstance(gate_id, str) else ""
        if not normalized:
            raise ValueError("gate_id must be a non-empty string.")

        gate = self._gates.get(normalized)
        if gate is not None:
            return dict(gate)

        known_ids = self.get_gate_ids()
        if known_ids:
            raise ValueError(
                f"Unknown gate_id: {normalized}. "
                f"Known gate_ids: {', '.join(known_ids)}"
            )
        raise ValueError(
            f"Unknown gate_id: {normalized}. No gates are available."
        )

    def __len__(self) -> int:
        return len(self._gates)


def load_gates_registry(path: Path | None = None) -> GatesRegistry:
    """Load and validate the gates registry from YAML.

    Returns a GatesRegistry with gate IDs in deterministic sorted order.
    """
    if yaml is None:
        raise RuntimeError("PyYAML is required to load gates registry.")

    resolved_path = _resolve_registry_path(path)

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(
            f"Failed to read gates registry YAML from {resolved_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Gates registry YAML is not valid: {resolved_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Gates registry YAML root must be a mapping: {resolved_path}"
        )

    gates_root = payload.get("gates")
    if not isinstance(gates_root, dict):
        raise ValueError(
            f"Gates registry missing 'gates' mapping: {resolved_path}"
        )

    meta = gates_root.get("_meta")
    if meta is not None and not isinstance(meta, dict):
        meta = None

    policy_id = ""
    if isinstance(meta, dict):
        raw_pid = meta.get("policy_id")
        if isinstance(raw_pid, str) and raw_pid.strip():
            policy_id = raw_pid.strip()
    if not policy_id:
        # The registry carries one policy, but downstream receipts still refer
        # to it by id. Fail here instead of inventing a policy identifier.
        raise ValueError(
            f"Gates registry _meta.policy_id is required: {resolved_path}"
        )

    gates: dict[str, dict[str, Any]] = {}
    for gate_id in sorted(gates_root.keys()):
        if gate_id == "_meta":
            continue
        entry = gates_root[gate_id]
        if not isinstance(entry, dict):
            raise ValueError(f"Gate entry must be a mapping: {gate_id}")
        gates[gate_id] = dict(entry)

    return GatesRegistry(
        policy_id=policy_id,
        gates=gates,
        meta=dict(meta) if meta else None,
    )
