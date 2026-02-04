import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestDownmixQaSmoke(unittest.TestCase):
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

    def _write_fake_ffmpeg(self, directory: Path) -> Path:
        script_path = directory / "fake_ffmpeg.py"
        script_path.write_text(
            (
                "import os\n"
                "import struct\n"
                "import sys\n"
                "\n"
                "def main() -> None:\n"
                "    args = sys.argv[1:]\n"
                "    path = args[args.index('-i') + 1] if '-i' in args else args[-1]\n"
                "    name = os.path.basename(path)\n"
                "    frames = 24000\n"
                "    if name.startswith('src'):\n"
                "        samples = [0.1, 0.1, 0.0, 0.0, 0.0, 0.0] * frames\n"
                "    else:\n"
                "        samples = [0.1, 0.1] * frames\n"
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

    def test_downmix_qa_basic_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            src_path = temp_path / "src.flac"
            ref_path = temp_path / "ref.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = self._write_fake_ffprobe(temp_path, ref_channels=2)
            ffmpeg_path = self._write_fake_ffmpeg(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

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
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            downmix_qa = payload.get("downmix_qa", {})
            measurements = downmix_qa.get("measurements", [])
            evidence_ids = {
                item.get("evidence_id")
                for item in measurements
                if isinstance(item, dict)
            }
            self.assertIn("EVID.DOWNMIX.QA.LOG", evidence_ids)
            self.assertIn("EVID.DOWNMIX.QA.CORR_FOLD", evidence_ids)
            self.assertIn("EVID.DOWNMIX.QA.CORR_REF", evidence_ids)
            self.assertIn("EVID.DOWNMIX.QA.CORR_DELTA", evidence_ids)

    def test_downmix_qa_ref_not_stereo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            src_path = temp_path / "src.flac"
            ref_path = temp_path / "ref.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = self._write_fake_ffprobe(temp_path, ref_channels=6)
            ffmpeg_path = self._write_fake_ffmpeg(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

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
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            payload = json.loads(result.stdout)
            issues = payload.get("downmix_qa", {}).get("issues", [])
            issue_ids = {
                issue.get("issue_id")
                for issue in issues
                if isinstance(issue, dict)
            }
            self.assertIn("ISSUE.DOWNMIX.QA.CHANNELS_INVALID", issue_ids)

    def test_downmix_qa_missing_ffprobe_flac(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            src_path = temp_path / "src.flac"
            ref_path = temp_path / "ref.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffmpeg_path = self._write_fake_ffmpeg(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env.pop("MMO_FFPROBE_PATH", None)
            env["PATH"] = ""

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
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            payload = json.loads(result.stdout)
            issues = payload.get("downmix_qa", {}).get("issues", [])
            issue_ids = {
                issue.get("issue_id")
                for issue in issues
                if isinstance(issue, dict)
            }
            self.assertIn("ISSUE.DOWNMIX.QA.DECODE_FAILED", issue_ids)
            evidence_values = {
                evidence.get("value")
                for issue in issues
                if isinstance(issue, dict)
                for evidence in issue.get("evidence", [])
                if isinstance(evidence, dict)
                and evidence.get("evidence_id") == "EVID.VALIDATION.MISSING_OPTIONAL_DEP"
            }
            self.assertIn("ffprobe", evidence_values)

    def test_downmix_qa_max_seconds_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repo_root = Path(__file__).resolve().parents[1]
            src_path = temp_path / "src.flac"
            ref_path = temp_path / "ref.flac"
            src_path.write_bytes(b"")
            ref_path.write_bytes(b"")

            ffprobe_path = self._write_fake_ffprobe(temp_path, ref_channels=2)
            ffmpeg_path = self._write_fake_ffmpeg(temp_path)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            env["MMO_FFMPEG_PATH"] = str(ffmpeg_path)
            env["MMO_FFPROBE_PATH"] = str(ffprobe_path)

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
                    "--max-seconds",
                    "0.25",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            measurements = payload.get("downmix_qa", {}).get("measurements", [])
            log_values = [
                item.get("value")
                for item in measurements
                if isinstance(item, dict)
                and item.get("evidence_id") == "EVID.DOWNMIX.QA.LOG"
            ]
            self.assertEqual(len(log_values), 1)
            log_payload = json.loads(log_values[0])
            self.assertEqual(log_payload.get("max_seconds"), 0.25)
            self.assertEqual(log_payload.get("seconds_compared"), 0.25)


if __name__ == "__main__":
    unittest.main()
