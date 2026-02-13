"""Scan local stem filenames into a names-only corpus and anonymized stats."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.core.role_lexicon import load_role_lexicon  # noqa: E402
from mmo.core.roles import load_roles  # noqa: E402
from mmo.core.stems_classifier import (  # noqa: E402
    UNKNOWN_ROLE_ID,
    classify_stems_with_evidence,
)
from mmo.core.stems_index import build_stems_index  # noqa: E402

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_TOP_TOKENS_LIMIT = 200
_PER_ROLE_TOP_LIMIT = 40
_AMBIGUOUS_MARGIN = 1
_HIGH_CONFIDENCE_THRESHOLD = 0.8
_SUGGESTION_KEYWORDS_PER_ROLE = 24


def _sha1_token(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _rel_dir_from_rel_path(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/")
    if "/" not in normalized:
        return "."
    parent = normalized.rsplit("/", 1)[0]
    return parent if parent else "."


def _ranked_counter(
    counter: Counter[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"token": token, "count": count} for token, count in ranked]


def _ranked_role_counter(
    counter: Counter[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"role_id": role_id, "count": count} for role_id, count in ranked]


def _is_suggestion_token(token: str) -> bool:
    if not _TOKEN_RE.fullmatch(token):
        return False
    return token not in {"l", "r", "left", "right", "mono", "stereo", "mix", "stem", "stems"}


def _known_role_tokens(
    *,
    roles_payload: dict[str, Any],
    role_lexicon_payload: dict[str, Any] | None,
) -> dict[str, set[str]]:
    known: dict[str, set[str]] = defaultdict(set)

    roles_map = roles_payload.get("roles")
    if isinstance(roles_map, dict):
        for role_id, role_entry in roles_map.items():
            if not isinstance(role_id, str) or role_id == "_meta":
                continue
            if not isinstance(role_entry, dict):
                continue
            inference = role_entry.get("inference")
            if not isinstance(inference, dict):
                continue
            keywords = inference.get("keywords")
            if not isinstance(keywords, list):
                continue
            for keyword in keywords:
                if not isinstance(keyword, str):
                    continue
                normalized = keyword.strip().lower()
                if normalized:
                    known[role_id].add(normalized)

    if isinstance(role_lexicon_payload, dict):
        for role_id, entry in role_lexicon_payload.items():
            if not isinstance(role_id, str):
                continue
            if not hasattr(entry, "keywords"):
                continue
            for keyword in getattr(entry, "keywords", ()):
                if isinstance(keyword, str) and keyword.strip():
                    known[role_id].add(keyword.strip().lower())
    return known


def _limited_stems_index(stems_index: dict[str, Any], max_files: int | None) -> dict[str, Any]:
    if max_files is None:
        return stems_index
    files = stems_index.get("files")
    if not isinstance(files, list):
        return stems_index
    trimmed = [item for item in files if isinstance(item, dict)][:max_files]
    payload = dict(stems_index)
    payload["files"] = trimmed
    return payload


def _load_role_lexicon_if_present(
    *,
    role_lexicon_path: Path | None,
    roles_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if role_lexicon_path is None:
        return None, None
    payload = load_role_lexicon(role_lexicon_path, roles_payload=roles_payload)
    return payload, role_lexicon_path.as_posix()


def _scan_payload(
    *,
    root: Path,
    redact_paths: bool,
    max_files: int | None,
    role_lexicon_path: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    roles_payload = load_roles(ROOT_DIR / "ontology" / "roles.yaml")
    role_lexicon_payload, role_lexicon_ref = _load_role_lexicon_if_present(
        role_lexicon_path=role_lexicon_path,
        roles_payload=roles_payload,
    )

    stems_index = build_stems_index(root, root_dir=str(root))
    stems_index = _limited_stems_index(stems_index, max_files)
    stems_map, explanations = classify_stems_with_evidence(
        stems_index,
        roles_payload,
        role_lexicon=role_lexicon_payload,
        stems_index_ref="(inline stems_index)",
        roles_ref="ontology/roles.yaml",
        role_lexicon_ref=role_lexicon_ref,
    )

    files = stems_index.get("files")
    assignments = stems_map.get("assignments")
    file_rows = [row for row in files if isinstance(row, dict)] if isinstance(files, list) else []
    assignment_rows = (
        [row for row in assignments if isinstance(row, dict)]
        if isinstance(assignments, list)
        else []
    )

    by_file_id: dict[str, dict[str, Any]] = {}
    for assignment in assignment_rows:
        file_id = assignment.get("file_id")
        if isinstance(file_id, str):
            by_file_id[file_id] = assignment

    corpus_rows: list[dict[str, Any]] = []
    for file_row in file_rows:
        file_id = file_row.get("file_id")
        rel_path = file_row.get("rel_path")
        basename = file_row.get("basename")
        ext = file_row.get("ext")
        tokens = file_row.get("tokens")
        folder_tokens = file_row.get("folder_tokens")
        set_id = file_row.get("set_id")
        if not isinstance(file_id, str) or not isinstance(rel_path, str):
            continue
        if not isinstance(basename, str) or not isinstance(ext, str):
            continue

        row: dict[str, Any] = {
            "file_id": file_id,
            "set_id": set_id if isinstance(set_id, str) else "",
            "basename": basename,
            "ext": ext,
            "tokens": [item for item in tokens if isinstance(item, str)] if isinstance(tokens, list) else [],
            "folder_tokens": (
                [item for item in folder_tokens if isinstance(item, str)]
                if isinstance(folder_tokens, list)
                else []
            ),
        }

        rel_dir = _rel_dir_from_rel_path(rel_path)
        if redact_paths:
            row["rel_dir_hash"] = _sha1_token(rel_dir)
        else:
            row["rel_path"] = rel_path
            row["rel_dir"] = rel_dir

        assignment = by_file_id.get(file_id)
        if isinstance(assignment, dict):
            row["role_id"] = assignment.get("role_id", UNKNOWN_ROLE_ID)
            row["confidence"] = assignment.get("confidence", 0.0)
            row["bus_group"] = assignment.get("bus_group")
        else:
            row["role_id"] = UNKNOWN_ROLE_ID
            row["confidence"] = 0.0
            row["bus_group"] = None
        corpus_rows.append(row)

    corpus_rows.sort(
        key=lambda item: (
            item.get("rel_path", ""),
            item.get("basename", ""),
            item.get("file_id", ""),
        )
    )
    return corpus_rows, stems_map, explanations, role_lexicon_payload


def _build_stats(
    *,
    corpus_rows: list[dict[str, Any]],
    explanations: dict[str, Any],
) -> dict[str, Any]:
    token_frequency = Counter[str]()
    unknown_token_frequency = Counter[str]()
    per_role_token_frequency: dict[str, Counter[str]] = defaultdict(Counter)
    ambiguous_token_role_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in corpus_rows:
        tokens = row.get("tokens")
        if not isinstance(tokens, list):
            continue
        token_values = [token for token in tokens if isinstance(token, str) and token]
        token_frequency.update(token_values)

        role_id = row.get("role_id")
        confidence = row.get("confidence")
        if role_id == UNKNOWN_ROLE_ID:
            unknown_token_frequency.update(token_values)

        if (
            isinstance(role_id, str)
            and role_id != UNKNOWN_ROLE_ID
            and isinstance(confidence, (int, float))
            and float(confidence) >= _HIGH_CONFIDENCE_THRESHOLD
        ):
            per_role_token_frequency[role_id].update(token_values)

        file_id = row.get("file_id")
        if not isinstance(file_id, str):
            continue
        explain = explanations.get(file_id)
        if not isinstance(explain, dict):
            continue
        candidates = explain.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            continue

        positive = [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and isinstance(candidate.get("score"), int)
            and candidate.get("score", 0) > 0
            and isinstance(candidate.get("role_id"), str)
        ]
        if len(positive) < 2:
            continue

        top_score = positive[0]["score"]
        ambiguous_roles = [
            candidate["role_id"]
            for candidate in positive
            if candidate["score"] >= top_score - _AMBIGUOUS_MARGIN
        ]
        if len(ambiguous_roles) < 2:
            continue

        for token in token_values:
            for role in ambiguous_roles:
                ambiguous_token_role_counts[token][role] += 1

    per_role_top = {
        role_id: _ranked_counter(counter, limit=_PER_ROLE_TOP_LIMIT)
        for role_id, counter in sorted(per_role_token_frequency.items())
    }

    ambiguous_rows: list[dict[str, Any]] = []
    for token, counter in sorted(ambiguous_token_role_counts.items()):
        candidate_roles = _ranked_role_counter(counter, limit=32)
        total = sum(item["count"] for item in candidate_roles)
        ambiguous_rows.append(
            {
                "token": token,
                "candidate_roles": candidate_roles,
                "total_count": total,
            }
        )
    ambiguous_rows.sort(key=lambda item: (-item["total_count"], item["token"]))
    ambiguous_rows = ambiguous_rows[:_TOP_TOKENS_LIMIT]

    return {
        "total_files": len(corpus_rows),
        "token_frequency_top": _ranked_counter(token_frequency, limit=_TOP_TOKENS_LIMIT),
        "unknown_token_frequency_top": _ranked_counter(
            unknown_token_frequency,
            limit=_TOP_TOKENS_LIMIT,
        ),
        "per_role_token_top": per_role_top,
        "ambiguous_cases": ambiguous_rows,
    }


def _build_role_lexicon_suggestions(
    *,
    corpus_rows: list[dict[str, Any]],
    roles_payload: dict[str, Any],
    role_lexicon_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    known_tokens = _known_role_tokens(
        roles_payload=roles_payload,
        role_lexicon_payload=role_lexicon_payload,
    )

    role_token_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in corpus_rows:
        role_id = row.get("role_id")
        confidence = row.get("confidence")
        if (
            not isinstance(role_id, str)
            or role_id == UNKNOWN_ROLE_ID
            or not isinstance(confidence, (int, float))
            or float(confidence) < _HIGH_CONFIDENCE_THRESHOLD
        ):
            continue
        tokens = row.get("tokens")
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if not isinstance(token, str):
                continue
            normalized = token.strip().lower()
            if not normalized or not _is_suggestion_token(normalized):
                continue
            role_token_counts[role_id][normalized] += 1

    suggestions: dict[str, dict[str, list[str]]] = {}
    for role_id, counter in sorted(role_token_counts.items()):
        known = known_tokens.get(role_id, set())
        ranked = [
            token
            for token, _count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
            if token not in known
        ]
        ranked = ranked[:_SUGGESTION_KEYWORDS_PER_ROLE]
        if ranked:
            suggestions[role_id] = {"keywords": ranked}
    return {"role_lexicon": suggestions}


def _write_corpus_jsonl(out_path: Path, rows: list[dict[str, Any]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(serialized + "\n", encoding="utf-8")


def _render_suggestions_yaml(payload: dict[str, Any]) -> str:
    role_lexicon = payload.get("role_lexicon")
    rows = (
        sorted(role_lexicon.items(), key=lambda item: item[0])
        if isinstance(role_lexicon, dict)
        else []
    )
    lines = [
        "# HUMAN REVIEW REQUIRED",
        "# Generated by tools/stem_corpus_scan.py as a starter draft.",
        "# Review each token before use; do not auto-merge.",
        "# Validate with: python -m mmo stems classify --role-lexicon <this-file> --root <stems_root> --out stems_map.json",
        "role_lexicon:",
    ]
    if not rows:
        lines.append("  {}")
        return "\n".join(lines) + "\n"

    for role_id, entry in rows:
        lines.append(f"  {role_id}:")
        keywords = entry.get("keywords") if isinstance(entry, dict) else None
        keyword_values = (
            [item for item in keywords if isinstance(item, str) and item]
            if isinstance(keywords, list)
            else []
        )
        if keyword_values:
            lines.append("    keywords:")
            for keyword in keyword_values:
                lines.append(f"      - {keyword}")
        else:
            lines.append("    {}")
    return "\n".join(lines) + "\n"


def _write_suggestions(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_suggestions_yaml(payload), encoding="utf-8")


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan stem filenames into a token corpus and anonymized stats using stems_index + "
            "stems_classifier deterministic logic."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Root directory containing stem audio files.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to output corpus JSONL.",
    )
    parser.add_argument(
        "--stats",
        required=True,
        help="Path to output stats JSON.",
    )
    parser.add_argument(
        "--redact-paths",
        action="store_true",
        help="Store basename and hashed rel_dir instead of rel_path/rel_dir.",
    )
    parser.add_argument(
        "--max-files",
        type=_positive_int,
        default=None,
        help="Optional max number of files to include after deterministic sorting.",
    )
    parser.add_argument(
        "--role-lexicon",
        default=None,
        help="Optional path to role_lexicon YAML used during classification.",
    )
    parser.add_argument(
        "--suggestions-out",
        default=None,
        help="Optional path to write starter role_lexicon suggestions YAML.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root)
    out_path = Path(args.out)
    stats_path = Path(args.stats)
    role_lexicon_path = Path(args.role_lexicon) if args.role_lexicon else None

    try:
        corpus_rows, stems_map, explanations, role_lexicon_payload = _scan_payload(
            root=root,
            redact_paths=args.redact_paths,
            max_files=args.max_files,
            role_lexicon_path=role_lexicon_path,
        )
        stats_payload = _build_stats(corpus_rows=corpus_rows, explanations=explanations)
        _write_corpus_jsonl(out_path, corpus_rows)
        _write_json(stats_path, stats_payload)

        if isinstance(args.suggestions_out, str) and args.suggestions_out.strip():
            roles_payload = load_roles(ROOT_DIR / "ontology" / "roles.yaml")
            suggestions_payload = _build_role_lexicon_suggestions(
                corpus_rows=corpus_rows,
                roles_payload=roles_payload,
                role_lexicon_payload=role_lexicon_payload,
            )
            _write_suggestions(Path(args.suggestions_out), suggestions_payload)

    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "total_files": len(corpus_rows),
                "out": out_path.as_posix(),
                "stats": stats_path.as_posix(),
                "redact_paths": bool(args.redact_paths),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
