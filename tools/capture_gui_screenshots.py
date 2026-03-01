"""Repo-level wrapper: generate all required MMO GUI screenshots.

Usage::

    xvfb-run -a python tools/capture_gui_screenshots.py
    xvfb-run -a python tools/capture_gui_screenshots.py --out-dir docs/manual/assets/screenshots
    xvfb-run -a python tools/capture_gui_screenshots.py --width 1360 --height 840

Calls ``python -m mmo.gui.capture`` for each scenario via subprocess so that
each capture runs in a fresh Tk session (multiple Tk roots in one process is
unsupported by most Tkinter builds).

Exit code: 0 if all scenarios succeeded, 1 if any failed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# (scenario_id, output_filename)
SCENARIOS: tuple[tuple[str, str], ...] = (
    ("GUI.CAPTURE.RUN_READY", "gui_run_ready.png"),
    ("GUI.CAPTURE.DASHBOARD_SAFE", "dashboard_safe.png"),
    ("GUI.CAPTURE.DASHBOARD_EXTREME", "dashboard_extreme.png"),
)

DEFAULT_OUT_DIR = "docs/manual/assets/screenshots"
DEFAULT_WIDTH = 1360
DEFAULT_HEIGHT = 840


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate all MMO GUI screenshots into a target directory.",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for PNGs (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_WIDTH,
        help=f"Capture window width in pixels (default: {DEFAULT_WIDTH}).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_HEIGHT,
        help=f"Capture window height in pixels (default: {DEFAULT_HEIGHT}).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (REPO_ROOT / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(SRC_DIR)

    failures: list[str] = []

    for scenario_id, filename in SCENARIOS:
        out_path = out_dir / filename
        cmd = [
            sys.executable,
            "-m",
            "mmo.gui.capture",
            "--scenario",
            scenario_id,
            "--out",
            str(out_path),
            "--width",
            str(args.width),
            "--height",
            str(args.height),
        ]
        print(f"[capture] Running: {scenario_id} → {filename}")
        result = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
        if result.returncode == 0:
            size = out_path.stat().st_size if out_path.is_file() else 0
            print(f"  OK  {scenario_id} → {filename} ({size} bytes)")
        else:
            print(f"  FAIL  {scenario_id} → {filename} (exit {result.returncode})")
            failures.append(scenario_id)

    if failures:
        print(
            f"\n[capture] {len(failures)} scenario(s) failed: {failures}",
            file=sys.stderr,
        )
        return 1

    print(f"\n[capture] All {len(SCENARIOS)} scenario(s) succeeded → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
