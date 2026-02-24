import os
import subprocess
import sys
import unittest


class TestCliSmoke(unittest.TestCase):
    def _python(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_cli_help(self) -> None:
        result = subprocess.run(
            [self._python(), "-m", "mmo", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"--help exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        self.assertIn("mmo", result.stdout.lower())

    def test_cli_export_help(self) -> None:
        result = subprocess.run(
            [
                self._python(),
                "-m",
                "mmo",
                "export",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"export --help exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        self.assertIn("--no-measurements", result.stdout)
        self.assertIn("--no-gates", result.stdout)
        self.assertIn("--truncate-values", result.stdout)


if __name__ == "__main__":
    unittest.main()
