#!/usr/bin/env python3
"""Compare two corpus stats JSON files and print stable deltas.

Usage:
    python tools/stem_corpus_diff.py --before stats_v1.json --after stats_v2.json
    python tools/stem_corpus_diff.py --before stats_v1.json --after stats_v2.json --out diff.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _token_map(rows: Any) -> dict[str, int]:
    """Convert a ranked-counter list to {token: count}."""
    if not isinstance(rows, list):
        return {}
    result: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            token = row.get("token")
            count = row.get("count")
            if isinstance(token, str) and isinstance(count, (int, float)):
                result[token] = int(count)
    return result


def _compute_delta(
    before_rows: Any,
    after_rows: Any,
    *,
    top: int,
) -> list[dict[str, Any]]:
    """Compute delta between two ranked-counter lists.

    Returns rows sorted by abs(delta) desc, then token asc.
    """
    before_map = _token_map(before_rows)
    after_map = _token_map(after_rows)
    all_tokens = sorted(set(before_map.keys()) | set(after_map.keys()))

    deltas: list[dict[str, Any]] = []
    for token in all_tokens:
        b = before_map.get(token, 0)
        a = after_map.get(token, 0)
        d = a - b
        if d != 0:
            deltas.append({
                "token": token,
                "before": b,
                "after": a,
                "delta": d,
            })

    deltas.sort(key=lambda r: (-abs(r["delta"]), r["token"]))
    return deltas[:top]


def _compute_per_role_delta(
    before_per_role: Any,
    after_per_role: Any,
    *,
    top: int,
) -> dict[str, list[dict[str, Any]]]:
    """Compute per-role delta between two per_role_token_top dicts."""
    if not isinstance(before_per_role, dict):
        before_per_role = {}
    if not isinstance(after_per_role, dict):
        after_per_role = {}

    all_roles = sorted(set(before_per_role.keys()) | set(after_per_role.keys()))
    result: dict[str, list[dict[str, Any]]] = {}
    for role_id in all_roles:
        delta = _compute_delta(
            before_per_role.get(role_id),
            after_per_role.get(role_id),
            top=top,
        )
        if delta:
            result[role_id] = delta
    return result


def _count_summary(
    before_rows: Any,
    after_rows: Any,
) -> dict[str, int]:
    """Count increased, decreased, unchanged tokens."""
    before_map = _token_map(before_rows)
    after_map = _token_map(after_rows)
    all_tokens = sorted(set(before_map.keys()) | set(after_map.keys()))

    increased = 0
    decreased = 0
    unchanged = 0
    for token in all_tokens:
        b = before_map.get(token, 0)
        a = after_map.get(token, 0)
        if a > b:
            increased += 1
        elif a < b:
            decreased += 1
        else:
            unchanged += 1
    return {
        "decreased_count": decreased,
        "increased_count": increased,
        "unchanged_count": unchanged,
    }


def diff_corpus_stats(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    before_path: str,
    after_path: str,
    top: int = 50,
) -> dict[str, Any]:
    """Produce a stable diff payload from two corpus stats dicts."""
    warnings: list[str] = []

    # Robust key access with warnings for missing keys.
    keys_to_check = [
        "token_frequency_top",
        "unknown_token_frequency_top",
        "per_role_token_top",
        "scan_params",
    ]
    for key in keys_to_check:
        if key not in before:
            warnings.append(f"missing_key:{key}_before")
        if key not in after:
            warnings.append(f"missing_key:{key}_after")

    scan_params_before = before.get("scan_params")
    scan_params_after = after.get("scan_params")

    token_freq_delta = _compute_delta(
        before.get("token_frequency_top"),
        after.get("token_frequency_top"),
        top=top,
    )
    unknown_token_freq_delta = _compute_delta(
        before.get("unknown_token_frequency_top"),
        after.get("unknown_token_frequency_top"),
        top=top,
    )
    per_role_delta = _compute_per_role_delta(
        before.get("per_role_token_top"),
        after.get("per_role_token_top"),
        top=top,
    )

    summary = _count_summary(
        before.get("token_frequency_top"),
        after.get("token_frequency_top"),
    )

    return {
        "ok": True,
        "before_path": before_path,
        "after_path": after_path,
        "scan_params_before": scan_params_before if isinstance(scan_params_before, dict) else {},
        "scan_params_after": scan_params_after if isinstance(scan_params_after, dict) else {},
        "deltas": {
            "token_frequency_top_delta": token_freq_delta,
            "unknown_token_frequency_top_delta": unknown_token_freq_delta,
            "per_role_token_top_delta": per_role_delta,
        },
        "decreased_count": summary["decreased_count"],
        "increased_count": summary["increased_count"],
        "unchanged_count": summary["unchanged_count"],
        "warnings": sorted(warnings),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two corpus stats JSON files and print stable deltas.",
    )
    parser.add_argument(
        "--before",
        required=True,
        help="Path to the baseline stats JSON.",
    )
    parser.add_argument(
        "--after",
        required=True,
        help="Path to the updated stats JSON.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write JSON output (default: stdout).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Number of top delta rows per section (default: 50).",
    )

    args = parser.parse_args(argv)

    before_path = Path(args.before)
    after_path = Path(args.after)

    try:
        before_payload = json.loads(before_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read --before: {exc}", file=sys.stderr)
        return 1
    if not isinstance(before_payload, dict):
        print("--before JSON root must be an object.", file=sys.stderr)
        return 1

    try:
        after_payload = json.loads(after_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read --after: {exc}", file=sys.stderr)
        return 1
    if not isinstance(after_payload, dict):
        print("--after JSON root must be an object.", file=sys.stderr)
        return 1

    result = diff_corpus_stats(
        before_payload,
        after_payload,
        before_path=before_path.as_posix(),
        after_path=after_path.as_posix(),
        top=args.top,
    )

    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if isinstance(args.out, str) and args.out.strip():
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    else:
        print(output, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
