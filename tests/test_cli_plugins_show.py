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

    def _layout_payload(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "layout_id": "LAYOUT.PLUGIN.RENDERER.TEMP_FORM",
            "grid": {
                "columns": 12,
                "gap_px": 16,
                "row_height_px": 48,
                "margin_px": 24,
            },
            "container": {"section_gap_px": 16},
            "sections": [
                {
                    "section_id": "main",
                    "widgets": [
                        {
                            "widget_id": "widget.main.gain_db",
                            "col_span": 6,
                            "row_span": 1,
                            "param_ref": "PARAM.RENDERER.GAIN_DB",
                        },
                        {
                            "widget_id": "widget.main.mode",
                            "col_span": 6,
                            "row_span": 1,
                            "param_ref": "PARAM.RENDERER.MODE",
                        },
                    ],
                }
            ],
        }

    def _write_temp_plugin(self, plugins_dir: Path) -> tuple[str, Path, Path]:
        plugin_id = "PLUGIN.RENDERER.TEMP_FORM"
        manifest_path = plugins_dir / "renderers" / "temp_form.plugin.yaml"
        layout_path = manifest_path.parent / "ui" / "layout.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.write_text(
            json.dumps(self._layout_payload(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
                    'entrypoint: "mmo.plugins.renderers.safe_renderer:SafeRenderer"',
                    'ui_layout: "ui/layout.json"',
                    "config_schema:",
                    '  "$schema": "https://json-schema.org/draft/2020-12/schema"',
                    '  "type": "object"',
                    '  "additionalProperties": false',
                    '  "properties":',
                    '    "gain_db":',
                    '      "type": "number"',
                    '      "minimum": -6',
                    '      "maximum": 6',
                    '      "x_mmo_ui":',
                    '        "widget": "fader"',
                    '        "units": "dB"',
                    '        "step": 0.5',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return plugin_id, manifest_path, layout_path

    def _run_plugins_show(
        self,
        *,
        plugin_id: str,
        plugins_dir: Path,
        output_format: str,
        include_ui_layout_snapshot: bool = False,
        include_ui_hints: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        args = [
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
        ]
        if include_ui_layout_snapshot:
            args.append("--include-ui-layout-snapshot")
        if include_ui_hints:
            args.append("--include-ui-hints")
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
        )

    def test_plugins_show_json_includes_config_schema_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, manifest_path, layout_path = self._write_temp_plugin(plugins_dir)
            expected_plugins_dir = plugins_dir.resolve().as_posix()
            expected_manifest_path = manifest_path.resolve().as_posix()
            expected_layout_path = layout_path.resolve().as_posix()

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

        ui_layout = payload.get("ui_layout")
        self.assertIsInstance(ui_layout, dict)
        if not isinstance(ui_layout, dict):
            return
        self.assertTrue(ui_layout.get("present"))
        self.assertEqual(ui_layout.get("path"), expected_layout_path)
        self.assertIsInstance(ui_layout.get("sha256"), str)
        self.assertEqual(len(ui_layout.get("sha256", "")), 64)
        self.assertNotIn("ui_layout_snapshot", payload)

    def test_plugins_show_json_can_include_ui_layout_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, _, layout_path = self._write_temp_plugin(plugins_dir)
            expected_layout_path = layout_path.resolve().as_posix()

            first = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
                include_ui_layout_snapshot=True,
            )
            second = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
                include_ui_layout_snapshot=True,
            )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        snapshot = payload.get("ui_layout_snapshot")
        self.assertIsInstance(snapshot, dict)
        if not isinstance(snapshot, dict):
            return
        self.assertTrue(snapshot.get("present"))
        self.assertEqual(snapshot.get("path"), expected_layout_path)
        self.assertIsInstance(snapshot.get("sha256"), str)
        self.assertEqual(len(snapshot.get("sha256", "")), 64)
        self.assertEqual(snapshot.get("violations_count"), 0)

    def test_plugins_show_json_can_include_ui_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, manifest_path, _ = self._write_temp_plugin(plugins_dir)
            expected_manifest_path = manifest_path.resolve().as_posix()

            first = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
                include_ui_hints=True,
            )
            second = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="json",
                include_ui_hints=True,
            )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        ui_hints = payload.get("ui_hints")
        self.assertIsInstance(ui_hints, dict)
        if not isinstance(ui_hints, dict):
            return
        self.assertTrue(ui_hints.get("present"))
        self.assertEqual(ui_hints.get("hint_count"), 1)
        self.assertIsInstance(ui_hints.get("sha256"), str)
        self.assertEqual(len(ui_hints.get("sha256", "")), 64)

        pointer = ui_hints.get("pointer")
        self.assertIsInstance(pointer, dict)
        if isinstance(pointer, dict):
            self.assertEqual(pointer.get("manifest_path"), expected_manifest_path)
            self.assertEqual(pointer.get("json_pointer"), "/config_schema")
            self.assertIsInstance(pointer.get("manifest_sha256"), str)
            self.assertEqual(len(pointer.get("manifest_sha256", "")), 64)

        hints = ui_hints.get("hints")
        self.assertIsInstance(hints, list)
        if not isinstance(hints, list) or not hints:
            return
        first_hint = hints[0]
        self.assertIsInstance(first_hint, dict)
        if not isinstance(first_hint, dict):
            return
        self.assertEqual(first_hint.get("json_pointer"), "/properties/gain_db/x_mmo_ui")

    def test_plugins_show_text_includes_schema_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, _, _ = self._write_temp_plugin(plugins_dir)

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
        self.assertIn("ui_layout.present: True", result.stdout)
        self.assertIn("ui_layout.path:", result.stdout)
        self.assertIn("ui_layout.sha256:", result.stdout)

    def test_plugins_show_text_can_include_ui_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, _, _ = self._write_temp_plugin(plugins_dir)

            result = self._run_plugins_show(
                plugin_id=plugin_id,
                plugins_dir=plugins_dir,
                output_format="text",
                include_ui_hints=True,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("ui_hints.present: True", result.stdout)
        self.assertIn("ui_hints.pointer:", result.stdout)
        self.assertIn("ui_hints.sha256:", result.stdout)
        self.assertIn("ui_hints.hint_count: 1", result.stdout)
        self.assertIn('"json_pointer": "/properties/gain_db/x_mmo_ui"', result.stdout)

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
