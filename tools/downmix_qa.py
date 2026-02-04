"""Run downmix QA on a multichannel source and stereo reference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.core.downmix_qa import run_downmix_qa  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare downmix fold against a stereo reference.")
    parser.add_argument("--src", required=True, help="Path to the multichannel source file.")
    parser.add_argument("--ref", required=True, help="Path to the stereo reference file.")
    parser.add_argument("--source-layout", required=True, help="Source layout ID.")
    parser.add_argument("--policy", default=None, help="Optional policy ID override.")
    parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default="truth",
        help="Meter pack to use (basic or truth).",
    )
    parser.add_argument(
        "--tolerance-lufs",
        type=float,
        default=1.0,
        help="LUFS delta tolerance for QA warnings.",
    )
    parser.add_argument(
        "--tolerance-true-peak",
        type=float,
        default=1.0,
        help="True peak delta tolerance (dBTP) for QA warnings.",
    )
    parser.add_argument(
        "--tolerance-corr",
        type=float,
        default=0.15,
        help="Correlation delta tolerance for QA warnings.",
    )
    parser.add_argument("--out", default=None, help="Optional output path; defaults to stdout.")
    args = parser.parse_args()

    try:
        report = run_downmix_qa(
            Path(args.src),
            Path(args.ref),
            source_layout_id=args.source_layout,
            policy_id=args.policy,
            tolerance_lufs=args.tolerance_lufs,
            tolerance_true_peak_db=args.tolerance_true_peak,
            tolerance_corr=args.tolerance_corr,
            repo_root=ROOT_DIR,
            meters=args.meters,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    else:
        print(output, end="")

    issues = report.get("downmix_qa", {}).get("issues", [])
    has_error = any(
        isinstance(issue, dict) and issue.get("severity", 0) >= 80 for issue in issues
    )
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
