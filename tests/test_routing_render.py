import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main


def _write_wav_16bit_mono(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.1,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(0.45 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
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
        "report_id": "REPORT.ROUTING.RENDER.001",
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
                "recommendation_id": "REC.RENDER.ROUTING.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "lead"},
                "params": [
                    {
                        "param_id": "PARAM.GAIN.DB",
                        "value": -6.0,
                    }
                ],
            }
        ],
    }


class TestRoutingRender(unittest.TestCase):
    def test_render_builds_routing_plan_from_cli_layout_flags(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            report = _base_report(stems_dir)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                    "--source-layout",
                    "LAYOUT.1_0",
                    "--target-layout",
                    "LAYOUT.2_0",
                ]
            )
            self.assertEqual(exit_code, 0)

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _gain_trim_manifest(manifest)
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return
            output = outputs[0]
            self.assertEqual(output.get("channel_count"), 2)
            metadata = output.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertTrue(metadata.get("routing_applied"))
            self.assertEqual(metadata.get("source_layout_id"), "LAYOUT.1_0")
            self.assertEqual(metadata.get("target_layout_id"), "LAYOUT.2_0")

    def test_render_applies_mono_to_stereo_routing_plan(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            report = _base_report(stems_dir)
            report["routing_plan"] = {
                "schema_version": "0.1.0",
                "source_layout_id": "LAYOUT.1_0",
                "target_layout_id": "LAYOUT.2_0",
                "routes": [
                    {
                        "stem_id": "lead",
                        "stem_channels": 1,
                        "target_channels": 2,
                        "mapping": [
                            {"src_ch": 0, "dst_ch": 0, "gain_db": -3.0},
                            {"src_ch": 0, "dst_ch": 1, "gain_db": -3.0},
                        ],
                        "notes": ["Mono routed equally to L/R at -3.0 dB each"],
                    }
                ],
            }
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(exit_code, 0)

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _gain_trim_manifest(manifest)
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return
            output = outputs[0]
            self.assertEqual(output.get("channel_count"), 2)

            output_path = out_dir / Path(output.get("file_path", ""))
            self.assertTrue(output_path.exists())
            with wave.open(str(output_path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 2)

            metadata = output.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertTrue(metadata.get("routing_applied"))
            self.assertEqual(metadata.get("source_layout_id"), "LAYOUT.1_0")
            self.assertEqual(metadata.get("target_layout_id"), "LAYOUT.2_0")
            self.assertEqual(
                metadata.get("routing_notes"),
                ["Mono routed equally to L/R at -3.0 dB each"],
            )

    def test_render_skips_when_route_has_no_mapping(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            report = _base_report(stems_dir)
            report["routing_plan"] = {
                "schema_version": "0.1.0",
                "source_layout_id": "LAYOUT.1_0",
                "target_layout_id": "LAYOUT.2_0",
                "routes": [
                    {
                        "stem_id": "lead",
                        "stem_channels": 1,
                        "target_channels": 2,
                        "mapping": [],
                        "notes": ["No safe default mapping"],
                    }
                ],
            }
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(exit_code, 0)

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _gain_trim_manifest(manifest)
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertEqual(outputs, [])
            skipped = gain_manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            if not isinstance(skipped, list):
                return

            tuples = {
                (
                    item.get("recommendation_id"),
                    item.get("action_id"),
                    item.get("reason"),
                )
                for item in skipped
                if isinstance(item, dict)
            }
            self.assertIn(
                (
                    "REC.RENDER.ROUTING.001",
                    "ACTION.UTILITY.GAIN",
                    "no_safe_routing",
                ),
                tuples,
            )


if __name__ == "__main__":
    unittest.main()
