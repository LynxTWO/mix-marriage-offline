from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from mmo.core.precedence import (
    PRECEDENCE_GATE_ID,
    apply_precedence,
    apply_recommendation_precedence,
)
from mmo.core.scene_templates import apply_scene_templates
from mmo.plugins.renderers.placement_mixdown_renderer import PlacementMixdownRenderer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAR_AND_WIDE_CHANNELS = {
    "SPK.LS",
    "SPK.RS",
    "SPK.LRS",
    "SPK.RRS",
    "SPK.LW",
    "SPK.RW",
}
_OVERHEAD_CHANNELS = {
    "SPK.TFL",
    "SPK.TFR",
    "SPK.TRL",
    "SPK.TRR",
    "SPK.TFC",
    "SPK.TBC",
}


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.12,
    freq_hz: float = 220.0,
    amplitude: float = 0.24,
) -> None:
    frame_count = int(sample_rate_hz * duration_s)
    samples: list[int] = []
    for index in range(frame_count):
        sample = int(
            amplitude
            * 32767.0
            * math.sin(2.0 * math.pi * freq_hz * index / sample_rate_hz)
        )
        samples.append(sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _field_bed() -> dict[str, Any]:
    return {
        "bed_id": "BED.FIELD.001",
        "label": "Field",
        "kind": "field",
        "intent": {
            "diffuse": 0.5,
            "confidence": 0.0,
            "locks": [],
        },
        "notes": [],
    }


def _object_entry(
    stem_id: str,
    *,
    role_id: str | None = None,
    bus_id: str | None = None,
    group_bus: str | None = None,
    width: float = 0.35,
    depth: float = 0.3,
    azimuth_deg: float | None = None,
    locks: list[str] | None = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "object_id": f"OBJ.{stem_id}",
        "stem_id": stem_id,
        "label": stem_id,
        "channel_count": 1,
        "confidence": 0.95,
        "intent": {
            "confidence": 0.95,
            "width": width,
            "depth": depth,
            "locks": list(locks or []),
        },
        "width_hint": width,
        "depth_hint": depth,
        "notes": [],
    }
    if role_id is not None:
        obj["role_id"] = role_id
    if bus_id is not None:
        obj["bus_id"] = bus_id
    if group_bus is not None:
        obj["group_bus"] = group_bus
    if azimuth_deg is not None:
        obj["azimuth_hint"] = azimuth_deg
        obj["intent"]["position"] = {"azimuth_deg": azimuth_deg}
    return obj


def _bed_entry(
    stem_id: str,
    *,
    bed_id: str = "BED.AMB",
    bus_id: str = "BUS.FX.AMBIENCE",
    content_hint: str = "ambience",
    diffuse: float = 0.96,
    height_send_caps: dict[str, float] | None = None,
    locks: list[str] | None = None,
) -> dict[str, Any]:
    bed: dict[str, Any] = {
        "bed_id": bed_id,
        "label": "Ambience Bed",
        "kind": "bed",
        "bus_id": bus_id,
        "stem_ids": [stem_id],
        "content_hint": content_hint,
        "width_hint": diffuse,
        "confidence": 0.92,
        "intent": {
            "diffuse": diffuse,
            "confidence": 0.92,
            "locks": list(locks or []),
        },
        "notes": [f"content_hint: {content_hint}"],
    }
    if height_send_caps is not None:
        bed["intent"]["height_send_caps"] = _json_clone(height_send_caps)
    return bed


def _scene_payload(
    stems_dir: Path,
    *,
    perspective: str | None = None,
    objects: list[dict[str, Any]] | None = None,
    beds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scene: dict[str, Any] = {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.LOCK.PRECEDENCE",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "draft",
        },
        "intent": {
            "confidence": 0.0,
            "locks": [],
        },
        "objects": objects or [],
        "beds": beds if beds is not None else [_field_bed()],
        "metadata": {},
    }
    if perspective is not None:
        scene["intent"]["perspective"] = perspective
    return scene


def _render_scene(
    *,
    scene_payload: dict[str, Any],
    stems_dir: Path,
    stems: list[dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    session = {
        "stems_dir": stems_dir.resolve().as_posix(),
        "stems": stems,
        "scene_payload": scene_payload,
    }
    renderer = PlacementMixdownRenderer()
    return renderer.render(session, [], out_dir)


def _output_by_layout(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return {}
    return {
        row.get("layout_id"): row
        for row in outputs
        if isinstance(row, dict) and isinstance(row.get("layout_id"), str)
    }


def _stem_summary(
    manifest: dict[str, Any],
    *,
    layout_id: str,
    stem_id: str,
) -> dict[str, Any]:
    by_layout = _output_by_layout(manifest)
    layout_row = by_layout.get(layout_id)
    if not isinstance(layout_row, dict):
        raise AssertionError(f"missing layout output: {layout_id}")
    metadata = layout_row.get("metadata")
    if not isinstance(metadata, dict):
        raise AssertionError(f"missing metadata for {layout_id}")
    stem_rows = metadata.get("stem_send_summary")
    if not isinstance(stem_rows, list):
        raise AssertionError(f"missing stem_send_summary for {layout_id}")
    for row in stem_rows:
        if isinstance(row, dict) and row.get("stem_id") == stem_id:
            return row
    raise AssertionError(f"missing stem summary for {stem_id} in {layout_id}")


def _precedence_entry(
    scene_payload: dict[str, Any],
    *,
    scope: str,
    field: str,
    stem_id: str | None = None,
    bed_id: str | None = None,
) -> dict[str, Any]:
    metadata = scene_payload.get("metadata")
    if not isinstance(metadata, dict):
        raise AssertionError("missing scene metadata")
    receipt = metadata.get("precedence_receipt")
    if not isinstance(receipt, dict):
        raise AssertionError("missing precedence_receipt")
    entries = receipt.get("entries")
    if not isinstance(entries, list):
        raise AssertionError("missing precedence_receipt entries")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("scope") != scope or entry.get("field") != field:
            continue
        if stem_id is not None and entry.get("stem_id") != stem_id:
            continue
        if bed_id is not None and entry.get("bed_id") != bed_id:
            continue
        return entry
    raise AssertionError(f"missing precedence entry for {scope}.{field}")


class TestLockPrecedenceMatrix(unittest.TestCase):
    def test_role_override_locked_beats_suggested_role_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "lead.wav", freq_hz=330.0)

            base_scene = _scene_payload(
                stems_dir,
                perspective="in_orchestra",
                objects=[_object_entry("STEM.LEAD")],
            )
            suggested_scene = _json_clone(base_scene)
            suggested_scene["objects"][0]["role_id"] = "ROLE.BRASS.HORN"

            merged_scene = apply_precedence(
                base_scene,
                {
                    "version": "0.1.0",
                    "overrides": {
                        "STEM.LEAD": {
                            "role_id": "ROLE.VOCAL.LEAD",
                        }
                    },
                },
                {"suggested": suggested_scene},
            )

            entry = _precedence_entry(
                merged_scene,
                scope="object",
                field="role_id",
                stem_id="STEM.LEAD",
            )
            self.assertEqual(entry.get("source"), "locked")
            self.assertEqual(entry.get("original_value"), "ROLE.BRASS.HORN")
            self.assertEqual(entry.get("applied_value"), "ROLE.VOCAL.LEAD")
            self.assertEqual(
                entry.get("lock_id"),
                "scene_build_override:STEM.LEAD:role_id",
            )

            manifest = _render_scene(
                scene_payload=merged_scene,
                stems_dir=stems_dir,
                stems=[
                    {
                        "stem_id": "STEM.LEAD",
                        "file_path": "lead.wav",
                        "channel_count": 1,
                    }
                ],
                out_dir=temp / "renders_role",
            )
            row = _stem_summary(manifest, layout_id="LAYOUT.7_1_4", stem_id="STEM.LEAD")
            notes = set(row.get("notes") or [])
            nonzero = set(row.get("nonzero_channels") or [])
            self.assertIn("role_source:locked", notes)
            self.assertIn("SPK.C", nonzero)
            self.assertFalse(nonzero & _REAR_AND_WIDE_CHANNELS)

    def test_bus_override_locked_beats_suggested_bus_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "vox.wav", freq_hz=260.0)

            base_scene = _scene_payload(
                stems_dir,
                objects=[
                    _object_entry(
                        "STEM.VOX",
                        role_id="ROLE.VOCAL.LEAD",
                        group_bus="BUS.OTHER",
                    )
                ],
            )
            suggested_scene = _json_clone(base_scene)
            suggested_scene["objects"][0]["bus_id"] = "BUS.FX.REVERB"
            suggested_scene["objects"][0]["group_bus"] = "BUS.FX"

            merged_scene = apply_precedence(
                base_scene,
                {
                    "version": "0.1.0",
                    "overrides": {
                        "STEM.VOX": {
                            "bus_id": "BUS.VOX.LEAD",
                        }
                    },
                },
                {"suggested": suggested_scene},
            )

            entry = _precedence_entry(
                merged_scene,
                scope="object",
                field="bus_id",
                stem_id="STEM.VOX",
            )
            self.assertEqual(entry.get("source"), "locked")
            self.assertEqual(entry.get("original_value"), "BUS.FX.REVERB")
            self.assertEqual(entry.get("applied_value"), "BUS.VOX.LEAD")
            self.assertEqual(
                entry.get("lock_id"),
                "scene_build_override:STEM.VOX:bus_id",
            )
            self.assertEqual(merged_scene["objects"][0].get("group_bus"), "BUS.VOX")

            manifest = _render_scene(
                scene_payload=merged_scene,
                stems_dir=stems_dir,
                stems=[
                    {
                        "stem_id": "STEM.VOX",
                        "file_path": "vox.wav",
                        "channel_count": 1,
                    }
                ],
                out_dir=temp / "renders_bus",
            )
            row = _stem_summary(manifest, layout_id="LAYOUT.5_1", stem_id="STEM.VOX")
            self.assertIn("bus_source:locked", set(row.get("notes") or []))

    def test_locked_azimuth_survives_placement_policy_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "horn.wav", freq_hz=196.0)

            base_scene = _scene_payload(
                stems_dir,
                perspective="in_orchestra",
                objects=[
                    _object_entry(
                        "STEM.HORN",
                        role_id="ROLE.BRASS.HORN",
                        group_bus="BUS.MUSIC",
                    )
                ],
            )

            merged_scene = apply_precedence(
                base_scene,
                {
                    "version": "0.1.0",
                    "overrides": {
                        "STEM.HORN": {
                            "placement": {
                                "azimuth_deg": 0.0,
                            }
                        }
                    },
                },
                None,
            )

            entry = _precedence_entry(
                merged_scene,
                scope="object",
                field="azimuth_deg",
                stem_id="STEM.HORN",
            )
            self.assertEqual(entry.get("source"), "locked")
            self.assertEqual(entry.get("applied_value"), 0.0)
            self.assertEqual(
                entry.get("lock_id"),
                "scene_build_override:STEM.HORN:placement.azimuth_deg",
            )

            manifest = _render_scene(
                scene_payload=merged_scene,
                stems_dir=stems_dir,
                stems=[
                    {
                        "stem_id": "STEM.HORN",
                        "file_path": "horn.wav",
                        "channel_count": 1,
                    }
                ],
                out_dir=temp / "renders_azimuth",
            )
            row = _stem_summary(manifest, layout_id="LAYOUT.7_1_4", stem_id="STEM.HORN")
            notes = set(row.get("notes") or [])
            nonzero = set(row.get("nonzero_channels") or [])
            self.assertIn("azimuth_source:locked", notes)
            self.assertIn("azimuth_deg:0.000", notes)
            self.assertFalse(nonzero & _REAR_AND_WIDE_CHANNELS)

    def test_locked_bed_caps_block_widening_and_height_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "amb.wav", freq_hz=480.0)

            base_scene = _scene_payload(
                stems_dir,
                beds=[
                    _bed_entry(
                        "STEM.AMB",
                        height_send_caps={
                            "top_max_gain": 0.0,
                            "top_front_max_gain": 0.0,
                            "top_rear_max_gain": 0.0,
                        },
                        locks=["LOCK.NO_HEIGHT_SEND", "LOCK.NO_STEREO_WIDENING"],
                    )
                ],
            )
            suggested_scene = _json_clone(base_scene)
            suggested_scene["beds"][0]["intent"]["diffuse"] = 0.99
            suggested_scene["beds"][0]["width_hint"] = 0.99
            suggested_scene["beds"][0]["intent"]["height_send_caps"] = {
                "top_max_gain": 0.14,
                "top_front_max_gain": 0.14,
                "top_rear_max_gain": 0.12,
            }

            merged_scene = apply_precedence(
                base_scene,
                None,
                {"suggested": suggested_scene},
            )

            entry = _precedence_entry(
                merged_scene,
                scope="bed",
                field="height_send_caps",
                bed_id="BED.AMB",
            )
            self.assertEqual(entry.get("source"), "locked")
            self.assertEqual(
                entry.get("applied_value"),
                {
                    "top_max_gain": 0.0,
                    "top_front_max_gain": 0.0,
                    "top_rear_max_gain": 0.0,
                },
            )
            self.assertEqual(entry.get("lock_id"), "LOCK.NO_HEIGHT_SEND")

            recommendations = [
                {
                    "recommendation_id": "REC.BED.WIDEN",
                    "action_id": "ACTION.STEREO.WIDEN",
                    "scope": {"bed_id": "BED.AMB"},
                    "eligible_auto_apply": True,
                    "eligible_render": True,
                },
                {
                    "recommendation_id": "REC.BED.PAN",
                    "action_id": "ACTION.UTILITY.PAN",
                    "scope": {"bed_id": "BED.AMB"},
                    "eligible_auto_apply": True,
                    "eligible_render": True,
                },
            ]
            apply_recommendation_precedence(merged_scene, recommendations)
            for rec in recommendations:
                self.assertFalse(rec.get("eligible_auto_apply"))
                self.assertFalse(rec.get("eligible_render"))
                gate_ids = {
                    result.get("gate_id")
                    for result in rec.get("gate_results", [])
                    if isinstance(result, dict)
                }
                self.assertIn(PRECEDENCE_GATE_ID, gate_ids)

            widen_conflicts = recommendations[0].get("precedence_conflicts")
            self.assertEqual(
                [
                    conflict.get("lock_id")
                    for conflict in widen_conflicts
                    if isinstance(conflict, dict)
                ],
                ["LOCK.NO_STEREO_WIDENING"],
            )
            pan_conflicts = recommendations[1].get("precedence_conflicts")
            self.assertEqual(
                [
                    conflict.get("lock_id")
                    for conflict in pan_conflicts
                    if isinstance(conflict, dict)
                ],
                ["LOCK.NO_HEIGHT_SEND"],
            )

            manifest = _render_scene(
                scene_payload=merged_scene,
                stems_dir=stems_dir,
                stems=[
                    {
                        "stem_id": "STEM.AMB",
                        "file_path": "amb.wav",
                        "channel_count": 1,
                    }
                ],
                out_dir=temp / "renders_bed",
            )
            row = _stem_summary(manifest, layout_id="LAYOUT.9_1_6", stem_id="STEM.AMB")
            nonzero = set(row.get("nonzero_channels") or [])
            self.assertFalse(nonzero & _REAR_AND_WIDE_CHANNELS)
            self.assertFalse(nonzero & _OVERHEAD_CHANNELS)

    def test_scene_perspective_lock_beats_template_suggestion_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "brass.wav", freq_hz=247.0)

            base_scene = _scene_payload(
                stems_dir,
                objects=[
                    _object_entry(
                        "STEM.BRASS",
                        role_id="ROLE.BRASS.HORN",
                        group_bus="BUS.MUSIC",
                    )
                ],
            )
            suggested_scene = apply_scene_templates(
                _json_clone(base_scene),
                ["TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA"],
                scene_templates_path=_REPO_ROOT / "ontology" / "scene_templates.yaml",
                scene_locks_path=_REPO_ROOT / "ontology" / "scene_locks.yaml",
            )

            merged_scene = apply_precedence(
                base_scene,
                {
                    "version": "0.1.0",
                    "scene": {"perspective": "audience"},
                    "overrides": {},
                },
                {"suggested": suggested_scene},
            )

            entry = _precedence_entry(
                merged_scene,
                scope="scene",
                field="perspective",
            )
            self.assertEqual(entry.get("source"), "locked")
            self.assertEqual(entry.get("original_value"), "in_orchestra")
            self.assertEqual(entry.get("applied_value"), "audience")
            self.assertEqual(
                entry.get("lock_id"),
                "scene_build_override:scene:perspective",
            )

            manifest = _render_scene(
                scene_payload=merged_scene,
                stems_dir=stems_dir,
                stems=[
                    {
                        "stem_id": "STEM.BRASS",
                        "file_path": "brass.wav",
                        "channel_count": 1,
                    }
                ],
                out_dir=temp / "renders_perspective",
            )
            row = _stem_summary(manifest, layout_id="LAYOUT.7_1_4", stem_id="STEM.BRASS")
            notes = set(row.get("notes") or [])
            nonzero = set(row.get("nonzero_channels") or [])
            self.assertNotIn("immersive_perspective:in_orchestra", notes)
            self.assertFalse(nonzero & {"SPK.LRS", "SPK.RRS"})


if __name__ == "__main__":
    unittest.main()
