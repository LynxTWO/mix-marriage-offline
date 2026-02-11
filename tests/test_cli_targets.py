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

    def test_targets_show_accepts_alias_and_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        alias_command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "targets",
            "show",
            "  stereo   (streaming) ",
            "--format",
            "text",
        ]
        canonical_command = [
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
            alias_command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        second = subprocess.run(
            alias_command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        canonical = subprocess.run(
            canonical_command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(canonical.returncode, 0, msg=canonical.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stdout, canonical.stdout)
        self.assertTrue(first.stdout.startswith("TARGET.STEREO.2_0\n"))

    def test_targets_list_long_text_includes_aliases_and_notes(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "targets",
            "list",
            "--long",
            "--format",
            "text",
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("aliases: Stereo (streaming), Stereo (everyday)", result.stdout)
        self.assertIn("notes:", result.stdout)


if __name__ == "__main__":
    unittest.main()
