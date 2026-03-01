"""Headless GUI screenshot capture for MMO scenarios.

Entry point::

    python -m mmo.gui.capture --scenario GUI.CAPTURE.RUN_READY --out /tmp/rr.png
    python -m mmo.gui.capture --scenario GUI.CAPTURE.DASHBOARD_SAFE --out /tmp/safe.png [--json]

Each scenario launches a CustomTkinter window in a deterministic state, waits for the
first stable render, captures the window to a PNG, and exits cleanly.

Linux headless CI: run under xvfb-run::

    xvfb-run -a python -m mmo.gui.capture --scenario GUI.CAPTURE.RUN_READY --out rr.png

macOS / Windows: best-effort (no guarantees; mss behaviour varies).

Exit codes:
    0  — PNG written successfully.
    1  — Error (unknown scenario, missing dependency, capture failure).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Scenario IDs
# ---------------------------------------------------------------------------

SCENARIO_RUN_READY = "GUI.CAPTURE.RUN_READY"
SCENARIO_DASHBOARD_SAFE = "GUI.CAPTURE.DASHBOARD_SAFE"
SCENARIO_DASHBOARD_EXTREME = "GUI.CAPTURE.DASHBOARD_EXTREME"

KNOWN_SCENARIOS: frozenset[str] = frozenset(
    {
        SCENARIO_RUN_READY,
        SCENARIO_DASHBOARD_SAFE,
        SCENARIO_DASHBOARD_EXTREME,
    }
)

# ---------------------------------------------------------------------------
# Optional dependency guards (tested without launching Tk or mss)
# ---------------------------------------------------------------------------

try:
    import customtkinter as _ctk
except Exception:  # pragma: no cover
    _ctk = None  # type: ignore[assignment]

try:
    import mss as _mss
    import mss.tools as _mss_tools
except Exception:  # pragma: no cover
    _mss = None  # type: ignore[assignment]
    _mss_tools = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal capture helper
# ---------------------------------------------------------------------------

def _do_capture(root: Any, out_path: Path) -> bool:
    """Capture the window identified by *root* to *out_path* (PNG).

    Returns True on success, False on failure (prints error to stderr).
    """
    try:
        root.update()
        root.update_idletasks()

        x = root.winfo_rootx()
        y = root.winfo_rooty()
        w = root.winfo_width()
        h = root.winfo_height()

        if w <= 1 or h <= 1:
            print(
                f"[capture] Warning: window reports size {w}x{h}; "
                "may not be mapped yet.",
                file=sys.stderr,
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Prefer PIL.ImageGrab (uses xwd under X11/Xvfb; works where mss/XGetImage fails).
        # Fall back to mss if ImageGrab is unavailable.
        try:
            from PIL import ImageGrab  # noqa: PLC0415
            bbox = (x, y, x + max(w, 1), y + max(h, 1))
            img = ImageGrab.grab(bbox=bbox)
            img.save(str(out_path), format="PNG")
        except Exception:  # noqa: BLE001
            with _mss.mss() as sct:  # type: ignore[union-attr]
                monitor = {"top": y, "left": x, "width": max(w, 1), "height": max(h, 1)}
                screenshot = sct.grab(monitor)
                _mss_tools.to_png(screenshot.rgb, screenshot.size, output=str(out_path))

        if not out_path.is_file() or out_path.stat().st_size == 0:
            print(f"[capture] Error: output file is empty: {out_path}", file=sys.stderr)
            return False

        print(f"[capture] Saved: {out_path} ({out_path.stat().st_size} bytes)")
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"[capture] Capture failed: {exc}", file=sys.stderr)
        return False


def _capture_and_exit(root: Any, out_path: Path, state: dict[str, Any]) -> None:
    """Capture then destroy the window; record result in *state*."""
    success = _do_capture(root, out_path)
    state["ok"] = success
    if not success:
        state["error"] = "capture failed — see stderr"
    try:
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Scenario: RUN_READY — full _MMOGuiApp in default state
# ---------------------------------------------------------------------------

def _capture_run_ready(out_path: Path, width: int, height: int) -> bool:
    """Launch the real _MMOGuiApp, capture after first stable frame, exit."""
    from mmo.gui.main import _MMOGuiApp  # noqa: PLC0415 - intentional lazy import

    state: dict[str, Any] = {"ok": False}

    _ctk.set_appearance_mode("dark")
    _ctk.set_default_color_theme("dark-blue")

    app = _MMOGuiApp()
    app.geometry(f"{width}x{height}")
    app.minsize(width, height)
    app.update()
    app.update_idletasks()

    delay_ms = 600
    app.after(delay_ms, lambda: _capture_and_exit(app, out_path, state))
    app.mainloop()

    return state.get("ok", False)


# ---------------------------------------------------------------------------
# Scenario: DASHBOARD_SAFE / DASHBOARD_EXTREME — standalone dashboard window
# ---------------------------------------------------------------------------

def _capture_dashboard(
    out_path: Path,
    width: int,
    height: int,
    *,
    extreme: bool,
) -> bool:
    """Create a minimal CTk window with the dashboard panel and capture it."""
    from mmo.gui.dashboard import VisualizationDashboardPanel  # noqa: PLC0415
    from mmo.gui.fixtures.telemetry import (  # noqa: PLC0415
        extreme_dashboard_telemetry,
        safe_dashboard_telemetry,
    )

    state: dict[str, Any] = {"ok": False}
    telemetry = extreme_dashboard_telemetry() if extreme else safe_dashboard_telemetry()

    _ctk.set_appearance_mode("dark")
    _ctk.set_default_color_theme("dark-blue")

    root = _ctk.CTk()
    root.title("MMO Dashboard Capture")
    root.geometry(f"{width}x{height}")
    root.configure(fg_color="#0A0A09")
    root.resizable(False, False)
    root.update()

    # Build the panel (calls _render_and_schedule once synchronously)
    panel = VisualizationDashboardPanel(root, ctk_module=_ctk)

    # Override telemetry and force one more render pass with the new data
    panel._telemetry = telemetry  # type: ignore[attr-defined]
    panel._render_and_schedule()  # type: ignore[attr-defined]

    panel.container.pack(fill="both", expand=True, padx=4, pady=4)

    root.update()
    root.update_idletasks()

    delay_ms = 500
    root.after(delay_ms, lambda: _capture_and_exit(root, out_path, state))
    root.mainloop()

    return state.get("ok", False)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture MMO GUI screenshots for documentation.",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help=(
            "Scenario ID to capture. "
            f"Known values: {', '.join(sorted(KNOWN_SCENARIOS))}"
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output PNG file path.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1360,
        help="Capture window width in pixels (default: 1360).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=840,
        help="Capture window height in pixels (default: 840).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any warning or partial failure.",
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON status to stdout.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    scenario = args.scenario.strip()
    out_path = Path(args.out)

    result: dict[str, Any] = {
        "ok": False,
        "scenario": scenario,
        "out": str(out_path),
        "error": None,
    }

    # -- Validate scenario ID ------------------------------------------------
    if scenario not in KNOWN_SCENARIOS:
        result["error"] = (
            f"Unknown scenario: {scenario!r}. "
            f"Known values: {sorted(KNOWN_SCENARIOS)}"
        )
        if args.emit_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"[capture] error: {result['error']}", file=sys.stderr)
        return 1

    # -- Dependency guards ----------------------------------------------------
    if _ctk is None:
        result["error"] = (
            "customtkinter is not installed. "
            "Install with: pip install .[gui]"
        )
        if args.emit_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"[capture] error: {result['error']}", file=sys.stderr)
        return 1

    if _mss is None:
        result["error"] = (
            "mss is not installed. "
            "Install with: pip install .[screenshots]"
        )
        if args.emit_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"[capture] error: {result['error']}", file=sys.stderr)
        return 1

    # -- Validate output path parent ------------------------------------------
    if not out_path.parent.exists() and not str(out_path.parent) == ".":
        # Allow the capture functions to create the parent, but if it's clearly
        # wrong (non-existent absolute parent), fail early.
        resolved_parent = out_path.parent.resolve()
        if resolved_parent.is_absolute() and not resolved_parent.exists():
            try:
                resolved_parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                result["error"] = f"Cannot create output directory: {exc}"
                if args.emit_json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(f"[capture] error: {result['error']}", file=sys.stderr)
                return 1

    # -- Dispatch to scenario -------------------------------------------------
    try:
        if scenario == SCENARIO_RUN_READY:
            ok = _capture_run_ready(out_path, args.width, args.height)
        elif scenario == SCENARIO_DASHBOARD_SAFE:
            ok = _capture_dashboard(out_path, args.width, args.height, extreme=False)
        else:  # SCENARIO_DASHBOARD_EXTREME
            ok = _capture_dashboard(out_path, args.width, args.height, extreme=True)
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        if args.emit_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"[capture] error: {exc}", file=sys.stderr)
        return 1

    result["ok"] = ok
    if not ok and result["error"] is None:
        result["error"] = "capture returned False — see stderr for details"

    if args.emit_json:
        print(json.dumps(result, indent=2, sort_keys=True))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
