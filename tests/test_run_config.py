import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema

from mmo.cli import main
from mmo.core.run_config import load_run_config, merge_run_config, normalize_run_config


def _minimal_report_payload() -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.RUN.CONFIG",
        "project_id": "PROJECT.RUN.CONFIG",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": [],
    }


class TestRunConfig(unittest.TestCase):
    def test_load_normalize_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "run_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "truncate_values": "12",
                        "schema_version": "0.1.0",
                        "profile_id": " PROFILE.FULL_SEND ",
                        "meters": " truth ",
                        "max_seconds": "33.5",
                        "render": {"out_dir": " out/renders "},
                        "downmix": {
                            "target_layout_id": " LAYOUT.2_0 ",
                            "policy_id": " POLICY.DOWNMIX.STANDARD_FOLDOWN_V0 ",
                            "source_layout_id": " LAYOUT.5_1 ",
                        },
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_run_config(config_path)

        expected = normalize_run_config(
            {
                "schema_version": "0.1.0",
                "profile_id": "PROFILE.FULL_SEND",
                "meters": "truth",
                "max_seconds": 33.5,
                "truncate_values": 12,
                "downmix": {
                    "source_layout_id": "LAYOUT.5_1",
                    "target_layout_id": "LAYOUT.2_0",
                    "policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                },
                "render": {"out_dir": "out/renders"},
            }
        )
        self.assertEqual(loaded, expected)
        self.assertEqual(loaded, normalize_run_config(loaded))
        self.assertEqual(list(loaded.keys()), sorted(loaded.keys()))
        self.assertEqual(
            list(loaded["downmix"].keys()),
            sorted(loaded["downmix"].keys()),
        )

    def test_merge_cli_overrides_config(self) -> None:
        base_cfg = {
            "schema_version": "0.1.0",
            "profile_id": "PROFILE.FULL_SEND",
            "meters": "truth",
            "max_seconds": 120.0,
            "downmix": {
                "source_layout_id": "LAYOUT.5_1",
                "target_layout_id": "LAYOUT.2_0",
                "policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            },
        }
        cli_overrides = {
            "profile_id": "PROFILE.ASSIST",
            "meters": "basic",
            "downmix": {"policy_id": "POLICY.DOWNMIX.CINEMA_FOLDOWN_V0"},
        }
        merged = merge_run_config(base_cfg, cli_overrides)

        self.assertEqual(merged["profile_id"], "PROFILE.ASSIST")
        self.assertEqual(merged["meters"], "basic")
        self.assertEqual(merged["max_seconds"], 120.0)
        self.assertEqual(merged["downmix"]["source_layout_id"], "LAYOUT.5_1")
        self.assertEqual(merged["downmix"]["target_layout_id"], "LAYOUT.2_0")
        self.assertEqual(
            merged["downmix"]["policy_id"],
            "POLICY.DOWNMIX.CINEMA_FOLDOWN_V0",
        )

    def test_cli_analyze_config_override_and_report_stamp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads((repo_root / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "run_config.json"
            out_report = temp_path / "out.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "profile_id": "PROFILE.FULL_SEND",
                        "meters": "truth",
                    }
                ),
                encoding="utf-8",
            )

            def _fake_run_analyze(
                _tools_dir: Path,
                _stems_dir: Path,
                out_report_path: Path,
                _meters: str | None,
                _include_peak: bool,
                _plugins_dir: str,
                _keep_scan: bool,
                _profile_id: str,
            ) -> int:
                out_report_path.write_text(
                    json.dumps(_minimal_report_payload(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return 0

            with mock.patch("mmo.cli._run_analyze", side_effect=_fake_run_analyze) as patched_run:
                exit_code = main(
                    [
                        "analyze",
                        "dummy_stems",
                        "--out-report",
                        str(out_report),
                        "--config",
                        str(config_path),
                        "--profile",
                        "PROFILE.ASSIST",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(patched_run.called)
            self.assertEqual(patched_run.call_args.args[3], "truth")
            self.assertEqual(patched_run.call_args.args[7], "PROFILE.ASSIST")

            report = json.loads(out_report.read_text(encoding="utf-8"))
            validator.validate(report)
            self.assertIn("run_config", report)
            run_config = report["run_config"]
            self.assertEqual(run_config.get("schema_version"), "0.1.0")
            self.assertEqual(run_config.get("profile_id"), "PROFILE.ASSIST")
            self.assertEqual(run_config.get("meters"), "truth")

    def test_report_schema_accepts_without_run_config(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads((repo_root / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(_minimal_report_payload())


if __name__ == "__main__":
    unittest.main()
