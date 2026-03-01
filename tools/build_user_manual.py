#!/usr/bin/env python3
"""Repo-root developer wrapper: build the MMO User Manual PDF.

Delegates to ``python -m mmo.tools.build_user_manual`` with src/ on the path,
so this script works from a repo checkout without a full package install.

Usage::

    python tools/build_user_manual.py --out sandbox_tmp/manual/MMO_User_Manual.pdf
    python tools/build_user_manual.py \\
        --manifest docs/manual/manual.yaml \\
        --out sandbox_tmp/manual/MMO_User_Manual.pdf \\
        --strict
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"


def main() -> int:
    env = os.environ.copy()
    # Prepend src/ to PYTHONPATH so mmo.* imports resolve in checkout mode
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(SRC_DIR)

    result = subprocess.run(
        [sys.executable, "-m", "mmo.tools.build_user_manual", *sys.argv[1:]],
        env=env,
        cwd=str(REPO_ROOT),
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
