"""Validate UI screen example JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _load_example(path: Path) -> dict[str, Any]:
    from mmo.core.ui_screen_examples import load_ui_screen_example  # noqa: WPS433

    return load_ui_screen_example(path)


def validate_ui_examples(*, examples_dir: Path, repo_root: Path) -> dict[str, Any]:
    failures: list[dict[str, str]] = []

    if not examples_dir.exists():
        failures.append(
            {
                "file": str(examples_dir),
                "error": "Examples directory does not exist.",
            }
        )
        return {"ok": False, "count": 0, "failures": failures}

    if not examples_dir.is_dir():
        failures.append(
            {
                "file": str(examples_dir),
                "error": "Examples path is not a directory.",
            }
        )
        return {"ok": False, "count": 0, "failures": failures}

    example_paths = sorted(examples_dir.glob("*.json"), key=lambda path: path.name)
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    for path in example_paths:
        try:
            _load_example(path)
        except (RuntimeError, ValueError) as exc:
            failures.append({"file": path.name, "error": str(exc)})

    return {
        "ok": not failures,
        "count": len(example_paths),
        "failures": failures,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Validate UI screen examples.")
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing examples/ and schemas/.",
    )
    parser.add_argument(
        "--examples-dir",
        default="examples/ui_screens",
        help="Path to UI examples directory (absolute or relative to --repo-root).",
    )
    args = parser.parse_args()

    root = Path(args.repo_root)
    result = validate_ui_examples(
        examples_dir=_resolve_path(args.examples_dir, repo_root=root),
        repo_root=root,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
