"""Repo-level wrapper: generate MMO Tauri canonical-state GUI screenshots.

Runs the Playwright capture spec in ``gui/desktop-tauri/tests/`` via ``npx``,
which loads each screen with fixture data and writes PNGs to the output
directory.

The dev server does not need to be started manually — the Playwright
``webServer`` block in ``playwright.config.ts`` starts ``npm run dev``
automatically when the server is not already running.

These screenshots are deterministic, named canonical app states for the manual
and regression baselines. They do not attempt to capture every transient GUI
state, and native OS dialogs stay text-only.

Usage::

    python tools/capture_tauri_screenshots.py
    python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
    python tools/capture_tauri_screenshots.py --out-dir /tmp/mmo-gui-screens

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

try:
    from screenshot_baselines import (
        DEFAULT_BASELINE_DIR,
        SCREENSHOT_POLICY_PATH,
        WALKTHROUGH_PATH,
        canonical_filenames,
        format_screenshot_inventory,
        format_text_only_inventory,
    )
except ImportError:  # pragma: no cover - module mode fallback
    from tools.screenshot_baselines import (
        DEFAULT_BASELINE_DIR,
        SCREENSHOT_POLICY_PATH,
        WALKTHROUGH_PATH,
        canonical_filenames,
        format_screenshot_inventory,
        format_text_only_inventory,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = REPO_ROOT / "gui" / "desktop-tauri"

DEFAULT_OUT_DIR = str(DEFAULT_BASELINE_DIR)

EXPECTED_FILES: tuple[str, ...] = canonical_filenames()


def _parse_args() -> argparse.Namespace:
    epilog = (
        "Committed canonical screenshot baselines:\n"
        f"{format_screenshot_inventory(include_locations=True)}\n\n"
        "Named canonical state that stays text-only:\n"
        f"{format_text_only_inventory(include_locations=True)}\n\n"
        "Native file pickers and other OS dialogs are intentionally excluded from\n"
        "committed baselines.\n"
        f"Policy + refresh guide: {SCREENSHOT_POLICY_PATH.as_posix()}"
    )
    parser = argparse.ArgumentParser(
        description=(
            "Generate MMO Tauri canonical-state GUI screenshots into a target directory."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=(
            f"Output directory for PNGs (default: {DEFAULT_OUT_DIR}). "
            "Use a temp dir first if you want to diff before refreshing the "
            "committed baselines."
        ),
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

    print("[tauri-capture] Canonical screenshot set:")
    print(format_screenshot_inventory(include_locations=False))
    print("[tauri-capture] Named text-only canonical state:")
    print(format_text_only_inventory(include_locations=False))
    print(
        "[tauri-capture] Native OS dialogs and other transient states are "
        "excluded from committed baselines."
    )
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
    committed_dir = (REPO_ROOT / DEFAULT_BASELINE_DIR).resolve()
    if out_dir == committed_dir:
        print(
            "[tauri-capture] Refreshed committed canonical-state baselines. "
            f"If the screen meaning changed, update {WALKTHROUGH_PATH.as_posix()} "
            f"and {SCREENSHOT_POLICY_PATH.as_posix()} in the same change."
        )
    else:
        print(
            "[tauri-capture] Compare against committed baselines with:\n"
            "    python tools/check_screenshot_diff.py "
            f"--committed {DEFAULT_BASELINE_DIR.as_posix()} --generated {out_dir}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
