import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.core.ui_bundle import build_ui_bundle


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _sample_report() -> dict:
    issue_evidence = [{"evidence_id": "EVID.TEST.SIGNAL", "value": "x"}]
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.UI.BUNDLE.TEST",
        "project_id": "PROJECT.UI.BUNDLE.TEST",
        "profile_id": "PROFILE.FULL_SEND",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [
            {
                "issue_id": "ISSUE.ZETA",
                "severity": 80,
                "confidence": 1.0,
                "message": "zeta issue",
                "evidence": issue_evidence,
            },
            {
                "issue_id": "ISSUE.ALPHA",
                "severity": 90,
                "confidence": 1.0,
                "message": "alpha issue",
                "evidence": issue_evidence,
            },
            {
                "issue_id": "ISSUE.GAMMA",
                "severity": 90,
                "confidence": 1.0,
                "message": "gamma issue",
                "evidence": issue_evidence,
            },
            {
                "issue_id": "ISSUE.DELTA",
                "severity": 90,
                "confidence": 1.0,
                "message": "delta issue",
                "evidence": issue_evidence,
            },
            {
                "issue_id": "ISSUE.OMEGA",
                "severity": 70,
                "confidence": 1.0,
                "message": "omega issue",
                "evidence": issue_evidence,
            },
            {
                "issue_id": "ISSUE.BETA",
                "severity": 30,
                "confidence": 1.0,
                "message": "beta issue",
                "evidence": issue_evidence,
            },
        ],
        "recommendations": [
            {
                "recommendation_id": "REC.UI.BUNDLE.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": True,
                "extreme": False,
            },
            {
                "recommendation_id": "REC.UI.BUNDLE.002",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "params": [],
                "eligible_auto_apply": False,
                "eligible_render": True,
                "extreme": True,
            },
            {
                "recommendation_id": "REC.UI.BUNDLE.003",
                "action_id": "ACTION.DOWNMIX.RENDER",
                "risk": "low",
                "requires_approval": False,
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": False,
                "extreme": True,
            },
            {
                "recommendation_id": "REC.UI.BUNDLE.004",
                "action_id": "ACTION.DIAGNOSTIC.CHECK_PHASE_CORRELATION",
                "risk": "low",
                "requires_approval": False,
                "params": [],
            },
        ],
        "downmix_qa": {
            "src_path": "a.wav",
            "ref_path": "b.wav",
            "issues": [
                {
                    "issue_id": "ISSUE.DOWNMIX.QA.CORRELATION_MISMATCH",
                    "severity": 60,
                    "confidence": 1.0,
                    "message": "corr issue",
                    "target": {"scope": "session"},
                    "evidence": [
                        {
                            "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                            "value": 0.55,
                            "unit_id": "UNIT.CORRELATION",
                        }
                    ],
                }
            ],
            "measurements": [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": -1.5,
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": 2.2,
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": 0.4,
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": -1.7,
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_FOLD",
                    "value": 0.86,
                    "unit_id": "UNIT.CORRELATION",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_REF",
                    "value": 0.62,
                    "unit_id": "UNIT.CORRELATION",
                },
            ],
            "log": "{}",
        },
        "mix_complexity": {
            "density_mean": 1.75,
            "density_peak": 3,
            "density_timeline": [
                {"start_s": 0.0, "end_s": 0.1, "active_stems": 2},
                {"start_s": 0.1, "end_s": 0.2, "active_stems": 3},
            ],
            "top_masking_pairs": [
                {
                    "stem_a": "vocals",
                    "stem_b": "guitar",
                    "score": 0.82,
                    "start_s": 0.1,
                    "end_s": 0.2,
                    "window_count": 12,
                },
                {
                    "stem_a": "keys",
                    "stem_b": "guitar",
                    "score": 0.67,
                    "start_s": 0.2,
                    "end_s": 0.3,
                    "window_count": 12,
                },
            ],
            "top_masking_pairs_count": 2,
            "sample_rate_hz": 48000,
            "included_stem_ids": ["guitar", "keys", "vocals"],
            "skipped_stem_ids": [],
            "density": {
                "density_mean": 1.75,
                "density_peak": 3,
                "density_timeline": [],
                "timeline_total_windows": 12,
                "timeline_truncated": False,
                "window_size": 2048,
                "hop_size": 1024,
                "rms_threshold_dbfs": -45.0,
                "bands_hz": [],
                "stem_count": 3,
            },
            "masking_risk": {
                "top_pairs": [],
                "pair_count": 2,
                "window_size": 2048,
                "hop_size": 1024,
                "mid_band_hz": {"low_hz": 300.0, "high_hz": 3000.0},
            },
        },
    }


def _sample_render_manifest(report_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
        "renderer_manifests": [],
    }


def _sample_apply_manifest(report_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "context": "auto_apply",
        "report_id": report_id,
        "renderer_manifests": [
            {
                "renderer_id": "PLUGIN.RENDERER.SAFE",
                "outputs": [
                    {
                        "output_id": "OUT.APPLY.001",
                        "file_path": "applied/safe-001.wav",
                    }
                ],
                "skipped": [
                    {
                        "recommendation_id": "REC.UI.BUNDLE.004",
                        "action_id": "ACTION.DIAGNOSTIC.CHECK_PHASE_CORRELATION",
                        "reason": "blocked_by_gates",
                        "gate_summary": "auto_apply: reject GATE.EXAMPLE",
                    }
                ],
            },
            {
                "renderer_id": "PLUGIN.RENDERER.GAIN_TRIM",
                "outputs": [
                    {
                        "output_id": "OUT.APPLY.002",
                        "file_path": "applied/gain-001.wav",
                    },
                    {
                        "output_id": "OUT.APPLY.003",
                        "file_path": "applied/gain-002.wav",
                    },
                ],
                "skipped": [
                    {
                        "recommendation_id": "REC.UI.BUNDLE.002",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "reason": "unsupported_target",
                        "gate_summary": "auto_apply: suggest_only GATE.EXAMPLE",
                    }
                ],
            },
        ],
    }


def _sample_applied_report() -> dict:
    applied = _sample_report()
    applied["report_id"] = "REPORT.UI.BUNDLE.TEST.APPLIED"
    return applied


class TestUiBundle(unittest.TestCase):
    def test_build_ui_bundle_dashboard_and_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        validator.validate(bundle)

        dashboard = bundle["dashboard"]
        self.assertEqual(dashboard["profile_id"], "PROFILE.FULL_SEND")
        self.assertEqual(
            [item["issue_id"] for item in dashboard["top_issues"]],
            [
                "ISSUE.ALPHA",
                "ISSUE.DELTA",
                "ISSUE.GAMMA",
                "ISSUE.ZETA",
                "ISSUE.OMEGA",
            ],
        )
        self.assertEqual(dashboard["eligible_counts"], {"auto_apply": 2, "render": 2})
        self.assertEqual(dashboard["blocked_counts"], {"auto_apply": 2, "render": 2})
        self.assertEqual(dashboard["extreme_count"], 2)
        self.assertEqual(
            dashboard["downmix_qa"],
            {
                "has_issues": True,
                "max_delta_lufs": 2.2,
                "max_delta_true_peak": 1.7,
                "min_corr": 0.55,
            },
        )
        self.assertEqual(
            dashboard["mix_complexity"],
            {
                "density_mean": 1.75,
                "density_peak": 3,
                "top_masking_pairs_count": 2,
            },
        )
        help_payload = bundle.get("help")
        self.assertIsInstance(help_payload, dict)
        if isinstance(help_payload, dict):
            self.assertEqual(list(help_payload.keys()), ["HELP.MODE.FULL_SEND"])
            self.assertEqual(
                help_payload["HELP.MODE.FULL_SEND"]["title"],
                "Full Send mode",
            )

        second_bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        self.assertEqual(bundle["dashboard"], second_bundle["dashboard"])
        self.assertEqual(bundle.get("help"), second_bundle.get("help"))

    def test_build_ui_bundle_with_apply_payload_and_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        apply_manifest = _sample_apply_manifest(report["report_id"])
        applied_report = _sample_applied_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(
            report,
            None,
            apply_manifest=apply_manifest,
            applied_report=applied_report,
            help_registry_path=help_registry_path,
        )
        validator.validate(bundle)

        self.assertIn("apply_manifest", bundle)
        self.assertIn("applied_report", bundle)
        self.assertIn("help", bundle)
        self.assertEqual(
            bundle["dashboard"]["apply"],
            {
                "eligible_count": 2,
                "blocked_count": 2,
                "outputs_count": 3,
                "skipped_count": 2,
            },
        )

    def test_build_ui_bundle_help_includes_profile_and_vibe_preset(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["run_config"] = {
            "schema_version": "0.1.0",
            "preset_id": "PRESET.VIBE.WARM_INTIMATE",
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=repo_root / "ontology" / "help.yaml",
        )
        validator.validate(bundle)

        help_payload = bundle.get("help")
        self.assertIsInstance(help_payload, dict)
        if not isinstance(help_payload, dict):
            return
        self.assertEqual(
            list(help_payload.keys()),
            ["HELP.MODE.FULL_SEND", "HELP.PRESET.VIBE.WARM_INTIMATE"],
        )
        preset_help = help_payload["HELP.PRESET.VIBE.WARM_INTIMATE"]
        self.assertIn("title", preset_help)
        self.assertIn("short", preset_help)
        self.assertIn("long", preset_help)
        self.assertIn("cues", preset_help)
        self.assertIn("watch_out_for", preset_help)
        self.assertEqual(
            preset_help["title"],
            "Warm intimate",
        )

    def test_cli_bundle_writes_schema_valid_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        render_manifest = _sample_render_manifest(report["report_id"])

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            render_manifest_path = temp_path / "render_manifest.json"
            out_bundle_path = temp_path / "ui_bundle.json"

            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            render_manifest_path.write_text(
                json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "bundle",
                    "--report",
                    str(report_path),
                    "--render-manifest",
                    str(render_manifest_path),
                    "--out",
                    str(out_bundle_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_bundle_path.exists())

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)
            self.assertIn("render_manifest", bundle)
            self.assertEqual(bundle["render_manifest"]["report_id"], report["report_id"])
            self.assertEqual(
                bundle["dashboard"]["eligible_counts"],
                {"auto_apply": 2, "render": 2},
            )

    def test_cli_bundle_with_apply_payload_writes_schema_valid_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        render_manifest = _sample_render_manifest(report["report_id"])
        apply_manifest = _sample_apply_manifest(report["report_id"])
        applied_report = _sample_applied_report()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            render_manifest_path = temp_path / "render_manifest.json"
            apply_manifest_path = temp_path / "apply_manifest.json"
            applied_report_path = temp_path / "applied_report.json"
            out_bundle_path = temp_path / "ui_bundle.json"

            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            render_manifest_path.write_text(
                json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            apply_manifest_path.write_text(
                json.dumps(apply_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            applied_report_path.write_text(
                json.dumps(applied_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "bundle",
                    "--report",
                    str(report_path),
                    "--render-manifest",
                    str(render_manifest_path),
                    "--apply-manifest",
                    str(apply_manifest_path),
                    "--applied-report",
                    str(applied_report_path),
                    "--out",
                    str(out_bundle_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_bundle_path.exists())

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)
            self.assertEqual(
                bundle["dashboard"]["apply"],
                {
                    "eligible_count": 2,
                    "blocked_count": 2,
                    "outputs_count": 3,
                    "skipped_count": 2,
                },
            )
            self.assertIn("apply_manifest", bundle)
            self.assertIn("applied_report", bundle)


if __name__ == "__main__":
    unittest.main()
