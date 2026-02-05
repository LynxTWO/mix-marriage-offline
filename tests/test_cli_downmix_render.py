import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema

from mmo.cli import main
from mmo.core import gates as gates_module


class TestCliDownmixRender(unittest.TestCase):
    def test_downmix_render_writes_valid_manifest_and_skips_blocked(self) -> None:
        eligible_id = "REC.CLI.RENDER.ELIGIBLE"
        blocked_id = "REC.CLI.RENDER.BLOCKED"
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.CLI.DOWNMIX.RENDER",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": eligible_id,
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.DOWNMIX.POLICY_ID",
                            "value": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.TARGET_LAYOUT_ID",
                            "value": "LAYOUT.2_0",
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.QA.LUFS_DELTA",
                            "value": 1.0,
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.QA.TRUE_PEAK_DELTA",
                            "value": 0.5,
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.QA.CORR_DELTA",
                            "value": 0.1,
                        },
                    ],
                },
                {
                    "recommendation_id": blocked_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -20.0,
                        }
                    ],
                },
            ],
        }

        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "render_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            manifest_path = temp_path / "render_manifest.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "downmix",
                    "render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(manifest_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(manifest_path.exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(manifest)

            renderer_manifests = manifest.get("renderer_manifests")
            self.assertIsInstance(renderer_manifests, list)
            safe_manifest = next(
                (
                    item
                    for item in renderer_manifests
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.SAFE"
                ),
                None,
            )
            self.assertIsNotNone(safe_manifest)
            if safe_manifest is None:
                return

            skipped = safe_manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            skipped_ids = [
                item.get("recommendation_id")
                for item in skipped
                if isinstance(item, dict)
            ]
            self.assertIn(blocked_id, skipped_ids)

            received_ids = safe_manifest.get("received_recommendation_ids")
            self.assertEqual(received_ids, [eligible_id])
            self.assertNotIn(blocked_id, received_ids)

    def test_downmix_render_passes_profile_to_gating(self) -> None:
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.CLI.DOWNMIX.RENDER.PROFILE",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.CLI.RENDER.PROFILE",
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.DOWNMIX.POLICY_ID",
                            "value": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.TARGET_LAYOUT_ID",
                            "value": "LAYOUT.2_0",
                        },
                    ],
                }
            ],
        }
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            manifest_path = temp_path / "render_manifest.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with mock.patch(
                "mmo.core.gates.apply_gates_to_report",
                wraps=gates_module.apply_gates_to_report,
            ) as patched_apply_gates:
                exit_code = main(
                    [
                        "downmix",
                        "render",
                        "--report",
                        str(report_path),
                        "--plugins",
                        str(repo_root / "plugins"),
                        "--out-manifest",
                        str(manifest_path),
                        "--profile",
                        "PROFILE.FULL_SEND",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(manifest_path.exists())
            self.assertTrue(patched_apply_gates.called)
            self.assertEqual(
                patched_apply_gates.call_args.kwargs.get("profile_id"),
                "PROFILE.FULL_SEND",
            )
            applied_report = patched_apply_gates.call_args.args[0]
            self.assertEqual(applied_report.get("profile_id"), "PROFILE.FULL_SEND")


if __name__ == "__main__":
    unittest.main()
