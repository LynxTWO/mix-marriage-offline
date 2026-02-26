"""Repo launcher for the packaged MMO visualization dashboard internals."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _bootstrap_src_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if src_dir.exists():
        src_text = str(src_dir)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)


def main() -> int:
    _bootstrap_src_path()
    from mmo.gui.dashboard import (
        build_visualization_frame,
        default_dashboard_telemetry,
        frame_signature,
    )

    telemetry = default_dashboard_telemetry()
    frame = build_visualization_frame(telemetry, tick=0)
    print(
        json.dumps(
            {
                "layout_id": telemetry.layout_id,
                "layout_standard": telemetry.layout_standard,
                "frame_signature": frame_signature(frame),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
