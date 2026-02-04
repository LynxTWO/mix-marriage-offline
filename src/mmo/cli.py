from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run_command(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _run_scan(
    tools_dir: Path,
    stems_dir: Path,
    out_path: Path,
    meters: str | None,
    include_peak: bool,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "scan_session.py"),
        str(stems_dir),
        "--out",
        str(out_path),
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    return _run_command(command)


def _run_analyze(
    tools_dir: Path,
    stems_dir: Path,
    out_report: Path,
    meters: str | None,
    include_peak: bool,
    plugins_dir: str,
    keep_scan: bool,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "analyze_stems.py"),
        str(stems_dir),
        "--out-report",
        str(out_report),
        "--plugins",
        plugins_dir,
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    if keep_scan:
        command.append("--keep-scan")
    return _run_command(command)


def _run_export(
    tools_dir: Path,
    report_path: Path,
    csv_path: str | None,
    pdf_path: str | None,
    *,
    no_measurements: bool,
    no_gates: bool,
    truncate_values: int,
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
    if no_measurements:
        command.append("--no-measurements")
    if no_gates:
        command.append("--no-gates")
    if truncate_values != 200:
        command.extend(["--truncate-values", str(truncate_values)])
    if len(command) == 4:
        return 0
    return _run_command(command)


def _load_report(report_path: Path) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON must be an object.")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MMO command-line tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan stems and write a report JSON.")
    scan_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    scan_parser.add_argument("--out", required=True, help="Path to output report JSON.")
    scan_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    scan_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run scan + pipeline + exports for a stems directory."
    )
    analyze_parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
    analyze_parser.add_argument(
        "--out-report",
        required=True,
        help="Path to the output report JSON after running the pipeline.",
    )
    analyze_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default=None,
        help="Enable additional meter packs (basic or truth).",
    )
    analyze_parser.add_argument(
        "--peak",
        action="store_true",
        help="Compute WAV sample peak meter readings for stems.",
    )
    analyze_parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to the plugins directory.",
    )
    analyze_parser.add_argument(
        "--keep-scan",
        action="store_true",
        help="Keep the intermediate scan report JSON instead of deleting it.",
    )

    export_parser = subparsers.add_parser(
        "export", help="Export CSV/PDF artifacts from a report JSON."
    )
    export_parser.add_argument("--report", required=True, help="Path to report JSON.")
    export_parser.add_argument("--csv", default=None, help="Optional output CSV path.")
    export_parser.add_argument("--pdf", default=None, help="Optional output PDF path.")
    export_parser.add_argument(
        "--no-measurements",
        action="store_true",
        help="Omit Measurements section from PDF output.",
    )
    export_parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Omit gate fields/sections from exports.",
    )
    export_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF cell values to this length.",
    )

    downmix_parser = subparsers.add_parser("downmix", help="Downmix policy tools.")
    downmix_subparsers = downmix_parser.add_subparsers(dest="downmix_command", required=True)
    downmix_show_parser = downmix_subparsers.add_parser(
        "show", help="Resolve and display a downmix matrix."
    )
    downmix_show_parser.add_argument(
        "--source",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_show_parser.add_argument(
        "--target",
        required=True,
        help="Target layout ID (e.g., LAYOUT.2_0).",
    )
    downmix_show_parser.add_argument(
        "--policy",
        default=None,
        help="Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0).",
    )
    downmix_show_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format for the resolved matrix.",
    )
    downmix_show_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout.",
    )
    downmix_qa_parser = downmix_subparsers.add_parser(
        "qa", help="Compare folded downmix against a stereo reference."
    )
    downmix_qa_parser.add_argument(
        "--src",
        required=True,
        help="Path to the multichannel source file.",
    )
    downmix_qa_parser.add_argument(
        "--ref",
        required=True,
        help="Path to the stereo reference file.",
    )
    downmix_qa_parser.add_argument(
        "--source-layout",
        required=True,
        help="Source layout ID (e.g., LAYOUT.5_1).",
    )
    downmix_qa_parser.add_argument(
        "--policy",
        default=None,
        help="Optional policy ID override (e.g., POLICY.DOWNMIX.STANDARD_FOLDOWN_V0).",
    )
    downmix_qa_parser.add_argument(
        "--meters",
        choices=["basic", "truth"],
        default="truth",
        help="Meter pack to use (basic or truth).",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-lufs",
        type=float,
        default=1.0,
        help="LUFS delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-true-peak",
        type=float,
        default=1.0,
        help="True peak delta tolerance (dBTP) for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--tolerance-corr",
        type=float,
        default=0.15,
        help="Correlation delta tolerance for QA warnings.",
    )
    downmix_qa_parser.add_argument(
        "--max-seconds",
        type=float,
        default=120.0,
        help="Maximum overlap seconds to compare (<= 0 disables the cap).",
    )
    downmix_qa_parser.add_argument(
        "--format",
        choices=["json", "csv", "pdf"],
        default="json",
        help="Output format for downmix QA results.",
    )
    downmix_qa_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path; defaults to stdout for json/csv.",
    )
    downmix_qa_parser.add_argument(
        "--truncate-values",
        type=int,
        default=200,
        help="Truncate PDF values to this length.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    tools_dir = repo_root / "tools"

    if args.command == "scan":
        return _run_scan(
            tools_dir,
            Path(args.stems_dir),
            Path(args.out),
            args.meters,
            args.peak,
        )
    if args.command == "analyze":
        return _run_analyze(
            tools_dir,
            Path(args.stems_dir),
            Path(args.out_report),
            args.meters,
            args.peak,
            args.plugins,
            args.keep_scan,
        )
    if args.command == "export":
        return _run_export(
            tools_dir,
            Path(args.report),
            args.csv,
            args.pdf,
            no_measurements=args.no_measurements,
            no_gates=args.no_gates,
            truncate_values=args.truncate_values,
        )
    if args.command == "downmix":
        from mmo.dsp.downmix import (  # noqa: WPS433
            render_matrix,
            resolve_downmix_matrix,
        )
        from mmo.core.downmix_qa import run_downmix_qa  # noqa: WPS433
        from mmo.exporters.downmix_qa_csv import (  # noqa: WPS433
            export_downmix_qa_csv,
            render_downmix_qa_csv,
        )
        from mmo.exporters.downmix_qa_pdf import export_downmix_qa_pdf  # noqa: WPS433

        if args.downmix_command == "qa":
            try:
                report = run_downmix_qa(
                    Path(args.src),
                    Path(args.ref),
                    source_layout_id=args.source_layout,
                    policy_id=args.policy,
                    tolerance_lufs=args.tolerance_lufs,
                    tolerance_true_peak_db=args.tolerance_true_peak,
                    tolerance_corr=args.tolerance_corr,
                    repo_root=repo_root,
                    meters=args.meters,
                    max_seconds=args.max_seconds,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

            if args.format == "json":
                output = json.dumps(report, indent=2, sort_keys=True) + "\n"
                if args.out:
                    out_path = Path(args.out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(output, encoding="utf-8")
                else:
                    print(output, end="")
            elif args.format == "csv":
                if args.out:
                    export_downmix_qa_csv(report, Path(args.out))
                else:
                    print(render_downmix_qa_csv(report), end="")
            elif args.format == "pdf":
                out_path = Path(args.out) if args.out else Path.cwd() / "downmix_qa.pdf"
                export_downmix_qa_pdf(
                    report,
                    out_path,
                    truncate_values=args.truncate_values,
                )
            else:
                print(f"Unsupported format: {args.format}", file=sys.stderr)
                return 2

            issues = report.get("downmix_qa", {}).get("issues", [])
            has_error = any(
                isinstance(issue, dict) and issue.get("severity", 0) >= 80
                for issue in issues
            )
            return 1 if has_error else 0

        if args.downmix_command != "show":
            print("Unknown downmix command.", file=sys.stderr)
            return 2

        layouts_path = repo_root / "ontology" / "layouts.yaml"
        registry_path = repo_root / "ontology" / "policies" / "downmix.yaml"
        try:
            matrix = resolve_downmix_matrix(
                repo_root=repo_root,
                source_layout_id=args.source,
                target_layout_id=args.target,
                policy_id=args.policy,
                layouts_path=layouts_path,
                registry_path=registry_path,
            )
            output = render_matrix(matrix, output_format=args.format)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0

    return 0
