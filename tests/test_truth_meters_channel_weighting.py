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
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(6, 0x3F)
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("mask_known_51", mode_str)

    def test_mask_71_sl_sr_surround(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(8, 0x63F)
        expected = np.array(
            [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.41, 1.41], dtype=np.float64
        )
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("mask_known_71", mode_str)

    def test_fallback_mask_underspecified(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import _bs1770_gi_weights

        weights, order_csv, mode_str = _bs1770_gi_weights(6, 0x3)
        expected = np.ones(6, dtype=np.float64)
        self.assertEqual(order_csv, "unknown")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("fallback_mask_underspecified", mode_str)


if __name__ == "__main__":
    unittest.main()
