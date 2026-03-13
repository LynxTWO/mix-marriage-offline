import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


class TestCliPresetPreview(unittest.TestCase):
    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        src_dir = str((repo_root / "src").resolve())
        self._original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = (
            src_dir
            if not self._original_pythonpath
            else f"{src_dir}{os.pathsep}{self._original_pythonpath}"
        )

    def tearDown(self) -> None:
        if self._original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
            return
        os.environ["PYTHONPATH"] = self._original_pythonpath

    def test_presets_preview_json_is_deterministic_and_schema_valid(self) -> None:
        command = [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            "-m",
            "mmo",
            "presets",
            "preview",
            "PRESET.SAFE_CLEANUP",
            "--format",
            "json",
        ]
        first = subprocess.run(command, check=False, capture_output=True, text=True)
        second = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, dict)
        self.assertEqual(
            sorted(payload.keys()),
            sorted(
                [
                    "preset_id",
                    "label",
                    "overlay",
                    "category",
                    "tags",
                    "goals",
                    "warnings",
                    "help",
                    "effective_run_config",
                    "changes_from_defaults",
                    "preview_safety",
                    "feature_initialization",
                ]
            ),
        )

        help_payload = payload.get("help")
        self.assertIsInstance(help_payload, dict)
        if not isinstance(help_payload, dict):
            return
        self.assertIn("title", help_payload)
        self.assertIn("short", help_payload)
        self.assertIn("cues", help_payload)
        self.assertIn("watch_out_for", help_payload)

        effective_run_config = payload.get("effective_run_config")
        self.assertIsInstance(effective_run_config, dict)
        if not isinstance(effective_run_config, dict):
            return

        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (repo_root / "schemas" / "run_config.schema.json").read_text(encoding="utf-8")
        )
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(effective_run_config)

        changes = payload.get("changes_from_defaults")
        self.assertIsInstance(changes, list)
        if not isinstance(changes, list):
            return
        key_paths = [
            item.get("key_path")
            for item in changes
            if isinstance(item, dict) and isinstance(item.get("key_path"), str)
        ]
        self.assertEqual(key_paths, sorted(key_paths))

        preview_safety = payload.get("preview_safety")
        self.assertIsInstance(preview_safety, dict)
        if not isinstance(preview_safety, dict):
            return
        self.assertTrue(preview_safety.get("evaluation_only"))
        self.assertEqual(preview_safety.get("guard_db"), 2.0)

        feature_initialization = payload.get("feature_initialization")
        self.assertIsInstance(feature_initialization, list)

    def test_presets_preview_text_includes_guidance_headers(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "preview",
                "PRESET.SAFE_CLEANUP",
                "--format",
                "text",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Safe cleanup (PRESET.SAFE_CLEANUP) [WORKFLOW]", result.stdout)
        self.assertIn("What changes if you use this preset:", result.stdout)

        lines = result.stdout.splitlines()
        self.assertIn("When to use:", lines)
        when_to_use_idx = lines.index("When to use:")
        cue_lines: list[str] = []
        for line in lines[when_to_use_idx + 1 :]:
            if line == "Watch out for:":
                break
            if line.startswith("  - "):
                cue_lines.append(line)
        self.assertTrue(cue_lines, msg=result.stdout)

    def test_presets_preview_merge_order_cli_profile_overrides_preset(self) -> None:
        result = subprocess.run(
            [
                os.fspath(os.getenv("PYTHON", "") or sys.executable),
                "-m",
                "mmo",
                "presets",
                "preview",
                "PRESET.TURBO_DRAFT",
                "--profile",
                "PROFILE.ASSIST",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        effective_run_config = payload.get("effective_run_config")
        self.assertIsInstance(effective_run_config, dict)
        if not isinstance(effective_run_config, dict):
            return
        self.assertEqual(effective_run_config.get("profile_id"), "PROFILE.ASSIST")

        changes = payload.get("changes_from_defaults", [])
        self.assertIsInstance(changes, list)
        if not isinstance(changes, list):
            return
        profile_changes = [
            item
            for item in changes
            if isinstance(item, dict) and item.get("key_path") == "profile_id"
        ]
        self.assertTrue(profile_changes, msg=result.stdout)
        self.assertEqual(profile_changes[-1].get("after"), "PROFILE.ASSIST")

    def test_presets_preview_report_context_is_bounded_and_explainable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "run_config": {"profile_id": "PROFILE.ASSIST"},
                        "vibe_signals": {"translation_risk": "high"},
                        "metering": {
                            "session": {
                                "lufs_i_range_db": 7.2,
                                "true_peak_max_dbtp": -0.6,
                            }
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    os.fspath(os.getenv("PYTHON", "") or sys.executable),
                    "-m",
                    "mmo",
                    "presets",
                    "preview",
                    "PRESET.VIBE.DENSE_GLUE",
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
        preview_safety = payload.get("preview_safety")
        self.assertIsInstance(preview_safety, dict)
        if not isinstance(preview_safety, dict):
            return

        self.assertTrue(preview_safety.get("evaluation_only"))
        self.assertTrue(preview_safety.get("commit_required"))
        self.assertEqual(preview_safety.get("pack_id"), "PACK.VIBE_STARTER")
        self.assertEqual(
            preview_safety.get("feature_init_policy_id"),
            "FEATURE_INIT.REPORT_CONTEXT.BOUNDED_V1",
        )
        self.assertEqual(preview_safety.get("current_profile_id"), "PROFILE.ASSIST")
        self.assertEqual(preview_safety.get("target_profile_id"), "PROFILE.FULL_SEND")
        self.assertEqual(preview_safety.get("predicted_jump_db"), 1.5)
        self.assertEqual(preview_safety.get("guard_db"), 1.0)
        self.assertEqual(preview_safety.get("applied_preview_compensation_db"), -1.0)
        self.assertIn("evaluation-only", str(preview_safety.get("details")))

        feature_initialization = payload.get("feature_initialization")
        self.assertIsInstance(feature_initialization, list)
        if not isinstance(feature_initialization, list):
            return
        rule_ids = [
            item.get("rule_id")
            for item in feature_initialization
            if isinstance(item, dict)
        ]
        self.assertIn("FEATURE_INIT.REPORT_CONTEXT.TRANSLATION_RISK_HIGH", rule_ids)
        self.assertIn("FEATURE_INIT.REPORT_CONTEXT.TRUE_PEAK_TIGHTEN", rule_ids)
        self.assertIn("FEATURE_INIT.REPORT_CONTEXT.PROFILE_DELTA", rule_ids)


if __name__ == "__main__":
    unittest.main()
