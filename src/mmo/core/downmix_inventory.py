from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mmo.dsp.downmix import (
    load_downmix_registry,
    load_layouts,
    load_policy_pack,
)


def build_downmix_list_payload(
    *,
    repo_root: Path,
    include_layouts: bool,
    include_policies: bool,
    include_conversions: bool,
) -> dict[str, list[dict[str, object]]]:
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")

    payload: dict[str, list[dict[str, object]]] = {
        "layouts": [],
        "policies": [],
        "conversions": [],
    }

    if include_layouts:
        layout_rows: list[dict[str, object]] = []
        for layout_id in sorted(layouts.keys()):
            info = layouts[layout_id]
            row: dict[str, object] = {"id": layout_id}
            label = info.get("label")
            if isinstance(label, str) and label:
                row["name"] = label
            channel_count = info.get("channel_count")
            if isinstance(channel_count, int):
                row["channels"] = channel_count
            channel_order = info.get("channel_order")
            if isinstance(channel_order, list):
                row["speakers"] = list(channel_order)
            layout_rows.append(row)
        payload["layouts"] = layout_rows

    policies_data = registry.get("downmix", {}).get("policies", {})
    policies = policies_data if isinstance(policies_data, dict) else {}
    if include_policies:
        policy_rows: list[dict[str, object]] = []
        for policy_id in sorted(policies.keys()):
            entry = policies.get(policy_id, {})
            row: dict[str, object] = {"id": policy_id}
            description = entry.get("description") if isinstance(entry, dict) else None
            if isinstance(description, str) and description:
                row["description"] = description
            policy_rows.append(row)
        payload["policies"] = policy_rows

    if include_conversions:
        conversion_map: dict[tuple[str, str], set[str]] = {}
        conversions = registry.get("downmix", {}).get("conversions", [])
        if isinstance(conversions, list):
            for entry in conversions:
                if not isinstance(entry, dict):
                    continue
                source = entry.get("source_layout_id")
                target = entry.get("target_layout_id")
                if not (isinstance(source, str) and isinstance(target, str)):
                    continue
                conversion_map.setdefault((source, target), set())
                policy_id = entry.get("policy_id")
                if isinstance(policy_id, str):
                    conversion_map[(source, target)].add(policy_id)

        for policy_id in sorted(policies.keys()):
            pack = load_policy_pack(registry, policy_id, repo_root)
            matrices = (
                pack.get("downmix_policy_pack", {}).get("matrices", {})
                if isinstance(pack, dict)
                else {}
            )
            if not isinstance(matrices, dict):
                continue
            for matrix in matrices.values():
                if not isinstance(matrix, dict):
                    continue
                source = matrix.get("source_layout_id")
                target = matrix.get("target_layout_id")
                if not (isinstance(source, str) and isinstance(target, str)):
                    continue
                conversion_map.setdefault((source, target), set()).add(policy_id)

        conversion_rows: list[dict[str, object]] = []
        for (source, target) in sorted(conversion_map.keys()):
            conversion_rows.append(
                {
                    "source_layout_id": source,
                    "target_layout_id": target,
                    "policy_ids_available": sorted(conversion_map[(source, target)]),
                }
            )
        payload["conversions"] = conversion_rows

    return payload


def conversion_inventory_id(source_layout_id: str, target_layout_id: str) -> str:
    return f"{source_layout_id}->{target_layout_id}"


def extract_downmix_inventory_ids(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    layout_ids = [
        row.get("id")
        for row in payload.get("layouts", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    policy_ids = [
        row.get("id")
        for row in payload.get("policies", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    conversion_ids = [
        conversion_inventory_id(row["source_layout_id"], row["target_layout_id"])
        for row in payload.get("conversions", [])
        if isinstance(row, dict)
        and isinstance(row.get("source_layout_id"), str)
        and isinstance(row.get("target_layout_id"), str)
    ]
    return {
        "layouts": layout_ids,
        "policies": policy_ids,
        "conversions": conversion_ids,
    }
