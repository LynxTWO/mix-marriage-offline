import unittest
from pathlib import Path

from tools.check_screenshot_diff import _format_dimensions, _format_size_mismatch


class TestScreenshotDiffFormatting(unittest.TestCase):
    def test_format_dimensions_reports_width_before_height(self) -> None:
        self.assertEqual(_format_dimensions((1280, 3058)), "1280x3058")

    def test_size_mismatch_message_reports_width_before_height(self) -> None:
        message = _format_size_mismatch(
            Path("committed.png"),
            (1280, 3013),
            Path("generated.png"),
            (1280, 3058),
        )
        self.assertEqual(
            message,
            "Image size mismatch: committed.png is 1280x3013 "
            "but generated.png is 1280x3058",
        )


if __name__ == "__main__":
    unittest.main()
