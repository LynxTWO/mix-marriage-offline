"""Minimal placeholder for running policy fixtures."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run policy fixtures and compare expected validation issues."
    )
    parser.parse_args()
    print("run_policy_fixtures.py: not implemented", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
