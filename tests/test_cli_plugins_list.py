import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestCliPluginsList(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _run_plugins_list(self, output_format: str) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "plugins",
                "list",
                "--format",
                output_format,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_plugins_list_json_includes_capabilities(self) -> None:
        result = self._run_plugins_list("json")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertIn("plugins", payload)
        plugins = payload.get("plugins", [])
        self.assertIsInstance(plugins, list)

        safe_plugin = next(
            (
                plugin
                for plugin in plugins
                if isinstance(plugin, dict)
                and plugin.get("plugin_id") == "PLUGIN.RENDERER.SAFE"
            ),
            None,
        )
        self.assertIsNotNone(safe_plugin)
        if safe_plugin is None:
            return

        capabilities = safe_plugin.get("capabilities")
        self.assertIsInstance(capabilities, dict)
        if not isinstance(capabilities, dict):
            return

        self.assertEqual(capabilities.get("max_channels"), 32)
        self.assertEqual(
            capabilities.get("supported_contexts"),
            ["render", "auto_apply"],
        )

    def test_plugins_list_text_shows_max_channels_and_contexts(self) -> None:
        result = self._run_plugins_list("text")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "PLUGIN.RENDERER.SAFE (max_channels=32) contexts=render,auto_apply",
            result.stdout,
        )
        self.assertIn(
            "PLUGIN.RENDERER.GAIN_TRIM (max_channels=32) contexts=render,auto_apply",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
