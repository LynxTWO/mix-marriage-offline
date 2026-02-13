"""Generate preview-only scene and routing_plan drafts from a stems_map."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any


def _sorted_assignments(stems_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Return assignments sorted by (rel_path, file_id) for deterministic output."""
    assignments = stems_map.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("stems_map has no 'assignments' list")
    return sorted(
        assignments,
        key=lambda a: (a.get("rel_path", ""), a.get("file_id", "")),
    )


def _scene_id_hash(assignments: list[dict[str, Any]]) -> str:
    """Deterministic SHA-1 hash of sorted file_ids for the scene_id suffix."""
    file_ids = sorted(a.get("file_id", "") for a in assignments)
    combined = "|".join(file_ids)
    return hashlib.sha1(combined.encode("utf-8")).hexdigest()[:10]


def _assignment_notes(assignment: dict[str, Any]) -> list[str]:
    """Build notes list with bus_group and role_id for human context."""
    notes: list[str] = []
    bus_group = assignment.get("bus_group")
    if isinstance(bus_group, str) and bus_group:
        notes.append(f"bus_group: {bus_group}")
    role_id = assignment.get("role_id")
    if isinstance(role_id, str) and role_id:
        notes.append(f"role_id: {role_id}")
    return notes


def build_draft_scene(
    stems_map: dict[str, Any],
    *,
    stems_dir: str = "/DRAFT/stems",
) -> dict[str, Any]:
    """Build a preview-only scene payload from a classified stems_map.

    The result validates against scene.schema.json.  All defaults are
    conservative (single channel, neutral position, zero width/depth).
    """
    version = stems_map.get("version")
    if version != "0.1.0":
        raise ValueError(f"Unsupported stems_map version: {version!r}")

    assignments = _sorted_assignments(stems_map)
    scene_hash = _scene_id_hash(assignments)

    objects: list[dict[str, Any]] = []
    for idx, assignment in enumerate(assignments):
        rel_path = assignment.get("rel_path", "")
        label = PurePosixPath(rel_path).stem if rel_path else f"stem_{idx}"

        objects.append({
            "object_id": f"OBJ.{idx + 1:03d}",
            "stem_id": assignment.get("file_id", ""),
            "label": label,
            "channel_count": 1,
            "intent": {
                "confidence": assignment.get("confidence", 0.0),
                "locks": [],
                "position": {
                    "azimuth_deg": 0,
                    "elevation_deg": 0,
                },
                "width": 0,
                "depth": 0,
                "loudness_bias": "neutral",
            },
            "notes": _assignment_notes(assignment),
        })

    beds: list[dict[str, Any]] = [
        {
            "bed_id": "BED.001",
            "label": "Master bed",
            "kind": "bed",
            "intent": {
                "confidence": 0.5,
                "locks": [],
                "diffuse": 0.5,
            },
            "notes": ["Draft default bed — review before use."],
        },
    ]

    return {
        "schema_version": "0.1.0",
        "scene_id": f"SCENE.DRAFT.{scene_hash}",
        "source": {
            "stems_dir": stems_dir,
            "created_from": "draft",
        },
        "objects": objects,
        "beds": beds,
        "metadata": {},
    }


def build_draft_routing_plan(
    stems_map: dict[str, Any],
) -> dict[str, Any]:
    """Build a preview-only routing_plan payload from a classified stems_map.

    The result validates against routing_plan.schema.json.  All defaults are
    conservative (mono source, stereo target, center-panned).
    """
    version = stems_map.get("version")
    if version != "0.1.0":
        raise ValueError(f"Unsupported stems_map version: {version!r}")

    assignments = _sorted_assignments(stems_map)

    routes: list[dict[str, Any]] = []
    for assignment in assignments:
        routes.append({
            "stem_id": assignment.get("file_id", ""),
            "stem_channels": 1,
            "target_channels": 2,
            "mapping": [
                {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                {"src_ch": 0, "dst_ch": 1, "gain_db": 0.0},
            ],
            "notes": _assignment_notes(assignment),
        })

    return {
        "schema_version": "0.1.0",
        "source_layout_id": "LAYOUT.STEMS",
        "target_layout_id": "LAYOUT.2_0",
        "routes": routes,
    }
