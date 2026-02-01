import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestScanSessionCliErrors(unittest.TestCase):
    def test_empty_stems_dir_returns_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            scan_session = repo_root / "tools" / "scan_session.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("No audio stems found", result.stderr)


if __name__ == "__main__":
    unittest.main()
