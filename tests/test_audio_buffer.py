from __future__ import annotations

import unittest

from mmo.dsp.buffer import AudioBufferF64, generic_channel_order


class TestAudioBufferF64(unittest.TestCase):
    def test_invariants_enforced(self) -> None:
        with self.assertRaises(ValueError):
            AudioBufferF64(
                data=[0.0, 0.1, 0.2],
                channels=2,
                channel_order=("SPK.L", "SPK.R"),
                sample_rate_hz=48000,
            )

        with self.assertRaises(ValueError):
            AudioBufferF64(
                data=[0.0, 0.1],
                channels=2,
                channel_order=("SPK.L",),
                sample_rate_hz=48000,
            )

        with self.assertRaises(ValueError):
            AudioBufferF64.from_planar_lists(
                [[0.1, 0.2], [0.3]],
                channel_order=("CH.1", "CH.2"),
                sample_rate_hz=48000,
            )

    def test_planar_round_trip_is_reversible_within_tolerance(self) -> None:
        original = AudioBufferF64(
            data=[
                0.123456789,
                -0.333333333,
                0.222222222,
                -0.444444444,
                0.555555555,
                -0.666666666,
            ],
            channels=2,
            channel_order=("SPK.L", "SPK.R"),
            sample_rate_hz=48000,
        )

        restored = AudioBufferF64.from_planar_lists(
            original.to_planar_lists(),
            channel_order=original.channel_order,
            sample_rate_hz=original.sample_rate_hz,
        )

        self.assertEqual(restored.channels, original.channels)
        self.assertEqual(restored.channel_order, original.channel_order)
        self.assertEqual(restored.sample_rate_hz, original.sample_rate_hz)
        self.assertEqual(restored.frame_count, original.frame_count)
        for restored_sample, original_sample in zip(restored.data, original.data):
            self.assertAlmostEqual(restored_sample, original_sample, places=12)

    def test_peak_per_channel_matches_expected_fixture(self) -> None:
        buffer = AudioBufferF64(
            data=[
                0.10,
                -0.40,
                0.20,
                -0.35,
                0.25,
                0.05,
                0.05,
                -0.10,
                -0.45,
            ],
            channels=3,
            channel_order=("SPK.L", "SPK.C", "SPK.R"),
            sample_rate_hz=48000,
        )

        self.assertEqual(buffer.peak_per_channel(), [0.35, 0.4, 0.45])

    def test_iter_frames_is_deterministic(self) -> None:
        buffer = AudioBufferF64(
            data=[
                0.0,
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                9.0,
            ],
            channels=2,
            channel_order=("SPK.L", "SPK.R"),
            sample_rate_hz=48000,
        )

        chunks = list(buffer.iter_frames(2))

        self.assertEqual([chunk.frame_count for chunk in chunks], [2, 2, 1])
        self.assertEqual(
            [chunk.data for chunk in chunks],
            [
                [0.0, 1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0, 7.0],
                [8.0, 9.0],
            ],
        )
        self.assertTrue(all(chunk.channel_order == buffer.channel_order for chunk in chunks))

    def test_slice_and_gain_preserve_metadata(self) -> None:
        buffer = AudioBufferF64(
            data=[0.2, -0.2, 0.3, -0.3, 0.4, -0.4],
            channels=2,
            channel_order=("SPK.L", "SPK.R"),
            sample_rate_hz=44100,
        )

        sliced = buffer.slice_frames(1, 2)
        gained = sliced.apply_gain_scalar(0.5)

        self.assertEqual(sliced.data, [0.3, -0.3, 0.4, -0.4])
        self.assertEqual(gained.data, [0.15, -0.15, 0.2, -0.2])
        self.assertEqual(gained.channel_order, ("SPK.L", "SPK.R"))
        self.assertEqual(gained.sample_rate_hz, 44100)

    def test_generic_channel_order_is_stable(self) -> None:
        self.assertEqual(generic_channel_order(4), ("CH.1", "CH.2", "CH.3", "CH.4"))


if __name__ == "__main__":
    unittest.main()
