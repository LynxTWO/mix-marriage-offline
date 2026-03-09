import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd, resolve_ffprobe_cmd


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

    def test_ffprobe_env_path_resolves_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "fake_ffprobe"
            temp_path.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"MMO_FFPROBE_PATH": str(temp_path)}):
                cmd = resolve_ffprobe_cmd()
        self.assertEqual(cmd, [str(temp_path)])

    def test_ffprobe_uses_sibling_of_ffmpeg_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            ffmpeg_path = temp_root / "ffmpeg"
            ffprobe_path = temp_root / "ffprobe"
            ffmpeg_path.write_text("", encoding="utf-8")
            ffprobe_path.write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"MMO_FFMPEG_PATH": str(ffmpeg_path), "MMO_FFPROBE_PATH": ""},
                clear=False,
            ):
                cmd = resolve_ffprobe_cmd()
        self.assertEqual(cmd, [str(ffprobe_path)])


if __name__ == "__main__":
    unittest.main()
