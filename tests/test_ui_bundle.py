import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.core.project_file import new_project, update_project_last_run, write_project
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
        "vibe_signals": {
            "density_level": "low",
            "masking_level": "medium",
            "translation_risk": "high",
            "notes": [
                "Translation risk is elevated. Fix clipping/lossy files and check mono."
            ],
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


def _sample_render_plan() -> dict:
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.UI.BUNDLE.TEST.1234abcd",
        "scene_path": "C:/tmp/scene.json",
        "targets": [
            "TARGET.STEREO.2_0",
            "TARGET.ATMOS.7_1_2",
            "TARGET.STEREO.2_0",
        ],
        "policies": {
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        },
        "jobs": [
            {
                "job_id": "JOB.002",
                "target_id": "TARGET.ATMOS.7_1_2",
                "target_layout_id": "LAYOUT.7_1_2",
                "output_formats": ["wav", "flac"],
                "contexts": ["render"],
                "notes": [],
            },
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "output_formats": ["flac", "aiff", "wav"],
                "contexts": ["render"],
                "notes": [],
            },
        ],
    }


def _sample_scene(*, include_unknown_lock: bool = False) -> dict:
    object_locks = ["LOCK.NO_STEREO_WIDENING"]
    if include_unknown_lock:
        object_locks.append("LOCK.UNKNOWN.TEST")

    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.UI.BUNDLE.TEST",
        "source": {
            "stems_dir": "C:/tmp/stems",
            "created_from": "analyze",
        },
        "intent": {
            "confidence": 0.75,
            "locks": ["LOCK.PRESERVE_DYNAMICS"],
        },
        "objects": [
            {
                "object_id": "OBJ.BASS",
                "stem_id": "bass",
                "label": "Bass",
                "channel_count": 1,
                "intent": {
                    "confidence": 0.9,
                    "locks": object_locks,
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.VOX",
                "stem_id": "vox",
                "label": "Vox",
                "channel_count": 1,
                "intent": {
                    "confidence": 0.9,
                    "locks": [],
                },
                "notes": [],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _sample_report_for_scene_overlay_tests(
    *,
    bass_action_id: str = "ACTION.UTILITY.GAIN",
    vox_action_id: str = "ACTION.UTILITY.GAIN",
) -> dict:
    report = _sample_report()
    report["recommendations"] = [
        {
            "recommendation_id": "REC.SCENE.OVERLAY.Z",
            "action_id": bass_action_id,
            "risk": "low",
            "requires_approval": False,
            "target": {"scope": "stem", "stem_id": "bass"},
            "params": [],
            "eligible_auto_apply": True,
            "eligible_render": True,
            "extreme": False,
        },
        {
            "recommendation_id": "REC.SCENE.OVERLAY.A",
            "action_id": vox_action_id,
            "risk": "low",
            "requires_approval": False,
            "target": {"scope": "stem", "stem_id": "vox"},
            "params": [],
            "eligible_auto_apply": True,
            "eligible_render": True,
            "extreme": False,
        },
    ]
    return report


def _sample_stems_index_payload() -> dict:
    return {
        "version": "0.1.0",
        "root_dir": "demo_stems",
        "stem_sets": [
            {
                "set_id": "STEMSET.bbbbbbbbbb",
                "rel_dir": "zeta",
                "file_count": 2,
                "score_hint": 0,
                "why": "folder hints: none",
            },
            {
                "set_id": "STEMSET.aaaaaaaaaa",
                "rel_dir": "alpha",
                "file_count": 5,
                "score_hint": 2,
                "why": "folder hints: stems",
            },
        ],
        "files": [],
    }


def _sample_stems_map_payload() -> dict:
    assignments: list[dict] = []
    counts_by_role: dict[str, int] = {}
    counts_by_bus_group: dict[str, int] = {}
    unknown_files = 0

    for idx in range(14):
        rel_idx = 13 - idx
        role_id = "ROLE.OTHER.UNKNOWN" if idx % 5 == 0 else "ROLE.DRUM.KICK"
        bus_group = "BG.OTHER" if role_id == "ROLE.OTHER.UNKNOWN" else "BG.RHYTHM"
        if role_id == "ROLE.OTHER.UNKNOWN":
            unknown_files += 1
        counts_by_role[role_id] = counts_by_role.get(role_id, 0) + 1
        counts_by_bus_group[bus_group] = counts_by_bus_group.get(bus_group, 0) + 1
        assignments.append(
            {
                "file_id": f"STEMFILE.{idx:010x}",
                "rel_path": f"stems/{rel_idx:02d}_track.wav",
                "role_id": role_id,
                "confidence": round(0.5 + (idx * 0.01), 3),
                "bus_group": bus_group,
                "reasons": ["seeded_for_ui_bundle_test"],
                "link_group_id": None,
            }
        )

    return {
        "version": "0.1.0",
        "stems_index_ref": "demo/stems_index.json",
        "roles_ref": "ontology/roles.yaml",
        "assignments": assignments,
        "summary": {
            "counts_by_role": {key: counts_by_role[key] for key in sorted(counts_by_role.keys())},
            "counts_by_bus_group": {
                key: counts_by_bus_group[key] for key in sorted(counts_by_bus_group.keys())
            },
            "unknown_files": unknown_files,
        },
    }


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
        self.assertEqual(
            dashboard["vibe_signals"],
            {
                "density_level": "low",
                "masking_level": "medium",
                "translation_risk": "high",
                "notes": [
                    "Translation risk is elevated. Fix clipping/lossy files and check mono."
                ],
            },
        )
        ui_copy_payload = bundle.get("ui_copy")
        self.assertIsInstance(ui_copy_payload, dict)
        if isinstance(ui_copy_payload, dict):
            self.assertEqual(ui_copy_payload.get("locale"), "en-US")
            entries = ui_copy_payload.get("entries")
            self.assertIsInstance(entries, dict)
            if isinstance(entries, dict):
                self.assertIn("COPY.PANEL.SIGNALS.TITLE", entries)
                self.assertIn("COPY.PANEL.DELIVERABLES.TITLE", entries)
                self.assertIn("COPY.BADGE.EXTREME", entries)
                self.assertIn("COPY.BADGE.BLOCKED", entries)
                self.assertIn("COPY.NAV.DASHBOARD", entries)
                self.assertIn("COPY.NAV.PRESETS", entries)
                self.assertIn("COPY.NAV.RUN", entries)
                self.assertIn("COPY.NAV.RESULTS", entries)
                self.assertIn("COPY.NAV.COMPARE", entries)
        preset_recommendations = dashboard.get("preset_recommendations")
        self.assertIsInstance(preset_recommendations, list)
        if isinstance(preset_recommendations, list):
            self.assertEqual(
                [item.get("preset_id") for item in preset_recommendations],
                [
                    "PRESET.SAFE_CLEANUP",
                    "PRESET.VIBE.TRANSLATION_SAFE",
                    "PRESET.VIBE.BRIGHT_AIRY",
                ],
            )
        help_payload = bundle.get("help")
        self.assertIsInstance(help_payload, dict)
        if isinstance(help_payload, dict):
            self.assertIn("HELP.MODE.FULL_SEND", help_payload)
            recommended_help_ids = [
                item.get("help_id")
                for item in dashboard.get("preset_recommendations", [])
                if isinstance(item, dict) and isinstance(item.get("help_id"), str)
            ]
            self.assertTrue(recommended_help_ids)
            for help_id in recommended_help_ids:
                self.assertIn(help_id, help_payload)
            self.assertEqual(
                help_payload["HELP.MODE.FULL_SEND"]["title"],
                "Full Send mode",
            )
        render_targets_payload = bundle.get("render_targets")
        self.assertIsInstance(render_targets_payload, dict)
        if isinstance(render_targets_payload, dict):
            targets = render_targets_payload.get("targets")
            self.assertIsInstance(targets, list)
            if isinstance(targets, list):
                target_ids = [
                    item.get("target_id")
                    for item in targets
                    if isinstance(item, dict) and isinstance(item.get("target_id"), str)
                ]
                self.assertEqual(
                    target_ids,
                    [
                        "TARGET.STEREO.2_0",
                        "TARGET.SURROUND.5_1",
                        "TARGET.SURROUND.7_1",
                    ],
                )
            self.assertEqual(
                render_targets_payload.get("highlighted_target_ids"),
                ["TARGET.STEREO.2_0"],
            )

        second_bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        self.assertEqual(bundle["dashboard"], second_bundle["dashboard"])
        self.assertEqual(bundle.get("help"), second_bundle.get("help"))

    def test_build_ui_bundle_embeds_translation_results_sorted_by_profile_id(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["translation_results"] = [
            {
                "profile_id": "TRANS.MONO.COLLAPSE",
                "score": 65,
                "issues": [
                    {
                        "issue_id": "ISSUE.TRANSLATION.PROFILE_SCORE_LOW",
                        "severity": 55,
                        "confidence": 1.0,
                        "target": {"scope": "session"},
                        "evidence": [
                            {
                                "evidence_id": "EVID.ISSUE.SCORE",
                                "value": 0.65,
                                "unit_id": "UNIT.RATIO",
                            }
                        ],
                    }
                ],
            },
            {
                "profile_id": "TRANS.DEVICE.PHONE",
                "score": 75,
            },
        ]
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        validator.validate(bundle)

        translation_results = bundle.get("translation_results")
        self.assertIsInstance(translation_results, list)
        if not isinstance(translation_results, list):
            return
        self.assertEqual(
            [item.get("profile_id") for item in translation_results if isinstance(item, dict)],
            ["TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
        )
        self.assertEqual(translation_results[1].get("issues"), report["translation_results"][0]["issues"])

    def test_build_ui_bundle_embeds_translation_summary_sorted_by_profile_id(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["translation_summary"] = [
            {
                "profile_id": "TRANS.MONO.COLLAPSE",
                "status": "fail",
                "score": 42,
                "label": "Mono collapse",
                "short_reason": (
                    "ISSUE.TRANSLATION.PROFILE_SCORE_LOW: score=42 fail<50 warn<70."
                ),
            },
            {
                "profile_id": "TRANS.DEVICE.PHONE",
                "status": "pass",
                "score": 75,
                "label": "Phone",
                "short_reason": "Score meets threshold.",
            },
        ]
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        validator.validate(bundle)

        translation_summary = bundle.get("translation_summary")
        self.assertIsInstance(translation_summary, list)
        if not isinstance(translation_summary, list):
            return
        self.assertEqual(
            [item.get("profile_id") for item in translation_summary if isinstance(item, dict)],
            ["TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
        )
        self.assertEqual(translation_summary[0].get("status"), "pass")
        self.assertEqual(translation_summary[1].get("status"), "fail")

    def test_build_ui_bundle_embeds_translation_reference(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["translation_reference"] = {
            "source_target_id": "TARGET.SURROUND.7_1",
            "method": "downmix_fallback",
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "source_channels": 8,
            "audio_path": "translation_reference/translation_reference.stereo.wav",
        }
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        validator.validate(bundle)
        self.assertEqual(bundle.get("translation_reference"), report["translation_reference"])

    def test_build_ui_bundle_with_apply_payload_and_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["routing_plan"] = {
            "schema_version": "0.1.0",
            "source_layout_id": "LAYOUT.7_1",
            "target_layout_id": "LAYOUT.5_1",
            "routes": [],
        }
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
        render_targets_payload = bundle.get("render_targets")
        self.assertIsInstance(render_targets_payload, dict)
        if isinstance(render_targets_payload, dict):
            targets = render_targets_payload.get("targets")
            self.assertIsInstance(targets, list)
            if isinstance(targets, list):
                target_ids = [
                    item.get("target_id")
                    for item in targets
                    if isinstance(item, dict) and isinstance(item.get("target_id"), str)
                ]
                self.assertEqual(
                    target_ids,
                    [
                        "TARGET.STEREO.2_0",
                        "TARGET.SURROUND.5_1",
                        "TARGET.SURROUND.7_1",
                    ],
                )
            self.assertEqual(
                render_targets_payload.get("highlighted_target_ids"),
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )

    def test_build_ui_bundle_render_targets_include_scene_recommendations(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"
        scene_payload = _sample_scene()
        scene_payload["beds"] = [
            {
                "bed_id": "BED.BETA.FIELD",
                "label": "Beta Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.90,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            },
            {
                "bed_id": "BED.ALPHA.FIELD",
                "label": "Alpha Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.80,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(scene_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        render_targets_payload = bundle.get("render_targets")
        self.assertIsInstance(render_targets_payload, dict)
        if not isinstance(render_targets_payload, dict):
            return

        recommendations = render_targets_payload.get("recommendations")
        self.assertIsInstance(recommendations, list)
        if not isinstance(recommendations, list):
            return
        self.assertEqual(
            [
                row.get("target_id")
                for row in recommendations
                if isinstance(row, dict)
            ],
            ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1", "TARGET.SURROUND.7_1"],
        )
        self.assertEqual(
            [
                row.get("rank")
                for row in recommendations
                if isinstance(row, dict)
            ],
            [1, 2, 3],
        )
        self.assertEqual(
            recommendations,
            sorted(
                recommendations,
                key=lambda row: (
                    int(row.get("rank", 0)) if isinstance(row, dict) else 0,
                    str(row.get("target_id", "")) if isinstance(row, dict) else "",
                ),
            ),
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
        self.assertIn("HELP.MODE.FULL_SEND", help_payload)
        self.assertIn("HELP.PRESET.VIBE.WARM_INTIMATE", help_payload)
        recommended_help_ids = [
            item.get("help_id")
            for item in bundle.get("dashboard", {}).get("preset_recommendations", [])
            if isinstance(item, dict) and isinstance(item.get("help_id"), str)
        ]
        self.assertTrue(recommended_help_ids)
        for help_id in recommended_help_ids:
            self.assertIn(help_id, help_payload)
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

    def test_build_ui_bundle_scene_meta_and_recommendation_overlays(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report_for_scene_overlay_tests()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(_sample_scene(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        scene_meta = bundle.get("scene_meta")
        self.assertIsInstance(scene_meta, dict)
        if not isinstance(scene_meta, dict):
            return

        locks_used = scene_meta.get("locks_used")
        self.assertIsInstance(locks_used, list)
        if not isinstance(locks_used, list):
            return
        lock_ids = [
            item.get("lock_id")
            for item in locks_used
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(lock_ids, ["LOCK.NO_STEREO_WIDENING", "LOCK.PRESERVE_DYNAMICS"])
        lock_labels = {
            item.get("lock_id"): item.get("label")
            for item in locks_used
            if isinstance(item, dict)
        }
        self.assertEqual(lock_labels.get("LOCK.NO_STEREO_WIDENING"), "No stereo widening")
        self.assertEqual(lock_labels.get("LOCK.PRESERVE_DYNAMICS"), "Preserve dynamics")

        help_payload = bundle.get("help")
        self.assertIsInstance(help_payload, dict)
        if not isinstance(help_payload, dict):
            return
        self.assertIn("HELP.LOCK.NO_STEREO_WIDENING", help_payload)
        self.assertIn("HELP.LOCK.PRESERVE_DYNAMICS", help_payload)
        for help_id in (
            "HELP.LOCK.NO_STEREO_WIDENING",
            "HELP.LOCK.PRESERVE_DYNAMICS",
        ):
            entry = help_payload.get(help_id)
            self.assertIsInstance(entry, dict)
            if not isinstance(entry, dict):
                continue
            self.assertIn("title", entry)
            self.assertIn("short", entry)
            self.assertIn("long", entry)

        intent_param_defs = scene_meta.get("intent_param_defs")
        self.assertIsInstance(intent_param_defs, list)
        if not isinstance(intent_param_defs, list):
            return
        param_ids = [
            item.get("param_id")
            for item in intent_param_defs
            if isinstance(item, dict) and isinstance(item.get("param_id"), str)
        ]
        self.assertEqual(param_ids, sorted(param_ids))
        self.assertIn("INTENT.WIDTH", param_ids)
        self.assertIn("INTENT.DEPTH", param_ids)
        self.assertIn("INTENT.CONFIDENCE", param_ids)

        scene_templates = scene_meta.get("scene_templates")
        self.assertIsInstance(scene_templates, list)
        if not isinstance(scene_templates, list):
            return
        template_ids = [
            item.get("template_id")
            for item in scene_templates
            if isinstance(item, dict) and isinstance(item.get("template_id"), str)
        ]
        self.assertEqual(template_ids, sorted(template_ids))
        self.assertEqual(
            template_ids,
            [
                "TEMPLATE.SCENE.LIVE.YOU_ARE_THERE",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD",
            ],
        )

        recommendation_overlays = bundle.get("recommendation_overlays")
        self.assertIsInstance(recommendation_overlays, dict)
        if not isinstance(recommendation_overlays, dict):
            return
        self.assertEqual(
            list(recommendation_overlays.keys()),
            sorted(recommendation_overlays.keys()),
        )

        targeted_overlay = recommendation_overlays.get("REC.SCENE.OVERLAY.Z")
        self.assertIsInstance(targeted_overlay, dict)
        if not isinstance(targeted_overlay, dict):
            return
        targeted_locks = targeted_overlay.get("locks_in_effect")
        self.assertIsInstance(targeted_locks, list)
        if not isinstance(targeted_locks, list):
            return
        targeted_lock_ids = [
            item.get("lock_id")
            for item in targeted_locks
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(
            targeted_lock_ids,
            ["LOCK.NO_STEREO_WIDENING", "LOCK.PRESERVE_DYNAMICS"],
        )
        self.assertEqual(targeted_lock_ids, sorted(targeted_lock_ids))
        self.assertEqual(
            targeted_overlay.get("scope"),
            {"scene": True, "object_id": "OBJ.BASS"},
        )

        other_overlay = recommendation_overlays.get("REC.SCENE.OVERLAY.A")
        self.assertIsInstance(other_overlay, dict)
        if not isinstance(other_overlay, dict):
            return
        other_locks = other_overlay.get("locks_in_effect")
        self.assertIsInstance(other_locks, list)
        if not isinstance(other_locks, list):
            return
        other_lock_ids = [
            item.get("lock_id")
            for item in other_locks
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(other_lock_ids, ["LOCK.PRESERVE_DYNAMICS"])
        self.assertEqual(
            other_overlay.get("scope"),
            {"scene": True, "object_id": "OBJ.VOX"},
        )

    def test_build_ui_bundle_scene_overlay_lock_notes_include_hint_short(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report_for_scene_overlay_tests(
            bass_action_id="ACTION.DSP.COMPRESS.BUS",
        )
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(_sample_scene(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        recommendation_overlays = bundle.get("recommendation_overlays")
        self.assertIsInstance(recommendation_overlays, dict)
        if not isinstance(recommendation_overlays, dict):
            return
        targeted_overlay = recommendation_overlays.get("REC.SCENE.OVERLAY.Z")
        self.assertIsInstance(targeted_overlay, dict)
        if not isinstance(targeted_overlay, dict):
            return
        lock_notes = targeted_overlay.get("lock_notes")
        self.assertIsInstance(lock_notes, list)
        if not isinstance(lock_notes, list):
            return
        self.assertEqual(
            lock_notes,
            [
                {
                    "lock_id": "LOCK.PRESERVE_DYNAMICS",
                    "severity": "hard",
                    "note": (
                        "Preserve dynamics: avoid heavy squashing. "
                        "If you tame peaks, keep the punch."
                    ),
                    "tags": ["dynamics"],
                }
            ],
        )

    def test_build_ui_bundle_scene_overlay_lock_notes_action_filter(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["recommendations"] = [
            {
                "recommendation_id": "REC.SCENE.ACTION.NON_MATCH",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "bass"},
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": True,
                "extreme": False,
            },
            {
                "recommendation_id": "REC.SCENE.ACTION.MATCH",
                "action_id": "ACTION.STEREO.WIDEN.CLASSIC",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "bass"},
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": True,
                "extreme": False,
            },
        ]
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(_sample_scene(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        recommendation_overlays = bundle.get("recommendation_overlays")
        self.assertIsInstance(recommendation_overlays, dict)
        if not isinstance(recommendation_overlays, dict):
            return

        non_match_overlay = recommendation_overlays.get("REC.SCENE.ACTION.NON_MATCH")
        self.assertIsInstance(non_match_overlay, dict)
        if not isinstance(non_match_overlay, dict):
            return
        self.assertNotIn("lock_notes", non_match_overlay)

        match_overlay = recommendation_overlays.get("REC.SCENE.ACTION.MATCH")
        self.assertIsInstance(match_overlay, dict)
        if not isinstance(match_overlay, dict):
            return
        lock_notes = match_overlay.get("lock_notes")
        self.assertIsInstance(lock_notes, list)
        if not isinstance(lock_notes, list):
            return
        self.assertEqual(
            lock_notes,
            [
                {
                    "lock_id": "LOCK.NO_STEREO_WIDENING",
                    "severity": "hard",
                    "note": "No widening: keep the stereo image honest. Don't inflate the sides.",
                    "tags": ["image", "stereo"],
                }
            ],
        )

    def test_build_ui_bundle_scene_overlay_lock_conflicts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        report["recommendations"] = [
            {
                "recommendation_id": "REC.SCENE.CONFLICT.MATCH",
                "action_id": "ACTION.STEREO.WIDEN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "bass"},
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": True,
                "extreme": False,
            },
            {
                "recommendation_id": "REC.SCENE.CONFLICT.NO_MATCH",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "bass"},
                "params": [],
                "eligible_auto_apply": True,
                "eligible_render": True,
                "extreme": False,
            },
        ]
        help_registry_path = repo_root / "ontology" / "help.yaml"
        scene_payload = _sample_scene()
        scene_payload["intent"]["locks"] = [
            "LOCK.PRESERVE_CENTER_IMAGE",
            "LOCK.NO_STEREO_WIDENING",
        ]
        scene_payload["objects"][0]["intent"]["locks"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(scene_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        recommendation_overlays = bundle.get("recommendation_overlays")
        self.assertIsInstance(recommendation_overlays, dict)
        if not isinstance(recommendation_overlays, dict):
            return

        match_overlay = recommendation_overlays.get("REC.SCENE.CONFLICT.MATCH")
        self.assertIsInstance(match_overlay, dict)
        if not isinstance(match_overlay, dict):
            return
        lock_conflicts = match_overlay.get("lock_conflicts")
        self.assertIsInstance(lock_conflicts, list)
        if not isinstance(lock_conflicts, list):
            return
        self.assertEqual(
            lock_conflicts,
            [
                {
                    "lock_id": "LOCK.NO_STEREO_WIDENING",
                    "severity": "hard",
                    "action_id": "ACTION.STEREO.WIDEN",
                    "note": (
                        "Action ACTION.STEREO.WIDEN may violate "
                        "LOCK.NO_STEREO_WIDENING."
                    ),
                },
                {
                    "lock_id": "LOCK.PRESERVE_CENTER_IMAGE",
                    "severity": "hard",
                    "action_id": "ACTION.STEREO.WIDEN",
                    "note": (
                        "Action ACTION.STEREO.WIDEN may violate "
                        "LOCK.PRESERVE_CENTER_IMAGE."
                    ),
                },
            ],
        )

        non_match_overlay = recommendation_overlays.get("REC.SCENE.CONFLICT.NO_MATCH")
        self.assertIsInstance(non_match_overlay, dict)
        if not isinstance(non_match_overlay, dict):
            return
        self.assertNotIn("lock_conflicts", non_match_overlay)

    def test_build_ui_bundle_scene_overlay_lock_notes_are_sorted_and_stable(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report_for_scene_overlay_tests(
            bass_action_id="ACTION.DSP.COMPRESS.BUS",
        )
        help_registry_path = repo_root / "ontology" / "help.yaml"

        scene_payload = _sample_scene()
        scene_payload["intent"]["locks"] = ["LOCK.PRESERVE_DYNAMICS", "LOCK.NO_EXTRA_BASS"]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(scene_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            first_bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )
            second_bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(first_bundle)
        validator.validate(second_bundle)

        first_overlays = first_bundle.get("recommendation_overlays")
        second_overlays = second_bundle.get("recommendation_overlays")
        self.assertIsInstance(first_overlays, dict)
        self.assertIsInstance(second_overlays, dict)
        if not isinstance(first_overlays, dict) or not isinstance(second_overlays, dict):
            return

        first_overlay = first_overlays.get("REC.SCENE.OVERLAY.Z")
        second_overlay = second_overlays.get("REC.SCENE.OVERLAY.Z")
        self.assertIsInstance(first_overlay, dict)
        self.assertIsInstance(second_overlay, dict)
        if not isinstance(first_overlay, dict) or not isinstance(second_overlay, dict):
            return

        first_lock_notes = first_overlay.get("lock_notes")
        second_lock_notes = second_overlay.get("lock_notes")
        self.assertIsInstance(first_lock_notes, list)
        self.assertIsInstance(second_lock_notes, list)
        if not isinstance(first_lock_notes, list) or not isinstance(second_lock_notes, list):
            return

        self.assertEqual(first_lock_notes, second_lock_notes)
        lock_ids = [
            item.get("lock_id")
            for item in first_lock_notes
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(lock_ids, ["LOCK.NO_EXTRA_BASS", "LOCK.PRESERVE_DYNAMICS"])
        self.assertEqual(lock_ids, sorted(lock_ids))

    def test_build_ui_bundle_scene_meta_uses_placeholder_for_unknown_lock(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report_for_scene_overlay_tests()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_path.write_text(
                json.dumps(
                    _sample_scene(include_unknown_lock=True),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)

        scene_meta = bundle.get("scene_meta")
        self.assertIsInstance(scene_meta, dict)
        if not isinstance(scene_meta, dict):
            return
        locks_used = scene_meta.get("locks_used")
        self.assertIsInstance(locks_used, list)
        if not isinstance(locks_used, list):
            return
        lock_rows = {
            item.get("lock_id"): item
            for item in locks_used
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        }
        unknown_lock = lock_rows.get("LOCK.UNKNOWN.TEST")
        self.assertIsInstance(unknown_lock, dict)
        if not isinstance(unknown_lock, dict):
            return
        self.assertEqual(unknown_lock.get("label"), "LOCK.UNKNOWN.TEST")
        self.assertEqual(unknown_lock.get("severity"), "taste")

        recommendation_overlays = bundle.get("recommendation_overlays")
        self.assertIsInstance(recommendation_overlays, dict)
        if not isinstance(recommendation_overlays, dict):
            return
        targeted_overlay = recommendation_overlays.get("REC.SCENE.OVERLAY.Z")
        self.assertIsInstance(targeted_overlay, dict)
        if not isinstance(targeted_overlay, dict):
            return
        locks_in_effect = targeted_overlay.get("locks_in_effect")
        self.assertIsInstance(locks_in_effect, list)
        if not isinstance(locks_in_effect, list):
            return
        lock_summaries = {
            item.get("lock_id"): item
            for item in locks_in_effect
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        }
        unknown_overlay_lock = lock_summaries.get("LOCK.UNKNOWN.TEST")
        self.assertIsInstance(unknown_overlay_lock, dict)
        if not isinstance(unknown_overlay_lock, dict):
            return
        self.assertEqual(unknown_overlay_lock.get("label"), "LOCK.UNKNOWN.TEST")
        self.assertEqual(unknown_overlay_lock.get("severity"), "taste")

    def test_build_ui_bundle_embeds_render_plan_summary(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            render_plan_path = temp_path / "render_plan.json"
            render_plan_path.write_text(
                json.dumps(_sample_render_plan(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_plan_path=render_plan_path,
            )

        validator.validate(bundle)
        self.assertEqual(
            bundle.get("render_plan_summary"),
            {
                "target_ids": [
                    "TARGET.ATMOS.7_1_2",
                    "TARGET.STEREO.2_0",
                ],
                "output_formats": ["aiff", "flac", "wav"],
                "policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            },
        )

    def test_build_ui_bundle_without_render_plan_omits_render_plan_summary(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_render_plan_path = temp_path / "render_plan.json"
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_plan_path=missing_render_plan_path,
            )

        validator.validate(bundle)
        self.assertNotIn("render_plan_summary", bundle)

    def test_build_ui_bundle_embeds_project_gui_design_and_pointers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            out_dir = temp_path / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            deliverables_index_path = out_dir / "deliverables_index.json"
            listen_pack_path = out_dir / "listen_pack.json"
            scene_path = out_dir / "scene.json"
            project_path = temp_path / "project.json"

            project_payload = new_project(stems_dir, notes=None)
            project_payload = update_project_last_run(
                project_payload,
                {
                    "mode": "single",
                    "out_dir": out_dir.resolve().as_posix(),
                    "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                    "listen_pack_path": listen_pack_path.resolve().as_posix(),
                },
            )
            write_project(project_path, project_payload)

            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                project_path=project_path,
                deliverables_index_path=deliverables_index_path,
                listen_pack_path=listen_pack_path,
                scene_path=scene_path,
            )

        validator.validate(bundle)
        self.assertEqual(
            bundle.get("project"),
            {
                "project_id": project_payload["project_id"],
                "stems_dir": project_payload["stems_dir"],
                "last_run": project_payload["last_run"],
                "updated_at_utc": project_payload["updated_at_utc"],
            },
        )
        self.assertEqual(
            bundle.get("pointers"),
            {
                "project_path": project_path.resolve().as_posix(),
                "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                "listen_pack_path": listen_pack_path.resolve().as_posix(),
                "scene_path": scene_path.resolve().as_posix(),
            },
        )

        gui_design = bundle.get("gui_design")
        self.assertIsInstance(gui_design, dict)
        if not isinstance(gui_design, dict):
            return
        self.assertIn("palette", gui_design)
        self.assertIn("typography", gui_design)
        self.assertIn("layout_rules", gui_design)
        palette = gui_design.get("palette")
        self.assertIsInstance(palette, dict)
        if isinstance(palette, dict):
            self.assertEqual(palette.get("background"), "#0F1117")

    def test_build_ui_bundle_embeds_optional_gui_state_pointer_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            gui_state_path = temp_path / "gui_state.json"
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                gui_state_path=gui_state_path,
            )

        validator.validate(bundle)
        self.assertEqual(
            bundle.get("pointers"),
            {"gui_state_path": gui_state_path.resolve().as_posix()},
        )
        self.assertNotIn("gui_state", bundle)

    def test_build_ui_bundle_embeds_stems_summary_when_paths_are_present(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_index_path = temp_path / "stems_index.json"
            stems_map_path = temp_path / "stems_map.json"
            stems_index_path.write_text(
                json.dumps(_sample_stems_index_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            stems_map_path.write_text(
                json.dumps(_sample_stems_map_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                stems_index_path=stems_index_path,
                stems_map_path=stems_map_path,
            )

        validator.validate(bundle)
        self.assertEqual(
            bundle.get("pointers"),
            {
                "stems_index_path": stems_index_path.resolve().as_posix(),
                "stems_map_path": stems_map_path.resolve().as_posix(),
            },
        )

        stems_summary = bundle.get("stems_summary")
        self.assertIsInstance(stems_summary, dict)
        if not isinstance(stems_summary, dict):
            return

        stem_sets = stems_summary.get("stem_sets")
        self.assertIsInstance(stem_sets, list)
        if isinstance(stem_sets, list) and stem_sets:
            self.assertEqual(stem_sets[0].get("rel_dir"), "alpha")
            self.assertEqual(stem_sets[1].get("rel_dir"), "zeta")

        assignments_preview = stems_summary.get("assignments_preview")
        self.assertIsInstance(assignments_preview, list)
        if isinstance(assignments_preview, list):
            self.assertEqual(len(assignments_preview), 12)
            rel_paths = [
                item.get("rel_path")
                for item in assignments_preview
                if isinstance(item, dict) and isinstance(item.get("rel_path"), str)
            ]
            self.assertEqual(rel_paths, sorted(rel_paths))

        self.assertEqual(
            stems_summary.get("counts_by_bus_group"),
            {"BG.OTHER": 3, "BG.RHYTHM": 11},
        )
        self.assertEqual(stems_summary.get("unknown_files"), 3)
        self.assertEqual(
            stems_summary.get("stems_map_path"),
            stems_map_path.resolve().as_posix(),
        )

    def test_build_ui_bundle_missing_stems_artifacts_omits_stems_summary(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_stems_index_path = temp_path / "missing_stems_index.json"
            missing_stems_map_path = temp_path / "missing_stems_map.json"
            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                stems_index_path=missing_stems_index_path,
                stems_map_path=missing_stems_map_path,
            )

        validator.validate(bundle)
        self.assertEqual(
            bundle.get("pointers"),
            {
                "stems_index_path": missing_stems_index_path.resolve().as_posix(),
                "stems_map_path": missing_stems_map_path.resolve().as_posix(),
            },
        )
        self.assertNotIn("stems_summary", bundle)

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
                    "--ui-locale",
                    "en-US",
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
            self.assertEqual(bundle.get("ui_copy", {}).get("locale"), "en-US")
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

    # -- project_init section --------------------------------------------------

    def test_build_ui_bundle_includes_project_init_when_provided(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        project_init = {
            "stems_index_path": "/tmp/proj/stems/stems_index.json",
            "stems_map_path": "/tmp/proj/stems/stems_map.json",
            "stems_overrides_path": "/tmp/proj/stems/stems_overrides.yaml",
            "scene_draft_path": "/tmp/proj/drafts/scene.draft.json",
            "routing_draft_path": "/tmp/proj/drafts/routing_plan.draft.json",
            "preview_only": True,
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            project_init=project_init,
        )
        validator.validate(bundle)
        self.assertEqual(bundle["project_init"], project_init)
        self.assertTrue(bundle["project_init"]["preview_only"])
        for key in (
            "stems_index_path",
            "stems_map_path",
            "stems_overrides_path",
            "scene_draft_path",
            "routing_draft_path",
        ):
            self.assertNotIn("\\", bundle["project_init"][key])

    def test_build_ui_bundle_omits_project_init_when_not_provided(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
        )
        validator.validate(bundle)
        self.assertNotIn("project_init", bundle)

    def test_build_ui_bundle_project_init_minimal(self) -> None:
        """Only preview_only is required; path fields are optional."""
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            project_init={"preview_only": True},
        )
        validator.validate(bundle)
        self.assertEqual(bundle["project_init"], {"preview_only": True})

    # -- stems_auditions section -----------------------------------------------

    def test_build_ui_bundle_includes_stems_auditions_when_provided(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        stems_auditions = {
            "manifest_path": "/tmp/proj/stems_auditions/manifest.json",
            "out_dir": "/tmp/proj/stems_auditions",
            "rendered_groups_count": 4,
            "missing_files_count": 1,
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            stems_auditions=stems_auditions,
        )
        validator.validate(bundle)
        self.assertEqual(bundle["stems_auditions"], stems_auditions)
        self.assertEqual(bundle["stems_auditions"]["rendered_groups_count"], 4)
        self.assertEqual(bundle["stems_auditions"]["missing_files_count"], 1)

    def test_build_ui_bundle_omits_stems_auditions_when_not_provided(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
        )
        validator.validate(bundle)
        self.assertNotIn("stems_auditions", bundle)

    # -- generated_at_utc determinism ------------------------------------------

    def test_generated_at_utc_derived_from_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        self.assertEqual(bundle["generated_at_utc"], report["generated_at"])

    def test_generated_at_utc_fallback_when_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        del report["generated_at"]
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        self.assertEqual(bundle["generated_at_utc"], "2000-01-01T00:00:00Z")

    def test_two_runs_produce_identical_json_bytes(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle_a = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        bundle_b = build_ui_bundle(report, None, help_registry_path=help_registry_path)
        bytes_a = json.dumps(bundle_a, indent=2, sort_keys=True).encode("utf-8")
        bytes_b = json.dumps(bundle_b, indent=2, sort_keys=True).encode("utf-8")
        self.assertEqual(bytes_a, bytes_b)

    # -- determinism + size sanity for new sections ----------------------------

    def test_bundle_new_sections_deterministic_key_ordering(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        project_init = {
            "stems_index_path": "/tmp/proj/stems/stems_index.json",
            "stems_map_path": "/tmp/proj/stems/stems_map.json",
            "scene_draft_path": "/tmp/proj/drafts/scene.draft.json",
            "routing_draft_path": "/tmp/proj/drafts/routing_plan.draft.json",
            "preview_only": True,
        }
        stems_auditions = {
            "manifest_path": "/tmp/proj/stems_auditions/manifest.json",
            "out_dir": "/tmp/proj/stems_auditions",
            "rendered_groups_count": 3,
            "missing_files_count": 0,
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            project_init=project_init,
            stems_auditions=stems_auditions,
        )
        text_a = json.dumps(bundle, indent=2, sort_keys=True)
        text_b = json.dumps(bundle, indent=2, sort_keys=True)
        self.assertEqual(text_a, text_b)

        # Verify key ordering within sections is stable after round-trip
        rt = json.loads(text_a)
        self.assertEqual(
            sorted(rt["project_init"].keys()),
            list(sorted(rt["project_init"].keys())),
        )
        self.assertEqual(
            sorted(rt["stems_auditions"].keys()),
            list(sorted(rt["stems_auditions"].keys())),
        )

    def test_bundle_size_sanity_with_new_sections(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        project_init = {
            "stems_index_path": "/tmp/proj/stems/stems_index.json",
            "stems_map_path": "/tmp/proj/stems/stems_map.json",
            "stems_overrides_path": "/tmp/proj/stems/stems_overrides.yaml",
            "scene_draft_path": "/tmp/proj/drafts/scene.draft.json",
            "routing_draft_path": "/tmp/proj/drafts/routing_plan.draft.json",
            "preview_only": True,
        }
        stems_auditions = {
            "manifest_path": "/tmp/proj/stems_auditions/manifest.json",
            "out_dir": "/tmp/proj/stems_auditions",
            "rendered_groups_count": 10,
            "missing_files_count": 2,
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            project_init=project_init,
            stems_auditions=stems_auditions,
        )
        bundle_json = json.dumps(bundle, indent=2, sort_keys=True)
        self.assertLess(
            len(bundle_json),
            50_000,
            "Bundle with new pointer sections should remain small (< 50 KB)",
        )

    def test_stems_auditions_paths_are_posix(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        stems_auditions = {
            "manifest_path": "/tmp/proj/stems_auditions/manifest.json",
            "out_dir": "/tmp/proj/stems_auditions",
            "rendered_groups_count": 2,
            "missing_files_count": 0,
        }

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
            stems_auditions=stems_auditions,
        )
        validator.validate(bundle)
        self.assertNotIn("\\", bundle["stems_auditions"]["manifest_path"])
        self.assertNotIn("\\", bundle["stems_auditions"]["out_dir"])


    # -- render artifacts block -------------------------------------------------

    def test_build_ui_bundle_includes_render_block_when_paths_provided(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            render_request_path = temp_path / "render_request.json"
            render_plan_path = temp_path / "render_plan.json"
            render_report_path = temp_path / "render_report.json"

            render_request_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )
            render_plan_path.write_text(
                json.dumps(_sample_render_plan(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            render_report_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )

            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_request_path=render_request_path,
                render_plan_artifact_path=render_plan_path,
                render_report_path=render_report_path,
            )

        validator.validate(bundle)

        render_block = bundle.get("render")
        self.assertIsInstance(render_block, dict)
        if not isinstance(render_block, dict):
            return

        for key in ("render_request", "render_plan", "render_report"):
            entry = render_block.get(key)
            self.assertIsInstance(entry, dict, msg=f"Missing or invalid: render.{key}")
            if not isinstance(entry, dict):
                continue
            self.assertTrue(entry["exists"], msg=f"render.{key}.exists should be True")
            self.assertIsInstance(entry["sha256"], str)
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertNotIn("\\", entry["path"])

    def test_build_ui_bundle_render_block_missing_files(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_request = temp_path / "missing_render_request.json"
            missing_report = temp_path / "missing_render_report.json"

            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_request_path=missing_request,
                render_report_path=missing_report,
            )

        validator.validate(bundle)

        render_block = bundle.get("render")
        self.assertIsInstance(render_block, dict)
        if not isinstance(render_block, dict):
            return

        for key in ("render_request", "render_report"):
            entry = render_block.get(key)
            self.assertIsInstance(entry, dict, msg=f"Missing render.{key}")
            if not isinstance(entry, dict):
                continue
            self.assertFalse(entry["exists"])
            self.assertIsNone(entry["sha256"])
            self.assertNotIn("\\", entry["path"])

        self.assertNotIn("render_plan", render_block)

    def test_build_ui_bundle_omits_render_block_when_no_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        bundle = build_ui_bundle(
            report,
            None,
            help_registry_path=help_registry_path,
        )
        validator.validate(bundle)
        self.assertNotIn("render", bundle)

    def test_build_ui_bundle_render_block_determinism(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            render_request_path = temp_path / "render_request.json"
            render_request_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )
            missing_report = temp_path / "no_such_render_report.json"

            bundle_a = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_request_path=render_request_path,
                render_report_path=missing_report,
            )
            bundle_b = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_request_path=render_request_path,
                render_report_path=missing_report,
            )

        bytes_a = json.dumps(bundle_a, indent=2, sort_keys=True).encode("utf-8")
        bytes_b = json.dumps(bundle_b, indent=2, sort_keys=True).encode("utf-8")
        self.assertEqual(bytes_a, bytes_b)

    def test_build_ui_bundle_render_block_path_hygiene(self) -> None:
        """Backslash paths are normalized to forward slashes."""
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()
        help_registry_path = repo_root / "ontology" / "help.yaml"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            render_request_path = temp_path / "render_request.json"
            render_request_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )

            bundle = build_ui_bundle(
                report,
                None,
                help_registry_path=help_registry_path,
                render_request_path=render_request_path,
            )

        validator.validate(bundle)
        render_block = bundle.get("render")
        self.assertIsInstance(render_block, dict)
        if not isinstance(render_block, dict):
            return
        entry = render_block.get("render_request")
        self.assertIsInstance(entry, dict)
        if isinstance(entry, dict):
            self.assertNotIn("\\", entry["path"])

    def test_cli_bundle_with_render_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")
        report = _sample_report()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            render_request_path = temp_path / "render_request.json"
            render_plan_path = temp_path / "render_plan.json"
            render_report_path = temp_path / "render_report.json"
            out_bundle_path = temp_path / "ui_bundle.json"

            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            render_request_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )
            render_plan_path.write_text(
                json.dumps(_sample_render_plan(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            render_report_path.write_text(
                json.dumps({"schema_version": "0.1.0"}, indent=2) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "bundle",
                    "--report",
                    str(report_path),
                    "--render-request",
                    str(render_request_path),
                    "--render-plan",
                    str(render_plan_path),
                    "--render-report",
                    str(render_report_path),
                    "--out",
                    str(out_bundle_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_bundle_path.exists())

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)

            render_block = bundle.get("render")
            self.assertIsInstance(render_block, dict)
            if not isinstance(render_block, dict):
                return

            for key in ("render_request", "render_plan", "render_report"):
                entry = render_block.get(key)
                self.assertIsInstance(entry, dict, msg=f"Missing: render.{key}")
                if isinstance(entry, dict):
                    self.assertTrue(entry["exists"])
                    self.assertIsInstance(entry["sha256"], str)
                    self.assertNotIn("\\", entry["path"])

            # render_plan_summary should also be present (from the same --render-plan)
            self.assertIn("render_plan_summary", bundle)


if __name__ == "__main__":
    unittest.main()
