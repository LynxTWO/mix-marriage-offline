from __future__ import annotations

import unittest

from mmo.core.render_clarity import (
    build_deliverable_summary_rows,
    build_result_summary,
)
from mmo.core.validators import validate_session


class TestRenderClarity(unittest.TestCase):
    def test_duration_mismatch_issue_gets_title_message_and_remedy(self) -> None:
        issues = validate_session(
            {
                "stems": [
                    {
                        "stem_id": "STEM.A",
                        "file_path": "stems/a.wav",
                        "duration_s": 1.0,
                    },
                    {
                        "stem_id": "STEM.B",
                        "file_path": "stems/b.wav",
                        "duration_s": 1.25,
                    },
                ]
            }
        )

        duration_issue = next(
            issue
            for issue in issues
            if issue.get("issue_id") == "ISSUE.VALIDATION.DURATION_MISMATCH"
        )
        self.assertEqual(duration_issue.get("title"), "Stem durations do not match")
        self.assertIn("different length", str(duration_issue.get("message")))
        self.assertIn("rerun Analyze", str(duration_issue.get("remedy")))

    def test_deliverable_summary_rows_use_frame_derived_duration(self) -> None:
        rows = build_deliverable_summary_rows(
            renderer_manifests=[
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        {
                            "output_id": "OUT.001",
                            "file_path": "render/2_0/mix.wav",
                            "layout_id": "LAYOUT.2_0",
                            "channel_count": 2,
                            "sample_rate_hz": 48000,
                            "format": "wav",
                        }
                    ],
                    "skipped": [],
                }
            ],
            deliverables=[
                {
                    "deliverable_id": "DELIV.LAYOUT.2_0.2CH",
                    "artifact_role": "master",
                    "target_layout_id": "LAYOUT.2_0",
                    "output_ids": ["OUT.001"],
                    "status": "success",
                    "is_valid_master": True,
                    "rendered_frame_count": 4800,
                    "duration_seconds": 9.9,
                    "failure_reason": None,
                    "warning_codes": [],
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("duration_seconds"), 0.1)
        self.assertEqual(rows[0].get("rendered_frame_count"), 4800)
        self.assertEqual(rows[0].get("sample_rate_hz"), 48000)

    def test_result_summary_explains_zero_decoded_failure(self) -> None:
        result_summary = build_result_summary(
            deliverables_summary={
                "overall_status": "failed",
                "deliverable_count": 1,
                "success_count": 0,
                "failed_count": 1,
                "partial_count": 0,
                "invalid_master_count": 0,
                "valid_master_count": 0,
                "mixed_outcomes": False,
                "result_bucket": "full_failure",
                "top_failure_reason": "RENDER_RESULT.NO_DECODABLE_STEMS",
                "top_failure_status": "failed",
            },
            deliverable_summary_rows=[
                {
                    "deliverable_id": "DELIV.LAYOUT.2_0.2CH",
                    "output_id": "OUT.FAIL.001",
                    "layout": "LAYOUT.2_0",
                    "file_path": "render/failed/master.wav",
                    "channel_count": 2,
                    "sample_rate_hz": 48000,
                    "rendered_frame_count": 0,
                    "duration_seconds": 0.0,
                    "status": "failed",
                    "validity": "full_failure",
                    "failure_reason": "RENDER_RESULT.NO_DECODABLE_STEMS",
                }
            ],
        )

        self.assertEqual(
            result_summary.get("title"),
            "Render failed: no decodable stems",
        )
        self.assertIn(
            "none of the selected stems decoded into audio",
            str(result_summary.get("message")),
        )
        self.assertIn("stem diagnostics", str(result_summary.get("remedy")))
