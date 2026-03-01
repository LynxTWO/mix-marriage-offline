import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _build_registry() -> Registry:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schema_path = SCHEMAS_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=_build_registry())


# ---------------------------------------------------------------------------
# Minimal valid fixtures
# ---------------------------------------------------------------------------

MINIMAL_RENDER_REQUEST = {
    "schema_version": "0.1.0",
    "target_layout_id": "LAYOUT.2_0",
    "scene_path": "scenes/my_project/scene.json",
}

FULL_RENDER_REQUEST = {
    "schema_version": "0.1.0",
    "target_layout_id": "LAYOUT.7_1_4",
    "scene_path": "scenes/immersive_project/scene.json",
    "routing_plan_path": "scenes/immersive_project/routing_plan.json",
    "options": {
        "output_formats": ["wav", "flac"],
        "downmix_policy_id": "POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0",
        "gates_policy_id": "POLICY.GATES.CORE_V0",
        "loudness_profile_id": "LOUD.EBU_R128_PROGRAM",
        "lfe_derivation_profile_id": "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
        "lfe_mode": "mono",
        "sample_rate_hz": 48000,
        "bit_depth": 24,
        "dry_run": False,
        "max_theoretical_quality": False,
        "plugin_chain": [
            {
                "plugin_id": "gain_v0",
                "params": {"gain_db": -3.0},
            }
        ],
    },
}

MINIMAL_RENDER_REPORT = {
    "schema_version": "0.1.0",
    "request": {
        "target_layout_id": "LAYOUT.2_0",
        "scene_path": "scenes/my_project/scene.json",
    },
    "jobs": [],
    "policies_applied": {},
    "qa_gates": {
        "status": "not_run",
        "gates": [],
    },
}

FULL_RENDER_REPORT = {
    "schema_version": "0.1.0",
    "request": {
        "target_layout_id": "LAYOUT.5_1",
        "scene_path": "scenes/surround_project/scene.json",
        "routing_plan_path": "scenes/surround_project/routing.json",
    },
    "jobs": [
        {
            "job_id": "JOB.001",
            "status": "completed",
            "output_files": [
                {
                    "file_path": "renders/stereo/mix.wav",
                    "format": "wav",
                    "channel_count": 2,
                    "sample_rate_hz": 48000,
                    "bit_depth": 24,
                    "sha256": "abcdef0123456789abcdef0123456789",
                },
            ],
            "notes": ["Rendered via standard fold-down."],
        },
        {
            "job_id": "JOB.002",
            "status": "skipped",
            "output_files": [],
            "notes": ["Gate rejected: clipping detected."],
        },
    ],
    "loudness_profile_receipt": {
        "loudness_profile_id": "LOUD.EBU_R128_PROGRAM",
        "target_loudness": -23.0,
        "target_unit": "LUFS",
        "tolerance_lu": 0.5,
        "max_true_peak_dbtp": -1.0,
        "method_id": "BS.1770-5",
        "method_implemented": True,
        "scope": "broadcast",
        "compliance_mode": "compliance",
        "best_effort": False,
        "notes": ["Broadcast full-program target profile."],
        "warnings": [],
    },
    "policies_applied": {
        "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        "gates_policy_id": "POLICY.GATES.CORE_V0",
        "lfe_derivation_profile_id": "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
        "matrix_id": "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP",
    },
    "qa_gates": {
        "status": "warn",
        "gates": [
            {
                "gate_id": "GATE.PEAK_CEILING",
                "outcome": "pass",
            },
            {
                "gate_id": "GATE.LFE_LEAK",
                "outcome": "warn",
                "reason_id": "REASON.LFE_ENERGY_ABOVE_THRESHOLD",
                "details": {"threshold_db": -20, "measured_db": -18.5},
            },
        ],
    },
}

MINIMAL_RENDER_EXECUTE = {
    "schema_version": "0.1.0",
    "run_id": "RUN.0123456789abcdef",
    "request_sha256": "0" * 64,
    "plan_sha256": "1" * 64,
    "jobs": [
        {
            "job_id": "JOB.001",
            "inputs": [
                {
                    "path": "stems/mix.wav",
                    "sha256": "2" * 64,
                }
            ],
            "outputs": [
                {
                    "path": "renders/render_outputs/job_001/mix.wav",
                    "sha256": "3" * 64,
                }
            ],
            "ffmpeg_version": "ffmpeg version N-12345-gdeadbeef",
            "ffmpeg_commands": [
                {
                    "args": ["ffmpeg", "-version"],
                    "determinism_flags": [],
                }
            ],
        }
    ],
}

MINIMAL_RENDER_QA = {
    "schema_version": "0.1.0",
    "run_id": "RUN.0123456789abcdef",
    "request_sha256": "0" * 64,
    "plan_sha256": "1" * 64,
    "report_sha256": "2" * 64,
    "plugin_chain_used": False,
    "thresholds": {
        "polarity_error_correlation_lte": -0.6,
        "correlation_warn_lte": -0.2,
        "true_peak_warn_dbtp_gt": -2.0,
        "true_peak_error_dbtp_gt": -1.0,
        "lra_warn_lu_lte": 1.5,
        "lra_warn_lu_gte": 18.0,
        "lra_error_lu_gte": 24.0,
        "plugin_delta_lufs_warn_abs": 2.0,
        "plugin_delta_lufs_error_abs": 4.0,
        "plugin_delta_crest_warn_abs": 3.0,
        "plugin_delta_crest_error_abs": 6.0,
    },
    "jobs": [
        {
            "job_id": "JOB.001",
            "input": {
                "path": "stems/mix.wav",
                "sha256": "3" * 64,
                "format": "wav",
                "channel_count": 2,
                "sample_rate_hz": 48000,
                "metrics": {
                    "peak_dbfs": -1.0,
                    "rms_dbfs": -10.0,
                    "integrated_lufs": -12.0,
                    "short_term_lufs_p10": -14.0,
                    "short_term_lufs_p50": -12.0,
                    "short_term_lufs_p90": -10.0,
                    "loudness_range_lu": 4.0,
                    "crest_factor_db": 9.0,
                    "true_peak_dbtp": -0.5,
                    "clip_sample_count": 0,
                    "intersample_over_count": 0,
                    "dc_offset": 0.0,
                    "correlation_lr": 0.5,
                    "mid_rms_dbfs": -11.0,
                    "side_rms_dbfs": -20.0,
                    "side_mid_ratio_db": -9.0,
                    "mono_rms_dbfs": -11.0,
                },
                "spectral": {
                    "centers_hz": [16.0, 20.0, 25.0],
                    "levels_db": [-80.0, -78.0, -76.0],
                    "tilt_db_per_oct": 1.0,
                    "section_tilt_db_per_oct": {
                        "sub_bass_low_end": 1.0,
                        "low_midrange": 0.5,
                        "midrange_high_mid": -0.2,
                        "highs_treble": -0.6
                    },
                    "adjacent_band_slopes_db_per_oct": [
                        {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                        {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386}
                    ],
                    "section_subband_slopes_db_per_oct": {
                        "sub_bass_low_end": [
                            {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                            {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386}
                        ],
                        "low_midrange": [],
                        "midrange_high_mid": [],
                        "highs_treble": []
                    }
                },
                "polarity_risk": False,
            },
            "outputs": [
                {
                    "path": "renders/job_001/mix.wav",
                    "sha256": "4" * 64,
                    "format": "wav",
                    "channel_count": 2,
                    "sample_rate_hz": 48000,
                    "metrics": {
                        "peak_dbfs": -1.2,
                        "rms_dbfs": -11.0,
                        "integrated_lufs": -13.0,
                        "short_term_lufs_p10": -14.5,
                        "short_term_lufs_p50": -13.0,
                        "short_term_lufs_p90": -11.0,
                        "loudness_range_lu": 3.5,
                        "crest_factor_db": 8.8,
                        "true_peak_dbtp": -0.6,
                        "clip_sample_count": 0,
                        "intersample_over_count": 0,
                        "dc_offset": 0.0,
                        "correlation_lr": 0.4,
                        "mid_rms_dbfs": -12.0,
                        "side_rms_dbfs": -22.0,
                        "side_mid_ratio_db": -10.0,
                        "mono_rms_dbfs": -12.0,
                    },
                    "spectral": {
                        "centers_hz": [16.0, 20.0, 25.0],
                        "levels_db": [-81.0, -79.0, -77.0],
                        "tilt_db_per_oct": 0.8,
                        "section_tilt_db_per_oct": {
                            "sub_bass_low_end": 0.8,
                            "low_midrange": 0.3,
                            "midrange_high_mid": -0.3,
                            "highs_treble": -0.7
                        },
                        "adjacent_band_slopes_db_per_oct": [
                            {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                            {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386}
                        ],
                        "section_subband_slopes_db_per_oct": {
                            "sub_bass_low_end": [
                                {"low_hz": 16.0, "high_hz": 20.0, "slope_db_per_oct": 6.4386},
                                {"low_hz": 20.0, "high_hz": 25.0, "slope_db_per_oct": 6.4386}
                            ],
                            "low_midrange": [],
                            "midrange_high_mid": [],
                            "highs_treble": []
                        }
                    },
                    "polarity_risk": False,
                }
            ],
            "comparisons": [],
        }
    ],
    "issues": [],
}


class TestRenderRequestSchema(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator("render_request.schema.json")

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema_path = SCHEMAS_DIR / "render_request.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_minimal_request_validates(self) -> None:
        errors = list(self.validator.iter_errors(MINIMAL_RENDER_REQUEST))
        self.assertEqual(errors, [])

    def test_full_request_validates(self) -> None:
        errors = list(self.validator.iter_errors(FULL_RENDER_REQUEST))
        self.assertEqual(errors, [])

    def test_missing_required_fields_rejected(self) -> None:
        for field in ("schema_version", "target_layout_id", "scene_path"):
            with self.subTest(missing=field):
                payload = dict(MINIMAL_RENDER_REQUEST)
                del payload[field]
                errors = list(self.validator.iter_errors(payload))
                self.assertGreater(len(errors), 0)

    def test_invalid_layout_id_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["target_layout_id"] = "bad_layout"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_backslash_in_scene_path_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["scene_path"] = "scenes\\bad\\path.json"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_additional_properties_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["unexpected_key"] = "surprise"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_output_format_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {"output_formats": ["mp3"]}
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_plugin_chain_shape_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {
            "plugin_chain": [
                {
                    "plugin_id": "gain_v0",
                    "params": "not_an_object",
                }
            ]
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_mix_inputs_shape_validates(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {
            "mix_inputs": [
                {
                    "path": "stems/vocal.wav",
                    "gain_db": -3.0,
                    "pan": -0.25,
                    "mute": False,
                    "role": "STEM.VOCAL",
                },
                {
                    "path": "stems/music.wav",
                },
            ]
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_mix_inputs_additional_properties_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {
            "mix_inputs": [
                {
                    "path": "stems/vocal.wav",
                    "junk": True,
                },
            ]
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_max_theoretical_quality_type_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {"max_theoretical_quality": "yes"}
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_loudness_profile_id_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {"loudness_profile_id": "bad_profile"}
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_lfe_derivation_profile_id_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {"lfe_derivation_profile_id": "bad_profile"}
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_lfe_mode_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["options"] = {"lfe_mode": "quad"}
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_wrong_schema_version_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REQUEST)
        payload["schema_version"] = "99.0.0"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)


class TestRenderReportSchema(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator("render_report.schema.json")

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema_path = SCHEMAS_DIR / "render_report.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_minimal_report_validates(self) -> None:
        errors = list(self.validator.iter_errors(MINIMAL_RENDER_REPORT))
        self.assertEqual(errors, [])

    def test_full_report_validates(self) -> None:
        errors = list(self.validator.iter_errors(FULL_RENDER_REPORT))
        self.assertEqual(errors, [])

    def test_missing_required_fields_rejected(self) -> None:
        for field in ("schema_version", "request", "jobs", "policies_applied", "qa_gates"):
            with self.subTest(missing=field):
                payload = dict(MINIMAL_RENDER_REPORT)
                del payload[field]
                errors = list(self.validator.iter_errors(payload))
                self.assertGreater(len(errors), 0)

    def test_invalid_job_status_rejected(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_REPORT))
        payload["jobs"] = [
            {"job_id": "JOB.001", "status": "unknown", "output_files": []},
        ]
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_qa_gate_outcome_rejected(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_REPORT))
        payload["qa_gates"] = {
            "status": "pass",
            "gates": [
                {"gate_id": "GATE.TEST", "outcome": "maybe"},
            ],
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_additional_properties_rejected(self) -> None:
        payload = dict(MINIMAL_RENDER_REPORT)
        payload["unexpected_key"] = "surprise"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_invalid_gate_id_pattern_rejected(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_REPORT))
        payload["qa_gates"] = {
            "status": "pass",
            "gates": [
                {"gate_id": "bad_gate", "outcome": "pass"},
            ],
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_loudness_profile_receipt_validates_when_present(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_REPORT))
        payload["loudness_profile_receipt"] = {
            "loudness_profile_id": "LOUD.SPOTIFY_PLAYBACK_NORMALIZATION",
            "target_loudness": -14.0,
            "target_unit": "LUFS",
            "tolerance_lu": None,
            "max_true_peak_dbtp": -1.0,
            "method_id": "BS.1770-5",
            "method_implemented": True,
            "scope": "streaming",
            "compliance_mode": "informational",
            "best_effort": False,
            "notes": ["Playback normalization guidance."],
            "warnings": [
                "This loudness profile is informational playback normalization guidance, not a delivery spec.",
            ],
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertEqual(errors, [])


class TestRenderExecuteSchema(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator("render_execute.schema.json")

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema_path = SCHEMAS_DIR / "render_execute.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_minimal_execute_validates(self) -> None:
        errors = list(self.validator.iter_errors(MINIMAL_RENDER_EXECUTE))
        self.assertEqual(errors, [])

    def test_missing_required_fields_rejected(self) -> None:
        for field in ("schema_version", "run_id", "request_sha256", "plan_sha256", "jobs"):
            with self.subTest(missing=field):
                payload = dict(MINIMAL_RENDER_EXECUTE)
                del payload[field]
                errors = list(self.validator.iter_errors(payload))
                self.assertGreater(len(errors), 0)

    def test_invalid_run_id_rejected(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_EXECUTE))
        payload["run_id"] = "RUN.not_hex"
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)

    def test_pointer_meters_validate_when_present(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_EXECUTE))
        payload["jobs"][0]["inputs"][0]["meters"] = {
            "peak_dbfs": -1.2,
            "rms_dbfs": -9.4,
            "integrated_lufs": -10.0,
        }
        payload["jobs"][0]["outputs"][0]["meters"] = {
            "peak_dbfs": None,
            "rms_dbfs": None,
            "integrated_lufs": None,
        }
        errors = list(self.validator.iter_errors(payload))
        self.assertEqual(errors, [])


class TestRenderQASchema(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator("render_qa.schema.json")

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema_path = SCHEMAS_DIR / "render_qa.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_minimal_render_qa_validates(self) -> None:
        errors = list(self.validator.iter_errors(MINIMAL_RENDER_QA))
        self.assertEqual(errors, [])

    def test_missing_required_fields_rejected(self) -> None:
        for field in (
            "schema_version",
            "run_id",
            "request_sha256",
            "plan_sha256",
            "report_sha256",
            "plugin_chain_used",
            "thresholds",
            "jobs",
            "issues",
        ):
            with self.subTest(missing=field):
                payload = dict(MINIMAL_RENDER_QA)
                del payload[field]
                errors = list(self.validator.iter_errors(payload))
                self.assertGreater(len(errors), 0)

    def test_invalid_issue_severity_rejected(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_RENDER_QA))
        payload["issues"] = [
            {
                "issue_id": "ISSUE.RENDER.QA.TEST",
                "severity": "fatal",
                "message": "invalid severity",
                "job_id": "JOB.001",
                "output_path": "renders/job_001/mix.wav",
                "metric": "correlation_lr",
                "value": -1.0,
                "threshold": -0.6,
            }
        ]
        errors = list(self.validator.iter_errors(payload))
        self.assertGreater(len(errors), 0)


class TestRenderSchemasRegistered(unittest.TestCase):
    def test_render_request_in_schema_anchors(self) -> None:
        from importlib import import_module
        import sys

        src_dir = str(REPO_ROOT / "tools")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        contracts_path = REPO_ROOT / "tools" / "validate_contracts.py"
        text = contracts_path.read_text(encoding="utf-8")
        self.assertIn("schemas/render_request.schema.json", text)
        self.assertIn("schemas/render_report.schema.json", text)
        self.assertIn("schemas/render_execute.schema.json", text)
        self.assertIn("schemas/render_qa.schema.json", text)


class TestLayoutsAndDownmixOntologyPresent(unittest.TestCase):
    def test_layouts_yaml_has_required_channel_sets(self) -> None:
        import yaml

        layouts_path = REPO_ROOT / "ontology" / "layouts.yaml"
        data = yaml.safe_load(layouts_path.read_text(encoding="utf-8"))
        layouts = data.get("layouts", {})

        required = ["LAYOUT.2_0", "LAYOUT.5_1", "LAYOUT.7_1", "LAYOUT.7_1_4"]
        for layout_id in required:
            with self.subTest(layout_id=layout_id):
                self.assertIn(layout_id, layouts)
                entry = layouts[layout_id]
                self.assertIn("channel_count", entry)
                self.assertIn("channel_order", entry)
                self.assertIsInstance(entry["channel_order"], list)
                self.assertEqual(len(entry["channel_order"]), entry["channel_count"])

    def test_downmix_yaml_has_policies(self) -> None:
        import yaml

        downmix_path = REPO_ROOT / "ontology" / "policies" / "downmix.yaml"
        data = yaml.safe_load(downmix_path.read_text(encoding="utf-8"))
        downmix = data.get("downmix", {})

        policies = downmix.get("policies", {})
        self.assertGreater(len(policies), 0)
        self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", policies)
        self.assertIn("POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0", policies)

    def test_layouts_ids_are_unique(self) -> None:
        import yaml

        layouts_path = REPO_ROOT / "ontology" / "layouts.yaml"
        data = yaml.safe_load(layouts_path.read_text(encoding="utf-8"))
        layouts = data.get("layouts", {})

        layout_ids = [k for k in layouts if k != "_meta"]
        self.assertEqual(len(layout_ids), len(set(layout_ids)))


if __name__ == "__main__":
    unittest.main()
