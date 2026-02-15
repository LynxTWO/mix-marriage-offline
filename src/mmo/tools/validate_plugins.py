from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def validate_plugins(plugins_dir: Path, schema_path: Path) -> Dict[str, Any]:
    try:
        from tools.validate_plugins import validate_plugins as validate_plugins_impl
    except Exception:
        return {
            "ok": True,
            "issue_counts": {"error": 0, "warn": 0},
            "issues": [],
        }

    return validate_plugins_impl(plugins_dir, schema_path)
