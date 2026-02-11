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

from mmo.core.translation_profiles import list_translation_profiles


def _clamp_sample(value: float) -> int:
    clipped = max(-0.999969, min(0.999969, value))
    return int(round(clipped * 32767.0))


def _write_stereo_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    duration_s: float,
    left_fn,
    right_fn,
) -> None:
    frame_count = int(round(sample_rate_hz * duration_s))
    samples: list[int] = []
    for index in range(frame_count):
        t = index / float(sample_rate_hz)
        left = _clamp_sample(float(left_fn(t)))
        right = _clamp_sample(float(right_fn(t)))
        samples.extend([left, right])

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_cancellation_fixture(path: Path) -> None:
    sample_rate_hz = 48000
    duration_s = 1.0
    frequency_hz = 440.0
    amplitude = 0.7
    _write_stereo_wav(
        path,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        left_fn=lambda t: amplitude * math.sin(2.0 * math.pi * frequency_hz * t),
        right_fn=lambda t: -amplitude * math.sin(2.0 * math.pi * frequency_hz * t),
    )


def _write_device_fixture(path: Path) -> None:
    sample_rate_hz = 48000
    duration_s = 1.0
    _write_stereo_wav(
        path,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        left_fn=lambda t: (
            0.65 * math.sin(2.0 * math.pi * 50.0 * t)
            + 0.2 * math.sin(2.0 * math.pi * 500.0 * t)
            + 0.5 * math.sin(2.0 * math.pi * 3000.0 * t)
        ),
        right_fn=lambda t: (
            0.65 * math.sin(2.0 * math.pi * 50.0 * t + 0.1)
            + 0.2 * math.sin(2.0 * math.pi * 500.0 * t + 0.05)
            + 0.5 * math.sin(2.0 * math.pi * 3000.0 * t + 0.2)
        ),
    )


class TestCliTranslationRun(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def _run(self, repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._python_cmd(), "-m", "mmo", *args],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )

    def test_translation_run_json_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "translation_device.wav"
            _write_device_fixture(audio_path)
            args = [
                "translation",
                "run",
                "--audio",
                str(audio_path),
                "--profiles",
                "TRANS.MONO.COLLAPSE,TRANS.DEVICE.PHONE",
                "--format",
                "json",
            ]
            first = self._run(repo_root, args)
            second = self._run(repo_root, args)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        profile_ids = [
            item.get("profile_id")
            for item in payload
            if isinstance(item, dict)
        ]
        self.assertEqual(profile_ids, ["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"])

    def test_translation_run_unknown_profile_ids_error_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "translation_device.wav"
            _write_device_fixture(audio_path)
            args = [
                "translation",
                "run",
                "--audio",
                str(audio_path),
                "--profiles",
                "TRANS.UNKNOWN.ZZZ,TRANS.UNKNOWN.AAA",
                "--format",
                "json",
            ]
            first = self._run(repo_root, args)
            second = self._run(repo_root, args)

        self.assertNotEqual(first.returncode, 0)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)

        available = list_translation_profiles(
            repo_root / "ontology" / "translation_profiles.yaml"
        )
        known_ids = sorted(
            item.get("profile_id")
            for item in available
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        )
        expected = (
            "Unknown translation profile_id: TRANS.UNKNOWN.AAA, TRANS.UNKNOWN.ZZZ. "
            f"Known profile_ids: {', '.join(known_ids)}"
        )
        self.assertEqual(first.stderr.strip(), expected)

    def test_translation_run_mono_collapse_emits_low_score_issue(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "translation_cancel.wav"
            _write_cancellation_fixture(audio_path)
            result = self._run(
                repo_root,
                [
                    "translation",
                    "run",
                    "--audio",
                    str(audio_path),
                    "--profiles",
                    "TRANS.MONO.COLLAPSE",
                    "--format",
                    "json",
                ],
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload), 1)
        row = payload[0]
        self.assertEqual(row.get("profile_id"), "TRANS.MONO.COLLAPSE")
        score = row.get("score")
        self.assertIsInstance(score, int)
        if isinstance(score, int):
            self.assertLess(score, 70)

        issues = row.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list) or not issues:
            self.fail("Expected ISSUE.TRANSLATION.PROFILE_SCORE_LOW in translation result.")
        issue = issues[0]
        self.assertEqual(issue.get("issue_id"), "ISSUE.TRANSLATION.PROFILE_SCORE_LOW")
        evidence = issue.get("evidence")
        self.assertIsInstance(evidence, list)
        evidence_ids = {
            item.get("evidence_id")
            for item in evidence
            if isinstance(item, dict)
        }
        self.assertIn("EVID.ISSUE.SCORE", evidence_ids)
        self.assertIn("EVID.ISSUE.MEASURED_VALUE", evidence_ids)
        self.assertIn("EVID.SEGMENT.START_S", evidence_ids)
        self.assertIn("EVID.SEGMENT.END_S", evidence_ids)

    def test_translation_run_device_scores_are_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "translation_device.wav"
            _write_device_fixture(audio_path)
            args = [
                "translation",
                "run",
                "--audio",
                str(audio_path),
                "--profiles",
                "TRANS.DEVICE.PHONE,TRANS.DEVICE.SMALL_SPEAKER,TRANS.DEVICE.EARBUDS,TRANS.DEVICE.CAR",
                "--format",
                "json",
            ]
            first = self._run(repo_root, args)
            second = self._run(repo_root, args)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        observed = {
            item.get("profile_id"): item.get("score")
            for item in payload
            if isinstance(item, dict)
        }
        expected_scores = {
            "TRANS.DEVICE.PHONE": 70,
            "TRANS.DEVICE.SMALL_SPEAKER": 65,
            "TRANS.DEVICE.EARBUDS": 45,
            "TRANS.DEVICE.CAR": 48,
        }
        self.assertEqual(observed, expected_scores)


if __name__ == "__main__":
    unittest.main()
