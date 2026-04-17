from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from mmo.core.loudness_profiles import (
    DEFAULT_LOUDNESS_PROFILE_ID,
    resolve_loudness_profile_receipt,
)
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffprobe_cmd


RENDER_PREFLIGHT_SCHEMA_VERSION = "0.1.0"
_DURATION_PRECISION = 6


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _normalize_posix_path(value: Any) -> str:
    normalized = _coerce_str(value).strip().replace("\\", "/")
    return normalized if normalized else "."


def _normalize_job_id(value: Any) -> str:
    normalized = _coerce_str(value).strip()
    return normalized if normalized else "JOB.000"


def _normalize_role(value: Any) -> str:
    normalized = _coerce_str(value).strip()
    return normalized if normalized else "unknown"


def _ffprobe_command_from_env() -> tuple[str, ...] | None:
    resolved = resolve_ffprobe_cmd()
    if resolved is None:
        return None
    return tuple(resolved)


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_duration_seconds(value: Any) -> float | None:
    parsed: float
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed < 0:
        return None
    return round(parsed, _DURATION_PRECISION)


def _run_ffprobe(ffprobe_cmd: tuple[str, ...], *, input_path: Path) -> dict[str, Any] | None:
    command = [
        *ffprobe_cmd,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        os.fspath(input_path),
    ]
    # Preflight records one artifact across every input. Probe failures collapse
    # to None so the caller can keep scanning and emit the full issue set.
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    audio_stream: dict[str, Any] | None = None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            audio_stream = stream
            break
    if audio_stream is None:
        return None

    sample_rate = _parse_int(audio_stream.get("sample_rate"))
    channel_count = _parse_int(audio_stream.get("channels"))
    duration_seconds = _parse_duration_seconds(audio_stream.get("duration"))
    if duration_seconds is None:
        format_payload = payload.get("format")
        if isinstance(format_payload, dict):
            duration_seconds = _parse_duration_seconds(format_payload.get("duration"))

    if (
        sample_rate is None
        or sample_rate <= 0
        or channel_count is None
        or channel_count <= 0
        or duration_seconds is None
    ):
        return None

    return {
        "sample_rate": sample_rate,
        "channel_count": channel_count,
        "duration_seconds": duration_seconds,
    }


def _resolve_input_path(*, plan_path: Path, input_path: str) -> Path:
    candidate = Path(input_path)
    # Job inputs may be stored as relative refs. Anchor them to the saved plan
    # so preflight checks the same files a later render run would resolve.
    if not candidate.is_absolute():
        candidate = plan_path.parent / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _issue(
    *,
    issue_id: str,
    severity: str,
    message: str,
    job_id: str,
    path: str,
    role: str,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "message": message,
        "evidence": {
            "job_id": _normalize_job_id(job_id),
            "path": _normalize_posix_path(path),
            "role": _normalize_role(role),
        },
    }


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    evidence = issue.get("evidence")
    evidence_payload = evidence if isinstance(evidence, dict) else {}
    return (
        _coerce_str(issue.get("severity")).strip(),
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("message")).strip(),
        _coerce_str(evidence_payload.get("job_id")).strip(),
        _coerce_str(evidence_payload.get("path")).strip(),
        _coerce_str(evidence_payload.get("role")).strip(),
    )


def _requested_loudness_profile_id(plan: dict[str, Any]) -> str | None:
    request_echo = plan.get("request")
    if isinstance(request_echo, dict):
        options = request_echo.get("options")
        if isinstance(options, dict):
            profile_id = _coerce_str(options.get("loudness_profile_id")).strip()
            if profile_id:
                return profile_id

    policies = plan.get("policies")
    if isinstance(policies, dict):
        profile_id = _coerce_str(policies.get("loudness_profile_id")).strip()
        if profile_id:
            return profile_id
    return None


def _loudness_profile_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    requested_profile_id = _requested_loudness_profile_id(plan)
    try:
        return resolve_loudness_profile_receipt(requested_profile_id)
    except ValueError as exc:
        # Keep the receipt shape stable even when a saved plan echoes an unknown
        # profile id from an older install or edited request.
        fallback = resolve_loudness_profile_receipt(DEFAULT_LOUDNESS_PROFILE_ID)
        warnings = list(fallback.get("warnings") or [])
        warnings.insert(
            0,
            (
                f"{exc}. Falling back to default loudness_profile_id "
                f"{DEFAULT_LOUDNESS_PROFILE_ID!r}."
            ),
        )
        fallback["warnings"] = warnings
        return fallback


def build_render_preflight_payload(
    plan: dict[str, Any],
    *,
    plan_path: Path,
) -> dict[str, Any]:
    ffprobe_cmd = _ffprobe_command_from_env()
    jobs = plan.get("jobs")
    job_rows: list[dict[str, Any]] = [row for row in jobs if isinstance(row, dict)] if isinstance(jobs, list) else []
    # Sort jobs and inputs so the saved artifact does not depend on planner or
    # filesystem iteration order.
    indexed_jobs = list(enumerate(job_rows))
    indexed_jobs.sort(key=lambda item: (_normalize_job_id(item[1].get("job_id")), item[0]))

    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for _, job in indexed_jobs:
        job_id = _normalize_job_id(job.get("job_id"))
        raw_inputs = job.get("inputs")
        input_rows: list[dict[str, Any]] = (
            [row for row in raw_inputs if isinstance(row, dict)]
            if isinstance(raw_inputs, list)
            else []
        )

        indexed_inputs = list(enumerate(input_rows))
        indexed_inputs.sort(
            key=lambda item: (
                _normalize_posix_path(item[1].get("path")),
                _normalize_role(item[1].get("role")),
                item[0],
            )
        )

        input_checks: list[dict[str, Any]] = []
        has_error = False
        for _, input_row in indexed_inputs:
            input_path = _normalize_posix_path(input_row.get("path"))
            role = _normalize_role(input_row.get("role"))
            resolved_input_path = _resolve_input_path(
                plan_path=plan_path,
                input_path=input_path,
            )

            exists = resolved_input_path.exists()
            is_file = resolved_input_path.is_file()

            if not exists:
                # Missing or wrong-shaped inputs are hard stop evidence. Later
                # render stages must not try to recover past these rows.
                has_error = True
                issues.append(
                    _issue(
                        issue_id="ISSUE.RENDER.PREFLIGHT.INPUT_MISSING",
                        severity="error",
                        message="Input path does not exist.",
                        job_id=job_id,
                        path=input_path,
                        role=role,
                    )
                )
            elif not is_file:
                has_error = True
                issues.append(
                    _issue(
                        issue_id="ISSUE.RENDER.PREFLIGHT.INPUT_NOT_FILE",
                        severity="error",
                        message="Input path is not a file.",
                        job_id=job_id,
                        path=input_path,
                        role=role,
                    )
                )

            ffprobe_payload: dict[str, Any]
            if ffprobe_cmd is None:
                # Missing ffprobe downgrades metadata collection only. Existence
                # and file-shape checks still make preflight useful.
                ffprobe_payload = {"status": "skipped", "reason": "ffprobe unavailable"}
            elif not exists:
                ffprobe_payload = {
                    "status": "skipped",
                    "reason": "input path does not exist",
                }
            elif not is_file:
                ffprobe_payload = {
                    "status": "skipped",
                    "reason": "input path is not a file",
                }
            else:
                metadata = _run_ffprobe(ffprobe_cmd, input_path=resolved_input_path)
                if metadata is None:
                    ffprobe_payload = {
                        "status": "skipped",
                        "reason": "ffprobe metadata unavailable",
                    }
                else:
                    ffprobe_payload = {
                        "status": "ok",
                        "sample_rate": metadata["sample_rate"],
                        "channel_count": metadata["channel_count"],
                        "duration_seconds": metadata["duration_seconds"],
                    }

            input_checks.append(
                {
                    "path": input_path,
                    "role": role,
                    "exists": exists,
                    "is_file": is_file,
                    "ffprobe": ffprobe_payload,
                }
            )

        checks.append(
            {
                "job_id": job_id,
                "input_count": len(input_checks),
                "status": "error" if has_error else "ok",
                "input_checks": input_checks,
            }
        )

    sorted_issues = sorted(issues, key=_issue_sort_key)
    loudness_profile_receipt = _loudness_profile_receipt(plan)
    return {
        "schema_version": RENDER_PREFLIGHT_SCHEMA_VERSION,
        "plan_path": plan_path.resolve().as_posix(),
        "plan_id": _coerce_str(plan.get("plan_id")).strip(),
        "checks": checks,
        "issues": sorted_issues,
        "loudness_profile_receipt": loudness_profile_receipt,
    }


def preflight_has_error_issues(payload: dict[str, Any]) -> bool:
    issues = payload.get("issues")
    if not isinstance(issues, list):
        return False
    # Only error severity blocks render continuation. Warnings stay attached to
    # the artifact without turning preflight into a hard stop.
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if _coerce_str(issue.get("severity")).strip() == "error":
            return True
    return False
