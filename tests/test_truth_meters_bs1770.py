import math
import os
import tempfile
import unittest
import wave
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

from mmo.dsp.meters import compute_sample_peak_dbfs_wav


class TestTruthMetersBS1770(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        if np is None:
            self.skipTest("numpy not available")

    def _write_mono_wav(self, path: Path, samples: "np.ndarray", sample_rate: int) -> None:
        int_samples = np.round(samples * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as wav_handle:
            wav_handle.setnchannels(1)
            wav_handle.setsampwidth(2)
            wav_handle.setframerate(sample_rate)
            wav_handle.writeframes(int_samples.tobytes())

    def test_k_weighting_coeffs_48k_exact(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import k_weighting_biquads

        pre_b, pre_a, rlb_b, rlb_a = k_weighting_biquads(48000)
        expected_pre_b = np.array(
            [1.53512485958697, -2.69169618940638, 1.19839281085285],
            dtype=np.float64,
        )
        expected_pre_a = np.array(
            [1.0, -1.69065929318241, 0.73248077421585],
            dtype=np.float64,
        )
        expected_rlb_b = np.array([1.0, -2.0, 1.0], dtype=np.float64)
        expected_rlb_a = np.array(
            [1.0, -1.99004745483398, 0.99007225036621],
            dtype=np.float64,
        )
        self.assertTrue(np.allclose(pre_b, expected_pre_b, atol=1e-12, rtol=0.0))
        self.assertTrue(np.allclose(pre_a, expected_pre_a, atol=1e-12, rtol=0.0))
        self.assertTrue(np.allclose(rlb_b, expected_rlb_b, atol=1e-12, rtol=0.0))
        self.assertTrue(np.allclose(rlb_a, expected_rlb_a, atol=1e-12, rtol=0.0))

    def test_k_weighting_coeffs_ffmpeg_non_48k(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import k_weighting_biquads

        expected = {
            44100: (
                np.array([1.5308412300503478, -2.6509799951547297, 1.169079079921587]),
                np.array([1.0, -1.6636551132560204, 0.7125954280732254]),
                np.array([1.0, -2.0, 1.0]),
                np.array([1.0, -1.989169673629796, 0.9891990357870393]),
            ),
            96000: (
                np.array([1.5597142289757966, -2.9267415782510824, 1.3782612023158187]),
                np.array([1.0, -1.8446094698901085, 0.8558433229306412]),
                np.array([1.0, -2.0, 1.0]),
                np.array([1.0, -1.9950175447247156, 0.9950237590409233]),
            ),
        }
        for fs, (pre_b_t, pre_a_t, rlb_b_t, rlb_a_t) in expected.items():
            pre_b, pre_a, rlb_b, rlb_a = k_weighting_biquads(fs)
            self.assertTrue(np.allclose(pre_b, pre_b_t, atol=1e-12, rtol=0.0))
            self.assertTrue(np.allclose(pre_a, pre_a_t, atol=1e-12, rtol=0.0))
            self.assertTrue(np.allclose(rlb_b, rlb_b_t, atol=1e-12, rtol=0.0))
            self.assertTrue(np.allclose(rlb_a, rlb_a_t, atol=1e-12, rtol=0.0))

    def test_lufs_gating_sanity(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import compute_lufs_integrated_wav

        sample_rate = 48000
        duration_s = 10.0
        freq = 997.0
        t = np.arange(int(sample_rate * duration_s), dtype=np.float64) / sample_rate
        full_scale = 32767.0 / 32768.0
        tone = full_scale * np.sin(2.0 * math.pi * freq * t)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
        try:
            self._write_mono_wav(path, tone, sample_rate)
            lufs = compute_lufs_integrated_wav(path)
            self.assertGreater(lufs, -3.26)
            self.assertLess(lufs, -2.76)
        finally:
            path.unlink(missing_ok=True)

        loud_amp = 10.0 ** (-20.0 / 20.0)
        quiet_amp = 10.0 ** (-40.0 / 20.0)
        t_half = np.arange(int(sample_rate * duration_s / 2.0), dtype=np.float64) / sample_rate
        loud = loud_amp * np.sin(2.0 * math.pi * freq * t_half)
        quiet = quiet_amp * np.sin(2.0 * math.pi * freq * t_half)
        concatenated = np.concatenate([loud, quiet])

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
        try:
            self._write_mono_wav(path, concatenated, sample_rate)
            lufs = compute_lufs_integrated_wav(path)
            self.assertGreater(lufs, -30.0)
            self.assertLess(lufs, -15.0)
        finally:
            path.unlink(missing_ok=True)

    def test_true_peak_inter_sample(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import compute_true_peak_dbtp_wav

        sample_rate = 48000
        duration_s = 1.0
        freq = 12000.0
        phase = math.pi / 4.0
        t = np.arange(int(sample_rate * duration_s), dtype=np.float64) / sample_rate
        tone = np.sin(2.0 * math.pi * freq * t + phase)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
        try:
            self._write_mono_wav(path, tone, sample_rate)
            sample_peak_dbfs = compute_sample_peak_dbfs_wav(path)
            true_peak_dbtp = compute_true_peak_dbtp_wav(path)
            self.assertGreater(sample_peak_dbfs, -3.5)
            self.assertLess(sample_peak_dbfs, -2.5)
            self.assertGreater(true_peak_dbtp, -0.5)
            self.assertLess(true_peak_dbtp, 0.5)
            self.assertGreater(true_peak_dbtp - sample_peak_dbfs, 2.5)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
