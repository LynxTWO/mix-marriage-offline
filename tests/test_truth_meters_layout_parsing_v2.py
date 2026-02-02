import os
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None


class TestTruthMetersLayoutParsingV2(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        if np is None:
            self.skipTest("numpy not available")

    def test_layout_list_exact_51(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(
            6, None, "fl+fr+fc+lfe+bl+br"
        )
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,BL,BR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("layout_list_exact", mode_str)

    def test_layout_51_side_surround(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(6, None, "5.1(side)")
        expected = np.array([1.0, 1.0, 1.0, 0.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,FC,LFE,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_51_sl_sr_surround", mode_str)

    def test_layout_71_wide(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(8, None, "7.1(wide)")
        expected = np.array(
            [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.41, 1.41], dtype=np.float64
        )
        self.assertEqual(order_csv, "FL,FR,FC,LFE,FLC,FRC,SL,SR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_71_wide", mode_str)

    def test_layout_quad(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(4, None, "quad")
        expected = np.array([1.0, 1.0, 1.41, 1.41], dtype=np.float64)
        self.assertEqual(order_csv, "FL,FR,BL,BR")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("ffmpeg_layout_known_quad", mode_str)

    def test_layout_unknown(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        weights, order_csv, mode_str = bs1770_weighting_info(6, None, "unknown")
        expected = np.ones(6, dtype=np.float64)
        self.assertEqual(order_csv, "unknown")
        self.assertTrue(np.allclose(weights, expected, atol=1e-12, rtol=0.0))
        self.assertIn("fallback_layout_unknown", mode_str)


if __name__ == "__main__":
    unittest.main()
