import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tools.scan_session import build_report


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    duration_s: float,
    frequency_hz: float | None,
    amplitude: float = 0.4,
) -> None:
    frame_count = int(sample_rate_hz * duration_s)
    samples = bytearray()
    for index in range(frame_count):
        if frequency_hz is None:
            value = 0.0
        else:
            t = index / float(sample_rate_hz)
            value = amplitude * math.sin(2.0 * math.pi * frequency_hz * t)
        clipped = max(-1.0, min(1.0, value))
        samples.extend(struct.pack("<h", int(clipped * 32767.0)))

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(bytes(samples))


class TestMixComplexityMeters(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("mix complexity meters require numpy")

    def test_masking_risk_ranks_overlapping_pair_highest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            _write_mono_wav(
                stems_dir / "overlap_a.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=500.0,
            )
            _write_mono_wav(
                stems_dir / "overlap_b.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=500.0,
            )
            _write_mono_wav(
                stems_dir / "non_overlap.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=80.0,
            )

            report = build_report(
                stems_dir,
                "2000-01-01T00:00:00Z",
                meters="basic",
            )
            mix_complexity = report.get("mix_complexity", {})
            top_pairs = mix_complexity.get("top_masking_pairs", [])

            self.assertGreaterEqual(len(top_pairs), 1)
            top_pair = top_pairs[0]
            self.assertEqual(
                {top_pair.get("stem_a"), top_pair.get("stem_b")},
                {"overlap_a", "overlap_b"},
            )
            self.assertGreaterEqual(float(top_pair.get("score", 0.0)), 0.8)

    def test_density_metrics_reflect_silent_vs_active_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            _write_mono_wav(
                stems_dir / "active_a.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=400.0,
            )
            _write_mono_wav(
                stems_dir / "active_b.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=900.0,
            )
            _write_mono_wav(
                stems_dir / "silent.wav",
                sample_rate_hz=16000,
                duration_s=0.6,
                frequency_hz=None,
            )

            report = build_report(
                stems_dir,
                "2000-01-01T00:00:00Z",
                meters="basic",
            )
            mix_complexity = report.get("mix_complexity", {})
            density_peak = mix_complexity.get("density_peak")
            density_mean = mix_complexity.get("density_mean")
            timeline = mix_complexity.get("density_timeline", [])

            self.assertEqual(density_peak, 2)
            self.assertIsInstance(density_mean, float)
            self.assertGreaterEqual(density_mean, 1.8)
            self.assertLessEqual(density_mean, 2.0)
            self.assertTrue(timeline)
            self.assertTrue(
                all(item.get("active_stems") == 2 for item in timeline if isinstance(item, dict))
            )


if __name__ == "__main__":
    unittest.main()
