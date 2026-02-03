import csv
import json
import tempfile
import unittest
from pathlib import Path

from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf

try:
    import reportlab  # noqa: F401
except ImportError:
    reportlab = None


class TestExporters(unittest.TestCase):
    def _load_report(self) -> dict:
        path = Path("fixtures/export/report_small.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_export_recall_csv_ordering(self) -> None:
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertEqual(
            rows[0],
            [
                "recommendation_id",
                "issue_id",
                "action_id",
                "risk",
                "requires_approval",
                "target",
                "params",
                "notes",
                "eligible_auto_apply",
                "eligible_render",
                "gate_summary",
            ],
        )
        self.assertEqual(rows[1][0], "REC.001")
        self.assertEqual(rows[2][0], "REC.002")
        self.assertEqual(rows[1][-3:], ["", "", ""])
        self.assertEqual(rows[2][-3:], ["", "", ""])

    def test_export_report_pdf_exists(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
