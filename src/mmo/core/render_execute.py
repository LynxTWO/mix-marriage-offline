"""Build deterministic render_execute payloads for executed render-run jobs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import sha256_file
from mmo.dsp.stream_meters import compute_stream_meters


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_id(*, request_sha256: str, plan_sha256: str) -> str:
    material = f"{request_sha256}:{plan_sha256}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"RUN.{digest[:16]}"


def resolve_ffmpeg_version(ffmpeg_cmd: Sequence[str] | None) -> str:
    """Return first non-empty ``ffmpeg -version`` line, or ``unknown``."""
    if not ffmpeg_cmd:
        return "unknown"
    command = [*ffmpeg_cmd, "-version"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unknown"

    candidates = [
        completed.stdout.splitlines(),
        completed.stderr.splitlines(),
    ]
    for lines in candidates:
        for line in lines:
            normalized = line.strip()
            if normalized:
                return normalized
    return "unknown"


def _normalize_paths(raw_paths: Any) -> list[Path]:
    if not isinstance(raw_paths, list):
        return []

    normalized: dict[str, Path] = {}
    for value in raw_paths:
        if isinstance(value, Path):
            resolved = value.resolve()
        elif isinstance(value, str) and value.strip():
            resolved = Path(value.strip()).resolve()
        else:
            continue
        normalized.setdefault(resolved.as_posix(), resolved)
    return [normalized[key] for key in sorted(normalized.keys())]


def _file_pointer(
    path: Path,
    *,
    ffmpeg_cmd: Sequence[str] | None,
    meters_cache: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"render_execute file pointer path is missing: {resolved.as_posix()}")
    key = resolved.as_posix()
    if key not in meters_cache:
        meters_cache[key] = compute_stream_meters(
            resolved,
            ffmpeg_cmd=ffmpeg_cmd,
        )
    return {
        "path": key,
        "sha256": sha256_file(resolved),
        "meters": {
            "peak_dbfs": meters_cache[key].get("peak_dbfs"),
            "rms_dbfs": meters_cache[key].get("rms_dbfs"),
            "integrated_lufs": meters_cache[key].get("integrated_lufs"),
        },
    }


def _normalize_ffmpeg_commands(raw_commands: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_commands, list):
        return []

    normalized_rows: list[dict[str, Any]] = []
    for row in raw_commands:
        if not isinstance(row, dict):
            continue
        args_raw = row.get("args")
        flags_raw = row.get("determinism_flags")
        if not isinstance(args_raw, list):
            continue

        args = [
            _coerce_str(arg).strip()
            for arg in args_raw
            if _coerce_str(arg).strip()
        ]
        if not args:
            continue
        determinism_flags = (
            [
                _coerce_str(flag).strip()
                for flag in flags_raw
                if _coerce_str(flag).strip()
            ]
            if isinstance(flags_raw, list)
            else []
        )
        normalized_rows.append(
            {
                "args": args,
                "determinism_flags": determinism_flags,
            }
        )
    return normalized_rows


def build_render_execute_payload(
    *,
    request_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    job_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a schema-valid deterministic render_execute payload."""
    request_sha256 = _canonical_sha256(request_payload)
    plan_sha256 = _canonical_sha256(plan_payload)
    run_id = _run_id(request_sha256=request_sha256, plan_sha256=plan_sha256)
    ffmpeg_cmd = resolve_ffmpeg_cmd()
    meters_cache: dict[str, dict[str, float | None]] = {}

    jobs: list[dict[str, Any]] = []
    for row in job_rows:
        if not isinstance(row, dict):
            continue
        job_id = _coerce_str(row.get("job_id")).strip()
        if not job_id:
            continue

        input_paths = _normalize_paths(row.get("input_paths"))
        if not input_paths:
            raise ValueError(f"render_execute job {job_id} is missing input_paths.")
        output_paths = _normalize_paths(row.get("output_paths"))
        if not output_paths:
            raise ValueError(f"render_execute job {job_id} is missing output_paths.")

        ffmpeg_version = _coerce_str(row.get("ffmpeg_version")).strip() or "unknown"
        ffmpeg_commands = _normalize_ffmpeg_commands(row.get("ffmpeg_commands"))
        if not ffmpeg_commands:
            raise ValueError(f"render_execute job {job_id} is missing ffmpeg_commands.")

        jobs.append(
            {
                "job_id": job_id,
                "inputs": [
                    _file_pointer(
                        path,
                        ffmpeg_cmd=ffmpeg_cmd,
                        meters_cache=meters_cache,
                    )
                    for path in input_paths
                ],
                "outputs": [
                    _file_pointer(
                        path,
                        ffmpeg_cmd=ffmpeg_cmd,
                        meters_cache=meters_cache,
                    )
                    for path in output_paths
                ],
                "ffmpeg_version": ffmpeg_version,
                "ffmpeg_commands": ffmpeg_commands,
            }
        )

    if not jobs:
        raise ValueError("render_execute requires at least one executed job row.")
    jobs.sort(key=lambda item: _coerce_str(item.get("job_id")).strip())

    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "request_sha256": request_sha256,
        "plan_sha256": plan_sha256,
        "jobs": jobs,
    }
