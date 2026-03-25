from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from mmo.core.pipeline import PluginEntry, run_renderers
from mmo.dsp.buffer import AudioBufferF64
from mmo.dsp.plugin_mode_runner import (
    PluginModeRunError,
    run_plugin_mode,
    validate_plugin_session_compatibility,
)
from mmo.dsp.process_context import build_process_context
from mmo.plugins.interfaces import PluginCapabilities


class _ExplodingRenderer:
    def __init__(self) -> None:
        self.called = False

    def render(self, session, recommendations, output_dir=None):  # type: ignore[no-untyped-def]
        self.called = True
        raise AssertionError("renderer should not run for unsupported topology")


class _RecordingRenderer:
    def __init__(self) -> None:
        self.called = False

    def render(self, session, recommendations, output_dir=None):  # type: ignore[no-untyped-def]
        self.called = True
        return {"outputs": [], "notes": "rendered"}


class _LinkedGroupProcessor:
    def process_linked_group(  # type: ignore[no-untyped-def]
        self,
        audio_buffer,
        sample_rate_hz,
        params,
        *,
        group_name,
        channel_ids,
        process_ctx,
    ):
        return audio_buffer, {
            "group_name": group_name,
            "channel_ids": list(channel_ids),
            "touched": False,
        }


class _TrueMultichannelProcessor:
    def process_true_multichannel(  # type: ignore[no-untyped-def]
        self,
        audio_buffer,
        sample_rate_hz,
        params,
        *,
        process_ctx,
    ):
        return audio_buffer, {
            "channel_ids_seen": list(audio_buffer.channel_order),
            "buffer_type": type(audio_buffer).__name__,
        }


def _linked_group_entry(*, instance: object) -> PluginEntry:
    manifest = {
        "plugin_id": "PLUGIN.RENDERER.STEREO_LINKED_TEST",
        "plugin_type": "renderer",
        "name": "Stereo Linked Test",
        "version": "0.1.0",
        "entrypoint": "test:StereoLinked",
        "capabilities": {
            "max_channels": 32,
            "channel_mode": "linked_group",
            "supported_group_sizes": [1, 2],
            "supported_link_groups": ["front", "custom"],
            "scene_scope": "object_capable",
            "layout_safety": "layout_agnostic",
            "supported_contexts": ["render", "auto_apply"],
        },
    }
    return PluginEntry(
        plugin_id="PLUGIN.RENDERER.STEREO_LINKED_TEST",
        plugin_type="renderer",
        version="0.1.0",
        capabilities=PluginCapabilities(
            max_channels=32,
            channel_mode="linked_group",
            supported_group_sizes=(1, 2),
            supported_link_groups=("front", "custom"),
            scene_scope="object_capable",
            layout_safety="layout_agnostic",
            supported_contexts=("render", "auto_apply"),
        ),
        instance=instance,
        manifest_path=Path("plugins/renderers/stereo_linked_test.plugin.yaml"),
        manifest=manifest,
    )


def _true_multichannel_entry(*, instance: object) -> PluginEntry:
    manifest = {
        "plugin_id": "PLUGIN.RENDERER.TRUE_MULTICHANNEL_TEST",
        "plugin_type": "renderer",
        "name": "True Multichannel Test",
        "version": "0.1.0",
        "entrypoint": "test:TrueMultichannel",
        "capabilities": {
            "max_channels": 32,
            "channel_mode": "true_multichannel",
            "supported_group_sizes": [32],
            "supported_link_groups": ["all", "custom"],
            "requires_speaker_positions": True,
            "scene_scope": "object_capable",
            "layout_safety": "layout_agnostic",
            "supported_contexts": ["render"],
        },
    }
    return PluginEntry(
        plugin_id="PLUGIN.RENDERER.TRUE_MULTICHANNEL_TEST",
        plugin_type="renderer",
        version="0.1.0",
        capabilities=PluginCapabilities(
            max_channels=32,
            channel_mode="true_multichannel",
            supported_group_sizes=(32,),
            supported_link_groups=("all", "custom"),
            requires_speaker_positions=True,
            scene_scope="object_capable",
            layout_safety="layout_agnostic",
            supported_contexts=("render",),
        ),
        instance=instance,
        manifest_path=Path("plugins/renderers/true_multichannel_test.plugin.yaml"),
        manifest=manifest,
    )


class TestPluginRuntimeTopology(unittest.TestCase):
    def test_stereo_linked_plugin_is_session_compatible_in_32_channel_session(self) -> None:
        plugin_entry = _linked_group_entry(instance=_LinkedGroupProcessor())
        process_ctx = build_process_context("LAYOUT.32CH", seed=17)

        validate_plugin_session_compatibility(plugin_entry, process_ctx)

    def test_host_rejects_stereo_linked_plugin_as_single_32_channel_instance(self) -> None:
        renderer = _ExplodingRenderer()
        plugin_entry = _linked_group_entry(instance=renderer)
        report = {
            "session": {
                "stems": [
                    {
                        "stem_id": "wide_bed",
                        "file_path": "wide_bed.wav",
                        "channel_count": 32,
                    }
                ]
            },
            "recommendations": [
                {
                    "recommendation_id": "REC.TOPOLOGY.001",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "wide_bed"},
                }
            ],
        }

        manifests = run_renderers(report, [plugin_entry])

        self.assertFalse(renderer.called)
        self.assertEqual(len(manifests), 1)
        skipped = manifests[0].get("skipped")
        self.assertIsInstance(skipped, list)
        if not isinstance(skipped, list):
            return
        self.assertEqual(skipped[0].get("reason"), "plugin_topology_unsupported")
        details = skipped[0].get("details")
        self.assertIsInstance(details, dict)
        if not isinstance(details, dict):
            return
        self.assertEqual(details.get("required_channels"), 32)
        self.assertEqual(details.get("channel_mode"), "linked_group")
        self.assertEqual(details.get("supported_group_sizes"), [1, 2])

    def test_true_multichannel_plugin_is_accepted_for_lawful_32_channel_target(self) -> None:
        plugin_entry = _true_multichannel_entry(instance=_TrueMultichannelProcessor())
        process_ctx = build_process_context("LAYOUT.32CH", seed=23)
        source = np.zeros((process_ctx.num_channels, 8), dtype=np.float64)

        result = run_plugin_mode(plugin_entry, source, process_ctx)

        np.testing.assert_array_equal(result.rendered, source)
        self.assertEqual(result.evidence["channel_mode"], "true_multichannel")
        self.assertEqual(result.evidence["buffer_type"], AudioBufferF64.__name__)
        self.assertEqual(result.evidence["channel_ids_seen"], list(process_ctx.channel_order))

    def test_unsupported_group_size_is_rejected_deterministically(self) -> None:
        plugin_entry = _linked_group_entry(instance=_LinkedGroupProcessor())
        process_ctx = build_process_context("LAYOUT.5_1", seed=29)
        source = np.zeros((process_ctx.num_channels, 8), dtype=np.float64)

        with self.assertRaisesRegex(
            PluginModeRunError,
            "group size 3 is not declared",
        ):
            run_plugin_mode(
                plugin_entry,
                source,
                process_ctx,
                params={"group_name": "front"},
            )

    def test_unsupported_link_group_is_rejected_deterministically(self) -> None:
        plugin_entry = _linked_group_entry(instance=_LinkedGroupProcessor())
        process_ctx = build_process_context("LAYOUT.5_1", seed=31)
        source = np.zeros((process_ctx.num_channels, 8), dtype=np.float64)

        with self.assertRaisesRegex(
            PluginModeRunError,
            "supported_link_groups",
        ):
            run_plugin_mode(
                plugin_entry,
                source,
                process_ctx,
                params={"group_name": "surrounds"},
            )


if __name__ == "__main__":
    unittest.main()
