import unittest

from mmo.dsp.downmix import format_coeff_rows


class TestDownmixShowFormatting(unittest.TestCase):
    def test_format_coeff_rows_deterministic(self) -> None:
        coeffs = [
            [1, 0.5, 0],
            [0.25, -0.125, 0.3333333],
        ]
        formatted = format_coeff_rows(coeffs, decimals=6)
        self.assertEqual(
            formatted,
            [
                ["1.000000", "0.500000", "0.000000"],
                ["0.250000", "-0.125000", "0.333333"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
