import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.lfe_audit import classify_lfe_program_state
from mmo.core.registries.downmix_registry import load_downmix_registry
from mmo.core.registries.gates_registry import load_gates_registry
from mmo.core.render_planner import build_render_plan
from mmo.core.render_reporting import build_render_report_from_plan
from mmo.resources import load_ontology_yaml


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    repo_root = Path(__file__).resolve().parents[1]
    schemas_dir = repo_root / "schemas"
    registry = Registry()
    for candidate in sorted(schemas_dir.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((schemas_dir / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _layouts_map() -> dict[str, dict]:
    payload = load_ontology_yaml("layouts.yaml")
    layouts = payload.get("layouts")
    if not isinstance(layouts, dict):
        raise AssertionError("layouts.yaml must include a 'layouts' mapping")
    return layouts


def _base_scene(*, source_layout_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.LFE.DERIVATION.INTEGRATION",
        "source": {
            "stems_dir": "stems",
            "created_from": "analyze",
            "layout_id": source_layout_id,
        },
        "objects": [],
        "beds": [],
        "metadata": {},
    }


class TestLfeDerivationPlannerIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.layouts = _layouts_map()
        self.downmix_registry = load_downmix_registry()
        self.gates_policy_ids = load_gates_registry().get_policy_ids()
        self.plan_validator = _schema_validator("render_plan.schema.json")
        self.report_validator = _schema_validator("render_report.schema.json")

    def test_missing_source_lfe_derives_for_dual_lfe_target_default_mono(self) -> None:
        request = {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.5_2",
            "scene_path": "scene.json",
        }
        scene = _base_scene(source_layout_id="LAYOUT.2_0")

        plan = build_render_plan(
            request,
            scene,
            layouts=self.layouts,
            downmix_registry=self.downmix_registry,
            gates_policy_ids=self.gates_policy_ids,
        )
        self.plan_validator.validate(plan)

        jobs = plan.get("jobs")
        self.assertIsInstance(jobs, list)
        if not isinstance(jobs, list) or not jobs:
            return
        receipt = jobs[0].get("lfe_receipt")
        self.assertIsInstance(receipt, dict)
        if not isinstance(receipt, dict):
            return
        self.assertEqual(receipt["status"], "derived")
        self.assertTrue(receipt["derivation_applied"])
        self.assertFalse(receipt["derivation_ran"])
        self.assertEqual(receipt["lfe_mode"], "mono")
        self.assertEqual(receipt["target_lfe_channel_count"], 2)
        self.assertEqual(receipt["chosen_sum_mode"], "L+R")
        self.assertEqual(
            plan["policies"]["lfe_derivation_profile_id"],
            "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
        )

    def test_source_lfe_passthrough_receipt(self) -> None:
        request = {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.5_1",
            "scene_path": "scene.json",
        }
        scene = _base_scene(source_layout_id="LAYOUT.5_1")
        scene["metadata"]["source_has_lfe_program_content"] = True

        plan = build_render_plan(
            request,
            scene,
            layouts=self.layouts,
            downmix_registry=self.downmix_registry,
            gates_policy_ids=self.gates_policy_ids,
        )
        self.plan_validator.validate(plan)

        receipt = plan["jobs"][0]["lfe_receipt"]
        self.assertEqual(receipt["status"], "passthrough")
        self.assertFalse(receipt["derivation_applied"])
        self.assertFalse(receipt["derivation_ran"])
        self.assertEqual(receipt["chosen_sum_mode"], "passthrough")

    def test_stereo_lfe_request_flows_to_plan_and_report_receipts(self) -> None:
        request = {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.5_2",
            "scene_path": "scene.json",
            "options": {
                "lfe_derivation_profile_id": "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
                "lfe_mode": "stereo",
            },
        }
        scene = _base_scene(source_layout_id="LAYOUT.2_0")

        plan = build_render_plan(
            request,
            scene,
            layouts=self.layouts,
            downmix_registry=self.downmix_registry,
            gates_policy_ids=self.gates_policy_ids,
        )
        self.plan_validator.validate(plan)
        self.assertEqual(plan["resolved"]["lfe_mode"], "stereo")
        self.assertEqual(
            plan["resolved"]["lfe_derivation_profile_id"],
            "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
        )
        self.assertEqual(plan["jobs"][0]["lfe_receipt"]["lfe_mode"], "stereo")

        report = build_render_report_from_plan(plan)
        self.report_validator.validate(report)
        self.assertEqual(
            report["policies_applied"]["lfe_derivation_profile_id"],
            "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
        )
        self.assertEqual(report["jobs"][0]["lfe_receipt"]["lfe_mode"], "stereo")

    def test_lfe_audit_classification_distinguishes_derived_passthrough_and_empty(self) -> None:
        passthrough = classify_lfe_program_state(
            target_has_lfe=True,
            source_has_lfe_program_content=False,
            lfe_receipt={"status": "passthrough"},
        )
        derived = classify_lfe_program_state(
            target_has_lfe=True,
            source_has_lfe_program_content=False,
            lfe_receipt={"status": "derived"},
        )
        empty = classify_lfe_program_state(
            target_has_lfe=True,
            source_has_lfe_program_content=False,
            lfe_receipt={"status": "empty"},
        )
        not_applicable = classify_lfe_program_state(
            target_has_lfe=False,
            source_has_lfe_program_content=False,
            lfe_receipt=None,
        )

        self.assertEqual(passthrough, "passthrough")
        self.assertEqual(derived, "derived")
        self.assertEqual(empty, "empty")
        self.assertEqual(not_applicable, "not_applicable")


if __name__ == "__main__":
    unittest.main()
