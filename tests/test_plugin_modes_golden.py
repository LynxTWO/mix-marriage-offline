from __future__ import annotations

import math
import unittest
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from mmo.core.plugin_loader import load_plugin_root_entries
from mmo.dsp.plugin_mode_runner import run_plugin_mode
from mmo.dsp.process_context import build_process_context

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "plugin_authoring"
    / "starter_pack"
)
_PER_CHANNEL_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.PER_CHANNEL_GAIN"
_LINKED_GROUP_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.LINKED_GROUP_BED"
_TRUE_MULTICHANNEL_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.TRUE_MULTICHANNEL_CHECKSUM"
_PER_CHANNEL_GAIN_LINEAR = math.pow(10.0, 1.0 / 20.0)
_LINKED_GROUP_GAIN_DB = 1.5
_LINKED_GROUP_GAIN_LINEAR = math.pow(10.0, _LINKED_GROUP_GAIN_DB / 20.0)
_SPEAKER_BASE_LEVELS = {
    "SPK.L": 0.050,
    "SPK.R": 0.060,
    "SPK.C": 0.070,
    "SPK.LFE": 0.015,
    "SPK.LS": 0.080,
    "SPK.RS": 0.090,
    "SPK.LRS": 0.100,
    "SPK.RRS": 0.110,
    "SPK.TFL": 0.120,
    "SPK.TFR": 0.130,
    "SPK.TRL": 0.140,
    "SPK.TRR": 0.150,
}


@lru_cache(maxsize=1)
def _fixture_entries() -> dict[str, Any]:
    entries = load_plugin_root_entries(_FIXTURE_ROOT)
    return {entry.plugin_id: entry for entry in entries}


def _speaker_level(spk_id: str) -> float:
    if spk_id in _SPEAKER_BASE_LEVELS:
        return _SPEAKER_BASE_LEVELS[spk_id]
    fallback = (sum(ord(char) for char in spk_id) % 20) / 1000.0
    return 0.040 + fallback


def _build_fixture_buffer(process_ctx: Any, *, frame_count: int = 32) -> np.ndarray:
    ramp = (np.arange(frame_count, dtype=np.float64) + 1.0) / float(frame_count)
    rows = [
        _speaker_level(spk_id) * (0.5 + ramp)
        for spk_id in process_ctx.channel_order
    ]
    return np.vstack(rows)


class TestPluginModesGolden(unittest.TestCase):
    def test_fixture_manifests_declare_explicit_mode_semantics(self) -> None:
        entries = _fixture_entries()

        self.assertEqual(
            sorted(entries),
            [
                _LINKED_GROUP_PLUGIN_ID,
                _PER_CHANNEL_PLUGIN_ID,
                _TRUE_MULTICHANNEL_PLUGIN_ID,
            ],
        )

        per_channel = entries[_PER_CHANNEL_PLUGIN_ID].manifest["capabilities"]
        self.assertGreaterEqual(per_channel["max_channels"], 32)
        self.assertEqual(per_channel["channel_mode"], "per_channel")
        self.assertEqual(per_channel["scene_scope"], "object_capable")
        self.assertEqual(per_channel["layout_safety"], "layout_agnostic")
        self.assertEqual(per_channel["deterministic_seed_policy"], "none")
        self.assertEqual(
            per_channel["purity"],
            {
                "audio_buffer": "typed_f64_interleaved",
                "randomness": "forbidden",
                "wall_clock": "forbidden",
                "thread_scheduling": "forbidden",
            },
        )

        linked_group = entries[_LINKED_GROUP_PLUGIN_ID].manifest["capabilities"]
        self.assertGreaterEqual(linked_group["max_channels"], 32)
        self.assertEqual(linked_group["channel_mode"], "linked_group")
        self.assertTrue(linked_group["bed_only"])
        self.assertEqual(linked_group["scene_scope"], "bed_only")
        self.assertEqual(linked_group["layout_safety"], "layout_agnostic")
        self.assertEqual(linked_group["latency"], {"type": "fixed", "samples": 64})
        self.assertEqual(
            linked_group["supported_link_groups"],
            ["front", "surrounds", "heights"],
        )
        self.assertEqual(linked_group["supported_group_sizes"], [3, 4])
        self.assertEqual(linked_group["deterministic_seed_policy"], "none")
        self.assertEqual(
            linked_group["purity"],
            {
                "audio_buffer": "typed_f64_interleaved",
                "randomness": "forbidden",
                "wall_clock": "forbidden",
                "thread_scheduling": "forbidden",
            },
        )

        true_multichannel = entries[_TRUE_MULTICHANNEL_PLUGIN_ID].manifest["capabilities"]
        self.assertGreaterEqual(true_multichannel["max_channels"], 32)
        self.assertEqual(true_multichannel["channel_mode"], "true_multichannel")
        self.assertEqual(true_multichannel["supported_group_sizes"], [6, 12])
        self.assertTrue(true_multichannel["requires_speaker_positions"])
        self.assertEqual(true_multichannel["scene_scope"], "object_capable")
        self.assertEqual(true_multichannel["layout_safety"], "layout_specific")
        self.assertEqual(
            true_multichannel["supported_layout_ids"],
            ["LAYOUT.5_1", "LAYOUT.7_1_4"],
        )
        self.assertEqual(true_multichannel["latency"], {"type": "dynamic"})
        self.assertEqual(
            true_multichannel["deterministic_seed_policy"],
            "seed_required",
        )
        self.assertEqual(
            true_multichannel["purity"],
            {
                "audio_buffer": "typed_f64_interleaved",
                "randomness": "process_context_seed",
                "wall_clock": "forbidden",
                "thread_scheduling": "forbidden",
            },
        )

    def test_per_channel_plugin_targets_semantic_speakers_across_channel_orders(self) -> None:
        plugin_entry = _fixture_entries()[_PER_CHANNEL_PLUGIN_ID]
        target_channel_ids = ["SPK.C", "SPK.LS"]

        for standard in ("SMPTE", "FILM"):
            with self.subTest(standard=standard):
                process_ctx = build_process_context("LAYOUT.5_1", standard=standard, seed=11)
                source = _build_fixture_buffer(process_ctx)
                result = run_plugin_mode(
                    plugin_entry,
                    source,
                    process_ctx,
                    params={"target_channel_ids": target_channel_ids},
                )

                self.assertEqual(result.evidence["channel_mode"], "per_channel")
                self.assertEqual(result.evidence["runtime_audio_buffer"], "typed_f64_interleaved")
                self.assertEqual(
                    result.evidence["channel_ids_touched"],
                    sorted(target_channel_ids),
                )
                self.assertEqual(
                    result.evidence["channel_call_count"],
                    process_ctx.num_channels,
                )

                for spk_id in process_ctx.channel_order:
                    index = process_ctx.index_of(spk_id)
                    if index is None:
                        self.fail(f"Missing index for {spk_id}")
                    expected = source[index]
                    if spk_id in target_channel_ids:
                        expected = expected * _PER_CHANNEL_GAIN_LINEAR
                    np.testing.assert_allclose(
                        result.rendered[index],
                        expected,
                        rtol=0.0,
                        atol=1e-12,
                    )

    def test_linked_group_plugin_applies_equal_gain_to_front_surrounds_and_heights(self) -> None:
        plugin_entry = _fixture_entries()[_LINKED_GROUP_PLUGIN_ID]
        process_ctx = build_process_context("LAYOUT.7_1_4", seed=21)
        expected_ids_by_group = {
            "front": ["SPK.L", "SPK.R", "SPK.C"],
            "surrounds": ["SPK.LS", "SPK.RS", "SPK.LRS", "SPK.RRS"],
            "heights": ["SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR"],
        }

        for group_name, expected_channel_ids in expected_ids_by_group.items():
            with self.subTest(group_name=group_name):
                source = _build_fixture_buffer(process_ctx)
                result = run_plugin_mode(
                    plugin_entry,
                    source,
                    process_ctx,
                    params={
                        "group_name": group_name,
                        "gain_db": _LINKED_GROUP_GAIN_DB,
                    },
                )

                self.assertEqual(result.evidence["channel_mode"], "linked_group")
                self.assertEqual(result.evidence["runtime_audio_buffer"], "typed_f64_interleaved")
                self.assertEqual(result.evidence["buffer_type"], "AudioBufferF64")
                self.assertEqual(result.evidence["group_name"], group_name)
                self.assertEqual(result.evidence["channel_ids"], expected_channel_ids)

                for spk_id in process_ctx.channel_order:
                    index = process_ctx.index_of(spk_id)
                    if index is None:
                        self.fail(f"Missing index for {spk_id}")
                    expected = source[index]
                    if spk_id in expected_channel_ids:
                        expected = expected * _LINKED_GROUP_GAIN_LINEAR
                    np.testing.assert_allclose(
                        result.rendered[index],
                        expected,
                        rtol=0.0,
                        atol=1e-12,
                    )

    def test_true_multichannel_plugin_sees_full_buffer_and_is_deterministic(self) -> None:
        plugin_entry = _fixture_entries()[_TRUE_MULTICHANNEL_PLUGIN_ID]
        cases = (
            ("LAYOUT.5_1", "FILM", 37, "SPK.LFE"),
            ("LAYOUT.7_1_4", "SMPTE", 73, "SPK.TFR"),
        )

        for layout_id, standard, seed, target_channel_id in cases:
            with self.subTest(layout_id=layout_id, standard=standard):
                process_ctx = build_process_context(layout_id, standard=standard, seed=seed)
                source = _build_fixture_buffer(process_ctx)
                checksum = float(np.sum(source, dtype=np.float64))
                params = {
                    "expected_sum_min": checksum - 1e-12,
                    "expected_sum_max": checksum + 1e-12,
                    "target_channel_id": target_channel_id,
                }

                first = run_plugin_mode(plugin_entry, source, process_ctx, params=params)
                second = run_plugin_mode(plugin_entry, source, process_ctx, params=params)

                np.testing.assert_array_equal(first.rendered, second.rendered)
                self.assertEqual(first.evidence["runtime_audio_buffer"], "typed_f64_interleaved")
                self.assertEqual(first.evidence["buffer_type"], "AudioBufferF64")
                self.assertEqual(
                    first.evidence["channel_ids_seen"],
                    list(process_ctx.channel_order),
                )
                self.assertTrue(first.evidence["checksum_matched"])
                self.assertTrue(first.evidence["tone_written"])
                self.assertEqual(first.evidence["tone_channel_id"], target_channel_id)
                self.assertEqual(first.evidence["seed"], seed)

                target_index = process_ctx.index_of(target_channel_id)
                if target_index is None:
                    self.fail(f"Missing index for {target_channel_id}")

                for index, spk_id in enumerate(process_ctx.channel_order):
                    if index == target_index:
                        self.assertFalse(
                            np.array_equal(first.rendered[index], source[index]),
                            msg=f"{layout_id} target channel {spk_id} did not receive checksum tone",
                        )
                        continue
                    np.testing.assert_array_equal(first.rendered[index], source[index])

                mismatch = run_plugin_mode(
                    plugin_entry,
                    source,
                    process_ctx,
                    params={
                        "expected_sum_min": checksum + 1.0,
                        "expected_sum_max": checksum + 2.0,
                        "target_channel_id": target_channel_id,
                    },
                )
                np.testing.assert_array_equal(mismatch.rendered, source)
                self.assertFalse(mismatch.evidence["checksum_matched"])
                self.assertFalse(mismatch.evidence["tone_written"])


if __name__ == "__main__":
    unittest.main()
