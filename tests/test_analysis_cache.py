import contextlib
import io
import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.core.cache_keys import cache_key, hash_lockfile, hash_run_config
from mmo.core.cache_store import cache_paths, save_cached_report, try_load_cached_report
from mmo.core.lockfile import build_lockfile
from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config


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


if __name__ == "__main__":
    unittest.main()
