import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCliPluginMarketplace(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return subprocess.run(
            [self._python_cmd(), "-m", "mmo", *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
        )

    def test_plugin_market_list_json_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = (
            "plugin",
            "list",
            "--plugins",
            str(repo_root / "plugins"),
            "--index",
            str(repo_root / "ontology" / "plugin_index.yaml"),
            "--format",
            "json",
        )
        first = self._run(*command)
        second = self._run(*command)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertEqual(payload.get("schema_version"), "0.1.0")
        self.assertEqual(payload.get("market_id"), "MARKET.PLUGIN.OFFLINE.V0")
        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list):
            return

        safe = next(
            (
                item
                for item in entries
                if isinstance(item, dict)
                and item.get("plugin_id") == "PLUGIN.RENDERER.SAFE"
            ),
            None,
        )
        self.assertIsNotNone(safe)
        if not isinstance(safe, dict):
            return
        self.assertTrue(safe.get("installed"))
        self.assertEqual(safe.get("install_state"), "installed")

    def test_plugin_market_update_json_writes_snapshot(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "plugin_market" / "plugin_index.snapshot.json"
            command = (
                "plugin",
                "update",
                "--index",
                str(repo_root / "ontology" / "plugin_index.yaml"),
                "--out",
                str(out_path),
                "--format",
                "json",
            )
            first = self._run(*command)
            second = self._run(*command)

            self.assertEqual(first.returncode, 0, msg=first.stderr)
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertTrue(out_path.is_file())

            payload = json.loads(first.stdout)
            self.assertEqual(payload.get("schema_version"), "0.1.0")
            self.assertEqual(payload.get("market_id"), "MARKET.PLUGIN.OFFLINE.V0")
            self.assertEqual(payload.get("out_path"), out_path.resolve().as_posix())
            self.assertIsInstance(payload.get("sha256"), str)
            self.assertEqual(len(payload.get("sha256", "")), 64)

            snapshot_payload = json.loads(out_path.read_text(encoding="utf-8"))
            entries = snapshot_payload.get("entries")
            self.assertIsInstance(entries, list)
            if isinstance(entries, list):
                self.assertEqual(len(entries), payload.get("entry_count"))

    def test_plugin_market_install_json_is_deterministic_after_first_install(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            command = (
                "plugin",
                "install",
                "PLUGIN.RENDERER.GAIN_TRIM",
                "--plugins",
                str(plugins_dir),
                "--index",
                str(repo_root / "ontology" / "plugin_index.yaml"),
                "--format",
                "json",
            )
            first = self._run(*command)
            second = self._run(*command)

            self.assertEqual(first.returncode, 0, msg=first.stderr)
            self.assertEqual(second.returncode, 0, msg=second.stderr)

            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual(first_payload.get("plugin_id"), "PLUGIN.RENDERER.GAIN_TRIM")
            self.assertEqual(second_payload.get("plugin_id"), "PLUGIN.RENDERER.GAIN_TRIM")
            self.assertTrue(first_payload.get("changed"))
            self.assertFalse(second_payload.get("changed"))
            self.assertTrue(second_payload.get("already_installed"))

            self.assertTrue((plugins_dir / "renderers" / "gain_trim_renderer.plugin.yaml").is_file())
            self.assertTrue((plugins_dir / "renderers" / "gain_trim_renderer.py").is_file())


if __name__ == "__main__":
    unittest.main()
