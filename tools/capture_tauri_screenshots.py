"""Repo-level wrapper: generate all required MMO Tauri GUI screenshots.

Runs the Playwright capture spec in ``gui/desktop-tauri/tests/`` via ``npx``,
which loads each screen with fixture data and writes PNGs to the output
directory.

The dev server does not need to be started manually — the Playwright
``webServer`` block in ``playwright.config.ts`` starts ``npm run dev``
automatically when the server is not already running.

Usage::

    python tools/capture_tauri_screenshots.py
    python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
    python tools/capture_tauri_screenshots.py --out-dir /tmp/tauri-screenshots

To update the committed baselines after an intentional GUI change, run with the
default ``--out-dir`` (or point it at the committed path) and commit the result::

    python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
    git add docs/manual/assets/screenshots/tauri_*.png
    git commit -m "Update Tauri GUI screenshot baselines"

Exit code: 0 if all expected screenshots were written, 1 if Playwright failed
or any expected output file is missing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = REPO_ROOT / "gui" / "desktop-tauri"

DEFAULT_OUT_DIR = "docs/manual/assets/screenshots"

# Must match the filenames written by capture-screenshots.spec.ts.
EXPECTED_FILES: tuple[str, ...] = (
    "tauri_session_ready.png",
    "tauri_scene_loaded.png",
    "tauri_results_loaded.png",
    "tauri_compare_loaded.png",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate all MMO Tauri GUI screenshots into a target directory.",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for PNGs (default: {DEFAULT_OUT_DIR}).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (REPO_ROOT / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not TAURI_DIR.is_dir():
        print(
            f"[tauri-capture] Tauri directory not found: {TAURI_DIR}",
            file=sys.stderr,
        )
        return 1

    env = os.environ.copy()
    env["MMO_CAPTURE_SCREENSHOTS"] = "1"
    env["MMO_SCREENSHOT_DIR"] = str(out_dir)

    cmd = [
        "npx",
        "playwright",
        "test",
        "tests/capture-screenshots.spec.ts",
        "--project=firefox",
        "--reporter=list",
    ]

    print(f"[tauri-capture] Running Playwright capture spec → {out_dir}")
    result = subprocess.run(cmd, env=env, cwd=str(TAURI_DIR))

    if result.returncode != 0:
        print(
            f"[tauri-capture] Playwright exited with code {result.returncode}.",
            file=sys.stderr,
        )
        return 1

    # Verify all expected files were written.
    failures: list[str] = []
    for filename in EXPECTED_FILES:
        out_path = out_dir / filename
        if out_path.is_file():
            size = out_path.stat().st_size
            print(f"  OK  {filename} ({size} bytes)")
        else:
            print(f"  MISSING  {filename}", file=sys.stderr)
            failures.append(filename)

    if failures:
        print(
            f"\n[tauri-capture] {len(failures)} file(s) missing after Playwright run: {failures}",
            file=sys.stderr,
        )
        return 1

    print(f"\n[tauri-capture] All {len(EXPECTED_FILES)} screenshot(s) written → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
