import os
import unittest


class TestTruthMetersModeTokens(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

    def test_mode_tokens_exact(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import bs1770_weighting_info

        cases = [
            ((6, None, "fl+fr+fc+lfe+bl+br"), "ffmpeg_layout_known_layout_list_exact"),
            ((6, None, "5.1(side)"), "ffmpeg_layout_known_51_sl_sr_surround"),
            ((6, None, "5.1"), "ffmpeg_layout_known_51"),
            ((8, None, "7.1"), "ffmpeg_layout_known_71_sl_sr_surround_blbr_rear"),
            ((8, None, "7.1(wide)"), "ffmpeg_layout_known_71_wide"),
            ((4, None, "quad"), "ffmpeg_layout_known_quad"),
            ((6, 0x3F, None), "mask_known_51_blbr_surround"),
            ((8, 0x63F, None), "mask_known_71_sl_sr_surround_blbr_rear"),
            ((6, 0x3, None), "fallback_layout_missing"),
            ((6, None, "unknown"), "fallback_layout_unknown"),
        ]

        for args, expected in cases:
            _, _, mode_str = bs1770_weighting_info(*args)
            self.assertEqual(mode_str, expected)


if __name__ == "__main__":
    unittest.main()
