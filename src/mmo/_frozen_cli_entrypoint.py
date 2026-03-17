"""Frozen-friendly CLI entrypoint for packaged sidecars and release binaries."""

from __future__ import annotations

import runpy
import sys

from mmo.cli import main


def _resolve_passthrough_module(module_name: str) -> str | None:
    normalized = module_name.strip()
    if not normalized:
        return None
    if normalized == "mmo":
        return "mmo.__main__"
    if normalized.startswith("mmo."):
        return normalized
    return None


def _try_module_passthrough(argv: list[str]) -> int | None:
    if len(argv) < 3 or argv[1] != "-m":
        return None

    module_name = _resolve_passthrough_module(argv[2])
    if module_name is None:
        return None

    saved_argv = sys.argv[:]
    try:
        sys.argv = [module_name, *argv[3:]]
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    finally:
        sys.argv = saved_argv
    return 0


if __name__ == "__main__":
    passthrough_exit = _try_module_passthrough(sys.argv)
    if passthrough_exit is not None:
        raise SystemExit(passthrough_exit)
    raise SystemExit(main())
