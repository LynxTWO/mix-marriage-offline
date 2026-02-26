from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mmo.core.plugin_loader import (
    PLUGIN_DIR_ENV_VAR,
    load_registered_plugins,
)
from mmo.core.plugin_registry import PluginRegistryError


def _write_renderer_plugin(
    *,
    root: Path,
    plugin_id: str,
    module_name: str,
    channel_mode: str = "per_channel",
) -> None:
    root.mkdir(parents=True, exist_ok=True)

    module_path = root / f"{module_name}.py"
    module_path.write_text(
        "\n".join(
            [
                "class TestRenderer:",
                "    def render(self, session, recommendations, output_dir=None):",
                "        return {}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manifests_dir = root / "renderers"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"{module_name}.plugin.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                f'plugin_id: "{plugin_id}"',
                'plugin_type: "renderer"',
                f'name: "{plugin_id} Renderer"',
                'version: "0.1.0"',
                f'entrypoint: "{module_name}:TestRenderer"',
                "capabilities:",
                "  max_channels: 2",
                f'  channel_mode: "{channel_mode}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestPluginLoader(unittest.TestCase):
    def test_loads_default_user_plugins_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home"
            user_plugins = home_root / ".mmo" / "plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_plugin_renderer",
            )
            _write_renderer_plugin(
                root=user_plugins,
                plugin_id="PLUGIN.RENDERER.USER_PLUGIN",
                module_name="user_plugin_renderer",
            )

            with patch.dict(
                os.environ,
                {"HOME": home_root.as_posix()},
                clear=False,
            ):
                os.environ.pop(PLUGIN_DIR_ENV_VAR, None)
                plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(
                plugin_ids,
                ["PLUGIN.RENDERER.BASE_PLUGIN", "PLUGIN.RENDERER.USER_PLUGIN"],
            )

    def test_plugin_dir_override_takes_precedence_over_default_user_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home"
            default_user_plugins = home_root / ".mmo" / "plugins"
            override_plugins = tmp_root / "override_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_override_renderer",
            )
            _write_renderer_plugin(
                root=default_user_plugins,
                plugin_id="PLUGIN.RENDERER.DEFAULT_USER_PLUGIN",
                module_name="default_user_renderer",
            )
            _write_renderer_plugin(
                root=override_plugins,
                plugin_id="PLUGIN.RENDERER.OVERRIDE_PLUGIN",
                module_name="override_renderer",
            )

            with patch.dict(
                os.environ,
                {"HOME": home_root.as_posix()},
                clear=False,
            ):
                os.environ.pop(PLUGIN_DIR_ENV_VAR, None)
                plugins = load_registered_plugins(
                    base_plugins,
                    plugin_dir=override_plugins,
                )

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(
                plugin_ids,
                ["PLUGIN.RENDERER.BASE_PLUGIN", "PLUGIN.RENDERER.OVERRIDE_PLUGIN"],
            )

    def test_env_plugin_dir_override_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            env_plugins = tmp_root / "env_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_env_renderer",
            )
            _write_renderer_plugin(
                root=env_plugins,
                plugin_id="PLUGIN.RENDERER.ENV_PLUGIN",
                module_name="env_renderer",
            )

            with patch.dict(
                os.environ,
                {PLUGIN_DIR_ENV_VAR: env_plugins.as_posix()},
                clear=False,
            ):
                plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(
                plugin_ids,
                ["PLUGIN.RENDERER.BASE_PLUGIN", "PLUGIN.RENDERER.ENV_PLUGIN"],
            )

    def test_invalid_external_semantics_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            external_plugins = tmp_root / "external_plugins"
            base_plugins.mkdir(parents=True, exist_ok=True)

            _write_renderer_plugin(
                root=external_plugins,
                plugin_id="PLUGIN.RENDERER.BAD_SEMANTICS",
                module_name="bad_semantics_renderer",
                channel_mode="definitely_not_valid",
            )

            with self.assertRaises(PluginRegistryError):
                load_registered_plugins(base_plugins, plugin_dir=external_plugins)

    def test_duplicate_plugin_ids_across_roots_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            external_plugins = tmp_root / "external_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.DUPLICATE_ID",
                module_name="duplicate_base_renderer",
            )
            _write_renderer_plugin(
                root=external_plugins,
                plugin_id="PLUGIN.RENDERER.DUPLICATE_ID",
                module_name="duplicate_external_renderer",
            )

            with self.assertRaises(ValueError):
                load_registered_plugins(base_plugins, plugin_dir=external_plugins)
