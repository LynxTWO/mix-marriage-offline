from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from mmo.core.scene_builder import build_scene_from_bus_plan
from mmo.core.placement_policy import build_render_intent
from mmo.core.scene_templates import apply_scene_templates


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


def _mini_orchestra_stems_map() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_utc": "2000-01-01T00:00:00Z",
        "stems_dir": "/tmp/mini_orchestra",
        "roles_ref": "ontology/roles.yaml",
        "assignments": [
            {
                "file_id": "STEM.BAGPIPE",
                "rel_path": "bagpipe.wav",
                "role_id": "ROLE.WINDS.BAGPIPE",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.BRASS",
                "rel_path": "brass_horn.wav",
                "role_id": "ROLE.BRASS.HORN",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.CELLO",
                "rel_path": "cello.wav",
                "role_id": "ROLE.STRINGS.CELLO",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.DIDGE",
                "rel_path": "didgeridoo.wav",
                "role_id": "ROLE.WINDS.DIDGERIDOO",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.PERC",
                "rel_path": "perc.wav",
                "role_id": "ROLE.DRUM.PERCUSSION",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.VIOLA",
                "rel_path": "viola.wav",
                "role_id": "ROLE.STRINGS.VIOLA",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.VIOLIN",
                "rel_path": "violin.wav",
                "role_id": "ROLE.STRINGS.VIOLIN",
                "confidence": 0.95,
            },
        ],
    }


def _mini_orchestra_bus_plan() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_utc": "2000-01-01T00:00:00Z",
        "assignments": [
            {
                "stem_id": "STEM.BAGPIPE",
                "file_path": "bagpipe.wav",
                "role_id": "ROLE.WINDS.BAGPIPE",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.BRASS",
                "file_path": "brass_horn.wav",
                "role_id": "ROLE.BRASS.HORN",
                "bus_id": "BUS.MUSIC.BRASS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.CELLO",
                "file_path": "cello.wav",
                "role_id": "ROLE.STRINGS.CELLO",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.DIDGE",
                "file_path": "didgeridoo.wav",
                "role_id": "ROLE.WINDS.DIDGERIDOO",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.PERC",
                "file_path": "perc.wav",
                "role_id": "ROLE.DRUM.PERCUSSION",
                "bus_id": "BUS.DRUMS.PERC",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.VIOLA",
                "file_path": "viola.wav",
                "role_id": "ROLE.STRINGS.VIOLA",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.VIOLIN",
                "file_path": "violin.wav",
                "role_id": "ROLE.STRINGS.VIOLIN",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
        ],
    }


def _mini_orchestra_scene(template_id: str) -> dict[str, Any]:
    scene = build_scene_from_bus_plan(
        _mini_orchestra_stems_map(),
        _mini_orchestra_bus_plan(),
        profile_id="PROFILE.ASSIST",
    )
    return apply_scene_templates(
        scene,
        [template_id],
        scene_templates_path=_REPO_ROOT / "ontology" / "scene_templates.yaml",
        scene_locks_path=_REPO_ROOT / "ontology" / "scene_locks.yaml",
    )


def _hybrid_stage_stems_map() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_utc": "2000-01-01T00:00:00Z",
        "stems_dir": "/tmp/hybrid_stage",
        "roles_ref": "ontology/roles.yaml",
        "assignments": [
            {
                "file_id": "STEM.BAGPIPE",
                "rel_path": "bagpipe.wav",
                "role_id": "ROLE.WINDS.BAGPIPE",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.BASS_CLAR",
                "rel_path": "bass_clarinet.wav",
                "role_id": "ROLE.WW.BASS_CLARINET",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.BASS_GTR",
                "rel_path": "bass_guitar.wav",
                "role_id": "ROLE.BASS.GUITAR",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.BGV",
                "rel_path": "bgv.wav",
                "role_id": "ROLE.VOCAL.BGV",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.DIDGE",
                "rel_path": "didgeridoo.wav",
                "role_id": "ROLE.WINDS.DIDGERIDOO",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.ERHU",
                "rel_path": "erhu.wav",
                "role_id": "ROLE.STRINGS.BOWED",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.EUPH",
                "rel_path": "euphonium.wav",
                "role_id": "ROLE.BRASS.EUPHONIUM",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.FLUTE",
                "rel_path": "flute.wav",
                "role_id": "ROLE.WW.FLUTE",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.HARP",
                "rel_path": "harp.wav",
                "role_id": "ROLE.STRINGS.HARP",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.LEAD_A",
                "rel_path": "lead_a.wav",
                "role_id": "ROLE.VOCAL.LEAD",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.LEAD_B",
                "rel_path": "lead_b.wav",
                "role_id": "ROLE.VOX.LEAD",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.MANDO",
                "rel_path": "mandolin.wav",
                "role_id": "ROLE.GTR.MANDOLIN",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.MARIMBA",
                "rel_path": "marimba.wav",
                "role_id": "ROLE.DRUM.MALLETS",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.ORGAN",
                "rel_path": "pipe_organ.wav",
                "role_id": "ROLE.KEYS.ORGAN",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.SHAMISEN",
                "rel_path": "shamisen.wav",
                "role_id": "ROLE.STRINGS.PLUCKED",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.TABLA",
                "rel_path": "tabla.wav",
                "role_id": "ROLE.DRUM.WORLD_PERC",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.TUBA",
                "rel_path": "tuba.wav",
                "role_id": "ROLE.BRASS.TUBA",
                "confidence": 0.95,
            },
            {
                "file_id": "STEM.VIOLIN",
                "rel_path": "violin.wav",
                "role_id": "ROLE.STRINGS.VIOLIN",
                "confidence": 0.95,
            },
        ],
    }


def _hybrid_stage_bus_plan() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_utc": "2000-01-01T00:00:00Z",
        "assignments": [
            {
                "stem_id": "STEM.BAGPIPE",
                "file_path": "bagpipe.wav",
                "role_id": "ROLE.WINDS.BAGPIPE",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.BASS_CLAR",
                "file_path": "bass_clarinet.wav",
                "role_id": "ROLE.WW.BASS_CLARINET",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.BASS_GTR",
                "file_path": "bass_guitar.wav",
                "role_id": "ROLE.BASS.GUITAR",
                "bus_id": "BUS.BASS.GTR",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.BGV",
                "file_path": "bgv.wav",
                "role_id": "ROLE.VOCAL.BGV",
                "bus_id": "BUS.VOX.BGV",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.DIDGE",
                "file_path": "didgeridoo.wav",
                "role_id": "ROLE.WINDS.DIDGERIDOO",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.ERHU",
                "file_path": "erhu.wav",
                "role_id": "ROLE.STRINGS.BOWED",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.EUPH",
                "file_path": "euphonium.wav",
                "role_id": "ROLE.BRASS.EUPHONIUM",
                "bus_id": "BUS.MUSIC.BRASS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.FLUTE",
                "file_path": "flute.wav",
                "role_id": "ROLE.WW.FLUTE",
                "bus_id": "BUS.MUSIC.WINDS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.HARP",
                "file_path": "harp.wav",
                "role_id": "ROLE.STRINGS.HARP",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.LEAD_A",
                "file_path": "lead_a.wav",
                "role_id": "ROLE.VOCAL.LEAD",
                "bus_id": "BUS.VOX.LEAD",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.LEAD_B",
                "file_path": "lead_b.wav",
                "role_id": "ROLE.VOX.LEAD",
                "bus_id": "BUS.VOX.LEAD",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.MANDO",
                "file_path": "mandolin.wav",
                "role_id": "ROLE.GTR.MANDOLIN",
                "bus_id": "BUS.MUSIC.GTR",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.MARIMBA",
                "file_path": "marimba.wav",
                "role_id": "ROLE.DRUM.MALLETS",
                "bus_id": "BUS.DRUMS.PERC",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.ORGAN",
                "file_path": "pipe_organ.wav",
                "role_id": "ROLE.KEYS.ORGAN",
                "bus_id": "BUS.MUSIC.KEYS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.SHAMISEN",
                "file_path": "shamisen.wav",
                "role_id": "ROLE.STRINGS.PLUCKED",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.TABLA",
                "file_path": "tabla.wav",
                "role_id": "ROLE.DRUM.WORLD_PERC",
                "bus_id": "BUS.DRUMS.PERC",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.TUBA",
                "file_path": "tuba.wav",
                "role_id": "ROLE.BRASS.TUBA",
                "bus_id": "BUS.MUSIC.BRASS",
                "confidence": 0.95,
            },
            {
                "stem_id": "STEM.VIOLIN",
                "file_path": "violin.wav",
                "role_id": "ROLE.STRINGS.VIOLIN",
                "bus_id": "BUS.MUSIC.STRINGS",
                "confidence": 0.95,
            },
        ],
    }


def _hybrid_stage_scene(template_id: str) -> dict[str, Any]:
    scene = build_scene_from_bus_plan(
        _hybrid_stage_stems_map(),
        _hybrid_stage_bus_plan(),
        profile_id="PROFILE.ASSIST",
    )
    return apply_scene_templates(
        scene,
        [template_id],
        scene_templates_path=_REPO_ROOT / "ontology" / "scene_templates.yaml",
        scene_locks_path=_REPO_ROOT / "ontology" / "scene_locks.yaml",
    )


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
            self.assertEqual(pad[speaker_id], 0.0)
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
                        "depth_source": "locked",
                        "height_send_caps_source": "locked",
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
        self.assertIn("depth_source:locked", kick["notes"])

    def test_scene_lock_no_height_send_disables_height_channels_in_immersive_layouts(self) -> None:
        scene = _load_fixture_scene()
        scene["intent"] = {"confidence": 0.0, "locks": ["LOCK.NO_HEIGHT_SEND"]}

        for layout_id in ("LAYOUT.7_1_4", "LAYOUT.9_1_6"):
            render_intent = build_render_intent(scene, layout_id)
            self.assertIsInstance(render_intent, dict)
            if not isinstance(render_intent, dict):
                continue

            amb = _stem_by_id(render_intent)["STEM.AMB"]["gains"]
            for speaker_id in ("SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR"):
                self.assertEqual(amb[speaker_id], 0.0)
            if layout_id == "LAYOUT.9_1_6":
                self.assertEqual(amb["SPK.TFC"], 0.0)
                self.assertEqual(amb["SPK.TBC"], 0.0)

    def test_bed_height_send_caps_can_force_no_heights_in_immersive_layouts(self) -> None:
        scene = _load_fixture_scene()
        beds = scene.get("beds")
        self.assertIsInstance(beds, list)
        if not isinstance(beds, list):
            return
        for bed in beds:
            if not isinstance(bed, dict):
                continue
            stem_ids = bed.get("stem_ids")
            if not isinstance(stem_ids, list) or "STEM.AMB" not in stem_ids:
                continue
            intent = bed.get("intent")
            if not isinstance(intent, dict):
                intent = {}
                bed["intent"] = intent
            intent["height_send_caps"] = {"top_max_gain": 0.0}

        for layout_id in ("LAYOUT.7_1_4", "LAYOUT.9_1_6"):
            render_intent = build_render_intent(scene, layout_id)
            self.assertIsInstance(render_intent, dict)
            if not isinstance(render_intent, dict):
                continue

            amb = _stem_by_id(render_intent)["STEM.AMB"]["gains"]
            for speaker_id in ("SPK.TFL", "SPK.TFR", "SPK.TRL", "SPK.TRR"):
                self.assertEqual(amb[speaker_id], 0.0)
            if layout_id == "LAYOUT.9_1_6":
                self.assertEqual(amb["SPK.TFC"], 0.0)
                self.assertEqual(amb["SPK.TBC"], 0.0)

    def test_scene_perspective_marks_immersive_intent(self) -> None:
        scene = _load_fixture_scene()
        scene["intent"] = {
            "confidence": 0.0,
            "locks": [],
            "perspective": "in_band",
            "notes": [],
        }
        render_intent = build_render_intent(scene, "LAYOUT.7_1_4")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return
        notes = render_intent.get("notes")
        self.assertIsInstance(notes, list)
        if not isinstance(notes, list):
            return
        self.assertIn("immersive_perspective:in_band", notes)
        self.assertIn("immersive_perspective_source:scene.intent.perspective", notes)

        scene["intent"] = {
            "confidence": 0.0,
            "locks": [],
            "notes": ["perspective: in_orchestra"],
        }
        render_intent_notes = build_render_intent(scene, "LAYOUT.7_1_4")
        self.assertIsInstance(render_intent_notes, dict)
        if not isinstance(render_intent_notes, dict):
            return
        notes_from_scene_note = render_intent_notes.get("notes")
        self.assertIsInstance(notes_from_scene_note, list)
        if not isinstance(notes_from_scene_note, list):
            return
        self.assertIn("immersive_perspective:in_orchestra", notes_from_scene_note)
        self.assertIn(
            "immersive_perspective_source:scene.intent.notes",
            notes_from_scene_note,
        )

    def test_orchestra_template_places_violin_left_and_uses_wides_in_9_1_6(self) -> None:
        scene = _mini_orchestra_scene("TEMPLATE.SEATING.ORCHESTRA_AUDIENCE")
        render_intent = build_render_intent(scene, "LAYOUT.9_1_6")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        violin = _stem_by_id(render_intent)["STEM.VIOLIN"]["gains"]
        self.assertGreater(violin["SPK.L"], violin["SPK.R"])
        self.assertGreater(violin["SPK.LW"], 0.0)
        self.assertEqual(violin["SPK.RRS"], 0.0)

    def test_orchestra_brass_is_rear_biased_only_in_in_orchestra_mode(self) -> None:
        audience_scene = _mini_orchestra_scene("TEMPLATE.SEATING.ORCHESTRA_AUDIENCE")
        in_orchestra_scene = _mini_orchestra_scene("TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA")

        audience_intent = build_render_intent(audience_scene, "LAYOUT.7_1_4")
        in_orchestra_intent = build_render_intent(in_orchestra_scene, "LAYOUT.7_1_4")
        self.assertIsInstance(audience_intent, dict)
        self.assertIsInstance(in_orchestra_intent, dict)
        if not isinstance(audience_intent, dict) or not isinstance(in_orchestra_intent, dict):
            return

        audience_brass = _stem_by_id(audience_intent)["STEM.BRASS"]["gains"]
        in_orchestra_brass = _stem_by_id(in_orchestra_intent)["STEM.BRASS"]["gains"]

        self.assertEqual(audience_brass["SPK.LRS"], 0.0)
        self.assertEqual(audience_brass["SPK.RRS"], 0.0)
        self.assertGreater(in_orchestra_brass["SPK.LRS"], 0.0)
        self.assertGreater(in_orchestra_brass["SPK.RRS"], 0.0)
        self.assertGreater(
            in_orchestra_brass["SPK.LRS"] + in_orchestra_brass["SPK.RRS"],
            in_orchestra_brass["SPK.L"] + in_orchestra_brass["SPK.R"],
        )

    def test_hybrid_in_orchestra_template_spreads_sections_and_keeps_object_heights_off(self) -> None:
        scene = _hybrid_stage_scene("TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA")
        render_intent = build_render_intent(scene, "LAYOUT.9_1_6")
        self.assertIsInstance(render_intent, dict)
        if not isinstance(render_intent, dict):
            return

        by_stem = _stem_by_id(render_intent)
        violin = by_stem["STEM.VIOLIN"]["gains"]
        erhu = by_stem["STEM.ERHU"]["gains"]
        self.assertGreater(violin["SPK.L"], violin["SPK.R"])
        self.assertGreater(erhu["SPK.L"], erhu["SPK.R"])

        euph = by_stem["STEM.EUPH"]["gains"]
        tuba = by_stem["STEM.TUBA"]["gains"]
        self.assertGreater(euph["SPK.LRS"] + euph["SPK.RRS"], euph["SPK.L"] + euph["SPK.R"])
        self.assertGreater(tuba["SPK.LRS"] + tuba["SPK.RRS"], tuba["SPK.L"] + tuba["SPK.R"])

        marimba = by_stem["STEM.MARIMBA"]["gains"]
        tabla = by_stem["STEM.TABLA"]["gains"]
        self.assertGreater(
            marimba["SPK.LRS"] + marimba["SPK.RRS"],
            marimba["SPK.L"] + marimba["SPK.R"],
        )
        self.assertGreater(
            tabla["SPK.LRS"] + tabla["SPK.RRS"],
            tabla["SPK.L"] + tabla["SPK.R"],
        )

        for stem_id, send in by_stem.items():
            if not stem_id.startswith("STEM."):
                continue
            gains = send.get("gains", {})
            self.assertEqual(gains.get("SPK.TFL", 0.0), 0.0)
            self.assertEqual(gains.get("SPK.TFR", 0.0), 0.0)
            self.assertEqual(gains.get("SPK.TRL", 0.0), 0.0)
            self.assertEqual(gains.get("SPK.TRR", 0.0), 0.0)
            self.assertEqual(gains.get("SPK.TFC", 0.0), 0.0)
            self.assertEqual(gains.get("SPK.TBC", 0.0), 0.0)

        euph_notes = by_stem["STEM.EUPH"].get("notes")
        tuba_notes = by_stem["STEM.TUBA"].get("notes")
        self.assertIsInstance(euph_notes, list)
        self.assertIsInstance(tuba_notes, list)
        if isinstance(euph_notes, list):
            self.assertTrue(any(note.startswith("section_slot:") for note in euph_notes))
        if isinstance(tuba_notes, list):
            self.assertTrue(any(note.startswith("section_slot:") for note in tuba_notes))


if __name__ == "__main__":
    unittest.main()
