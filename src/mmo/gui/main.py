"""CustomTkinter desktop GUI for MMO (offline + deterministic CLI wrapper)."""

from __future__ import annotations

import argparse
import importlib
import json
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from mmo.core.plugin_loader import default_user_plugins_dir
from mmo.core.plugin_market import (
    build_plugin_market_list_payload,
    install_plugin_market_entry,
)
from mmo.core.render_targets import list_render_targets
from mmo.core.speaker_layout import LayoutStandard
from mmo.core.target_tokens import resolve_target_token
from mmo.gui.dashboard import VisualizationDashboardPanel

try:  # Optional at import time so tests can run without GUI deps.
    import customtkinter as _ctk
except Exception:  # pragma: no cover - dependency/runtime environment specific
    _ctk = None

try:  # Optional drag/drop helper.
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - dependency/runtime environment specific
    DND_FILES = None
    TkinterDnD = None


_DEFAULT_PROFILE_ID = "PROFILE.ASSIST"
_DEFAULT_GUI_WORKSPACE = "_mmo_gui"
_DEFAULT_GUI_STEMS_MAP = "stems_map.json"
_DEFAULT_GUI_BUS_PLAN = "bus_plan.json"
_DEFAULT_GUI_BUS_PLAN_CSV = "bus_plan.summary.csv"
_DEFAULT_GUI_SCENE = "scene.json"
_DEFAULT_GUI_SCENE_LINT = "scene_lint.json"
_DEFAULT_RENDER_MANY_TARGET_IDS: tuple[str, ...] = (
    "TARGET.STEREO.2_0",
    "TARGET.SURROUND.5_1",
    "TARGET.SURROUND.7_1",
)
_ISSUE_RENDER_NO_OUTPUTS = "ISSUE.RENDER.NO_OUTPUTS"
_NO_OUTPUTS_BANNER_TEXT = (
    "No audio outputs were written. This build may not include a mixdown renderer yet."
)
_DEFAULT_SCENE_SUMMARY_TEXT = (
    "Perspective:\n"
    "- (pending analyze)\n\n"
    "Objects (azimuth/width/depth/confidence):\n"
    "- (pending analyze)\n\n"
    "Bed buses:\n"
    "- (pending analyze)\n\n"
    "Scene lint warnings:\n"
    "- (pending analyze)"
)
_STUDIO_THEME: Mapping[str, str] = {
    "bg": "#0A0A09",
    "hero": "#13110E",
    "hero_edge": "#2B2318",
    "hero_text": "#F2E8D2",
    "hero_muted": "#C6B08C",
    "surface": "#13110F",
    "surface_edge": "#2B2318",
    "text": "#F2E8D2",
    "text_muted": "#B59F7F",
    "accent": "#D79B48",
    "accent_hover": "#C48735",
    "accent_cool": "#5DA4A0",
    "danger": "#B44A3A",
    "danger_hover": "#913729",
    "panel": "#0B0A09",
    "panel_edge": "#2A2219",
}
_FONT_UI = "Inter"
_FONT_DISPLAY = "Space Grotesk"
_FONT_MONO = "Consolas"
_DISCOVER_GRADIENTS: Mapping[str, tuple[str, str, str, str]] = {
    "ember": ("#21110A", "#60311A", "#F0B469", "#F8ECD2"),
    "tide": ("#0E1D1F", "#16484D", "#78D8D2", "#DCF7F4"),
    "sunset": ("#1E130D", "#5D2E1A", "#F0A265", "#FFE9D5"),
}
_DISCOVER_TYPE_GRADIENT: Mapping[str, str] = {
    "detector": "ember",
    "resolver": "tide",
    "renderer": "sunset",
}
_TARGET_PICKER_LABELS_BY_ID: Mapping[str, str] = {
    "TARGET.FRONT.3_0": "LCR (3.0)",
    "TARGET.FRONT.3_1": "LCR + LFE (3.1)",
    "TARGET.HEADPHONES.BINAURAL": "Binaural (headphones)",
    "TARGET.STEREO.2_0": "Stereo (2.0)",
    "TARGET.STEREO.2_1": "Stereo + LFE (2.1)",
    "TARGET.SURROUND.4_0": "Quad (4.0)",
    "TARGET.SURROUND.4_1": "Quad + LFE (4.1)",
    "TARGET.SURROUND.5_1": "Surround (5.1)",
    "TARGET.SURROUND.7_1": "Surround (7.1)",
}


@dataclass(frozen=True)
class GuiRunConfig:
    stems_dir: Path
    out_dir: Path
    target_id: str
    render_many: bool
    render_many_target_ids: tuple[str, ...]
    layout_standard: str
    preview_headphones: bool
    plugins_dir: Path
    profile_id: str = _DEFAULT_PROFILE_ID


@dataclass(frozen=True)
class GuiPipelinePaths:
    report_path: Path
    dry_receipt_path: Path
    final_receipt_path: Path
    dry_manifest_path: Path
    final_manifest_path: Path
    cancel_token_path: Path


@dataclass(frozen=True)
class PluginDiscoverCard:
    plugin_id: str
    plugin_type: str
    name: str
    version: str
    summary: str
    tags: tuple[str, ...]
    preview_tagline: str
    preview_gradient: str
    preview_chips: tuple[str, ...]
    install_state: str
    installable: bool


def _as_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _target_picker_label(target_id: str) -> str:
    normalized_target_id = target_id.strip()
    if not normalized_target_id:
        return ""
    return _TARGET_PICKER_LABELS_BY_ID.get(normalized_target_id, normalized_target_id)


def _build_target_picker_map(target_ids: Sequence[str]) -> dict[str, str]:
    picker_map: dict[str, str] = {}
    for target_id in target_ids:
        normalized_target_id = target_id.strip() if isinstance(target_id, str) else ""
        if not normalized_target_id:
            continue
        label = _target_picker_label(normalized_target_id)
        if not label:
            continue
        if label in picker_map and picker_map[label] != normalized_target_id:
            # Preserve deterministic and unambiguous selection entries.
            picker_map[normalized_target_id] = normalized_target_id
            continue
        picker_map[label] = normalized_target_id
    return picker_map


def _discover_gradient_for_type(plugin_type: str) -> str:
    normalized = plugin_type.strip().casefold() if isinstance(plugin_type, str) else ""
    return _DISCOVER_TYPE_GRADIENT.get(normalized, "ember")


def _normalized_preview(
    entry: Mapping[str, Any],
    *,
    plugin_type: str,
    summary: str,
    tags: tuple[str, ...],
) -> tuple[str, str, tuple[str, ...]]:
    preview = entry.get("preview")
    default_gradient = _discover_gradient_for_type(plugin_type)
    default_tagline = summary or "Offline-ready plugin card."
    default_chips = tags[:3]

    if not isinstance(preview, Mapping):
        return (default_tagline, default_gradient, default_chips)

    raw_tagline = preview.get("tagline")
    tagline = raw_tagline.strip() if isinstance(raw_tagline, str) and raw_tagline.strip() else default_tagline

    raw_gradient = preview.get("gradient")
    gradient = (
        raw_gradient.strip().casefold()
        if isinstance(raw_gradient, str) and raw_gradient.strip()
        else default_gradient
    )
    if gradient not in _DISCOVER_GRADIENTS:
        gradient = default_gradient

    chips: list[str] = []
    seen: set[str] = set()
    raw_chips = preview.get("chips")
    if isinstance(raw_chips, list):
        for raw_chip in raw_chips:
            if not isinstance(raw_chip, str):
                continue
            chip = raw_chip.strip()
            if not chip:
                continue
            dedupe_key = chip.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chips.append(chip)

    if not chips:
        chips = list(default_chips)
    return (tagline, gradient, tuple(chips[:4]))


def build_plugin_discover_cards(payload: Mapping[str, Any]) -> tuple[PluginDiscoverCard, ...]:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return ()

    cards: list[PluginDiscoverCard] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            continue
        plugin_id = str(raw_entry.get("plugin_id", "")).strip()
        if not plugin_id:
            continue
        plugin_type = str(raw_entry.get("plugin_type", "")).strip() or "unknown"
        name = str(raw_entry.get("name", "")).strip() or plugin_id
        version = str(raw_entry.get("version", "")).strip() or "-"
        summary = str(raw_entry.get("summary", "")).strip()

        tags_raw = raw_entry.get("tags")
        if isinstance(tags_raw, list):
            tags = tuple(
                item.strip()
                for item in tags_raw
                if isinstance(item, str) and item.strip()
            )
        else:
            tags = ()
        preview_tagline, preview_gradient, preview_chips = _normalized_preview(
            raw_entry,
            plugin_type=plugin_type,
            summary=summary,
            tags=tags,
        )
        install_state = str(raw_entry.get("install_state", "")).strip().casefold() or "available"
        installable = bool(raw_entry.get("installable"))
        cards.append(
            PluginDiscoverCard(
                plugin_id=plugin_id,
                plugin_type=plugin_type,
                name=name,
                version=version,
                summary=summary,
                tags=tags,
                preview_tagline=preview_tagline,
                preview_gradient=preview_gradient,
                preview_chips=preview_chips,
                install_state=install_state,
                installable=installable,
            )
        )

    return tuple(sorted(cards, key=lambda row: (row.plugin_id, row.plugin_type, row.version)))


def layout_standard_options() -> tuple[str, ...]:
    return tuple(standard.value for standard in LayoutStandard)


def normalize_layout_standard(raw: str) -> str:
    candidate = raw.strip().upper() if isinstance(raw, str) else ""
    valid = set(layout_standard_options())
    return candidate if candidate in valid else LayoutStandard.SMPTE.value


def render_target_layout_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in list_render_targets():
        if not isinstance(row, dict):
            continue
        target_id = row.get("target_id")
        layout_id = row.get("layout_id")
        if isinstance(target_id, str) and isinstance(layout_id, str):
            target_id_clean = target_id.strip()
            layout_id_clean = layout_id.strip()
            if target_id_clean and layout_id_clean and target_id_clean not in mapping:
                mapping[target_id_clean] = layout_id_clean
    return {target_id: mapping[target_id] for target_id in sorted(mapping)}


def _layout_from_target_token(
    token: str,
    target_layouts: Mapping[str, str],
) -> str:
    stripped = token.strip()
    if not stripped:
        return ""
    try:
        return resolve_target_token(stripped).layout_id
    except ValueError:
        # Keep deterministic fallback behavior for injected GUI test maps.
        return target_layouts.get(stripped, "")


def normalize_render_many_layout_ids(
    target_tokens: Sequence[str],
    *,
    target_layouts: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    resolved_layouts: set[str] = set()
    layout_map = target_layouts or render_target_layout_map()
    for token in target_tokens:
        if not isinstance(token, str):
            continue
        layout_id = _layout_from_target_token(token, layout_map)
        if layout_id:
            resolved_layouts.add(layout_id)

    if not resolved_layouts:
        fallback_layouts = {
            _layout_from_target_token(token, layout_map)
            for token in _DEFAULT_RENDER_MANY_TARGET_IDS
        }
        fallback_layouts.discard("")
        if fallback_layouts:
            return tuple(sorted(fallback_layouts))
        return ("LAYOUT.2_0",)
    return tuple(sorted(resolved_layouts))


def resolve_single_target_layout_id(
    target_token: str,
    *,
    target_layouts: Mapping[str, str] | None = None,
) -> str:
    layout_map = target_layouts or render_target_layout_map()
    layout_id = _layout_from_target_token(target_token, layout_map)
    return layout_id or "LAYOUT.2_0"


def build_pipeline_paths(workspace_dir: Path) -> GuiPipelinePaths:
    return GuiPipelinePaths(
        report_path=workspace_dir / "report.json",
        dry_receipt_path=workspace_dir / "safe_render.dry_receipt.json",
        final_receipt_path=workspace_dir / "safe_render.receipt.json",
        dry_manifest_path=workspace_dir / "safe_render.dry_manifest.json",
        final_manifest_path=workspace_dir / "safe_render.render_manifest.json",
        cancel_token_path=workspace_dir / "safe_render.cancel",
    )


def build_analyze_cli_argv(
    config: GuiRunConfig,
    paths: GuiPipelinePaths,
) -> list[str]:
    return [
        "analyze",
        _as_posix(config.stems_dir),
        "--out-report",
        _as_posix(paths.report_path),
        "--plugins",
        _as_posix(config.plugins_dir),
        "--profile",
        config.profile_id,
    ]


def gui_stems_map_path(workspace_dir: Path) -> Path:
    return workspace_dir / _DEFAULT_GUI_STEMS_MAP


def gui_bus_plan_path(workspace_dir: Path) -> Path:
    return workspace_dir / _DEFAULT_GUI_BUS_PLAN


def gui_bus_plan_csv_path(workspace_dir: Path) -> Path:
    return workspace_dir / _DEFAULT_GUI_BUS_PLAN_CSV


def gui_scene_path(workspace_dir: Path) -> Path:
    return workspace_dir / _DEFAULT_GUI_SCENE


def gui_scene_lint_path(workspace_dir: Path) -> Path:
    return workspace_dir / _DEFAULT_GUI_SCENE_LINT


def build_stems_classify_cli_argv(
    config: GuiRunConfig,
    *,
    workspace_dir: Path,
) -> list[str]:
    return [
        "stems",
        "classify",
        "--root",
        _as_posix(config.stems_dir),
        "--out",
        _as_posix(gui_stems_map_path(workspace_dir)),
    ]


def build_stems_bus_plan_cli_argv(
    *,
    workspace_dir: Path,
) -> list[str]:
    return [
        "stems",
        "bus-plan",
        "--map",
        _as_posix(gui_stems_map_path(workspace_dir)),
        "--out",
        _as_posix(gui_bus_plan_path(workspace_dir)),
        "--csv",
        _as_posix(gui_bus_plan_csv_path(workspace_dir)),
    ]


def build_scene_build_cli_argv(
    config: GuiRunConfig,
    *,
    workspace_dir: Path,
) -> list[str]:
    return [
        "scene",
        "build",
        "--map",
        _as_posix(gui_stems_map_path(workspace_dir)),
        "--bus",
        _as_posix(gui_bus_plan_path(workspace_dir)),
        "--out",
        _as_posix(gui_scene_path(workspace_dir)),
        "--profile",
        config.profile_id,
    ]


def build_scene_lint_cli_argv(
    *,
    workspace_dir: Path,
) -> list[str]:
    return [
        "scene",
        "lint",
        "--scene",
        _as_posix(gui_scene_path(workspace_dir)),
        "--out",
        _as_posix(gui_scene_lint_path(workspace_dir)),
    ]


def _bus_plan_count_items(counts_payload: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(counts_payload, Mapping):
        return ()
    rows: list[tuple[str, int]] = []
    for raw_key, raw_value in counts_payload.items():
        if not isinstance(raw_key, str):
            continue
        if not isinstance(raw_value, int):
            continue
        rows.append((raw_key, raw_value))
    return tuple(sorted(rows, key=lambda row: row[0]))


def bus_plan_role_count_items(bus_plan_payload: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    summary_payload = bus_plan_payload.get("summary")
    if not isinstance(summary_payload, Mapping):
        return ()
    return _bus_plan_count_items(summary_payload.get("role_counts"))


def bus_plan_tree_lines(bus_plan_payload: Mapping[str, Any]) -> tuple[str, ...]:
    buses_payload = bus_plan_payload.get("buses")
    if not isinstance(buses_payload, list):
        return ()

    ordered_bus_ids: list[str] = []
    bus_by_id: dict[str, Mapping[str, Any]] = {}
    parent_by_id: dict[str, str | None] = {}
    children_by_id: dict[str, tuple[str, ...]] = {}

    for row in buses_payload:
        if not isinstance(row, Mapping):
            continue
        bus_id = row.get("bus_id")
        if not isinstance(bus_id, str) or not bus_id.strip():
            continue
        cleaned_bus_id = bus_id.strip()
        ordered_bus_ids.append(cleaned_bus_id)
        bus_by_id[cleaned_bus_id] = row

    for bus_id in ordered_bus_ids:
        row = bus_by_id[bus_id]
        raw_parent = row.get("parent_id")
        parent_id = raw_parent.strip() if isinstance(raw_parent, str) and raw_parent.strip() else None
        parent_by_id[bus_id] = parent_id

        raw_children = row.get("children_ids")
        if isinstance(raw_children, list):
            children = tuple(
                child.strip()
                for child in raw_children
                if isinstance(child, str) and child.strip()
            )
        else:
            children = ()
        children_by_id[bus_id] = children

    root_ids = [
        bus_id
        for bus_id in ordered_bus_ids
        if parent_by_id.get(bus_id) is None
    ]
    if not root_ids:
        root_ids = ordered_bus_ids[:]

    lines: list[str] = []
    visited: set[str] = set()

    def _walk(bus_id: str, depth: int) -> None:
        if bus_id in visited:
            return
        visited.add(bus_id)
        row = bus_by_id.get(bus_id)
        if row is None:
            return
        raw_stem_ids = row.get("stem_ids")
        stem_count = (
            len([item for item in raw_stem_ids if isinstance(item, str)])
            if isinstance(raw_stem_ids, list)
            else 0
        )
        indent = "  " * max(depth, 0)
        lines.append(f"{indent}- {bus_id} ({stem_count} stems)")
        for child_id in children_by_id.get(bus_id, ()):
            if child_id in bus_by_id:
                _walk(child_id, depth + 1)

    for root_id in root_ids:
        _walk(root_id, depth=0)

    for bus_id in ordered_bus_ids:
        if bus_id not in visited:
            _walk(bus_id, depth=0)

    return tuple(lines)


def render_bus_plan_summary_text(bus_plan_payload: Mapping[str, Any]) -> str:
    role_items = bus_plan_role_count_items(bus_plan_payload)
    tree_rows = bus_plan_tree_lines(bus_plan_payload)

    lines = ["Role counts:"]
    if role_items:
        for role_id, count in role_items:
            lines.append(f"- {role_id}: {count}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("Bus tree:")
    if tree_rows:
        lines.extend(tree_rows)
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _scene_numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _scene_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _scene_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scene_fmt(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def _scene_first_numeric(*values: Any) -> float | None:
    for value in values:
        numeric = _scene_numeric_value(value)
        if numeric is not None:
            return numeric
    return None


def _scene_object_rows(scene_payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    objects_payload = scene_payload.get("objects")
    if not isinstance(objects_payload, list):
        return ()

    rows: list[dict[str, Any]] = []
    for item in objects_payload:
        if not isinstance(item, Mapping):
            continue
        object_id = _scene_str(item.get("object_id"))
        if not object_id:
            continue
        intent_payload = _scene_mapping(item.get("intent"))
        position_payload = _scene_mapping(intent_payload.get("position"))
        rows.append(
            {
                "object_id": object_id,
                "label": _scene_str(item.get("label")) or object_id,
                "role_id": _scene_str(item.get("role_id")),
                "group_bus": _scene_str(item.get("group_bus")),
                "azimuth": _scene_first_numeric(
                    position_payload.get("azimuth_deg"),
                    item.get("azimuth_hint"),
                ),
                "width": _scene_first_numeric(
                    intent_payload.get("width"),
                    item.get("width_hint"),
                ),
                "depth": _scene_first_numeric(
                    intent_payload.get("depth"),
                    item.get("depth_hint"),
                ),
                "confidence": _scene_first_numeric(
                    intent_payload.get("confidence"),
                    item.get("confidence"),
                ),
            }
        )
    rows.sort(key=lambda row: (_scene_str(row.get("object_id")), _scene_str(row.get("label"))))
    return tuple(rows)


def _scene_bed_rows(scene_payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    beds_payload = scene_payload.get("beds")
    if not isinstance(beds_payload, list):
        return ()

    rows: list[dict[str, Any]] = []
    for item in beds_payload:
        if not isinstance(item, Mapping):
            continue
        bed_id = _scene_str(item.get("bed_id"))
        bus_id = _scene_str(item.get("bus_id"))
        if not bed_id and not bus_id:
            continue
        intent_payload = _scene_mapping(item.get("intent"))
        notes_payload = item.get("notes")
        note = ""
        if isinstance(notes_payload, list):
            note = next(
                (
                    _scene_str(raw_note)
                    for raw_note in notes_payload
                    if isinstance(raw_note, str) and _scene_str(raw_note)
                ),
                "",
            )
        rows.append(
            {
                "bed_id": bed_id or bus_id,
                "bus_id": bus_id,
                "label": _scene_str(item.get("label")) or (bed_id or bus_id),
                "kind": _scene_str(item.get("kind")),
                "confidence": _scene_first_numeric(
                    intent_payload.get("confidence"),
                    item.get("confidence"),
                ),
                "content_hint": _scene_str(item.get("content_hint")),
                "note": note,
            }
        )
    rows.sort(
        key=lambda row: (
            _scene_str(row.get("bus_id")),
            _scene_str(row.get("bed_id")),
            _scene_str(row.get("label")),
        )
    )
    return tuple(rows)


def _scene_lint_warning_rows(lint_payload: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    issues_payload = lint_payload.get("issues")
    if not isinstance(issues_payload, list):
        return ()

    rows: list[dict[str, str]] = []
    for issue in issues_payload:
        if not isinstance(issue, Mapping):
            continue
        severity = _scene_str(issue.get("severity")).casefold()
        if severity not in {"warn", "warning"}:
            continue
        issue_id = _scene_str(issue.get("issue_id"))
        message = _scene_str(issue.get("message"))
        path = _scene_str(issue.get("path"))
        if not issue_id:
            continue
        rows.append(
            {
                "issue_id": issue_id,
                "path": path,
                "message": message,
            }
        )
    rows.sort(
        key=lambda row: (
            _scene_str(row.get("issue_id")),
            _scene_str(row.get("path")),
            _scene_str(row.get("message")),
        )
    )
    return tuple(rows)


def render_scene_summary_text(
    scene_payload: Mapping[str, Any],
    *,
    lint_payload: Mapping[str, Any] | None = None,
) -> str:
    scene_intent = _scene_mapping(scene_payload.get("intent"))
    perspective = _scene_str(scene_intent.get("perspective")) or "(unspecified)"
    perspective_confidence = _scene_numeric_value(scene_intent.get("confidence"))
    object_rows = _scene_object_rows(scene_payload)
    bed_rows = _scene_bed_rows(scene_payload)
    lint_summary = _scene_mapping(lint_payload.get("summary")) if isinstance(lint_payload, Mapping) else {}
    lint_warning_rows = (
        _scene_lint_warning_rows(lint_payload)
        if isinstance(lint_payload, Mapping)
        else ()
    )

    lines = ["Perspective:"]
    perspective_line = f"- {perspective}"
    if perspective_confidence is not None:
        perspective_line = (
            f"{perspective_line} (confidence={_scene_fmt(perspective_confidence, digits=2)})"
        )
    lines.append(perspective_line)

    lines.extend(["", "Objects (azimuth/width/depth/confidence):"])
    if object_rows:
        for row in object_rows:
            parts = [
                f"{row['label']} [{row['object_id']}]",
                f"azimuth={_scene_fmt(row.get('azimuth'), digits=1, suffix=' deg')}",
                f"width={_scene_fmt(row.get('width'), digits=2)}",
                f"depth={_scene_fmt(row.get('depth'), digits=2)}",
                f"confidence={_scene_fmt(row.get('confidence'), digits=2)}",
            ]
            role_id = _scene_str(row.get("role_id"))
            if role_id:
                parts.append(f"role={role_id}")
            group_bus = _scene_str(row.get("group_bus"))
            if group_bus:
                parts.append(f"bus={group_bus}")
            lines.append(f"- {' | '.join(parts)}")
    else:
        lines.append("- (none)")

    lines.extend(["", "Bed buses:"])
    if bed_rows:
        for row in bed_rows:
            bus_id = _scene_str(row.get("bus_id")) or "(no bus)"
            parts = [
                f"{bus_id} <- {row['label']} [{row['bed_id']}]",
                f"confidence={_scene_fmt(row.get('confidence'), digits=2)}",
            ]
            kind = _scene_str(row.get("kind"))
            if kind:
                parts.append(f"kind={kind}")
            content_hint = _scene_str(row.get("content_hint"))
            if content_hint:
                parts.append(f"hint={content_hint}")
            note = _scene_str(row.get("note"))
            if note:
                parts.append(f"note={note}")
            lines.append(f"- {' | '.join(parts)}")
    else:
        lines.append("- (none)")

    lines.extend(["", "Scene lint warnings:"])
    error_count = lint_summary.get("error_count")
    warn_count = lint_summary.get("warn_count")
    if isinstance(error_count, int) and isinstance(warn_count, int):
        lines.append(f"- summary: {error_count} error(s), {warn_count} warning(s)")
    if lint_payload is None:
        lines.append("- (scene lint report unavailable)")
    elif lint_warning_rows:
        for row in lint_warning_rows:
            path = _scene_str(row.get("path"))
            prefix = f"{row['issue_id']} {path}".strip()
            message = _scene_str(row.get("message"))
            if message:
                lines.append(f"- {prefix}: {message}")
            else:
                lines.append(f"- {prefix}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def build_watch_cli_argv(
    watch_dir: Path,
    *,
    out_dir: Path | None = None,
    target_ids: Sequence[str] = _DEFAULT_RENDER_MANY_TARGET_IDS,
    once: bool = False,
    include_existing: bool = True,
    visual_queue: bool = False,
    cinematic_progress: bool = False,
) -> list[str]:
    argv = [
        "watch",
        _as_posix(watch_dir),
    ]

    if out_dir is not None:
        argv.extend(["--out", _as_posix(out_dir)])

    normalized_target_ids = [
        token.strip()
        for token in target_ids
        if isinstance(token, str) and token.strip()
    ]
    if normalized_target_ids:
        argv.extend(["--targets", ",".join(normalized_target_ids)])

    if once:
        argv.append("--once")
    if not include_existing:
        argv.append("--no-existing")
    if visual_queue:
        argv.append("--visual-queue")
    if cinematic_progress:
        argv.append("--cinematic-progress")

    return argv


def build_safe_render_cli_argv(
    config: GuiRunConfig,
    paths: GuiPipelinePaths,
    *,
    dry_run: bool,
    approve: str | None,
    live_progress: bool = False,
    cancel_file: Path | None = None,
) -> list[str]:
    target_layouts = render_target_layout_map()
    argv: list[str] = [
        "safe-render",
        "--report",
        _as_posix(paths.report_path),
        "--plugins",
        _as_posix(config.plugins_dir),
        "--profile",
        config.profile_id,
        "--layout-standard",
        normalize_layout_standard(config.layout_standard),
        "--out-dir",
        _as_posix(config.out_dir),
        "--out-manifest",
        _as_posix(paths.dry_manifest_path if dry_run else paths.final_manifest_path),
        "--receipt-out",
        _as_posix(paths.dry_receipt_path if dry_run else paths.final_receipt_path),
        "--force",
    ]

    if dry_run:
        argv.append("--dry-run")

    if config.render_many:
        layout_ids = normalize_render_many_layout_ids(
            config.render_many_target_ids,
            target_layouts=target_layouts,
        )
        argv.extend(
            [
                "--render-many",
                "--render-many-targets",
                ",".join(layout_ids),
            ]
        )
    else:
        argv.extend(
            [
                "--target",
                resolve_single_target_layout_id(
                    config.target_id,
                    target_layouts=target_layouts,
                ),
            ]
        )

    if isinstance(approve, str) and approve.strip():
        argv.extend(["--approve", approve.strip()])
    if live_progress:
        argv.append("--live-progress")
    if cancel_file is not None:
        argv.extend(["--cancel-file", _as_posix(cancel_file)])
    if config.preview_headphones:
        argv.append("--preview-headphones")
    return argv


def build_pipeline_cli_argvs(
    config: GuiRunConfig,
    *,
    workspace_dir: Path,
    approve: str | None = None,
) -> tuple[list[str], list[str], list[str], GuiPipelinePaths]:
    paths = build_pipeline_paths(workspace_dir)
    analyze_argv = build_analyze_cli_argv(config, paths)
    dry_run_argv = build_safe_render_cli_argv(
        config,
        paths,
        dry_run=True,
        approve=None,
        live_progress=True,
        cancel_file=paths.cancel_token_path,
    )
    final_argv = build_safe_render_cli_argv(
        config,
        paths,
        dry_run=False,
        approve=approve,
        live_progress=True,
        cancel_file=paths.cancel_token_path,
    )
    return analyze_argv, dry_run_argv, final_argv, paths


def build_python_command(
    cli_argv: Sequence[str],
    *,
    python_executable: str | None = None,
) -> list[str]:
    executable = python_executable or sys.executable
    return [executable, "-m", "mmo", *cli_argv]


def has_high_risk_blocked_recommendations(receipt_payload: Mapping[str, Any]) -> bool:
    blocked = receipt_payload.get("blocked_recommendations")
    if not isinstance(blocked, list):
        return False
    for row in blocked:
        if not isinstance(row, Mapping):
            continue
        risk = row.get("risk")
        if isinstance(risk, str) and risk.strip().casefold() == "high":
            return True
    return False


def has_issue_in_receipt_qa(
    receipt_payload: Mapping[str, Any],
    *,
    issue_id: str,
) -> bool:
    qa_issues = receipt_payload.get("qa_issues")
    if not isinstance(qa_issues, list):
        return False
    for issue in qa_issues:
        if not isinstance(issue, Mapping):
            continue
        current_issue_id = issue.get("issue_id")
        if isinstance(current_issue_id, str) and current_issue_id.strip() == issue_id:
            return True
    return False


def has_no_outputs_issue(receipt_payload: Mapping[str, Any]) -> bool:
    return has_issue_in_receipt_qa(
        receipt_payload,
        issue_id=_ISSUE_RENDER_NO_OUTPUTS,
    )


if _ctk is not None and TkinterDnD is not None and hasattr(TkinterDnD, "DnDWrapper"):

    class _DropEnabledCTk(_ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[misc]
        pass

else:

    class _DropEnabledCTk(_ctk.CTk if _ctk is not None else object):  # type: ignore[misc]
        pass


class _MMOGuiApp(_DropEnabledCTk):  # pragma: no cover - GUI runtime path
    def __init__(self) -> None:
        super().__init__()
        self.title("MMO StudioConsole Noir")
        self.geometry("1360x840")
        self.minsize(1100, 740)
        self.configure(fg_color=_STUDIO_THEME["bg"])

        self._worker_thread: threading.Thread | None = None
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None
        self._cancel_file_path: Path | None = None
        self._dashboard_panel: VisualizationDashboardPanel | None = None
        self._discover_cards_frame: Any | None = None
        self._discover_status_var = _ctk.StringVar(value="Offline plugin hub ready.")
        self._discover_install_buttons: dict[str, Any] = {}
        self._discover_installing_ids: set[str] = set()
        self._warning_receipt_path: Path | None = None

        self._target_layouts = render_target_layout_map()
        self._target_ids = tuple(sorted(self._target_layouts))
        if not self._target_ids:
            self._target_ids = ("TARGET.STEREO.2_0",)
        self._target_picker_map = _build_target_picker_map(self._target_ids)
        if not self._target_picker_map:
            self._target_picker_map = {"TARGET.STEREO.2_0": "TARGET.STEREO.2_0"}
        self._target_picker_values = tuple(sorted(self._target_picker_map))
        default_target_id = (
            "TARGET.STEREO.2_0"
            if "TARGET.STEREO.2_0" in self._target_ids
            else self._target_ids[0]
        )
        default_target_label = _target_picker_label(default_target_id)
        if default_target_label not in self._target_picker_map:
            default_target_label = self._target_picker_values[0]

        self._stems_var = _ctk.StringVar(value="")
        self._out_var = _ctk.StringVar(value=_as_posix(Path.cwd() / "mmo_gui_out"))
        self._plugins_var = _ctk.StringVar(value=_as_posix(Path("plugins")))
        self._target_var = _ctk.StringVar(value=default_target_label)
        self._render_many_var = _ctk.BooleanVar(value=True)
        self._render_many_targets_var = _ctk.StringVar(
            value=",".join(_DEFAULT_RENDER_MANY_TARGET_IDS)
        )
        self._layout_standard_var = _ctk.StringVar(value=LayoutStandard.SMPTE.value)
        self._profile_var = _ctk.StringVar(value=_DEFAULT_PROFILE_ID)
        self._status_var = _ctk.StringVar(value="Ready.")
        self._progress_var = _ctk.DoubleVar(value=0.0)

        self._build_layout()
        self._wire_drag_drop()
        self._sync_render_many_widgets()

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(1, weight=1)

        hero = _ctk.CTkFrame(
            self,
            fg_color=_STUDIO_THEME["hero"],
            corner_radius=18,
            border_width=1,
            border_color=_STUDIO_THEME["hero_edge"],
        )
        hero.grid(row=0, column=0, columnspan=2, padx=18, pady=(18, 10), sticky="nsew")
        hero.grid_columnconfigure(0, weight=1)
        _ctk.CTkLabel(
            hero,
            text="MMO StudioConsole Noir",
            font=(_FONT_DISPLAY, 30, "bold"),
            text_color=_STUDIO_THEME["hero_text"],
        ).grid(row=0, column=0, padx=20, pady=(16, 2), sticky="w")
        _ctk.CTkLabel(
            hero,
            text=(
                "Offline + deterministic. Shape the mix in one canvas: feel, evidence, and "
                "bounded authority approval."
            ),
            font=(_FONT_UI, 15),
            text_color=_STUDIO_THEME["hero_muted"],
        ).grid(row=1, column=0, padx=20, pady=(0, 16), sticky="w")

        controls = _ctk.CTkFrame(
            self,
            fg_color=_STUDIO_THEME["surface"],
            corner_radius=18,
            border_width=1,
            border_color=_STUDIO_THEME["surface_edge"],
        )
        controls.grid(row=1, column=0, padx=(18, 9), pady=(0, 18), sticky="nsew")
        controls.grid_columnconfigure(0, weight=1)

        _ctk.CTkLabel(
            controls,
            text="Inputs",
            font=(_FONT_DISPLAY, 20, "bold"),
            text_color=_STUDIO_THEME["text"],
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        self._drop_zone = _ctk.CTkFrame(
            controls,
            fg_color=_STUDIO_THEME["panel"],
            border_color=_STUDIO_THEME["panel_edge"],
            border_width=2,
            corner_radius=14,
        )
        self._drop_zone.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        self._drop_zone.grid_columnconfigure(0, weight=1)
        self._drop_hint = _ctk.CTkLabel(
            self._drop_zone,
            text="Drop a stems folder here",
            font=(_FONT_UI, 16, "bold"),
            text_color=_STUDIO_THEME["text"],
        )
        self._drop_hint.grid(row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        _ctk.CTkLabel(
            self._drop_zone,
            text="or click Browse to choose a directory.",
            font=(_FONT_UI, 13),
            text_color=_STUDIO_THEME["text_muted"],
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        self._stems_entry = _ctk.CTkEntry(controls, textvariable=self._stems_var, height=34)
        self._stems_entry.grid(row=2, column=0, padx=16, pady=(6, 4), sticky="ew")
        _ctk.CTkButton(
            controls,
            text="Browse Stems Folder",
            command=self._choose_stems_dir,
            fg_color=_STUDIO_THEME["accent"],
            hover_color=_STUDIO_THEME["accent_hover"],
            text_color="#1A1208",
        ).grid(row=3, column=0, padx=16, pady=(0, 10), sticky="ew")

        _ctk.CTkLabel(
            controls,
            text="Output Root",
            font=(_FONT_UI, 15, "bold"),
            text_color=_STUDIO_THEME["text"],
        ).grid(row=4, column=0, padx=16, pady=(4, 4), sticky="w")
        _ctk.CTkEntry(controls, textvariable=self._out_var, height=34).grid(
            row=5,
            column=0,
            padx=16,
            pady=(0, 4),
            sticky="ew",
        )
        _ctk.CTkButton(
            controls,
            text="Browse Output Folder",
            command=self._choose_out_dir,
            fg_color=_STUDIO_THEME["accent_cool"],
            hover_color="#4A8681",
            text_color="#06100F",
        ).grid(row=6, column=0, padx=16, pady=(0, 10), sticky="ew")

        _ctk.CTkLabel(
            controls,
            text="Render Focus",
            font=(_FONT_DISPLAY, 20, "bold"),
            text_color=_STUDIO_THEME["text"],
        ).grid(row=7, column=0, padx=16, pady=(8, 6), sticky="w")

        self._target_menu = _ctk.CTkOptionMenu(
            controls,
            values=list(self._target_picker_values),
            variable=self._target_var,
            fg_color="#1B1712",
            button_color=_STUDIO_THEME["accent"],
            button_hover_color=_STUDIO_THEME["accent_hover"],
            dropdown_fg_color=_STUDIO_THEME["panel"],
            text_color=_STUDIO_THEME["text"],
        )
        self._target_menu.grid(row=8, column=0, padx=16, pady=(0, 6), sticky="ew")

        self._render_many_switch = _ctk.CTkSwitch(
            controls,
            text="Render Many Targets",
            variable=self._render_many_var,
            onvalue=True,
            offvalue=False,
            command=self._sync_render_many_widgets,
            progress_color=_STUDIO_THEME["accent"],
            text_color=_STUDIO_THEME["text_muted"],
            font=(_FONT_UI, 13),
        )
        self._render_many_switch.grid(row=9, column=0, padx=16, pady=(0, 4), sticky="w")

        self._render_many_entry = _ctk.CTkEntry(
            controls,
            textvariable=self._render_many_targets_var,
            height=34,
        )
        self._render_many_entry.grid(row=10, column=0, padx=16, pady=(0, 6), sticky="ew")

        self._layout_menu = _ctk.CTkOptionMenu(
            controls,
            values=list(layout_standard_options()),
            variable=self._layout_standard_var,
            fg_color="#1B1712",
            button_color=_STUDIO_THEME["accent"],
            button_hover_color=_STUDIO_THEME["accent_hover"],
            dropdown_fg_color=_STUDIO_THEME["panel"],
            text_color=_STUDIO_THEME["text"],
        )
        self._layout_menu.grid(row=11, column=0, padx=16, pady=(0, 6), sticky="ew")

        _ctk.CTkEntry(controls, textvariable=self._plugins_var, height=34).grid(
            row=12,
            column=0,
            padx=16,
            pady=(0, 6),
            sticky="ew",
        )
        _ctk.CTkEntry(controls, textvariable=self._profile_var, height=34).grid(
            row=13,
            column=0,
            padx=16,
            pady=(0, 8),
            sticky="ew",
        )

        self._run_button = _ctk.CTkButton(
            controls,
            text="Run Analyze + Safe Render",
            command=self._start_pipeline,
            height=42,
            fg_color=_STUDIO_THEME["accent"],
            hover_color=_STUDIO_THEME["accent_hover"],
            text_color="#1A1208",
            font=(_FONT_UI, 15, "bold"),
        )
        self._run_button.grid(row=14, column=0, padx=16, pady=(6, 10), sticky="ew")

        self._preview_headphones_button = _ctk.CTkButton(
            controls,
            text="Preview on Headphones",
            command=self._start_pipeline_headphones,
            height=38,
            fg_color="#8A6331",
            hover_color="#755228",
            text_color="#F8EEDB",
            font=(_FONT_UI, 14, "bold"),
        )
        self._preview_headphones_button.grid(row=15, column=0, padx=16, pady=(0, 10), sticky="ew")

        self._progress_bar = _ctk.CTkProgressBar(
            controls,
            fg_color="#261F16",
            progress_color=_STUDIO_THEME["accent"],
            height=14,
            corner_radius=999,
        )
        self._progress_bar.grid(row=16, column=0, padx=16, pady=(0, 8), sticky="ew")
        self._progress_bar.set(0.0)

        self._cancel_button = _ctk.CTkButton(
            controls,
            text="Cancel Running Job",
            command=self._request_cancel,
            height=34,
            fg_color=_STUDIO_THEME["danger"],
            hover_color=_STUDIO_THEME["danger_hover"],
            state="disabled",
        )
        self._cancel_button.grid(row=17, column=0, padx=16, pady=(0, 8), sticky="ew")

        _ctk.CTkLabel(
            controls,
            textvariable=self._status_var,
            font=(_FONT_UI, 13),
            text_color=_STUDIO_THEME["text_muted"],
            justify="left",
            wraplength=520,
        ).grid(row=18, column=0, padx=16, pady=(0, 14), sticky="w")

        self._warning_banner = _ctk.CTkFrame(
            controls,
            fg_color="#3A2611",
            border_width=1,
            border_color="#D79B48",
            corner_radius=10,
        )
        self._warning_banner.grid(row=19, column=0, padx=16, pady=(0, 14), sticky="ew")
        self._warning_banner.grid_columnconfigure(0, weight=1)
        self._warning_banner_message = _ctk.CTkLabel(
            self._warning_banner,
            text=_NO_OUTPUTS_BANNER_TEXT,
            font=(_FONT_UI, 13, "bold"),
            text_color="#F6DDC0",
            justify="left",
            wraplength=500,
        )
        self._warning_banner_message.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="w")
        self._warning_banner_link = _ctk.CTkButton(
            self._warning_banner,
            text="",
            command=self._copy_warning_receipt_path,
            fg_color="transparent",
            hover_color="#4B3520",
            text_color="#8ED1CA",
            font=(_FONT_MONO, 11),
            anchor="w",
        )
        self._warning_banner_link.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")
        self._warning_banner.grid_remove()

        log_panel = _ctk.CTkFrame(
            self,
            fg_color=_STUDIO_THEME["surface"],
            corner_radius=18,
            border_width=1,
            border_color=_STUDIO_THEME["surface_edge"],
        )
        log_panel.grid(row=1, column=1, padx=(9, 18), pady=(0, 18), sticky="nsew")
        log_panel.grid_columnconfigure(0, weight=1)
        log_panel.grid_rowconfigure(1, weight=1)

        _ctk.CTkLabel(
            log_panel,
            text="Live Log + Visualization",
            font=(_FONT_DISPLAY, 18, "bold"),
            text_color=_STUDIO_THEME["text"],
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        self._surfaces_tabs = _ctk.CTkTabview(
            log_panel,
            fg_color=_STUDIO_THEME["panel"],
            segmented_button_fg_color="#1B1712",
            segmented_button_selected_color=_STUDIO_THEME["accent"],
            segmented_button_selected_hover_color=_STUDIO_THEME["accent_hover"],
            segmented_button_unselected_color="#14110E",
            segmented_button_unselected_hover_color="#1D1814",
            text_color=_STUDIO_THEME["text"],
        )
        self._surfaces_tabs.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._surfaces_tabs.add("Dashboard")
        self._surfaces_tabs.add("Live Log")
        self._surfaces_tabs.add("Scene")
        self._surfaces_tabs.add("Discover")

        dashboard_tab = self._surfaces_tabs.tab("Dashboard")
        dashboard_tab.grid_columnconfigure(0, weight=1)
        dashboard_tab.grid_rowconfigure(0, weight=1)
        self._dashboard_panel = VisualizationDashboardPanel(
            dashboard_tab,
            ctk_module=_ctk,
        )
        self._dashboard_panel.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        log_tab = self._surfaces_tabs.tab("Live Log")
        log_tab.grid_columnconfigure(0, weight=1)
        log_tab.grid_rowconfigure(0, weight=1)
        self._log_box = _ctk.CTkTextbox(
            log_tab,
            fg_color=_STUDIO_THEME["panel"],
            text_color=_STUDIO_THEME["text"],
            border_color=_STUDIO_THEME["panel_edge"],
            border_width=1,
            corner_radius=10,
            font=(_FONT_MONO, 12),
        )
        self._log_box.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        scene_tab = self._surfaces_tabs.tab("Scene")
        scene_tab.grid_columnconfigure(0, weight=1)
        scene_tab.grid_rowconfigure(1, weight=1)
        _ctk.CTkLabel(
            scene_tab,
            text=(
                "Read-only scene intent preview from _mmo_gui artifacts "
                "(scene.json + scene_lint.json)."
            ),
            font=(_FONT_UI, 12),
            text_color=_STUDIO_THEME["text_muted"],
            justify="left",
            wraplength=560,
        ).grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        self._scene_box = _ctk.CTkTextbox(
            scene_tab,
            fg_color=_STUDIO_THEME["panel"],
            text_color=_STUDIO_THEME["text"],
            border_color=_STUDIO_THEME["panel_edge"],
            border_width=1,
            corner_radius=10,
            font=(_FONT_MONO, 12),
        )
        self._scene_box.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        self._scene_box.configure(state="normal")
        self._scene_box.insert("end", _DEFAULT_SCENE_SUMMARY_TEXT)
        self._scene_box.configure(state="disabled")

        discover_tab = self._surfaces_tabs.tab("Discover")
        discover_tab.grid_columnconfigure(0, weight=1)
        discover_tab.grid_rowconfigure(1, weight=1)

        discover_header = _ctk.CTkFrame(
            discover_tab,
            fg_color="#11100E",
            border_color="#2B2318",
            border_width=1,
            corner_radius=10,
        )
        discover_header.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
        discover_header.grid_columnconfigure(0, weight=1)
        _ctk.CTkLabel(
            discover_header,
            text="Offline Plugin Hub",
            font=(_FONT_DISPLAY, 18, "bold"),
            text_color="#F7E8C8",
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        _ctk.CTkLabel(
            discover_header,
            text=(
                "Discover deterministic plugin packs with preview cards. "
                "Install in one click to your selected plugin root."
            ),
            font=(_FONT_UI, 12),
            text_color="#CDB28A",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")
        _ctk.CTkButton(
            discover_header,
            text="Refresh Discover",
            command=self._refresh_discover_cards,
            fg_color=_STUDIO_THEME["accent_cool"],
            hover_color="#4A8681",
            text_color="#06100F",
            width=160,
        ).grid(row=0, column=1, rowspan=2, padx=(8, 12), pady=10, sticky="e")

        self._discover_cards_frame = _ctk.CTkScrollableFrame(
            discover_tab,
            fg_color="#0F0D0B",
            border_color="#2A2219",
            border_width=1,
            corner_radius=10,
        )
        self._discover_cards_frame.grid(row=1, column=0, padx=8, pady=(0, 6), sticky="nsew")
        self._discover_cards_frame.grid_columnconfigure(0, weight=1)

        _ctk.CTkLabel(
            discover_tab,
            textvariable=self._discover_status_var,
            font=(_FONT_UI, 12),
            text_color=_STUDIO_THEME["text_muted"],
            justify="left",
            wraplength=560,
        ).grid(row=2, column=0, padx=10, pady=(0, 8), sticky="w")

        self._surfaces_tabs.set("Dashboard")
        self._append_log("MMO StudioConsole Noir initialized.")
        self._refresh_discover_cards()

    def _discover_plugins_root_path(self) -> Path:
        raw_plugins = self._plugins_var.get().strip()
        if raw_plugins:
            return Path(raw_plugins).expanduser().resolve()
        return default_user_plugins_dir().expanduser().resolve()

    def _refresh_discover_cards(self) -> None:
        frame = self._discover_cards_frame
        if frame is None:
            return
        install_root = self._discover_plugins_root_path()
        try:
            payload = build_plugin_market_list_payload(
                plugins_dir=install_root,
            )
        except (RuntimeError, ValueError, AttributeError, OSError) as exc:
            self._discover_status_var.set(
                f"Discover unavailable: {exc}"
            )
            self._append_log(f"Discover refresh failed: {exc}")
            return

        cards = build_plugin_discover_cards(payload)
        for child in frame.winfo_children():
            child.destroy()

        self._discover_install_buttons = {}

        if not cards:
            _ctk.CTkLabel(
                frame,
                text="No marketplace cards available.",
                text_color="#B9A07E",
                font=(_FONT_UI, 13),
            ).grid(row=0, column=0, padx=10, pady=10, sticky="w")
        else:
            self._render_discover_cards(cards)

        entry_count = payload.get("entry_count")
        installed_count = payload.get("installed_count")
        if isinstance(entry_count, int) and isinstance(installed_count, int):
            self._discover_status_var.set(
                f"Discover ready: {entry_count} card(s), {installed_count} installed. "
                f"Install target: {_as_posix(install_root)}"
            )
        else:
            self._discover_status_var.set(
                f"Discover ready. Install target: {_as_posix(install_root)}"
            )

    def _render_discover_cards(self, cards: Sequence[PluginDiscoverCard]) -> None:
        frame = self._discover_cards_frame
        if frame is None:
            return
        for row_index, card in enumerate(cards):
            gradient = _DISCOVER_GRADIENTS.get(card.preview_gradient, _DISCOVER_GRADIENTS["ember"])
            card_frame = _ctk.CTkFrame(
                frame,
                fg_color=gradient[0],
                border_color=gradient[1],
                border_width=2,
                corner_radius=12,
            )
            card_frame.grid(row=row_index, column=0, padx=8, pady=8, sticky="ew")
            card_frame.grid_columnconfigure(0, weight=1)

            header = f"{card.name}  [{card.plugin_type}]  v{card.version}"
            _ctk.CTkLabel(
                card_frame,
                text=header,
                font=(_FONT_DISPLAY, 16, "bold"),
                text_color=gradient[2],
            ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
            _ctk.CTkLabel(
                card_frame,
                text=card.preview_tagline,
                font=(_FONT_UI, 12, "bold"),
                text_color=gradient[3],
            ).grid(row=1, column=0, padx=12, pady=(2, 0), sticky="w")
            _ctk.CTkLabel(
                card_frame,
                text=card.summary,
                font=(_FONT_UI, 12),
                text_color="#DEC7A2",
                wraplength=520,
                justify="left",
            ).grid(row=2, column=0, padx=12, pady=(2, 2), sticky="w")

            chips = card.preview_chips or card.tags[:3]
            chips_text = "  ".join(f"[{chip}]" for chip in chips)
            if chips_text:
                _ctk.CTkLabel(
                    card_frame,
                    text=chips_text,
                    font=(_FONT_MONO, 11),
                    text_color="#C9E0DC" if card.plugin_type == "resolver" else "#E3C89A",
                    justify="left",
                    wraplength=520,
                ).grid(row=3, column=0, padx=12, pady=(0, 10), sticky="w")

            state_text = card.install_state.upper()
            _ctk.CTkLabel(
                card_frame,
                text=f"{card.plugin_id}  |  state={state_text}",
                font=(_FONT_MONO, 11),
                text_color="#BDA47E",
            ).grid(row=4, column=0, padx=12, pady=(0, 10), sticky="w")

            button_text = "Install"
            button_state = "normal"
            button_color = _STUDIO_THEME["accent"]
            button_hover = _STUDIO_THEME["accent_hover"]
            if card.install_state == "installed":
                button_text = "Installed"
                button_state = "disabled"
                button_color = "#4A3A24"
                button_hover = "#4A3A24"
            elif not card.installable:
                button_text = "Unavailable"
                button_state = "disabled"
                button_color = "#403226"
                button_hover = "#403226"
            elif card.plugin_id in self._discover_installing_ids:
                button_text = "Installing..."
                button_state = "disabled"

            install_button = _ctk.CTkButton(
                card_frame,
                text=button_text,
                command=lambda pid=card.plugin_id: self._on_install_discover_plugin(pid),
                width=150,
                fg_color=button_color,
                hover_color=button_hover,
                state=button_state,
                text_color="#1A1208" if button_state == "normal" else "#EAD9BE",
            )
            install_button.grid(row=0, column=1, rowspan=5, padx=(6, 12), pady=12, sticky="e")
            self._discover_install_buttons[card.plugin_id] = install_button

    def _on_install_discover_plugin(self, plugin_id: str) -> None:
        normalized_plugin_id = plugin_id.strip()
        if not normalized_plugin_id:
            return
        if normalized_plugin_id in self._discover_installing_ids:
            return
        self._discover_installing_ids.add(normalized_plugin_id)
        button = self._discover_install_buttons.get(normalized_plugin_id)
        if button is not None:
            button.configure(text="Installing...", state="disabled")

        thread = threading.Thread(
            target=self._run_discover_install_worker,
            args=(normalized_plugin_id,),
            daemon=True,
            name=f"mmo_gui_install_{normalized_plugin_id}",
        )
        thread.start()

    def _run_discover_install_worker(self, plugin_id: str) -> None:
        install_root = self._discover_plugins_root_path()
        try:
            receipt = install_plugin_market_entry(
                plugin_id=plugin_id,
                plugins_dir=install_root,
            )
            changed = bool(receipt.get("changed"))
            if changed:
                self._append_log_threadsafe(
                    f"Installed plugin card {plugin_id} into {_as_posix(install_root)}"
                )
                self._set_status_threadsafe(
                    f"Installed plugin {plugin_id}."
                )
            else:
                self._append_log_threadsafe(
                    f"Plugin card already installed: {plugin_id}"
                )
                self._set_status_threadsafe(
                    f"Plugin {plugin_id} is already installed."
                )
        except (RuntimeError, ValueError, AttributeError, OSError) as exc:
            self._append_log_threadsafe(f"Plugin install failed for {plugin_id}: {exc}")
            self._set_status_threadsafe(f"Plugin install failed: {plugin_id}")
            self._show_error_threadsafe("Plugin install failed", str(exc))
        finally:
            self._discover_installing_ids.discard(plugin_id)
            self.after(0, self._refresh_discover_cards)

    def _wire_drag_drop(self) -> None:
        if DND_FILES is None:
            self._append_log("Drag/drop support unavailable (optional dependency: tkinterdnd2).")
            return

        wired = False
        for widget in (self._drop_zone, self._drop_hint):
            register = getattr(widget, "drop_target_register", None)
            binder = getattr(widget, "dnd_bind", None)
            if callable(register) and callable(binder):
                register(DND_FILES)
                binder("<<Drop>>", self._on_drop)
                wired = True
        if not wired:
            self._append_log("Drag/drop hooks not available in current Tk runtime; browse is enabled.")

    def _on_drop(self, event: Any) -> None:
        raw_data = str(getattr(event, "data", "")).strip()
        if not raw_data:
            return
        items = list(self.tk.splitlist(raw_data))
        if not items:
            return
        candidate = Path(str(items[0]).strip("{}")).expanduser()
        if candidate.is_file():
            candidate = candidate.parent
        self._stems_var.set(_as_posix(candidate))
        self._append_log(f"Stems folder selected via drag/drop: {_as_posix(candidate)}")

    def _choose_stems_dir(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory()
        if selected:
            self._stems_var.set(_as_posix(Path(selected)))

    def _choose_out_dir(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory()
        if selected:
            self._out_var.set(_as_posix(Path(selected)))

    def _sync_render_many_widgets(self) -> None:
        if self._render_many_var.get():
            self._target_menu.configure(state="disabled")
            self._render_many_entry.configure(state="normal")
        else:
            self._target_menu.configure(state="normal")
            self._render_many_entry.configure(state="disabled")

    def _primary_layout_for_config(self, config: GuiRunConfig) -> str:
        if config.render_many:
            layout_ids = normalize_render_many_layout_ids(
                config.render_many_target_ids,
                target_layouts=self._target_layouts,
            )
            return layout_ids[0] if layout_ids else "LAYOUT.2_0"
        return resolve_single_target_layout_id(
            config.target_id,
            target_layouts=self._target_layouts,
        )

    def _sync_dashboard_layout(self, config: GuiRunConfig) -> None:
        if self._dashboard_panel is None:
            return
        self._dashboard_panel.set_layout(
            layout_id=self._primary_layout_for_config(config),
            layout_standard=config.layout_standard,
        )

    def _append_log(self, line: str) -> None:
        self._log_box.insert("end", f"{line}\n")
        self._log_box.see("end")

    def _append_log_threadsafe(self, line: str) -> None:
        self.after(0, lambda text=line: self._append_log(text))

    def _set_status_threadsafe(self, status: str) -> None:
        def _apply() -> None:
            self._status_var.set(status)
            if self._dashboard_panel is not None:
                self._dashboard_panel.set_status_line(status)

        self.after(0, _apply)

    def _set_progress_threadsafe(self, fraction: float) -> None:
        clamped = max(0.0, min(1.0, float(fraction)))
        def _apply() -> None:
            self._progress_bar.set(clamped)
            if self._dashboard_panel is not None:
                self._dashboard_panel.set_progress(clamped)

        self.after(0, _apply)

    def _set_bus_plan_summary_threadsafe(self, summary_text: str) -> None:
        def _apply() -> None:
            if self._dashboard_panel is None:
                return
            self._dashboard_panel.set_bus_plan_summary(summary_text)

        self.after(0, _apply)

    def _set_scene_summary_threadsafe(self, summary_text: str) -> None:
        def _apply() -> None:
            if not hasattr(self, "_scene_box"):
                return
            self._scene_box.configure(state="normal")
            self._scene_box.delete("1.0", "end")
            self._scene_box.insert("end", summary_text.strip() or _DEFAULT_SCENE_SUMMARY_TEXT)
            self._scene_box.configure(state="disabled")

        self.after(0, _apply)

    def _set_running_threadsafe(self, running: bool) -> None:
        def _apply() -> None:
            self._run_button.configure(state="disabled" if running else "normal")
            self._preview_headphones_button.configure(state="disabled" if running else "normal")
            self._cancel_button.configure(state="normal" if running else "disabled")

        self.after(0, _apply)

    def _set_warning_banner_threadsafe(
        self,
        *,
        show: bool,
        receipt_path: Path | None = None,
    ) -> None:
        def _apply() -> None:
            if not hasattr(self, "_warning_banner"):
                return
            if not show:
                self._warning_receipt_path = None
                self._warning_banner_link.configure(text="", state="disabled")
                self._warning_banner.grid_remove()
                return
            self._warning_receipt_path = receipt_path
            if receipt_path is None:
                self._warning_banner_link.configure(
                    text="Receipt path unavailable.",
                    state="disabled",
                )
            else:
                self._warning_banner_link.configure(
                    text=_as_posix(receipt_path),
                    state="normal",
                )
            self._warning_banner.grid()

        self.after(0, _apply)

    def _copy_warning_receipt_path(self) -> None:
        path = self._warning_receipt_path
        if path is None:
            return
        path_text = _as_posix(path)
        try:
            self.clipboard_clear()
            self.clipboard_append(path_text)
        except Exception:  # noqa: BLE001
            self._append_log(f"Receipt path: {path_text}")
            return
        self._append_log(f"Receipt path copied: {path_text}")
        self._status_var.set("Warning receipt path copied to clipboard.")

    def _show_error_threadsafe(self, title: str, message: str) -> None:
        from tkinter import messagebox

        self.after(0, lambda: messagebox.showerror(title, message))

    def _collect_config(self) -> GuiRunConfig | None:
        from tkinter import messagebox

        stems_raw = self._stems_var.get().strip()
        out_raw = self._out_var.get().strip()
        plugins_raw = self._plugins_var.get().strip()
        profile_raw = self._profile_var.get().strip() or _DEFAULT_PROFILE_ID

        if not stems_raw:
            messagebox.showerror("Missing stems folder", "Select or drop a stems folder first.")
            return None
        if not out_raw:
            messagebox.showerror("Missing output folder", "Select an output folder.")
            return None
        if not plugins_raw:
            messagebox.showerror("Missing plugins folder", "Provide a plugins directory.")
            return None

        stems_dir = Path(stems_raw).expanduser()
        if not stems_dir.exists() or not stems_dir.is_dir():
            messagebox.showerror(
                "Invalid stems folder",
                f"Stems folder does not exist or is not a directory:\n{stems_dir}",
            )
            return None

        out_dir = Path(out_raw).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        plugins_dir = Path(plugins_raw).expanduser()
        render_many_targets = tuple(
            token.strip()
            for token in self._render_many_targets_var.get().split(",")
            if token.strip()
        )
        target_value = self._target_var.get().strip()
        target_token = self._target_picker_map.get(target_value, target_value)

        return GuiRunConfig(
            stems_dir=stems_dir.resolve(),
            out_dir=out_dir.resolve(),
            target_id=target_token,
            render_many=bool(self._render_many_var.get()),
            render_many_target_ids=render_many_targets,
            layout_standard=normalize_layout_standard(self._layout_standard_var.get()),
            preview_headphones=False,
            plugins_dir=plugins_dir.resolve(),
            profile_id=profile_raw,
        )

    def _start_pipeline(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        config = self._collect_config()
        if config is None:
            return
        self._start_pipeline_with_config(
            config,
            status_text="Running analyze + dry-run safety preview...",
        )

    def _start_pipeline_headphones(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        config = self._collect_config()
        if config is None:
            return
        self._start_pipeline_with_config(
            replace(config, preview_headphones=True),
            status_text="Running analyze + headphone virtualization preview...",
        )

    def _start_pipeline_with_config(
        self,
        config: GuiRunConfig,
        *,
        status_text: str,
    ) -> None:
        self._sync_dashboard_layout(config)
        self._set_running_threadsafe(True)
        self._set_status_threadsafe(status_text)
        self._set_progress_threadsafe(0.0)
        self._set_warning_banner_threadsafe(show=False)
        self._set_bus_plan_summary_threadsafe(
            "Role counts:\n- (pending analyze)\n\nBus tree:\n- (pending analyze)"
        )
        self._set_scene_summary_threadsafe(_DEFAULT_SCENE_SUMMARY_TEXT)
        workspace_dir = config.out_dir / _DEFAULT_GUI_WORKSPACE
        workspace_dir.mkdir(parents=True, exist_ok=True)
        self._cancel_file_path = build_pipeline_paths(workspace_dir).cancel_token_path
        self._clear_cancel_file()

        self._worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(config, workspace_dir),
            daemon=True,
            name="mmo_gui_worker",
        )
        self._worker_thread.start()

    def _clear_cancel_file(self) -> None:
        path = self._cancel_file_path
        if path is None:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _cancel_requested(self) -> bool:
        path = self._cancel_file_path
        return bool(path is not None and path.exists())

    def _request_cancel(self) -> None:
        self._set_status_threadsafe("Cancellation requested...")
        self._append_log("Cancellation requested by user.")
        path = self._cancel_file_path
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("cancel\n", encoding="utf-8")
            except OSError as exc:
                self._append_log(f"Failed to write cancel file: {exc}")
        with self._process_lock:
            process = self._active_process
        if process is not None and process.poll() is None:
            process.terminate()

    def _consume_live_progress_line(self, line: str) -> bool:
        prefix = "[MMO-LIVE] "
        if not line.startswith(prefix):
            return False
        payload_text = line[len(prefix):].strip()
        if not payload_text:
            return False
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, Mapping):
            return False

        if self._dashboard_panel is not None:
            snapshot = dict(payload)
            self.after(
                0,
                lambda payload_snapshot=snapshot: (
                    self._dashboard_panel.ingest_live_payload(payload_snapshot)
                    if self._dashboard_panel is not None
                    else None
                ),
            )

        progress_value = payload.get("progress")
        if isinstance(progress_value, (int, float)):
            self._set_progress_threadsafe(float(progress_value))

        what = payload.get("what")
        why = payload.get("why")
        where = payload.get("where")
        confidence = payload.get("confidence")
        where_text = ""
        if isinstance(where, list):
            where_text = ", ".join(
                str(item)
                for item in where
                if isinstance(item, str) and item.strip()
            )
        if isinstance(what, str) and isinstance(why, str):
            conf_text = (
                f"{float(confidence):.2f}"
                if isinstance(confidence, (int, float))
                else "n/a"
            )
            detail = f"[LIVE] {what} | why={why} | where={where_text or '(none)'} | confidence={conf_text}"
            self._append_log_threadsafe(detail)
            self._set_status_threadsafe(what)
            return True
        return False

    def _run_command(self, cli_argv: Sequence[str], *, stage: str = "command") -> int:
        command = build_python_command(cli_argv)
        self._append_log_threadsafe(f"[GUI.STAGE] {stage} starting.")
        self._append_log_threadsafe(f"$ {shlex.join(command)}")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log_threadsafe(
                f"[GUI.E2001] spawn_failed | stage={stage} | {exc}"
            )
            self._append_log_threadsafe(
                "  Hint: ensure the mmo package is installed and the executable path is correct."
            )
            return 1
        with self._process_lock:
            self._active_process = process
        assert process.stdout is not None
        first_error_line: str | None = None
        try:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                if self._consume_live_progress_line(stripped):
                    continue
                self._append_log_threadsafe(stripped)
                if first_error_line is None and (
                    "error:" in stripped.lower() or "traceback" in stripped.lower()
                ):
                    first_error_line = stripped
            rc = process.wait()
        finally:
            with self._process_lock:
                self._active_process = None
        if rc != 0:
            self._append_log_threadsafe(
                f"[GUI.E2000] stage_failed | stage={stage} | rc={rc}"
            )
            if first_error_line is not None:
                self._append_log_threadsafe(
                    f"[GUI.E2000] first_error_line | stage={stage} | {first_error_line}"
                )
        else:
            self._append_log_threadsafe(f"[GUI.STAGE] {stage} completed ok.")
        return rc

    def _approve_high_risk_prompt(self, receipt_payload: Mapping[str, Any]) -> bool:
        from tkinter import messagebox

        blocked = receipt_payload.get("blocked_recommendations")
        if not isinstance(blocked, list):
            return False

        high_risk_ids: list[str] = []
        for row in blocked:
            if not isinstance(row, Mapping):
                continue
            risk = row.get("risk")
            if isinstance(risk, str) and risk.strip().casefold() == "high":
                rec_id = row.get("recommendation_id")
                if isinstance(rec_id, str) and rec_id.strip():
                    high_risk_ids.append(rec_id.strip())

        preview = ", ".join(sorted(high_risk_ids)[:4])
        if len(high_risk_ids) > 4:
            preview = f"{preview}, ..."
        message = (
            f"Detected {len(high_risk_ids)} high-risk recommendation(s).\n\n"
            f"{preview}\n\n"
            "Approve all high-risk actions for the final render?"
        )

        decision: dict[str, bool] = {"approve": False}
        gate = threading.Event()

        def _prompt() -> None:
            decision["approve"] = bool(
                messagebox.askyesno(
                    "High-risk approval required",
                    message,
                )
            )
            gate.set()

        self.after(0, _prompt)
        gate.wait()
        return decision["approve"]

    def _run_pipeline_worker(self, config: GuiRunConfig, workspace_dir: Path) -> None:
        try:
            analyze_argv, dry_run_argv, final_argv, paths = build_pipeline_cli_argvs(
                config,
                workspace_dir=workspace_dir,
                approve=None,
            )

            analyze_rc = self._run_command(analyze_argv, stage="analyze")
            if analyze_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Cancelled during analysis.")
                return
            if analyze_rc != 0:
                self._set_status_threadsafe("Analyze failed. Check live log.")
                return
            self._set_progress_threadsafe(0.15)

            self._set_status_threadsafe("Analyze complete. Classifying stems...")
            classify_argv = build_stems_classify_cli_argv(
                config,
                workspace_dir=workspace_dir,
            )
            classify_rc = self._run_command(classify_argv, stage="stems-classify")
            if classify_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Cancelled during stems classification.")
                return
            if classify_rc != 0:
                self._set_status_threadsafe("Stems classification failed. Check live log.")
                return

            self._set_status_threadsafe("Building deterministic bus plan...")
            bus_plan_argv = build_stems_bus_plan_cli_argv(workspace_dir=workspace_dir)
            bus_plan_rc = self._run_command(bus_plan_argv, stage="stems-bus-plan")
            if bus_plan_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Cancelled during bus plan generation.")
                return
            if bus_plan_rc != 0:
                self._set_status_threadsafe("Bus plan generation failed. Check live log.")
                return

            bus_plan_out_path = gui_bus_plan_path(workspace_dir)
            if not bus_plan_out_path.exists():
                self._set_status_threadsafe("Bus plan artifact missing after generation.")
                return
            try:
                bus_plan_payload = json.loads(bus_plan_out_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._set_status_threadsafe("Bus plan artifact is unreadable.")
                return
            if not isinstance(bus_plan_payload, Mapping):
                self._set_status_threadsafe("Bus plan artifact is invalid.")
                return
            bus_summary = render_bus_plan_summary_text(bus_plan_payload)
            self._set_bus_plan_summary_threadsafe(bus_summary)
            for line in bus_summary.splitlines():
                log_line = line if line else "-"
                self._append_log_threadsafe(f"[BUS.PLAN] {log_line}")
            self._set_status_threadsafe("Building scene intent preview...")
            scene_summary = (
                "Perspective:\n"
                "- (unavailable)\n\n"
                "Objects (azimuth/width/depth/confidence):\n"
                "- (scene build unavailable)\n\n"
                "Bed buses:\n"
                "- (scene build unavailable)\n\n"
                "Scene lint warnings:\n"
                "- (scene build unavailable)"
            )
            scene_ready = False
            scene_build_argv = build_scene_build_cli_argv(
                config,
                workspace_dir=workspace_dir,
            )
            scene_build_rc = self._run_command(scene_build_argv, stage="scene-build")
            if scene_build_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Cancelled during scene preview generation.")
                return
            if scene_build_rc == 0:
                scene_out_path = gui_scene_path(workspace_dir)
                scene_payload: Mapping[str, Any] | None = None
                if scene_out_path.exists():
                    try:
                        loaded_scene = json.loads(scene_out_path.read_text(encoding="utf-8"))
                        if isinstance(loaded_scene, Mapping):
                            scene_payload = loaded_scene
                    except (OSError, json.JSONDecodeError):
                        scene_payload = None
                if scene_payload is None:
                    self._append_log_threadsafe(
                        "Scene preview unavailable: scene.json is missing or unreadable."
                    )
                else:
                    lint_payload: Mapping[str, Any] | None = None
                    scene_lint_argv = build_scene_lint_cli_argv(workspace_dir=workspace_dir)
                    scene_lint_rc = self._run_command(scene_lint_argv, stage="scene-lint")
                    if scene_lint_rc != 0 and self._cancel_requested():
                        self._set_status_threadsafe("Cancelled during scene lint.")
                        return
                    if scene_lint_rc not in (0, 2):
                        self._append_log_threadsafe(
                            "Scene lint failed unexpectedly; showing scene preview without lint warnings."
                        )
                    lint_out_path = gui_scene_lint_path(workspace_dir)
                    if lint_out_path.exists():
                        try:
                            loaded_lint = json.loads(lint_out_path.read_text(encoding="utf-8"))
                            if isinstance(loaded_lint, Mapping):
                                lint_payload = loaded_lint
                        except (OSError, json.JSONDecodeError):
                            lint_payload = None
                    scene_summary = render_scene_summary_text(
                        scene_payload,
                        lint_payload=lint_payload,
                    )
                    scene_ready = True
            else:
                self._append_log_threadsafe(
                    "Scene build failed; continuing with bus-plan summary and render stages."
                )

            self._set_scene_summary_threadsafe(scene_summary)
            if scene_ready:
                self._set_status_threadsafe("Analyze complete. Bus plan + scene preview ready.")
            else:
                self._set_status_threadsafe("Analyze complete. Bus plan ready (scene preview unavailable).")
            self._set_progress_threadsafe(0.25)

            dry_rc = self._run_command(dry_run_argv, stage="safe-render(dry)")
            if dry_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Cancelled during dry-run safety preview.")
                return
            if dry_rc == 130:
                self._set_status_threadsafe("Cancelled during dry-run safety preview.")
                return
            if dry_rc != 0:
                self._set_status_threadsafe("Dry-run safety preview failed. Check live log.")
                return
            self._set_progress_threadsafe(0.45)

            approve_value: str | None = None
            if paths.dry_receipt_path.exists():
                receipt_payload = json.loads(
                    paths.dry_receipt_path.read_text(encoding="utf-8")
                )
                if (
                    isinstance(receipt_payload, Mapping)
                    and has_high_risk_blocked_recommendations(receipt_payload)
                ):
                    self._set_status_threadsafe(
                        "High-risk actions detected. Awaiting approval dialog..."
                    )
                    if self._approve_high_risk_prompt(receipt_payload):
                        approve_value = "all"
                        self._append_log_threadsafe("User approved high-risk actions: --approve all")
                    else:
                        self._append_log_threadsafe(
                            "User declined high-risk approval; continuing with bounded defaults."
                        )

            _, _, final_argv, _ = build_pipeline_cli_argvs(
                config,
                workspace_dir=workspace_dir,
                approve=approve_value,
            )
            self._set_status_threadsafe("Rendering...")
            final_rc = self._run_command(final_argv, stage="safe-render(final)")
            final_receipt_payload: Mapping[str, Any] | None = None
            final_receipt_path: Path | None = paths.final_receipt_path
            if final_receipt_path.exists():
                try:
                    loaded = json.loads(paths.final_receipt_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, Mapping):
                        final_receipt_payload = loaded
                except (OSError, json.JSONDecodeError):
                    final_receipt_payload = None

            has_no_outputs = bool(
                isinstance(final_receipt_payload, Mapping)
                and has_no_outputs_issue(final_receipt_payload)
            )
            self._set_warning_banner_threadsafe(
                show=(has_no_outputs or final_rc != 0),
                receipt_path=final_receipt_path,
            )
            if final_rc != 0 and self._cancel_requested():
                self._set_status_threadsafe("Render cancelled.")
                return
            if final_rc == 130:
                self._set_status_threadsafe("Render cancelled.")
                return
            if final_rc != 0:
                if has_no_outputs:
                    self._set_status_threadsafe(_NO_OUTPUTS_BANNER_TEXT)
                else:
                    self._set_status_threadsafe("Render failed. Check live log.")
                return
            if has_no_outputs:
                self._set_progress_threadsafe(1.0)
                self._set_status_threadsafe(_NO_OUTPUTS_BANNER_TEXT)
                return

            self._set_progress_threadsafe(1.0)
            self._set_status_threadsafe(f"Completed. Artifacts in {_as_posix(config.out_dir)}")
        except Exception as exc:  # noqa: BLE001
            self._show_error_threadsafe("GUI pipeline error", str(exc))
            self._set_status_threadsafe("Pipeline failed with an unexpected error.")
        finally:
            self._clear_cancel_file()
            self._set_running_threadsafe(False)


def launch_gui() -> int:
    if _ctk is None:
        print(
            (
                "CustomTkinter is required for the desktop GUI. "
                "Install extras: pip install .[gui]"
            ),
            file=sys.stderr,
        )
        return 2

    _ctk.set_appearance_mode("dark")
    app = _MMOGuiApp()
    app.mainloop()
    return 0


def _passthrough_module_to_run(module: str) -> str:
    if module == "mmo":
        return "mmo.__main__"
    return module


def _passthrough_exit_code(code: object, *, from_system_exit: bool) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        if from_system_exit:
            print(code, file=sys.stderr)
        return 1
    try:
        return int(code)
    except (TypeError, ValueError):
        return 1


def _try_cli_passthrough(argv: Sequence[str] | None) -> int | None:
    """If argv starts with ['-m', 'mmo*', ...], dispatch via module ``main()``.

    This allows a frozen GUI executable to also act as a Python module runner, so
    that ``sys.executable -m mmo ...`` and ``sys.executable -m mmo.tools...`` both
    work in PyInstaller/packaged builds where ``python -m`` is not available separately.

    Returns the CLI exit code when dispatched, or None if not a passthrough call.
    """
    effective: list[str] = list(argv) if argv is not None else list(sys.argv[1:])
    if len(effective) >= 2 and effective[0] == "-m" and effective[1].startswith("mmo"):
        module = effective[1]
        module_to_run = _passthrough_module_to_run(module)
        module_args = effective[2:]
        original_argv = list(sys.argv)
        try:
            sys.argv = [module, *module_args]
            if module == "mmo":
                from mmo.cli import main as cli_main

                return _passthrough_exit_code(cli_main(), from_system_exit=False)

            module_impl = importlib.import_module(module_to_run)
            module_main = getattr(module_impl, "main", None)
            if not callable(module_main):
                print(
                    f"error: module '{module_to_run}' has no callable main()",
                    file=sys.stderr,
                )
                return 2
            return _passthrough_exit_code(module_main(), from_system_exit=False)
        except SystemExit as exc:
            return _passthrough_exit_code(exc.code, from_system_exit=True)
        except ImportError as exc:
            missing_mmo_entrypoint = (
                module == "mmo"
                and (
                    getattr(exc, "name", "") in {"mmo.__main__", "mmo.cli"}
                    or "mmo.__main__" in str(exc)
                    or "mmo.cli" in str(exc)
                )
            )
            if missing_mmo_entrypoint:
                print(
                    (
                        "This build is missing mmo CLI entrypoint modules "
                        "(mmo.__main__/mmo.cli). Packaging bug: ensure PyInstaller "
                        "includes hidden-imports for both modules."
                    ),
                    file=sys.stderr,
                )
                return 2
            print(f"error: unable to import module '{module_to_run}': {exc}", file=sys.stderr)
            return 2
        finally:
            sys.argv = original_argv
    return None


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MMO CustomTkinter desktop GUI.")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Parse entrypoint and exit without launching Tk (for smoke tests).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    rc = _try_cli_passthrough(argv)
    if rc is not None:
        return rc
    args = _parse_args(argv)
    if args.smoke:
        return 0
    return launch_gui()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
