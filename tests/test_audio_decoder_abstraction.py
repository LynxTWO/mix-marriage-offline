from __future__ import annotations

import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from mmo.core.session import discover_stem_files
from mmo.dsp.decoders import detect_format_from_path, iter_audio_float64_samples
from mmo.dsp.sample_rate import choose_render_sample_rate_hz


def _write_wav_16bit(path: Path, *, sample_rate_hz: int) -> None:
    frame_count = 64
    values = [int(0.4 * 32767.0) for _ in range(frame_count)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))


def _write_fake_ffmpeg(path: Path) -> None:
    path.write_text(
        """
import struct
import sys


def main() -> None:
    samples = [0.1] * 128
    sys.stdout.buffer.write(struct.pack(f"<{len(samples)}d", *samples))


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )


class TestAudioDecoderAbstraction(unittest.TestCase):
    def test_detect_format_includes_ape(self) -> None:
        self.assertEqual(detect_format_from_path(Path("stem.ape")), "ape")

    def test_discover_stem_files_includes_ape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ape_path = temp_path / "bass.ape"
            ape_path.write_bytes(b"")
            stems = discover_stem_files(temp_path)
        self.assertIn(ape_path, stems)

    def test_choose_render_sample_rate_majority_tie_and_explicit(self) -> None:
        selected, receipt = choose_render_sample_rate_hz([48000, 44100, 44100])
        self.assertEqual(selected, 44100)
        self.assertEqual(receipt.get("selection_reason"), "majority")

        selected, receipt = choose_render_sample_rate_hz([48000, 44100, 48000, 44100])
        self.assertEqual(selected, 48000)
        self.assertEqual(receipt.get("selection_reason"), "tie_higher_sample_rate")

        selected, receipt = choose_render_sample_rate_hz(
            [48000, 44100, 44100],
            explicit_sample_rate_hz=96000,
        )
        self.assertEqual(selected, 96000)
        self.assertEqual(receipt.get("selection_reason"), "explicit_sample_rate_hz")

    def test_iter_audio_float64_samples_resamples_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            wav_path = temp_path / "tone.wav"
            _write_wav_16bit(wav_path, sample_rate_hz=48000)

            chunks = list(
                iter_audio_float64_samples(
                    wav_path,
                    error_context="decoder abstraction test",
                    target_sample_rate_hz=44100,
                )
            )

        flattened = [sample for chunk in chunks for sample in chunk]
        self.assertGreater(len(flattened), 0)

    def test_iter_audio_float64_samples_decodes_non_wav_via_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_ffmpeg = temp_path / "fake_ffmpeg.py"
            _write_fake_ffmpeg(fake_ffmpeg)
            ape_path = temp_path / "stem.ape"
            ape_path.write_bytes(b"")

            with mock.patch.dict(
                os.environ,
                {"MMO_FFMPEG_PATH": str(fake_ffmpeg)},
                clear=False,
            ):
                chunks = list(
                    iter_audio_float64_samples(
                        ape_path,
                        error_context="decoder abstraction ffmpeg test",
                        metadata={"channels": 1, "sample_rate_hz": 48000},
                    )
                )

        flattened = [sample for chunk in chunks for sample in chunk]
        self.assertEqual(len(flattened), 128)


if __name__ == "__main__":
    unittest.main()
