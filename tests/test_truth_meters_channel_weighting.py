import os
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None


class TestTruthMetersChannelWeighting(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        if np is None:
            self.skipTest("numpy not available")

    def test_mask_51_blbr_surround(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(6, 0x3F, None)
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("mask_known_51", mode_str)

    def test_mask_71_sl_sr_surround(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(8, 0x63F, None)
        expected = np.array(
            [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.41, 1.41], dtype=np.float64
        )
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("mask_known_71", mode_str)

    def test_fallback_mask_underspecified(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(6, 0x3, None)
        expected = np.ones(6, dtype=np.float64)
        self.assertEqual(order_csv, "unknown")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("fallback_layout_missing", mode_str)


if __name__ == "__main__":
    unittest.main()
