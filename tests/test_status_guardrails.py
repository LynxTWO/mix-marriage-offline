from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from mmo.core import deliverables, qa_states
from mmo.core.status_display import (
    label_for_deliverable_result_bucket,
    label_for_lifecycle_status,
    label_for_measurement_state,
    label_for_qa_gate_status,
    label_for_scene_binding_status,
)
from mmo.core.statuses import (
    DELIVERABLE_RESULT_BUCKET_VALID_MASTER,
    DELIVERABLE_STATUS_SUCCESS,
    LIFECYCLE_STATUS_BLOCKED,
    MEASUREMENT_STATE_NOT_APPLICABLE,
    QA_GATE_STATUS_WARN,
    SCENE_BINDING_STATUS_REWRITTEN,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _schema_description(schema: dict[str, Any], *path: str) -> str:
    current: Any = schema
    for key in path:
        current = current[key]
    if not isinstance(current, dict):
        raise AssertionError(f"Schema path does not resolve to an object: {path!r}")
    description = current.get("description")
    if not isinstance(description, str) or not description.strip():
        raise AssertionError(f"Schema description missing at path: {path!r}")
    return description


class TestStatusGuardrails(unittest.TestCase):
    def test_shared_status_labels_are_stable(self) -> None:
        self.assertEqual(
            label_for_deliverable_result_bucket(DELIVERABLE_RESULT_BUCKET_VALID_MASTER),
            "Valid master render",
        )
        self.assertEqual(label_for_lifecycle_status(LIFECYCLE_STATUS_BLOCKED), "Blocked")
        self.assertEqual(label_for_qa_gate_status(QA_GATE_STATUS_WARN), "Warn")
        self.assertEqual(
            label_for_measurement_state(MEASUREMENT_STATE_NOT_APPLICABLE),
            "Not applicable",
        )
        self.assertEqual(
            label_for_scene_binding_status(SCENE_BINDING_STATUS_REWRITTEN),
            "Rewritten to canonical stems",
        )

    def test_existing_backend_modules_use_shared_status_constants(self) -> None:
        self.assertEqual(deliverables.DELIVERABLE_STATUS_SUCCESS, DELIVERABLE_STATUS_SUCCESS)
        self.assertEqual(
            qa_states.MEASUREMENT_STATE_NOT_APPLICABLE,
            MEASUREMENT_STATE_NOT_APPLICABLE,
        )

    def test_render_status_schemas_reference_shared_defs(self) -> None:
        render_manifest = json.loads(
            (REPO_ROOT / "schemas" / "render_manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        safe_render_receipt = json.loads(
            (REPO_ROOT / "schemas" / "safe_render_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        render_qa = json.loads(
            (REPO_ROOT / "schemas" / "render_qa.schema.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_statuses = json.loads(
            (REPO_ROOT / "src" / "mmo" / "data" / "schemas" / "statuses.schema.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_render_manifest = json.loads(
            (REPO_ROOT / "src" / "mmo" / "data" / "schemas" / "render_manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            render_manifest["$defs"]["deliverable_summary_row"]["properties"]["status"]["$ref"],
            "statuses.schema.json#/$defs/deliverable_status_or_null",
        )
        self.assertEqual(
            render_manifest["$defs"]["result_summary"]["properties"]["result_bucket"]["$ref"],
            "statuses.schema.json#/$defs/deliverable_result_bucket_or_null",
        )
        self.assertEqual(
            safe_render_receipt["properties"]["status"]["$ref"],
            "statuses.schema.json#/$defs/lifecycle_status_safe_render",
        )
        self.assertEqual(
            safe_render_receipt["properties"]["scene_binding_summary"]["$ref"],
            "#/$defs/scene_binding_summary",
        )
        self.assertEqual(
            safe_render_receipt["$defs"]["scene_binding_summary"]["properties"]["status"]["$ref"],
            "statuses.schema.json#/$defs/scene_binding_status",
        )
        self.assertEqual(
            render_qa["$defs"]["issue"]["properties"]["measurement_state"]["$ref"],
            "statuses.schema.json#/$defs/measurement_state",
        )
        self.assertEqual(
            packaged_statuses["$defs"]["qa_gate_status"]["enum"],
            ["pass", "warn", "fail", "not_run"],
        )
        self.assertEqual(
            packaged_statuses["$defs"]["scene_binding_status"]["enum"],
            ["not_applicable", "clean", "rewritten", "partial", "failed"],
        )
        self.assertEqual(
            packaged_render_manifest["$defs"]["result_summary"]["properties"]["result_bucket"]["$ref"],
            "statuses.schema.json#/$defs/deliverable_result_bucket_or_null",
        )
        self.assertEqual(
            packaged_render_manifest["properties"]["scene_binding_summary"]["$ref"],
            "#/$defs/scene_binding_summary",
        )

    def test_render_contract_schema_ownership_notes_and_dead_fields_are_guarded(self) -> None:
        render_plan = json.loads(
            (REPO_ROOT / "schemas" / "render_plan.schema.json").read_text(encoding="utf-8")
        )
        render_manifest = json.loads(
            (REPO_ROOT / "schemas" / "render_manifest.schema.json").read_text(encoding="utf-8")
        )
        safe_render_receipt = json.loads(
            (REPO_ROOT / "schemas" / "safe_render_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_render_plan = json.loads(
            (REPO_ROOT / "src" / "mmo" / "data" / "schemas" / "render_plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_render_manifest = json.loads(
            (REPO_ROOT / "src" / "mmo" / "data" / "schemas" / "render_manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        packaged_safe_render_receipt = json.loads(
            (REPO_ROOT / "src" / "mmo" / "data" / "schemas" / "safe_render_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )

        source_description_paths = [
            ("render_plan.schema.json", render_plan, ("properties", "request"), "request echo"),
            ("render_plan.schema.json", render_plan, ("properties", "resolved"), "compatibility"),
            ("render_plan.schema.json", render_plan, ("properties", "resolved_layouts"), "canonical"),
            ("render_plan.schema.json", render_plan, ("$defs", "job", "properties", "target_id"), "selected"),
            ("render_plan.schema.json", render_plan, ("$defs", "job", "properties", "resolved_target_id"), "canonical"),
            ("render_plan.schema.json", render_plan, ("$defs", "job", "properties", "target_layout_id"), "concrete"),
            ("render_manifest.schema.json", render_manifest, ("properties", "scene_binding_summary"), "scene-to-session"),
            ("render_manifest.schema.json", render_manifest, ("properties", "preflight_summary"), "gate decision"),
            ("render_manifest.schema.json", render_manifest, ("properties", "deliverables_summary"), "machine"),
            ("render_manifest.schema.json", render_manifest, ("properties", "deliverable_summary_rows"), "row-wise"),
            ("render_manifest.schema.json", render_manifest, ("properties", "result_summary"), "user-facing"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "scene_binding_summary"), "scene-to-session"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "preflight_summary"), "gate decision"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "approved_by"), "legacy"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "approved_by_user"), "structured"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "deliverables_summary"), "machine"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "deliverable_summary_rows"), "row-wise"),
            ("safe_render_receipt.schema.json", safe_render_receipt, ("properties", "result_summary"), "user-facing"),
        ]
        for _schema_name, schema, path, needle in source_description_paths:
            description = _schema_description(schema, *path)
            self.assertIn(needle, description.lower())

        parity_paths = [
            (render_plan, packaged_render_plan, ("properties", "request")),
            (render_plan, packaged_render_plan, ("properties", "resolved")),
            (render_plan, packaged_render_plan, ("properties", "resolved_layouts")),
            (render_plan, packaged_render_plan, ("$defs", "job", "properties", "target_id")),
            (render_plan, packaged_render_plan, ("$defs", "job", "properties", "resolved_target_id")),
            (render_plan, packaged_render_plan, ("$defs", "job", "properties", "target_layout_id")),
            (render_manifest, packaged_render_manifest, ("properties", "scene_binding_summary")),
            (render_manifest, packaged_render_manifest, ("properties", "preflight_summary")),
            (render_manifest, packaged_render_manifest, ("properties", "deliverables_summary")),
            (render_manifest, packaged_render_manifest, ("properties", "deliverable_summary_rows")),
            (render_manifest, packaged_render_manifest, ("properties", "result_summary")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "approved_by")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "approved_by_user")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "scene_binding_summary")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "preflight_summary")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "deliverables_summary")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "deliverable_summary_rows")),
            (safe_render_receipt, packaged_safe_render_receipt, ("properties", "result_summary")),
        ]
        for source_schema, packaged_schema, path in parity_paths:
            self.assertEqual(
                _schema_description(source_schema, *path),
                _schema_description(packaged_schema, *path),
            )

        self.assertNotIn("spectral_summary", safe_render_receipt["properties"])
        self.assertNotIn("spectral_summary", packaged_safe_render_receipt["properties"])
