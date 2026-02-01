import os
import struct
import tempfile
import unittest
from itertools import chain
from pathlib import Path
from unittest import mock

from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd


class TestFfmpegDecode(unittest.TestCase):
    def _write_fake_ffmpeg(self, directory: Path, samples: list[float]) -> Path:
        script_path = directory / "fake_ffmpeg.py"
        payload = struct.pack(f"<{len(samples)}d", *samples)
        script_path.write_text(
            (
                "import sys\n"
                "def main() -> None:\n"
                f"    data = {payload!r}\n"
                "    sys.stdout.buffer.write(data)\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
            encoding="utf-8",
        )
        return script_path

    def test_iter_ffmpeg_float64_samples(self) -> None:
        samples = [0.0, 0.5, -0.25, 1.0, -1.0]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ffmpeg_path = self._write_fake_ffmpeg(temp_path, samples)
            dummy = temp_path / "dummy.flac"
            dummy.write_bytes(b"")
            with mock.patch.dict(os.environ, {"MMO_FFMPEG_PATH": str(ffmpeg_path)}):
                ffmpeg_cmd = resolve_ffmpeg_cmd()
                self.assertIsNotNone(ffmpeg_cmd)
                chunks = list(
                    iter_ffmpeg_float64_samples(dummy, ffmpeg_cmd, chunk_frames=2)
                )
        flattened = list(chain.from_iterable(chunks))
        self.assertEqual(len(flattened), len(samples))
        for value, target in zip(flattened, samples):
            self.assertAlmostEqual(value, target, places=12)


if __name__ == "__main__":
    unittest.main()
