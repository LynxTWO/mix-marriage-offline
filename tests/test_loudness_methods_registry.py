import math
import os
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None


class TestLoudnessMethodsRegistry(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        if np is None:
            self.skipTest("numpy not available")

    def test_registry_includes_default_and_placeholders(self) -> None:
        from mmo.core.loudness_methods import list_loudness_method_ids

        method_ids = list_loudness_method_ids()
        self.assertIn("BS.1770-5", method_ids)
        self.assertIn("BS.1770-5-DIALOG-GATED", method_ids)
        self.assertIn("BS.1770-5-DIALOG-ANCHOR", method_ids)

    def test_placeholder_method_raises_not_implemented(self) -> None:
        from mmo.core.loudness_methods import require_implemented_loudness_method

        with self.assertRaisesRegex(NotImplementedError, "BS.1770-5-DIALOG-GATED"):
            require_implemented_loudness_method("BS.1770-5-DIALOG-GATED")

    def test_lufs_entrypoint_dispatches_via_method_registry(self) -> None:
        self._skip_if_no_numpy()
        from mmo.dsp.meters_truth import compute_lufs_integrated_float64

        samples = np.zeros((480, 2), dtype=np.float64)
        with self.assertRaisesRegex(NotImplementedError, "BS.1770-5-DIALOG-ANCHOR"):
            compute_lufs_integrated_float64(
                samples,
                48000,
                2,
                channel_mask=None,
                channel_layout="stereo",
                method_id="BS.1770-5-DIALOG-ANCHOR",
            )

        value = compute_lufs_integrated_float64(
            samples,
            48000,
            2,
            channel_mask=None,
            channel_layout="stereo",
            method_id="BS.1770-5",
        )
        self.assertTrue(math.isinf(value))


if __name__ == "__main__":
    unittest.main()
