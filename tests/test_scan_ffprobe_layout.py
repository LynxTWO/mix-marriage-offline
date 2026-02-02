import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestScanSessionFfprobeLayout(unittest.TestCase):
    def _write_fake_ffprobe(self, directory: Path) -> Path:
        script_path = directory / "fake_ffprobe.py"
        script_path.write_text(
            """
import json
import sys


def main() -> None:
    # Minimal ffprobe payload with channel_layout for scan_session.
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "flac",
                "channels": 6,
                "sample_rate": "48000",
                "duration": "2.5",
                "channel_layout": "5.1",
            }
        ],
        "format": {"duration": "2.5"},
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
""".lstrip(),
            encoding="utf-8",
        )
        return script_path

    def test_scan_session_includes_channel_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True)
            (stems_dir / "dummy.flac").write_bytes(b"")

            ffprobe_path = self._write_fake_ffprobe(Path(temp_dir))
            scan_session = repo_root / "tools" / "scan_session.py"
            schema_path = repo_root / "schemas" / "report.schema.json"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--schema",
                    os.fspath(schema_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            stems = report.get("session", {}).get("stems", [])
            self.assertEqual(len(stems), 1)
            stem = stems[0]
            self.assertEqual(stem.get("channel_layout"), "5.1")
            self.assertEqual(stem.get("channel_count"), 6)


if __name__ == "__main__":
    unittest.main()
