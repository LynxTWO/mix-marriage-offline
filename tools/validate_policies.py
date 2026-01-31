"""Minimal placeholder for policy validation."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate policy registries and referenced policy packs."
    )
    parser.parse_args()
    print("validate_policies.py: not implemented", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
