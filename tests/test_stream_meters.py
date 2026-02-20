import os
import shutil
import struct
import unittest
import wave
from pathlib import Path
from uuid import uuid4

from mmo.dsp.stream_meters import compute_stream_meters

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_pcm16_wav(
    path: Path,
    *,
    channels: int,
    sample_value: int,
    sample_rate_hz: int = 48000,
    frames: int = 48000,
) -> None:
    values = [sample_value] * (frames * channels)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))


class TestStreamMeters(unittest.TestCase):
    def setUp(self) -> None:
        root = (REPO_ROOT / "sandbox_tmp" / "test_stream_meters").resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = root / f"case_{os.getpid()}_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_compute_stream_meters_wav_is_deterministic(self) -> None:
        path = self.temp_dir / "steady.wav"
        _write_pcm16_wav(path, channels=2, sample_value=16384)

        first = compute_stream_meters(path, ffmpeg_cmd=None)
        second = compute_stream_meters(path, ffmpeg_cmd=None)

        self.assertEqual(first, second)
        self.assertEqual(first["peak_dbfs"], -6.0206)
        self.assertEqual(first["rms_dbfs"], -6.0206)
        self.assertIn("integrated_lufs", first)
        self.assertTrue(
            first["integrated_lufs"] is None
            or isinstance(first["integrated_lufs"], (int, float))
        )

    def test_compute_stream_meters_silent_wav_returns_null_levels(self) -> None:
        path = self.temp_dir / "silence.wav"
        _write_pcm16_wav(path, channels=2, sample_value=0)

        result = compute_stream_meters(path, ffmpeg_cmd=None)
        self.assertEqual(
            result,
            {
                "peak_dbfs": None,
                "rms_dbfs": None,
                "integrated_lufs": None,
            },
        )

    def test_compute_stream_meters_non_wav_without_ffmpeg_returns_null_levels(self) -> None:
        path = self.temp_dir / "fake.flac"
        path.write_bytes(b"not audio")

        result = compute_stream_meters(path, ffmpeg_cmd=None)
        self.assertEqual(
            result,
            {
                "peak_dbfs": None,
                "rms_dbfs": None,
                "integrated_lufs": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
