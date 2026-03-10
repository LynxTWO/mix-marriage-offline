from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from mmo.core.trace_metadata import build_trace_metadata
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.plugins.renderers.mixdown_renderer import MixdownRenderer


def _write_mono_wav(path: Path, *, sample_rate_hz: int = 48000) -> None:
    frame_count = int(sample_rate_hz * 0.1)
    values = [
        int(0.2 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
        for index in range(frame_count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))


def _riff_chunks(path: Path) -> dict[str, bytes]:
    payload = path.read_bytes()
    if payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise AssertionError(f"not a RIFF/WAVE file: {path}")

    chunks: dict[str, bytes] = {}
    cursor = 12
    while cursor + 8 <= len(payload):
        chunk_id = payload[cursor : cursor + 4].decode("ascii", errors="replace")
        chunk_size = struct.unpack("<I", payload[cursor + 4 : cursor + 8])[0]
        start = cursor + 8
        end = start + chunk_size
        chunks[chunk_id] = payload[start:end]
        cursor = end + (chunk_size % 2)
    return chunks


def _trace_fields_from_ixml(ixml_payload: bytes) -> dict[str, str]:
    root = ET.fromstring(ixml_payload.rstrip(b"\x00").decode("utf-8"))
    trace_parent = None
    for element in root.iter():
        if element.tag.split("}", 1)[-1].upper() == "MMO_TRACE":
            trace_parent = element
            break
    if trace_parent is None:
        return {}
    return {
        child.tag.split("}", 1)[-1].lower(): (child.text or "").strip()
        for child in trace_parent
        if (child.text or "").strip()
    }


class TestWavTraceMetadata(unittest.TestCase):
    def test_mixdown_renderer_embeds_trace_ixml_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_a = temp_path / "render_a"
            out_b = temp_path / "render_b"
            _write_mono_wav(stems_dir / "stem.wav")

            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "render_seed": 11,
                "profile_id": "PROFILE.ASSIST",
                "stems": [
                    {
                        "stem_id": "STEM.001",
                        "file_path": "stem.wav",
                    }
                ],
            }

            renderer = MixdownRenderer()
            manifest_a = renderer.render(session, [], out_a)
            manifest_b = renderer.render(session, [], out_b)

            outputs_a = manifest_a.get("outputs", [])
            outputs_b = manifest_b.get("outputs", [])
            self.assertIsInstance(outputs_a, list)
            self.assertIsInstance(outputs_b, list)
            if not isinstance(outputs_a, list) or not isinstance(outputs_b, list):
                return

            stereo_a = next(row for row in outputs_a if row.get("layout_id") == "LAYOUT.2_0")
            stereo_b = next(row for row in outputs_b if row.get("layout_id") == "LAYOUT.2_0")
            path_a = out_a / Path(str(stereo_a["file_path"]))
            path_b = out_b / Path(str(stereo_b["file_path"]))

            self.assertEqual(sha256_file(path_a), sha256_file(path_b))

            chunks = _riff_chunks(path_a)
            self.assertIn("iXML", chunks)
            trace_fields = _trace_fields_from_ixml(chunks["iXML"])
            expected = build_trace_metadata(
                {
                    "session": session,
                    "layout_id": "LAYOUT.2_0",
                    "render_seed": 11,
                }
            )
            self.assertEqual(trace_fields, expected)

            metadata = read_wav_metadata(path_a)
            normalized = metadata.get("tags", {}).get("normalized", {})
            self.assertEqual(normalized.get("mmo_version"), [expected["mmo_version"]])
            self.assertEqual(normalized.get("scene_sha256"), [expected["scene_sha256"]])
            self.assertEqual(normalized.get("render_contract_version"), [expected["render_contract_version"]])
            self.assertEqual(normalized.get("downmix_policy_version"), [expected["downmix_policy_version"]])
            self.assertEqual(normalized.get("layout_id"), ["LAYOUT.2_0"])
            self.assertEqual(normalized.get("profile_id"), ["PROFILE.ASSIST"])
            self.assertEqual(normalized.get("export_profile_id"), ["PROFILE.ASSIST"])
            self.assertEqual(normalized.get("seed"), ["11"])


if __name__ == "__main__":
    unittest.main()
