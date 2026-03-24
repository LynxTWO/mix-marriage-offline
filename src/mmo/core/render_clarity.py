from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence

from mmo.core.deliverables import (
    DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY,
    DELIVERABLE_RESULT_BUCKET_FULL_FAILURE,
    DELIVERABLE_RESULT_BUCKET_PARTIAL_SUCCESS,
    DELIVERABLE_RESULT_BUCKET_SUCCESS_NO_MASTER,
    DELIVERABLE_RESULT_BUCKET_VALID_MASTER,
    DELIVERABLE_STATUS_FAILED,
    DELIVERABLE_STATUS_INVALID_MASTER,
    DELIVERABLE_STATUS_PARTIAL,
    RENDER_RESULT_NO_DECODABLE_STEMS,
    RENDER_RESULT_NO_OUTPUT_ARTIFACT,
    RENDER_RESULT_SILENT_OUTPUT,
)
from mmo.core.status_display import label_for_deliverable_result_bucket
from mmo.resources import load_ontology_yaml

_DURATION_PRECISION = 6

_ISSUE_COPY_OVERRIDES: dict[str, dict[str, str]] = {
    "ISSUE.VALIDATION.DURATION_MISMATCH": {
        "title": "Stem durations do not match",
        "message": (
            "At least one stem is a different length, so MMO cannot trust timing "
            "alignment for the session."
        ),
        "remedy": (
            "Re-export the stems so they start together and run the same length, "
            "then rerun Analyze."
        ),
    },
    "ISSUE.RENDER.ALL_MASTERS_INVALID": {
        "title": "No valid master was produced",
        "message": (
            "MMO kept the written artifacts for diagnostics, but none of the "
            "master outputs qualified as a valid render."
        ),
        "remedy": (
            "Open the failing deliverable summary, fix the decode or routing "
            "problem, then rerun Render."
        ),
    },
    "ISSUE.RENDER.NO_OUTPUTS": {
        "title": "Render produced no outputs",
        "message": "MMO finished the render step without writing any audio files.",
        "remedy": (
            "Confirm that the selected target has an active renderer and that the "
            "workspace is writable, then rerun Render."
        ),
    },
    "ISSUE.RENDER.QA.SILENT_OUTPUT": {
        "title": "Rendered master is silent",
        "message": (
            "MMO measured the rendered output as effectively silent, so the file "
            "does not count as a valid master."
        ),
        "remedy": (
            "Check routing, muted stems, and source audio, then rerun Render after "
            "confirming audible signal reaches the target output."
        ),
    },
    "ISSUE.RENDER.QA.LOUDNESS_NON_MEASURABLE": {
        "title": "Rendered loudness could not be measured",
        "message": (
            "MMO expected audible program material, but loudness measurement did "
            "not produce a usable result."
        ),
        "remedy": (
            "Check for silent or unreadable render output, then rerun Render after "
            "fixing the source or routing problem."
        ),
    },
    "ISSUE.RENDER.QA.PEAK_NON_MEASURABLE": {
        "title": "Rendered true-peak could not be measured",
        "message": (
            "MMO expected audible program material, but true-peak measurement did "
            "not produce a usable result."
        ),
        "remedy": (
            "Check for silent or unreadable render output, then rerun Render after "
            "fixing the source or routing problem."
        ),
    },
    "ISSUE.RENDER.QA.CORRELATION_NON_MEASURABLE": {
        "title": "Rendered stereo correlation could not be measured",
        "message": (
            "MMO expected measurable stereo output, but the rendered audio did "
            "not contain enough usable signal for correlation analysis."
        ),
        "remedy": (
            "Check for silent output, missing decode, or routing problems, then "
            "rerun Render."
        ),
    },
    "ISSUE.RENDER.SCENE_STEM_BINDING_EMPTY": {
        "title": "Scene references do not match analyzed stems",
        "message": (
            "Scene references do not match analyzed stems. MMO could not match "
            "any of the explicit scene references to the stems owned by the "
            "analyzed report, so rendering was stopped before audio was written."
        ),
        "remedy": (
            "Rebuild the scene from this report or replace the drifted scene "
            "references with the current analyzed stem IDs, then rerun Render."
        ),
    },
    "ISSUE.RENDER.SCENE_STEM_BINDING_PARTIAL": {
        "title": "Scene only partially matches analyzed stems",
        "message": (
            "Scene references only partially match analyzed stems. Some explicit "
            "scene references still match the analyzed report, but others do not, "
            "so MMO cannot trust the scene completely."
        ),
        "remedy": (
            "Fix the unresolved scene references or rebuild the scene from the "
            "current report before rerunning Render."
        ),
    },
    "ISSUE.RENDER.SCENE_STEM_BINDING_AMBIGUOUS": {
        "title": "Scene references collapse onto the same analyzed stem",
        "message": (
            "Multiple scene refs resolved to the same analyzed stem, so the "
            "scene may be double-addressing one source."
        ),
        "remedy": (
            "Review the explicit scene bindings, remove duplicate references, and "
            "rerun Render."
        ),
    },
}

_FAILURE_REASON_COPY: dict[str, dict[str, str]] = {
    RENDER_RESULT_NO_DECODABLE_STEMS: {
        "title": "Render failed: no decodable stems",
        "message": (
            "MMO planned the render, but none of the selected stems decoded into "
            "audio. Any written artifact is diagnostic only."
        ),
        "remedy": (
            "Open the stem diagnostics, repair or replace the failing source "
            "files, then rerun Render."
        ),
    },
    RENDER_RESULT_NO_OUTPUT_ARTIFACT: {
        "title": "Render produced no output files",
        "message": (
            "MMO finished the render stage without writing any audio deliverable."
        ),
        "remedy": (
            "Check the renderer selection and workspace permissions, then rerun "
            "Render."
        ),
    },
    RENDER_RESULT_SILENT_OUTPUT: {
        "title": "Render invalid: silent master",
        "message": (
            "MMO wrote the output file, but the rendered master is effectively "
            "silent and does not count as a valid master."
        ),
        "remedy": (
            "Check routing, muted stems, source audio, and decode counts, then "
            "rerun Render after confirming audible signal reaches the target "
            "layout."
        ),
    },
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


def _iter_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]
    return sorted(set(normalized))


@lru_cache(maxsize=1)
def _issue_registry() -> dict[str, dict[str, Any]]:
    try:
        payload = load_ontology_yaml("issues.yaml")
    except Exception:
        return {}
    issues = payload.get("issues")
    if not isinstance(issues, dict):
        return {}
    return {
        issue_id: entry
        for issue_id, entry in issues.items()
        if isinstance(issue_id, str)
        and issue_id
        and isinstance(entry, dict)
        and not issue_id.startswith("_")
    }


def _generic_issue_remedy(issue_id: str) -> str:
    if issue_id.startswith("ISSUE.VALIDATION."):
        return "Fix the reported input problem, then rerun Analyze."
    if issue_id.startswith("ISSUE.RENDER.QA."):
        return "Fix the render problem, then rerun Render."
    if issue_id.startswith("ISSUE.RENDER."):
        return "Review the render diagnostics, correct the failure, then rerun Render."
    return "Review the evidence for this issue, correct the source problem, then rerun."


def _issue_copy_from_registry(issue_id: str) -> dict[str, str]:
    entry = _issue_registry().get(issue_id)
    if not isinstance(entry, dict):
        return {}
    title = _coerce_str(entry.get("label")).strip()
    message = _coerce_str(entry.get("description")).strip()
    payload: dict[str, str] = {}
    if title:
        payload["title"] = title
    if message:
        payload["message"] = message
    return payload


def _issue_failure_reason(issue: dict[str, Any]) -> str:
    failure_reason = _coerce_str(issue.get("failure_reason")).strip()
    if failure_reason:
        return failure_reason
    warning_codes = _normalized_string_list(issue.get("warning_codes"))
    for code in warning_codes:
        if code.startswith("RENDER_RESULT."):
            return code
    return ""


def enrich_issue_for_user(issue: dict[str, Any]) -> dict[str, Any]:
    payload = dict(issue)
    issue_id = _coerce_str(payload.get("issue_id")).strip()
    failure_reason = _issue_failure_reason(payload)
    copy_payload = dict(_issue_copy_from_registry(issue_id))
    if issue_id in _ISSUE_COPY_OVERRIDES:
        copy_payload.update(_ISSUE_COPY_OVERRIDES[issue_id])
    if failure_reason in _FAILURE_REASON_COPY:
        copy_payload.update(_FAILURE_REASON_COPY[failure_reason])

    title = _coerce_str(payload.get("title")).strip() or _coerce_str(copy_payload.get("title")).strip()
    message = _coerce_str(copy_payload.get("message")).strip() or _coerce_str(payload.get("message")).strip()
    remedy = _coerce_str(payload.get("remedy")).strip() or _coerce_str(copy_payload.get("remedy")).strip()

    if title:
        payload["title"] = title
    if message:
        payload["message"] = message
    if not remedy:
        remedy = _generic_issue_remedy(issue_id)
    if remedy:
        payload["remedy"] = remedy
    return payload


def enrich_issue_list_for_user(issues: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(issues, Sequence):
        return []
    return [
        enrich_issue_for_user(issue)
        for issue in issues
        if isinstance(issue, dict)
    ]


def _output_index(renderer_manifests: Sequence[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for manifest in renderer_manifests or []:
        if not isinstance(manifest, dict):
            continue
        for output in _iter_dict_list(manifest.get("outputs")):
            output_id = _coerce_str(output.get("output_id")).strip()
            if output_id and output_id not in indexed:
                indexed[output_id] = output
    return indexed


def _duration_from_frames(
    *,
    rendered_frame_count: int | None,
    sample_rate_hz: int | None,
    fallback_duration_seconds: float | None,
) -> float | None:
    if (
        isinstance(rendered_frame_count, int)
        and rendered_frame_count >= 0
        and isinstance(sample_rate_hz, int)
        and sample_rate_hz > 0
    ):
        return round(rendered_frame_count / sample_rate_hz, _DURATION_PRECISION)
    if isinstance(fallback_duration_seconds, (int, float)) and fallback_duration_seconds >= 0:
        return round(float(fallback_duration_seconds), _DURATION_PRECISION)
    return None


def _deliverable_failure_reason(deliverable: dict[str, Any]) -> str | None:
    explicit = _coerce_str(deliverable.get("failure_reason")).strip()
    if explicit:
        return explicit
    warning_codes = _normalized_string_list(deliverable.get("warning_codes"))
    return warning_codes[0] if warning_codes else None


def _deliverable_validity(deliverable: dict[str, Any]) -> str:
    artifact_role = _coerce_str(deliverable.get("artifact_role")).strip().lower()
    status = _coerce_str(deliverable.get("status")).strip().lower()
    if deliverable.get("is_valid_master") is True:
        return DELIVERABLE_RESULT_BUCKET_VALID_MASTER
    if artifact_role == "master":
        if status == DELIVERABLE_STATUS_INVALID_MASTER:
            return DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY
        if status == DELIVERABLE_STATUS_FAILED:
            return DELIVERABLE_RESULT_BUCKET_FULL_FAILURE
        if status == DELIVERABLE_STATUS_PARTIAL:
            return DELIVERABLE_RESULT_BUCKET_PARTIAL_SUCCESS
    return DELIVERABLE_RESULT_BUCKET_SUCCESS_NO_MASTER


def build_deliverable_summary_rows(
    *,
    renderer_manifests: Sequence[dict[str, Any]] | None,
    deliverables: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    outputs_by_id = _output_index(renderer_manifests)
    rows: list[dict[str, Any]] = []

    for deliverable in sorted(
        (item for item in deliverables or [] if isinstance(item, dict)),
        key=lambda item: _coerce_str(item.get("deliverable_id")).strip(),
    ):
        output_ids = [
            output_id.strip()
            for output_id in deliverable.get("output_ids", [])
            if isinstance(output_id, str) and output_id.strip()
        ]
        if not output_ids:
            output_ids = [""]

        for output_id in sorted(output_ids):
            output = outputs_by_id.get(output_id, {})
            sample_rate_hz = _coerce_int(output.get("sample_rate_hz"))
            rendered_frame_count = _coerce_int(deliverable.get("rendered_frame_count"))
            duration_seconds = _duration_from_frames(
                rendered_frame_count=rendered_frame_count,
                sample_rate_hz=sample_rate_hz,
                fallback_duration_seconds=_coerce_float(
                    deliverable.get("duration_seconds")
                ),
            )
            row: dict[str, Any] = {
                "deliverable_id": _coerce_str(deliverable.get("deliverable_id")).strip(),
                "output_id": output_id or None,
                "layout": (
                    _coerce_str(deliverable.get("target_layout_id")).strip()
                    or _coerce_str(output.get("layout_id")).strip()
                    or None
                ),
                "file_path": _coerce_str(output.get("file_path")).strip() or None,
                "channel_count": (
                    _coerce_int(output.get("channel_count"))
                    or _coerce_int(deliverable.get("channel_count"))
                ),
                "sample_rate_hz": sample_rate_hz,
                "rendered_frame_count": rendered_frame_count,
                "duration_seconds": duration_seconds,
                "status": _coerce_str(deliverable.get("status")).strip() or None,
                "validity": _deliverable_validity(deliverable),
                "failure_reason": _deliverable_failure_reason(deliverable),
            }
            output_format = _coerce_str(output.get("format")).strip().lower()
            if output_format:
                row["format"] = output_format
            artifact_role = _coerce_str(deliverable.get("artifact_role")).strip()
            if artifact_role:
                row["artifact_role"] = artifact_role
            rows.append(row)

    rows.sort(
        key=lambda row: (
            _coerce_str(row.get("layout")).strip(),
            _coerce_str(row.get("file_path")).strip(),
            _coerce_str(row.get("output_id")).strip(),
            _coerce_str(row.get("deliverable_id")).strip(),
        )
    )
    return rows


def _first_row_path(
    rows: Sequence[dict[str, Any]],
    *,
    validity: str | None = None,
) -> str | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if validity is not None and _coerce_str(row.get("validity")).strip() != validity:
            continue
        file_path = _coerce_str(row.get("file_path")).strip()
        if file_path:
            return file_path
    return None


def build_result_summary(
    *,
    deliverables_summary: dict[str, Any],
    deliverable_summary_rows: Sequence[dict[str, Any]] | None,
) -> dict[str, Any]:
    rows = [
        row
        for row in deliverable_summary_rows or []
        if isinstance(row, dict)
    ]
    result_bucket = _coerce_str(deliverables_summary.get("result_bucket")).strip()
    overall_status = _coerce_str(deliverables_summary.get("overall_status")).strip()
    top_failure_reason = _coerce_str(
        deliverables_summary.get("top_failure_reason")
    ).strip()
    valid_master_count = _coerce_int(deliverables_summary.get("valid_master_count")) or 0
    deliverable_count = _coerce_int(deliverables_summary.get("deliverable_count")) or 0
    failed_total = (
        (_coerce_int(deliverables_summary.get("failed_count")) or 0)
        + (_coerce_int(deliverables_summary.get("invalid_master_count")) or 0)
    )
    primary_output_path = _first_row_path(
        rows,
        validity=DELIVERABLE_RESULT_BUCKET_VALID_MASTER,
    ) or _first_row_path(rows)

    failure_copy = _FAILURE_REASON_COPY.get(top_failure_reason, {})
    title = "Render result"
    message = "MMO finished the render step."
    remedy = "Review the render artifacts and QA output."

    if deliverable_count == 0 and not result_bucket:
        title = "No rendered outputs recorded"
        message = "This artifact does not include any rendered deliverables yet."
        remedy = "Run Render to create output audio, or inspect the dry-run receipt for the planned actions."
    elif result_bucket == DELIVERABLE_RESULT_BUCKET_VALID_MASTER:
        title = label_for_deliverable_result_bucket(result_bucket)
        message = (
            f"MMO rendered {valid_master_count} valid master output"
            f"{'' if valid_master_count == 1 else 's'}."
        )
        if primary_output_path:
            message = f"{message} Primary file: {primary_output_path}."
        remedy = "Review any remaining warnings, then use the valid master deliverable."
    elif result_bucket == DELIVERABLE_RESULT_BUCKET_SUCCESS_NO_MASTER:
        title = label_for_deliverable_result_bucket(result_bucket)
        message = (
            f"MMO rendered {len(rows)} output artifact"
            f"{'' if len(rows) == 1 else 's'}, but none of them are master deliverables."
        )
        remedy = (
            "Use the non-master artifacts as intended, or rerun with master export "
            "enabled if you need a final master."
        )
    elif result_bucket == DELIVERABLE_RESULT_BUCKET_PARTIAL_SUCCESS:
        title = label_for_deliverable_result_bucket(result_bucket)
        attention_label = "needs" if failed_total == 1 else "need"
        message = (
            f"MMO rendered {valid_master_count} valid master output"
            f"{'' if valid_master_count == 1 else 's'}, but {failed_total} deliverable"
            f"{'' if failed_total == 1 else 's'} still {attention_label} attention."
        )
        if failure_copy:
            message = f"{message} {failure_copy['message']}"
            remedy = failure_copy["remedy"]
        else:
            remedy = "Use the valid master only if it meets your immediate need, then fix the failed deliverable and rerun."
    elif result_bucket in {
        DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY,
        DELIVERABLE_RESULT_BUCKET_FULL_FAILURE,
    }:
        if failure_copy:
            title = failure_copy["title"]
            message = failure_copy["message"]
            remedy = failure_copy["remedy"]
        elif result_bucket == DELIVERABLE_RESULT_BUCKET_DIAGNOSTICS_ONLY:
            title = label_for_deliverable_result_bucket(result_bucket)
            message = (
                "MMO wrote diagnostic artifacts, but the master did not qualify as "
                "valid output."
            )
            remedy = "Review the failing master summary, fix the render problem, then rerun."
        else:
            title = label_for_deliverable_result_bucket(result_bucket)
            message = "MMO did not produce a usable master render."
            remedy = "Review the render diagnostics, fix the failure, then rerun."

    payload: dict[str, Any] = {
        "title": title,
        "message": message,
        "remedy": remedy,
        "result_bucket": result_bucket or None,
        "overall_status": overall_status or None,
        "top_failure_reason": top_failure_reason or None,
        "deliverable_count": deliverable_count,
        "valid_master_count": valid_master_count,
        "primary_output_path": primary_output_path,
    }
    return payload
