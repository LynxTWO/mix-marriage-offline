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
        "sample_rate_hz": 48000,
        "bit_depth": 24,
        "dry_run": False,
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
    "policies_applied": {
        "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        "gates_policy_id": "POLICY.GATES.CORE_V0",
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
