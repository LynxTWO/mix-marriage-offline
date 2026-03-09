from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.downmix import enforce_rendered_surround_similarity_gate
from mmo.core.fallback_sequencer import run_fallback_sequence


def _write_stereo_wav(
    path: Path,
    *,
    amp_l: float,
    amp_r: float,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.2,
    freq_hz: float = 220.0,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples: list[int] = []
    for index in range(frames):
        phase = 2.0 * math.pi * freq_hz * index / sample_rate_hz
        left = int(amp_l * 32767.0 * math.sin(phase))
        right = int(amp_r * 32767.0 * math.sin(phase))
        samples.extend((left, right))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_51_wav(
    path: Path,
    *,
    amp_l: float,
    amp_r: float,
    amp_ls: float,
    amp_rs: float,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.2,
    freq_hz: float = 220.0,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples: list[int] = []
    for index in range(frames):
        phase = 2.0 * math.pi * freq_hz * index / sample_rate_hz
        left = int(amp_l * 32767.0 * math.sin(phase))
        right = int(amp_r * 32767.0 * math.sin(phase))
        surround_left = int(amp_ls * 32767.0 * math.sin(phase))
        surround_right = int(amp_rs * 32767.0 * math.sin(phase))
        samples.extend((left, right, 0, 0, surround_left, surround_right))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(6)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestFallbackSequencer(unittest.TestCase):
    def test_run_fallback_sequence_stops_when_improvement_stalls(self) -> None:
        def _render_fn(state: dict[str, float]) -> dict[str, float]:
            return dict(state)

        def _qa_fn(state: dict[str, float]) -> dict[str, float | bool]:
            return {
                "passed": float(state["score"]) <= 0.0,
                "score": float(state["score"]),
            }

        steps = [
            {
                "step_id": "step_a",
                "apply": lambda state: ({"score": float(state["score"]) - 1.0}, [{"delta": -1.0}]),
            },
            {
                "step_id": "step_b",
                "apply": lambda state: ({"score": float(state["score"]) - 0.001}, [{"delta": -0.001}]),
            },
            {
                "step_id": "step_c",
                "apply": lambda state: ({"score": float(state["score"]) - 0.001}, [{"delta": -0.001}]),
            },
        ]
        final_state, report = run_fallback_sequence(
            render_fn=_render_fn,
            qa_fn=_qa_fn,
            initial_state={"score": 3.0},
            steps=steps,
            stop_rule={
                "max_steps": 3,
                "improvement_epsilon": 0.01,
                "stagnation_limit": 2,
            },
        )
        self.assertAlmostEqual(float(final_state["score"]), 1.998, places=6)
        attempts = report.get("fallback_attempts")
        self.assertIsInstance(attempts, list)
        if not isinstance(attempts, list):
            return
        self.assertEqual([row["step_id"] for row in attempts], ["step_a", "step_b", "step_c"])
        self.assertEqual(report["fallback_final"]["stop_reason"], "insufficient_improvement")
        self.assertEqual(report["fallback_final"]["final_outcome"], "fail")

    def test_similarity_gate_runs_ordered_fallback_and_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stereo_path = temp / "reference.stereo.wav"
            surround_path = temp / "surround.5_1.hot.wav"
            _write_stereo_wav(stereo_path, amp_l=0.22, amp_r=0.18)
            _write_51_wav(
                surround_path,
                amp_l=0.22,
                amp_r=0.18,
                amp_ls=0.9,
                amp_rs=0.9,
            )

            try:
                result = enforce_rendered_surround_similarity_gate(
                    stereo_render_file=stereo_path,
                    surround_render_file=surround_path,
                    source_layout_id="LAYOUT.5_1",
                    surround_backoff_db=-24.0,
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
            except RuntimeError as exc:
                if "numpy" in str(exc).lower() or "truth meters" in str(exc).lower():
                    self.skipTest(str(exc))
                raise

            self.assertTrue(result["fallback_applied"])
            self.assertTrue(result["passed"])
            self.assertEqual(result["fallback_final"]["final_outcome"], "pass")
            attempts = result.get("fallback_attempts")
            self.assertIsInstance(attempts, list)
            if not isinstance(attempts, list):
                return
            self.assertGreaterEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["step_id"], "reduce_surround_and_wide")
            ordered_step_ids = [row["step_id"] for row in attempts]
            expected_order = [
                "reduce_surround_and_wide",
                "reduce_height",
                "front_bias_ambiguous_beds",
                "collapse_bed_to_front_only",
            ]
            self.assertEqual(
                ordered_step_ids,
                sorted(ordered_step_ids, key=expected_order.index),
            )
            rendered_attempts = result.get("attempts")
            self.assertIsInstance(rendered_attempts, list)
            if isinstance(rendered_attempts, list):
                self.assertGreaterEqual(len(rendered_attempts), 2)
                self.assertFalse(bool(rendered_attempts[0].get("passed")))
                self.assertTrue(bool(rendered_attempts[-1].get("passed")))


if __name__ == "__main__":
    unittest.main()
