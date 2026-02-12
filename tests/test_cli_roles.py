import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliRoles(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_roles_list_json_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "roles",
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
        self.assertEqual(first.stderr, second.stderr)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        role_ids = [role_id for role_id in payload if isinstance(role_id, str)]
        self.assertEqual(role_ids, sorted(role_ids))
        self.assertIn("ROLE.BASS.AMP", role_ids)

    def test_roles_show_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "roles",
            "show",
            "ROLE.BASS.AMP",
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
        self.assertEqual(first.stderr, second.stderr)
        self.assertIn("ROLE.BASS.AMP", first.stdout)
        self.assertIn("label: Bass amp", first.stdout)
        self.assertIn("kind: source", first.stdout)


if __name__ == "__main__":
    unittest.main()
