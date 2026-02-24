import os
import subprocess
import sys
import unittest


class TestCliSmoke(unittest.TestCase):
    def _python(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self._python(), "-m", "mmo", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_cli_help(self) -> None:
        result = self._run("--help")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"--help exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        combined = result.stdout + result.stderr
        self.assertIn(
            "usage:",
            combined.lower(),
            msg=f"'usage:' not found.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        self.assertIn("mmo", combined.lower())

    def test_cli_export_help(self) -> None:
        result = self._run("export", "--help")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"export --help exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        self.assertIn("--no-measurements", result.stdout)
        self.assertIn("--no-gates", result.stdout)
        self.assertIn("--truncate-values", result.stdout)

    def test_cli_profile_list(self) -> None:
        result = self._run("profile", "list")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"profile list exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        self.assertIn("PROFILE.", result.stdout)

    def test_cli_render_help(self) -> None:
        result = self._run("render", "--help")
        self.assertEqual(
            result.returncode,
            0,
            msg=f"render --help exited {result.returncode}.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        combined = result.stdout + result.stderr
        self.assertIn(
            "usage:",
            combined.lower(),
            msg=f"'usage:' not in render --help.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
