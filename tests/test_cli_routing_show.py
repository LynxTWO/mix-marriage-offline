import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


def _write_wav_16bit_mono(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.05,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(0.4 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestCliRoutingShow(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_routing_show_json(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "routing",
                    "show",
                    "--stems",
                    str(stems_dir),
                    "--source-layout",
                    "LAYOUT.1_0",
                    "--target-layout",
                    "LAYOUT.2_0",
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("schema_version"), "0.1.0")
        self.assertEqual(payload.get("source_layout_id"), "LAYOUT.1_0")
        self.assertEqual(payload.get("target_layout_id"), "LAYOUT.2_0")
        routes = payload.get("routes", [])
        self.assertEqual(len(routes), 1)
        self.assertEqual(
            routes[0].get("mapping"),
            [
                {"src_ch": 0, "dst_ch": 0, "gain_db": -3.0},
                {"src_ch": 0, "dst_ch": 1, "gain_db": -3.0},
            ],
        )

    def test_routing_show_text(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_wav_16bit_mono(stems_dir / "lead.wav")

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "routing",
                    "show",
                    "--stems",
                    str(stems_dir),
                    "--source-layout",
                    "LAYOUT.1_0",
                    "--target-layout",
                    "LAYOUT.2_0",
                    "--format",
                    "text",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Routing plan:", result.stdout)
        self.assertIn("Mono routed equally to L/R at -3.0 dB each", result.stdout)


if __name__ == "__main__":
    unittest.main()
