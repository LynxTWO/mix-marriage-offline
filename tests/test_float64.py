import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.dsp.float64 import bytes_to_int_samples_pcm, pcm_int_to_float64
from mmo.dsp.meters import (
    compute_clip_sample_count_wav,
    compute_crest_factor_db_wav,
    compute_dc_offset_wav,
    compute_rms_dbfs_wav,
    compute_sample_peak_dbfs_wav,
)


class TestFloat64Conversion(unittest.TestCase):
    def test_pcm_int_to_float64_16bit_exactness(self) -> None:
        samples = [-32768, -1, 0, 1, 32767]
        expected = [
            -1.0,
            -1.0 / 32768.0,
            0.0,
            1.0 / 32768.0,
            32767.0 / 32768.0,
        ]
        result = pcm_int_to_float64(samples, 16)
        self.assertEqual(len(result), len(expected))
        for value, target in zip(result, expected):
            self.assertAlmostEqual(value, target, places=12)

    def test_bytes_to_int_samples_pcm_24bit_sign_extend(self) -> None:
        frames = b"\xff\xff\xff" + b"\x00\x00\x80" + b"\xff\xff\x7f"
        result = bytes_to_int_samples_pcm(frames, 24, 1)
        self.assertEqual(result, [-1, -8388608, 8388607])

    def test_peak_meter_dbfs_float64(self) -> None:
        samples = [0, 0, 16384, -8192, 32767, 0]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)

        try:
            with wave.open(str(path), "wb") as wav_handle:
                wav_handle.setnchannels(2)
                wav_handle.setsampwidth(2)
                wav_handle.setframerate(48000)
                wav_handle.writeframes(
                    struct.pack(f"<{len(samples)}h", *samples)
                )

            expected_peak = max(abs(sample) / 32768.0 for sample in samples)
            expected_dbfs = 20.0 * math.log10(expected_peak)
            result = compute_sample_peak_dbfs_wav(path)
            self.assertAlmostEqual(result, expected_dbfs, places=7)
        finally:
            path.unlink(missing_ok=True)

    def test_basic_meters_float64(self) -> None:
        samples = [-32768, 0, 32767, 16384, -16384, 0]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)

        try:
            with wave.open(str(path), "wb") as wav_handle:
                wav_handle.setnchannels(1)
                wav_handle.setsampwidth(2)
                wav_handle.setframerate(48000)
                wav_handle.writeframes(
                    struct.pack(f"<{len(samples)}h", *samples)
                )

            floats = [sample / 32768.0 for sample in samples]
            expected_clip = sum(1 for value in floats if abs(value) >= 1.0 - 1e-12)
            expected_dc = sum(floats) / len(floats)
            mean_square = sum(value * value for value in floats) / len(floats)
            rms = math.sqrt(mean_square)
            expected_rms_dbfs = 20.0 * math.log10(rms) if rms > 0.0 else float("-inf")
            peak = max(abs(value) for value in floats)
            expected_crest_db = (
                20.0 * math.log10(peak / rms) if rms > 0.0 else float("-inf")
            )

            self.assertEqual(compute_clip_sample_count_wav(path), expected_clip)
            self.assertAlmostEqual(compute_dc_offset_wav(path), expected_dc, places=12)
            self.assertAlmostEqual(
                compute_rms_dbfs_wav(path), expected_rms_dbfs, places=7
            )
            self.assertAlmostEqual(
                compute_crest_factor_db_wav(path), expected_crest_db, places=7
            )
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
