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


def _suggested_keywords_by_role(path: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    current_role: str | None = None
    in_keywords = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("  ROLE.") and line.endswith(":"):
            current_role = line.strip()[:-1]
            rows.setdefault(current_role, [])
            in_keywords = False
            continue
        if current_role is None:
            continue
        if line.strip() == "keywords:":
            in_keywords = True
            continue
        if in_keywords and line.startswith("      - "):
            rows[current_role].append(line.removeprefix("      - ").strip())
            continue
        if line.startswith("    ") and line.strip() == "{}":
            in_keywords = False
    return rows


class TestToolsStemCorpusScan(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _tool_path(self) -> Path:
        return self._repo_root() / "tools" / "stem_corpus_scan.py"

    def _temp_root(self, name: str) -> Path:
        path = self._repo_root() / "sandbox_tmp" / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _run_scan(
        self,
        *,
        root: Path,
        out: Path,
        stats: Path,
        suggestions: Path | None = None,
        extra_args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.fspath(self._repo_root() / "src")
        cmd = [
            self._python_cmd(),
            os.fspath(self._tool_path()),
            "--root",
            os.fspath(root),
            "--out",
            os.fspath(out),
            "--stats",
            os.fspath(stats),
        ]
        if suggestions is not None:
            cmd.extend(["--suggestions-out", os.fspath(suggestions)])
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    def test_scan_outputs_are_deterministic_and_sorted(self) -> None:
        temp_root = self._temp_root("test_tools_stem_corpus_scan_deterministic")
        try:
            stems_root = temp_root / "Cambridge Set"
            out_path = temp_root / "cambridge.corpus.jsonl"
            stats_path = temp_root / "cambridge.corpus.stats.json"
            suggestions_path = temp_root / "cambridge.role_lexicon.suggestions.yaml"

            _write_tiny_wav(stems_root / "Disc B" / "stems" / "03_unknown_xyz.wav")
            _write_tiny_wav(stems_root / "Disc A" / "stems" / "02_vox lead.wav")
            _write_tiny_wav(stems_root / "Disc A" / "stems" / "01_kick.wav")

            first_result = self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
            )
            first_out_text = out_path.read_text(encoding="utf-8")
            first_stats_text = stats_path.read_text(encoding="utf-8")
            first_suggestions_text = suggestions_path.read_text(encoding="utf-8")

            second_result = self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
            )
            second_out_text = out_path.read_text(encoding="utf-8")
            second_stats_text = stats_path.read_text(encoding="utf-8")
            second_suggestions_text = suggestions_path.read_text(encoding="utf-8")

            self.assertEqual(first_result.stdout, second_result.stdout)
            self.assertEqual(first_out_text, second_out_text)
            self.assertEqual(first_stats_text, second_stats_text)
            self.assertEqual(first_suggestions_text, second_suggestions_text)

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
                    "scan_params",
                    "token_frequency_top",
                    "total_files",
                    "unknown_token_frequency_top",
                ],
            )
            self.assertEqual(stats_payload.get("total_files"), 3)

            scan_params = stats_payload.get("scan_params")
            self.assertIsInstance(scan_params, dict)
            if isinstance(scan_params, dict):
                self.assertEqual(scan_params.get("include_folder_tokens"), False)
                self.assertEqual(scan_params.get("min_count"), 10)
                self.assertEqual(scan_params.get("min_set_count"), 3)
                self.assertEqual(scan_params.get("min_precision"), 0.85)
                self.assertEqual(scan_params.get("min_confidence"), 0.8)
                stopwords = scan_params.get("stopwords")
                self.assertIsInstance(stopwords, list)
                if isinstance(stopwords, list):
                    self.assertIn("mix", stopwords)
                    self.assertIn("version", stopwords)

            token_top = stats_payload.get("token_frequency_top")
            self.assertIsInstance(token_top, list)
            if isinstance(token_top, list):
                self.assertTrue(
                    _is_ranked_token_rows([row for row in token_top if isinstance(row, dict)])
                )

            self.assertTrue(first_suggestions_text.startswith("# HUMAN REVIEW REQUIRED"))
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_folder_tokens_are_opt_in_for_suggestions(self) -> None:
        temp_root = self._temp_root("test_tools_stem_corpus_scan_folder_tokens")
        try:
            stems_root = temp_root / "Cambridge Set"
            out_path = temp_root / "cambridge.corpus.jsonl"
            stats_path = temp_root / "cambridge.corpus.stats.json"
            suggestions_off = temp_root / "suggestions_off.yaml"
            suggestions_on = temp_root / "suggestions_on.yaml"

            _write_tiny_wav(stems_root / "Disc A" / "folderonly" / "vox lead alpha.wav")
            _write_tiny_wav(stems_root / "Disc B" / "folderonly" / "vox lead beta.wav")

            threshold_args = [
                "--min-count",
                "1",
                "--min-set-count",
                "1",
                "--min-precision",
                "0.0",
                "--min-confidence",
                "0.0",
            ]

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_off,
                extra_args=threshold_args,
            )
            text_without_folders = suggestions_off.read_text(encoding="utf-8")
            self.assertNotIn("- folderonly", text_without_folders)

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_on,
                extra_args=threshold_args + ["--include-folder-tokens"],
            )
            text_with_folders = suggestions_on.read_text(encoding="utf-8")
            self.assertIn("- folderonly", text_with_folders)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_digit_only_tokens_are_excluded(self) -> None:
        temp_root = self._temp_root("test_tools_stem_corpus_scan_digit_filter")
        try:
            stems_root = temp_root / "Cambridge Set"
            out_path = temp_root / "cambridge.corpus.jsonl"
            stats_path = temp_root / "cambridge.corpus.stats.json"
            suggestions_path = temp_root / "suggestions.yaml"

            _write_tiny_wav(stems_root / "Disc A" / "stems" / "vox lead 123.wav")
            _write_tiny_wav(stems_root / "Disc B" / "stems" / "vox lead 123.wav")

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
                extra_args=[
                    "--min-count",
                    "1",
                    "--min-set-count",
                    "1",
                    "--min-precision",
                    "0.0",
                    "--min-confidence",
                    "0.0",
                ],
            )
            suggestion_text = suggestions_path.read_text(encoding="utf-8")
            self.assertNotIn("- 123", suggestion_text)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_min_thresholds_control_suggestions(self) -> None:
        temp_root = self._temp_root("test_tools_stem_corpus_scan_thresholds")
        try:
            stems_root = temp_root / "Cambridge Set"
            out_path = temp_root / "cambridge.corpus.jsonl"
            stats_path = temp_root / "cambridge.corpus.stats.json"
            suggestions_path = temp_root / "suggestions.yaml"

            _write_tiny_wav(stems_root / "Set 1" / "stems" / "vox lead chorus blend.wav")
            _write_tiny_wav(stems_root / "Set 2" / "stems" / "vox lead chorus blend.wav")
            _write_tiny_wav(stems_root / "Set 3" / "stems" / "vox lead chorus.wav")
            _write_tiny_wav(stems_root / "Set 4" / "stems" / "synth lead blend.wav")

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
                extra_args=[
                    "--min-count",
                    "3",
                    "--min-set-count",
                    "3",
                    "--min-precision",
                    "0.8",
                    "--min-confidence",
                    "0.0",
                ],
            )
            strict_keywords = _suggested_keywords_by_role(suggestions_path)
            strict_all = sorted(
                token
                for tokens in strict_keywords.values()
                for token in tokens
            )
            self.assertIn("chorus", strict_all)
            self.assertNotIn("blend", strict_all)

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
                extra_args=[
                    "--min-count",
                    "3",
                    "--min-set-count",
                    "3",
                    "--min-precision",
                    "0.6",
                    "--min-confidence",
                    "0.0",
                ],
            )
            relaxed_precision = _suggested_keywords_by_role(suggestions_path)
            relaxed_all = sorted(
                token
                for tokens in relaxed_precision.values()
                for token in tokens
            )
            self.assertIn("chorus", relaxed_all)
            self.assertIn("blend", relaxed_all)

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
                extra_args=[
                    "--min-count",
                    "4",
                    "--min-set-count",
                    "3",
                    "--min-precision",
                    "0.6",
                    "--min-confidence",
                    "0.0",
                ],
            )
            count_filtered = _suggested_keywords_by_role(suggestions_path)
            count_all = sorted(
                token
                for tokens in count_filtered.values()
                for token in tokens
            )
            self.assertNotIn("chorus", count_all)
            self.assertNotIn("blend", count_all)

            self._run_scan(
                root=stems_root,
                out=out_path,
                stats=stats_path,
                suggestions=suggestions_path,
                extra_args=[
                    "--min-count",
                    "3",
                    "--min-set-count",
                    "4",
                    "--min-precision",
                    "0.6",
                    "--min-confidence",
                    "0.0",
                ],
            )
            set_filtered = _suggested_keywords_by_role(suggestions_path)
            set_all = sorted(
                token
                for tokens in set_filtered.values()
                for token in tokens
            )
            self.assertNotIn("chorus", set_all)
            self.assertNotIn("blend", set_all)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
