from __future__ import annotations

import json
from pathlib import Path

from mmo.core.downmix_inventory import (
    build_downmix_list_payload,
    extract_downmix_inventory_ids,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT_DIR / "tests" / "fixtures"


def _load_expected_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise AssertionError(f"Fixture must be a JSON array: {path}")
    ids = [item for item in payload if isinstance(item, str)]
    if len(ids) != len(payload):
        raise AssertionError(f"Fixture must contain only string IDs: {path}")
    if ids != sorted(ids):
        raise AssertionError(f"Fixture IDs must be sorted: {path}")
    return ids


def _actual_inventory_ids() -> dict[str, list[str]]:
    # This uses the same payload builder that `mmo downmix list` uses.
    payload = build_downmix_list_payload(
        repo_root=ROOT_DIR,
        include_layouts=True,
        include_policies=True,
        include_conversions=True,
    )
    return extract_downmix_inventory_ids(payload)


def _assert_inventory_ids(label: str, actual: list[str], expected: list[str]) -> None:
    if actual == expected:
        return

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))

    lines = [f"{label} inventory mismatch."]
    lines.append(f"missing IDs: {missing}" if missing else "missing IDs: []")
    lines.append(f"extra IDs: {extra}" if extra else "extra IDs: []")
    lines.append(f"expected: {expected}")
    lines.append(f"actual: {actual}")
    raise AssertionError("\n".join(lines))


def test_downmix_layout_inventory_matches_fixture() -> None:
    actual_ids = _actual_inventory_ids()["layouts"]
    expected_ids = _load_expected_ids(FIXTURES_DIR / "expected_downmix_layouts.json")
    _assert_inventory_ids("layouts", actual_ids, expected_ids)


def test_downmix_policy_inventory_matches_fixture() -> None:
    actual_ids = _actual_inventory_ids()["policies"]
    expected_ids = _load_expected_ids(FIXTURES_DIR / "expected_downmix_policies.json")
    _assert_inventory_ids("policies", actual_ids, expected_ids)


def test_downmix_conversion_inventory_matches_fixture() -> None:
    actual_ids = _actual_inventory_ids()["conversions"]
    expected_ids = _load_expected_ids(FIXTURES_DIR / "expected_downmix_conversions.json")
    _assert_inventory_ids("conversions", actual_ids, expected_ids)
