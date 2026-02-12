import contextlib
import io
import json
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from mmo.cli import main
from mmo.core.cache_keys import (
    cache_key,
    hash_lockfile,
    hash_run_config,
    translation_cache_key,
)
from mmo.core.cache_store import cache_paths, save_cached_report, try_load_cached_report
from mmo.core.lockfile import build_lockfile
from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config
from mmo.core.translation_audition import render_translation_auditions
from mmo.core.translation_checks import run_translation_checks
from mmo.core.translation_profiles import load_translation_profiles


def _write_wav_16bit(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.1,
    freq_hz: float = 220.0,
    amplitude: float = 0.45,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq_hz * index / sample_rate_hz))
        for index in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestAnalysisCache(unittest.TestCase):
    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        src_dir = str((repo_root / "src").resolve())
        self._original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = (
            src_dir
            if not self._original_pythonpath
            else f"{src_dir}{os.pathsep}{self._original_pythonpath}"
        )

    def tearDown(self) -> None:
        if self._original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
            return
        os.environ["PYTHONPATH"] = self._original_pythonpath

    def test_cache_keys_are_deterministic_and_root_dir_agnostic(self) -> None:
        lock_a = {
            "schema_version": "0.1.0",
            "root_dir": "/tmp/a",
            "files": [
                {"rel_path": "a.wav", "size_bytes": 1, "sha256": "11" * 32},
                {"rel_path": "b.wav", "size_bytes": 2, "sha256": "22" * 32},
            ],
        }
        lock_b = {
            "schema_version": "0.1.0",
            "root_dir": "/tmp/b",
            "files": [
                {"rel_path": "b.wav", "size_bytes": 999, "sha256": "22" * 32},
                {"rel_path": "a.wav", "size_bytes": 555, "sha256": "11" * 32},
            ],
        }
        cfg = normalize_run_config(
            {
                "schema_version": RUN_CONFIG_SCHEMA_VERSION,
                "profile_id": "PROFILE.ASSIST",
                "meters": "truth",
            }
        )

        lock_hash_a = hash_lockfile(lock_a)
        lock_hash_b = hash_lockfile(lock_b)
        self.assertEqual(lock_hash_a, lock_hash_b)
        cfg_hash = hash_run_config(cfg)
        self.assertEqual(
            cache_key(lock_hash_a, cfg_hash),
            cache_key(lock_hash_b, cfg_hash),
        )

    def test_cache_store_writes_expected_paths(self) -> None:
        lock = {
            "schema_version": "0.1.0",
            "root_dir": "/tmp/session",
            "files": [{"rel_path": "tone.wav", "size_bytes": 1, "sha256": "ab" * 32}],
        }
        cfg = {
            "schema_version": RUN_CONFIG_SCHEMA_VERSION,
            "profile_id": "PROFILE.ASSIST",
        }
        report = {
            "schema_version": "0.1.0",
            "report_id": "r",
            "project_id": "p",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.0.0",
            "ontology_version": "0.0.0",
            "session": {"stems_dir": "/tmp/session", "stems": []},
            "issues": [],
            "recommendations": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / ".mmo_cache"
            save_cached_report(cache_dir, lock, cfg, report)
            report_path, metadata_path = cache_paths(cache_dir, lock, cfg)
            self.assertTrue(report_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertEqual(
                try_load_cached_report(cache_dir, lock, cfg),
                report,
            )

    def test_analyze_uses_cache_and_invalidates_when_stem_changes(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            wav_path = stems_dir / "tone.wav"
            cache_dir = temp_path / ".mmo_cache"
            out_first = temp_path / "out_first.json"
            out_second = temp_path / "out_second.json"
            out_third = temp_path / "out_third.json"

            _write_wav_16bit(wav_path, freq_hz=220.0, amplitude=0.45)

            stdout_first = io.StringIO()
            with contextlib.redirect_stdout(stdout_first):
                first_exit = main(
                    [
                        "analyze",
                        str(stems_dir),
                        "--out-report",
                        str(out_first),
                        "--plugins",
                        str(repo_root / "plugins"),
                        "--cache",
                        "on",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            self.assertEqual(first_exit, 0)
            self.assertIn("analysis cache: miss", stdout_first.getvalue())

            lock_payload = build_lockfile(stems_dir)
            run_config = normalize_run_config(
                {
                    "schema_version": RUN_CONFIG_SCHEMA_VERSION,
                    "profile_id": "PROFILE.ASSIST",
                }
            )
            key = cache_key(hash_lockfile(lock_payload), hash_run_config(run_config))
            self.assertTrue((cache_dir / "reports" / f"{key}.report.json").exists())
            self.assertTrue((cache_dir / "metadata" / f"{key}.meta.json").exists())

            stdout_second = io.StringIO()
            with contextlib.redirect_stdout(stdout_second):
                second_exit = main(
                    [
                        "analyze",
                        str(stems_dir),
                        "--out-report",
                        str(out_second),
                        "--plugins",
                        str(repo_root / "plugins"),
                        "--cache",
                        "on",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            self.assertEqual(second_exit, 0)
            self.assertIn("analysis cache: hit", stdout_second.getvalue())

            first_report = json.loads(out_first.read_text(encoding="utf-8"))
            second_report = json.loads(out_second.read_text(encoding="utf-8"))
            self.assertEqual(first_report, second_report)

            _write_wav_16bit(wav_path, freq_hz=330.0, amplitude=0.25)

            stdout_third = io.StringIO()
            with contextlib.redirect_stdout(stdout_third):
                third_exit = main(
                    [
                        "analyze",
                        str(stems_dir),
                        "--out-report",
                        str(out_third),
                        "--plugins",
                        str(repo_root / "plugins"),
                        "--cache",
                        "on",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            self.assertEqual(third_exit, 0)
            self.assertIn("analysis cache: miss", stdout_third.getvalue())

            third_report = json.loads(out_third.read_text(encoding="utf-8"))
            self.assertNotEqual(
                second_report.get("report_id"),
                third_report.get("report_id"),
            )

    def test_translation_cache_key_is_content_based_and_profile_order_agnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path_a = temp_path / "tone_a.wav"
            audio_path_b = temp_path / "tone_b.wav"
            audio_path_c = temp_path / "tone_c.wav"
            _write_wav_16bit(audio_path_a, freq_hz=220.0, amplitude=0.45)
            _write_wav_16bit(audio_path_b, freq_hz=220.0, amplitude=0.45)
            _write_wav_16bit(audio_path_c, freq_hz=330.0, amplitude=0.25)

            key_a = translation_cache_key(
                audio_path_a,
                ["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"],
                "translation_checks_v1",
            )
            key_b = translation_cache_key(
                audio_path_b,
                ["TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
                "translation_checks_v1",
            )
            key_c = translation_cache_key(
                audio_path_c,
                ["TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
                "translation_checks_v1",
            )
            key_d = translation_cache_key(
                audio_path_a,
                ["TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
                "translation_checks_v2",
            )

            self.assertEqual(key_a, key_b)
            self.assertNotEqual(key_a, key_c)
            self.assertNotEqual(key_a, key_d)

    def test_translation_checks_cache_creates_entry_and_reuses_cached_results(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        profiles = load_translation_profiles(repo_root / "ontology" / "translation_profiles.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "translation_checks.wav"
            cache_dir = temp_path / ".mmo_cache"
            _write_wav_16bit(audio_path, freq_hz=220.0, amplitude=0.45)

            first = run_translation_checks(
                audio_path=audio_path,
                profiles=profiles,
                profile_ids=["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"],
                cache_dir=cache_dir,
                use_cache=True,
            )
            cache_files = sorted((cache_dir / "translation_checks").glob("*.json"))
            self.assertEqual(len(cache_files), 1)

            with mock.patch(
                "mmo.core.translation_checks._load_channels",
                side_effect=AssertionError("expected translation checks cache hit"),
            ):
                second = run_translation_checks(
                    audio_path=audio_path,
                    profiles=profiles,
                    profile_ids=["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"],
                    cache_dir=cache_dir,
                    use_cache=True,
                )

            self.assertEqual(second, first)

    def test_translation_audition_cache_creates_entry_and_reuses_cached_renders(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        profiles = load_translation_profiles(repo_root / "ontology" / "translation_profiles.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "translation_audition.wav"
            first_out_dir = temp_path / "out_first" / "translation_auditions"
            second_out_dir = temp_path / "out_second" / "translation_auditions"
            cache_dir = temp_path / ".mmo_cache"
            profile_ids = ["TRANS.MONO.COLLAPSE", "TRANS.DEVICE.PHONE"]
            _write_wav_16bit(audio_path, freq_hz=330.0, amplitude=0.35)

            first = render_translation_auditions(
                audio_path=audio_path,
                out_dir=first_out_dir,
                profiles=profiles,
                profile_ids=profile_ids,
                segment_s=0.05,
                cache_dir=cache_dir,
                use_cache=True,
            )
            cached_manifest_paths = sorted(
                (cache_dir / "translation_auditions").glob("*/manifest.json")
            )
            self.assertEqual(len(cached_manifest_paths), 1)

            with mock.patch(
                "mmo.core.translation_audition._load_channels",
                side_effect=AssertionError("expected translation audition cache hit"),
            ):
                second = render_translation_auditions(
                    audio_path=audio_path,
                    out_dir=second_out_dir,
                    profiles=profiles,
                    profile_ids=profile_ids,
                    segment_s=0.05,
                    cache_dir=cache_dir,
                    use_cache=True,
                )

            first_renders = first.get("renders")
            second_renders = second.get("renders")
            self.assertIsInstance(first_renders, list)
            self.assertIsInstance(second_renders, list)
            if not isinstance(first_renders, list) or not isinstance(second_renders, list):
                return
            self.assertEqual(
                [
                    item.get("profile_id")
                    for item in first_renders
                    if isinstance(item, dict)
                ],
                profile_ids,
            )
            self.assertEqual(
                [
                    item.get("profile_id")
                    for item in second_renders
                    if isinstance(item, dict)
                ],
                profile_ids,
            )

            for profile_id in profile_ids:
                first_file = first_out_dir / f"{profile_id}.wav"
                second_file = second_out_dir / f"{profile_id}.wav"
                self.assertTrue(first_file.exists())
                self.assertTrue(second_file.exists())
                self.assertEqual(first_file.read_bytes(), second_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
