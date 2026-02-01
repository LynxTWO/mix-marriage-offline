import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestScanSessionFfmpegBasic(unittest.TestCase):
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

    def test_scan_session_basic_with_fake_ffmpeg(self) -> None:
        samples = [0.0, 0.5, -0.25, 0.25]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True)
            (stems_dir / "dummy.flac").write_bytes(b"")

            ffmpeg_path = self._write_fake_ffmpeg(Path(temp_dir), samples)
            scan_session = repo_root / "tools" / "scan_session.py"
            schema_path = repo_root / "schemas" / "report.schema.json"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--schema",
                    os.fspath(schema_path),
                    "--meters",
                    "basic",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            stems = report.get("session", {}).get("stems", [])
            evidence_ids = {
                measurement.get("evidence_id")
                for stem in stems
                if isinstance(stem, dict)
                for measurement in stem.get("measurements", [])
                if isinstance(measurement, dict)
            }
            self.assertIn("EVID.METER.RMS_DBFS", evidence_ids)
            self.assertIn("EVID.METER.PEAK_DBFS", evidence_ids)

    def test_scan_session_missing_ffmpeg_adds_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True)
            (stems_dir / "dummy.flac").write_bytes(b"")

            scan_session = repo_root / "tools" / "scan_session.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env.pop("MMO_FFMPEG_PATH", None)
            env["PATH"] = ""

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--meters",
                    "basic",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            issues = report.get("issues", [])
            optional_dep = [
                issue
                for issue in issues
                if isinstance(issue, dict)
                and issue.get("issue_id")
                == "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING"
            ]
            self.assertTrue(optional_dep)
            evidence_values = {
                item.get("value")
                for issue in optional_dep
                for item in issue.get("evidence", [])
                if isinstance(item, dict)
                and item.get("evidence_id")
                == "EVID.VALIDATION.MISSING_OPTIONAL_DEP"
            }
            self.assertIn("ffmpeg", evidence_values)


if __name__ == "__main__":
    unittest.main()
