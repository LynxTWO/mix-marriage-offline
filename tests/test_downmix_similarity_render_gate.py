from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.downmix import (
    apply_downmix_matrix_deterministic,
    compare_rendered_surround_to_stereo_reference,
    enforce_rendered_surround_similarity_gate,
)


def _write_stereo_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.25,
    amp_l: float = 0.25,
    amp_r: float = 0.25,
    freq_l_hz: float = 220.0,
    freq_r_hz: float = 330.0,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for index in range(frames):
        sample_l = int(
            amp_l
            * 32767.0
            * math.sin(2.0 * math.pi * freq_l_hz * index / sample_rate_hz)
        )
        sample_r = int(
            amp_r
            * 32767.0
            * math.sin(2.0 * math.pi * freq_r_hz * index / sample_rate_hz)
        )
        interleaved.extend([sample_l, sample_r])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _write_51_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.25,
    amp_l: float = 0.25,
    amp_r: float = 0.25,
    amp_ls: float = 0.0,
    amp_rs: float = 0.0,
) -> None:
    # Channel order: L R C LFE LS RS
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for index in range(frames):
        sample_l = int(
            amp_l * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz)
        )
        sample_r = int(
            amp_r * 32767.0 * math.sin(2.0 * math.pi * 330.0 * index / sample_rate_hz)
        )
        sample_ls = int(
            amp_ls * 32767.0 * math.sin(2.0 * math.pi * 550.0 * index / sample_rate_hz)
        )
        sample_rs = int(
            amp_rs * 32767.0 * math.sin(2.0 * math.pi * 660.0 * index / sample_rate_hz)
        )
        interleaved.extend([sample_l, sample_r, 0, 0, sample_ls, sample_rs])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(6)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


class TestRenderedSimilarityGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _path(self, name: str) -> Path:
        return Path(self._tmp) / name

    def test_apply_downmix_matrix_deterministic_returns_stereo_output(self) -> None:
        source = [1.0, 0.5, 0.0, 0.0, 0.0, 0.0]
        result = apply_downmix_matrix_deterministic(
            source,
            source_layout_id="LAYOUT.5_1",
            target_layout_id="LAYOUT.2_0",
        )
        self.assertEqual(result["source_channels"], 6)
        self.assertEqual(result["target_channels"], 2)
        output = result["output_interleaved"]
        self.assertEqual(len(output), 2)
        self.assertAlmostEqual(output[0], 1.0, places=4)
        self.assertAlmostEqual(output[1], 0.5, places=4)

    def test_compare_rendered_surround_to_stereo_reference_passes_when_aligned(self) -> None:
        stereo_path = self._path("reference.stereo.wav")
        surround_path = self._path("surround.5_1.wav")
        _write_stereo_wav(stereo_path, amp_l=0.25, amp_r=0.2)
        _write_51_wav(surround_path, amp_l=0.25, amp_r=0.2, amp_ls=0.0, amp_rs=0.0)

        result = compare_rendered_surround_to_stereo_reference(
            stereo_render_file=stereo_path,
            surround_render_file=surround_path,
            source_layout_id="LAYOUT.5_1",
            loudness_delta_warn_abs=0.6,
            loudness_delta_error_abs=1.2,
            spectral_distance_warn_db=4.0,
            spectral_distance_error_db=8.0,
            peak_delta_warn_abs=2.0,
            peak_delta_error_abs=4.0,
            true_peak_delta_warn_abs=2.0,
            true_peak_delta_error_abs=4.0,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["risk_level"], "low")
        self.assertIn("metrics", result)
        metrics = result["metrics"]
        self.assertIn("loudness_delta_lufs", metrics)
        self.assertIn("correlation_over_time_min", metrics)
        self.assertIn("spectral_distance_db", metrics)
        self.assertIn("peak_delta_dbfs", metrics)
        self.assertIn("true_peak_delta_dbtp", metrics)

    def test_enforce_rendered_surround_similarity_gate_applies_one_retry(self) -> None:
        stereo_path = self._path("reference.stereo.wav")
        surround_path = self._path("surround.5_1.hot_surrounds.wav")
        _write_stereo_wav(stereo_path, amp_l=0.22, amp_r=0.18)
        _write_51_wav(surround_path, amp_l=0.22, amp_r=0.18, amp_ls=0.9, amp_rs=0.9)

        result = enforce_rendered_surround_similarity_gate(
            stereo_render_file=stereo_path,
            surround_render_file=surround_path,
            source_layout_id="LAYOUT.5_1",
            surround_backoff_db=-36.0,
            loudness_delta_warn_abs=0.8,
            loudness_delta_error_abs=1.6,
            correlation_time_warn_lte=0.3,
            correlation_time_error_lte=0.1,
            spectral_distance_warn_db=5.0,
            spectral_distance_error_db=10.0,
            peak_delta_warn_abs=2.5,
            peak_delta_error_abs=5.0,
            true_peak_delta_warn_abs=2.0,
            true_peak_delta_error_abs=4.0,
        )
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertFalse(result["attempts"][0]["passed"])
        first_metrics = result["attempts"][0].get("metrics", {})
        second_metrics = result["attempts"][1].get("metrics", {})
        first_loudness = first_metrics.get("loudness_delta_lufs")
        second_loudness = second_metrics.get("loudness_delta_lufs")
        if isinstance(first_loudness, (int, float)) and isinstance(second_loudness, (int, float)):
            self.assertLessEqual(abs(float(second_loudness)), abs(float(first_loudness)))

    def test_compare_is_deterministic(self) -> None:
        stereo_path = self._path("reference.stereo.wav")
        surround_path = self._path("surround.5_1.wav")
        _write_stereo_wav(stereo_path, amp_l=0.2, amp_r=0.2)
        _write_51_wav(surround_path, amp_l=0.2, amp_r=0.2, amp_ls=0.15, amp_rs=0.12)

        first = compare_rendered_surround_to_stereo_reference(
            stereo_render_file=stereo_path,
            surround_render_file=surround_path,
            source_layout_id="LAYOUT.5_1",
        )
        second = compare_rendered_surround_to_stereo_reference(
            stereo_render_file=stereo_path,
            surround_render_file=surround_path,
            source_layout_id="LAYOUT.5_1",
        )
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
