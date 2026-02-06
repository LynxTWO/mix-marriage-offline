import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCliPresets(unittest.TestCase):
    def test_presets_list_json_is_sorted(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "list",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)
        preset_ids: list[str] = []
        for item in payload:
            self.assertIsInstance(item, dict)
            if not isinstance(item, dict):
                continue
            for required_key in ["preset_id", "file", "label", "description"]:
                self.assertIn(required_key, item)
            preset_id = item.get("preset_id")
            if isinstance(preset_id, str):
                preset_ids.append(preset_id)
        self.assertEqual(preset_ids, sorted(preset_ids))

    def test_presets_list_text_includes_label_and_is_sorted(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "list",
                "--format",
                "text",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "Expected at least one preset line in text output.")

        preset_ids: list[str] = []
        for line in lines:
            preset_id, separator, rest = line.partition("  ")
            self.assertEqual(separator, "  ", msg=f"Missing label separator in line: {line}")
            self.assertTrue(rest.strip(), msg=f"Missing label in line: {line}")
            preset_ids.append(preset_id)
        self.assertEqual(preset_ids, sorted(preset_ids))
        self.assertIn("PRESET.SAFE_CLEANUP  Safe cleanup [WORKFLOW]", lines)

    def test_presets_list_tag_filter_works(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "list",
                "--tag",
                "translation",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(
            [item.get("preset_id") for item in payload if isinstance(item, dict)],
            [
                "PRESET.SAFE_CLEANUP",
                "PRESET.VIBE.LIVE_YOU_ARE_THERE",
                "PRESET.VIBE.TRANSLATION_SAFE",
                "PRESET.VIBE.VOCAL_FORWARD",
            ],
        )

    def test_presets_show_json_includes_preset_id(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "show",
                "PRESET.SAFE_CLEANUP",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("preset_id"), "PRESET.SAFE_CLEANUP")

        run_config = payload.get("run_config")
        self.assertIsInstance(run_config, dict)
        if not isinstance(run_config, dict):
            return
        self.assertEqual(run_config.get("preset_id"), "PRESET.SAFE_CLEANUP")

    def test_presets_recommend_json_outputs_derived_list(self) -> None:
        report = {
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "medium",
                "translation_risk": "high",
                "notes": [],
            },
            "recommendations": [{"extreme": True}],
            "profile_id": "PROFILE.FULL_SEND",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    "-m",
                    "mmo",
                    "presets",
                    "recommend",
                    "--report",
                    os.fspath(report_path),
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [item.get("preset_id") for item in payload if isinstance(item, dict)],
            [
                "PRESET.SAFE_CLEANUP",
                "PRESET.VIBE.TRANSLATION_SAFE",
                "PRESET.VIBE.BRIGHT_AIRY",
            ],
        )
        self.assertTrue(
            all(
                isinstance(item, dict) and "report_id" not in item
                for item in payload
            )
        )

    def test_presets_recommend_text_includes_overlay_and_reasons(self) -> None:
        report = {
            "vibe_signals": {
                "density_level": "high",
                "masking_level": "high",
                "translation_risk": "medium",
                "notes": [],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    "-m",
                    "mmo",
                    "presets",
                    "recommend",
                    "--report",
                    os.fspath(report_path),
                    "--format",
                    "text",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PRESET.VIBE.PUNCHY_TIGHT  Punchy tight (Punch)", result.stdout)
        self.assertIn("  - ", result.stdout)


if __name__ == "__main__":
    unittest.main()
