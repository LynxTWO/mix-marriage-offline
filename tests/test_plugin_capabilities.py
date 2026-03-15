import tempfile
import unittest
from pathlib import Path

from mmo.core.pipeline import load_plugins
from tools.validate_plugins import (
    ISSUE_PLUGIN_CAPABILITIES_INVALID,
    ISSUE_PLUGIN_DSP_TRAITS_INVALID,
    ISSUE_PLUGIN_DSP_TRAITS_REQUIRED,
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
    inject_safety_defaults: bool = True,
) -> None:
    capability_lines = capabilities_block.splitlines()
    if inject_safety_defaults and not any("scene_scope:" in line for line in capability_lines):
        capability_lines = ['  scene_scope: "object_capable"', *capability_lines]
    if inject_safety_defaults and not any("layout_safety:" in line for line in capability_lines):
        capability_lines = ['  layout_safety: "layout_agnostic"', *capability_lines]
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
                'entrypoint: "mmo.plugins.renderers.safe_renderer:SafeRenderer"',
                "capabilities:",
                *capability_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestPluginCapabilities(unittest.TestCase):
    def test_renderer_plugins_declare_capabilities_metadata(self) -> None:
        plugins = load_plugins(Path("plugins"))
        by_id = {plugin.plugin_id: plugin for plugin in plugins}

        for plugin_id in (
            "PLUGIN.RENDERER.SAFE",
            "PLUGIN.RENDERER.GAIN_TRIM",
            "PLUGIN.RENDERER.MIXDOWN_BASELINE",
            "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1",
        ):
            plugin = by_id.get(plugin_id)
            self.assertIsNotNone(plugin)
            if plugin is None:
                return

            capabilities = plugin.capabilities
            self.assertIsNotNone(capabilities)
            if capabilities is None:
                return

            expected_max_channels = 16 if plugin_id == "PLUGIN.RENDERER.MIXDOWN_BASELINE" else 32
            self.assertEqual(capabilities.max_channels, expected_max_channels)
            if plugin_id == "PLUGIN.RENDERER.MIXDOWN_BASELINE":
                self.assertEqual(capabilities.scene_scope, "bed_only")
                self.assertEqual(capabilities.layout_safety, "layout_specific")
                self.assertTrue(capabilities.bed_only)
            elif plugin_id == "PLUGIN.RENDERER.GAIN_TRIM":
                self.assertEqual(capabilities.scene_scope, "object_capable")
                self.assertEqual(capabilities.layout_safety, "layout_agnostic")
            else:
                self.assertEqual(capabilities.scene_scope, "object_capable")
                self.assertEqual(capabilities.layout_safety, "layout_specific")
            self.assertEqual(capabilities.deterministic_seed_policy, "none")
            self.assertIsNotNone(capabilities.purity)
            if capabilities.purity is None:
                return
            self.assertEqual(capabilities.purity.audio_buffer, "typed_f64_interleaved")
            self.assertEqual(capabilities.purity.randomness, "forbidden")
            self.assertEqual(capabilities.purity.wall_clock, "forbidden")
            self.assertEqual(capabilities.purity.thread_scheduling, "forbidden")
            self.assertEqual(capabilities.supported_contexts, ("render", "auto_apply"))
            if plugin_id == "PLUGIN.RENDERER.MIXDOWN_BASELINE":
                self.assertEqual(
                    capabilities.notes,
                    ("Always writes a baseline master for supported target layouts.",),
                )
            else:
                if plugin_id == "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1":
                    self.assertEqual(
                        capabilities.notes,
                        (
                            "Scene-driven deterministic placement mixdown with conservative surround and height sends.",
                        ),
                    )
                else:
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
            elif plugin_id == "PLUGIN.RENDERER.MIXDOWN_BASELINE":
                self.assertIsNotNone(capabilities.scene)
                if capabilities.scene is None:
                    return
                self.assertFalse(capabilities.scene.supports_objects)
                self.assertTrue(capabilities.scene.supports_beds)
                self.assertTrue(capabilities.scene.supports_locks)
                self.assertFalse(capabilities.scene.requires_speaker_positions)
                self.assertEqual(
                    capabilities.scene.supported_target_ids,
                    (
                        "TARGET.STEREO.2_0",
                        "TARGET.SURROUND.5_1",
                        "TARGET.SURROUND.7_1",
                        "TARGET.IMMERSIVE.7_1_4",
                        "TARGET.IMMERSIVE.9_1_6",
                    ),
                )
            elif plugin_id == "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1":
                self.assertIsNotNone(capabilities.scene)
                if capabilities.scene is None:
                    return
                self.assertTrue(capabilities.scene.supports_objects)
                self.assertTrue(capabilities.scene.supports_beds)
                self.assertTrue(capabilities.scene.supports_locks)
                self.assertTrue(capabilities.scene.requires_speaker_positions)
                self.assertEqual(
                    capabilities.scene.supported_target_ids,
                    (
                        "TARGET.STEREO.2_0",
                        "TARGET.SURROUND.5_1",
                        "TARGET.SURROUND.7_1",
                        "TARGET.IMMERSIVE.7_1_4",
                        "TARGET.IMMERSIVE.9_1_6",
                    ),
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
                "deterministic_seed_policy": "none",
                "layout_safety": "layout_specific",
                "max_channels": 32,
                "notes": ["Deterministic gain/trim rendering; no boosts."],
                "purity": {
                    "audio_buffer": "typed_f64_interleaved",
                    "randomness": "forbidden",
                    "thread_scheduling": "forbidden",
                    "wall_clock": "forbidden",
                },
                "scene_scope": "object_capable",
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
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
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

    def test_validate_plugins_rejects_missing_scene_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_MISSING_SCENE_SCOPE",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  layout_safety: "layout_agnostic"',
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
                    ]
                ),
                inject_safety_defaults=False,
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        messages = [
            issue.get("message", "")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertTrue(
            any("capabilities.scene_scope must explicitly declare" in message for message in messages),
            msg=messages,
        )

    def test_validate_plugins_rejects_layout_specific_without_declared_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_LAYOUT_SPECIFIC_NO_SUPPORT",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  scene_scope: "object_capable"',
                        '  layout_safety: "layout_specific"',
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
                    ]
                ),
                inject_safety_defaults=False,
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        messages = [
            issue.get("message", "")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertTrue(
            any("capabilities.layout_safety='layout_specific' requires either" in message for message in messages),
            msg=messages,
        )

    def test_validate_plugins_rejects_purity_seed_policy_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_PURITY_CONFLICT",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  deterministic_seed_policy: "none"',
                        "  purity:",
                        '    audio_buffer: "typed_f64_interleaved"',
                        '    randomness: "process_context_seed"',
                        '    wall_clock: "forbidden"',
                        '    thread_scheduling: "forbidden"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
                    ]
                ),
            )

            result = validate_plugins(plugins_dir, Path("schemas/plugin.schema.json"))

        self.assertFalse(result["ok"])
        messages = [
            issue.get("message", "")
            for issue in result.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertTrue(
            any("purity.randomness='process_context_seed'" in message for message in messages),
            msg=messages,
        )

    def test_validate_plugins_rejects_unknown_supported_layout_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_INVALID_LAYOUT",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
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
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
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
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "information_preserving"',
                        '    linearity: "linear"',
                        '    phase_behavior: "linear_phase"',
                        "    adds_noise: false",
                        "    introduces_harmonics: false",
                        '    anti_aliasing: "na"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 0.2",
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

    def test_validate_plugins_rejects_nonlinear_without_anti_aliasing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_NONLINEAR_NO_AA",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  deterministic_seed_policy: "none"',
                        "  dsp_traits:",
                        '    tier: "controlled_nonlinear"',
                        '    linearity: "nonlinear"',
                        '    phase_behavior: "mixed"',
                        "    adds_noise: false",
                        "    introduces_harmonics: true",
                        '    anti_aliasing: "none"',
                        "    measurable_claims:",
                        '      - metric_id: "METER.TRUE_PEAK_DBTP"',
                        '        expected_direction: "within"',
                        "        threshold: 1.0",
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
        self.assertIn(ISSUE_PLUGIN_DSP_TRAITS_INVALID, issue_ids)

    def test_validate_plugins_rejects_renderer_without_dsp_traits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir)
            _write_manifest(
                plugins_dir,
                plugin_id="PLUGIN.RENDERER.TEMP_MISSING_DSP_TRAITS",
                capabilities_block="\n".join(
                    [
                        "  max_channels: 2",
                        '  deterministic_seed_policy: "none"',
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
        self.assertIn(ISSUE_PLUGIN_DSP_TRAITS_REQUIRED, issue_ids)


if __name__ == "__main__":
    unittest.main()
