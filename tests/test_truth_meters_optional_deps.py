import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.make_demo_stems import make_demo_stems


class TestTruthMetersOptionalDeps(unittest.TestCase):
    def test_truth_meters_missing_numpy_adds_issue_and_validates_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)

            scan_session = repo_root / "tools" / "scan_session.py"
            schema_path = repo_root / "schemas" / "report.schema.json"

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

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--schema",
                    os.fspath(schema_path),
                    "--meters",
                    "truth",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            issues = report.get("issues", [])
            issue_ids = {
                issue.get("issue_id")
                for issue in issues
                if isinstance(issue, dict)
            }
            self.assertIn("ISSUE.VALIDATION.OPTIONAL_DEP_MISSING", issue_ids)

    def test_truth_meters_emit_measurements_when_numpy_available(self) -> None:
        if os.getenv("SKIP_NUMPY_TESTS"):
            self.skipTest("Skipping numpy-dependent test via SKIP_NUMPY_TESTS.")
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)

            scan_session = repo_root / "tools" / "scan_session.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--meters",
                    "truth",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            stems = report.get("session", {}).get("stems", [])
            evidence_ids = {
                measurement.get("evidence_id")
                for stem in stems
                if isinstance(stem, dict)
                for measurement in stem.get("measurements", [])
                if isinstance(measurement, dict)
            }
            self.assertIn("EVID.METER.TRUEPEAK_DBTP", evidence_ids)
            self.assertIn("EVID.METER.LUFS_I", evidence_ids)
            self.assertIn("EVID.METER.LUFS_S", evidence_ids)


if __name__ == "__main__":
    unittest.main()
