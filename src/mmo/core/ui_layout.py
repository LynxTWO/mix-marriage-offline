"""Deterministic UI layout snapshot solver."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

UI_LAYOUT_SCHEMA_VERSION = "0.1.0"
UI_LAYOUT_SNAPSHOT_SCHEMA_VERSION = "0.1.0"

_GRID_COLUMNS = 12
_PX_PRECISION = 6
_EPSILON = 1e-9
_VIEWPORT_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _round_px(value: float) -> float:
    rounded = round(value, _PX_PRECISION)
    if abs(rounded) < _EPSILON:
        return 0.0
    return rounded


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def parse_viewport_spec(raw_viewport: str) -> tuple[int, int]:
    match = _VIEWPORT_RE.match(_coerce_str(raw_viewport))
    if match is None:
        raise ValueError("Viewport must be in WxH form (for example: 1280x720).")
    width = int(match.group(1))
    height = int(match.group(2))
    if width < 1 or height < 1:
        raise ValueError("Viewport width and height must be >= 1.")
    return width, height


def _breakpoint_rows(layout: dict[str, Any]) -> list[dict[str, Any]]:
    raw = layout.get("breakpoints")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _select_breakpoint(
    layout: dict[str, Any],
    *,
    viewport_width_px: int,
) -> dict[str, Any] | None:
    matches: list[tuple[int, int, str, int, dict[str, Any]]] = []
    for index, breakpoint_row in enumerate(_breakpoint_rows(layout)):
        min_width = _optional_int(breakpoint_row.get("min_viewport_width_px"))
        max_width = _optional_int(breakpoint_row.get("max_viewport_width_px"))
        if min_width is not None and viewport_width_px < min_width:
            continue
        if max_width is not None and viewport_width_px > max_width:
            continue
        breakpoint_id = _coerce_str(breakpoint_row.get("breakpoint_id")).strip()
        sort_min = -(min_width if min_width is not None else -1)
        sort_max = max_width if max_width is not None else 10**9
        matches.append((sort_min, sort_max, breakpoint_id, index, breakpoint_row))

    if not matches:
        return None
    # Prefer the most specific matching breakpoint so larger-range fallbacks do
    # not shadow narrow layouts for the same viewport.
    matches.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return matches[0][4]


def _effective_scale(*, scale: float, selected_breakpoint: dict[str, Any] | None) -> float:
    if scale <= 0:
        raise ValueError("Scale must be > 0.")
    multiplier = 1.0
    if selected_breakpoint is not None:
        multiplier = _coerce_float(selected_breakpoint.get("scale_multiplier"), 1.0)
        if multiplier <= 0:
            multiplier = 1.0
    return _round_px(scale * multiplier)


def _effective_grid(
    layout: dict[str, Any],
    *,
    selected_breakpoint: dict[str, Any] | None,
    scale: float,
) -> dict[str, Any]:
    raw_grid = layout.get("grid")
    grid = raw_grid if isinstance(raw_grid, dict) else {}

    gap_px = _coerce_float(grid.get("gap_px"), 0.0)
    row_height_px = _coerce_float(grid.get("row_height_px"), 1.0)
    margin_px = _coerce_float(grid.get("margin_px"), 0.0)

    if selected_breakpoint is not None:
        raw_overrides = selected_breakpoint.get("grid_overrides")
        overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
        if "gap_px" in overrides:
            gap_px = _coerce_float(overrides.get("gap_px"), gap_px)
        if "row_height_px" in overrides:
            row_height_px = _coerce_float(overrides.get("row_height_px"), row_height_px)
        if "margin_px" in overrides:
            margin_px = _coerce_float(overrides.get("margin_px"), margin_px)

    return {
        "columns": _GRID_COLUMNS,
        "gap_px": _round_px(max(gap_px, 0.0) * scale),
        "row_height_px": _round_px(max(row_height_px, _EPSILON) * scale),
        "margin_px": _round_px(max(margin_px, 0.0) * scale),
    }


def _effective_container(
    layout: dict[str, Any],
    *,
    selected_breakpoint: dict[str, Any] | None,
    scale: float,
) -> dict[str, Any]:
    raw_container = layout.get("container")
    container = raw_container if isinstance(raw_container, dict) else {}
    section_gap_px = _coerce_float(container.get("section_gap_px"), 0.0)

    if selected_breakpoint is not None:
        raw_overrides = selected_breakpoint.get("container_overrides")
        overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
        if "section_gap_px" in overrides:
            section_gap_px = _coerce_float(
                overrides.get("section_gap_px"),
                section_gap_px,
            )

    return {"section_gap_px": _round_px(max(section_gap_px, 0.0) * scale)}


def _sorted_section_widgets(section: dict[str, Any]) -> list[dict[str, Any]]:
    raw_widgets = section.get("widgets")
    widgets = [row for row in raw_widgets if isinstance(row, dict)] if isinstance(raw_widgets, list) else []
    indexed_widgets = list(enumerate(widgets))
    # Sort by widget_id, then original index, so snapshots stay stable without
    # erasing author intent when duplicate ids slip through.
    indexed_widgets.sort(
        key=lambda item: (
            _coerce_str(item[1].get("widget_id")).strip(),
            item[0],
        )
    )
    return [row for _, row in indexed_widgets]


def _can_place(
    occupied_cells: set[tuple[int, int]],
    *,
    col_start: int,
    row_start: int,
    col_span: int,
    row_span: int,
) -> bool:
    for row in range(row_start, row_start + row_span):
        for col in range(col_start, col_start + col_span):
            if (row, col) in occupied_cells:
                return False
    return True


def _mark_cells(
    occupied_cells: set[tuple[int, int]],
    *,
    col_start: int,
    row_start: int,
    col_span: int,
    row_span: int,
) -> None:
    for row in range(row_start, row_start + row_span):
        for col in range(col_start, col_start + col_span):
            occupied_cells.add((row, col))


def _auto_place(
    occupied_cells: set[tuple[int, int]],
    *,
    section_columns: int,
    col_span: int,
    row_span: int,
) -> tuple[int, int]:
    if col_span > section_columns:
        max_row = max((row for row, _ in occupied_cells), default=0)
        return 1, max_row + 1

    # Auto-placement scans rows top-to-bottom, left-to-right. That keeps widget
    # placement deterministic when authors omit explicit grid coordinates.
    max_col_start = section_columns - col_span + 1
    row_start = 1
    while True:
        for col_start in range(1, max_col_start + 1):
            if _can_place(
                occupied_cells,
                col_start=col_start,
                row_start=row_start,
                col_span=col_span,
                row_span=row_span,
            ):
                return col_start, row_start
        row_start += 1


def _box_right(box: dict[str, Any]) -> float:
    return _round_px(_coerce_float(box.get("x_px")) + _coerce_float(box.get("width_px")))


def _box_bottom(box: dict[str, Any]) -> float:
    return _round_px(_coerce_float(box.get("y_px")) + _coerce_float(box.get("height_px")))


def _boxes_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_x = _coerce_float(left.get("x_px"))
    left_y = _coerce_float(left.get("y_px"))
    right_x = _coerce_float(right.get("x_px"))
    right_y = _coerce_float(right.get("y_px"))
    return (
        left_x < _box_right(right)
        and _box_right(left) > right_x
        and left_y < _box_bottom(right)
        and _box_bottom(left) > right_y
    )


def _overlap_evidence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    overlap_x = max(_coerce_float(left.get("x_px")), _coerce_float(right.get("x_px")))
    overlap_y = max(_coerce_float(left.get("y_px")), _coerce_float(right.get("y_px")))
    overlap_right = min(_box_right(left), _box_right(right))
    overlap_bottom = min(_box_bottom(left), _box_bottom(right))
    overlap_width = max(overlap_right - overlap_x, 0.0)
    overlap_height = max(overlap_bottom - overlap_y, 0.0)

    return {
        "section_id": _coerce_str(left.get("section_id")).strip(),
        "widget_id": _coerce_str(left.get("widget_id")).strip(),
        "other_widget_id": _coerce_str(right.get("widget_id")).strip(),
        "x_px": _round_px(overlap_x),
        "y_px": _round_px(overlap_y),
        "width_px": _round_px(overlap_width),
        "height_px": _round_px(overlap_height),
    }


def _issue(
    *,
    issue_id: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _coerce_str(issue.get("severity")).strip(),
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("message")).strip(),
        json.dumps(issue.get("evidence", {}), sort_keys=True, separators=(",", ":")),
    )


def _sorted_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=_issue_sort_key)


def build_ui_layout_snapshot(
    layout: dict[str, Any],
    *,
    layout_path: Path,
    viewport_width_px: int,
    viewport_height_px: int,
    scale: float = 1.0,
) -> dict[str, Any]:
    if viewport_width_px < 1 or viewport_height_px < 1:
        raise ValueError("Viewport width and height must be >= 1.")

    selected_breakpoint = _select_breakpoint(layout, viewport_width_px=viewport_width_px)
    # Breakpoint choice and scaled grid math are part of the snapshot receipt.
    # Keep them deterministic so UI lint and screenshot tests see the same boxes.
    effective_scale = _effective_scale(scale=scale, selected_breakpoint=selected_breakpoint)
    grid_payload = _effective_grid(
        layout,
        selected_breakpoint=selected_breakpoint,
        scale=effective_scale,
    )
    container_payload = _effective_container(
        layout,
        selected_breakpoint=selected_breakpoint,
        scale=effective_scale,
    )

    columns = _GRID_COLUMNS
    gap_px = _coerce_float(grid_payload.get("gap_px"))
    row_height_px = _coerce_float(grid_payload.get("row_height_px"))
    margin_px = _coerce_float(grid_payload.get("margin_px"))
    section_gap_px = _coerce_float(container_payload.get("section_gap_px"))

    content_width_px = max(float(viewport_width_px) - (2.0 * margin_px), 0.0)
    total_gaps_px = gap_px * float(columns - 1)
    column_width_px = (content_width_px - total_gaps_px) / float(columns)
    if column_width_px < 0:
        column_width_px = 0.0
    column_width_px = _round_px(column_width_px)

    raw_sections = layout.get("sections")
    section_rows = [row for row in raw_sections if isinstance(row, dict)] if isinstance(raw_sections, list) else []

    section_boxes: list[dict[str, Any]] = []
    widget_boxes: list[dict[str, Any]] = []

    cursor_y_px = margin_px
    for section in section_rows:
        section_id = _coerce_str(section.get("section_id")).strip()
        if not section_id:
            continue

        section_columns = _coerce_int(section.get("col_span"), columns)
        if section_columns < 1:
            section_columns = 1
        if section_columns > columns:
            section_columns = columns

        section_min_height_px = _coerce_float(section.get("min_height_px"), 0.0)
        section_min_height_px = _round_px(max(section_min_height_px, 0.0) * effective_scale)

        section_x_px = _round_px(margin_px)
        section_y_px = _round_px(cursor_y_px)
        section_width_px = _round_px(
            (column_width_px * float(section_columns))
            + (gap_px * float(max(section_columns - 1, 0)))
        )

        occupied_cells: set[tuple[int, int]] = set()
        section_bottom_px = section_y_px
        for widget in _sorted_section_widgets(section):
            widget_id = _coerce_str(widget.get("widget_id")).strip()
            if not widget_id:
                continue

            col_span = _coerce_int(widget.get("col_span"), 1)
            if col_span < 1:
                col_span = 1
            if col_span > columns:
                col_span = columns

            row_span = _coerce_int(widget.get("row_span"), 1)
            if row_span < 1:
                row_span = 1

            col_start = _optional_int(widget.get("col_start"))
            row_start = _optional_int(widget.get("row_start"))
            if col_start is None or row_start is None:
                col_start, row_start = _auto_place(
                    occupied_cells,
                    section_columns=section_columns,
                    col_span=col_span,
                    row_span=row_span,
                )
            if col_start < 1:
                col_start = 1
            if row_start < 1:
                row_start = 1

            _mark_cells(
                occupied_cells,
                col_start=col_start,
                row_start=row_start,
                col_span=col_span,
                row_span=row_span,
            )

            x_px = _round_px(section_x_px + float(col_start - 1) * (column_width_px + gap_px))
            y_px = _round_px(section_y_px + float(row_start - 1) * (row_height_px + gap_px))
            width_px = _round_px(
                (column_width_px * float(col_span))
                + (gap_px * float(max(col_span - 1, 0)))
            )
            height_px = _round_px(
                (row_height_px * float(row_span))
                + (gap_px * float(max(row_span - 1, 0)))
            )

            min_width_px = _coerce_float(widget.get("min_width_px"), 0.0)
            min_height_px = _coerce_float(widget.get("min_height_px"), 0.0)
            min_width_px = _round_px(max(min_width_px, 0.0) * effective_scale)
            min_height_px = _round_px(max(min_height_px, 0.0) * effective_scale)

            param_ref = widget.get("param_ref")
            normalized_param_ref = (
                param_ref.strip()
                if isinstance(param_ref, str) and param_ref.strip()
                else None
            )

            widget_box = {
                "widget_id": widget_id,
                "section_id": section_id,
                "param_ref": normalized_param_ref,
                "col_start": col_start,
                "col_span": col_span,
                "row_start": row_start,
                "row_span": row_span,
                "x_px": x_px,
                "y_px": y_px,
                "width_px": width_px,
                "height_px": height_px,
                "min_width_px": min_width_px,
                "min_height_px": min_height_px,
            }
            widget_boxes.append(widget_box)

            section_bottom_px = max(section_bottom_px, _box_bottom(widget_box))

        section_height_px = _round_px(max(section_bottom_px - section_y_px, section_min_height_px))
        section_boxes.append(
            {
                "section_id": section_id,
                "x_px": section_x_px,
                "y_px": section_y_px,
                "width_px": section_width_px,
                "height_px": section_height_px,
            }
        )
        cursor_y_px = _round_px(section_y_px + section_height_px + section_gap_px)

    widget_boxes.sort(
        key=lambda row: (
            _coerce_str(row.get("widget_id")).strip(),
            _coerce_str(row.get("section_id")).strip(),
        )
    )

    issues: list[dict[str, Any]] = []
    # Report layout violations instead of auto-fixing them. Silent repair would
    # hide broken metadata from plugin authors and UI review tests.
    for left_index, left in enumerate(widget_boxes):
        for right in widget_boxes[left_index + 1:]:
            if not _boxes_overlap(left, right):
                continue
            left_widget_id = _coerce_str(left.get("widget_id")).strip()
            right_widget_id = _coerce_str(right.get("widget_id")).strip()
            issues.append(
                _issue(
                    issue_id="ISSUE.UI.LAYOUT.OVERLAP",
                    severity="error",
                    message=f"Widget '{left_widget_id}' overlaps widget '{right_widget_id}'.",
                    evidence=_overlap_evidence(left, right),
                )
            )

    for widget in widget_boxes:
        x_px = _coerce_float(widget.get("x_px"))
        y_px = _coerce_float(widget.get("y_px"))
        width_px = _coerce_float(widget.get("width_px"))
        height_px = _coerce_float(widget.get("height_px"))
        right_px = _box_right(widget)
        bottom_px = _box_bottom(widget)

        section_id = _coerce_str(widget.get("section_id")).strip()
        widget_id = _coerce_str(widget.get("widget_id")).strip()

        if (
            x_px < -_EPSILON
            or y_px < -_EPSILON
            or right_px > float(viewport_width_px) + _EPSILON
            or bottom_px > float(viewport_height_px) + _EPSILON
        ):
            issues.append(
                _issue(
                    issue_id="ISSUE.UI.LAYOUT.OFF_SCREEN",
                    severity="error",
                    message=f"Widget '{widget_id}' extends beyond the viewport bounds.",
                    evidence={
                        "section_id": section_id,
                        "widget_id": widget_id,
                        "viewport_width_px": viewport_width_px,
                        "viewport_height_px": viewport_height_px,
                        "x_px": _round_px(x_px),
                        "y_px": _round_px(y_px),
                        "width_px": _round_px(width_px),
                        "height_px": _round_px(height_px),
                    },
                )
            )

        min_width_px = _coerce_float(widget.get("min_width_px"))
        min_height_px = _coerce_float(widget.get("min_height_px"))
        if width_px + _EPSILON < min_width_px or height_px + _EPSILON < min_height_px:
            issues.append(
                _issue(
                    issue_id="ISSUE.UI.LAYOUT.MIN_SIZE_BROKEN",
                    severity="error",
                    message=f"Widget '{widget_id}' violates minimum size constraints.",
                    evidence={
                        "section_id": section_id,
                        "widget_id": widget_id,
                        "x_px": _round_px(x_px),
                        "y_px": _round_px(y_px),
                        "width_px": _round_px(width_px),
                        "height_px": _round_px(height_px),
                        "required_min_width_px": _round_px(min_width_px),
                        "required_min_height_px": _round_px(min_height_px),
                    },
                )
            )

    selected_breakpoint_id = None
    if selected_breakpoint is not None:
        selected_breakpoint_id = _coerce_str(selected_breakpoint.get("breakpoint_id")).strip() or None

    violations = _sorted_issues(issues)
    return {
        "schema_version": UI_LAYOUT_SNAPSHOT_SCHEMA_VERSION,
        "layout_path": _path_to_posix(layout_path),
        "layout_id": _coerce_str(layout.get("layout_id")).strip(),
        "viewport": {
            "width_px": viewport_width_px,
            "height_px": viewport_height_px,
            "scale": effective_scale,
        },
        "grid": grid_payload,
        "container": container_payload,
        "selected_breakpoint_id": selected_breakpoint_id,
        "sections": section_boxes,
        "widgets": widget_boxes,
        "violations": violations,
        "ok": len(violations) == 0,
    }


def snapshot_has_violations(snapshot_payload: dict[str, Any]) -> bool:
    raw_violations = snapshot_payload.get("violations")
    return isinstance(raw_violations, list) and len(raw_violations) > 0


__all__ = [
    "UI_LAYOUT_SCHEMA_VERSION",
    "UI_LAYOUT_SNAPSHOT_SCHEMA_VERSION",
    "parse_viewport_spec",
    "build_ui_layout_snapshot",
    "snapshot_has_violations",
]
