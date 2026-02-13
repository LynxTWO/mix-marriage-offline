import json
import os
import shutil
import subprocess
import sys
import unittest
import wave
from pathlib import Path


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


def _is_ranked_token_rows(rows: list[dict[str, object]]) -> bool:
    for idx in range(len(rows) - 1):
        left = rows[idx]
        right = rows[idx + 1]
        left_count = left.get("count")
        right_count = right.get("count")
        left_token = left.get("token")
        right_token = right.get("token")
        if not isinstance(left_count, int) or not isinstance(right_count, int):
            return False
        if not isinstance(left_token, str) or not isinstance(right_token, str):
            return False
        if left_count < right_count:
            return False
        if left_count == right_count and left_token > right_token:
            return False
    return True


class TestToolsStemCorpusScan(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _tool_path(self) -> Path:
        return self._repo_root() / "tools" / "stem_corpus_scan.py"

    def _run_scan(self, *, root: Path, out: Path, stats: Path) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.fspath(self._repo_root() / "src")
        result = subprocess.run(
            [
                self._python_cmd(),
                os.fspath(self._tool_path()),
                "--root",
                os.fspath(root),
                "--out",
                os.fspath(out),
                "--stats",
                os.fspath(stats),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_scan_outputs_are_deterministic_and_sorted(self) -> None:
        temp_root = self._repo_root() / "sandbox_tmp" / "test_tools_stem_corpus_scan"
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            stems_root = temp_root / "Cambridge Set"
            out_path = temp_root / "cambridge.corpus.jsonl"
            stats_path = temp_root / "cambridge.corpus.stats.json"

            _write_tiny_wav(stems_root / "Disc B" / "stems" / "03_unknown_xyz.wav")
            _write_tiny_wav(stems_root / "Disc A" / "stems" / "02_vox lead.wav")
            _write_tiny_wav(stems_root / "Disc A" / "stems" / "01_kick.wav")

            self._run_scan(root=stems_root, out=out_path, stats=stats_path)
            first_out_text = out_path.read_text(encoding="utf-8")
            first_stats_text = stats_path.read_text(encoding="utf-8")

            self._run_scan(root=stems_root, out=out_path, stats=stats_path)
            second_out_text = out_path.read_text(encoding="utf-8")
            second_stats_text = stats_path.read_text(encoding="utf-8")

            self.assertEqual(first_out_text, second_out_text)
            self.assertEqual(first_stats_text, second_stats_text)

            corpus_rows = [
                json.loads(line)
                for line in first_out_text.splitlines()
                if line.strip()
            ]
            rel_paths = [
                row.get("rel_path")
                for row in corpus_rows
                if isinstance(row, dict) and isinstance(row.get("rel_path"), str)
            ]
            self.assertEqual(rel_paths, sorted(rel_paths))

            stats_payload = json.loads(first_stats_text)
            self.assertEqual(
                sorted(stats_payload.keys()),
                [
                    "ambiguous_cases",
                    "per_role_token_top",
                    "token_frequency_top",
                    "total_files",
                    "unknown_token_frequency_top",
                ],
            )
            self.assertEqual(stats_payload.get("total_files"), 3)

            token_top = stats_payload.get("token_frequency_top")
            self.assertIsInstance(token_top, list)
            if isinstance(token_top, list):
                self.assertTrue(
                    _is_ranked_token_rows([row for row in token_top if isinstance(row, dict)])
                )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
