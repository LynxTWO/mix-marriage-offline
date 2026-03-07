from __future__ import annotations

import unittest

from mmo.dsp.process_context import build_process_context


class TestProcessContext(unittest.TestCase):
    def test_index_of_uses_standard_specific_channel_order(self) -> None:
        ctx = build_process_context("LAYOUT.5_1", standard="FILM")

        self.assertEqual(ctx.layout_standard, "FILM")
        self.assertEqual(
            ctx.channel_order,
            ("SPK.L", "SPK.C", "SPK.R", "SPK.LS", "SPK.RS", "SPK.LFE"),
        )
        self.assertEqual(ctx.index_of("SPK.C"), 1)
        self.assertEqual(ctx.index_of("SPK.LFE"), 5)
        self.assertIsNone(ctx.index_of("SPK.TFL"))

    def test_indices_of_preserves_buffer_order(self) -> None:
        ctx = build_process_context("LAYOUT.7_1_4")

        self.assertTrue(ctx.has("SPK.TFR"))
        self.assertFalse(ctx.has("SPK.TFC"))
        self.assertEqual(
            ctx.indices_of({"SPK.TFR", "SPK.LFE", "SPK.LRS"}),
            [3, 6, 9],
        )

    def test_group_indices_for_5_1(self) -> None:
        ctx = build_process_context("LAYOUT.5_1")

        self.assertEqual(ctx.group_indices("front"), [0, 1, 2])
        self.assertEqual(ctx.group_indices("surround"), [4, 5])
        self.assertEqual(ctx.group_indices("rear"), [])
        self.assertEqual(ctx.group_indices("lfe"), [3])
        self.assertEqual(ctx.group_indices("height"), [])

    def test_group_indices_for_7_1_4(self) -> None:
        ctx = build_process_context("LAYOUT.7_1_4")

        self.assertEqual(ctx.group_indices("rear"), [6, 7])
        self.assertEqual(ctx.group_indices("height"), [8, 9, 10, 11])
        self.assertEqual(ctx.lfe_indices, [3])

    def test_group_indices_for_9_1_6(self) -> None:
        ctx = build_process_context("LAYOUT.9_1_6")

        self.assertEqual(ctx.group_indices("front"), [0, 1, 2, 8, 9])
        self.assertEqual(ctx.group_indices("surround"), [4, 5])
        self.assertEqual(ctx.group_indices("rear"), [6, 7])
        self.assertEqual(ctx.group_indices("height"), [10, 11, 12, 13, 14, 15])
        self.assertEqual(ctx.lfe_indices, [3])

    def test_unlisted_standard_falls_back_to_canonical_channel_order(self) -> None:
        ctx = build_process_context("LAYOUT.9_1_6", standard="VST3")

        self.assertEqual(ctx.layout_standard, "VST3")
        self.assertEqual(
            ctx.channel_order,
            (
                "SPK.L",
                "SPK.R",
                "SPK.C",
                "SPK.LFE",
                "SPK.LS",
                "SPK.RS",
                "SPK.LRS",
                "SPK.RRS",
                "SPK.LW",
                "SPK.RW",
                "SPK.TFL",
                "SPK.TFR",
                "SPK.TRL",
                "SPK.TRR",
                "SPK.TFC",
                "SPK.TBC",
            ),
        )
        self.assertEqual(ctx.index_of("SPK.LFE"), 3)
        self.assertEqual(ctx.group_indices("front"), [0, 1, 2, 8, 9])
        self.assertEqual(ctx.group_indices("height"), [10, 11, 12, 13, 14, 15])


if __name__ == "__main__":
    unittest.main()
