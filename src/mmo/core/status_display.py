"""Canonical status-to-label mapping for CLI/backend presentation."""

from __future__ import annotations

from mmo.core.statuses import (
    DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY,
    DELIVERABLE_RESULT_BUCKET_FULL_FAILURE,
    DELIVERABLE_RESULT_BUCKET_PARTIAL_SUCCESS,
    DELIVERABLE_RESULT_BUCKET_SUCCESS_NO_MASTER,
    DELIVERABLE_RESULT_BUCKET_VALID_MASTER,
    LIFECYCLE_STATUS_BLOCKED,
    LIFECYCLE_STATUS_COMPLETED,
    LIFECYCLE_STATUS_DRY_RUN_ONLY,
    MEASUREMENT_STATE_FAILED,
    MEASUREMENT_STATE_INVALID_DUE_TO_SILENCE,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_APPLICABLE,
    QA_GATE_STATUS_FAIL,
    QA_GATE_STATUS_NOT_RUN,
    QA_GATE_STATUS_PASS,
    QA_GATE_STATUS_WARN,
    SCENE_BINDING_STATUS_CLEAN,
    SCENE_BINDING_STATUS_FAILED,
    SCENE_BINDING_STATUS_NOT_APPLICABLE,
    SCENE_BINDING_STATUS_PARTIAL,
    SCENE_BINDING_STATUS_REWRITTEN,
)

_DELIVERABLE_RESULT_BUCKET_LABELS = {
    DELIVERABLE_RESULT_BUCKET_VALID_MASTER: "Valid master render",
    DELIVERABLE_RESULT_BUCKET_SUCCESS_NO_MASTER: "Successful artifacts (no master)",
    DELIVERABLE_RESULT_BUCKET_PARTIAL_SUCCESS: "Partial success",
    DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY: "Invalid render with diagnostics",
    DELIVERABLE_RESULT_BUCKET_FULL_FAILURE: "Full failure",
}

_LIFECYCLE_STATUS_LABELS = {
    LIFECYCLE_STATUS_DRY_RUN_ONLY: "Dry-run only",
    LIFECYCLE_STATUS_COMPLETED: "Completed",
    LIFECYCLE_STATUS_BLOCKED: "Blocked",
}

_QA_GATE_STATUS_LABELS = {
    QA_GATE_STATUS_PASS: "Pass",
    QA_GATE_STATUS_WARN: "Warn",
    QA_GATE_STATUS_FAIL: "Fail",
    QA_GATE_STATUS_NOT_RUN: "Not run",
}

_MEASUREMENT_STATE_LABELS = {
    MEASUREMENT_STATE_MEASURED: "Measured",
    MEASUREMENT_STATE_NOT_APPLICABLE: "Not applicable",
    MEASUREMENT_STATE_FAILED: "Measurement failed",
    MEASUREMENT_STATE_INVALID_DUE_TO_SILENCE: "Invalid due to silence",
}

_SCENE_BINDING_STATUS_LABELS = {
    SCENE_BINDING_STATUS_NOT_APPLICABLE: "Not applicable",
    SCENE_BINDING_STATUS_CLEAN: "Already canonical",
    SCENE_BINDING_STATUS_REWRITTEN: "Rewritten to canonical stems",
    SCENE_BINDING_STATUS_PARTIAL: "Partially bound",
    SCENE_BINDING_STATUS_FAILED: "Binding failed",
}


def label_for_deliverable_result_bucket(value: str) -> str:
    return _DELIVERABLE_RESULT_BUCKET_LABELS.get(value, "Unknown render result")


def label_for_lifecycle_status(value: str) -> str:
    return _LIFECYCLE_STATUS_LABELS.get(value, "Unknown lifecycle state")


def label_for_qa_gate_status(value: str) -> str:
    return _QA_GATE_STATUS_LABELS.get(value, "Unknown QA state")


def label_for_measurement_state(value: str) -> str:
    return _MEASUREMENT_STATE_LABELS.get(value, "Unknown measurement state")


def label_for_scene_binding_status(value: str) -> str:
    return _SCENE_BINDING_STATUS_LABELS.get(value, "Unknown scene binding state")


__all__ = [
    "label_for_deliverable_result_bucket",
    "label_for_lifecycle_status",
    "label_for_measurement_state",
    "label_for_qa_gate_status",
    "label_for_scene_binding_status",
]
