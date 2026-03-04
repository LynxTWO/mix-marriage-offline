from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from mmo.core.placement_policy import build_render_intent


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "placement_policy" / "conservative_scene.json"
)


def _load_fixture_scene() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _stem_by_id(render_intent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = render_intent.get("stem_sends")
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stem_id = row.get("stem_id")
        if isinstance(stem_id, str) and stem_id:
            out[stem_id] = row
    return out


class TestPlacementPolicy(unittest.TestCase):
    def test_deterministic_for_known_fixture(self) -> None:
        scene = _load_fixture_scene()
        first = build_render_intent(scene, "LAYOUT.5_1")
        second = build_render_intent(scene, "LAYOUT.5_1")
        self.assertEqual(first, second)

    def test_returns_none_for_unsupported_layout(self) -> None:
        scene = _load_fixture_scene()
        self.assertIsNone(build_render_intent(scene, "LAYOUT.5_1_2"))

    def test_2_0_uses_front_only_channels(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.2_0")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return
        self.assertEqual(render_intent.get("channel_order"), ["SPK.L", "SPK.R"])
        by_stem = _stem_by_id(render_intent)
        for stem in by_stem.values():
            gains = stem.get("gains")
            self.assertEqual(sorted(gains.keys()), ["SPK.L", "SPK.R"])

    def test_object_stems_are_front_only(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        for stem_id in ("STEM.KICK", "STEM.SNARE", "STEM.BASS", "STEM.HAT"):
            gains = by_stem[stem_id]["gains"]
            self.assertGreater(gains["SPK.L"], 0.0)
            self.assertGreater(gains["SPK.R"], 0.0)
            self.assertEqual(gains["SPK.LS"], 0.0)
            self.assertEqual(gains["SPK.RS"], 0.0)

    def test_lead_stem_can_use_center_but_no_surround(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        lead = _stem_by_id(render_intent)["STEM.LEAD"]
        gains = lead["gains"]
        self.assertGreater(gains["SPK.C"], 0.0)
        self.assertGreater(gains["SPK.L"], 0.0)
        self.assertGreater(gains["SPK.R"], 0.0)
        self.assertEqual(gains["SPK.LS"], 0.0)
        self.assertEqual(gains["SPK.RS"], 0.0)

    def test_bed_stems_get_subtle_surround_in_5_1(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        for stem_id in ("STEM.PAD", "STEM.AMB"):
            gains = by_stem[stem_id]["gains"]
            self.assertGreater(gains["SPK.LS"], 0.0)
            self.assertGreater(gains["SPK.RS"], 0.0)
            self.assertLess(gains["SPK.LS"], gains["SPK.L"])
            self.assertLess(gains["SPK.RS"], gains["SPK.R"])

    def test_bed_surround_send_disabled_below_confidence_threshold(self) -> None:
        scene = _load_fixture_scene()
        beds = scene.get("beds")
        self.assertIsInstance(beds, list)
        if not isinstance(beds, list):
            return
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            stem_ids = bed.get("stem_ids")
            if isinstance(stem_ids, list) and "STEM.AMB" in stem_ids:
                bed["confidence"] = 0.2
                intent = bed.get("intent")
                if isinstance(intent, dict):
                    intent["confidence"] = 0.2
                break

        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return
        amb = _stem_by_id(render_intent)["STEM.AMB"]
        gains = amb["gains"]
        self.assertEqual(gains["SPK.LS"], 0.0)
        self.assertEqual(gains["SPK.RS"], 0.0)
        self.assertIn("surround_send_disabled_low_confidence", amb["notes"])

    def test_7_1_4_adds_overheads_for_beds_not_objects(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.7_1_4")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        amb = by_stem["STEM.AMB"]["gains"]
        pad = by_stem["STEM.PAD"]["gains"]
        kick = by_stem["STEM.KICK"]["gains"]
        snare = by_stem["STEM.SNARE"]["gains"]

        for speaker_id in ("SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR"):
            self.assertGreater(amb[speaker_id], 0.0)
            self.assertGreater(pad[speaker_id], 0.0)
            self.assertEqual(kick[speaker_id], 0.0)
            self.assertEqual(snare[speaker_id], 0.0)

    def test_7_1_6_supports_top_center_bed_sends(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.7_1_6")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        amb = _stem_by_id(render_intent)["STEM.AMB"]["gains"]
        self.assertGreater(amb["SPK.TFC"], 0.0)
        self.assertGreater(amb["SPK.TBC"], 0.0)

    def test_scene_lock_no_stereo_widening_disables_bed_surround(self) -> None:
        scene = _load_fixture_scene()
        scene["intent"] = {"confidence": 0.0, "locks": ["LOCK.NO_STEREO_WIDENING"]}
        render_intent = build_render_intent(scene, "LAYOUT.7_1_4")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        amb = _stem_by_id(render_intent)["STEM.AMB"]["gains"]
        for speaker_id in (
            "SPK.LS",
            "SPK.RS",
            "SPK.LRS",
            "SPK.RRS",
            "SPK.TFL",
            "SPK.TFR",
            "SPK.TRL",
            "SPK.TRR",
        ):
            self.assertEqual(amb[speaker_id], 0.0)

    def test_bus_gain_staging_tracks_bed_group_trims(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        staging = render_intent.get("bus_gain_staging")
        self.assertIsInstance(staging, dict)
        if not isinstance(staging, dict):
            return
        trims = staging.get("group_trims_db")
        self.assertIsInstance(trims, dict)
        if not isinstance(trims, dict):
            return
        self.assertIn("BUS.FX.AMBIENCE", trims)
        self.assertIn("BUS.MUSIC.SYNTH", trims)

    def test_source_receipt_notes_propagate_to_object_sends(self) -> None:
        scene = _load_fixture_scene()
        scene["metadata"] = {
            "locks_receipt": {
                "version": "0.1.0",
                "objects": [
                    {
                        "stem_id": "STEM.KICK",
                        "role_source": "locked",
                        "bus_source": "explicit_metadata",
                        "azimuth_source": "inferred",
                        "width_source": "locked",
                        "surround_send_caps_source": "locked",
                    }
                ],
                "unmatched_stem_ids": [],
            }
        }

        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return
        kick = _stem_by_id(render_intent)["STEM.KICK"]
        self.assertIn("role_source:locked", kick["notes"])
        self.assertIn("width_source:locked", kick["notes"])


if __name__ == "__main__":
    unittest.main()
