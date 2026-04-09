"""Tests for `mmo review` — pending-approval recommendation summary."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _minimal_report(*, recommendations: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": "RPT.REVIEW.TEST",
        "project_id": "PROJECT.REVIEW.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": recommendations,
    }


def _rec(
    rec_id: str,
    *,
    action_id: str = "ACTION.DYN.LIMITER",
    risk: str = "high",
    requires_approval: bool = True,
    stem_id: str = "01_kick",
    issue_id: str | None = "ISSUE.SAFETY.TRUEPEAK_OVER_CEILING",
) -> dict:
    r: dict = {
        "recommendation_id": rec_id,
        "action_id": action_id,
        "risk": risk,
        "requires_approval": requires_approval,
        "scope": {"stem_id": stem_id},
        "params": [],
    }
    if issue_id:
        r["issue_id"] = issue_id
    return r


class TestMmoReview(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        import io
        from contextlib import redirect_stdout, redirect_stderr

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    # ── basic text output ─────────────────────────────────────────

    def test_no_pending_approvals_prints_clear_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.001", requires_approval=False, risk="low"),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("No pending approvals", out)

    def test_one_pending_shows_count_and_rec_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.ALPHA", requires_approval=True, risk="high", stem_id="02_snare"),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("1 recommendation", out)
        self.assertIn("REC.ALPHA", out)
        self.assertIn("02_snare", out)

    def test_multiple_pending_shows_count(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.001", requires_approval=True),
                _rec("REC.002", requires_approval=True, stem_id="03_bass"),
                _rec("REC.003", requires_approval=False),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("2 recommendations", out)
        self.assertIn("REC.001", out)
        self.assertIn("REC.002", out)
        self.assertNotIn("REC.003", out)

    def test_approve_rec_flags_appear_in_footer(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.X1", requires_approval=True),
                _rec("REC.X2", requires_approval=True, stem_id="03_bass"),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("--approve-rec REC.X1", out)
        self.assertIn("--approve-rec REC.X2", out)
        self.assertIn("mmo safe-render", out)

    def test_issue_id_shown_in_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.ISSUE", requires_approval=True, issue_id="ISSUE.SAFETY.TRUEPEAK_OVER_CEILING"),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", out)

    def test_risk_column_shown(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.RISK", requires_approval=True, risk="high"),
            ]))
            code, out, _ = self._run(["review", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("high", out)

    # ── JSON format ───────────────────────────────────────────────

    def test_json_format_returns_pending_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.JSON.1", requires_approval=True),
                _rec("REC.JSON.2", requires_approval=False),
            ]))
            code, out, _ = self._run(["review", str(path), "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        ids = [r["recommendation_id"] for r in payload["pending_approvals"]]
        self.assertIn("REC.JSON.1", ids)
        self.assertNotIn("REC.JSON.2", ids)

    def test_json_format_no_pending_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[]))
            code, out, _ = self._run(["review", str(path), "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["pending_approvals"], [])

    # ── --risk filter ─────────────────────────────────────────────

    def test_risk_filter_high_excludes_medium(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.MED", requires_approval=True, risk="medium"),
                _rec("REC.HIGH", requires_approval=True, risk="high"),
            ]))
            code, out, _ = self._run(["review", str(path), "--risk", "high"])
        self.assertEqual(code, 0)
        self.assertIn("REC.HIGH", out)
        self.assertNotIn("REC.MED", out)

    def test_risk_filter_medium_excludes_high(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.MED", requires_approval=True, risk="medium"),
                _rec("REC.HIGH", requires_approval=True, risk="high"),
            ]))
            code, out, _ = self._run(["review", str(path), "--risk", "medium"])
        self.assertEqual(code, 0)
        self.assertIn("REC.MED", out)
        self.assertNotIn("REC.HIGH", out)

    def test_risk_filter_no_match_shows_no_pending(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.HIGH", requires_approval=True, risk="high"),
            ]))
            code, out, _ = self._run(["review", str(path), "--risk", "low"])
        self.assertEqual(code, 0)
        self.assertIn("No pending approvals", out)

    # ── directory input ───────────────────────────────────────────

    def test_accepts_directory_with_report_json_inside(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=[
                _rec("REC.DIR.1", requires_approval=True),
            ]))
            code, out, _ = self._run(["review", d])
        self.assertEqual(code, 0)
        self.assertIn("REC.DIR.1", out)

    # ── error cases ───────────────────────────────────────────────

    def test_missing_file_exits_nonzero(self):
        code, _, err = self._run(["review", "/nonexistent/report.json"])
        self.assertNotEqual(code, 0)

    def test_non_json_file_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            path.write_text("not json", encoding="utf-8")
            code, _, err = self._run(["review", str(path)])
        self.assertNotEqual(code, 0)

    # ── output is stable ─────────────────────────────────────────

    def test_text_output_is_deterministic(self):
        """Same report always produces identical text output."""
        recs = [
            _rec("REC.STABLE.1", requires_approval=True, stem_id="01_kick"),
            _rec("REC.STABLE.2", requires_approval=True, stem_id="02_snare"),
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            _write_json(path, _minimal_report(recommendations=recs))
            _, out1, _ = self._run(["review", str(path)])
            _, out2, _ = self._run(["review", str(path)])
        self.assertEqual(out1, out2)


if __name__ == "__main__":
    unittest.main()
