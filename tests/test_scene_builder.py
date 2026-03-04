"""Tests for DoD 4.3: scene_builder.build_scene_from_session().

Covers:
- Determinism: same inputs → same output.
- Schema validity: output validates against scene.schema.json.
- Confidence gating: no metering → confidence=0, no hints emitted.
- Inference vs explicit: with metering → width/depth hints may be emitted.
- Stereo advisory: confidence capped at 0.35 for stereo-stem inference.
- User locks override: locks propagate verbatim regardless of confidence.
- routing_intent: inferred from stem channel counts (stereo/surround/immersive).
- Fixtures: stereo-stems, mono-stems, 5.1, immersive sessions.
"""
from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.scene_builder import (
    _ADVISORY_STEREO_CONF_CAP,
    _CONFIDENCE_GATE,
    build_scene_from_session,
)


# ---------------------------------------------------------------------------
# Schema validator helper
# ---------------------------------------------------------------------------

def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "scene"


def _load_fixture(name: str, stems_dir: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    payload["stems_dir"] = stems_dir
    return payload


def _make_metering(
    stems: list[dict[str, Any]],
    *,
    mode: str = "basic",
) -> dict[str, Any]:
    """Build a minimal metering_report from a list of stem dicts."""
    lufs_vals = [s["lufs_i"] for s in stems if s.get("lufs_i") is not None]
    tp_vals = [s["true_peak_dbtp"] for s in stems if s.get("true_peak_dbtp") is not None]
    return {
        "mode": mode,
        "stems": stems,
        "session": {
            "stem_count": len(stems),
            "lufs_i_min": min(lufs_vals) if lufs_vals else None,
            "lufs_i_max": max(lufs_vals) if lufs_vals else None,
            "lufs_i_range_db": (
                round(max(lufs_vals) - min(lufs_vals), 3) if len(lufs_vals) >= 2 else None
            ),
            "true_peak_max_dbtp": max(tp_vals) if tp_vals else None,
        },
    }


def _write_stereo_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48_000,
    duration_s: float = 0.2,
    left_amplitude: float = 0.4,
    right_amplitude: float = 0.4,
    phase_offset_rad: float = 0.0,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for index in range(frames):
        phase = 2.0 * math.pi * 220.0 * index / sample_rate_hz
        left = int(left_amplitude * 32767.0 * math.sin(phase))
        right = int(right_amplitude * 32767.0 * math.sin(phase + phase_offset_rad))
        interleaved.extend((left, right))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


# ---------------------------------------------------------------------------
# Core contract tests
# ---------------------------------------------------------------------------

class TestSceneBuilderDeterminism(unittest.TestCase):
    def test_identical_calls_produce_equal_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            metering = json.loads((_FIXTURES / "stereo_metering.json").read_text(encoding="utf-8"))

            a = build_scene_from_session(
                session, metering, scene_id="SCENE.DET.TEST", lock_hash="abc123"
            )
            b = build_scene_from_session(
                session, metering, scene_id="SCENE.DET.TEST", lock_hash="abc123"
            )
            self.assertEqual(a, b)

    def test_objects_sorted_by_stem_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            scene = build_scene_from_session(session)
            ids = [o["stem_id"] for o in scene["objects"]]
            self.assertEqual(ids, sorted(ids))


class TestSceneBuilderSchemaValid(unittest.TestCase):
    def setUp(self) -> None:
        self._validator = _schema_validator(
            _REPO_ROOT / "schemas" / "scene.schema.json"
        )

    def _validate(self, scene: dict[str, Any]) -> None:
        self._validator.validate(scene)

    def test_stereo_session_no_metering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            scene = build_scene_from_session(session)
            self._validate(scene)

    def test_stereo_session_with_metering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            metering = json.loads((_FIXTURES / "stereo_metering.json").read_text(encoding="utf-8"))
            scene = build_scene_from_session(session, metering)
            self._validate(scene)

    def test_mono_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("mono_session.json", tmp)
            scene = build_scene_from_session(session)
            self._validate(scene)

    def test_surround_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("surround_session.json", tmp)
            scene = build_scene_from_session(session)
            self._validate(scene)

    def test_immersive_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("immersive_session.json", tmp)
            scene = build_scene_from_session(session)
            self._validate(scene)

    def test_object_source_metadata_tags_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {
                        "stem_id": "STEM.TAGS",
                        "file_path": "tags.wav",
                        "channel_count": 2,
                        "source_metadata": {
                            "technical": {
                                "channels": 2,
                                "sample_rate_hz": 48000,
                            },
                            "tags": {
                                "raw": [
                                    {
                                        "source": "format",
                                        "container": "wav",
                                        "scope": "info",
                                        "key": "INAM",
                                        "value": "Song",
                                        "index": 0,
                                    }
                                ],
                                "normalized": {"inam": ["Song"]},
                                "warnings": [],
                            },
                        },
                    }
                ],
            }
            scene = build_scene_from_session(session)
            self._validate(scene)
            source_metadata = scene["objects"][0].get("source_metadata")
            self.assertIsInstance(source_metadata, dict)
            if not isinstance(source_metadata, dict):
                return
            self.assertEqual(
                source_metadata.get("tags", {}).get("normalized", {}).get("inam"),
                ["Song"],
            )


class TestSceneBuilderConfidenceGating(unittest.TestCase):
    """Without metering, confidence=0 and no hints emitted."""

    def test_no_metering_yields_zero_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            scene = build_scene_from_session(session)
            for obj in scene["objects"]:
                self.assertEqual(obj["intent"]["confidence"], 0.0)
                self.assertNotIn("width", obj["intent"])
                self.assertNotIn("depth", obj["intent"])

    def test_no_metering_locks_still_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            scene = build_scene_from_session(session)
            for obj in scene["objects"]:
                self.assertEqual(obj["intent"]["locks"], [])


class TestSceneBuilderInference(unittest.TestCase):
    """With metering, width/depth hints are emitted at appropriate confidence."""

    def _stereo_scene_with_metering(self, correlation: float, crest_db: float) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.A", "file_path": "a.wav", "channel_count": 2, "label": "A"}
                ],
            }
            metering = _make_metering([
                {
                    "stem_id": "STEM.A",
                    "lufs_i": -18.0,
                    "true_peak_dbtp": -6.0,
                    "crest_db": crest_db,
                    "correlation": correlation,
                }
            ])
            return build_scene_from_session(session, metering)

    def test_high_correlation_yields_narrow_width(self) -> None:
        scene = self._stereo_scene_with_metering(correlation=0.90, crest_db=13.0)
        obj = scene["objects"][0]
        # Should emit width hint (high correlation → narrow)
        self.assertIn("width", obj["intent"])
        self.assertLessEqual(obj["intent"]["width"], 0.3)
        self.assertGreater(obj["intent"]["confidence"], 0.0)

    def test_low_correlation_yields_wide_width(self) -> None:
        scene = self._stereo_scene_with_metering(correlation=0.30, crest_db=13.0)
        obj = scene["objects"][0]
        self.assertIn("width", obj["intent"])
        self.assertGreaterEqual(obj["intent"]["width"], 0.7)

    def test_high_crest_yields_forward_depth(self) -> None:
        scene = self._stereo_scene_with_metering(correlation=0.70, crest_db=20.0)
        obj = scene["objects"][0]
        self.assertIn("depth", obj["intent"])
        self.assertLessEqual(obj["intent"]["depth"], 0.2)

    def test_low_crest_yields_diffuse_depth(self) -> None:
        scene = self._stereo_scene_with_metering(correlation=0.70, crest_db=5.0)
        obj = scene["objects"][0]
        self.assertIn("depth", obj["intent"])
        self.assertGreaterEqual(obj["intent"]["depth"], 0.65)

    def test_advisory_stereo_note_present(self) -> None:
        scene = self._stereo_scene_with_metering(correlation=0.70, crest_db=13.0)
        obj = scene["objects"][0]
        self.assertIn("advisory_stereo_stem", obj["notes"])

    def test_mono_stem_no_width_hint(self) -> None:
        """Mono stems have channel_count=1; width inference requires stereo."""
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.MONO", "file_path": "m.wav", "channel_count": 1, "label": "M"}
                ],
            }
            metering = _make_metering([
                {
                    "stem_id": "STEM.MONO",
                    "lufs_i": -20.0,
                    "true_peak_dbtp": -8.0,
                    "crest_db": 14.0,
                    "correlation": None,
                }
            ])
            scene = build_scene_from_session(session, metering)
            obj = scene["objects"][0]
            self.assertNotIn("width", obj["intent"])


class TestSceneBuilderStereoHintExtraction(unittest.TestCase):
    def test_wide_stereo_signal_emits_object_hints_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stem_path = stems_dir / "wide.wav"
            _write_stereo_wav(
                stem_path,
                left_amplitude=0.4,
                right_amplitude=0.4,
                phase_offset_rad=math.pi,
            )
            session: dict[str, Any] = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.WIDE",
                        "file_path": "wide.wav",
                        "channel_count": 2,
                        "label": "Wide",
                    }
                ],
            }

            scene = build_scene_from_session(session)
            obj = scene["objects"][0]
            self.assertGreater(obj.get("width_hint", 0.0), 0.0)
            self.assertIn("azimuth_hint", obj)

            stereo_hints = scene.get("metadata", {}).get("stereo_hints")
            self.assertIsInstance(stereo_hints, list)
            if not isinstance(stereo_hints, list):
                return
            self.assertEqual(len(stereo_hints), 1)
            evidence = stereo_hints[0]
            self.assertTrue(evidence.get("applied"))
            metric_ids = {
                item.get("metric_id")
                for item in evidence.get("metrics", [])
                if isinstance(item, dict)
            }
            self.assertIn("lr_correlation", metric_ids)
            self.assertIn("side_mid_ratio_db", metric_ids)
            self.assertIn("ild_weighted_db", metric_ids)

    def test_left_heavy_stereo_signal_infers_positive_azimuth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stem_path = stems_dir / "left_heavy.wav"
            _write_stereo_wav(
                stem_path,
                left_amplitude=0.55,
                right_amplitude=0.12,
            )
            session: dict[str, Any] = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.LEFT",
                        "file_path": "left_heavy.wav",
                        "channel_count": 2,
                        "label": "Left Heavy",
                    }
                ],
            }

            scene = build_scene_from_session(session)
            obj = scene["objects"][0]
            self.assertGreater(obj.get("azimuth_hint", 0.0), 0.0)


class TestSceneBuilderStereoAdvisory(unittest.TestCase):
    """Stereo-stem inference confidence is always capped."""

    def test_stereo_confidence_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.ST", "file_path": "s.wav", "channel_count": 2, "label": "S"}
                ],
            }
            metering = _make_metering([
                {
                    "stem_id": "STEM.ST",
                    "lufs_i": -18.0,
                    "true_peak_dbtp": -4.0,
                    "crest_db": 15.0,
                    "correlation": 0.95,
                }
            ])
            scene = build_scene_from_session(session, metering)
            obj = scene["objects"][0]
            self.assertLessEqual(obj["intent"]["confidence"], _ADVISORY_STEREO_CONF_CAP)


class TestSceneBuilderUserLocks(unittest.TestCase):
    """Explicit user locks propagate verbatim and are sorted."""

    def test_user_locks_propagate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.X", "file_path": "x.wav", "channel_count": 1, "label": "X"}
                ],
            }
            scene = build_scene_from_session(
                session,
                user_locks={"STEM.X": ["LOCK.POSITION", "LOCK.DYNAMICS"]},
            )
            obj = scene["objects"][0]
            self.assertEqual(obj["intent"]["locks"], ["LOCK.DYNAMICS", "LOCK.POSITION"])

    def test_no_user_locks_is_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.Y", "file_path": "y.wav", "channel_count": 1, "label": "Y"}
                ],
            }
            scene = build_scene_from_session(session)
            self.assertEqual(scene["objects"][0]["intent"]["locks"], [])


class TestSceneBuilderRoutingIntent(unittest.TestCase):
    """routing_intent is inferred from stem channel counts."""

    def _routing_for(self, channel_counts: list[int]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            stems = [
                {
                    "stem_id": f"STEM.{i:03d}",
                    "file_path": f"stem_{i}.wav",
                    "channel_count": ch,
                    "label": f"Stem {i}",
                }
                for i, ch in enumerate(channel_counts)
            ]
            session: dict[str, Any] = {"stems_dir": tmp, "stems": stems}
            scene = build_scene_from_session(session)
            return scene["routing_intent"]

    def test_mono_only_suggests_stereo(self) -> None:
        ri = self._routing_for([1, 1])
        self.assertEqual(ri["suggested_layout_class"], "stereo")
        self.assertIn("mono_stems_only", ri["notes"])

    def test_stereo_stems_suggest_stereo(self) -> None:
        ri = self._routing_for([2, 2])
        self.assertEqual(ri["suggested_layout_class"], "stereo")
        self.assertIn("stereo_stems_advisory", ri["notes"])

    def test_surround_stems_suggest_surround(self) -> None:
        ri = self._routing_for([6, 2])
        self.assertEqual(ri["suggested_layout_class"], "surround")

    def test_gt6ch_stem_suggests_immersive(self) -> None:
        ri = self._routing_for([7, 1])
        self.assertEqual(ri["suggested_layout_class"], "immersive")

    def test_routing_intent_has_confidence_in_range(self) -> None:
        for counts in ([1], [2], [6], [7]):
            ri = self._routing_for(counts)
            self.assertGreaterEqual(ri["confidence"], 0.0)
            self.assertLessEqual(ri["confidence"], 1.0)


class TestSceneBuilderSceneId(unittest.TestCase):
    def test_explicit_scene_id_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [
                    {"stem_id": "STEM.A", "file_path": "a.wav", "channel_count": 1, "label": "A"}
                ],
            }
            scene = build_scene_from_session(session, scene_id="SCENE.MY.ID")
            self.assertEqual(scene["scene_id"], "SCENE.MY.ID")

    def test_lock_hash_scene_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {
                "stems_dir": tmp,
                "stems": [],
            }
            scene = build_scene_from_session(session, lock_hash="abcdef123456789")
            self.assertEqual(scene["scene_id"], "SCENE.abcdef123456")

    def test_no_id_falls_back_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session: dict[str, Any] = {"stems_dir": tmp, "stems": []}
            scene = build_scene_from_session(session)
            self.assertEqual(scene["scene_id"], "SCENE.UNKNOWN")


class TestSceneBuilderErrors(unittest.TestCase):
    def test_non_dict_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_scene_from_session("not a dict")  # type: ignore[arg-type]

    def test_missing_stems_dir_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_scene_from_session({"stems": []})

    def test_relative_stems_dir_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_scene_from_session({"stems_dir": "relative/path", "stems": []})


class TestSceneBuilderMeteringInMetadata(unittest.TestCase):
    """Metering report is embedded in scene.metadata.metering when provided."""

    def test_metering_embedded_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            metering = json.loads((_FIXTURES / "stereo_metering.json").read_text(encoding="utf-8"))
            scene = build_scene_from_session(session, metering)
            self.assertIn("metering", scene["metadata"])
            self.assertEqual(scene["metadata"]["metering"]["mode"], "basic")

    def test_no_metering_absent_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            scene = build_scene_from_session(session)
            self.assertNotIn("metering", scene["metadata"])

    def test_object_meters_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _load_fixture("stereo_session.json", tmp)
            metering = json.loads((_FIXTURES / "stereo_metering.json").read_text(encoding="utf-8"))
            scene = build_scene_from_session(session, metering)
            obj_meters = scene["metadata"]["metering"].get("objects", [])
            stem_ids = {m["stem_id"] for m in obj_meters}
            # Only stems present in both session and metering should appear
            self.assertIn("STEM.BASS", stem_ids)
            self.assertIn("STEM.DRUMS", stem_ids)


if __name__ == "__main__":
    unittest.main()
