from __future__ import annotations

import unittest

from mmo.core.deliverables import (
    build_deliverables_from_renderer_manifests,
    summarize_deliverables,
)


def _master_output(
    *,
    output_id: str,
    layout_id: str,
    channel_count: int,
    planned_stem_count: int,
    decoded_stem_count: int,
    prepared_stem_count: int,
    skipped_stem_count: int,
    rendered_frame_count: int,
    duration_seconds: float,
    warning_codes: list[str] | None = None,
    failure_reason: str | None = None,
) -> dict:
    return {
        "output_id": output_id,
        "file_path": f"render/{output_id.lower()}.wav",
        "format": "wav",
        "layout_id": layout_id,
        "channel_count": channel_count,
        "metadata": {
            "artifact_role": "master",
            "target_layout_id": layout_id,
            "render_result": {
                "artifact_role": "master",
                "planned_stem_count": planned_stem_count,
                "decoded_stem_count": decoded_stem_count,
                "prepared_stem_count": prepared_stem_count,
                "skipped_stem_count": skipped_stem_count,
                "rendered_frame_count": rendered_frame_count,
                "duration_seconds": duration_seconds,
                "failure_reason": failure_reason,
                "warning_codes": list(warning_codes or []),
                "target_layout_id": layout_id,
            },
        },
    }


class TestRenderResultContract(unittest.TestCase):
    def test_full_success_across_layouts(self) -> None:
        deliverables = build_deliverables_from_renderer_manifests(
            [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        _master_output(
                            output_id="OUT.STEREO",
                            layout_id="LAYOUT.2_0",
                            channel_count=2,
                            planned_stem_count=3,
                            decoded_stem_count=3,
                            prepared_stem_count=3,
                            skipped_stem_count=0,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                        ),
                        _master_output(
                            output_id="OUT.SURROUND",
                            layout_id="LAYOUT.5_1",
                            channel_count=6,
                            planned_stem_count=3,
                            decoded_stem_count=3,
                            prepared_stem_count=3,
                            skipped_stem_count=0,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                        ),
                    ],
                    "skipped": [],
                }
            ]
        )

        self.assertEqual([item.get("status") for item in deliverables], ["success", "success"])
        self.assertEqual(
            summarize_deliverables(deliverables),
            {
                "overall_status": "success",
                "deliverable_count": 2,
                "success_count": 2,
                "failed_count": 0,
                "partial_count": 0,
                "invalid_master_count": 0,
                "valid_master_count": 2,
                "mixed_outcomes": False,
                "result_bucket": "valid_master",
                "top_failure_reason": None,
                "top_failure_status": None,
            },
        )

    def test_all_layouts_fail_decode(self) -> None:
        deliverables = build_deliverables_from_renderer_manifests(
            [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        _master_output(
                            output_id="OUT.STEREO",
                            layout_id="LAYOUT.2_0",
                            channel_count=2,
                            planned_stem_count=2,
                            decoded_stem_count=0,
                            prepared_stem_count=0,
                            skipped_stem_count=2,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                            warning_codes=["RENDER_RESULT.NO_DECODABLE_STEMS"],
                        ),
                        _master_output(
                            output_id="OUT.SURROUND",
                            layout_id="LAYOUT.5_1",
                            channel_count=6,
                            planned_stem_count=2,
                            decoded_stem_count=0,
                            prepared_stem_count=0,
                            skipped_stem_count=2,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                            warning_codes=["RENDER_RESULT.NO_DECODABLE_STEMS"],
                        ),
                    ],
                    "skipped": [],
                }
            ]
        )

        self.assertEqual(
            [item.get("status") for item in deliverables],
            ["failed", "failed"],
        )
        self.assertEqual(
            summarize_deliverables(deliverables),
            {
                "overall_status": "failed",
                "deliverable_count": 2,
                "success_count": 0,
                "failed_count": 2,
                "partial_count": 0,
                "invalid_master_count": 0,
                "valid_master_count": 0,
                "mixed_outcomes": False,
                "result_bucket": "full_failure",
                "top_failure_reason": "RENDER_RESULT.NO_DECODABLE_STEMS",
                "top_failure_status": "failed",
            },
        )

    def test_silent_master_written_to_disk_is_marked_invalid(self) -> None:
        deliverables = build_deliverables_from_renderer_manifests(
            [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        _master_output(
                            output_id="OUT.STEREO",
                            layout_id="LAYOUT.2_0",
                            channel_count=2,
                            planned_stem_count=2,
                            decoded_stem_count=2,
                            prepared_stem_count=2,
                            skipped_stem_count=0,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                            warning_codes=["RENDER_RESULT.SILENT_OUTPUT"],
                            failure_reason="RENDER_RESULT.SILENT_OUTPUT",
                        )
                    ],
                    "skipped": [],
                }
            ]
        )

        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].get("status"), "invalid_master")
        self.assertFalse(deliverables[0].get("is_valid_master"))
        self.assertEqual(
            deliverables[0].get("failure_reason"),
            "RENDER_RESULT.SILENT_OUTPUT",
        )

    def test_invalid_master_written_to_disk_is_marked_invalid(self) -> None:
        deliverables = build_deliverables_from_renderer_manifests(
            [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        _master_output(
                            output_id="OUT.SURROUND",
                            layout_id="LAYOUT.5_1",
                            channel_count=6,
                            planned_stem_count=4,
                            decoded_stem_count=4,
                            prepared_stem_count=4,
                            skipped_stem_count=0,
                            rendered_frame_count=4800,
                            duration_seconds=0.1,
                            warning_codes=["RENDER_RESULT.DOWNMIX_QA_FAILED"],
                            failure_reason="RENDER_RESULT.DOWNMIX_QA_FAILED",
                        )
                    ],
                    "skipped": [],
                }
            ]
        )

        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].get("status"), "invalid_master")
        self.assertFalse(deliverables[0].get("is_valid_master"))
        self.assertEqual(
            deliverables[0].get("failure_reason"),
            "RENDER_RESULT.DOWNMIX_QA_FAILED",
        )
        self.assertEqual(
            summarize_deliverables(deliverables),
            {
                "overall_status": "invalid_master",
                "deliverable_count": 1,
                "success_count": 0,
                "failed_count": 0,
                "partial_count": 0,
                "invalid_master_count": 1,
                "valid_master_count": 0,
                "mixed_outcomes": False,
                "result_bucket": "diagnostics_only",
                "top_failure_reason": "RENDER_RESULT.DOWNMIX_QA_FAILED",
                "top_failure_status": "invalid_master",
            },
        )
