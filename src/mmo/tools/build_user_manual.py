"""Install-safe CLI entry point for the MMO User Manual PDF builder.

Usage::

    python -m mmo.tools.build_user_manual --out out/MMO_User_Manual.pdf
    python -m mmo.tools.build_user_manual \\
        --manifest docs/manual/manual.yaml \\
        --out sandbox_tmp/manual/MMO_User_Manual.pdf \\
        --strict

Exit codes:
    0  — PDF written successfully.
    1  — Build error (bad manifest, missing chapters in strict mode, etc.).
    2  — reportlab or PyYAML not installed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path | None:
    """Walk parents until pyproject.toml or docs/manual/manual.yaml is found."""
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
        if (parent / "docs" / "manual" / "manual.yaml").is_file():
            return parent
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the MMO User Manual PDF from docs/manual/manual.yaml.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Path to manual.yaml. "
            "Defaults to docs/manual/manual.yaml relative to the repository root."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output PDF path.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail immediately if any chapter file referenced in the manifest is missing.",
    )
    parser.add_argument(
        "--version",
        default=None,
        dest="version_override",
        help="Override the version string shown on the title page.",
    )
    args = parser.parse_args()

    # Resolve manifest path
    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
    else:
        # Auto-discover from this file's location or cwd
        repo_root = _find_repo_root(Path(__file__).resolve()) or _find_repo_root(Path.cwd())
        if repo_root is None:
            print(
                "ERROR: Cannot locate repository root (no pyproject.toml found). "
                "Use --manifest to specify the path explicitly.",
                file=sys.stderr,
            )
            return 1
        manifest_path = repo_root / "docs" / "manual" / "manual.yaml"

    out_path = Path(args.out).resolve()

    try:
        from mmo.exporters.pdf_manual import build_manual_pdf  # noqa: PLC0415
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        build_manual_pdf(
            manifest_path,
            out_path,
            strict=args.strict,
            version_override=args.version_override,
        )
    except ImportError as exc:
        print(f"ERROR: missing dependency — {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: PDF build failed — {exc}", file=sys.stderr)
        return 1

    print(f"Manual PDF written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
