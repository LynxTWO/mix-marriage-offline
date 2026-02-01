import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.make_demo_stems import make_demo_stems


class TestAnalyzeStemsKeepScan(unittest.TestCase):
    def _run_analyze(self, stems_dir: Path, out_report: Path, extra_args: list[str] | None = None) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        analyze_stems = repo_root / "tools" / "analyze_stems.py"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        command = [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            os.fspath(analyze_stems),
            os.fspath(stems_dir),
            "--out-report",
            os.fspath(out_report),
        ]
        if extra_args:
            command.extend(extra_args)

        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=os.fspath(repo_root),
        )

    def test_default_deletes_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)
            out_report = Path(temp_dir) / "out.json"
            scan_report = out_report.with_name(f"{out_report.stem}.scan{out_report.suffix}")

            self._run_analyze(stems_dir, out_report)

            self.assertTrue(out_report.exists())
            self.assertFalse(scan_report.exists())

    def test_keep_scan_preserves_intermediate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)
            out_report = Path(temp_dir) / "out.json"
            scan_report = out_report.with_name(f"{out_report.stem}.scan{out_report.suffix}")

            self._run_analyze(stems_dir, out_report, ["--keep-scan"])

            self.assertTrue(out_report.exists())
            self.assertTrue(scan_report.exists())


if __name__ == "__main__":
    unittest.main()
