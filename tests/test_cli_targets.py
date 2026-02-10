import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliTargets(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_targets_list_json_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "targets",
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
        target_ids = [
            item.get("target_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("target_id"), str)
        ]
        self.assertEqual(target_ids, sorted(target_ids))
        self.assertIn("TARGET.STEREO.2_0", target_ids)

    def test_targets_show_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "targets",
            "show",
            "TARGET.STEREO.2_0",
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
        self.assertIn("label: Stereo", first.stdout)
        self.assertIn("layout_id: LAYOUT.2_0", first.stdout)
        self.assertIn("downmix_policy_id:", first.stdout)
        self.assertIn("safety_policy_id:", first.stdout)
        self.assertIn("notes:", first.stdout)


if __name__ == "__main__":
    unittest.main()
