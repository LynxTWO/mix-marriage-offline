import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import sha256_file


def _write_wav_16bit(path: Path, *, sample_rate_hz: int = 48000, duration_s: float = 0.25) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(0.45 * 32767.0 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _py_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    src_root = str(repo_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"
    return env


def _render_manifest(report_path: Path, out_manifest_path: Path, out_dir: Path, repo_root: Path) -> dict:
    subprocess.run(
        [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            "-m",
            "mmo",
            "render",
            "--report",
            os.fspath(report_path),
            "--plugins",
            os.fspath(repo_root / "plugins"),
            "--out-manifest",
            os.fspath(out_manifest_path),
            "--out-dir",
            os.fspath(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_py_env(repo_root),
    )
    return json.loads(out_manifest_path.read_text(encoding="utf-8"))


def _gain_trim_manifest(manifest: dict) -> dict:
    renderer_manifests = manifest.get("renderer_manifests", [])
    if not isinstance(renderer_manifests, list):
        return {}
    for item in renderer_manifests:
        if (
            isinstance(item, dict)
            and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
        ):
            return item
    return {}


class TestGainTrimRendererMultiformat(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if resolve_ffmpeg_cmd() is None:
            raise unittest.SkipTest("ffmpeg not available")

    def test_render_flac_input_outputs_wav_with_metadata(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "render_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        self.assertIsNotNone(ffmpeg_cmd)
        if ffmpeg_cmd is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_wav = stems_dir / "tone.wav"
            source_flac = stems_dir / "tone.flac"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"

            _write_wav_16bit(source_wav)
            subprocess.run(
                list(ffmpeg_cmd)
                + [
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    os.fspath(source_wav),
                    "-c:a",
                    "flac",
                    os.fspath(source_flac),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.RENDER.GAIN_TRIM.FLAC.001",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "tone",
                            "file_path": "tone.flac",
                            "channel_count": 1,
                            "sample_rate_hz": 48000,
                            "bits_per_sample": 16,
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.TRIM.FLAC.001",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "eligible_render": True,
                        "target": {"scope": "stem", "stem_id": "tone"},
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

            manifest = _render_manifest(report_path, out_manifest_path, out_dir, repo_root)
            jsonschema.Draft202012Validator(schema).validate(manifest)

            gain_manifest = _gain_trim_manifest(manifest)
            outputs = gain_manifest.get("outputs", [])
            self.assertEqual(len(outputs), 1)
            output = outputs[0]

            output_path = out_dir / Path(output["file_path"])
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.suffix.lower(), ".wav")
            self.assertEqual(output["sha256"], sha256_file(output_path))
            self.assertEqual(output["sample_rate_hz"], 48000)
            self.assertEqual(output["channel_count"], 1)
            self.assertEqual(output["bit_depth"], 16)
            self.assertTrue(str(output["output_id"]).startswith("OUTPUT.GAIN_TRIM.tone."))
            metadata = output.get("metadata")
            self.assertIsInstance(metadata, dict)
            if isinstance(metadata, dict):
                self.assertEqual(metadata.get("applied_gain_db"), -6.0)
                self.assertEqual(
                    metadata.get("contributing_recommendation_ids"),
                    ["REC.RENDER.GAIN.TRIM.FLAC.001"],
                )

    def test_render_skips_lossy_mp3_input(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        self.assertIsNotNone(ffmpeg_cmd)
        if ffmpeg_cmd is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_mp3 = stems_dir / "tone.mp3"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            stems_dir.mkdir(parents=True, exist_ok=True)
            source_mp3.write_bytes(b"")

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.RENDER.GAIN_TRIM.MP3.001",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "tone",
                            "file_path": "tone.mp3",
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.TRIM.MP3.001",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "eligible_render": True,
                        "target": {"scope": "stem", "stem_id": "tone"},
                        "params": [
                            {
                                "param_id": "PARAM.GAIN.DB",
                                "value": -3.0,
                            }
                        ],
                    }
                ],
            }
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            manifest = _render_manifest(report_path, out_manifest_path, out_dir, repo_root)
            gain_manifest = _gain_trim_manifest(manifest)
            self.assertEqual(gain_manifest.get("outputs"), [])
            skipped = gain_manifest.get("skipped", [])
            self.assertIsInstance(skipped, list)
            reasons = {
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
                    "REC.RENDER.GAIN.TRIM.MP3.001",
                    "ACTION.UTILITY.GAIN",
                    "lossy_input",
                ),
                reasons,
            )


if __name__ == "__main__":
    unittest.main()
