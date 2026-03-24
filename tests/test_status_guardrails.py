from __future__ import annotations

import json
import unittest
from pathlib import Path

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
