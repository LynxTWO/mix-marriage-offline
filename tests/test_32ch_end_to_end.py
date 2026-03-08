from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from mmo.dsp.io import sha256_file
from mmo.plugins.renderers.placement_mixdown_renderer import PlacementMixdownRenderer


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48_000,
    duration_s: float = 0.12,
    freq_hz: float = 220.0,
    amplitude: float = 0.2,
) -> None:
    frame_count = int(sample_rate_hz * duration_s)
    values = [
        int(
            amplitude
            * 32767.0
            * math.sin(2.0 * math.pi * freq_hz * index / sample_rate_hz)
        )
        for index in range(frame_count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))


def _scene_payload(stems_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.RENDER.32CH",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "test",
        },
        "intent": {
            "confidence": 0.0,
            "locks": [],
        },
        "objects": [
            {
                "object_id": "OBJ.STEM.MONO",
                "stem_id": "STEM.MONO",
                "role_id": "ROLE.SYNTH.LEAD",
                "group_bus": "BUS.MUSIC",
                "label": "Mono Stem",
                "channel_count": 1,
                "width_hint": 0.2,
                "depth_hint": 0.3,
                "confidence": 0.95,
                "intent": {
                    "confidence": 0.95,
                    "width": 0.2,
                    "depth": 0.3,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "beds": [],
        "metadata": {},
    }


def _render_once(stems_dir: Path, output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    renderer = PlacementMixdownRenderer()
    session = {
        "report_id": "REPORT.RENDER.32CH.E2E.001",
        "render_seed": 32,
        "stems_dir": stems_dir.resolve().as_posix(),
        "stems": [
            {
                "stem_id": "STEM.MONO",
                "file_path": "mono.wav",
                "channel_count": 1,
                "sample_rate_hz": 48_000,
            }
        ],
        "scene_payload": _scene_payload(stems_dir),
        "render_export_options": {
            "export_layout_ids": ["LAYOUT.32CH"],
        },
    }
    manifest = renderer.render(session, [], output_dir)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise AssertionError("renderer manifest missing outputs list")
    if len(outputs) != 1 or not isinstance(outputs[0], dict):
        raise AssertionError(f"expected exactly one output row, got {outputs!r}")
    output_row = outputs[0]
    output_path = output_dir / Path(str(output_row.get("file_path", "")))
    return manifest, output_row, output_path


class Test32ChEndToEnd(unittest.TestCase):
    def test_placement_renderer_exports_deterministic_32ch_wav_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            _write_mono_wav(stems_dir / "mono.wav")

            manifest_a, output_a, output_path_a = _render_once(
                stems_dir,
                temp_path / "run_a",
            )
            manifest_b, output_b, output_path_b = _render_once(
                stems_dir,
                temp_path / "run_b",
            )

            self.assertEqual(
                manifest_a.get("renderer_id"),
                "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1",
            )
            self.assertTrue(output_path_a.exists())
            self.assertTrue(output_path_b.exists())
            self.assertEqual(output_a.get("layout_id"), "LAYOUT.32CH")
            self.assertEqual(output_a.get("channel_count"), 32)
            self.assertEqual(output_a.get("sha256"), output_b.get("sha256"))
            self.assertEqual(output_a.get("sha256"), sha256_file(output_path_a))
            self.assertEqual(output_b.get("sha256"), sha256_file(output_path_b))

            metadata = output_a.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            channel_order = metadata.get("channel_order")
            self.assertIsInstance(channel_order, list)
            if not isinstance(channel_order, list):
                return
            self.assertEqual(len(channel_order), 32)
            self.assertEqual(channel_order[0], "SPK.CH01")
            self.assertEqual(channel_order[-1], "SPK.CH32")

            with wave.open(str(output_path_a), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 32)
                self.assertEqual(handle.getframerate(), 48_000)
                payload = handle.readframes(min(handle.getnframes(), 128))
            self.assertTrue(any(payload), "rendered 32-channel payload should not be silent")


if __name__ == "__main__":
    unittest.main()
