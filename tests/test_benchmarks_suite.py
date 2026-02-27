import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestBenchmarkSuite(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_single_case_writes_json_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "bench.json"
            result = subprocess.run(
                [
                    self._python_cmd(),
                    "benchmarks/suite.py",
                    "--case",
                    "cli.roles.list_json",
                    "--runs",
                    "1",
                    "--warmup-runs",
                    "0",
                    "--out",
                    str(out_path),
                ],
                check=False,
                capture_output=True,
                cwd=repo_root,
                env=self._env(repo_root),
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("suite_version"), "1.1.0")
            summary = payload.get("summary", {})
            self.assertEqual(summary.get("case_count"), 1)
            self.assertEqual(summary.get("total_runs"), 1)

            cases = payload.get("cases", [])
            self.assertEqual(len(cases), 1)
            case = cases[0]
            self.assertEqual(case.get("case_id"), "cli.roles.list_json")
            self.assertEqual(case.get("runs"), 1)
            self.assertEqual(case.get("warmup_runs"), 0)
            metrics = case.get("metrics_ms", {})
            self.assertIn("mean_ms", metrics)
            self.assertIn("p95_ms", metrics)


if __name__ == "__main__":
    unittest.main()
