"""Tests for `mmo report` CLI command."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main

try:
    import reportlab  # noqa: F401
except ImportError:
    reportlab = None

_MINIMAL_REPORT = {
    "schema_version": "0.1.0",
    "report_id": "report-cli-test",
    "project_id": "PROJECT.CLI.REPORT.TEST",
    "generated_at": "2000-01-01T00:00:00Z",
    "engine_version": "0.0.0",
    "ontology_version": "0.0.0",
    "session": {"stems": []},
    "issues": [
        {
            "issue_id": "ISSUE.CLIP.TRUE_PEAK",
            "severity": 90,
            "confidence": 0.95,
            "message": "True peak clip",
            "target": {"scope": "stem", "stem_id": "kick"},
            "evidence": [
                {
                    "evidence_id": "EVID.METER.TRUE_PEAK_DBTP",
                    "value": 0.3,
                    "unit_id": "UNIT.DBTP",
                }
            ],
        },
        {
            "issue_id": "ISSUE.FORMAT.LOSSY",
            "severity": 40,
            "confidence": 0.8,
            "message": "Lossy file detected",
            "evidence": [
                {
                    "evidence_id": "EVID.FILE.FORMAT",
                    "value": "mp3",
                }
            ],
        },
    ],
    "recommendations": [
        {
            "recommendation_id": "REC.CLIP.001",
            "issue_id": "ISSUE.CLIP.TRUE_PEAK",
            "action_id": "ACTION.UTILITY.GAIN",
            "risk": "low",
            "requires_approval": False,
            "scope": {"global": True},
            "params": [{"param_id": "PARAM.GAIN_DB", "value": -1.0, "unit_id": "UNIT.DB"}],
        }
    ],
}


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestCliReport(unittest.TestCase):
    def test_report_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            out_json = Path(tmp) / "out.json"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main(["report", "--report", str(report_path), "--json", str(out_json)])
            self.assertEqual(rc, 0)
            result = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(result["report_id"], "report-cli-test")

    def test_report_json_validates_against_schema(self) -> None:
        """The emitted JSON must round-trip as valid schema."""
        import jsonschema
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        schemas_dir = Path("schemas")
        registry = Registry()
        for candidate in sorted(schemas_dir.glob("*.schema.json")):
            schema = json.loads(candidate.read_text(encoding="utf-8"))
            resource = Resource.from_contents(schema, default_specification=DRAFT202012)
            registry = registry.with_resource(candidate.resolve().as_uri(), resource)
            schema_id = schema.get("$id")
            if isinstance(schema_id, str) and schema_id:
                registry = registry.with_resource(schema_id, resource)
        root_schema = json.loads((schemas_dir / "report.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(root_schema, registry=registry)

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            out_json = Path(tmp) / "out.json"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main(["report", "--report", str(report_path), "--json", str(out_json)])
            self.assertEqual(rc, 0)
            result = json.loads(out_json.read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(result))
        self.assertEqual(errors, [], errors)

    def test_report_recall_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            recall_path = Path(tmp) / "recall.csv"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main(["report", "--report", str(report_path), "--recall", str(recall_path)])
            self.assertEqual(rc, 0)
            rows = list(csv.reader(recall_path.read_text(encoding="utf-8").splitlines()))
        # Header
        self.assertEqual(rows[0][0], "rank")
        self.assertEqual(rows[0][1], "issue_id")
        # Rank 1 = highest severity
        self.assertEqual(rows[1][1], "ISSUE.CLIP.TRUE_PEAK")
        self.assertEqual(rows[2][1], "ISSUE.FORMAT.LOSSY")

    def test_report_recall_ranked_issues_have_action_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            recall_path = Path(tmp) / "recall.csv"
            _write_report(report_path, _MINIMAL_REPORT)
            main(["report", "--report", str(report_path), "--recall", str(recall_path)])
            rows = list(csv.reader(recall_path.read_text(encoding="utf-8").splitlines()))
        # ISSUE.CLIP.TRUE_PEAK has one recommendation — action_ids is col 8
        header = rows[0]
        action_ids_col = header.index("action_ids")
        self.assertIn("ACTION.UTILITY.GAIN", rows[1][action_ids_col])
        # ISSUE.FORMAT.LOSSY has no recommendations
        self.assertEqual(rows[2][action_ids_col], "")

    def test_report_recall_evidence_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            recall_path = Path(tmp) / "recall.csv"
            _write_report(report_path, _MINIMAL_REPORT)
            main(["report", "--report", str(report_path), "--recall", str(recall_path)])
            rows = list(csv.reader(recall_path.read_text(encoding="utf-8").splitlines()))
        # evidence_summary column contains the evidence_id
        header = rows[0]
        evidence_col = header.index("evidence_summary")
        self.assertIn("EVID.METER.TRUE_PEAK_DBTP", rows[1][evidence_col])

    def test_report_invalid_json_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "bad.json"
            report_path.write_text("not json", encoding="utf-8")
            rc = main(["report", "--report", str(report_path), "--json", str(Path(tmp) / "out.json")])
        self.assertNotEqual(rc, 0)

    def test_report_invalid_schema_returns_error(self) -> None:
        bad_report = {"schema_version": "0.1.0", "bad_field": True}
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "bad_schema.json"
            _write_report(report_path, bad_report)
            rc = main(["report", "--report", str(report_path), "--json", str(Path(tmp) / "out.json")])
        self.assertNotEqual(rc, 0)

    def test_report_pdf_output(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            pdf_path = Path(tmp) / "report.pdf"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main(["report", "--report", str(report_path), "--pdf", str(pdf_path)])
            self.assertEqual(rc, 0)
            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 0)

    def test_report_all_outputs_combined(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            out_json = Path(tmp) / "out.json"
            pdf_path = Path(tmp) / "report.pdf"
            recall_path = Path(tmp) / "recall.csv"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main([
                "report",
                "--report", str(report_path),
                "--json", str(out_json),
                "--pdf", str(pdf_path),
                "--recall", str(recall_path),
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(out_json.exists())
            self.assertTrue(pdf_path.exists())
            self.assertTrue(recall_path.exists())

    def test_report_no_outputs_is_validate_only(self) -> None:
        """mmo report with no output flags should validate and return 0."""
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            _write_report(report_path, _MINIMAL_REPORT)
            rc = main(["report", "--report", str(report_path)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
