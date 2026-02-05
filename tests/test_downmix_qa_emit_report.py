import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from mmo.exporters import pdf_report

try:
    import reportlab  # noqa: F401
except ImportError:
    reportlab = None


class TestDownmixQaEmitReport(unittest.TestCase):
    def _write_fake_ffprobe(self, directory: Path, *, ref_channels: int = 2) -> Path:
        script_path = directory / "fake_ffprobe.py"
        script_path.write_text(
            (
                "import json\n"
                "import os\n"
                "import sys\n"
                "\n"
                "def main() -> None:\n"
                "    path = sys.argv[-1]\n"
                "    name = os.path.basename(path)\n"
                "    if name.startswith('src'):\n"
                "        payload = {\n"
                "            'streams': [\n"
                "                {\n"
                "                    'codec_type': 'audio',\n"
                "                    'codec_name': 'flac',\n"
                "                    'channels': 6,\n"
                "                    'sample_rate': '48000',\n"
                "                    'duration': '0.5',\n"
                "                    'channel_layout': '5.1(side)',\n"
                "                }\n"
                "            ],\n"
                "            'format': {'duration': '0.5'},\n"
                "        }\n"
                "    else:\n"
                f"        payload = {{\n"
                f"            'streams': [\n"
                f"                {{\n"
                f"                    'codec_type': 'audio',\n"
                f"                    'codec_name': 'wav',\n"
                f"                    'channels': {ref_channels},\n"
                f"                    'sample_rate': '48000',\n"
                f"                    'duration': '0.5',\n"
                f"                    'channel_layout': 'stereo',\n"
                f"                }}\n"
                f"            ],\n"
                f"            'format': {{'duration': '0.5'}},\n"
                f"        }}\n"
                "    print(json.dumps(payload))\n"
                "\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
            encoding="utf-8",
        )
        return script_path

    def _write_fake_ffmpeg(self, directory: Path, *, ref_samples: Optional[list] = None) -> Path:
        script_path = directory / "fake_ffmpeg.py"
        if ref_samples is None:
            ref_samples = [0.1, 0.1]
        ref_samples_literal = repr(ref_samples)
        script_path.write_text(
            (
                "import os\n"
                "import struct\n"
                "import sys\n"
                "\n"
                f"REF_SAMPLES = {ref_samples_literal}\n"
                "\n"
                "def main() -> None:\n"
                "    args = sys.argv[1:]\n"
                "    path = args[args.index('-i') + 1] if '-i' in args else args[-1]\n"
                "    name = os.path.basename(path)\n"
                "    frames = 24000\n"
                "    if name.startswith('src'):\n"
                "        samples = [0.1, 0.1, 0.0, 0.0, 0.0, 0.0] * frames\n"
                "    else:\n"
                "        samples = REF_SAMPLES * frames\n"
                "    payload = struct.pack(f'<{len(samples)}d', *samples)\n"
                "    sys.stdout.buffer.write(payload)\n"
                "\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
            encoding="utf-8",
        )
        return script_path

    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _base_env(self, repo_root: Path, ffmpeg_path: Path, ffprobe_path: Optional[Path]) -> dict:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
        if ffprobe_path is None:
            env.pop("MMO_FFPROBE_PATH", None)
            env["PATH"] = ""
        else:
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)
        return env

    def _emit_report(self, temp_path: Path, *, ref_samples: Optional[list] = None) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        src_path = temp_path / "src.flac"
        ref_path = temp_path / "ref.flac"
        src_path.write_bytes(b"")
        ref_path.write_bytes(b"")

        ffprobe_path = self._write_fake_ffprobe(temp_path, ref_channels=2)
        ffmpeg_path = self._write_fake_ffmpeg(temp_path, ref_samples=ref_samples)
        env = self._base_env(repo_root, ffmpeg_path, ffprobe_path)

        report_path = temp_path / "qa_report.json"
        result = subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "downmix",
                "qa",
                "--src",
                os.fspath(src_path),
                "--ref",
                os.fspath(ref_path),
                "--source-layout",
                "LAYOUT.5_1",
                "--meters",
                "basic",
                "--emit-report",
                os.fspath(report_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(report_path.exists())
        return report_path

    def test_downmix_qa_emit_report_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = self._emit_report(temp_path)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            for key in ["session", "issues", "recommendations", "downmix_qa"]:
                self.assertIn(key, payload)
            self.assertEqual(payload.get("recommendations"), [])

            downmix_qa = payload.get("downmix_qa", {})
            self.assertIn("src_path", downmix_qa)
            self.assertIn("ref_path", downmix_qa)
            measurements = downmix_qa.get("measurements", [])
            self.assertIsInstance(measurements, list)
            evidence_ids = {
                item.get("evidence_id")
                for item in measurements
                if isinstance(item, dict)
            }
            self.assertIn("EVID.DOWNMIX.QA.LOG", evidence_ids)
            summary_fields = pdf_report._downmix_qa_summary_fields(downmix_qa)
            summary_map = {label: value for label, value in summary_fields}
            self.assertIn("policy_id", summary_map)
            self.assertIn("matrix_id", summary_map)
            self.assertIn("source_layout_id", summary_map)
            self.assertIn("target_layout_id", summary_map)
            self.assertIn("seconds_compared", summary_map)
            self.assertIn("max_seconds", summary_map)

    def test_downmix_qa_emit_report_pdf_export(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = self._emit_report(temp_path)
            repo_root = Path(__file__).resolve().parents[1]

            pdf_path = temp_path / "qa_report.pdf"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "export",
                    "--report",
                    os.fspath(report_path),
                    "--pdf",
                    os.fspath(pdf_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 0)

    def test_downmix_qa_emit_report_includes_diagnostic_rec_on_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = self._emit_report(temp_path, ref_samples=[0.1, -0.1, 0.2, -0.2])

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            recommendations = payload.get("recommendations", [])
            self.assertEqual(len(recommendations), 2)
            diagnostic_recs = [
                rec
                for rec in recommendations
                if rec.get("action_id") == "ACTION.DIAGNOSTIC.CHECK_DOWNMIX_QA"
            ]
            self.assertEqual(len(diagnostic_recs), 1)
            rec = diagnostic_recs[0]
            gate_results = rec.get("gate_results", [])
            gate_ids = {result.get("gate_id") for result in gate_results}
            self.assertIn("GATE.DOWNMIX_QA_CORR_DELTA_LIMIT", gate_ids)
            self.assertIn("GATE.DIAGNOSTIC_SUGGEST_ONLY", gate_ids)
            corr_gate_results = [
                result
                for result in gate_results
                if result.get("gate_id") == "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"
            ]
            self.assertTrue(
                any(
                    result.get("context") == "suggest" and result.get("outcome") == "reject"
                    for result in corr_gate_results
                )
            )

            render_recs = [
                rec
                for rec in recommendations
                if rec.get("action_id") == "ACTION.DOWNMIX.RENDER"
            ]
            self.assertEqual(len(render_recs), 1)
            render_rec = render_recs[0]
            render_params = render_rec.get("params", [])
            param_ids = {
                param.get("param_id")
                for param in render_params
                if isinstance(param, dict)
            }
            self.assertIn("PARAM.DOWNMIX.POLICY_ID", param_ids)
            self.assertIn("PARAM.DOWNMIX.TARGET_LAYOUT_ID", param_ids)
            render_gate_results = render_rec.get("gate_results", [])
            render_gate_ids = {result.get("gate_id") for result in render_gate_results}
            self.assertIn("GATE.DOWNMIX_QA_CORR_DELTA_LIMIT", render_gate_ids)
            self.assertFalse(render_rec.get("eligible_render", True))
            corr_render_results = [
                result
                for result in render_gate_results
                if result.get("gate_id") == "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT"
            ]
            self.assertTrue(
                any(
                    result.get("context") == "render" and result.get("outcome") == "reject"
                    for result in corr_render_results
                )
            )


if __name__ == "__main__":
    unittest.main()
