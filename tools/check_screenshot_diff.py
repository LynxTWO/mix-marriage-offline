"""Perceptual screenshot diff checker for MMO manual canonical-state screenshots.

Compares the committed canonical-state baselines against freshly-generated
screenshots and fails only when the mean absolute pixel difference exceeds a
threshold.

Small PNG-compression jitter and minor rendering variance are acceptable. The
default threshold of 20.0 means the average pixel across the *entire* image
must shift by ~8 % of full scale before CI treats it as a meaningful
canonical-state or layout change.

Usage::

    python tools/check_screenshot_diff.py \\
        --committed docs/manual/assets/screenshots \\
        --generated /tmp/mmo-gui-screens

Exit codes:
    0  — all files within tolerance.
    1  — one or more files exceed the threshold, or a dependency is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from screenshot_baselines import (
        CANONICAL_SCREENSHOTS,
        SCREENSHOT_POLICY_PATH,
        WALKTHROUGH_PATH,
        canonical_filenames,
        format_screenshot_inventory,
        format_text_only_inventory,
    )
except ImportError:  # pragma: no cover - module mode fallback
    from tools.screenshot_baselines import (
        CANONICAL_SCREENSHOTS,
        SCREENSHOT_POLICY_PATH,
        WALKTHROUGH_PATH,
        canonical_filenames,
        format_screenshot_inventory,
        format_text_only_inventory,
    )


# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

#: Maximum allowed per-channel mean absolute pixel difference (0–255 scale).
#:
#: The threshold is set to 20.0 so minor pixel variance can pass while
#: substantial canonical-state or layout changes still fail loudly.
#:
#: To update committed baselines after an intentional large GUI change, run:
#:   python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
#: Then update the walkthrough chapter and screenshot policy README if the
#: screen meaning changed, and commit the result.
THRESHOLD_MAE: float = 20.0


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def _mean_abs_diff(path_a: Path, path_b: Path) -> float:
    """Return the per-channel mean absolute pixel difference (0–255 scale)."""
    try:
        from PIL import Image, ImageChops, ImageStat  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"[screenshot-diff] Missing dependency: {exc}\n"
            "Install with: pip install -e \".[screenshots]\"\n"
            "Fallback: pip install pillow",
            file=sys.stderr,
        )
        sys.exit(1)

    with Image.open(path_a) as image_a, Image.open(path_b) as image_b:
        rgb_a = image_a.convert("RGB")
        rgb_b = image_b.convert("RGB")

    if rgb_a.size != rgb_b.size:
        raise ValueError(
            f"Image size mismatch: {path_a.name} is {rgb_a.size[1]}x{rgb_a.size[0]} "
            f"but {path_b.name} is {rgb_b.size[1]}x{rgb_b.size[0]}"
        )

    diff_image = ImageChops.difference(rgb_a, rgb_b)
    channel_means = ImageStat.Stat(diff_image).mean
    return float(sum(channel_means) / len(channel_means))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    epilog = (
        "Committed canonical screenshot baselines:\n"
        f"{format_screenshot_inventory(include_locations=True)}\n\n"
        "Named canonical state that stays text-only:\n"
        f"{format_text_only_inventory(include_locations=True)}\n\n"
        "Small variance is acceptable. Large state/layout changes require "
        "refreshed baselines plus manual chapter updates.\n"
        "Native file pickers and other OS dialogs are intentionally excluded from "
        "committed baselines.\n"
        f"Policy + refresh guide: {SCREENSHOT_POLICY_PATH.as_posix()}"
    )
    parser = argparse.ArgumentParser(
        description=(
            "Perceptual screenshot diff checker for MMO manual canonical-state "
            "screenshots."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--committed",
        required=True,
        metavar="DIR",
        help="Directory containing committed canonical-state baseline PNGs.",
    )
    parser.add_argument(
        "--generated",
        required=True,
        metavar="DIR",
        help="Directory containing freshly-generated canonical-state PNGs.",
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
    expected_files = canonical_filenames()

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

    committed_pngs = {path.name: path for path in sorted(committed_dir.glob("*.png"))}
    generated_pngs = {path.name: path for path in sorted(generated_dir.glob("*.png"))}

    if not committed_pngs:
        print(
            f"[screenshot-diff] No PNGs found in committed dir: {committed_dir}",
            file=sys.stderr,
        )
        return 1

    extra_committed = sorted(set(committed_pngs) - set(expected_files))
    extra_generated = sorted(set(generated_pngs) - set(expected_files))
    if extra_committed:
        print(
            "[screenshot-diff] Ignoring non-canonical committed PNGs: "
            f"{extra_committed}"
        )
    if extra_generated:
        print(
            "[screenshot-diff] Ignoring non-canonical generated PNGs: "
            f"{extra_generated}"
        )

    # (filename, state_name, mae_or_nan, status_string)
    rows: list[tuple[str, str, float, str]] = []
    failures: list[tuple[str, str]] = []

    for baseline in CANONICAL_SCREENSHOTS:
        name = baseline.filename
        state_name = baseline.state_name
        committed_path = committed_pngs.get(name)
        generated_path = generated_pngs.get(name)

        if committed_path is None:
            rows.append((name, state_name, float("nan"), "MISSING baseline"))
            failures.append((name, state_name))
            continue

        if generated_path is None:
            rows.append((name, state_name, float("nan"), "MISSING generated"))
            failures.append((name, state_name))
            continue

        try:
            mae = _mean_abs_diff(committed_path, generated_path)
        except Exception as exc:  # noqa: BLE001
            rows.append((name, state_name, float("nan"), f"ERROR: {exc}"))
            failures.append((name, state_name))
            continue

        status = "PASS" if mae <= threshold else "FAIL"
        rows.append((name, state_name, mae, status))
        if status == "FAIL":
            failures.append((name, state_name))

    # Print results table.
    name_w = max(len(r[0]) for r in rows)
    state_w = max(len(r[1]) for r in rows)
    header = f"{'File':<{name_w}}  {'State':<{state_w}}  {'MAE':>8}  {'threshold':>10}  Status"
    print(f"\n{header}")
    print("-" * len(header))
    for name, state_name, mae, status in rows:
        mae_str = f"{mae:8.3f}" if mae == mae else "     N/A"  # NaN check
        print(
            f"{name:<{name_w}}  {state_name:<{state_w}}  "
            f"{mae_str}  {threshold:>10.1f}  {status}"
        )
    print()

    if failures:
        failure_labels = [f"{name} ({state_name})" for name, state_name in failures]
        print(
            f"[screenshot-diff] FAILED: {len(failures)} file(s) exceed "
            f"threshold (MAE > {threshold:.1f}) or are missing: {failure_labels}",
            file=sys.stderr,
        )
        print(
            "[screenshot-diff] Small variance is acceptable. A failure usually "
            "means the canonical state meaning/layout changed or the capture "
            "drifted into the wrong state.",
            file=sys.stderr,
        )
        print(
            "[screenshot-diff] If the change is intentional, refresh the "
            "committed baselines and update both:\n"
            f"    {WALKTHROUGH_PATH.as_posix()}\n"
            f"    {SCREENSHOT_POLICY_PATH.as_posix()}",
            file=sys.stderr,
        )
        print(
            "[screenshot-diff] Refresh command:\n"
            "    python tools/capture_tauri_screenshots.py "
            "--out-dir docs/manual/assets/screenshots",
            file=sys.stderr,
        )
        return 1

    print(
        f"[screenshot-diff] All {len(rows)} canonical screenshot(s) within "
        f"tolerance (MAE ≤ {threshold:.1f}). Small variance is acceptable; no "
        "baseline refresh is needed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
