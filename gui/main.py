"""Repo launcher for the packaged MMO CustomTkinter GUI entrypoint."""

from __future__ import annotations

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
    from mmo.gui.main import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())

