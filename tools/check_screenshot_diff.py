"""Perceptual screenshot diff checker for MMO manual screenshots.

Compares committed (baseline) screenshots against freshly-generated ones and
fails only when the mean absolute pixel difference exceeds a threshold.

Pure PNG-compression jitter and minor animation-frame variance (observed MAE
< 3.0) pass silently.  The default threshold of 20.0 means the average pixel
across the *entire* image must shift by ~8 % of full scale — requiring a
substantial layout change, major colour-scheme revision, or large widget
addition/removal to trigger a failure.

Usage::

    python tools/check_screenshot_diff.py \\
        --committed docs/manual/assets/screenshots \\
        --generated /tmp/mmo-gui-screenshots

Exit codes:
    0  — all files within tolerance.
    1  — one or more files exceed the threshold, or a dependency is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

#: Maximum allowed per-channel mean absolute pixel difference (0–255 scale).
#:
#: Calibration (measured on ubuntu-24.04 with Python 3.12 / Pillow 11):
#:   - gui_run_ready.png   jitter MAE ≈ 0.00  (fully deterministic)
#:   - dashboard_safe.png  jitter MAE ≈ 2.31  (animation-frame variance)
#:   - dashboard_extreme.png jitter MAE ≈ 1.21 (animation-frame variance)
#:
#: The threshold is set to 20.0 — nearly 9× the worst observed jitter —
#: so only genuinely large visual changes (major panel add/remove, dramatic
#: colour-scheme shift, significant layout restructure) will trip CI.
#: Minor GUI tweaks (a label change, a small colour nudge, a single widget
#: moved by a few pixels) fall well below this bar and pass silently.
#:
#: To update committed baselines after an intentional large GUI change, run:
#:   python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
#: and commit the result.
#: (Legacy CTK baselines used: xvfb-run -a python tools/capture_gui_screenshots.py)
THRESHOLD_MAE: float = 20.0


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def _mean_abs_diff(path_a: Path, path_b: Path) -> float:
    """Return the per-channel mean absolute pixel difference (0–255 scale)."""
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"[screenshot-diff] Missing dependency: {exc}\n"
            "Install with: pip install -e \".[screenshots]\"\n"
            "Fallback: pip install pillow numpy",
            file=sys.stderr,
        )
        sys.exit(1)

    arr_a = np.asarray(Image.open(path_a).convert("RGB"), dtype=float)
    arr_b = np.asarray(Image.open(path_b).convert("RGB"), dtype=float)

    if arr_a.shape != arr_b.shape:
        raise ValueError(
            f"Image size mismatch: {path_a.name} is {arr_a.shape[:2]} "
            f"but {path_b.name} is {arr_b.shape[:2]}"
        )

    return float(np.abs(arr_a - arr_b).mean())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Perceptual screenshot diff checker for MMO manual screenshots.",
    )
    parser.add_argument(
        "--committed",
        required=True,
        metavar="DIR",
        help="Directory containing committed (baseline) screenshot PNGs.",
    )
    parser.add_argument(
        "--generated",
        required=True,
        metavar="DIR",
        help="Directory containing freshly-generated screenshot PNGs.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD_MAE,
        metavar="N",
        help=(
            f"Max allowed per-channel mean absolute pixel diff (0–255 scale). "
            f"Default: {THRESHOLD_MAE}"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    committed_dir = Path(args.committed)
    generated_dir = Path(args.generated)
    threshold = args.threshold

    if not committed_dir.is_dir():
        print(
            f"[screenshot-diff] Committed dir not found: {committed_dir}",
            file=sys.stderr,
        )
        return 1
    if not generated_dir.is_dir():
        print(
            f"[screenshot-diff] Generated dir not found: {generated_dir}",
            file=sys.stderr,
        )
        return 1

    committed_pngs = sorted(committed_dir.glob("*.png"))
    if not committed_pngs:
        print(
            f"[screenshot-diff] No PNGs found in committed dir: {committed_dir}",
            file=sys.stderr,
        )
        return 1

    # (filename, mae_or_nan, status_string)
    rows: list[tuple[str, float, str]] = []
    failures: list[str] = []

    for committed_path in committed_pngs:
        name = committed_path.name
        generated_path = generated_dir / name

        if not generated_path.exists():
            rows.append((name, float("nan"), "MISSING"))
            failures.append(name)
            continue

        try:
            mae = _mean_abs_diff(committed_path, generated_path)
        except Exception as exc:  # noqa: BLE001
            rows.append((name, float("nan"), f"ERROR: {exc}"))
            failures.append(name)
            continue

        status = "PASS" if mae <= threshold else "FAIL"
        rows.append((name, mae, status))
        if status == "FAIL":
            failures.append(name)

    # Print results table.
    name_w = max(len(r[0]) for r in rows)
    header = f"{'File':<{name_w}}  {'MAE':>8}  {'threshold':>10}  Status"
    print(f"\n{header}")
    print("-" * len(header))
    for name, mae, status in rows:
        mae_str = f"{mae:8.3f}" if mae == mae else "     N/A"  # NaN check
        print(f"{name:<{name_w}}  {mae_str}  {threshold:>10.1f}  {status}")
    print()

    if failures:
        print(
            f"[screenshot-diff] FAILED: {len(failures)} file(s) exceed "
            f"threshold (MAE > {threshold:.1f}): {failures}",
            file=sys.stderr,
        )
        print(
            "[screenshot-diff] To update committed baselines after an "
            "intentional GUI change, run:\n"
            "    python tools/capture_tauri_screenshots.py "
            "--out-dir docs/manual/assets/screenshots\n"
            "and commit the result.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[screenshot-diff] All {len(rows)} file(s) within tolerance "
        f"(MAE ≤ {threshold:.1f})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
