from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

from mmo.core.layout_negotiation import get_layout_channel_order

_UNKNOWN_LAYOUT_ID = "LAYOUT.UNKNOWN"
_EXCLUDED_ARTIFACT_ROLES = {"stem_copy", "subbus"}

DELIVERABLE_STATUS_SUCCESS = "success"
DELIVERABLE_STATUS_FAILED = "failed"
DELIVERABLE_STATUS_PARTIAL = "partial"
DELIVERABLE_STATUS_INVALID_MASTER = "invalid_master"
_DELIVERABLE_STATUSES = (
    DELIVERABLE_STATUS_SUCCESS,
    DELIVERABLE_STATUS_FAILED,
    DELIVERABLE_STATUS_PARTIAL,
    DELIVERABLE_STATUS_INVALID_MASTER,
)

RENDER_RESULT_DOWNMIX_QA_FAILED = "RENDER_RESULT.DOWNMIX_QA_FAILED"
RENDER_RESULT_FALLBACK_APPLIED = "RENDER_RESULT.FALLBACK_APPLIED"
RENDER_RESULT_MISSING_CHANNEL_ORDER = "RENDER_RESULT.MISSING_CHANNEL_ORDER"
RENDER_RESULT_NO_DECODABLE_STEMS = "RENDER_RESULT.NO_DECODABLE_STEMS"
RENDER_RESULT_NO_OUTPUT_ARTIFACT = "RENDER_RESULT.NO_OUTPUT_ARTIFACT"
RENDER_RESULT_PLACEMENT_POLICY_UNAVAILABLE = "RENDER_RESULT.PLACEMENT_POLICY_UNAVAILABLE"
RENDER_RESULT_SAFETY_COLLAPSE_APPLIED = "RENDER_RESULT.SAFETY_COLLAPSE_APPLIED"
RENDER_RESULT_SILENT_OUTPUT = "RENDER_RESULT.SILENT_OUTPUT"
RENDER_RESULT_STEM_DECODE_FAILED = "RENDER_RESULT.STEM_DECODE_FAILED"
RENDER_RESULT_STEMS_SKIPPED = "RENDER_RESULT.STEMS_SKIPPED"

SILENT_OUTPUT_PEAK_DBFS_LTE = -120.0
SILENT_OUTPUT_LINEAR_TOLERANCE = 10.0 ** (SILENT_OUTPUT_PEAK_DBFS_LTE / 20.0)

_FAILURE_REASON_WARNING_CODES = {
    RENDER_RESULT_DOWNMIX_QA_FAILED,
    RENDER_RESULT_NO_DECODABLE_STEMS,
    RENDER_RESULT_SILENT_OUTPUT,
}
_INVALID_MASTER_WARNING_CODES = {
    RENDER_RESULT_DOWNMIX_QA_FAILED,
    RENDER_RESULT_SILENT_OUTPUT,
}
_LAYOUT_FAILURE_CODES_BY_SUFFIX = {
    "downmix_similarity_gate_failed_after_fallback": RENDER_RESULT_DOWNMIX_QA_FAILED,
    "fallback_applied": RENDER_RESULT_FALLBACK_APPLIED,
    "missing_channel_order": RENDER_RESULT_MISSING_CHANNEL_ORDER,
    "placement_policy_unavailable": RENDER_RESULT_PLACEMENT_POLICY_UNAVAILABLE,
    "rendered_silence:no_decodable_stems": RENDER_RESULT_NO_DECODABLE_STEMS,
    "safety_collapse_applied": RENDER_RESULT_SAFETY_COLLAPSE_APPLIED,
    "silent_output": RENDER_RESULT_SILENT_OUTPUT,
}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _output_sort_key(output: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _output_metadata(output: Dict[str, Any]) -> dict[str, Any]:
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {}


def _output_render_result(output: Dict[str, Any]) -> dict[str, Any]:
    metadata = _output_metadata(output)
    render_result = metadata.get("render_result")
    if isinstance(render_result, dict):
        return render_result
    return {}


def _output_artifact_role(output: Dict[str, Any]) -> str:
    render_result = _output_render_result(output)
    artifact_role = _coerce_str(render_result.get("artifact_role")).strip().lower()
    if artifact_role:
        return artifact_role

    metadata = _output_metadata(output)
    artifact_role = _coerce_str(metadata.get("artifact_role")).strip().lower()
    if artifact_role:
        return artifact_role

    if _coerce_str(output.get("target_bus_id")).strip():
        return "processed_bus"
    if _coerce_str(output.get("target_stem_id")).strip():
        return "processed_stem"
    if _coerce_str(output.get("layout_id")).strip():
        return "master"
    return ""


def _should_include_output_in_deliverables(output: Dict[str, Any]) -> bool:
    artifact_role = _output_artifact_role(output)
    return artifact_role not in _EXCLUDED_ARTIFACT_ROLES


def _group_target_layout_id(output: Dict[str, Any]) -> str:
    layout_id = _coerce_str(output.get("layout_id")).strip()
    if layout_id:
        return layout_id

    render_result = _output_render_result(output)
    layout_id = _coerce_str(render_result.get("target_layout_id")).strip()
    if layout_id:
        return layout_id

    metadata = _output_metadata(output)
    layout_id = _coerce_str(metadata.get("target_layout_id")).strip()
    if layout_id:
        return layout_id

    layout_id = _coerce_str(metadata.get("layout_id")).strip()
    if layout_id:
        return layout_id

    return _UNKNOWN_LAYOUT_ID


def _group_channel_count(output: Dict[str, Any]) -> int | None:
    channel_count = _coerce_int(output.get("channel_count"))
    if channel_count is None or channel_count < 1:
        return None
    return channel_count


def _output_target_stem_id(output: Dict[str, Any]) -> str:
    return _coerce_str(output.get("target_stem_id")).strip()


def _output_target_bus_id(output: Dict[str, Any]) -> str:
    return _coerce_str(output.get("target_bus_id")).strip()


def _group_identity(output: Dict[str, Any]) -> tuple[str, str, str, int | None]:
    artifact_role = _output_artifact_role(output) or "artifact"
    layout_id = _group_target_layout_id(output)
    channel_count = _group_channel_count(output)
    target_stem_id = _output_target_stem_id(output)
    if artifact_role == "processed_stem" or target_stem_id:
        return ("processed_stem", target_stem_id or "UNKNOWN", layout_id, channel_count)

    target_bus_id = _output_target_bus_id(output)
    if artifact_role == "processed_bus" or target_bus_id:
        return ("processed_bus", target_bus_id or "UNKNOWN", layout_id, channel_count)

    if artifact_role == "master" or layout_id != _UNKNOWN_LAYOUT_ID:
        return ("master", layout_id, layout_id, channel_count)

    output_id = _coerce_str(output.get("output_id")).strip() or "UNKNOWN"
    return (artifact_role, output_id, layout_id, channel_count)


def _group_sort_key(group_key: Tuple[str, str, str, int | None]) -> tuple[int, str, str, int, str]:
    artifact_role, primary_token, layout_id, channel_count = group_key
    role_priority = {
        "master": 0,
        "processed_stem": 1,
        "processed_bus": 2,
    }.get(artifact_role, 99)
    channel_sort = channel_count if channel_count is not None else 2**31 - 1
    return (role_priority, layout_id, primary_token, channel_sort, artifact_role)


def _deliverable_base_id(
    artifact_role: str,
    primary_token: str,
    layout_id: str,
    channel_count: int | None,
) -> str:
    layout_token = layout_id if layout_id != _UNKNOWN_LAYOUT_ID else "UNKNOWN"
    channel_token = f"{channel_count}CH" if channel_count is not None else "UNKNOWNCH"
    if artifact_role == "processed_stem":
        return f"DELIV.STEM.{primary_token}.{layout_token}.{channel_token}"
    if artifact_role == "processed_bus":
        return f"DELIV.BUS.{primary_token}.{layout_token}.{channel_token}"
    if artifact_role != "master":
        return f"DELIV.ARTIFACT.{artifact_role}.{primary_token}.{layout_token}.{channel_token}"
    return f"DELIV.{layout_token}.{channel_token}"


def _normalized_code_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized = [
        item.strip()
        for item in values
        if isinstance(item, str) and item.strip().startswith("RENDER_RESULT.")
    ]
    return sorted(set(normalized))


def _warning_codes_from_strings(values: Sequence[str]) -> list[str]:
    codes: set[str] = set()
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            continue
        if "downmix_similarity_gate_failed_after_fallback" in value:
            codes.add(RENDER_RESULT_DOWNMIX_QA_FAILED)
        if value.endswith(":fallback_applied") or value == "fallback_applied":
            codes.add(RENDER_RESULT_FALLBACK_APPLIED)
        if value.endswith(":missing_channel_order") or value == "missing_channel_order":
            codes.add(RENDER_RESULT_MISSING_CHANNEL_ORDER)
        if (
            "rendered_silence:no_decodable_stems" in value
            or value == "rendered_silence:no_decodable_stems"
        ):
            codes.add(RENDER_RESULT_NO_DECODABLE_STEMS)
        if value.endswith(":placement_policy_unavailable") or value == "placement_policy_unavailable":
            codes.add(RENDER_RESULT_PLACEMENT_POLICY_UNAVAILABLE)
        if value.endswith(":safety_collapse_applied") or value == "safety_collapse_applied":
            codes.add(RENDER_RESULT_SAFETY_COLLAPSE_APPLIED)
        if value.endswith(":silent_output") or value == "silent_output":
            codes.add(RENDER_RESULT_SILENT_OUTPUT)
        if value.endswith(":decode_failed") or "decode_failed" in value:
            codes.add(RENDER_RESULT_STEM_DECODE_FAILED)
    return sorted(codes)


def canonical_warning_codes(*values: Any) -> list[str]:
    codes: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            codes.update(_warning_codes_from_strings([value.strip()]))
        elif isinstance(value, list):
            codes.update(_normalized_code_list(value))
            codes.update(_warning_codes_from_strings(_normalized_string_list(value)))
    return sorted(codes)


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def build_output_render_result(
    *,
    artifact_role: str,
    planned_stem_count: int | None,
    decoded_stem_count: int | None,
    prepared_stem_count: int | None,
    skipped_stem_count: int | None,
    rendered_frame_count: int | None,
    duration_seconds: float | None,
    warning_codes: Sequence[str] | None = None,
    failure_reason: str | None = None,
    target_layout_id: str | None = None,
) -> dict[str, Any]:
    warning_code_values = sorted(
        {
            code.strip()
            for code in list(warning_codes or [])
            if isinstance(code, str) and code.strip()
        }
    )
    normalized_failure_reason = failure_reason.strip() if isinstance(failure_reason, str) else ""
    if not normalized_failure_reason:
        normalized_failure_reason = next(
            (code for code in warning_code_values if code in _FAILURE_REASON_WARNING_CODES),
            "",
        )

    return {
        "artifact_role": artifact_role,
        "planned_stem_count": planned_stem_count,
        "decoded_stem_count": decoded_stem_count,
        "prepared_stem_count": prepared_stem_count,
        "skipped_stem_count": skipped_stem_count,
        "rendered_frame_count": rendered_frame_count,
        "duration_seconds": (
            round(float(duration_seconds), 6)
            if isinstance(duration_seconds, (int, float))
            else None
        ),
        "failure_reason": normalized_failure_reason or None,
        "warning_codes": warning_code_values,
        "target_layout_id": target_layout_id or None,
    }


def _output_warning_codes(output: Dict[str, Any]) -> list[str]:
    render_result = _output_render_result(output)
    warning_codes = set(_normalized_code_list(render_result.get("warning_codes")))
    metadata = _output_metadata(output)
    warning_codes.update(
        _warning_codes_from_strings(_normalized_string_list(metadata.get("warnings")))
    )
    return sorted(warning_codes)


def _output_result_value(output: Dict[str, Any], key: str) -> Any:
    render_result = _output_render_result(output)
    return render_result.get(key)


def _max_optional_int(values: Sequence[int | None]) -> int | None:
    normalized = [value for value in values if isinstance(value, int) and value >= 0]
    if not normalized:
        return None
    return max(normalized)


def _max_optional_float(values: Sequence[float | None]) -> float | None:
    normalized = [value for value in values if isinstance(value, (int, float)) and value >= 0]
    if not normalized:
        return None
    return float(max(normalized))


def _first_nonempty_string(values: Sequence[str]) -> str | None:
    for value in values:
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def is_effectively_silent_peak_linear(peak_linear: float | None) -> bool:
    if peak_linear is None:
        return True
    if not isinstance(peak_linear, (int, float)):
        return False
    if not math.isfinite(float(peak_linear)):
        return False
    return float(peak_linear) <= SILENT_OUTPUT_LINEAR_TOLERANCE


def _deliverable_status(
    *,
    artifact_roles: set[str],
    output_count: int,
    planned_stem_count: int | None,
    decoded_stem_count: int | None,
    prepared_stem_count: int | None,
    skipped_stem_count: int | None,
    rendered_frame_count: int | None,
    warning_codes: list[str],
    failure_reason: str | None,
) -> str:
    if output_count <= 0:
        return DELIVERABLE_STATUS_FAILED

    zero_decoded_nonempty = (
        planned_stem_count is not None
        and planned_stem_count > 0
        and decoded_stem_count is not None
        and decoded_stem_count <= 0
    )
    if zero_decoded_nonempty:
        return DELIVERABLE_STATUS_FAILED

    failure_code = failure_reason or next(
        (code for code in warning_codes if code in _FAILURE_REASON_WARNING_CODES),
        None,
    )
    invalid_master_code = (
        failure_code
        if failure_code in _INVALID_MASTER_WARNING_CODES
        else next((code for code in warning_codes if code in _INVALID_MASTER_WARNING_CODES), None)
    )

    is_master_candidate = "master" in artifact_roles
    if is_master_candidate and invalid_master_code:
        return DELIVERABLE_STATUS_INVALID_MASTER
    if failure_code == RENDER_RESULT_NO_DECODABLE_STEMS:
        return DELIVERABLE_STATUS_FAILED
    if is_master_candidate and planned_stem_count and decoded_stem_count is not None:
        if decoded_stem_count < planned_stem_count:
            return DELIVERABLE_STATUS_PARTIAL

    if planned_stem_count and prepared_stem_count is not None and prepared_stem_count < planned_stem_count:
        return DELIVERABLE_STATUS_PARTIAL
    if skipped_stem_count is not None and skipped_stem_count > 0:
        return DELIVERABLE_STATUS_PARTIAL
    if rendered_frame_count is not None and rendered_frame_count <= 0:
        return DELIVERABLE_STATUS_FAILED
    if warning_codes:
        return DELIVERABLE_STATUS_PARTIAL
    return DELIVERABLE_STATUS_SUCCESS


def _deliverable_row_from_group(
    *,
    artifact_role: str,
    primary_token: str,
    layout_id: str,
    channel_count: int | None,
    outputs: list[Dict[str, Any]],
) -> dict[str, Any] | None:
    group_outputs = sorted(outputs, key=_output_sort_key)

    output_ids = [
        output_id
        for output in group_outputs
        for output_id in [_coerce_str(output.get("output_id")).strip()]
        if output_id
    ]
    if not output_ids:
        return None

    formats = sorted(
        {
            output_format
            for output in group_outputs
            for output_format in [_coerce_str(output.get("format")).strip().lower()]
            if output_format
        }
    )
    artifact_roles = {
        artifact_role
        for output in group_outputs
        for artifact_role in [_output_artifact_role(output)]
        if artifact_role
    }
    warning_codes = sorted(
        {
            code
            for output in group_outputs
            for code in _output_warning_codes(output)
        }
    )

    planned_stem_count = _max_optional_int(
        [_coerce_int(_output_result_value(output, "planned_stem_count")) for output in group_outputs]
    )
    decoded_stem_count = _max_optional_int(
        [_coerce_int(_output_result_value(output, "decoded_stem_count")) for output in group_outputs]
    )
    prepared_stem_count = _max_optional_int(
        [_coerce_int(_output_result_value(output, "prepared_stem_count")) for output in group_outputs]
    )
    skipped_stem_count = _max_optional_int(
        [_coerce_int(_output_result_value(output, "skipped_stem_count")) for output in group_outputs]
    )
    rendered_frame_count = _max_optional_int(
        [_coerce_int(_output_result_value(output, "rendered_frame_count")) for output in group_outputs]
    )
    duration_seconds = _max_optional_float(
        [_coerce_float(_output_result_value(output, "duration_seconds")) for output in group_outputs]
    )

    if (
        planned_stem_count is not None
        and decoded_stem_count is not None
        and decoded_stem_count < planned_stem_count
        and RENDER_RESULT_STEMS_SKIPPED not in warning_codes
    ):
        warning_codes.append(RENDER_RESULT_STEMS_SKIPPED)
        warning_codes = sorted(set(warning_codes))
    if (
        skipped_stem_count is not None
        and skipped_stem_count > 0
        and RENDER_RESULT_STEMS_SKIPPED not in warning_codes
    ):
        warning_codes.append(RENDER_RESULT_STEMS_SKIPPED)
        warning_codes = sorted(set(warning_codes))

    failure_reason = _first_nonempty_string(
        [
            _coerce_str(_output_result_value(output, "failure_reason"))
            for output in group_outputs
        ]
    )
    if failure_reason is None:
        failure_reason = next(
            (code for code in warning_codes if code in _FAILURE_REASON_WARNING_CODES),
            None,
        )

    deliverable: Dict[str, Any] = {
        "label": (
            f"{layout_id} deliverable"
            if artifact_role == "master" and layout_id != _UNKNOWN_LAYOUT_ID
            else (
                f"{primary_token} processed stem"
                if artifact_role == "processed_stem" and primary_token
                else (
                    f"{primary_token} processed bus"
                    if artifact_role == "processed_bus" and primary_token
                    else "Deliverable"
                )
            )
        ),
        "artifact_role": artifact_role,
        "output_ids": output_ids,
        "status": _deliverable_status(
            artifact_roles=artifact_roles,
            output_count=len(group_outputs),
            planned_stem_count=planned_stem_count,
            decoded_stem_count=decoded_stem_count,
            prepared_stem_count=prepared_stem_count,
            skipped_stem_count=skipped_stem_count,
            rendered_frame_count=rendered_frame_count,
            warning_codes=warning_codes,
            failure_reason=failure_reason,
        ),
        "is_valid_master": bool("master" in artifact_roles),
        "planned_stem_count": planned_stem_count,
        "decoded_stem_count": decoded_stem_count,
        "prepared_stem_count": prepared_stem_count,
        "skipped_stem_count": skipped_stem_count,
        "rendered_frame_count": rendered_frame_count,
        "duration_seconds": round(float(duration_seconds), 6)
        if duration_seconds is not None
        else None,
        "failure_reason": failure_reason,
        "warning_codes": warning_codes,
    }
    if deliverable["status"] != DELIVERABLE_STATUS_SUCCESS:
        deliverable["is_valid_master"] = False

    if layout_id != _UNKNOWN_LAYOUT_ID:
        deliverable["target_layout_id"] = layout_id
    if artifact_role == "processed_stem" and primary_token:
        deliverable["target_stem_id"] = primary_token
    if artifact_role == "processed_bus" and primary_token:
        deliverable["target_bus_id"] = primary_token
    if channel_count is not None:
        deliverable["channel_count"] = channel_count
    if formats:
        deliverable["formats"] = formats
    return deliverable


def _layout_failure_codes_from_manifest(manifest: dict[str, Any]) -> dict[str, list[str]]:
    notes = _coerce_str(manifest.get("notes")).strip()
    if not notes:
        return {}

    codes_by_layout: dict[str, set[str]] = {}
    for raw_note in notes.split(";"):
        note = raw_note.strip()
        if not note.startswith("LAYOUT."):
            continue
        layout_id, _separator, remainder = note.partition(":")
        if not layout_id or not remainder:
            continue
        for suffix, code in _LAYOUT_FAILURE_CODES_BY_SUFFIX.items():
            if remainder.endswith(suffix) or remainder == suffix:
                codes_by_layout.setdefault(layout_id, set()).add(code)
    return {
        layout_id: sorted(codes)
        for layout_id, codes in sorted(codes_by_layout.items())
    }


def _layout_channel_count(layout_id: str) -> int | None:
    if not layout_id or layout_id == _UNKNOWN_LAYOUT_ID:
        return None
    channel_order = get_layout_channel_order(layout_id)
    if not isinstance(channel_order, list) or not channel_order:
        return None
    return len(channel_order)


def _failed_deliverable_row(
    *,
    layout_id: str,
    warning_codes: list[str],
) -> dict[str, Any]:
    channel_count = _layout_channel_count(layout_id)
    failure_reason = next(
        (code for code in warning_codes if code in _FAILURE_REASON_WARNING_CODES),
        None,
    ) or _first_nonempty_string(warning_codes) or RENDER_RESULT_NO_OUTPUT_ARTIFACT
    return {
        "deliverable_id": _deliverable_base_id("master", layout_id, layout_id, channel_count),
        "label": (
            f"{layout_id} deliverable"
            if layout_id != _UNKNOWN_LAYOUT_ID
            else "Deliverable"
        ),
        "artifact_role": "master",
        "target_layout_id": layout_id if layout_id != _UNKNOWN_LAYOUT_ID else None,
        "channel_count": channel_count,
        "formats": [],
        "output_ids": [],
        "status": DELIVERABLE_STATUS_FAILED,
        "is_valid_master": False,
        "planned_stem_count": None,
        "decoded_stem_count": None,
        "prepared_stem_count": None,
        "skipped_stem_count": None,
        "rendered_frame_count": None,
        "duration_seconds": None,
        "failure_reason": failure_reason,
        "warning_codes": warning_codes or [RENDER_RESULT_NO_OUTPUT_ARTIFACT],
    }


def collect_outputs_from_renderer_manifests(
    renderer_manifests: Sequence[dict[str, Any]],
) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        manifest_outputs = manifest.get("outputs")
        if not isinstance(manifest_outputs, list):
            continue
        for output in manifest_outputs:
            if isinstance(output, dict):
                outputs.append(output)
    outputs.sort(key=_output_sort_key)
    return outputs


def build_deliverables_from_outputs(outputs: Sequence[dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str, int | None], List[Dict[str, Any]]] = {}
    for output in outputs:
        if not isinstance(output, dict) or not _should_include_output_in_deliverables(output):
            continue
        key = _group_identity(output)
        grouped.setdefault(key, []).append(output)

    provisional: List[Tuple[str, Dict[str, Any]]] = []
    for group_key in sorted(grouped, key=_group_sort_key):
        artifact_role, primary_token, layout_id, channel_count = group_key
        deliverable = _deliverable_row_from_group(
            artifact_role=artifact_role,
            primary_token=primary_token,
            layout_id=layout_id,
            channel_count=channel_count,
            outputs=grouped[group_key],
        )
        if deliverable is None:
            continue
        provisional.append(
            (
                _deliverable_base_id(
                    artifact_role,
                    primary_token,
                    layout_id,
                    channel_count,
                ),
                deliverable,
            )
        )

    deliverables: List[Dict[str, Any]] = []
    used_ids: Dict[str, int] = {}
    for base_id, deliverable in provisional:
        count = used_ids.get(base_id, 0) + 1
        used_ids[base_id] = count
        if count == 1:
            deliverable["deliverable_id"] = base_id
        else:
            deliverable["deliverable_id"] = f"{base_id}.{count}"
        deliverables.append(deliverable)

    deliverables.sort(key=lambda item: _coerce_str(item.get("deliverable_id")))
    return deliverables


def build_deliverables_from_renderer_manifests(
    renderer_manifests: Sequence[dict[str, Any]],
) -> List[Dict[str, Any]]:
    deliverables = build_deliverables_from_outputs(
        collect_outputs_from_renderer_manifests(renderer_manifests)
    )
    seen_layout_ids = {
        _coerce_str(deliverable.get("target_layout_id")).strip()
        for deliverable in deliverables
        if _coerce_str(deliverable.get("target_layout_id")).strip()
    }
    failed_deliverables: list[dict[str, Any]] = []
    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        for layout_id, warning_codes in _layout_failure_codes_from_manifest(manifest).items():
            if layout_id in seen_layout_ids:
                continue
            failed_deliverables.append(
                _failed_deliverable_row(
                    layout_id=layout_id,
                    warning_codes=warning_codes,
                )
            )
            seen_layout_ids.add(layout_id)

    all_deliverables = [*deliverables, *failed_deliverables]
    all_deliverables.sort(key=lambda item: _coerce_str(item.get("deliverable_id")))
    return all_deliverables


def summarize_deliverables(deliverables: Sequence[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "overall_status": None,
        "deliverable_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "partial_count": 0,
        "invalid_master_count": 0,
        "valid_master_count": 0,
        "mixed_outcomes": False,
    }
    statuses: list[str] = []
    for deliverable in deliverables:
        if not isinstance(deliverable, dict):
            continue
        summary["deliverable_count"] += 1
        if deliverable.get("is_valid_master") is True:
            summary["valid_master_count"] += 1

        status = _coerce_str(deliverable.get("status")).strip()
        if status not in _DELIVERABLE_STATUSES:
            continue
        statuses.append(status)
        summary[f"{status}_count"] += 1

    if not statuses:
        return summary

    unique_statuses = set(statuses)
    summary["mixed_outcomes"] = len(unique_statuses) > 1
    if all(status == DELIVERABLE_STATUS_SUCCESS for status in statuses):
        summary["overall_status"] = DELIVERABLE_STATUS_SUCCESS
    elif any(status in {DELIVERABLE_STATUS_SUCCESS, DELIVERABLE_STATUS_PARTIAL} for status in statuses):
        summary["overall_status"] = DELIVERABLE_STATUS_PARTIAL
    elif (
        DELIVERABLE_STATUS_INVALID_MASTER in unique_statuses
        and DELIVERABLE_STATUS_FAILED not in unique_statuses
    ):
        summary["overall_status"] = DELIVERABLE_STATUS_INVALID_MASTER
    else:
        summary["overall_status"] = DELIVERABLE_STATUS_FAILED
    return summary
