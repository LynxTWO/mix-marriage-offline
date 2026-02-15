from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.tools import analyze_stems as _impl


main = _impl.main


def _run_command(command: list[str]) -> int:
    return _impl._run_command(command)


def _run_pipeline(
    tools_dir: Path,
    report_path: Path,
    output_path: Path,
    plugins_dir: str,
    profile_id: str,
) -> int:
    del tools_dir
    command = [
        sys.executable,
        "-m",
        "mmo.tools.run_pipeline",
        "--report",
        str(report_path),
        "--plugins",
        plugins_dir,
        "--out",
        str(output_path),
    ]
    if profile_id:
        command.extend(["--profile", profile_id])
    return _run_command(command)


if __name__ == "__main__":
    raise SystemExit(main())
