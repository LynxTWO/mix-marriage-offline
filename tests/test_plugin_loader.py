from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mmo.core.plugin_loader import (
    PLUGIN_DIR_ENV_VAR,
    default_user_plugins_dir,
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
                '  scene_scope: "object_capable"',
                '  layout_safety: "layout_agnostic"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _minimal_env(tmp_root: Path, home_root: Path) -> dict[str, str]:
    """Minimal env dict for deterministic default_user_plugins_dir() resolution.

    On Windows set LOCALAPPDATA so the conventional dir lands inside tmp_root.
    On other platforms set HOME so XDG / Library paths land inside home_root.
    """
    if sys.platform == "win32":
        return {"LOCALAPPDATA": str(tmp_root / "localappdata")}
    return {"HOME": home_root.as_posix()}


class TestPluginLoader(unittest.TestCase):
    def test_loads_default_user_plugins_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_plugin_renderer",
            )

            env = _minimal_env(tmp_root, home_root)
            with patch.dict(os.environ, env, clear=True):
                user_plugins = default_user_plugins_dir()
                _write_renderer_plugin(
                    root=user_plugins,
                    plugin_id="PLUGIN.RENDERER.USER_PLUGIN",
                    module_name="user_plugin_renderer",
                )
                plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(
                plugin_ids,
                ["PLUGIN.RENDERER.BASE_PLUGIN", "PLUGIN.RENDERER.USER_PLUGIN"],
            )

    def test_empty_env_plugin_dir_falls_back_to_default_user_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_plugin_renderer",
            )

            env = {PLUGIN_DIR_ENV_VAR: "", **_minimal_env(tmp_root, home_root)}
            with patch.dict(os.environ, env, clear=True):
                user_plugins = default_user_plugins_dir()
                _write_renderer_plugin(
                    root=user_plugins,
                    plugin_id="PLUGIN.RENDERER.USER_PLUGIN",
                    module_name="user_plugin_renderer",
                )
                plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(
                plugin_ids,
                ["PLUGIN.RENDERER.BASE_PLUGIN", "PLUGIN.RENDERER.USER_PLUGIN"],
            )

    def test_missing_default_user_plugins_dir_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home_without_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_plugin_renderer",
            )

            env = _minimal_env(tmp_root / "empty_home", home_root)
            with patch.dict(os.environ, env, clear=True):
                plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(plugin_ids, ["PLUGIN.RENDERER.BASE_PLUGIN"])

    def test_plugin_dir_override_takes_precedence_over_default_user_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home"
            override_plugins = tmp_root / "override_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_override_renderer",
            )
            _write_renderer_plugin(
                root=override_plugins,
                plugin_id="PLUGIN.RENDERER.OVERRIDE_PLUGIN",
                module_name="override_renderer",
            )

            env = _minimal_env(tmp_root, home_root)
            with patch.dict(os.environ, env, clear=True):
                # Write a user plugin into the OS-conventional default dir so we can
                # verify it is NOT loaded when an explicit override is active.
                default_user_plugins = default_user_plugins_dir()
                _write_renderer_plugin(
                    root=default_user_plugins,
                    plugin_id="PLUGIN.RENDERER.DEFAULT_USER_PLUGIN",
                    module_name="default_user_renderer",
                )
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
                clear=True,
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

    def test_packaged_plugins_are_used_when_other_roots_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            missing_primary = tmp_root / "missing_primary"
            home_root = tmp_root / "home_without_plugins"
            packaged_plugins = tmp_root / "packaged_plugins"

            _write_renderer_plugin(
                root=packaged_plugins,
                plugin_id="PLUGIN.RENDERER.PACKAGED_PLUGIN",
                module_name="packaged_plugin_renderer",
            )

            env = {PLUGIN_DIR_ENV_VAR: "", **_minimal_env(tmp_root / "empty_home", home_root)}
            with patch.dict(os.environ, env, clear=True):
                with patch(
                    "mmo.core.plugin_loader.packaged_plugins_dir",
                    return_value=packaged_plugins.resolve(),
                ):
                    plugins = load_registered_plugins(missing_primary)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(plugin_ids, ["PLUGIN.RENDERER.PACKAGED_PLUGIN"])

    def test_packaged_plugins_are_fallback_only_when_primary_has_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            base_plugins = tmp_root / "base_plugins"
            home_root = tmp_root / "home_without_plugins"
            packaged_plugins = tmp_root / "packaged_plugins"

            _write_renderer_plugin(
                root=base_plugins,
                plugin_id="PLUGIN.RENDERER.BASE_PLUGIN",
                module_name="base_plugin_renderer",
            )
            _write_renderer_plugin(
                root=packaged_plugins,
                plugin_id="PLUGIN.RENDERER.PACKAGED_PLUGIN",
                module_name="packaged_plugin_renderer",
            )

            env = {PLUGIN_DIR_ENV_VAR: "", **_minimal_env(tmp_root / "empty_home", home_root)}
            with patch.dict(os.environ, env, clear=True):
                with patch(
                    "mmo.core.plugin_loader.packaged_plugins_dir",
                    return_value=packaged_plugins.resolve(),
                ):
                    plugins = load_registered_plugins(base_plugins)

            plugin_ids = [entry.plugin_id for entry in plugins]
            self.assertEqual(plugin_ids, ["PLUGIN.RENDERER.BASE_PLUGIN"])


class TestDefaultUserPluginsDir(unittest.TestCase):
    """Platform-path logic for default_user_plugins_dir()."""

    def _call_as_platform(self, platform: str, env: dict[str, str]) -> Path:
        """Invoke default_user_plugins_dir() with a patched sys.platform and env.

        Uses only the provided env (clear=True) so runner env vars cannot leak in.
        """
        with (
            patch("sys.platform", platform),
            patch.dict(os.environ, env, clear=True),
        ):
            return default_user_plugins_dir()

    def test_windows_uses_localappdata(self) -> None:
        path = self._call_as_platform(
            "win32",
            {"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"},
        )
        self.assertTrue(
            str(path).startswith("C:\\Users\\test\\AppData\\Local"),
            msg=f"Expected LOCALAPPDATA root, got: {path}",
        )
        self.assertTrue(str(path).endswith(os.path.join("mmo", "plugins")))

    def test_windows_falls_back_to_appdata_when_localappdata_absent(self) -> None:
        path = self._call_as_platform(
            "win32",
            {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"},
        )
        self.assertTrue(
            str(path).startswith("C:\\Users\\test\\AppData\\Roaming"),
            msg=f"Expected APPDATA root, got: {path}",
        )

    def test_windows_never_resolves_to_system32(self) -> None:
        path = self._call_as_platform(
            "win32",
            {"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"},
        )
        self.assertNotIn("System32", str(path))
        self.assertNotIn("system32", str(path).lower())

    def test_macos_uses_library_application_support(self) -> None:
        path = self._call_as_platform(
            "darwin",
            {"HOME": "/Users/test"},
        )
        self.assertIn("Library", str(path))
        self.assertIn("Application Support", str(path))
        self.assertTrue(str(path).endswith(os.path.join("mmo", "plugins")))

    def test_linux_uses_xdg_data_home_when_set(self) -> None:
        env = {"XDG_DATA_HOME": "/custom/xdg", "HOME": "/home/test"}
        path = self._call_as_platform("linux", env)
        expected = Path(env["XDG_DATA_HOME"]) / "mmo" / "plugins"
        self.assertEqual(path, expected)
        self.assertTrue(str(path).endswith(os.path.join("mmo", "plugins")))

    def test_linux_falls_back_to_local_share_without_xdg(self) -> None:
        path = self._call_as_platform(
            "linux",
            {"HOME": "/home/test"},
        )
        self.assertIn(".local", str(path))
        self.assertIn("share", str(path))
        self.assertTrue(str(path).endswith(os.path.join("mmo", "plugins")))
