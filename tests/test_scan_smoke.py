import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.make_demo_stems import make_demo_stems


class TestScanSessionSmoke(unittest.TestCase):
    def test_scan_session_schema_and_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            make_demo_stems(stems_dir)

            repo_root = Path(__file__).resolve().parents[1]
            scan_session = repo_root / "tools" / "scan_session.py"
            schema_path = repo_root / "schemas" / "report.schema.json"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(scan_session),
                    os.fspath(stems_dir),
                    "--schema",
                    os.fspath(schema_path),
                    "--meters",
                    "basic",
                    "--peak",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            report = json.loads(result.stdout)
            self.assertEqual(
                report.get("session", {}).get("stems_dir"),
                stems_dir.resolve().as_posix(),
            )
            stems = report.get("session", {}).get("stems", [])
            self.assertGreaterEqual(len(stems), 1)
            has_measurements = any(
                isinstance(stem.get("measurements"), list) and stem["measurements"]
                for stem in stems
                if isinstance(stem, dict)
            )
            self.assertTrue(has_measurements)
            evidence_ids = {
                measurement.get("evidence_id")
                for stem in stems
                if isinstance(stem, dict)
                for measurement in stem.get("measurements", [])
                if isinstance(measurement, dict)
            }
            self.assertIn("EVID.METER.SAMPLE_PEAK_DBFS", evidence_ids)
            self.assertIn("EVID.METER.PEAK_DBFS", evidence_ids)
            self.assertIn("EVID.METER.CLIP_SAMPLE_COUNT", evidence_ids)
            self.assertIn("EVID.QUALITY.CLIPPED_SAMPLES_COUNT", evidence_ids)
            mix_complexity = report.get("mix_complexity", {})
            self.assertIsInstance(mix_complexity, dict)
            self.assertIn("density_mean", mix_complexity)
            self.assertIn("density_peak", mix_complexity)
            self.assertIn("top_masking_pairs", mix_complexity)


if __name__ == "__main__":
    unittest.main()
