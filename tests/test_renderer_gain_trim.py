import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mmo.dsp.meters import compute_sample_peak_dbfs_wav
from tools.make_demo_stems import make_demo_stems


class TestRendererGainTrim(unittest.TestCase):
    def test_render_gain_trim_applies_negative_gain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            stems_dir = temp_root / "stems"
            out_dir = temp_root / "out"
            report_path = temp_root / "report.json"

            make_demo_stems(stems_dir)

            report = {
                "session": {
                    "stems": [
                        {
                            "stem_id": "kick",
                            "file_path": "kick.wav",
                        }
                    ]
                },
                "recommendations": [
                    {
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "params": [
                            {
                                "param_id": "PARAM.GAIN.DB",
                                "value": -6.0,
                            }
                        ],
                        "target": {
                            "scope": "stem",
                            "stem_id": "kick",
                        },
                    }
                ],
            }

            report_path.write_text(json.dumps(report), encoding="utf-8")

            repo_root = Path(__file__).resolve().parents[1]
            render_tool = repo_root / "tools" / "render_gain_trim.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")

            before_peak = compute_sample_peak_dbfs_wav(stems_dir / "kick.wav")

            subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    os.fspath(render_tool),
                    os.fspath(stems_dir),
                    "--report",
                    os.fspath(report_path),
                    "--out-dir",
                    os.fspath(out_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            rendered_path = out_dir / "kick.wav"
            self.assertTrue(rendered_path.exists())

            after_peak = compute_sample_peak_dbfs_wav(rendered_path)
            delta = before_peak - after_peak
            self.assertAlmostEqual(delta, 6.0, delta=0.4)


if __name__ == "__main__":
    unittest.main()
