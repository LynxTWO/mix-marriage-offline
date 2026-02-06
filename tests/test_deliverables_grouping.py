import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.deliverables import build_deliverables_from_outputs
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
                "target": {"scope": "stem", "stem_id": "lead"},
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
            deliverables[0],
            {
                "deliverable_id": "DELIV.LAYOUT.2_0.2CH",
                "label": "LAYOUT.2_0 deliverable",
                "target_layout_id": "LAYOUT.2_0",
                "channel_count": 2,
                "formats": ["flac", "wav"],
                "output_ids": ["OUT.STEREO.FLAC", "OUT.STEREO.WAV"],
            },
        )
        self.assertEqual(
            deliverables[1],
            {
                "deliverable_id": "DELIV.LAYOUT.5_1.6CH",
                "label": "LAYOUT.5_1 deliverable",
                "target_layout_id": "LAYOUT.5_1",
                "channel_count": 6,
                "formats": ["wav"],
                "output_ids": ["OUT.SURROUND.WAV"],
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

            expected_output_ids = [
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

            deliverables = render_manifest.get("deliverables")
            self.assertIsInstance(deliverables, list)
            self.assertEqual(len(deliverables), 1)
            if not isinstance(deliverables, list) or not deliverables:
                return

            deliverable = deliverables[0]
            self.assertEqual(deliverable.get("target_layout_id"), "LAYOUT.2_0")
            self.assertEqual(deliverable.get("channel_count"), 2)
            self.assertEqual(deliverable.get("formats"), ["flac", "wav"])
            self.assertEqual(deliverable.get("output_ids"), expected_output_ids)

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
            self.assertEqual(len(dashboard_deliverables), 1)
            if not isinstance(dashboard_deliverables, list) or not dashboard_deliverables:
                return

            dashboard_deliverable = dashboard_deliverables[0]
            self.assertEqual(
                dashboard_deliverable.get("deliverable_id"),
                deliverable.get("deliverable_id"),
            )
            self.assertEqual(dashboard_deliverable.get("output_count"), len(expected_output_ids))
            self.assertEqual(dashboard_deliverable.get("formats"), ["flac", "wav"])


if __name__ == "__main__":
    unittest.main()
