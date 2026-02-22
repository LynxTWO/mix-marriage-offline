"""Regenerate the plugin_chain_registry_dispatch golden fixtures.

Run from the repo root with the project venv active:
    python tools/regen_plugin_chain_baseline.py

The script replicates the exact setup from
TestRenderRunAudioExecution.test_plugin_chain_registry_dispatch_matches_captured_baseline_bytes
and writes fresh fixture files so the test passes on the current numpy version.
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import sys
import wave
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mmo.cli import main  # noqa: E402


# ---------------------------------------------------------------------------
# helpers (mirrors test_cli_render_run.py private helpers exactly)
# ---------------------------------------------------------------------------

def _write_pcm16_registry_baseline_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.25,
) -> None:
    frames = max(1, int(sample_rate_hz * duration_s))
    samples: list[int] = []
    for frame_index in range(frames):
        low = 0.35 * math.sin(2.0 * math.pi * 160.0 * frame_index / sample_rate_hz)
        high = 0.22 * math.sin(2.0 * math.pi * 6000.0 * frame_index / sample_rate_hz)
        value = int((low + high) * 32767.0)
        samples.extend([value, value])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _normalize_strings_for_regression(value: Any, *, repo_root_posix: str) -> Any:
    if isinstance(value, str):
        normalized = value.replace(repo_root_posix, "__REPO_ROOT__")
        if normalized.startswith("PLAN."):
            return "__PLAN_ID__"
        return normalized
    if isinstance(value, list):
        return [_normalize_strings_for_regression(item, repo_root_posix=repo_root_posix) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_strings_for_regression(item, repo_root_posix=repo_root_posix) for key, item in value.items()}
    return value


def _canonical_event_log_bytes(payload_bytes: bytes, *, repo_root_posix: str) -> bytes:
    rows: list[dict[str, Any]] = []
    for line in payload_bytes.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        row.pop("event_id", None)
        rows.append(_normalize_strings_for_regression(row, repo_root_posix=repo_root_posix))
    rows.sort(key=lambda r: json.dumps(r, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    lines = [json.dumps(r, ensure_ascii=True, separators=(",", ":"), sort_keys=True) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _normalize_execute_payload_for_regression(payload: dict[str, Any], *, repo_root_posix: str) -> dict[str, Any]:
    normalized = _normalize_strings_for_regression(payload, repo_root_posix=repo_root_posix)
    if not isinstance(normalized, dict):
        return {}
    for key in ("run_id", "plan_sha256", "request_sha256"):
        if key in normalized:
            normalized[key] = f"__{key.upper()}__"
    jobs = normalized.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if "ffmpeg_version" in job:
                job["ffmpeg_version"] = "__FFMPEG_VERSION__"
            commands = job.get("ffmpeg_commands")
            if not isinstance(commands, list):
                continue
            for command in commands:
                if not isinstance(command, dict):
                    continue
                args = command.get("args")
                if isinstance(args, list) and args:
                    args[0] = "__FFMPEG_BIN__"
    return normalized


def _normalize_qa_payload_for_regression(payload: dict[str, Any], *, repo_root_posix: str) -> dict[str, Any]:
    normalized = _normalize_strings_for_regression(payload, repo_root_posix=repo_root_posix)
    if not isinstance(normalized, dict):
        return {}
    for key in ("run_id",):
        if key in normalized:
            normalized[key] = f"__{key.upper()}__"
    return normalized


# ---------------------------------------------------------------------------
# main regeneration logic
# ---------------------------------------------------------------------------

def main_regen() -> int:
    fixture_dir = REPO_ROOT / "tests" / "fixtures" / "plugin_chain_registry_dispatch"
    case_dir = REPO_ROOT / "sandbox_tmp" / "plugin_chain_registry_baseline"
    shutil.rmtree(case_dir, ignore_errors=True)
    case_dir.mkdir(parents=True, exist_ok=True)

    try:
        stems_dir = case_dir / "stems"
        source_path = stems_dir / "mix.wav"
        _write_pcm16_registry_baseline_wav(source_path)

        scene_path = case_dir / "scene.json"
        request_path = case_dir / "render_request.json"
        plan_out = case_dir / "render_plan.json"
        report_out = case_dir / "render_report.json"
        event_log_out = case_dir / "event_log.jsonl"
        execute_out = case_dir / "render_execute.json"
        qa_out = case_dir / "render_qa.json"

        _write_json(scene_path, {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.PLUGIN.REGISTRY.BASELINE",
            "source": {"stems_dir": stems_dir.resolve().as_posix(), "created_from": "analyze"},
            "objects": [],
            "beds": [{"bed_id": "BED.FIELD.001", "label": "Field", "kind": "field",
                       "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []}, "notes": []}],
            "metadata": {},
        })
        _write_json(request_path, {
            "schema_version": "0.1.0",
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path.resolve().as_posix(),
            "options": {
                "dry_run": False,
                "max_theoretical_quality": True,
                "plugin_chain": [
                    {"plugin_id": "gain_v0", "params": {"gain_db": -2.5, "macro_mix": 100.0}},
                    {"plugin_id": "tilt_eq_v0", "params": {"tilt_db": 2.0, "pivot_hz": 1000.0, "macro_mix": 100.0, "bypass": False}},
                    {"plugin_id": "simple_compressor_v0", "params": {"threshold_db": -24.0, "ratio": 6.0, "attack_ms": 3.0, "release_ms": 120.0, "makeup_db": 0.0, "detector_mode": "rms", "macro_mix": 100.0, "bypass": False}},
                    {"plugin_id": "multiband_compressor_v0", "params": {"threshold_db": -26.0, "ratio": 5.0, "attack_ms": 8.0, "release_ms": 180.0, "makeup_db": 0.0, "lookahead_ms": 2.0, "detector_mode": "rms", "slope_sensitivity": 0.8, "min_band_count": 3, "max_band_count": 5, "oversampling": 1, "macro_mix": 100.0, "bypass": False}},
                    {"plugin_id": "multiband_expander_v0", "params": {"threshold_db": -26.0, "ratio": 5.0, "attack_ms": 8.0, "release_ms": 180.0, "makeup_db": 0.0, "lookahead_ms": 2.0, "detector_mode": "rms", "slope_sensitivity": 0.8, "min_band_count": 3, "max_band_count": 5, "oversampling": 1, "macro_mix": 100.0, "bypass": False}},
                    {"plugin_id": "multiband_dynamic_auto_v0", "params": {"threshold_db": -26.0, "ratio": 5.0, "attack_ms": 8.0, "release_ms": 180.0, "makeup_db": 0.0, "lookahead_ms": 2.0, "detector_mode": "rms", "slope_sensitivity": 0.8, "min_band_count": 3, "max_band_count": 5, "oversampling": 1, "macro_mix": 100.0, "bypass": False}},
                ],
            },
        })

        stderr_capture = StringIO()
        stdout_capture = StringIO()
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exit_code = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out),
                "--report-out", str(report_out),
                "--event-log-out", str(event_log_out),
                "--execute-out", str(execute_out),
                "--qa-out", str(qa_out),
            ])

        if exit_code != 0:
            print(f"render-run failed (exit {exit_code}):", file=sys.stderr)
            print(stderr_capture.getvalue(), file=sys.stderr)
            return 1

        report = json.loads(report_out.read_text(encoding="utf-8"))
        rendered_path = Path(report["jobs"][0]["output_files"][0]["file_path"])
        repo_root_posix = REPO_ROOT.resolve().as_posix()

        # --- event log ---
        canonical_event = _canonical_event_log_bytes(
            event_log_out.read_bytes(), repo_root_posix=repo_root_posix
        )
        # Write back as raw JSONL (one line per event, space-separated as original)
        # The fixture is stored as the RAW event log (not canonicalized), so we write it directly.
        fixture_dir.mkdir(parents=True, exist_ok=True)
        (fixture_dir / "expected_event_log.jsonl").write_bytes(event_log_out.read_bytes())

        # --- wav ---
        shutil.copy2(rendered_path, fixture_dir / "expected_output.wav")

        # --- execute payload ---
        execute_payload = json.loads(execute_out.read_text(encoding="utf-8"))
        (fixture_dir / "expected_render_execute.json").write_text(
            json.dumps(execute_payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        # --- qa payload ---
        qa_payload = json.loads(qa_out.read_text(encoding="utf-8"))
        (fixture_dir / "expected_render_qa.json").write_text(
            json.dumps(qa_payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        print(f"Fixtures regenerated in: {fixture_dir.as_posix()}")
        print(f"  expected_event_log.jsonl ({(fixture_dir / 'expected_event_log.jsonl').stat().st_size} bytes)")
        print(f"  expected_output.wav      ({(fixture_dir / 'expected_output.wav').stat().st_size} bytes)")
        print(f"  expected_render_execute.json")
        print(f"  expected_render_qa.json")
        return 0

    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main_regen())
