import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import jsonschema

from mmo.cli import main
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
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


def _build_report(*, report_id: str, stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
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
                "recommendation_id": "REC.RENDER.GAIN.LOSSLESS.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [
                    {
                        "param_id": "PARAM.GAIN.DB",
                        "value": -2.0,
                    }
                ],
            }
        ],
    }


def _gain_trim_manifest(payload: dict) -> dict | None:
    renderer_manifests = payload.get("renderer_manifests")
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


class TestLosslessOutputFormats(unittest.TestCase):
    def test_render_output_formats_wav_flac_wv(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (repo_root / "schemas" / "render_manifest.schema.json").read_text(encoding="utf-8")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            report_path.write_text(
                json.dumps(
                    _build_report(
                        report_id="REPORT.CLI.RENDER.LOSSLESS.001",
                        stems_dir=stems_dir,
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
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
                    "--output-formats",
                    "wav,flac,wv",
                ]
            )
            self.assertEqual(exit_code, 0)

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(manifest)

            gain_manifest = _gain_trim_manifest(manifest)
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return
            self.assertEqual(len(outputs), 3)

            formats = {item.get("format") for item in outputs if isinstance(item, dict)}
            self.assertEqual(formats, {"wav", "flac", "wv"})
            stem_ids = {item.get("target_stem_id") for item in outputs if isinstance(item, dict)}
            self.assertEqual(stem_ids, {"kick"})

            for output in outputs:
                if not isinstance(output, dict):
                    continue
                output_file = out_dir / Path(str(output.get("file_path", "")))
                self.assertTrue(output_file.exists())
                self.assertEqual(output.get("sha256"), sha256_file(output_file))

    def test_render_skip_non_wav_when_ffmpeg_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "render_manifest.json"
            out_dir = temp_path / "renders"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            report_path.write_text(
                json.dumps(
                    _build_report(
                        report_id="REPORT.CLI.RENDER.LOSSLESS.NO.FFMPEG",
                        stems_dir=stems_dir,
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch("mmo.core.pipeline.resolve_ffmpeg_cmd", return_value=None):
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
                        "--output-formats",
                        "wav,flac",
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
            if not isinstance(outputs, list):
                return
            self.assertEqual(
                {item.get("format") for item in outputs if isinstance(item, dict)},
                {"wav"},
            )
            wav_output = outputs[0] if outputs else {}
            if isinstance(wav_output, dict):
                wav_path = out_dir / Path(str(wav_output.get("file_path", "")))
                self.assertTrue(wav_path.exists())
                self.assertEqual(wav_output.get("sha256"), sha256_file(wav_path))

            skipped = gain_manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            if not isinstance(skipped, list):
                return
            reasons = {item.get("reason") for item in skipped if isinstance(item, dict)}
            self.assertIn("missing_ffmpeg_for_encode", reasons)


if __name__ == "__main__":
    unittest.main()
