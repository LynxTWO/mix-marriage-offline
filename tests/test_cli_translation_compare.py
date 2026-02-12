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
    duration_s = 0.8
    frequency_hz = 440.0
    amplitude = 0.7
    _write_stereo_wav(
        path,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        left_fn=lambda t: amplitude * math.sin(2.0 * math.pi * frequency_hz * t),
        right_fn=lambda t: -amplitude * math.sin(2.0 * math.pi * frequency_hz * t),
    )


def _write_balanced_fixture(path: Path) -> None:
    sample_rate_hz = 48000
    duration_s = 0.8
    _write_stereo_wav(
        path,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        left_fn=lambda t: (
            0.55 * math.sin(2.0 * math.pi * 80.0 * t)
            + 0.25 * math.sin(2.0 * math.pi * 650.0 * t)
            + 0.18 * math.sin(2.0 * math.pi * 3200.0 * t)
        ),
        right_fn=lambda t: (
            0.55 * math.sin(2.0 * math.pi * 80.0 * t)
            + 0.25 * math.sin(2.0 * math.pi * 650.0 * t)
            + 0.18 * math.sin(2.0 * math.pi * 3200.0 * t)
        ),
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


class TestCliTranslationCompare(unittest.TestCase):
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

    def test_translation_compare_text_is_sorted_and_repeatable(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            cancel_path = temp_path / "a_cancel.wav"
            balanced_path = temp_path / "z_balanced.wav"
            _write_cancellation_fixture(cancel_path)
            _write_balanced_fixture(balanced_path)

            args = [
                "translation",
                "compare",
                "--audio",
                f"{balanced_path},{cancel_path}",
                "--profiles",
                "TRANS.MONO.COLLAPSE,TRANS.DEVICE.PHONE",
                "--format",
                "text",
            ]
            first = self._run(repo_root, args)
            second = self._run(repo_root, args)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)

        lines = [line.strip() for line in first.stdout.splitlines() if isinstance(line, str) and line.strip()]
        self.assertTrue(lines)
        self.assertEqual(lines[0], "audio | profile_id | score | status")

        rows: list[tuple[str, str, int, str]] = []
        for line in lines[1:]:
            parts = [part.strip() for part in line.split("|")]
            self.assertEqual(len(parts), 4)
            rows.append((parts[0], parts[1], int(parts[2]), parts[3]))

        self.assertEqual(
            [(audio, profile_id) for audio, profile_id, _, _ in rows],
            [
                ("a_cancel.wav", "TRANS.DEVICE.PHONE"),
                ("a_cancel.wav", "TRANS.MONO.COLLAPSE"),
                ("z_balanced.wav", "TRANS.DEVICE.PHONE"),
                ("z_balanced.wav", "TRANS.MONO.COLLAPSE"),
            ],
        )
        self.assertIn(rows[1][3], {"pass", "warn", "fail"})
        self.assertIn(rows[3][3], {"pass", "warn", "fail"})
        self.assertNotEqual(rows[1][2], rows[3][2])

    def test_translation_compare_in_dir_glob_json_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_dir = temp_path / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            cancel_path = audio_dir / "a_cancel.wav"
            device_path = audio_dir / "b_device.wav"
            ignored_path = audio_dir / "ignored.wave"

            _write_cancellation_fixture(cancel_path)
            _write_device_fixture(device_path)
            _write_balanced_fixture(ignored_path)

            args = [
                "translation",
                "compare",
                "--in-dir",
                str(audio_dir),
                "--glob",
                "*.wav",
                "--profiles",
                "TRANS.MONO.COLLAPSE",
                "--format",
                "json",
            ]
            first = self._run(repo_root, args)
            second = self._run(repo_root, args)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertEqual(
            [item.get("audio") for item in payload if isinstance(item, dict)],
            ["a_cancel.wav", "b_device.wav"],
        )
        for row in payload:
            self.assertIsInstance(row, dict)
            if not isinstance(row, dict):
                continue
            self.assertEqual(row.get("profile_id"), "TRANS.MONO.COLLAPSE")
            self.assertIn(row.get("status"), {"pass", "warn", "fail"})
            self.assertIsInstance(row.get("issues_count"), int)

    def test_translation_compare_status_matches_thresholds(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        profiles = {
            item.get("profile_id"): item
            for item in list_translation_profiles(repo_root / "ontology" / "translation_profiles.yaml")
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "device.wav"
            _write_device_fixture(audio_path)
            result = self._run(
                repo_root,
                [
                    "translation",
                    "compare",
                    "--audio",
                    str(audio_path),
                    "--profiles",
                    "TRANS.DEVICE.CAR,TRANS.DEVICE.EARBUDS,TRANS.DEVICE.PHONE,TRANS.DEVICE.SMALL_SPEAKER",
                    "--format",
                    "json",
                ],
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)

        observed_profile_ids = [
            row.get("profile_id")
            for row in payload
            if isinstance(row, dict)
        ]
        self.assertEqual(observed_profile_ids, sorted(observed_profile_ids))

        for row in payload:
            self.assertIsInstance(row, dict)
            if not isinstance(row, dict):
                continue
            profile_id = row.get("profile_id")
            score = row.get("score")
            status = row.get("status")
            issues_count = row.get("issues_count")
            self.assertIsInstance(profile_id, str)
            self.assertIsInstance(score, int)
            self.assertIsInstance(status, str)
            self.assertIsInstance(issues_count, int)
            if not isinstance(profile_id, str) or not isinstance(score, int):
                continue
            profile = profiles.get(profile_id)
            self.assertIsInstance(profile, dict)
            if not isinstance(profile, dict):
                continue
            warn_below = int(profile.get("score_warn_below", 70))
            fail_below = int(profile.get("score_fail_below", 50))
            fail_below = min(fail_below, warn_below)
            expected_status = "pass"
            if score < fail_below:
                expected_status = "fail"
            elif score < warn_below:
                expected_status = "warn"
            self.assertEqual(status, expected_status)


if __name__ == "__main__":
    unittest.main()
