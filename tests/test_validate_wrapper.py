import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestValidateWrapper(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _wrapper_script(self) -> Path:
        return self._repo_root() / "tools" / "validate.py"

    def test_validate_wrapper_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._wrapper_script()), "--quiet"],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("validation passed", result.stderr.lower())

    def test_validate_wrapper_forwards_nonzero_exit_code(self) -> None:
        missing_root = self._repo_root() / "__missing_repo_root__"
        result = subprocess.run(
            [
                self._python_cmd(),
                os.fspath(self._wrapper_script()),
                "--repo-root",
                os.fspath(missing_root),
                "--quiet",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validation failed", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
