import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


class TestCliPluginsShow(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _write_temp_plugin(self, plugins_dir: Path) -> tuple[str, Path]:
        plugin_id = "PLUGIN.RENDERER.TEMP_FORM"
        manifest_path = plugins_dir / "renderers" / "temp_form.plugin.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            "\n".join(
                [
                    f'plugin_id: "{plugin_id}"',
                    'plugin_type: "renderer"',
                    'name: "Temp Form Renderer"',
                    'version: "0.1.0"',
                    'license: "Apache-2.0"',
                    'description: "Temporary renderer for plugins show tests."',
                    'mmo_min_version: "0.1.0"',
                    'ontology_min_version: "0.1.0"',
                    'entrypoint: "plugins.renderers.safe_renderer:SafeRenderer"',
                    "config_schema:",
                    '  "$schema": "https://json-schema.org/draft/2020-12/schema"',
                    '  "type": "object"',
                    '  "additionalProperties": false',
                    '  "properties":',
                    '    "gain_db":',
                    '      "type": "number"',
                    '      "minimum": -6',
                    '      "maximum": 6',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return plugin_id, manifest_path

    def _run_plugins_show(
        self,
        *,
        plugin_id: str,
        plugins_dir: Path,
        output_format: str,
    ) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "plugins",
                "show",
                plugin_id,
                "--plugins",
                str(plugins_dir),
                "--format",
                output_format,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
        )

    def test_plugins_show_json_includes_config_schema_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, manifest_path = self._write_temp_plugin(plugins_dir)
            expected_plugins_dir = plugins_dir.resolve().as_posix()
            expected_manifest_path = manifest_path.resolve().as_posix()

            first = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
            )
            second = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
            )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertEqual(payload.get("plugins_dir"), expected_plugins_dir)

        plugin = payload.get("plugin")
        self.assertIsInstance(plugin, dict)
        if not isinstance(plugin, dict):
            return
        self.assertEqual(plugin.get("plugin_id"), plugin_id)
        self.assertEqual(plugin.get("plugin_type"), "renderer")
        self.assertEqual(plugin.get("manifest_path"), expected_manifest_path)
        self.assertIsInstance(plugin.get("manifest_sha256"), str)

        config_schema = payload.get("config_schema")
        self.assertIsInstance(config_schema, dict)
        if not isinstance(config_schema, dict):
            return
        self.assertTrue(config_schema.get("present"))
        self.assertIsInstance(config_schema.get("sha256"), str)
        self.assertEqual(len(config_schema.get("sha256", "")), 64)

        pointer = config_schema.get("pointer")
        self.assertIsInstance(pointer, dict)
        if not isinstance(pointer, dict):
            return
        self.assertEqual(pointer.get("manifest_path"), expected_manifest_path)
        self.assertEqual(pointer.get("json_pointer"), "/config_schema")
        self.assertIsInstance(pointer.get("manifest_sha256"), str)
        self.assertEqual(len(pointer.get("manifest_sha256", "")), 64)

        schema_payload = config_schema.get("schema")
        self.assertIsInstance(schema_payload, dict)
        if isinstance(schema_payload, dict):
            jsonschema.Draft202012Validator.check_schema(schema_payload)

    def test_plugins_show_text_includes_schema_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, _ = self._write_temp_plugin(plugins_dir)

            result = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="text",
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"plugin_id: {plugin_id}", result.stdout)
        self.assertIn("config_schema.present: True", result.stdout)
        self.assertIn("config_schema.pointer:", result.stdout)
        self.assertIn("config_schema.sha256:", result.stdout)

    def test_plugins_show_unknown_plugin_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            self._write_temp_plugin(plugins_dir)

            result = self._run_plugins_show(
                plugin_id="PLUGIN.RENDERER.DOES_NOT_EXIST",
                plugins_dir=plugins_dir,
                output_format="json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Unknown plugin_id", result.stderr)


if __name__ == "__main__":
    unittest.main()
