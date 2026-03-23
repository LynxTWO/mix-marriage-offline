"""Shared QA measurement-state vocabulary."""

from __future__ import annotations

MEASUREMENT_STATE_MEASURED = "measured"
MEASUREMENT_STATE_NOT_APPLICABLE = "not_applicable"
MEASUREMENT_STATE_FAILED = "measurement_failed"
MEASUREMENT_STATE_INVALID_DUE_TO_SILENCE = "invalid_due_to_silence"

__all__ = [
    "MEASUREMENT_STATE_FAILED",
    "MEASUREMENT_STATE_INVALID_DUE_TO_SILENCE",
    "MEASUREMENT_STATE_MEASURED",
    "MEASUREMENT_STATE_NOT_APPLICABLE",
    "classify_measurement_state",
]


def classify_measurement_state(
    *,
    measured: bool,
    applicable: bool = True,
    silent: bool = False,
) -> str:
    """Return the canonical measurement-state label for a QA metric."""
    if not applicable:
        return MEASUREMENT_STATE_NOT_APPLICABLE
    if silent:
        return MEASUREMENT_STATE_INVALID_DUE_TO_SILENCE
    if measured:
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_FAILED
