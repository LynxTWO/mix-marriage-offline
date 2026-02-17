import json
import tempfile
import unittest
from pathlib import Path

from mmo.core.plugin_schema_index import build_plugins_config_schema_index


class TestPluginSchemaIndex(unittest.TestCase):
    def _layout_payload(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "layout_id": "LAYOUT.PLUGIN.SCHEMA_INDEX.TEST",
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
                            "widget_id": "widget.main.threshold",
                            "col_span": 12,
                            "row_span": 1,
                            "param_ref": "PARAM.RENDERER.THRESHOLD",
                        }
                    ],
                }
            ],
        }

    def _write_plugin(self, plugins_dir: Path) -> tuple[str, Path]:
        plugin_id = "PLUGIN.RENDERER.SCHEMA_INDEX_TEST"
        manifest_path = plugins_dir / "renderers" / "schema_index_test.plugin.yaml"
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
                    'name: "Schema Index Test Renderer"',
                    'version: "0.1.0"',
                    'license: "Apache-2.0"',
                    'description: "Renderer fixture for plugin schema index tests."',
                    'mmo_min_version: "0.1.0"',
                    'ontology_min_version: "0.1.0"',
                    'entrypoint: "plugins.renderers.safe_renderer:SafeRenderer"',
                    'ui_layout: "ui/layout.json"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return plugin_id, layout_path

    def test_index_defaults_remain_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            self._write_plugin(plugins_dir)

            payload = build_plugins_config_schema_index(
                plugins_dir=plugins_dir,
                include_schema=False,
            )

        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list) or not entries:
            return
        first = entries[0]
        self.assertIsInstance(first, dict)
        if not isinstance(first, dict):
            return
        self.assertIn("config_schema", first)
        self.assertNotIn("ui_layout", first)
        self.assertNotIn("ui_layout_snapshot", first)

    def test_index_with_layout_snapshot_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            plugin_id, layout_path = self._write_plugin(plugins_dir)
            expected_layout_path = layout_path.resolve().as_posix()

            first = build_plugins_config_schema_index(
                plugins_dir=plugins_dir,
                include_schema=False,
                include_ui_layout=True,
                include_ui_layout_snapshot=True,
            )
            second = build_plugins_config_schema_index(
                plugins_dir=plugins_dir,
                include_schema=False,
                include_ui_layout=True,
                include_ui_layout_snapshot=True,
            )

        bytes_first = json.dumps(first, indent=2, sort_keys=True).encode("utf-8")
        bytes_second = json.dumps(second, indent=2, sort_keys=True).encode("utf-8")
        self.assertEqual(bytes_first, bytes_second)

        entries = first.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list):
            return
        row = next(
            (
                item
                for item in entries
                if isinstance(item, dict) and item.get("plugin_id") == plugin_id
            ),
            None,
        )
        self.assertIsInstance(row, dict)
        if not isinstance(row, dict):
            return
        ui_layout = row.get("ui_layout")
        self.assertIsInstance(ui_layout, dict)
        if not isinstance(ui_layout, dict):
            return
        self.assertTrue(ui_layout.get("present"))
        self.assertEqual(ui_layout.get("path"), expected_layout_path)
        self.assertIsInstance(ui_layout.get("sha256"), str)
        self.assertEqual(len(ui_layout.get("sha256", "")), 64)

        snapshot = row.get("ui_layout_snapshot")
        self.assertIsInstance(snapshot, dict)
        if not isinstance(snapshot, dict):
            return
        self.assertTrue(snapshot.get("present"))
        self.assertEqual(snapshot.get("path"), expected_layout_path)
        self.assertIsInstance(snapshot.get("sha256"), str)
        self.assertEqual(len(snapshot.get("sha256", "")), 64)
        self.assertEqual(snapshot.get("violations_count"), 0)


if __name__ == "__main__":
    unittest.main()
