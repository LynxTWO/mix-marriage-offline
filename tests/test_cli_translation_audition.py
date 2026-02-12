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


def _clamp_sample(value: float) -> int:
    clipped = max(-0.999969, min(0.999969, value))
    return int(round(clipped * 32767.0))


def _write_stereo_fixture(path: Path) -> None:
    sample_rate_hz = 48000
    duration_s = 0.6
    frame_count = int(round(sample_rate_hz * duration_s))
    samples: list[int] = []
    for index in range(frame_count):
        t = index / float(sample_rate_hz)
        left = (
            0.6 * math.sin(2.0 * math.pi * 70.0 * t)
            + 0.2 * math.sin(2.0 * math.pi * 800.0 * t)
            + 0.2 * math.sin(2.0 * math.pi * 4200.0 * t)
        )
        right = (
            0.55 * math.sin(2.0 * math.pi * 70.0 * t + 0.08)
            + 0.2 * math.sin(2.0 * math.pi * 1100.0 * t + 0.04)
            + 0.2 * math.sin(2.0 * math.pi * 4600.0 * t + 0.12)
        )
        samples.extend([_clamp_sample(left), _clamp_sample(right)])

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestCliTranslationAudition(unittest.TestCase):
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

    def test_translation_audition_manifest_and_files_are_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        expected_profile_ids = [
            "TRANS.MONO.COLLAPSE",
            "TRANS.DEVICE.PHONE",
            "TRANS.DEVICE.SMALL_SPEAKER",
            "TRANS.DEVICE.EARBUDS",
            "TRANS.DEVICE.CAR",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "translation_fixture.wav"
            out_dir = temp_path / "out"
            _write_stereo_fixture(audio_path)

            args = [
                "translation",
                "audition",
                "--audio",
                str(audio_path),
                "--profiles",
                ",".join(expected_profile_ids),
                "--out-dir",
                str(out_dir),
                "--segment",
                "0.25",
            ]

            first = self._run(repo_root, args)
            manifest_path = out_dir / "translation_auditions" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            first_manifest = manifest_path.read_text(encoding="utf-8")
            first_files = sorted(
                path.name
                for path in (out_dir / "translation_auditions").glob("*.wav")
            )

            second = self._run(repo_root, args)
            second_manifest = manifest_path.read_text(encoding="utf-8")
            second_files = sorted(
                path.name
                for path in (out_dir / "translation_auditions").glob("*.wav")
            )
            for profile_id in expected_profile_ids:
                expected_path = out_dir / "translation_auditions" / f"{profile_id}.wav"
                self.assertTrue(expected_path.exists())

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_files, second_files)
        output_rows = [
            line.strip()
            for line in first.stdout.splitlines()
            if isinstance(line, str) and line.strip().startswith("- ")
        ]
        output_profile_ids = [
            row[2:].split(" -> ", 1)[0]
            for row in output_rows
            if " -> " in row
        ]
        self.assertEqual(output_profile_ids, sorted(expected_profile_ids))
        for row in output_rows:
            self.assertIn("translation_auditions/", row)

        expected_files = sorted(f"{profile_id}.wav" for profile_id in expected_profile_ids)
        self.assertEqual(first_files, expected_files)

        manifest = json.loads(second_manifest)
        renders = manifest.get("renders")
        self.assertIsInstance(renders, list)
        if not isinstance(renders, list):
            return

        observed_profile_ids = [
            item.get("profile_id")
            for item in renders
            if isinstance(item, dict)
        ]
        self.assertEqual(observed_profile_ids, expected_profile_ids)

    def test_translation_audition_cache_dir_and_no_cache_flags(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        profile_ids = ["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "translation_fixture.wav"
            cached_out_dir = temp_path / "out_cached"
            no_cached_out_dir = temp_path / "out_no_cache"
            cache_dir = temp_path / ".cache"
            no_cache_dir = temp_path / ".cache_disabled"
            _write_stereo_fixture(audio_path)

            cached = self._run(
                repo_root,
                [
                    "translation",
                    "audition",
                    "--audio",
                    str(audio_path),
                    "--profiles",
                    ",".join(profile_ids),
                    "--out-dir",
                    str(cached_out_dir),
                    "--segment",
                    "0.10",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )
            no_cached = self._run(
                repo_root,
                [
                    "translation",
                    "audition",
                    "--audio",
                    str(audio_path),
                    "--profiles",
                    ",".join(profile_ids),
                    "--out-dir",
                    str(no_cached_out_dir),
                    "--segment",
                    "0.10",
                    "--cache-dir",
                    str(no_cache_dir),
                    "--no-cache",
                ],
            )

            self.assertEqual(cached.returncode, 0, msg=cached.stderr)
            self.assertEqual(no_cached.returncode, 0, msg=no_cached.stderr)
            self.assertGreater(
                len(list((cache_dir / "translation_auditions").glob("*/manifest.json"))),
                0,
            )
            self.assertFalse((no_cache_dir / "translation_auditions").exists())


if __name__ == "__main__":
    unittest.main()
