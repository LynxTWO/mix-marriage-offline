import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.deliverables import (
    build_deliverables_from_outputs,
    build_deliverables_from_renderer_manifests,
    summarize_deliverables,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd


def _write_wav_16bit_mono(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.1,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(0.4 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _gain_trim_manifest(manifest: dict) -> dict | None:
    renderer_manifests = manifest.get("renderer_manifests")
    if not isinstance(renderer_manifests, list):
        return None
    return next(
        (
            item
            for item in renderer_manifests
            if isinstance(item, dict)
            and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
        ),
        None,
    )


def _base_report(stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.DELIVERABLES.TEST.001",
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": "lead",
                    "file_path": "lead.wav",
                    "channel_count": 1,
                }
            ],
        },
        "issues": [],
        "recommendations": [
            {
                "recommendation_id": "REC.DELIVERABLES.TEST.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "scope": {"stem_id": "lead"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -6.0}],
            }
        ],
    }


class TestDeliverablesGrouping(unittest.TestCase):
    def test_build_deliverables_from_outputs_groups_by_layout_and_channels(self) -> None:
        outputs = [
            {
                "output_id": "OUT.STEREO.WAV",
                "file_path": "render/stereo.wav",
                "format": "wav",
                "channel_count": 2,
                "metadata": {
                    "routing_applied": True,
                    "source_layout_id": "LAYOUT.1_0",
                    "target_layout_id": "LAYOUT.2_0",
                },
            },
            {
                "output_id": "OUT.STEREO.FLAC",
                "file_path": "render/stereo.flac",
                "format": "flac",
                "channel_count": 2,
                "metadata": {
                    "routing_applied": True,
                    "source_layout_id": "LAYOUT.1_0",
                    "target_layout_id": "LAYOUT.2_0",
                },
            },
            {
                "output_id": "OUT.SURROUND.WAV",
                "file_path": "render/surround.wav",
                "format": "wav",
                "channel_count": 6,
                "metadata": {
                    "routing_applied": True,
                    "source_layout_id": "LAYOUT.6_0",
                    "target_layout_id": "LAYOUT.5_1",
                },
            },
        ]

        deliverables = build_deliverables_from_outputs(outputs)

        self.assertEqual(
            [item.get("deliverable_id") for item in deliverables],
            ["DELIV.LAYOUT.2_0.2CH", "DELIV.LAYOUT.5_1.6CH"],
        )
        self.assertEqual(
            deliverables[0].get("deliverable_id"),
            "DELIV.LAYOUT.2_0.2CH",
        )
        self.assertEqual(deliverables[0].get("status"), "success")
        self.assertFalse(deliverables[0].get("is_valid_master"))
        self.assertEqual(deliverables[0].get("formats"), ["flac", "wav"])
        self.assertEqual(deliverables[0].get("output_ids"), ["OUT.STEREO.FLAC", "OUT.STEREO.WAV"])
        self.assertEqual(
            deliverables[1].get("deliverable_id"),
            "DELIV.LAYOUT.5_1.6CH",
        )
        self.assertEqual(deliverables[1].get("status"), "success")
        self.assertFalse(deliverables[1].get("is_valid_master"))
        self.assertEqual(deliverables[1].get("formats"), ["wav"])
        self.assertEqual(deliverables[1].get("output_ids"), ["OUT.SURROUND.WAV"])
        self.assertEqual(
            summarize_deliverables(deliverables),
            {
                "overall_status": "success",
                "deliverable_count": 2,
                "success_count": 2,
                "failed_count": 0,
                "partial_count": 0,
                "invalid_master_count": 0,
                "valid_master_count": 0,
                "mixed_outcomes": False,
                "result_bucket": "success_no_master",
                "top_failure_reason": None,
                "top_failure_status": None,
            },
        )

    def test_build_deliverables_from_outputs_separates_master_and_processed_stem_outputs(self) -> None:
        outputs = [
            {
                "output_id": "OUT.MASTER.WAV",
                "file_path": "render/master.wav",
                "format": "wav",
                "layout_id": "LAYOUT.2_0",
                "channel_count": 2,
                "metadata": {
                    "artifact_role": "master",
                    "target_layout_id": "LAYOUT.2_0",
                    "render_result": {
                        "artifact_role": "master",
                        "planned_stem_count": 1,
                        "decoded_stem_count": 1,
                        "prepared_stem_count": 1,
                        "skipped_stem_count": 0,
                        "rendered_frame_count": 4800,
                        "duration_seconds": 0.1,
                        "warning_codes": [],
                        "target_layout_id": "LAYOUT.2_0",
                    },
                },
            },
            {
                "output_id": "OUT.STEM.WAV",
                "file_path": "render/lead.wav",
                "format": "wav",
                "layout_id": "LAYOUT.2_0",
                "target_stem_id": "lead",
                "channel_count": 2,
                "metadata": {
                    "artifact_role": "processed_stem",
                    "target_layout_id": "LAYOUT.2_0",
                    "render_result": {
                        "artifact_role": "processed_stem",
                        "planned_stem_count": 1,
                        "decoded_stem_count": 1,
                        "prepared_stem_count": 1,
                        "skipped_stem_count": 0,
                        "rendered_frame_count": 4800,
                        "duration_seconds": 0.1,
                        "warning_codes": [],
                        "target_layout_id": "LAYOUT.2_0",
                    },
                },
            },
        ]

        deliverables = build_deliverables_from_outputs(outputs)

        self.assertEqual(
            [item.get("deliverable_id") for item in deliverables],
            [
                "DELIV.LAYOUT.2_0.2CH",
                "DELIV.STEM.lead.LAYOUT.2_0.2CH",
            ],
        )
        self.assertEqual(deliverables[0].get("artifact_role"), "master")
        self.assertEqual(deliverables[0].get("output_ids"), ["OUT.MASTER.WAV"])
        self.assertTrue(deliverables[0].get("is_valid_master"))
        self.assertEqual(deliverables[1].get("artifact_role"), "processed_stem")
        self.assertEqual(deliverables[1].get("target_stem_id"), "lead")
        self.assertEqual(deliverables[1].get("output_ids"), ["OUT.STEM.WAV"])
        self.assertFalse(deliverables[1].get("is_valid_master"))

    def test_renderer_manifests_produce_mixed_success_and_failure_summary(self) -> None:
        renderer_manifests = [
            {
                "renderer_id": "PLUGIN.RENDERER.SAFE",
                "outputs": [
                    {
                        "output_id": "OUT.STEREO.WAV",
                        "file_path": "render/stereo.wav",
                        "format": "wav",
                        "layout_id": "LAYOUT.2_0",
                        "channel_count": 2,
                        "metadata": {
                            "artifact_role": "master",
                            "render_result": {
                                "artifact_role": "master",
                                "planned_stem_count": 2,
                                "decoded_stem_count": 2,
                                "prepared_stem_count": 2,
                                "skipped_stem_count": 0,
                                "rendered_frame_count": 4800,
                                "duration_seconds": 0.1,
                                "failure_reason": None,
                                "warning_codes": [],
                                "target_layout_id": "LAYOUT.2_0",
                            },
                            "target_layout_id": "LAYOUT.2_0",
                        },
                    }
                ],
                "notes": "LAYOUT.5_1:missing_channel_order",
                "skipped": [],
            }
        ]

        deliverables = build_deliverables_from_renderer_manifests(renderer_manifests)

        self.assertEqual(
            [item.get("status") for item in deliverables],
            ["success", "failed"],
        )
        self.assertEqual(
            [item.get("target_layout_id") for item in deliverables],
            ["LAYOUT.2_0", "LAYOUT.5_1"],
        )
        self.assertEqual(
            summarize_deliverables(deliverables),
            {
                "overall_status": "partial",
                "deliverable_count": 2,
                "success_count": 1,
                "failed_count": 1,
                "partial_count": 0,
                "invalid_master_count": 0,
                "valid_master_count": 1,
                "mixed_outcomes": True,
                "result_bucket": "partial_success",
                "top_failure_reason": "RENDER_RESULT.MISSING_CHANNEL_ORDER",
                "top_failure_status": "failed",
            },
        )

    def test_render_manifest_and_ui_bundle_include_deliverables(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            render_manifest_path = temp_path / "render_manifest.json"
            render_out_dir = temp_path / "render"
            bundle_path = temp_path / "ui_bundle.json"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            report = _base_report(stems_dir)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            render_exit_code = main(
                [
                    "render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(render_manifest_path),
                    "--out-dir",
                    str(render_out_dir),
                    "--source-layout",
                    "LAYOUT.1_0",
                    "--target-layout",
                    "LAYOUT.2_0",
                    "--output-formats",
                    "wav,flac",
                ]
            )
            self.assertEqual(render_exit_code, 0)

            render_manifest = json.loads(render_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _gain_trim_manifest(render_manifest)
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return

            gain_output_ids = [
                output.get("output_id")
                for output in sorted(
                    outputs,
                    key=lambda item: (
                        item.get("format", ""),
                        item.get("file_path", ""),
                    ),
                )
                if isinstance(output, dict)
                and isinstance(output.get("output_id"), str)
                and output.get("output_id")
            ]
            renderer_manifests = render_manifest.get("renderer_manifests")
            self.assertIsInstance(renderer_manifests, list)
            if not isinstance(renderer_manifests, list):
                return
            master_output_ids = [
                output.get("output_id")
                for renderer_manifest in renderer_manifests
                if isinstance(renderer_manifest, dict)
                for output in renderer_manifest.get("outputs", [])
                if isinstance(output, dict)
                and output.get("layout_id") == "LAYOUT.2_0"
                and output.get("channel_count") == 2
                and isinstance(output.get("output_id"), str)
                and output.get("output_id")
                and isinstance(output.get("metadata"), dict)
                and output["metadata"].get("artifact_role") == "master"
            ]

            deliverables = render_manifest.get("deliverables")
            self.assertIsInstance(deliverables, list)
            if not isinstance(deliverables, list) or not deliverables:
                return

            deliverable = next(
                (
                    item
                    for item in deliverables
                    if isinstance(item, dict)
                    and item.get("artifact_role") == "master"
                    and item.get("target_layout_id") == "LAYOUT.2_0"
                    and item.get("channel_count") == 2
                ),
                None,
            )
            self.assertIsNotNone(deliverable)
            if not isinstance(deliverable, dict):
                return

            self.assertEqual(deliverable.get("target_layout_id"), "LAYOUT.2_0")
            self.assertEqual(deliverable.get("channel_count"), 2)
            self.assertEqual(deliverable.get("formats"), ["flac", "wav"])
            self.assertCountEqual(deliverable.get("output_ids"), master_output_ids)
            self.assertEqual(deliverable.get("status"), "success")
            self.assertTrue(deliverable.get("is_valid_master"))

            processed_stem_deliverable = next(
                (
                    item
                    for item in deliverables
                    if isinstance(item, dict)
                    and item.get("artifact_role") == "processed_stem"
                    and item.get("target_stem_id") == "lead"
                ),
                None,
            )
            self.assertIsNotNone(processed_stem_deliverable)
            if not isinstance(processed_stem_deliverable, dict):
                return
            self.assertCountEqual(processed_stem_deliverable.get("output_ids"), gain_output_ids)
            self.assertFalse(processed_stem_deliverable.get("is_valid_master"))
            self.assertEqual(processed_stem_deliverable.get("status"), "success")

            deliverables_summary = render_manifest.get("deliverables_summary")
            self.assertIsInstance(deliverables_summary, dict)
            if isinstance(deliverables_summary, dict):
                self.assertEqual(deliverables_summary.get("overall_status"), "partial")
                self.assertTrue(deliverables_summary.get("mixed_outcomes"))

            bundle_exit_code = main(
                [
                    "bundle",
                    "--report",
                    str(report_path),
                    "--render-manifest",
                    str(render_manifest_path),
                    "--out",
                    str(bundle_path),
                ]
            )
            self.assertEqual(bundle_exit_code, 0)

            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            dashboard = bundle.get("dashboard")
            self.assertIsInstance(dashboard, dict)
            if not isinstance(dashboard, dict):
                return
            dashboard_deliverables = dashboard.get("deliverables")
            self.assertIsInstance(dashboard_deliverables, list)
            if not isinstance(dashboard_deliverables, list) or not dashboard_deliverables:
                return

            dashboard_deliverable = next(
                (
                    item
                    for item in dashboard_deliverables
                    if isinstance(item, dict)
                    and item.get("deliverable_id") == deliverable.get("deliverable_id")
                ),
                None,
            )
            self.assertIsNotNone(dashboard_deliverable)
            if not isinstance(dashboard_deliverable, dict):
                return

            self.assertEqual(
                dashboard_deliverable.get("deliverable_id"),
                deliverable.get("deliverable_id"),
            )
            self.assertEqual(dashboard_deliverable.get("output_count"), len(deliverable.get("output_ids", [])))
            self.assertEqual(dashboard_deliverable.get("formats"), ["flac", "wav"])
            self.assertEqual(dashboard_deliverable.get("artifact_role"), "master")
            self.assertEqual(dashboard_deliverable.get("status"), "success")
            self.assertTrue(dashboard_deliverable.get("is_valid_master"))
            dashboard_processed_stem = next(
                (
                    item
                    for item in dashboard_deliverables
                    if isinstance(item, dict)
                    and item.get("artifact_role") == "processed_stem"
                    and item.get("target_stem_id") == "lead"
                ),
                None,
            )
            self.assertIsNotNone(dashboard_processed_stem)
            dashboard_summary = dashboard.get("deliverables_summary")
            self.assertIsInstance(dashboard_summary, dict)
            if isinstance(dashboard_summary, dict):
                self.assertEqual(dashboard_summary, deliverables_summary)


if __name__ == "__main__":
    unittest.main()
