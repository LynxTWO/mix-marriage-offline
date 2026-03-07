"""Validate the Tauri desktop design-system contract and layout ergonomics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SRC_DIR = SCRIPT_REPO_ROOT / "src"
if str(SCRIPT_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_SRC_DIR))

from mmo.core.ui_layout import build_ui_layout_snapshot, snapshot_has_violations


LAYOUT_FILES: tuple[str, ...] = (
    "gui/desktop-tauri/layouts/dashboard.ui_layout.json",
    "gui/desktop-tauri/layouts/presets.ui_layout.json",
    "gui/desktop-tauri/layouts/run.ui_layout.json",
    "gui/desktop-tauri/layouts/compare.ui_layout.json",
)

SNAPSHOT_CASES: tuple[tuple[str, int, int, float], ...] = (
    ("mobile", 390, 844, 1.0),
    ("laptop", 1280, 900, 1.0),
    ("desktop_compact", 1728, 1117, 0.9),
    ("desktop_comfort", 1728, 1117, 1.15),
)

PALETTE_CSS_VAR_MAP: dict[str, str] = {
    "background": "--theme-background",
    "surface": "--theme-surface",
    "surface_alt": "--theme-surface-alt",
    "text": "--theme-text",
    "text_muted": "--theme-text-muted",
    "accent_primary": "--theme-accent-primary",
    "accent_secondary": "--theme-accent-secondary",
    "danger": "--theme-danger",
    "warning": "--theme-warning",
    "ok": "--theme-ok",
    "info": "--theme-info",
}

TYPOGRAPHY_CSS_VAR_MAP: dict[str, str] = {
    "ui_font": "--theme-ui-font",
    "mono_font": "--theme-mono-font",
    "display_font": "--theme-display-font",
}

SPACING_CSS_VAR_MAP: dict[str, str] = {
    "base_px": "--theme-space-base-px",
    "radius_px": "--theme-radius-px",
    "card_padding_px": "--theme-card-padding-px",
}

NUMERIC_CONTROL_KINDS: frozenset[str] = frozenset({"KNOB", "SLIDER", "XY"})
FINE_ADJUST_CONTROL_KINDS: frozenset[str] = frozenset({"KNOB", "SLIDER", "XY"})


@dataclass(frozen=True)
class WidgetRecord:
    control_kind: str | None
    direct_entry: bool
    fine_adjust: bool
    numeric_control: bool
    scale_control: bool
    scale_count: int | None
    units: str | None
    widget_id: str


class DesktopHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_ids: set[str] = set()
        self.widgets: dict[str, WidgetRecord] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        attributes = {name: value for name, value in attrs}
        section_id = (attributes.get("data-section-id") or "").strip()
        if section_id:
            self.section_ids.add(section_id)

        widget_id = (attributes.get("data-widget-id") or "").strip()
        if not widget_id:
            return

        control_kind_raw = (attributes.get("data-control-kind") or "").strip()
        control_kind = control_kind_raw if control_kind_raw else None
        scale_count_raw = (attributes.get("data-scale-count") or "").strip()
        scale_count = int(scale_count_raw) if scale_count_raw.isdigit() else None
        self.widgets[widget_id] = WidgetRecord(
            widget_id=widget_id,
            control_kind=control_kind,
            direct_entry=(attributes.get("data-direct-entry") or "").strip().lower() == "true",
            fine_adjust=(attributes.get("data-fine-adjust") or "").strip().lower() == "true",
            numeric_control=(attributes.get("data-numeric-control") or "").strip().lower() == "true",
            scale_control=(attributes.get("data-scale-control") or "").strip().lower() == "true",
            scale_count=scale_count,
            units=(attributes.get("data-units") or "").strip() or None,
        )


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML object at {path.as_posix()}.")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path.as_posix()}.")
    return payload


def _parse_html_widgets(index_html_path: Path) -> DesktopHtmlParser:
    parser = DesktopHtmlParser()
    parser.feed(index_html_path.read_text(encoding="utf-8"))
    return parser


def _css_custom_properties(styles_text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for match in re.finditer(r"(?P<name>--[A-Za-z0-9_-]+)\s*:\s*(?P<value>[^;]+);", styles_text):
        properties[match.group("name")] = match.group("value").strip().strip('"')
    return properties


def _validate_gui_design_schema(*, payload: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _load_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(
        f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in validator.iter_errors(payload)
    )


def _layout_widget_ids(layout_payload: dict[str, Any]) -> set[str]:
    section_rows = layout_payload.get("sections")
    if not isinstance(section_rows, list):
        return set()
    widget_ids: set[str] = set()
    for section in section_rows:
        if not isinstance(section, dict):
            continue
        widgets = section.get("widgets")
        if not isinstance(widgets, list):
            continue
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            widget_id = widget.get("widget_id")
            if isinstance(widget_id, str) and widget_id.strip():
                widget_ids.add(widget_id.strip())
    return widget_ids


def _normalize_css_font(value: str) -> str:
    return value.strip().strip('"').strip("'")


def validate_tauri_design_system(*, repo_root: Path) -> dict[str, Any]:
    errors: list[str] = []

    gui_design_path = repo_root / "ontology" / "gui_design.yaml"
    gui_design_schema_path = repo_root / "schemas" / "gui_design.schema.json"
    ui_layout_schema_path = repo_root / "schemas" / "ui_layout.schema.json"
    index_html_path = repo_root / "gui" / "desktop-tauri" / "index.html"
    styles_path = repo_root / "gui" / "desktop-tauri" / "src" / "styles.css"

    gui_design = _load_yaml(gui_design_path)
    schema_errors = _validate_gui_design_schema(payload=gui_design, schema_path=gui_design_schema_path)
    errors.extend(schema_errors)

    html_parser = _parse_html_widgets(index_html_path)
    css_properties = _css_custom_properties(styles_path.read_text(encoding="utf-8"))

    theme_mismatches: list[str] = []
    palette = gui_design.get("theme", {}).get("palette", {})
    if isinstance(palette, dict):
        for key, css_var in PALETTE_CSS_VAR_MAP.items():
            expected = palette.get(key)
            actual = css_properties.get(css_var)
            if isinstance(expected, str) and actual != expected:
                theme_mismatches.append(
                    f"{css_var} expected {expected!r} from ontology/gui_design.yaml, got {actual!r}."
                )

    typography = gui_design.get("theme", {}).get("typography", {})
    if isinstance(typography, dict):
        for key, css_var in TYPOGRAPHY_CSS_VAR_MAP.items():
            expected = typography.get(key)
            actual = css_properties.get(css_var)
            if isinstance(expected, str) and _normalize_css_font(actual or "") != expected:
                theme_mismatches.append(
                    f"{css_var} expected {expected!r} from ontology/gui_design.yaml, got {actual!r}."
                )

    spacing = gui_design.get("theme", {}).get("spacing", {})
    spacing_base_px = 0
    if isinstance(spacing, dict):
        spacing_base_px = int(spacing.get("base_px", 0) or 0)
        for key, css_var in SPACING_CSS_VAR_MAP.items():
            expected = spacing.get(key)
            actual = css_properties.get(css_var)
            if isinstance(expected, int) and actual != str(expected):
                theme_mismatches.append(
                    f"{css_var} expected {expected!r} from ontology/gui_design.yaml, got {actual!r}."
                )

    present_control_kinds = {
        widget.control_kind
        for widget in html_parser.widgets.values()
        if widget.control_kind is not None
    }
    required_control_kinds: list[str] = []
    raw_controls = gui_design.get("components", {}).get("controls", [])
    if isinstance(raw_controls, list):
        required_control_kinds = [
            item for item in raw_controls if isinstance(item, str) and item.strip()
        ]

    missing_control_kinds = sorted(
        control_kind for control_kind in required_control_kinds if control_kind not in present_control_kinds
    )

    numeric_missing_units = sorted(
        widget.widget_id
        for widget in html_parser.widgets.values()
        if widget.control_kind in NUMERIC_CONTROL_KINDS and not widget.units
    )
    numeric_missing_direct_entry = sorted(
        widget.widget_id
        for widget in html_parser.widgets.values()
        if widget.control_kind in NUMERIC_CONTROL_KINDS and not widget.direct_entry
    )
    drag_missing_fine_adjust = sorted(
        widget.widget_id
        for widget in html_parser.widgets.values()
        if widget.control_kind in FINE_ADJUST_CONTROL_KINDS and not widget.fine_adjust
    )

    scaling_payload = gui_design.get("scaling", {})
    scaling_presets = scaling_payload.get("presets", []) if isinstance(scaling_payload, dict) else []
    scale_widgets = [widget for widget in html_parser.widgets.values() if widget.scale_control]
    scale_control_errors: list[str] = []
    spacing_errors: list[str] = []
    if not scale_widgets:
        scale_control_errors.append("Missing data-scale-control widget in gui/desktop-tauri/index.html.")
    else:
        expected_count = len(scaling_presets) if isinstance(scaling_presets, list) else 0
        for widget in scale_widgets:
            if widget.scale_count != expected_count:
                scale_control_errors.append(
                    f"{widget.widget_id} expected data-scale-count={expected_count}, got {widget.scale_count!r}."
                )

    layout_schema = _load_json(ui_layout_schema_path)
    layout_validator = jsonschema.Draft202012Validator(layout_schema)
    layout_results: list[dict[str, Any]] = []
    missing_layout_widgets: list[str] = []
    for layout_rel_path in LAYOUT_FILES:
        layout_path = repo_root / layout_rel_path
        layout_payload = _load_json(layout_path)
        layout_schema_errors = sorted(
            f"{layout_rel_path}: {'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in layout_validator.iter_errors(layout_payload)
        )
        errors.extend(layout_schema_errors)

        missing_layout_widgets.extend(
            sorted(
                widget_id
                for widget_id in _layout_widget_ids(layout_payload)
                if widget_id not in html_parser.widgets
            )
        )

        snapshot_rows: list[dict[str, Any]] = []
        for case_id, width_px, height_px, scale in SNAPSHOT_CASES:
            snapshot_payload = build_ui_layout_snapshot(
                layout_payload,
                layout_path=layout_path,
                viewport_width_px=width_px,
                viewport_height_px=height_px,
                scale=scale,
            )
            grid_payload = snapshot_payload.get("grid", {})
            container_payload = snapshot_payload.get("container", {})
            effective_scale = snapshot_payload.get("viewport", {}).get("scale", scale)
            min_spacing = float(spacing_base_px) * float(effective_scale)
            gap_px = float(grid_payload.get("gap_px", 0.0)) if isinstance(grid_payload, dict) else 0.0
            section_gap_px = (
                float(container_payload.get("section_gap_px", 0.0))
                if isinstance(container_payload, dict)
                else 0.0
            )
            if gap_px + 1e-9 < min_spacing:
                spacing_errors.append(
                    f"{layout_rel_path} [{case_id}]: grid gap {gap_px} is below scaled base spacing {min_spacing:.2f}."
                )
            if section_gap_px + 1e-9 < min_spacing:
                spacing_errors.append(
                    f"{layout_rel_path} [{case_id}]: section gap {section_gap_px} is below scaled base spacing {min_spacing:.2f}."
                )
            snapshot_rows.append(
                {
                    "case_id": case_id,
                    "ok": snapshot_payload.get("ok") is True,
                    "violations_count": len(snapshot_payload.get("violations", [])),
                }
            )
            if snapshot_has_violations(snapshot_payload):
                errors.extend(
                    f"{layout_rel_path} [{case_id}]: {violation.get('message', 'layout violation')}"
                    for violation in snapshot_payload.get("violations", [])
                    if isinstance(violation, dict)
                )
        layout_results.append(
            {
                "layout_path": layout_rel_path,
                "snapshots": snapshot_rows,
            }
        )

    interaction_payload = gui_design.get("interaction_standards", {})
    if isinstance(interaction_payload, dict):
        if interaction_payload.get("numeric_text_entry") is True and numeric_missing_direct_entry:
            errors.extend(
                f"Numeric control is missing direct text entry: {widget_id}."
                for widget_id in numeric_missing_direct_entry
            )
        if interaction_payload.get("units_always_visible") is True and numeric_missing_units:
            errors.extend(
                f"Numeric control is missing visible units metadata: {widget_id}."
                for widget_id in numeric_missing_units
            )
        if interaction_payload.get("fine_adjust_modifier_feedback") is True and drag_missing_fine_adjust:
            errors.extend(
                f"Drag control is missing fine-adjust metadata: {widget_id}."
                for widget_id in drag_missing_fine_adjust
            )
        if interaction_payload.get("global_scale_control") is True:
            errors.extend(scale_control_errors)

    errors.extend(theme_mismatches)
    errors.extend(spacing_errors)
    errors.extend(f"Missing required control kind in desktop HTML: {kind}." for kind in missing_control_kinds)
    errors.extend(
        f"Layout widget is missing from gui/desktop-tauri/index.html: {widget_id}."
        for widget_id in sorted(set(missing_layout_widgets))
    )
    errors = sorted(set(errors))

    return {
        "ok": not errors,
        "layout_results": layout_results,
        "missing_control_kinds": missing_control_kinds,
        "numeric_missing_direct_entry": numeric_missing_direct_entry,
        "numeric_missing_units": numeric_missing_units,
        "drag_missing_fine_adjust": drag_missing_fine_adjust,
        "scale_control_errors": scale_control_errors,
        "spacing_errors": spacing_errors,
        "theme_mismatches": theme_mismatches,
        "widget_count": len(html_parser.widgets),
        "errors": errors,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate the Tauri desktop design-system layout and ergonomics contract."
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing the desktop-tauri app and ontology.",
    )
    args = parser.parse_args()

    root = _resolve_path(args.repo_root, repo_root=repo_root)
    result = validate_tauri_design_system(repo_root=root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
