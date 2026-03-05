from __future__ import annotations

import os
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

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


def _write_fake_ffprobe(path: Path) -> None:
    path.write_text(
        """
import json
import sys
from pathlib import Path

_CODECS = {
    ".flac": "flac",
    ".wv": "wavpack",
    ".aiff": "pcm_s16be",
    ".aif": "pcm_s16be",
    ".ape": "ape",
    ".wav": "pcm_s16le",
}


def main() -> None:
    source = Path(sys.argv[-1])
    suffix = source.suffix.lower()
    sample_rate = 44100 if "44k1" in source.stem.lower() else 48000
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": _CODECS.get(suffix, "flac"),
                "channels": 1,
                "sample_rate": str(sample_rate),
                "duration": "0.1",
                "bits_per_raw_sample": "16",
                "channel_layout": "mono",
            }
        ],
        "format": {"duration": "0.1", "format_name": suffix.lstrip(".") or "unknown"},
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_ffmpeg(path: Path) -> None:
    path.write_text(
        """
import math
import struct
import sys


def main() -> None:
    sample_rate_hz = 48000
    frame_count = 4096
    values = [
        0.12 * math.sin(2.0 * math.pi * 330.0 * index / sample_rate_hz)
        for index in range(frame_count)
    ]
    sys.stdout.buffer.write(struct.pack(f"<{len(values)}d", *values))


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )


class TestMixdownRendererMultiformat(unittest.TestCase):
    def test_baseline_mixdown_renders_mixed_lossless_inputs_with_resampling_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "renders"
            ffprobe_path = temp_path / "fake_ffprobe.py"
            ffmpeg_path = temp_path / "fake_ffmpeg.py"

            _write_fake_ffprobe(ffprobe_path)
            _write_fake_ffmpeg(ffmpeg_path)

            _write_mono_wav(stems_dir / "stem_wav_48k.wav", sample_rate_hz=48000)
            (stems_dir / "stem_flac_44k1.flac").write_bytes(b"")
            (stems_dir / "stem_wv_44k1.wv").write_bytes(b"")
            (stems_dir / "stem_aiff_48k.aiff").write_bytes(b"")
            (stems_dir / "stem_ape_44k1.ape").write_bytes(b"")

            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {"stem_id": "STEM.WAV48", "file_path": "stem_wav_48k.wav"},
                    {"stem_id": "STEM.FLAC44", "file_path": "stem_flac_44k1.flac"},
                    {"stem_id": "STEM.WV44", "file_path": "stem_wv_44k1.wv"},
                    {"stem_id": "STEM.AIFF48", "file_path": "stem_aiff_48k.aiff"},
                    {"stem_id": "STEM.APE44", "file_path": "stem_ape_44k1.ape"},
                ],
            }

            with mock.patch.dict(
                os.environ,
                {
                    "MMO_FFPROBE_PATH": str(ffprobe_path),
                    "MMO_FFMPEG_PATH": str(ffmpeg_path),
                },
                clear=False,
            ):
                renderer = MixdownRenderer()
                manifest = renderer.render(session, [], out_dir)

            outputs = manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return
            stereo_row = next(
                (
                    row
                    for row in outputs
                    if isinstance(row, dict) and row.get("layout_id") == "LAYOUT.2_0"
                ),
                None,
            )
            self.assertIsInstance(stereo_row, dict)
            if not isinstance(stereo_row, dict):
                return

            self.assertEqual(stereo_row.get("sample_rate_hz"), 44100)
            rendered_path = out_dir / Path(str(stereo_row.get("file_path", "")))
            self.assertTrue(rendered_path.exists())
            self.assertGreater(rendered_path.stat().st_size, 44)

            metadata = stereo_row.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertEqual(metadata.get("source_stem_count"), 5)
            resampling = metadata.get("resampling")
            self.assertIsInstance(resampling, dict)
            if not isinstance(resampling, dict):
                return
            self.assertEqual(resampling.get("target_sample_rate_hz"), 44100)
            selection = resampling.get("selection")
            self.assertIsInstance(selection, dict)
            if isinstance(selection, dict):
                self.assertEqual(selection.get("selection_reason"), "majority")


if __name__ == "__main__":
    unittest.main()
