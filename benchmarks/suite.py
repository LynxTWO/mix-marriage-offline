#!/usr/bin/env python3
"""MMO v1.1 benchmark suite.

This suite is intentionally stdlib-only so it runs on Linux, macOS, and
Windows without extra dependencies.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


Runner = Callable[[Path, dict[str, str], Path], None]


@dataclasses.dataclass(frozen=True)
class BenchmarkCase:
    """Single benchmark case definition."""

    case_id: str
    description: str
    default_runs: int
    runner: Runner


def _run_command(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    """Execute one command and raise on non-zero exit."""
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=cwd,
        env=env,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Benchmark command failed: "
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\n"
            + f"stderr:\n{completed.stderr}"
        )


def _make_cli_runner(python_cmd: str, argv_tail: list[str]) -> Runner:
    """Create a subprocess runner for one CLI command."""
    command = [python_cmd, "-m", "mmo"] + argv_tail

    def _runner(repo_root: Path, env: dict[str, str], _temp_root: Path) -> None:
        _run_command(command, cwd=repo_root, env=env)

    return _runner


def _make_harness_runner(python_cmd: str) -> Runner:
    """Create a subprocess runner for the self-dogfood harness benchmark."""

    def _runner(repo_root: Path, env: dict[str, str], temp_root: Path) -> None:
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=temp_root,
            prefix="bench_harness_",
        ) as td:
            out_dir = Path(td) / "out"
            command = [
                python_cmd,
                "-m",
                "tools.agent.run",
                "graph-only",
                "--root",
                "tools/agent",
                "--out",
                str(out_dir),
                "--no-contract-stamp",
                "--no-index",
                "--max-file-reads",
                "200",
                "--max-total-lines",
                "50000",
            ]
            _run_command(command, cwd=repo_root, env=env)

    return _runner


def _percentile(sorted_values: list[int], percent: float) -> float:
    """Linear percentile interpolation in nanoseconds."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (percent / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    lower_value = float(sorted_values[lower])
    upper_value = float(sorted_values[upper])
    return lower_value + ((upper_value - lower_value) * fraction)


def _stats_from_ns(samples_ns: list[int]) -> dict[str, float]:
    """Convert timing samples (ns) into stable ms metrics."""
    sorted_ns = sorted(samples_ns)
    mean_ns = statistics.fmean(samples_ns)
    median_ns = statistics.median(sorted_ns)
    p95_ns = _percentile(sorted_ns, 95.0)
    to_ms = lambda value_ns: round(value_ns / 1_000_000.0, 3)
    return {
        "max_ms": to_ms(float(sorted_ns[-1])),
        "mean_ms": to_ms(float(mean_ns)),
        "median_ms": to_ms(float(median_ns)),
        "min_ms": to_ms(float(sorted_ns[0])),
        "p95_ms": to_ms(float(p95_ns)),
    }


def _run_case(
    case: BenchmarkCase,
    repo_root: Path,
    env: dict[str, str],
    temp_root: Path,
    warmup_runs: int,
    run_count: int,
) -> dict[str, object]:
    """Run one case and return its benchmark summary payload."""
    for _ in range(warmup_runs):
        case.runner(repo_root, env, temp_root)

    samples_ns: list[int] = []
    for _ in range(run_count):
        start_ns = time.perf_counter_ns()
        case.runner(repo_root, env, temp_root)
        end_ns = time.perf_counter_ns()
        samples_ns.append(end_ns - start_ns)

    return {
        "case_id": case.case_id,
        "description": case.description,
        "runs": run_count,
        "warmup_runs": warmup_runs,
        "metrics_ms": _stats_from_ns(samples_ns),
    }


def _resolve_cases(
    python_cmd: str,
    case_filter: set[str],
) -> list[BenchmarkCase]:
    """Build case list, optionally filtered by explicit IDs."""
    cases = [
        BenchmarkCase(
            case_id="cli.roles.list_json",
            description="`mmo roles list --format json`",
            default_runs=12,
            runner=_make_cli_runner(
                python_cmd,
                ["roles", "list", "--format", "json"],
            ),
        ),
        BenchmarkCase(
            case_id="cli.targets.list_json",
            description="`mmo targets list --format json`",
            default_runs=12,
            runner=_make_cli_runner(
                python_cmd,
                ["targets", "list", "--format", "json"],
            ),
        ),
        BenchmarkCase(
            case_id="cli.downmix.list_json",
            description="`mmo downmix list --format json`",
            default_runs=10,
            runner=_make_cli_runner(
                python_cmd,
                ["downmix", "list", "--format", "json"],
            ),
        ),
        BenchmarkCase(
            case_id="harness.graph_only.tools_agent",
            description="`tools.agent.run graph-only --root tools/agent`",
            default_runs=3,
            runner=_make_harness_runner(python_cmd),
        ),
    ]
    if not case_filter:
        return cases
    known_ids = {case.case_id for case in cases}
    unknown_ids = sorted(case_filter - known_ids)
    if unknown_ids:
        raise ValueError(
            "Unknown case id(s): " + ", ".join(unknown_ids)
        )
    return [case for case in cases if case.case_id in case_filter]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MMO v1.1 benchmark suite.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=0,
        help=(
            "Override run count for every case. "
            "Use 0 to keep per-case defaults."
        ),
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=1,
        help="Warmup iterations per case before measurements.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run only this case id (repeatable).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output JSON file path.",
    )
    parser.add_argument(
        "--temp-root",
        type=Path,
        default=None,
        help=(
            "Directory for temporary benchmark artifacts. "
            "Defaults to sandbox_tmp/benchmarks."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.runs < 0:
        raise ValueError("--runs must be >= 0")
    if args.warmup_runs < 0:
        raise ValueError("--warmup-runs must be >= 0")

    repo_root = Path(__file__).resolve().parents[1]
    python_cmd = os.fspath(os.getenv("PYTHON", "") or sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")

    case_filter = set(args.case)
    cases = _resolve_cases(python_cmd, case_filter)

    temp_root = args.temp_root
    if temp_root is None:
        temp_root = repo_root / "sandbox_tmp" / "benchmarks"
    if not temp_root.is_absolute():
        temp_root = repo_root / temp_root

    case_payloads = []
    for case in cases:
        run_count = args.runs if args.runs > 0 else case.default_runs
        payload = _run_case(
            case=case,
            repo_root=repo_root,
            env=env,
            temp_root=temp_root,
            warmup_runs=args.warmup_runs,
            run_count=run_count,
        )
        case_payloads.append(payload)

    total_runs = sum(int(item["runs"]) for item in case_payloads)
    payload = {
        "suite_version": "1.1.0",
        "cases": case_payloads,
        "summary": {
            "case_count": len(case_payloads),
            "total_runs": total_runs,
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is None:
        print(rendered)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote benchmark results: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
