from __future__ import annotations

import unittest

from mmo.dsp.export_finalize import (
    StreamingExportFinalizer,
    export_finalize_interleaved_f64,
)
from mmo.dsp.float64 import bytes_to_int_samples_pcm


class TestExportFinalize(unittest.TestCase):
    def test_pcm16_tpdf_is_deterministic_for_fixed_seed(self) -> None:
        samples = [0.0, 0.125, -0.125, 0.5, -0.5, 0.999]

        first = export_finalize_interleaved_f64(
            samples,
            channels=2,
            bit_depth=16,
            dither_policy="tpdf",
            seed=12345,
        )
        second = export_finalize_interleaved_f64(
            samples,
            channels=2,
            bit_depth=16,
            dither_policy="tpdf",
            seed=12345,
        )

        self.assertEqual(first, second)

    def test_pcm24_none_matches_expected_rounding(self) -> None:
        samples = [0.5, -0.5, 0.25, -0.25]

        rendered = export_finalize_interleaved_f64(
            samples,
            channels=2,
            bit_depth=24,
            dither_policy="none",
            seed=0,
        )
        decoded = bytes_to_int_samples_pcm(rendered, 24, 2)

        self.assertEqual(decoded, [4194304, -4194304, 2097152, -2097152])

    def test_output_never_exceeds_pcm_bounds(self) -> None:
        samples = [-4.0, -1.0, -0.1, 0.1, 1.0, 4.0]
        rendered = export_finalize_interleaved_f64(
            samples,
            channels=1,
            bit_depth=16,
            dither_policy="tpdf",
            seed=777,
        )
        decoded = bytes_to_int_samples_pcm(rendered, 16, 1)

        self.assertTrue(all(-32768 <= sample <= 32767 for sample in decoded))

    def test_streaming_finalizer_matches_one_shot_output(self) -> None:
        samples = [0.01 * index for index in range(-32, 32)]
        one_shot = export_finalize_interleaved_f64(
            samples,
            channels=2,
            bit_depth=16,
            dither_policy="tpdf",
            seed=99,
        )

        finalizer = StreamingExportFinalizer(
            channels=2,
            bit_depth=16,
            dither_policy="tpdf",
            seed=99,
        )
        chunked = b"".join(
            (
                finalizer.finalize_chunk(samples[:18]),
                finalizer.finalize_chunk(samples[18:46]),
                finalizer.finalize_chunk(samples[46:]),
            )
        )

        self.assertEqual(chunked, one_shot)


if __name__ == "__main__":
    unittest.main()
