import json
import unittest
from pathlib import Path

from mmo.core.report_builders import (
    build_minimal_report_for_downmix_qa,
    enrich_blocked_downmix_render_diagnostics,
)


class TestBlockedRenderDiagnostics(unittest.TestCase):
    def _build_corr_fail_report(self) -> dict:
        repo_root = Path(__file__).resolve().parents[1]
        qa_payload = {
            "downmix_qa": {
                "src_path": "src.flac",
                "ref_path": "ref.wav",
                "policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN",
                "matrix_id": "MATRIX.STANDARD.5_1_TO_2_0",
                "sample_rate_hz": 48000,
                "log": json.dumps({"target_layout_id": "LAYOUT.2_0"}),
                "measurements": [
                    {
                        "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                        "value": 0.1,
                        "unit_id": "UNIT.LUFS",
                    },
                    {
                        "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                        "value": 0.2,
                        "unit_id": "UNIT.DBTP",
                    },
                    {
                        "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                        "value": 0.35,
                        "unit_id": "UNIT.CORRELATION",
                    },
                ],
                "issues": [
                    {
                        "issue_id": "ISSUE.DOWNMIX.QA.CORRELATION_MISMATCH",
                        "severity": 60,
                        "confidence": 1.0,
                        "message": "Correlation delta exceeded tolerance.",
                        "target": {"scope": "session"},
                        "evidence": [
                            {
                                "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                                "value": 0.35,
                                "unit_id": "UNIT.CORRELATION",
                            }
                        ],
                    }
                ],
            }
        }
        return build_minimal_report_for_downmix_qa(
            repo_root=repo_root,
            qa_payload=qa_payload,
        )

    def test_corr_fail_adds_targeted_diagnostics_and_is_idempotent(self) -> None:
        report = self._build_corr_fail_report()
        recommendations = report.get("recommendations", [])
        self.assertIsInstance(recommendations, list)

        render_recs = [
            rec
            for rec in recommendations
            if isinstance(rec, dict) and rec.get("action_id") == "ACTION.DOWNMIX.RENDER"
        ]
        self.assertEqual(len(render_recs), 1)
        render_rec = render_recs[0]
        self.assertFalse(render_rec.get("eligible_render", True))
        self.assertTrue(
            any(
                isinstance(result, dict)
                and result.get("gate_id") == "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"
                and result.get("context") == "render"
                and result.get("outcome") == "reject"
                for result in render_rec.get("gate_results", [])
            )
        )

        recommendation_ids = [
            rec.get("recommendation_id")
            for rec in recommendations
            if isinstance(rec, dict)
        ]
        self.assertIn("REC.DIAGNOSTIC.REVIEW_POLICY_MATRIX.001", recommendation_ids)
        self.assertIn("REC.DIAGNOSTIC.CHECK_PHASE_CORRELATION.001", recommendation_ids)
        self.assertNotIn("REC.DIAGNOSTIC.CHECK_REFERENCE_LEVELS.001", recommendation_ids)

        baseline_count = len(recommendation_ids)
        enrich_blocked_downmix_render_diagnostics(report)
        enrich_blocked_downmix_render_diagnostics(report)
        recommendations_after = [
            rec
            for rec in report.get("recommendations", [])
            if isinstance(rec, dict)
        ]
        self.assertEqual(len(recommendations_after), baseline_count)

        recommendation_ids_after = [
            rec.get("recommendation_id")
            for rec in recommendations_after
            if isinstance(rec.get("recommendation_id"), str)
        ]
        self.assertLess(
            recommendation_ids_after.index("REC.DIAGNOSTIC.REVIEW_POLICY_MATRIX.001"),
            recommendation_ids_after.index("REC.DIAGNOSTIC.CHECK_PHASE_CORRELATION.001"),
        )


if __name__ == "__main__":
    unittest.main()
