import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.core import gates as gates_module
from tools import analyze_stems, run_pipeline


class _FakeValidatePluginsModule:
    @staticmethod
    def validate_plugins(_plugins_dir: Path, _schema_path: Path) -> dict:
        return {
            "registry_file": "",
            "ok": True,
            "issue_counts": {"error": 0, "warn": 0},
            "issues": [],
        }


class TestProfilePlumbing(unittest.TestCase):
    def test_analyze_stems_passes_profile_to_run_pipeline(self) -> None:
        with mock.patch("tools.analyze_stems._run_command", return_value=0) as mocked_run:
            exit_code = analyze_stems._run_pipeline(
                Path("tools"),
                Path("in.scan.json"),
                Path("out.json"),
                "plugins",
                "PROFILE.FULL_SEND",
            )

        self.assertEqual(exit_code, 0)
        command = mocked_run.call_args.args[0]
        self.assertIn("--profile", command)
        profile_index = command.index("--profile")
        self.assertEqual(command[profile_index + 1], "PROFILE.FULL_SEND")

    def test_run_pipeline_passes_profile_to_apply_gates(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.PIPELINE.PROFILE",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.GAIN.LARGE",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -8.0,
                            "unit_id": "UNIT.DB",
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_path = temp_path / "out.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with mock.patch(
                "tools.run_pipeline._load_validate_plugins_module",
                return_value=_FakeValidatePluginsModule(),
            ), mock.patch(
                "mmo.core.pipeline.load_plugins",
                return_value=[],
            ), mock.patch(
                "mmo.core.pipeline.run_detectors",
                return_value=None,
            ), mock.patch(
                "mmo.core.pipeline.run_resolvers",
                return_value=None,
            ), mock.patch(
                "mmo.core.gates.apply_gates_to_report",
                wraps=gates_module.apply_gates_to_report,
            ) as patched_apply_gates, mock.patch.object(
                sys,
                "argv",
                [
                    "run_pipeline.py",
                    "--report",
                    str(report_path),
                    "--plugins",
                    "plugins",
                    "--out",
                    str(out_path),
                    "--profile",
                    "PROFILE.FULL_SEND",
                ],
            ):
                exit_code = run_pipeline.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())
            self.assertTrue(patched_apply_gates.called)
            self.assertEqual(
                patched_apply_gates.call_args.kwargs.get("profile_id"),
                "PROFILE.FULL_SEND",
            )

            output_report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(output_report.get("profile_id"), "PROFILE.FULL_SEND")
            rec = output_report["recommendations"][0]
            self.assertTrue(rec.get("eligible_auto_apply"))


if __name__ == "__main__":
    unittest.main()
