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

    def test_2_0_is_front_only(self) -> None:
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

    def test_anchor_stems_stay_front_safe_by_default(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        for stem_id in ("STEM.KICK", "STEM.SNARE", "STEM.BASS"):
            gains = by_stem[stem_id]["gains"]
            self.assertGreater(gains["SPK.L"], 0.0)
            self.assertGreater(gains["SPK.R"], 0.0)
            self.assertEqual(gains["SPK.LS"], 0.0)
            self.assertEqual(gains["SPK.RS"], 0.0)

    def test_lead_center_anchor_is_enabled_when_center_exists(self) -> None:
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

    def test_ambient_and_pad_get_modest_surround(self) -> None:
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

    def test_percussion_surround_send_is_tiny_and_gated(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        hat = by_stem["STEM.HAT"]["gains"]
        perc_low = by_stem["STEM.PERC_LOW"]["gains"]
        hat_locked = by_stem["STEM.HAT_LOCKED"]["gains"]

        self.assertGreater(hat["SPK.LS"], 0.0)
        self.assertGreater(hat["SPK.RS"], 0.0)
        self.assertLessEqual(hat["SPK.LS"], 0.07)
        self.assertLessEqual(hat["SPK.RS"], 0.07)

        self.assertEqual(perc_low["SPK.LS"], 0.0)
        self.assertEqual(perc_low["SPK.RS"], 0.0)

        self.assertEqual(hat_locked["SPK.LS"], 0.0)
        self.assertEqual(hat_locked["SPK.RS"], 0.0)

    def test_measured_anchor_exception_can_enable_surround_wrap(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        wrap = _stem_by_id(render_intent)["STEM.KICK_WRAP"]
        gains = wrap["gains"]
        self.assertEqual(
            wrap["policy_class"],
            "ANCHOR.TRANSIENT_SURROUND_WRAP_MEASURED",
        )
        self.assertGreater(gains["SPK.LS"], 0.0)
        self.assertGreater(gains["SPK.RS"], 0.0)
        # Safety-first: still keep some front anchor energy.
        self.assertGreater(gains["SPK.L"], 0.0)
        self.assertGreater(gains["SPK.R"], 0.0)

    def test_anchor_wrap_requires_explicit_immersive_intent(self) -> None:
        scene = _load_fixture_scene()
        for obj in scene.get("objects", []):
            if obj.get("stem_id") != "STEM.KICK_WRAP":
                continue
            intent = obj.get("intent")
            if isinstance(intent, dict):
                intent.pop("loudness_bias", None)
            obj["notes"] = []
            break
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        wrap = _stem_by_id(render_intent)["STEM.KICK_WRAP"]
        gains = wrap["gains"]
        self.assertEqual(wrap["policy_class"], "ANCHOR.TRANSIENT_FRONT_ONLY")
        self.assertEqual(gains["SPK.LS"], 0.0)
        self.assertEqual(gains["SPK.RS"], 0.0)
        self.assertIn(
            "surround_wrap_blocked_missing_immersive_intent",
            wrap["notes"],
        )

    def test_anchor_wrap_requires_measurement_evidence(self) -> None:
        scene = _load_fixture_scene()
        for obj in scene.get("objects", []):
            if obj.get("stem_id") != "STEM.KICK_WRAP":
                continue
            obj["width_hint"] = 0.55
            obj["depth_hint"] = 0.55
            obj["confidence"] = 0.95
            intent = obj.get("intent")
            if isinstance(intent, dict):
                intent["width"] = 0.55
                intent["depth"] = 0.55
                intent["confidence"] = 0.95
                intent["loudness_bias"] = "back"
            break

        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        wrap = _stem_by_id(render_intent)["STEM.KICK_WRAP"]
        gains = wrap["gains"]
        self.assertEqual(wrap["policy_class"], "ANCHOR.TRANSIENT_FRONT_ONLY")
        self.assertEqual(gains["SPK.LS"], 0.0)
        self.assertEqual(gains["SPK.RS"], 0.0)
        self.assertIn(
            "surround_wrap_blocked_insufficient_measurement_evidence",
            wrap["notes"],
        )

    def test_7_1_includes_rear_surround_for_ambient(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.7_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        amb = _stem_by_id(render_intent)["STEM.AMB"]["gains"]
        self.assertGreater(amb["SPK.LS"], 0.0)
        self.assertGreater(amb["SPK.RS"], 0.0)
        self.assertGreater(amb["SPK.LRS"], 0.0)
        self.assertGreater(amb["SPK.RRS"], 0.0)

    def test_7_1_4_adds_subtle_height_for_ambient_only(self) -> None:
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

        self.assertLess(amb["SPK.TFL"], amb["SPK.LS"])
        self.assertLess(amb["SPK.TFR"], amb["SPK.RS"])

    def test_9_1_6_adds_wides_for_ambient_not_anchor(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.9_1_6")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        amb = by_stem["STEM.AMB"]["gains"]
        kick = by_stem["STEM.KICK"]["gains"]

        self.assertGreater(amb["SPK.LW"], 0.0)
        self.assertGreater(amb["SPK.RW"], 0.0)
        self.assertEqual(kick["SPK.LW"], 0.0)
        self.assertEqual(kick["SPK.RW"], 0.0)

    def test_bus_gain_staging_is_present_and_deterministic(self) -> None:
        scene = _load_fixture_scene()
        render_intent = build_render_intent(scene, "LAYOUT.5_1")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        staging = render_intent.get("bus_gain_staging")
        self.assertIsInstance(staging, dict)
        if not isinstance(staging, dict):
            return
        self.assertIn("master_gain_db", staging)
        self.assertIn("group_trims_db", staging)
        trims = staging.get("group_trims_db")
        self.assertIsInstance(trims, dict)
        if not isinstance(trims, dict):
            return
        self.assertIn("BUS.FX.AMBIENCE", trims)
        self.assertIn("BUS.MUSIC.SYNTH", trims)

    def test_surround_send_caps_and_source_receipt_notes(self) -> None:
        scene = _load_fixture_scene()
        for obj in scene.get("objects", []):
            if not isinstance(obj, dict) or obj.get("stem_id") != "STEM.AMB":
                continue
            intent = obj.get("intent")
            if not isinstance(intent, dict):
                continue
            intent["surround_send_caps"] = {
                "side_max_gain": 0.01,
                "rear_max_gain": 0.005,
            }
            break

        scene["metadata"] = {
            "locks_receipt": {
                "version": "0.1.0",
                "objects": [
                    {
                        "stem_id": "STEM.AMB",
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

        amb = _stem_by_id(render_intent)["STEM.AMB"]
        gains = amb["gains"]
        self.assertLessEqual(gains["SPK.LS"], 0.01)
        self.assertLessEqual(gains["SPK.RS"], 0.01)
        self.assertIn("surround_send_caps_present", amb["notes"])
        self.assertIn("surround_side_send_capped_by_lock", amb["notes"])
        self.assertIn("surround_rear_send_capped_by_lock", amb["notes"])
        self.assertIn("role_source:locked", amb["notes"])
        self.assertIn("width_source:locked", amb["notes"])


if __name__ == "__main__":
    unittest.main()
