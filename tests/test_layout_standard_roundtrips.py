"""Regression tests for deterministic layout-standard round trips.

For each supported test layout, verify:
1) source standard -> SMPTE remap lands every speaker at the correct SMPTE slot.
2) SMPTE -> target standard remap lands every speaker at the correct target slot.
3) No speaker swaps occur across source->SMPTE->target paths.
4) Repeated runs are deterministic.
"""

from __future__ import annotations

import unittest

from mmo.core.layout_negotiation import (
    get_channel_order,
    load_layouts_registry,
    reorder_channels,
)

_STANDARDS: tuple[str, ...] = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")


def _multichannel_layout_ids() -> tuple[str, ...]:
    layout_ids: list[str] = []
    for layout_id, entry in load_layouts_registry().items():
        channel_count = entry.get("channel_count")
        if isinstance(channel_count, int) and channel_count >= 3:
            layout_ids.append(layout_id)
    return tuple(layout_ids)


_LAYOUT_IDS: tuple[str, ...] = _multichannel_layout_ids()


def _require_order(layout_id: str, standard: str) -> list[str]:
    order = get_channel_order(layout_id, standard)
    if order is None:
        raise AssertionError(
            f"Missing channel order for layout={layout_id} standard={standard}"
        )
    return order


class TestLayoutStandardRoundTrips(unittest.TestCase):
    """End-to-end source->SMPTE->target round-trip routing checks."""

    def test_matrix_includes_required_reference_layouts(self) -> None:
        required = {"LAYOUT.5_1", "LAYOUT.7_1", "LAYOUT.7_1_4", "LAYOUT.7_2_4"}
        self.assertTrue(required.issubset(set(_LAYOUT_IDS)))

    def _synthetic_buffer(
        self,
        layout_id: str,
        source_standard: str,
        source_order: list[str],
    ) -> list[str]:
        return [
            f"{layout_id}|{source_standard}|slot={slot}|{speaker_id}"
            for slot, speaker_id in enumerate(source_order)
        ]

    def test_source_to_smpte_to_target_preserves_speaker_identity(self) -> None:
        for layout_id in _LAYOUT_IDS:
            smpte_order = _require_order(layout_id, "SMPTE")
            for source_standard in _STANDARDS:
                source_order = _require_order(layout_id, source_standard)
                source_data = self._synthetic_buffer(
                    layout_id, source_standard, source_order
                )
                source_by_speaker = {
                    speaker_id: source_data[i]
                    for i, speaker_id in enumerate(source_order)
                }

                with self.subTest(
                    layout_id=layout_id,
                    source_standard=source_standard,
                    target_standard="SMPTE",
                ):
                    to_smpte = reorder_channels(source_data, source_order, smpte_order)
                    self.assertEqual(len(to_smpte), len(smpte_order))
                    for slot, speaker_id in enumerate(smpte_order):
                        self.assertEqual(
                            to_smpte[slot],
                            source_by_speaker[speaker_id],
                            f"{layout_id} {source_standard}->SMPTE swapped {speaker_id}",
                        )

                for target_standard in _STANDARDS:
                    target_order = _require_order(layout_id, target_standard)
                    with self.subTest(
                        layout_id=layout_id,
                        source_standard=source_standard,
                        target_standard=target_standard,
                    ):
                        to_smpte = reorder_channels(
                            source_data, source_order, smpte_order
                        )
                        to_target = reorder_channels(to_smpte, smpte_order, target_order)
                        self.assertEqual(len(to_target), len(target_order))
                        for slot, speaker_id in enumerate(target_order):
                            self.assertEqual(
                                to_target[slot],
                                source_by_speaker[speaker_id],
                                (
                                    f"{layout_id} {source_standard}->SMPTE->{target_standard} "
                                    f"swapped {speaker_id}"
                                ),
                            )

    def test_roundtrip_matrix_is_deterministic(self) -> None:
        for layout_id in _LAYOUT_IDS:
            smpte_order = _require_order(layout_id, "SMPTE")
            for source_standard in _STANDARDS:
                source_order = _require_order(layout_id, source_standard)
                source_data = self._synthetic_buffer(
                    layout_id, source_standard, source_order
                )
                to_smpte = reorder_channels(source_data, source_order, smpte_order)
                for target_standard in _STANDARDS:
                    target_order = _require_order(layout_id, target_standard)
                    with self.subTest(
                        layout_id=layout_id,
                        source_standard=source_standard,
                        target_standard=target_standard,
                    ):
                        a = reorder_channels(to_smpte, smpte_order, target_order)
                        b = reorder_channels(to_smpte, smpte_order, target_order)
                        self.assertEqual(list(a), list(b))


if __name__ == "__main__":
    unittest.main()
