from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.core.render_reporting import build_render_report_from_plan
from mmo.dsp.sample_rate import choose_target_rate_for_session, iter_resampled_float64_samples
from mmo.plugins.renderers.mixdown_renderer import MixdownRenderer


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schema_path = SCHEMAS_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    duration_s: float = 0.1,
    frequency_hz: float = 220.0,
) -> None:
    frame_count = max(1, int(round(sample_rate_hz * duration_s)))
    samples = [
        int(0.25 * 32767.0 * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate_hz))
        for index in range(frame_count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestResamplingPolicy(unittest.TestCase):
    def test_choose_target_rate_prefers_family_majority_then_higher_exact_rate(self) -> None:
        selected, receipt = choose_target_rate_for_session(
            [
                {"stem_id": "STEM.44100.A", "sample_rate_hz": 44_100},
                {"stem_id": "STEM.44100.B", "sample_rate_hz": 44_100},
                {"stem_id": "STEM.88200.A", "sample_rate_hz": 88_200},
                {"stem_id": "STEM.88200.B", "sample_rate_hz": 88_200},
                {"stem_id": "STEM.96000", "sample_rate_hz": 96_000},
                {"stem_id": "STEM.48000", "sample_rate_hz": 48_000},
            ]
        )

        self.assertEqual(selected, 88_200)
        self.assertEqual(receipt.get("selected_family_sample_rate_hz"), 44_100)
        self.assertEqual(receipt.get("selected_family_reason"), "majority")
        self.assertEqual(receipt.get("selection_reason"), "tie_higher_sample_rate")

    def test_choose_target_rate_prefers_48000_for_44100_48000_majority_and_tie(self) -> None:
        majority_selected, majority_receipt = choose_target_rate_for_session(
            [
                {"stem_id": "STEM.48000.A", "sample_rate_hz": 48_000},
                {"stem_id": "STEM.48000.B", "sample_rate_hz": 48_000},
                {"stem_id": "STEM.44100", "sample_rate_hz": 44_100},
            ]
        )
        self.assertEqual(majority_selected, 48_000)
        self.assertEqual(majority_receipt.get("selection_reason"), "majority")

        tie_selected, tie_receipt = choose_target_rate_for_session(
            [
                {"stem_id": "STEM.48000", "sample_rate_hz": 48_000},
                {"stem_id": "STEM.44100", "sample_rate_hz": 44_100},
            ]
        )
        self.assertEqual(tie_selected, 48_000)
        self.assertEqual(
            tie_receipt.get("selected_family_reason"),
            "tie_higher_sample_rate_family",
        )

    def test_iter_resampled_float64_samples_has_expected_frame_count_monotonicity(self) -> None:
        source_frames = [float(index) / 100.0 for index in range(96)]
        source_chunks = iter(
            [
                source_frames[:17],
                source_frames[17:51],
                source_frames[51:73],
                source_frames[73:],
            ]
        )
        downsampled = [
            sample
            for chunk in iter_resampled_float64_samples(
                source_chunks,
                channels=1,
                source_sample_rate_hz=48_000,
                target_sample_rate_hz=44_100,
                chunk_frames=11,
            )
            for sample in chunk
        ]

        upsampled = [
            sample
            for chunk in iter_resampled_float64_samples(
                iter(
                    [
                        source_frames[:19],
                        source_frames[19:58],
                        source_frames[58:],
                    ]
                ),
                channels=1,
                source_sample_rate_hz=44_100,
                target_sample_rate_hz=88_200,
                chunk_frames=13,
            )
            for sample in chunk
        ]

        self.assertGreater(len(downsampled), 0)
        self.assertGreater(len(upsampled), 0)
        self.assertLess(len(downsampled), len(source_frames))
        self.assertGreater(len(upsampled), len(source_frames))

    def test_mixed_sample_rate_render_receipt_is_promoted_into_render_report(self) -> None:
        validator = _validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "renders"
            _write_mono_wav(stems_dir / "stem_48k.wav", sample_rate_hz=48_000, frequency_hz=220.0)
            _write_mono_wav(stems_dir / "stem_44k1.wav", sample_rate_hz=44_100, frequency_hz=330.0)

            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.48K",
                        "file_path": "stem_48k.wav",
                        "sample_rate_hz": "not-an-int",
                    },
                    {
                        "stem_id": "STEM.44K1",
                        "file_path": "stem_44k1.wav",
                    },
                ],
            }

            manifest = MixdownRenderer().render(session, [], out_dir)
            outputs = manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return

            stereo_row = next(
                (
                    row
                    for row in outputs
                    if isinstance(row, dict) and row.get("layout_id") == "LAYOUT.2_0"
                ),
                None,
            )
            self.assertIsInstance(stereo_row, dict)
            if not isinstance(stereo_row, dict):
                return

            metadata = stereo_row.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            resampling_receipt = metadata.get("resampling")
            self.assertIsInstance(resampling_receipt, dict)
            if not isinstance(resampling_receipt, dict):
                return

            plan = {
                "schema_version": "0.1.0",
                "request": {
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": "scenes/test_session/scene.json",
                },
                "jobs": [
                    {
                        "job_id": "JOB.001",
                        "target_layout_id": "LAYOUT.2_0",
                        "output_formats": ["wav"],
                        "contexts": ["render"],
                        "notes": [],
                        "resampling_receipt": resampling_receipt,
                    }
                ],
                "policies": {},
            }

            report = build_render_report_from_plan(
                plan,
                status="completed",
                reason="rendered",
            )
            validator.validate(report)

            job = report["jobs"][0]
            self.assertIn("resampling_receipt", job)
            promoted_receipt = job["resampling_receipt"]
            self.assertEqual(promoted_receipt.get("target_sample_rate_hz"), 48_000)

            resampled_stem_ids = {
                row.get("stem_id")
                for row in promoted_receipt.get("resampled_stems", [])
                if isinstance(row, dict)
            }
            self.assertIn("STEM.44K1", resampled_stem_ids)

            warnings = promoted_receipt.get("decoder_warnings", [])
            warning_names = {
                row.get("warning")
                for row in warnings
                if isinstance(row, dict)
            }
            self.assertIn("metadata_sample_rate_invalid", warning_names)


if __name__ == "__main__":
    unittest.main()
