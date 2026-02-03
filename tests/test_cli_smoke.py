import os
import subprocess
import sys
import unittest


class TestCliSmoke(unittest.TestCase):
    def test_cli_help(self) -> None:
        result = subprocess.run(
            [os.fspath(os.getenv("PYTHON", "") or sys.executable), "-m", "mmo", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_cli_export_help(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "export",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--no-measurements", result.stdout)
        self.assertIn("--no-gates", result.stdout)
        self.assertIn("--truncate-values", result.stdout)


if __name__ == "__main__":
    unittest.main()
