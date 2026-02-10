import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliLocks(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_locks_list_json_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "locks",
            "list",
            "--format",
            "json",
        ]

        first = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        second = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        lock_ids = [
            item.get("lock_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(lock_ids, sorted(lock_ids))
        self.assertIn("LOCK.PRESERVE_DYNAMICS", lock_ids)

    def test_locks_show_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "locks",
            "show",
            "LOCK.PRESERVE_DYNAMICS",
            "--format",
            "text",
        ]

        first = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        second = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("label: Preserve dynamics", first.stdout)
        self.assertIn("severity: hard", first.stdout)
        self.assertIn("applies_to: object, bed, scene", first.stdout)


if __name__ == "__main__":
    unittest.main()
