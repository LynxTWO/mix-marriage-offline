import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestScanTruthWeightingMultiformat(unittest.TestCase):
    def _skip_if_no_numpy(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

    def _write_fake_ffprobe(self, directory: Path) -> Path:
        script_path = directory / "fake_ffprobe.py"
        script_path.write_text(
            """
import json
import sys
from pathlib import Path

def payload_for(name: str) -> dict:
    if name == "dummy_51.flac":
        return {"codec_name":"flac","channels":6,"sample_rate":"48000","duration":"0.5","channel_layout":"5.1(side)"}
    if name == "dummy_stereo.wv":
        return {"codec_name":"wavpack","channels":2,"sample_rate":"48000","duration":"0.5","channel_layout":"stereo"}
    if name == "dummy_71.wv":
        return {"codec_name":"wavpack","channels":8,"sample_rate":"48000","duration":"0.5","channel_layout":"7.1"}
    if name == "dummy_stereo.aiff":
        return {"codec_name":"pcm_s16be","channels":2,"sample_rate":"48000","duration":"0.5","channel_layout":"stereo"}
    return {"codec_name":"flac","channels":2,"sample_rate":"48000","duration":"0.5","channel_layout":"stereo"}

def main() -> None:
    path = Path(sys.argv[-1])
    stream = payload_for(path.name)
    payload = {"streams":[{"codec_type":"audio", **stream}], "format":{"duration": stream["duration"]}}
    print(json.dumps(payload))

if __name__ == "__main__":
    main()
""".lstrip(),
            encoding="utf-8",
        )
        return script_path

    def _write_fake_ffmpeg(self, directory: Path) -> Path:
        samples = [0.0] * 240
        payload = struct.pack(f"<{len(samples)}d", *samples)
        script_path = directory / "fake_ffmpeg.py"
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

    def test_truth_scan_emits_weighting_measurements_for_multiformat(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True)
            (stems_dir / "dummy_51.flac").write_bytes(b"")
            (stems_dir / "dummy_stereo.wv").write_bytes(b"")
            (stems_dir / "dummy_71.wv").write_bytes(b"")
            (stems_dir / "dummy_stereo.aiff").write_bytes(b"")

            ffprobe_path = self._write_fake_ffprobe(Path(temp_dir))
            ffmpeg_path = self._write_fake_ffmpeg(Path(temp_dir))

            scan_session = repo_root / "tools" / "scan_session.py"
            schema_path = repo_root / "schemas" / "report.schema.json"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--schema",
                    os.fspath(schema_path),
                    "--meters",
                    "truth",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            stems = report.get("session", {}).get("stems", [])
            self.assertEqual(len(stems), 4)
            for stem in stems:
                measurements = stem.get("measurements", [])
                ids = {m.get("evidence_id") for m in measurements if isinstance(m, dict)}
                self.assertIn("EVID.METER.LUFS_WEIGHTING_MODE", ids)
                self.assertIn("EVID.METER.LUFS_WEIGHTING_ORDER", ids)
                self.assertIn("EVID.METER.LUFS_WEIGHTING_GI", ids)


if __name__ == "__main__":
    unittest.main()
