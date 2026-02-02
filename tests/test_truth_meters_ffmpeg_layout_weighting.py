import os
import unittest


class TestTruthMetersFfmpegLayoutWeighting(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

    def test_layout_51_blbr_surround(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(
            6, None, channel_layout="5.1"
        )
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_51", mode_str)

    def test_layout_51_side_surround(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(
            6, None, channel_layout="5.1(side)"
        )
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_51", mode_str)

    def test_layout_71_surround(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(
            8, None, channel_layout="7.1"
        )
        expected = np.array(
            [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.41, 1.41], dtype=np.float64
        )
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_71", mode_str)


if __name__ == "__main__":
    unittest.main()
