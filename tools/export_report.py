from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Export recall CSV and PDF from a report JSON.")
    parser.add_argument("--report", required=True, help="Path to report JSON.")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Optional output CSV path.")
    parser.add_argument("--pdf", dest="pdf_path", default=None, help="Optional output PDF path.")
    parser.add_argument(
        "--no-measurements",
        action="store_true",
        help="Omit Measurements section from PDF output.",
    )
    parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Omit gate fields/sections from exports.",
    )
    parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF cell values to this length.",
    )
    args = parser.parse_args()

    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if args.csv_path:
        export_recall_csv(report, Path(args.csv_path), include_gates=not args.no_gates)
    if args.pdf_path:
        try:
            export_report_pdf(
                report,
                Path(args.pdf_path),
                include_measurements=not args.no_measurements,
                include_gates=not args.no_gates,
                truncate_values=args.truncate_values,
            )
        except RuntimeError:
            print(
                "PDF export requires reportlab. Install extras: pip install .[pdf]",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
