"""Frozen-friendly CLI entrypoint for packaged sidecars and release binaries."""

from __future__ import annotations

from mmo.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
