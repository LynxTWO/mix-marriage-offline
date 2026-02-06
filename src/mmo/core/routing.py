from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.dsp.downmix import load_layouts

ROUTING_PLAN_SCHEMA_VERSION = "0.1.0"
NO_SAFE_DEFAULT_MAPPING_NOTE = "No safe default mapping"
STEREO_FRONT_ONLY_NOTE = "Stereo routed to front L/R only"
MONO_STEREO_NOTE = "Mono routed equally to L/R at -3.0 dB each"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _safe_layout_channel_order(layout_id: str) -> list[str]:
    try:
        layouts = load_layouts(_repo_root() / "ontology" / "layouts.yaml")
    except (RuntimeError, ValueError):
        return []
    layout = layouts.get(layout_id)
    if not isinstance(layout, dict):
        return []
    channel_order = layout.get("channel_order")
    if not isinstance(channel_order, list):
        return []
    result: list[str] = []
    for item in channel_order:
        if isinstance(item, str) and item:
            result.append(item)
    return result


def _stems_sorted_for_routing(session: dict[str, Any]) -> list[dict[str, Any]]:
    stems_raw = session.get("stems")
    if not isinstance(stems_raw, list):
        return []

    rows: list[tuple[str, str, int, dict[str, Any]]] = []
    for index, stem in enumerate(stems_raw):
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id")).strip() or f"stem_{index:04d}"
        stem_file = _coerce_str(stem.get("file_path")).strip()
        rows.append((stem_id, stem_file, index, stem))

    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in rows]


def _mapping_entry(src_ch: int, dst_ch: int, gain_db: float = 0.0) -> dict[str, Any]:
    return {
        "src_ch": src_ch,
        "dst_ch": dst_ch,
        "gain_db": float(gain_db),
    }


def _mapping_sort_key(entry: dict[str, Any]) -> tuple[int, int]:
    return (_coerce_int(entry.get("src_ch")) or 0, _coerce_int(entry.get("dst_ch")) or 0)


def _speaker_index(channel_order: list[str], speaker_id: str) -> int | None:
    for index, candidate in enumerate(channel_order):
        if candidate == speaker_id:
            return index
    return None


def _front_lr_indices(target_channel_order: list[str], target_channels: int) -> tuple[int, int] | None:
    left = _speaker_index(target_channel_order, "SPK.L")
    right = _speaker_index(target_channel_order, "SPK.R")
    if left is None or right is None:
        if target_channels >= 2:
            return (0, 1)
        return None
    return (left, right)


def build_routing_plan(
    session: dict,
    source_layout_id: str,
    target_layout_id: str,
) -> dict:
    target_channel_order = _safe_layout_channel_order(target_layout_id)
    target_channels = len(target_channel_order)
    stems = _stems_sorted_for_routing(session if isinstance(session, dict) else {})

    routes: list[dict[str, Any]] = []
    for index, stem in enumerate(stems):
        stem_id = _coerce_str(stem.get("stem_id")).strip() or f"stem_{index:04d}"
        stem_channels = _coerce_int(stem.get("channel_count")) or 0
        if stem_channels < 0:
            stem_channels = 0

        mapping: list[dict[str, Any]] = []
        notes: list[str] = []

        if stem_channels > 0 and stem_channels == target_channels:
            for channel_index in range(stem_channels):
                mapping.append(_mapping_entry(channel_index, channel_index))
        elif stem_channels == 1 and target_channels == 2:
            front_lr = _front_lr_indices(target_channel_order, target_channels)
            if front_lr is None:
                notes.append(NO_SAFE_DEFAULT_MAPPING_NOTE)
            else:
                mapping.append(_mapping_entry(0, front_lr[0], -3.0))
                mapping.append(_mapping_entry(0, front_lr[1], -3.0))
                notes.append(MONO_STEREO_NOTE)
        elif stem_channels == 2 and target_channels in {6, 8}:
            front_lr = _front_lr_indices(target_channel_order, target_channels)
            if front_lr is None:
                notes.append(NO_SAFE_DEFAULT_MAPPING_NOTE)
            else:
                mapping.append(_mapping_entry(0, front_lr[0], 0.0))
                mapping.append(_mapping_entry(1, front_lr[1], 0.0))
                notes.append(STEREO_FRONT_ONLY_NOTE)
        else:
            notes.append(NO_SAFE_DEFAULT_MAPPING_NOTE)

        mapping.sort(key=_mapping_sort_key)
        routes.append(
            {
                "stem_id": stem_id,
                "stem_channels": stem_channels,
                "target_channels": target_channels,
                "mapping": mapping,
                "notes": notes,
            }
        )

    return {
        "schema_version": ROUTING_PLAN_SCHEMA_VERSION,
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "routes": routes,
    }


def _format_gain_db(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        if text in {"", "-0"}:
            return "0"
        return text
    return "0"


def format_routing_plan_text(plan: dict[str, Any]) -> str:
    source_layout_id = _coerce_str(plan.get("source_layout_id"))
    target_layout_id = _coerce_str(plan.get("target_layout_id"))
    lines = [f"Routing plan: {source_layout_id} -> {target_layout_id}"]

    routes = plan.get("routes")
    if not isinstance(routes, list):
        routes = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        stem_id = _coerce_str(route.get("stem_id"))
        stem_channels = _coerce_int(route.get("stem_channels")) or 0
        target_channels = _coerce_int(route.get("target_channels")) or 0
        lines.append(f"{stem_id}: stem_channels={stem_channels} target_channels={target_channels}")

        mapping = route.get("mapping")
        if isinstance(mapping, list) and mapping:
            for entry in mapping:
                if not isinstance(entry, dict):
                    continue
                src_ch = _coerce_int(entry.get("src_ch")) or 0
                dst_ch = _coerce_int(entry.get("dst_ch")) or 0
                gain_db = _format_gain_db(entry.get("gain_db", 0.0))
                lines.append(f"  {src_ch} -> {dst_ch}  gain_db={gain_db}")
        else:
            lines.append("  <no mapping>")

        notes = route.get("notes")
        if isinstance(notes, list):
            for note in notes:
                if isinstance(note, str) and note:
                    lines.append(f"  note: {note}")
    return "\n".join(lines) + "\n"


def render_routing_plan(plan: dict[str, Any], *, output_format: str = "json") -> str:
    if output_format == "json":
        return json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if output_format == "text":
        return format_routing_plan_text(plan)
    raise ValueError(f"Unsupported output format: {output_format}")


def routing_layout_ids_from_run_config(run_config: Any) -> tuple[str, str] | None:
    if not isinstance(run_config, dict):
        return None
    downmix_config = run_config.get("downmix")
    if not isinstance(downmix_config, dict):
        return None
    source_layout_id = _coerce_str(downmix_config.get("source_layout_id")).strip()
    target_layout_id = _coerce_str(downmix_config.get("target_layout_id")).strip()
    if not source_layout_id or not target_layout_id:
        return None
    return (source_layout_id, target_layout_id)


def apply_routing_plan_to_report(report: dict[str, Any], run_config: Any) -> None:
    layout_ids = routing_layout_ids_from_run_config(run_config)
    if layout_ids is None:
        report.pop("routing_plan", None)
        return
    session = report.get("session")
    if not isinstance(session, dict):
        session = {}
        report["session"] = session
    report["routing_plan"] = build_routing_plan(
        session,
        source_layout_id=layout_ids[0],
        target_layout_id=layout_ids[1],
    )
