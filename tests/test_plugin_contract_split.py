from __future__ import annotations

import unittest
from pathlib import Path

from mmo.core.plugin_registry import validate_manifest

_SCHEMA_PATH = Path("schemas/plugin.schema.json")


class TestPluginContractSplit(unittest.TestCase):
    def test_detector_manifest_accepts_declares_emits_issue_ids(self) -> None:
        manifest = {
            "plugin_id": "PLUGIN.DETECTOR.MUD_TEST",
            "plugin_type": "detector",
            "name": "Mud Detector Test",
            "version": "0.1.0",
            "entrypoint": "mmo.plugins.detectors.mud_detector:MudDetector",
            "capabilities": {
                "max_channels": 32,
                "channel_mode": "linked_group",
                "supported_group_sizes": [1, 2],
                "supported_link_groups": ["front", "custom"],
                "scene_scope": "object_capable",
                "layout_safety": "layout_agnostic",
                "supported_contexts": ["suggest"],
            },
            "declares": {
                "problem_domains": ["spectral", "masking"],
                "emits_issue_ids": ["ISSUE.SPECTRAL.MUD"],
                "target_scopes": ["stem", "bus"],
            },
        }

        self.assertEqual(
            validate_manifest(manifest, schema_path=_SCHEMA_PATH),
            [],
        )

    def test_resolver_manifest_accepts_declares_consumes_and_suggests(self) -> None:
        manifest = {
            "plugin_id": "PLUGIN.RESOLVER.MUD_EQ_TEST",
            "plugin_type": "resolver",
            "name": "Mud EQ Resolver Test",
            "version": "0.1.0",
            "entrypoint": "mmo.plugins.resolvers.conservative_eq_resolver:ConservativeEqResolver",
            "capabilities": {
                "max_channels": 32,
                "channel_mode": "linked_group",
                "supported_group_sizes": [1, 2],
                "supported_link_groups": ["front", "custom"],
                "scene_scope": "object_capable",
                "layout_safety": "layout_agnostic",
                "supported_contexts": ["suggest", "auto_apply"],
            },
            "declares": {
                "problem_domains": ["spectral", "masking"],
                "consumes_issue_ids": ["ISSUE.SPECTRAL.MUD"],
                "suggests_action_ids": [
                    "ACTION.EQ.BROAD_CUT",
                    "ACTION.EQ.NOTCH",
                ],
                "target_scopes": ["stem", "bus"],
            },
            "behavior_contract": {
                "loudness_behavior": "preserve",
                "max_integrated_lufs_delta": 0.1,
                "peak_behavior": "bounded",
                "max_true_peak_delta_db": 0.1,
                "gain_compensation": "required",
            },
        }

        self.assertEqual(
            validate_manifest(manifest, schema_path=_SCHEMA_PATH),
            [],
        )

    def test_renderer_manifest_accepts_runtime_only_capabilities(self) -> None:
        manifest = {
            "plugin_id": "PLUGIN.RENDERER.PLACEMENT_TEST",
            "plugin_type": "renderer",
            "name": "Placement Renderer Test",
            "version": "0.1.0",
            "entrypoint": "mmo.plugins.renderers.placement_mixdown_renderer:PlacementMixdownRenderer",
            "capabilities": {
                "max_channels": 32,
                "channel_mode": "true_multichannel",
                "supported_group_sizes": [1, 2, 6, 8, 10, 12, 16, 32],
                "supported_link_groups": [
                    "front",
                    "surrounds",
                    "heights",
                    "all",
                    "custom",
                ],
                "requires_speaker_positions": True,
                "scene_scope": "object_capable",
                "layout_safety": "layout_specific",
                "supported_contexts": ["render"],
                "supported_layout_ids": ["LAYOUT.5_1", "LAYOUT.7_1_4"],
            },
            "declares": {
                "problem_domains": ["rendering", "translation"],
                "related_feature_ids": ["FEATURE.RENDER.SCENE_TO_LAYOUT"],
                "target_scopes": ["scene", "target_layout"],
            },
            "behavior_contract": {
                "loudness_behavior": "preserve",
                "max_integrated_lufs_delta": 0.1,
                "peak_behavior": "bounded",
                "max_true_peak_delta_db": 0.1,
                "phase_behavior": "translation_safe",
            },
        }

        self.assertEqual(
            validate_manifest(manifest, schema_path=_SCHEMA_PATH),
            [],
        )


if __name__ == "__main__":
    unittest.main()
