import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliGates(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_gates_list_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "gates",
            "list",
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
        self.assertIn("POLICY.GATES.CORE_V0", first.stdout)

    def test_gates_list_json_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "gates",
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
        self.assertEqual(payload, sorted(payload))
        self.assertIn("POLICY.GATES.CORE_V0", payload)

    def test_gates_show_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "gates",
            "show",
            "POLICY.GATES.CORE_V0",
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
        self.assertIn("POLICY.GATES.CORE_V0", first.stdout)
        self.assertIn("GATE.NO_CLIP", first.stdout)

    def test_gates_show_json_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "gates",
            "show",
            "POLICY.GATES.CORE_V0",
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
        # JSON byte identity
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["policy_id"], "POLICY.GATES.CORE_V0")
        self.assertIn("gates", payload)
        self.assertIn("GATE.NO_CLIP", payload["gates"])

    def test_gates_show_unknown_id_error_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "gates",
            "show",
            "POLICY.GATES.NONEXISTENT",
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
        self.assertNotEqual(first.returncode, 0)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(first.stderr, second.stderr)
        self.assertIn("Unknown policy_id: POLICY.GATES.NONEXISTENT", first.stderr)
        self.assertIn("Known policy_ids: POLICY.GATES.CORE_V0", first.stderr)


if __name__ == "__main__":
    unittest.main()
