import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliDownmixList(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _run_list_json(self) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "downmix",
                "list",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_downmix_list_deterministic(self) -> None:
        first = self._run_list_json()
        second = self._run_list_json()
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        layouts = payload.get("layouts", [])
        layout_ids = {
            row.get("id")
            for row in layouts
            if isinstance(row, dict)
        }
        self.assertIn("LAYOUT.2_0", layout_ids)
        self.assertIn("LAYOUT.5_1", layout_ids)


if __name__ == "__main__":
    unittest.main()
