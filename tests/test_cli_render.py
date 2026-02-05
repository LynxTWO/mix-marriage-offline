import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.dsp.io import sha256_file


def _write_wav_16bit(path: Path, *, sample_rate_hz: int = 48000, duration_s: float = 0.1) -> None:
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


class TestCliRender(unittest.TestCase):
    def test_render_writes_output_and_manifest_hash(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "render_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"

            _write_wav_16bit(source_path)

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.CLI.RENDER.GAIN",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "kick",
                            "file_path": "drums/kick.wav",
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.001",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "target": {"scope": "stem", "stem_id": "kick"},
                        "params": [
                            {
                                "param_id": "PARAM.GAIN.DB",
                                "value": -6.0,
                            }
                        ],
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
            self.assertTrue(out_manifest_path.exists())

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(manifest)

            gain_manifest = next(
                (
                    item
                    for item in manifest.get("renderer_manifests", [])
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
                ),
                None,
            )
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            output = outputs[0]
            output_file = out_dir / Path(output["file_path"])
            self.assertTrue(output_file.exists())
            self.assertEqual(output["sha256"], sha256_file(output_file))
            self.assertEqual(output["target_stem_id"], "kick")
            self.assertEqual(output["format"], "wav")
            self.assertEqual(output["sample_rate_hz"], 48000)
            self.assertEqual(output["bit_depth"], 16)
            self.assertEqual(output["channel_count"], 1)
            self.assertEqual(
                output["metadata"].get("contributing_recommendation_ids"),
                ["REC.RENDER.GAIN.001"],
            )

    def test_render_without_out_dir_adds_plugin_skip_and_keeps_gate_skip(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "render_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"

            _write_wav_16bit(source_path)

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.CLI.RENDER.MISSING.OUT.DIR",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "kick",
                            "file_path": "kick.wav",
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.ELIGIBLE",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "target": {"scope": "stem", "stem_id": "kick"},
                        "params": [
                            {
                                "param_id": "PARAM.GAIN.DB",
                                "value": -6.0,
                            }
                        ],
                    },
                    {
                        "recommendation_id": "REC.RENDER.GAIN.BLOCKED",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "target": {"scope": "stem", "stem_id": "kick"},
                        "params": [
                            {
                                "param_id": "PARAM.GAIN.DB",
                                "value": -20.0,
                            }
                        ],
                    },
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
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_manifest_path.exists())

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(manifest)

            gain_manifest = next(
                (
                    item
                    for item in manifest.get("renderer_manifests", [])
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
                ),
                None,
            )
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            skipped = gain_manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            if not isinstance(skipped, list):
                return

            skipped_lookup = {
                (
                    item.get("recommendation_id"),
                    item.get("action_id"),
                    item.get("reason"),
                ): item
                for item in skipped
                if isinstance(item, dict)
            }
            self.assertIn(
                (
                    "REC.RENDER.GAIN.ELIGIBLE",
                    "ACTION.UTILITY.GAIN",
                    "missing_output_dir",
                ),
                skipped_lookup,
            )
            blocked_key = (
                "REC.RENDER.GAIN.BLOCKED",
                "ACTION.UTILITY.GAIN",
                "blocked_by_gates",
            )
            self.assertIn(blocked_key, skipped_lookup)
            self.assertIn(
                "GATE.MAX_GAIN_DB",
                skipped_lookup[blocked_key].get("gate_summary", ""),
            )


if __name__ == "__main__":
    unittest.main()
