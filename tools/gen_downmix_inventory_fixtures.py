"""Generate deterministic fixture inventories for `mmo downmix list --format json`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.core.downmix_inventory import (  # noqa: E402
    build_downmix_list_payload,
    extract_downmix_inventory_ids,
)

FIXTURES_DIR = ROOT_DIR / "tests" / "fixtures"


def _write_ids(path: Path, ids: list[str]) -> None:
    sorted_ids = sorted(ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted_ids, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def main() -> int:
    payload = build_downmix_list_payload(
        repo_root=ROOT_DIR,
        include_layouts=True,
        include_policies=True,
        include_conversions=True,
    )
    inventory_ids = extract_downmix_inventory_ids(payload)

    _write_ids(FIXTURES_DIR / "expected_downmix_layouts.json", inventory_ids["layouts"])
    _write_ids(FIXTURES_DIR / "expected_downmix_policies.json", inventory_ids["policies"])
    _write_ids(
        FIXTURES_DIR / "expected_downmix_conversions.json",
        inventory_ids["conversions"],
    )
    print("Run: pytest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
