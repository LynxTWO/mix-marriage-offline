"""Validate plugin UI contracts across ui_layout + x_mmo_ui hints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SRC_DIR = SCRIPT_REPO_ROOT / "src"
if str(SCRIPT_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_SRC_DIR))

from mmo.core.plugin_ui_contract import (  # noqa: E402
    build_plugin_ui_contract_lint_payload,
    plugin_ui_contract_has_errors,
)

_ISSUE_VALIDATION_FAILED = "ISSUE.UI.PLUGIN.LINT_FAILED"


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _error_payload(*, plugins_dir: Path, message: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "plugins_dir": plugins_dir.resolve().as_posix(),
        "plugin_count": 0,
        "issue_counts": {"error": 1, "warn": 0},
        "ok": False,
        "plugins": [],
        "issues": [
            {
                "plugin_id": "",
                "issue_id": _ISSUE_VALIDATION_FAILED,
                "severity": "error",
                "message": message,
                "evidence": {"plugins_dir": plugins_dir.resolve().as_posix()},
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate plugin UI contracts (ui_layout + x_mmo_ui)."
    )
    parser.add_argument(
        "--repo-root",
        default=str(SCRIPT_REPO_ROOT),
        help="Repository root containing plugins/ and src/.",
    )
    parser.add_argument(
        "--plugins",
        default="plugins",
        help="Path to plugins directory (absolute or relative to --repo-root).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    plugins_dir = _resolve_path(args.plugins, repo_root=repo_root)

    try:
        payload = build_plugin_ui_contract_lint_payload(plugins_dir=plugins_dir)
    except (RuntimeError, ValueError, OSError) as exc:
        payload = _error_payload(plugins_dir=plugins_dir, message=str(exc))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if plugin_ui_contract_has_errors(payload) else 0


if __name__ == "__main__":
    raise SystemExit(main())
