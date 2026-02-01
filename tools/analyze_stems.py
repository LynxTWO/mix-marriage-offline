from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_command(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _run_scan_session(
    tools_dir: Path,
    stems_dir: Path,
    report_path: Path,
    schema: str | None,
    meters: str | None,
    include_peak: bool,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "scan_session.py"),
        str(stems_dir),
        "--out",
        str(report_path),
    ]
    if schema:
        command.extend(["--schema", schema])
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    return _run_command(command)


def _run_pipeline(
    tools_dir: Path,
    report_path: Path,
    output_path: Path,
    plugins_dir: str,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "run_pipeline.py"),
        "--report",
        str(report_path),
        "--plugins",
        plugins_dir,
        "--out",
        str(output_path),
    ]
    return _run_command(command)


def _run_export_report(
    tools_dir: Path,
    report_path: Path,
    csv_path: str | None,
    pdf_path: str | None,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "export_report.py"),
        "--report",
        str(report_path),
    ]
    if csv_path:
        command.extend(["--csv", csv_path])
    if pdf_path:
        command.extend(["--pdf", pdf_path])
    if len(command) == 4:
        return 0
    return _run_command(command)


def _scan_report_path(out_report: Path) -> Path:
    return out_report.with_name(f"{out_report.stem}.scan{out_report.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan stems, run the plugin pipeline, and export report artifacts."
    )
    parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    parser.add_argument(
        "--out-report",
        required=True,
        help="Path to the output report JSON after running the pipeline.",
    )
    parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to the plugins directory.",
    )
    parser.add_argument(
        "--schema",
        default="schemas/report.schema.json",
        help="Optional report schema path for scan validation.",
    )
    parser.add_argument(
        "--meters",
        choices=["basic"],
        default="basic",
        help="Enable additional meter packs (basic).",
    )
    parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )
    parser.add_argument("--csv", default=None, help="Optional output CSV path.")
    parser.add_argument("--pdf", default=None, help="Optional output PDF path.")
    args = parser.parse_args()

    tools_dir = Path(__file__).resolve().parent
    stems_dir = Path(args.stems_dir)
    out_report = Path(args.out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    scan_report = _scan_report_path(out_report)

    exit_code = _run_scan_session(
        tools_dir,
        stems_dir,
        scan_report,
        args.schema,
        args.meters,
        args.peak,
    )
    if exit_code != 0:
        return exit_code

    exit_code = _run_pipeline(
        tools_dir,
        scan_report,
        out_report,
        args.plugins,
    )
    if exit_code != 0:
        return exit_code

    exit_code = _run_export_report(
        tools_dir,
        out_report,
        args.csv,
        args.pdf,
    )
    if exit_code != 0:
        return exit_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
