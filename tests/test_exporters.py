import csv
import json
import tempfile
import unittest
from pathlib import Path

from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf
from mmo.exporters import pdf_report
from mmo.exporters.pdf_utils import render_maybe_json

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
            export_recall_csv(report, out_path, include_gates=True)
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

    def test_export_recall_csv_without_gates(self) -> None:
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=False)
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
            ],
        )

    def test_export_recall_csv_gate_summary_includes_gate_id(self) -> None:
        report = {
            "recommendations": [
                {
                    "recommendation_id": "REC.GATE.TEST",
                    "issue_id": "ISSUE.TEST",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {},
                    "params": [],
                    "gate_results": [
                        {
                            "gate_id": "GATE.MAX_GAIN_DB",
                            "context": "render",
                            "outcome": "reject",
                            "reason_id": "REASON.GAIN_TOO_LARGE",
                            "details": {},
                        }
                    ],
                    "eligible_auto_apply": False,
                    "eligible_render": False,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=True)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertIn("gate_summary", rows[0])
        self.assertIn("render:reject(GATE.MAX_GAIN_DB|REASON.GAIN_TOO_LARGE)", rows[1][-1])

    def test_export_report_pdf_exists(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_export_report_pdf_truncation(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        report["session"] = {
            "stems": [
                {
                    "stem_id": "stem-long",
                    "measurements": [
                        {
                            "evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG",
                            "value": "x" * 1000,
                            "unit_id": "UNIT.TEXT",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path, truncate_values=100)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_export_report_pdf_no_measurements(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path, include_measurements=False)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_downmix_qa_summary_fields_from_log(self) -> None:
        downmix_qa = {
            "policy_id": "POLICY.DOWNMIX.TEST",
            "matrix_id": "MATRIX.TEST",
            "log": json.dumps(
                {
                    "source_layout_id": "LAYOUT.5_1",
                    "target_layout_id": "LAYOUT.2_0",
                    "seconds_compared": 12.5,
                    "max_seconds": 120.0,
                }
            ),
        }
        fields = pdf_report._downmix_qa_summary_fields(downmix_qa)
        field_map = {label: value for label, value in fields}
        self.assertEqual(field_map.get("policy_id"), "POLICY.DOWNMIX.TEST")
        self.assertEqual(field_map.get("matrix_id"), "MATRIX.TEST")
        self.assertEqual(field_map.get("source_layout_id"), "LAYOUT.5_1")
        self.assertEqual(field_map.get("target_layout_id"), "LAYOUT.2_0")
        self.assertEqual(field_map.get("seconds_compared"), 12.5)
        self.assertEqual(field_map.get("max_seconds"), 120.0)

    def test_downmix_qa_thresholds_line_from_gates(self) -> None:
        line = pdf_report._downmix_qa_thresholds_line()
        self.assertIsNotNone(line)
        if line is None:
            return
        self.assertIn("Thresholds:", line)
        self.assertIn("LUFS Δ warn 2.0 / fail 4.0", line)
        self.assertIn("True Peak Δ warn 1.0 / fail 2.0", line)
        self.assertIn("Correlation Δ warn 0.15 / fail 0.30", line)

    def test_downmix_qa_provenance_line(self) -> None:
        line = pdf_report._downmix_qa_provenance_line()
        self.assertIn("Provenance:", line)
        self.assertIn("downmix.yaml", line)

    def test_render_maybe_json_truncates_string_values(self) -> None:
        payload = {"keep": "ok", "blob": "x" * 50}
        rendered = render_maybe_json(json.dumps(payload), limit=20, pretty=True)
        self.assertIn("...(truncated)", rendered)
        self.assertIn('"keep": "ok"', rendered)


if __name__ == "__main__":
    unittest.main()
