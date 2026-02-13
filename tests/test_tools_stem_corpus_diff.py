"""Tests for tools/stem_corpus_diff.py — corpus stats diff tool."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _REPO_ROOT / "tools" / "stem_corpus_diff.py"
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_corpus_diff"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_diff(args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(_TOOL)] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


_BEFORE_STATS: dict = {
    "total_files": 100,
    "scan_params": {
        "include_folder_tokens": False,
        "min_confidence": 0.8,
        "min_count": 10,
        "min_precision": 0.85,
        "min_set_count": 3,
        "stopwords": ["mix", "stem"],
    },
    "token_frequency_top": [
        {"token": "kick", "count": 50},
        {"token": "snare", "count": 30},
        {"token": "vocal", "count": 20},
    ],
    "unknown_token_frequency_top": [
        {"token": "mystery", "count": 15},
        {"token": "thing", "count": 5},
    ],
    "per_role_token_top": {
        "ROLE.DRUMS.KICK": [
            {"token": "kick", "count": 50},
            {"token": "bd", "count": 10},
        ],
        "ROLE.DRUMS.SNARE": [
            {"token": "snare", "count": 30},
        ],
    },
    "ambiguous_cases": [],
}

_AFTER_STATS: dict = {
    "total_files": 150,
    "scan_params": {
        "include_folder_tokens": False,
        "min_confidence": 0.8,
        "min_count": 10,
        "min_precision": 0.85,
        "min_set_count": 3,
        "stopwords": ["mix", "stem"],
    },
    "token_frequency_top": [
        {"token": "kick", "count": 70},
        {"token": "snare", "count": 30},
        {"token": "vocal", "count": 25},
        {"token": "bass", "count": 15},
    ],
    "unknown_token_frequency_top": [
        {"token": "mystery", "count": 10},
        {"token": "newtoken", "count": 8},
    ],
    "per_role_token_top": {
        "ROLE.DRUMS.KICK": [
            {"token": "kick", "count": 70},
            {"token": "bd", "count": 10},
        ],
        "ROLE.DRUMS.SNARE": [
            {"token": "snare", "count": 35},
        ],
        "ROLE.BASS.DI": [
            {"token": "bass", "count": 15},
        ],
    },
    "ambiguous_cases": [],
}


class TestCorpusDiff(unittest.TestCase):
    def test_basic_diff(self) -> None:
        base = _SANDBOX / "basic"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, stderr = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertIn("deltas", result)
        self.assertIn("token_frequency_top_delta", result["deltas"])

    def test_deterministic_output(self) -> None:
        base = _SANDBOX / "determinism"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        _, stdout1, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])
        _, stdout2, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(stdout1, stdout2)

    def test_delta_ordering(self) -> None:
        """Deltas must be sorted by abs(delta) desc, then token asc."""
        base = _SANDBOX / "ordering"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        deltas = result["deltas"]["token_frequency_top_delta"]
        for i in range(len(deltas) - 1):
            curr = deltas[i]
            nxt = deltas[i + 1]
            self.assertGreaterEqual(
                abs(curr["delta"]),
                abs(nxt["delta"]),
                msg=f"Sort violation at index {i}: {curr} vs {nxt}",
            )
            if abs(curr["delta"]) == abs(nxt["delta"]):
                self.assertLessEqual(
                    curr["token"],
                    nxt["token"],
                    msg=f"Tiebreak violation at index {i}: {curr} vs {nxt}",
                )

    def test_summary_counts(self) -> None:
        base = _SANDBOX / "counts"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        self.assertIn("increased_count", result)
        self.assertIn("decreased_count", result)
        self.assertIn("unchanged_count", result)
        # kick: 50->70 (up), snare: 30->30 (same), vocal: 20->25 (up), bass: 0->15 (up)
        self.assertEqual(result["increased_count"], 3)
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(result["decreased_count"], 0)

    def test_missing_key_warnings(self) -> None:
        """Missing keys in before/after should produce deterministic warnings."""
        base = _SANDBOX / "warnings"
        before_path = base / "before.json"
        after_path = base / "after.json"

        # Before is missing per_role_token_top.
        before_partial = {
            "total_files": 10,
            "token_frequency_top": [{"token": "kick", "count": 5}],
            "unknown_token_frequency_top": [],
        }
        # After is missing unknown_token_frequency_top.
        after_partial = {
            "total_files": 20,
            "token_frequency_top": [{"token": "kick", "count": 10}],
            "per_role_token_top": {},
        }

        _write_json(before_path, before_partial)
        _write_json(after_path, after_partial)

        exit_code, stdout, stderr = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        warnings = result["warnings"]
        self.assertIsInstance(warnings, list)
        self.assertIn("missing_key:per_role_token_top_before", warnings)
        self.assertIn("missing_key:scan_params_before", warnings)
        self.assertIn("missing_key:unknown_token_frequency_top_after", warnings)
        self.assertIn("missing_key:scan_params_after", warnings)
        # Warnings must be sorted.
        self.assertEqual(warnings, sorted(warnings))

    def test_per_role_delta(self) -> None:
        base = _SANDBOX / "per_role"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        per_role = result["deltas"]["per_role_token_top_delta"]
        # ROLE.BASS.DI is new in after.
        self.assertIn("ROLE.BASS.DI", per_role)
        # Roles should be sorted.
        self.assertEqual(list(per_role.keys()), sorted(per_role.keys()))

    def test_output_to_file(self) -> None:
        base = _SANDBOX / "outfile"
        before_path = base / "before.json"
        after_path = base / "after.json"
        out_path = base / "diff.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, stderr = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
            "--out", str(out_path),
        ])

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertTrue(out_path.exists())
        file_result = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertTrue(file_result["ok"])

    def test_paths_use_forward_slashes(self) -> None:
        base = _SANDBOX / "slashes"
        before_path = base / "before.json"
        after_path = base / "after.json"
        _write_json(before_path, _BEFORE_STATS)
        _write_json(after_path, _AFTER_STATS)

        exit_code, stdout, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
        ])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        self.assertNotIn("\\", result["before_path"])
        self.assertNotIn("\\", result["after_path"])

    def test_top_limits_output(self) -> None:
        base = _SANDBOX / "top_limit"
        before_path = base / "before.json"
        after_path = base / "after.json"

        before = {
            "token_frequency_top": [
                {"token": f"t{i:03d}", "count": 100 - i}
                for i in range(20)
            ],
        }
        after = {
            "token_frequency_top": [
                {"token": f"t{i:03d}", "count": 100 - i + (i % 2)}
                for i in range(20)
            ],
        }
        _write_json(before_path, before)
        _write_json(after_path, after)

        exit_code, stdout, _ = _run_diff([
            "--before", str(before_path),
            "--after", str(after_path),
            "--top", "3",
        ])

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        deltas = result["deltas"]["token_frequency_top_delta"]
        self.assertLessEqual(len(deltas), 3)


if __name__ == "__main__":
    unittest.main()
