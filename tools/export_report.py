from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Export recall CSV and PDF from a report JSON.")
    parser.add_argument("--report", required=True, help="Path to report JSON.")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Optional output CSV path.")
    parser.add_argument("--pdf", dest="pdf_path", default=None, help="Optional output PDF path.")
    args = parser.parse_args()

    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if args.csv_path:
        export_recall_csv(report, Path(args.csv_path))
    if args.pdf_path:
        export_report_pdf(report, Path(args.pdf_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
