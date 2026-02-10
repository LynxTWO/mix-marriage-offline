import tempfile
import unittest
from pathlib import Path

from mmo.core.pipeline import load_plugins
from tools.validate_plugins import (
    ISSUE_PLUGIN_CAPABILITIES_INVALID,
    ISSUE_PLUGIN_LAYOUT_ID_UNKNOWN,
    ISSUE_PLUGIN_SCHEMA_INVALID,
    ISSUE_PLUGIN_TARGET_ID_UNKNOWN,
    validate_plugins,
)


def _write_manifest(
    plugins_dir: Path,
    *,
    plugin_id: str,
    capabilities_block: str,
) -> None:
    manifest_path = plugins_dir / "renderers" / f"{plugin_id}.plugin.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "\n".join(
            [
                f'plugin_id: "{plugin_id}"',
                'plugin_type: "renderer"',
                'name: "Temp Renderer"',
                'version: "0.1.0"',
                'license: "Apache-2.0"',
                'description: "Temporary renderer manifest for validator tests."',
                'mmo_min_version: "0.1.0"',
                'ontology_min_version: "0.1.0"',
                'entrypoint: "plugins.renderers.safe_renderer:SafeRenderer"',
                "capabilities:",
                capabilities_block,
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestPluginCapabilities(unittest.TestCase):
    def test_renderer_plugins_declare_capabilities_metadata(self) -> None:
        plugins = load_plugins(Path("plugins"))
        by_id = {plugin.plugin_id: plugin for plugin in plugins}

        for plugin_id in ("PLUGIN.RENDERER.SAFE", "PLUGIN.RENDERER.GAIN_TRIM"):
            plugin = by_id.get(plugin_id)
            self.assertIsNotNone(plugin)
            if plugin is None:
                return

            capabilities = plugin.capabilities
            self.assertIsNotNone(capabilities)
            if capabilities is None:
                return

            self.assertEqual(capabilities.max_channels, 32)
            self.assertEqual(capabilities.supported_contexts, ("render", "auto_apply"))
            self.assertEqual(
                capabilities.notes,
                ("Deterministic gain/trim rendering; no boosts.",),
            )
            if plugin_id == "PLUGIN.RENDERER.SAFE":
                self.assertIsNotNone(capabilities.scene)
                if capabilities.scene is None:
                    return
                self.assertTrue(capabilities.scene.supports_objects)
                self.assertTrue(capabilities.scene.supports_beds)
                self.assertTrue(capabilities.scene.supports_locks)
                self.assertTrue(capabilities.scene.requires_speaker_positions)
                self.assertEqual(
                    capabilities.scene.supported_target_ids,
                    ("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
                )
            else:
                self.assertIsNone(capabilities.scene)

    def test_loader_attaches_capabilities_to_plugin_instance(self) -> None:
        plugins = load_plugins(Path("plugins"))
        safe_plugin = next(
            plugin for plugin in plugins if plugin.plugin_id == "PLUGIN.RENDERER.SAFE"
        )

        instance_capabilities = getattr(safe_plugin.instance, "plugin_capabilities", None)
        self.assertIsNotNone(instance_capabilities)
        self.assertIs(instance_capabilities, safe_plugin.capabilities)
        self.assertEqual(
            instance_capabilities.to_dict(),
            {
                "max_channels": 32,
                "notes": ["Deterministic gain/trim rendering; no boosts."],
                "scene": {
                    "requires_speaker_positions": True,
                    "supported_target_ids": [
                        "TARGET.STEREO.2_0",
                        "TARGET.SURROUND.5_1",
                    ],
                    "supports_beds": True,
                    "supports_locks": True,
                    "supports_objects": True,
                },
                "supported_contexts": ["render", "auto_apply"],
            },
        )

    def test_validate_plugins_accepts_scene_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_SCENE_OK",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 8",
                        "  scene:",
                        "    supports_objects: true",
                        "    supports_beds: true",
                        "    supports_locks: true",
                        "    requires_speaker_positions: true",
                        "    supported_target_ids:",
                        '      - "TARGET.STEREO.2_0"',
                    ]
                ),
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertTrue(result["ok"], msg=result)

    def test_validate_plugins_rejects_unknown_supported_layout_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_INVALID_LAYOUT",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        "  supported_layout_ids:",
                        '    - "LAYOUT.NOT_REAL"',
                        "  supported_contexts:",
                        '    - "render"',
                    ]
                ),
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        issue_ids = [
            issue.get("issue_id")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertIn(ISSUE_PLUGIN_LAYOUT_ID_UNKNOWN, issue_ids)

    def test_validate_plugins_rejects_invalid_supported_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_INVALID_CONTEXT",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        "  supported_contexts:",
                        '    - "render"',
                        '    - "ship_it"',
                    ]
                ),
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        issue_ids = [
            issue.get("issue_id")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertTrue(
            ISSUE_PLUGIN_CAPABILITIES_INVALID in issue_ids
            or ISSUE_PLUGIN_SCHEMA_INVALID in issue_ids
        )

    def test_validate_plugins_rejects_unknown_supported_target_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_INVALID_TARGET",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 8",
                        "  scene:",
                        "    supports_objects: true",
                        "    requires_speaker_positions: true",
                        "    supported_target_ids:",
                        '      - "TARGET.NOT_REAL"',
                    ]
                ),
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        issue_ids = [
            issue.get("issue_id")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertIn(ISSUE_PLUGIN_TARGET_ID_UNKNOWN, issue_ids)


if __name__ == "__main__":
    unittest.main()
