import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd


class TestFfmpegDiscovery(unittest.TestCase):
    def test_env_path_resolves_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "fake_ffmpeg"
            temp_path.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"MMO_FFMPEG_PATH": str(temp_path)}):
                cmd = resolve_ffmpeg_cmd()
        self.assertEqual(cmd, [str(temp_path)])

    def test_env_path_py_invokes_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "fake_ffmpeg.py"
            temp_path.write_text("print('ok')\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"MMO_FFMPEG_PATH": str(temp_path)}):
                cmd = resolve_ffmpeg_cmd()
        self.assertEqual(cmd, [sys.executable, str(temp_path)])


if __name__ == "__main__":
    unittest.main()
