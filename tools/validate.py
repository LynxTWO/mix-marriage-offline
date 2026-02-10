"""Cross-platform wrapper for repository contract validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATE_CONTRACTS = SCRIPT_DIR / "validate_contracts.py"


def main() -> int:
    if not VALIDATE_CONTRACTS.is_file():
        print(
            f"validate.py: missing validator script at {VALIDATE_CONTRACTS}",
            file=sys.stderr,
        )
        return 2

    command = [sys.executable, str(VALIDATE_CONTRACTS), *sys.argv[1:]]
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"validate.py: failed to launch validator: {exc}", file=sys.stderr)
        return 2

    if completed.returncode == 0:
        print("validate.py: validation passed.", file=sys.stderr)
    else:
        print(
            f"validate.py: validation failed (exit code {completed.returncode}).",
            file=sys.stderr,
        )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
