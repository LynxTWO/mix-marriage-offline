import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.dsp.decoders import read_metadata


class TestFfprobeMetadata(unittest.TestCase):
    def _write_fake_ffprobe(self, directory: Path) -> Path:
        script_path = directory / "fake_ffprobe.py"
        script_path.write_text(
            """
import json
import os
import sys


def main() -> None:
    path = sys.argv[-1]
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".flac":
        payload = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "channels": 2,
                    "sample_rate": "48000",
                    "duration": "2.5",
                    "bits_per_raw_sample": "24",
                }
            ],
            "format": {"duration": "2.5"},
        }
    elif suffix == ".m4a":
        payload = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "AAC",
                    "channels": 1,
                    "sample_rate": "44100",
                }
            ],
            "format": {"duration": "1.25"},
        }
    else:
        payload = {"streams": [], "format": {}}
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
""".lstrip(),
            encoding="utf-8",
        )
        return script_path

    def test_ffprobe_metadata_flac_and_m4a(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ffprobe_path = self._write_fake_ffprobe(temp_path)
            flac_path = temp_path / "test.flac"
            flac_path.write_bytes(b"")
            m4a_path = temp_path / "test.m4a"
            m4a_path.write_bytes(b"")

            with mock.patch.dict(os.environ, {"MMO_FFPROBE_PATH": str(ffprobe_path)}):
                flac_meta = read_metadata(flac_path)
                m4a_meta = read_metadata(m4a_path)
                flac_meta_again = read_metadata(flac_path)

            self.assertEqual(flac_meta, flac_meta_again)
            self.assertEqual(flac_meta["channels"], 2)
            self.assertEqual(flac_meta["sample_rate_hz"], 48000)
            self.assertAlmostEqual(flac_meta["duration_s"], 2.5, places=6)
            self.assertEqual(flac_meta["bits_per_sample"], 24)
            self.assertEqual(flac_meta["codec_name"], "flac")

            self.assertEqual(m4a_meta["channels"], 1)
            self.assertEqual(m4a_meta["sample_rate_hz"], 44100)
            self.assertAlmostEqual(m4a_meta["duration_s"], 1.25, places=6)
            self.assertEqual(m4a_meta["codec_name"], "aac")


if __name__ == "__main__":
    unittest.main()
