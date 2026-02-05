import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mmo.core.validators import validate_session


class TestValidationWavCodec(unittest.TestCase):
    @staticmethod
    def _find_issue(issues, issue_id: str):
        for issue in issues:
            if isinstance(issue, dict) and issue.get("issue_id") == issue_id:
                return issue
        return None

    @staticmethod
    def _evidence_ids(issue) -> set[str]:
        evidence = issue.get("evidence", []) if isinstance(issue, dict) else []
        return {
            item.get("evidence_id")
            for item in evidence
            if isinstance(item, dict)
        }

    def test_validate_session_marks_non_pcm_wav_as_unsupported(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "stem1",
                    "file_path": "stem.wav",
                    "channel_count": 2,
                    "sample_rate_hz": 48000,
                    "duration_s": 0.25,
                    "bits_per_sample": 4,
                    "wav_audio_format": 0x0011,
                    "wav_audio_format_resolved": 0x0011,
                }
            ]
        }

        issues = validate_session(session)
        unsupported = self._find_issue(
            issues, "ISSUE.VALIDATION.UNSUPPORTED_AUDIO_FORMAT"
        )
        self.assertIsNotNone(unsupported)
        if unsupported is None:
            return

        evidence_ids = self._evidence_ids(unsupported)
        self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT", evidence_ids)
        self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT_RESOLVED", evidence_ids)

        issue_ids = {
            issue.get("issue_id")
            for issue in issues
            if isinstance(issue, dict)
        }
        self.assertNotIn("ISSUE.VALIDATION.LOSSY_STEMS_DETECTED", issue_ids)

    def test_validate_session_marks_mp3_in_wav_as_lossy(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "stem1",
                    "file_path": "stem.wav",
                    "channel_count": 2,
                    "sample_rate_hz": 48000,
                    "duration_s": 0.25,
                    "bits_per_sample": 16,
                    "wav_audio_format": 0x0055,
                    "wav_audio_format_resolved": 0x0055,
                }
            ]
        }

        issues = validate_session(session)
        lossy = self._find_issue(issues, "ISSUE.VALIDATION.LOSSY_STEMS_DETECTED")
        self.assertIsNotNone(lossy)
        if lossy is None:
            return

        evidence_ids = self._evidence_ids(lossy)
        self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT", evidence_ids)
        self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT_RESOLVED", evidence_ids)
        self.assertIn("EVID.VALIDATION.LOSSY_REASON", evidence_ids)

        message = str(lossy.get("message", "")).lower()
        self.assertIn("lossy", message)

        issue_ids = {
            issue.get("issue_id")
            for issue in issues
            if isinstance(issue, dict)
        }
        self.assertNotIn("ISSUE.VALIDATION.UNSUPPORTED_AUDIO_FORMAT", issue_ids)

    def test_scan_session_detects_adpcm_wav_as_unsupported(self) -> None:
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin is None:
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True)
            adpcm_path = stems_dir / "out_adpcm.wav"

            ffmpeg_cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.25",
                "-c:a",
                "adpcm_ima_wav",
                os.fspath(adpcm_path),
            ]
            try:
                subprocess.run(
                    ffmpeg_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                self.skipTest(f"ffmpeg cannot generate ADPCM WAV: {stderr}")

            repo_root = Path(__file__).resolve().parents[1]
            scan_session = repo_root / "tools" / "scan_session.py"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            issues = report.get("issues", [])
            unsupported = self._find_issue(
                issues, "ISSUE.VALIDATION.UNSUPPORTED_AUDIO_FORMAT"
            )
            self.assertIsNotNone(unsupported)
            if unsupported is None:
                return

            evidence_ids = self._evidence_ids(unsupported)
            self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT", evidence_ids)
            self.assertIn("EVID.VALIDATION.WAV_AUDIO_FORMAT_RESOLVED", evidence_ids)


if __name__ == "__main__":
    unittest.main()
