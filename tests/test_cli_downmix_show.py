import csv
import json
import os
import subprocess
import sys
import unittest


class TestCliDownmixShow(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_downmix_show_json(self) -> None:
        result = subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "downmix",
                "show",
                "--source",
                "LAYOUT.5_1",
                "--target",
                "LAYOUT.2_0",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, dict)
        for key in (
            "matrix_id",
            "source_layout_id",
            "target_layout_id",
            "source_speakers",
            "target_speakers",
            "coeffs",
        ):
            self.assertIn(key, payload)
        coeffs = payload["coeffs"]
        self.assertEqual(len(coeffs), 2)
        source_count = len(payload["source_speakers"])
        for row in coeffs:
            self.assertEqual(len(row), source_count)

    def test_downmix_show_csv(self) -> None:
        result = subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "downmix",
                "show",
                "--source",
                "LAYOUT.5_1",
                "--target",
                "LAYOUT.2_0",
                "--format",
                "csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        rows = list(csv.reader(result.stdout.splitlines()))
        self.assertTrue(rows)
        header = rows[0]
        self.assertIn("target_speaker", header)
        self.assertIn("SPK.L", header)
        self.assertIn("SPK.R", header)


if __name__ == "__main__":
    unittest.main()
