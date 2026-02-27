import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mmo.core.plugin_market import (
    build_plugin_market_list_payload,
    install_plugin_market_entry,
    load_plugin_market_index,
    update_plugin_market_snapshot,
)


class TestPluginMarket(unittest.TestCase):
    def test_load_plugin_market_index_is_sorted_and_contains_safe_renderer(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = load_plugin_market_index(repo_root / "ontology" / "plugin_index.yaml")

        self.assertEqual(payload.get("schema_version"), "0.1.0")
        self.assertEqual(payload.get("market_id"), "MARKET.PLUGIN.OFFLINE.V0")
        self.assertEqual(payload.get("install_asset_root"), "plugin_market/assets")
        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list):
            return

        plugin_ids = [
            item.get("plugin_id")
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("plugin_id"), str)
        ]
        self.assertEqual(plugin_ids, sorted(plugin_ids))
        self.assertIn("PLUGIN.RENDERER.SAFE", plugin_ids)

    def test_build_plugin_market_list_marks_repo_plugins_installed(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = build_plugin_market_list_payload(
            plugins_dir=repo_root / "plugins",
            index_path=repo_root / "ontology" / "plugin_index.yaml",
        )

        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list):
            return

        safe_entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict)
                and item.get("plugin_id") == "PLUGIN.RENDERER.SAFE"
            ),
            None,
        )
        self.assertIsNotNone(safe_entry)
        if not isinstance(safe_entry, dict):
            return
        self.assertTrue(safe_entry.get("installed"))
        self.assertEqual(safe_entry.get("install_state"), "installed")
        self.assertTrue(safe_entry.get("installable"))

    def test_update_plugin_market_snapshot_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "plugin_market" / "plugin_index.snapshot.json"

            first = update_plugin_market_snapshot(
                out_path=out_path,
                index_path=repo_root / "ontology" / "plugin_index.yaml",
            )
            second = update_plugin_market_snapshot(
                out_path=out_path,
                index_path=repo_root / "ontology" / "plugin_index.yaml",
            )

            self.assertEqual(first, second)
            self.assertTrue(out_path.is_file())
            snapshot_text = out_path.read_text(encoding="utf-8")
            self.assertTrue(snapshot_text.endswith("\n"))
            self.assertEqual(
                first.get("sha256"),
                hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest(),
            )

            snapshot_payload = json.loads(snapshot_text)
            self.assertEqual(snapshot_payload.get("schema_version"), "0.1.0")
            self.assertEqual(snapshot_payload.get("market_id"), "MARKET.PLUGIN.OFFLINE.V0")
            entries = snapshot_payload.get("entries")
            self.assertIsInstance(entries, list)
            if isinstance(entries, list):
                self.assertEqual(len(entries), first.get("entry_count"))

    def test_install_plugin_market_entry_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "plugins"

            first = install_plugin_market_entry(
                plugin_id="PLUGIN.RENDERER.SAFE",
                plugins_dir=install_root,
                index_path=repo_root / "ontology" / "plugin_index.yaml",
            )
            second = install_plugin_market_entry(
                plugin_id="PLUGIN.RENDERER.SAFE",
                plugins_dir=install_root,
                index_path=repo_root / "ontology" / "plugin_index.yaml",
            )

            self.assertEqual(first.get("plugin_id"), "PLUGIN.RENDERER.SAFE")
            self.assertTrue(first.get("changed"))
            self.assertFalse(first.get("already_installed"))
            self.assertEqual(second.get("plugin_id"), "PLUGIN.RENDERER.SAFE")
            self.assertFalse(second.get("changed"))
            self.assertTrue(second.get("already_installed"))

            manifest_path = install_root / "renderers" / "safe_renderer.plugin.yaml"
            module_path = install_root / "renderers" / "safe_renderer.py"
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(module_path.is_file())


if __name__ == "__main__":
    unittest.main()
