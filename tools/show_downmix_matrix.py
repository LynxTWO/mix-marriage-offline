"""Resolve and display downmix matrices from the ontology."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.dsp.downmix import (  # noqa: E402
    render_matrix,
    resolve_downmix_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve and display downmix matrices.")
    parser.add_argument("--source", required=True, help="Source layout ID.")
    parser.add_argument("--target", required=True, help="Target layout ID.")
    parser.add_argument("--policy", default=None, help="Optional policy ID override.")
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format for the resolved matrix.",
    )
    parser.add_argument("--out", default=None, help="Optional output path; defaults to stdout.")
    args = parser.parse_args()

    layouts_path = ROOT_DIR / "ontology" / "layouts.yaml"
    registry_path = ROOT_DIR / "ontology" / "policies" / "downmix.yaml"

    try:
        matrix = resolve_downmix_matrix(
            repo_root=ROOT_DIR,
            source_layout_id=args.source,
            target_layout_id=args.target,
            policy_id=args.policy,
            layouts_path=layouts_path,
            registry_path=registry_path,
        )
        output = render_matrix(matrix, output_format=args.format)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
