"""Benchmark plugin-chain precision modes for render-run.

Compares default mixed-precision mode (float32 buffers + float64 biquad math)
against max-theoretical-quality mode (float64 plugin-chain buffers).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import shutil
import statistics
import struct
import sys
import time
import uuid
import wave
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SRC_DIR = SCRIPT_REPO_ROOT / "src"
if str(SCRIPT_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_SRC_DIR))

from mmo.cli import main  # noqa: E402
from mmo.dsp.io import sha256_file  # noqa: E402
from mmo.resources import temp_dir  # noqa: E402


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _create_benchmark_temp_root() -> Path:
    base_root = temp_dir()
    base_root.mkdir(parents=True, exist_ok=True)
    for _ in range(128):
        candidate = base_root / f"benchmark_render_precision_{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(
        "Unable to allocate benchmark temporary directory under "
        f"{base_root.resolve().as_posix()}."
    )


def _write_pcm16_two_tone_wav(
    path: Path,
    *,
    channels: int = 2,
    sample_rate_hz: int = 48000,
    duration_s: float = 1.0,
    low_hz: float = 160.0,
    high_hz: float = 6000.0,
) -> None:
    frames = max(1, int(sample_rate_hz * duration_s))
    samples: list[int] = []
    for frame_index in range(frames):
        low_value = math.sin(2.0 * math.pi * low_hz * frame_index / sample_rate_hz)
        high_value = math.sin(2.0 * math.pi * high_hz * frame_index / sample_rate_hz)
        mixed = int(0.2 * 32767.0 * low_value + 0.2 * 32767.0 * high_value)
        for _ in range(channels):
            samples.append(mixed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _scene_payload(stems_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.BENCH.PRECISION",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "render",
        },
        "objects": [],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _request_payload(*, scene_path: Path, max_theoretical_quality: bool) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.2_0",
        "scene_path": scene_path.resolve().as_posix(),
        "options": {
            "dry_run": False,
            "max_theoretical_quality": max_theoretical_quality,
            "plugin_chain": [
                {
                    "plugin_id": "tilt_eq_v0",
                    "params": {
                        "tilt_db": 4.0,
                        "pivot_hz": 1000.0,
                        "macro_mix": 100.0,
                        "bypass": False,
                    },
                }
            ],
        },
    }


def _run_render_once(
    *,
    request_path: Path,
    scene_path: Path,
    plan_out: Path,
    report_out: Path,
) -> tuple[float, dict[str, Any]]:
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    start = time.perf_counter()
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        exit_code = main(
            [
                "render-run",
                "--request",
                str(request_path),
                "--scene",
                str(scene_path),
                "--plan-out",
                str(plan_out),
                "--report-out",
                str(report_out),
                "--force",
            ]
        )
    elapsed_s = time.perf_counter() - start
    if exit_code != 0:
        raise RuntimeError(
            "render-run failed: "
            + stderr_capture.getvalue().strip()
        )
    report = json.loads(report_out.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise RuntimeError("render-run report is not an object.")
    return elapsed_s, report


def _mode_summary(
    *,
    mode_name: str,
    durations_s: list[float],
    output_hashes: list[str],
    precision_notes: list[str],
) -> dict[str, Any]:
    mean_s = statistics.fmean(durations_s)
    median_s = statistics.median(durations_s)
    min_s = min(durations_s)
    max_s = max(durations_s)
    unique_hashes = sorted(set(output_hashes))
    unique_notes = sorted(set(precision_notes))
    return {
        "mode": mode_name,
        "iterations": len(durations_s),
        "durations_s": durations_s,
        "mean_s": mean_s,
        "median_s": median_s,
        "min_s": min_s,
        "max_s": max_s,
        "deterministic_within_mode": len(unique_hashes) == 1,
        "output_sha256": unique_hashes,
        "precision_notes": unique_notes,
    }


def _run_precision_mode(
    *,
    temp_root: Path,
    scene_path: Path,
    max_theoretical_quality: bool,
    iterations: int,
) -> dict[str, Any]:
    mode_name = "float64" if max_theoretical_quality else "float32"
    durations_s: list[float] = []
    output_hashes: list[str] = []
    precision_notes: list[str] = []

    request_path = temp_root / "render_request.json"
    plan_out = temp_root / "render_plan.json"
    report_out = temp_root / "render_report.json"

    for _ in range(iterations):
        _write_json(
            request_path,
            _request_payload(
                scene_path=scene_path,
                max_theoretical_quality=max_theoretical_quality,
            ),
        )
        elapsed_s, report = _run_render_once(
            request_path=request_path,
            scene_path=scene_path,
            plan_out=plan_out,
            report_out=report_out,
        )
        durations_s.append(elapsed_s)

        jobs = report.get("jobs")
        if not isinstance(jobs, list) or not jobs or not isinstance(jobs[0], dict):
            raise RuntimeError("render-run report jobs are missing.")
        output_files = jobs[0].get("output_files")
        if not isinstance(output_files, list) or not output_files or not isinstance(output_files[0], dict):
            raise RuntimeError("render-run report output_files are missing.")
        output_path = Path(str(output_files[0].get("file_path", "")))
        if not output_path.is_file():
            raise RuntimeError(f"Rendered output file missing: {output_path}")
        output_hashes.append(sha256_file(output_path))

        notes = jobs[0].get("notes")
        if isinstance(notes, list):
            for raw_note in notes:
                if not isinstance(raw_note, str):
                    continue
                if raw_note.startswith("plugin_chain_precision_mode: "):
                    precision_notes.append(raw_note)

    return _mode_summary(
        mode_name=mode_name,
        durations_s=durations_s,
        output_hashes=output_hashes,
        precision_notes=precision_notes,
    )


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark render-run plugin-chain precision modes "
            "(default float32 vs max theoretical quality float64)."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of render-run executions per precision mode.",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=3.0,
        help="Fixture audio duration in seconds.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args()


def main_cli() -> int:
    args = _build_args()
    if args.iterations < 1:
        print("--iterations must be >= 1", file=sys.stderr)
        return 2
    if args.duration_s <= 0:
        print("--duration-s must be > 0", file=sys.stderr)
        return 2

    temp_root = _create_benchmark_temp_root()
    try:
        stems_dir = temp_root / "stems"
        source_path = stems_dir / "mix.wav"
        _write_pcm16_two_tone_wav(
            source_path,
            duration_s=float(args.duration_s),
        )

        scene_path = temp_root / "scene.json"
        _write_json(scene_path, _scene_payload(stems_dir))

        float32_summary = _run_precision_mode(
            temp_root=temp_root,
            scene_path=scene_path,
            max_theoretical_quality=False,
            iterations=int(args.iterations),
        )
        float64_summary = _run_precision_mode(
            temp_root=temp_root,
            scene_path=scene_path,
            max_theoretical_quality=True,
            iterations=int(args.iterations),
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    mean32 = float(float32_summary["mean_s"])
    mean64 = float(float64_summary["mean_s"])
    ratio = (mean64 / mean32) if mean32 > 0 else None
    summary: dict[str, Any] = {
        "ok": True,
        "iterations": int(args.iterations),
        "duration_s": float(args.duration_s),
        "modes": [float32_summary, float64_summary],
        "ratio_float64_over_float32_mean": ratio,
    }

    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print("Render Precision Benchmark")
    print(f"- iterations: {summary['iterations']}")
    print(f"- duration_s: {summary['duration_s']}")
    print("")
    for mode in summary["modes"]:
        print(f"[{mode['mode']}]")
        print(f"  mean_s: {mode['mean_s']:.6f}")
        print(f"  median_s: {mode['median_s']:.6f}")
        print(f"  min_s: {mode['min_s']:.6f}")
        print(f"  max_s: {mode['max_s']:.6f}")
        print(f"  deterministic_within_mode: {mode['deterministic_within_mode']}")
        print(f"  output_sha256: {', '.join(mode['output_sha256'])}")
        if mode["precision_notes"]:
            print(f"  precision_notes: {', '.join(mode['precision_notes'])}")
        print("")
    if ratio is not None:
        print(f"float64/float32 mean ratio: {ratio:.3f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
