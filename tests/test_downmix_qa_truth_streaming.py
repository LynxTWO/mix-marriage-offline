import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.core.downmix_qa import run_downmix_qa


def _write_fake_ffprobe(
    directory: Path, *, ref_channels: int = 2, duration_s: str = "0.5"
) -> Path:
    script_path = directory / "fake_ffprobe.py"
    script_path.write_text(
        (
            "import json\n"
            "import os\n"
            "import sys\n"
            "\n"
            "def main() -> None:\n"
            "    path = sys.argv[-1]\n"
            "    name = os.path.basename(path)\n"
            "    if name.startswith('src'):\n"
            "        payload = {\n"
            "            'streams': [\n"
            "                {\n"
            "                    'codec_type': 'audio',\n"
            "                    'codec_name': 'flac',\n"
            "                    'channels': 6,\n"
            "                    'sample_rate': '48000',\n"
            f"                    'duration': '{duration_s}',\n"
            "                    'channel_layout': '5.1(side)',\n"
            "                }\n"
            "            ],\n"
            f"            'format': {{'duration': '{duration_s}'}},\n"
            "        }\n"
            "    else:\n"
            f"        payload = {{\n"
            f"            'streams': [\n"
            f"                {{\n"
            f"                    'codec_type': 'audio',\n"
            f"                    'codec_name': 'wav',\n"
            f"                    'channels': {ref_channels},\n"
            f"                    'sample_rate': '48000',\n"
            f"                    'duration': '{duration_s}',\n"
            f"                    'channel_layout': 'stereo',\n"
            f"                }}\n"
            f"            ],\n"
            f"            'format': {{'duration': '{duration_s}'}},\n"
            f"        }}\n"
            "    print(json.dumps(payload))\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )
    return script_path


def _write_fake_ffmpeg(directory: Path) -> Path:
    script_path = directory / "fake_ffmpeg.py"
    script_path.write_text(
        (
            "import os\n"
            "import struct\n"
            "import sys\n"
            "\n"
            "def main() -> None:\n"
            "    args = sys.argv[1:]\n"
            "    path = args[args.index('-i') + 1] if '-i' in args else args[-1]\n"
            "    name = os.path.basename(path)\n"
            "    frames = 24000\n"
            "    if name.startswith('src'):\n"
            "        samples = [0.1, 0.1, 0.0, 0.0, 0.0, 0.0] * frames\n"
            "    else:\n"
            "        samples = [0.1, 0.1] * frames\n"
            "    payload = struct.pack(f'<{len(samples)}d', *samples)\n"
            "    sys.stdout.buffer.write(payload)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )
    return script_path


class TestDownmixQaTruthStreaming(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("numpy not available")

    def _run_truth_qa(self, *, duration_s: str = "0.5") -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            src_path = temp_path / "src.flac"
            ref_path = temp_path / "ref.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = _write_fake_ffprobe(temp_path, ref_channels=2, duration_s=duration_s)
            ffmpeg_path = _write_fake_ffmpeg(temp_path)

            env = {
                "MMO_FFMPEG_PATH": str(ffmpeg_path),
                "MMO_FFPROBE_PATH": str(ffprobe_path),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                return run_downmix_qa(
                    src_path,
                    ref_path,
                    source_layout_id="LAYOUT.5_1",
                    target_layout_id="LAYOUT.2_0",
                    policy_id=None,
                    tolerance_lufs=1.0,
                    tolerance_true_peak_db=1.0,
                    tolerance_corr=0.15,
                    repo_root=repo_root,
                    meters="truth",
                    max_seconds=0.25,
                )

    def test_truth_streaming_path_used(self) -> None:
        self._skip_if_no_numpy()
        with mock.patch(
            "mmo.core.downmix_qa._truth_metrics_from_interleaved",
            side_effect=AssertionError("offline truth path should not be used"),
        ):
            payload = self._run_truth_qa()
        self.assertIn("downmix_qa", payload)
        self.assertEqual(payload["downmix_qa"].get("issues"), [])

    def test_truth_max_seconds_logged_with_long_metadata(self) -> None:
        self._skip_if_no_numpy()
        payload = self._run_truth_qa(duration_s="3600.0")
        log_payload = json.loads(payload["downmix_qa"]["log"])
        self.assertEqual(log_payload.get("seconds_compared"), 0.25)
        self.assertEqual(log_payload.get("max_seconds"), 0.25)
        self.assertEqual(log_payload.get("sample_rate_hz"), 48000)


class TestTruthMetersStreamingMath(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("numpy not available")

    def _chunked(self, array, chunk_frames):
        for start in range(0, array.shape[0], chunk_frames):
            yield array[start : start + chunk_frames]

    def test_online_lufs_matches_offline(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp import meters_truth

        rng = np.random.RandomState(0)
        data = rng.randn(2048, 2).astype(np.float64) * 0.1
        offline = meters_truth.compute_lufs_integrated_float64(
            data,
            48000,
            2,
            channel_mask=None,
            channel_layout="stereo",
        )
        for chunk_size in (1, 127):
            online = meters_truth.OnlineLufsIntegrated(
                48000,
                channels=2,
                channel_mask=None,
                channel_layout="stereo",
            )
            for chunk in self._chunked(data, chunk_size):
                online.update(chunk)
            self.assertAlmostEqual(offline, online.finalize(), places=9)

    def test_online_true_peak_matches_offline(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp import meters_truth

        rng = np.random.RandomState(1)
        data = rng.randn(2048, 2).astype(np.float64) * 0.1
        for sample_rate_hz in (48000, 44100):
            offline = meters_truth.compute_true_peak_dbtp_float64(data, sample_rate_hz)
            for chunk_size in (7, 255):
                online = meters_truth.OnlineTruePeak(sample_rate_hz, channels=2)
                for chunk in self._chunked(data, chunk_size):
                    online.update(chunk)
                self.assertAlmostEqual(offline, online.finalize(), delta=1e-6)


if __name__ == "__main__":
    unittest.main()
