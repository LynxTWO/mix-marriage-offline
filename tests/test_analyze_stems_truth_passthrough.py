import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.make_demo_stems import make_demo_stems


class TestAnalyzeStemsTruthPassthrough(unittest.TestCase):
    def test_truth_meters_passthrough_adds_optional_dep_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)

            out_report = Path(temp_dir) / "out.json"
            scan_report = out_report.with_name(f"{out_report.stem}.scan{out_report.suffix}")

            fake_numpy_root = Path(temp_dir) / "fake_numpy"
            fake_numpy_pkg = fake_numpy_root / "numpy"
            fake_numpy_pkg.mkdir(parents=True)
            (fake_numpy_pkg / "__init__.py").write_text(
                "raise ImportError('Simulated missing numpy')\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                [os.fspath(fake_numpy_root), os.fspath(repo_root / "src")]
            )

            analyze_stems = repo_root / "tools" / "analyze_stems.py"
            subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(analyze_stems),
                    os.fspath(stems_dir),
                    "--out-report",
                    os.fspath(out_report),
                    "--keep-scan",
                    "--meters",
                    "truth",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                cwd=os.fspath(repo_root),
            )

            self.assertTrue(scan_report.exists())
            self.assertTrue(out_report.exists())

            with scan_report.open("r", encoding="utf-8") as handle:
                scan_data = json.load(handle)
            issues = scan_data.get("issues", [])
            issue_ids = {
                issue.get("issue_id")
                for issue in issues
                if isinstance(issue, dict)
            }
            self.assertIn("ISSUE.VALIDATION.OPTIONAL_DEP_MISSING", issue_ids)


if __name__ == "__main__":
    unittest.main()
