from __future__ import annotations

from typing import Any

BUS_PLAN_SCHEMA = "mmo.bus_plan.v1"
DEFAULT_GENERATED_UTC = "1970-01-01T00:00:00Z"
_MASTER_BUS_ID = "BUS.MASTER"

_MAIN_GROUP_ORDER: tuple[str, ...] = (
    "DRUMS",
    "BASS",
    "MUSIC",
    "VOX",
    "FX",
    "OTHER",
)
_GROUP_SORT_RANK: dict[str, int] = {
    group: index for index, group in enumerate(_MAIN_GROUP_ORDER)
}


def _sorted_mapping_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts.keys())}


def _role_lookup(roles: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = roles.get("roles")
    if not isinstance(payload, dict):
        return {}
    return {
        role_id: entry
        for role_id, entry in payload.items()
        if isinstance(role_id, str) and role_id != "_meta" and isinstance(entry, dict)
    }


def _group_for_role(
    role_id: str,
    role_entry: dict[str, Any] | None,
    assignment: dict[str, Any],
) -> str:
    if role_id.startswith("ROLE.OTHER."):
        return "OTHER"

    raw_group: str | None = None
    if isinstance(role_entry, dict):
        value = role_entry.get("default_bus_group")
        if isinstance(value, str) and value.strip():
            raw_group = value.strip().upper()

    if raw_group is None:
        value = assignment.get("bus_group")
        if isinstance(value, str) and value.strip():
            raw_group = value.strip().upper()

    if raw_group in {"VOCAL", "VOCALS", "VOX", "DIALOGUE"}:
        return "VOX"
    if raw_group in {"SFX", "FX"}:
        return "FX"
    if raw_group in {"DRUMS", "BASS", "MUSIC"}:
        return raw_group

    # Fall back to the role family only when explicit grouping is absent. That
    # keeps older role data routable without adding a second grouping policy.
    if role_id.startswith("ROLE.DRUM."):
        return "DRUMS"
    if role_id.startswith("ROLE.BASS."):
        return "BASS"
    if role_id.startswith("ROLE.VOCAL."):
        return "VOX"
    if role_id.startswith("ROLE.DIALOGUE."):
        return "VOX"
    if role_id.startswith("ROLE.SFX."):
        return "FX"
    if role_id.startswith("ROLE.FX."):
        return "FX"

    return "OTHER"


def _role_suffix(role_id: str) -> str:
    if not isinstance(role_id, str) or not role_id.startswith("ROLE."):
        return "UNKNOWN"
    parts = [part for part in role_id.split(".") if part]
    if len(parts) < 2:
        return "UNKNOWN"

    if role_id.startswith("ROLE.SYNTH."):
        return "SYNTH"
    if role_id.startswith("ROLE.SFX."):
        return "SFX"

    return parts[-1].upper()


def _drum_consolidation_bus(role_id: str) -> str | None:
    normalized = role_id.upper()
    if normalized == "ROLE.DRUM.KICK":
        return "BUS.DRUMS.KICK"
    if normalized == "ROLE.DRUM.SNARE":
        return "BUS.DRUMS.SNARE"
    if normalized in {"ROLE.DRUM.TOM", "ROLE.DRUM.TOMS"}:
        return "BUS.DRUMS.TOMS"
    if normalized in {
        "ROLE.DRUM.HIHAT",
        "ROLE.DRUM.PERCUSSION",
        "ROLE.DRUM.CLAP",
        "ROLE.DRUM.LOOPS",
    }:
        return "BUS.DRUMS.PERC"
    if normalized in {
        "ROLE.DRUM.CYMBALS",
        "ROLE.DRUM.OVERHEADS",
    }:
        return "BUS.DRUMS.CYMBALS"
    return None


def _bus_id_for_assignment(
    role_id: str,
    role_entry: dict[str, Any] | None,
    assignment: dict[str, Any],
) -> str:
    # Honor explicit bus roles first so published bus IDs do not get renamed by
    # later consolidation rules.
    if role_id.startswith("ROLE.BUS."):
        parts = [part for part in role_id.split(".") if part]
        if len(parts) >= 3:
            group_candidate = parts[2].upper()
            if group_candidate in {"VOCALS", "VOCAL", "VOX", "DIALOGUE"}:
                return "BUS.VOX"
            if group_candidate in {"SFX", "FX"}:
                return "BUS.FX"
            if group_candidate == "MASTER":
                return _MASTER_BUS_ID
            if group_candidate in {"DRUMS", "BASS", "MUSIC"}:
                return f"BUS.{group_candidate}"

    drum_bus = _drum_consolidation_bus(role_id)
    if drum_bus is not None:
        return drum_bus

    # Bass stems collapse to one deterministic group bus so layered DI, amp,
    # and synth tracks do not drift into per-role child buses.
    if role_id.startswith("ROLE.BASS."):
        return "BUS.BASS"

    group = _group_for_role(role_id, role_entry, assignment)
    suffix = _role_suffix(role_id)
    return f"BUS.{group}.{suffix}"


def _label_for_bus(bus_id: str) -> str:
    if bus_id.startswith("BUS."):
        suffix = bus_id[4:]
    else:
        suffix = bus_id
    return suffix.replace(".", " ").title()


def _assignment_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    track_index = item.get("track_index")
    has_track = isinstance(track_index, (int, float)) and not isinstance(track_index, bool)
    rel_path = item.get("rel_path") if isinstance(item.get("rel_path"), str) else ""
    stem_id = item.get("stem_id") if isinstance(item.get("stem_id"), str) else ""
    # Use authored track order when present. rel_path and stem_id make the
    # fallback deterministic when track indices are missing.
    return (
        0 if has_track else 1,
        int(track_index) if has_track else 0,
        rel_path,
        stem_id,
    )


def _bus_sort_key(bus_id: str) -> tuple[int, int, str, str]:
    # Put master first, then parent groups, then children. That stable tree
    # order keeps bus-plan diffs readable even when upstream dict order moves.
    if bus_id == _MASTER_BUS_ID:
        return (-1, 0, "MASTER", bus_id)
    parts = bus_id.split(".")
    group = parts[1] if len(parts) > 1 else "OTHER"
    group_rank = _GROUP_SORT_RANK.get(group, len(_GROUP_SORT_RANK))
    is_parent = len(parts) == 2
    suffix = parts[-1] if parts else bus_id
    return (group_rank, 0 if is_parent else 1, suffix, bus_id)


def _bus_path(bus_id: str) -> str:
    if bus_id == _MASTER_BUS_ID:
        return bus_id
    if bus_id.count(".") == 1:
        return f"{_MASTER_BUS_ID}/{bus_id}"
    group = bus_id.split(".")[1]
    return f"{_MASTER_BUS_ID}/BUS.{group}/{bus_id}"


def build_bus_plan(stems_map: dict[str, Any], roles: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(stems_map, dict):
        raise ValueError("stems_map must be an object.")
    if not isinstance(roles, dict):
        raise ValueError("roles must be an object.")

    assignments_raw = stems_map.get("assignments")
    if not isinstance(assignments_raw, list):
        raise ValueError("stems_map.assignments must be an array.")

    sorted_assignments = sorted(
        [item for item in assignments_raw if isinstance(item, dict)],
        key=_assignment_sort_key,
    )
    # Build assignments, bus membership, and summary counts from the same sorted
    # stream so the receipt cannot disagree with itself about routing totals.

    role_entries = _role_lookup(roles)

    bus_to_stems: dict[str, list[str]] = {
        _MASTER_BUS_ID: [],
    }
    bus_children: dict[str, set[str]] = {
        _MASTER_BUS_ID: set(),
    }
    assignment_rows: list[dict[str, Any]] = []
    role_ids_for_counts: list[str] = []
    bus_ids_for_counts: list[str] = []

    for assignment in sorted_assignments:
        stem_id = assignment.get("stem_id") if isinstance(assignment.get("stem_id"), str) else ""
        file_path = assignment.get("rel_path") if isinstance(assignment.get("rel_path"), str) else ""
        role_id = assignment.get("role_id") if isinstance(assignment.get("role_id"), str) else "ROLE.OTHER.UNKNOWN"
        confidence_raw = assignment.get("confidence")
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float)) and not isinstance(confidence_raw, bool)
            else 0.0
        )

        role_entry = role_entries.get(role_id)
        bus_id = _bus_id_for_assignment(role_id, role_entry, assignment)
        group_bus_id = bus_id if bus_id.count(".") == 1 else "BUS." + bus_id.split(".")[1]

        if group_bus_id not in bus_to_stems:
            bus_to_stems[group_bus_id] = []
        if bus_id not in bus_to_stems:
            bus_to_stems[bus_id] = []

        bus_to_stems[_MASTER_BUS_ID].append(stem_id)
        if group_bus_id != _MASTER_BUS_ID:
            bus_to_stems[group_bus_id].append(stem_id)
        if bus_id != group_bus_id:
            bus_to_stems[bus_id].append(stem_id)

        if group_bus_id not in bus_children:
            bus_children[group_bus_id] = set()
        if group_bus_id != _MASTER_BUS_ID:
            bus_children[_MASTER_BUS_ID].add(group_bus_id)
        if bus_id != group_bus_id:
            bus_children[group_bus_id].add(bus_id)

        assignment_rows.append(
            {
                "stem_id": stem_id,
                "file_path": file_path,
                "role_id": role_id,
                "confidence": round(confidence, 3),
                "bus_id": bus_id,
                "bus_path": _bus_path(bus_id),
            }
        )
        role_ids_for_counts.append(role_id)
        bus_ids_for_counts.append(bus_id)

    for bus_id in list(bus_to_stems.keys()):
        if bus_id not in bus_children:
            bus_children[bus_id] = set()

    ordered_bus_ids = sorted(bus_to_stems.keys(), key=_bus_sort_key)
    buses: list[dict[str, Any]] = []
    for bus_id in ordered_bus_ids:
        parts = bus_id.split(".")
        parent_id: str | None
        if bus_id == _MASTER_BUS_ID:
            parent_id = None
        elif len(parts) == 2:
            parent_id = _MASTER_BUS_ID
        else:
            parent_id = "BUS." + parts[1]

        stem_ids = [stem for stem in bus_to_stems[bus_id] if isinstance(stem, str)]
        children = sorted(bus_children.get(bus_id, set()), key=_bus_sort_key)

        buses.append(
            {
                "bus_id": bus_id,
                "label": _label_for_bus(bus_id),
                "parent_id": parent_id,
                "children_ids": children,
                "stem_ids": stem_ids,
            }
        )

    source_roles_ref = stems_map.get("roles_ref")
    if not isinstance(source_roles_ref, str) or not source_roles_ref.strip():
        source_roles_ref = "ontology/roles.yaml"

    source_stems_map_ref = stems_map.get("stems_map_ref")
    if not isinstance(source_stems_map_ref, str) or not source_stems_map_ref.strip():
        source_stems_map_ref = "stems_map.json"

    return {
        "schema": BUS_PLAN_SCHEMA,
        "generated_utc": DEFAULT_GENERATED_UTC,
        "source": {
            "stems_map_ref": source_stems_map_ref,
            "roles_ref": source_roles_ref,
        },
        "buses": buses,
        "assignments": assignment_rows,
        "summary": {
            "role_counts": _sorted_mapping_counts(role_ids_for_counts),
            "bus_counts": _sorted_mapping_counts(bus_ids_for_counts),
        },
    }
