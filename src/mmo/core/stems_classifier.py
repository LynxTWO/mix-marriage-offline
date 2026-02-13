from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from mmo.core.role_lexicon import CompiledRoleLexiconEntry

STEMS_MAP_VERSION = "0.1.0"
DEFAULT_ROLES_REF = "ontology/roles.yaml"
UNKNOWN_ROLE_ID = "ROLE.OTHER.UNKNOWN"

_SCORE_KEYWORD_TOKEN = 4
_SCORE_KEYWORD_PHRASE = 6
_SCORE_REGEX = 5
_SCORE_FOLDER_TOKEN = 1
_SCORE_STRONG_THRESHOLD = 12
_SCORE_STRONG_MATCH_MIN = 8
_BUS_PREFERENCE_MARGIN = 1

_TOKEN_SPLIT_RE = re.compile(r"[\s_.\-\[\]\(\)\{\}]+")
_TRACK_PREFIX_RE = re.compile(r"^\s*\d+\s*[-_.\s]+\s*")
_TRAILING_DIGIT_TOKEN_RE = re.compile(r"^([a-z][a-z0-9]*?)(\d+)$")
_PURE_DIGIT_TOKEN_RE = re.compile(r"^\d+$")

_LEFT_LONG_TOKENS = frozenset({"left", "lf", "lt", "lft", "lhs", "lch"})
_RIGHT_LONG_TOKENS = frozenset({"right", "rf", "rt", "rgt", "rhs", "rch"})
_LEFT_SIDE_TOKENS = frozenset({"l", "left"})
_RIGHT_SIDE_TOKENS = frozenset({"r", "right"})
_COMPOUND_TOKEN_SPLITS: dict[str, tuple[str, str]] = {
    "kickin": ("kick", "in"),
    "kickout": ("kick", "out"),
    "kickinside": ("kick", "inside"),
    "kickoutside": ("kick", "outside"),
    "snaretop": ("snare", "top"),
    "snarebot": ("snare", "bot"),
    "snarebottom": ("snare", "bottom"),
    "snareup": ("snare", "up"),
    "snaredown": ("snare", "down"),
    "hihatopen": ("hihat", "open"),
    "hihatclosed": ("hihat", "closed"),
}


@dataclass(frozen=True)
class _RoleRule:
    role_id: str
    kind: str
    default_bus_group: str | None
    keywords: tuple[str, ...]
    regex: tuple[str, ...]
    compiled_regex: tuple[re.Pattern[str], ...]
    folder_match_tokens: tuple[str, ...]


@dataclass(frozen=True)
class _RoleEvidence:
    role_id: str
    kind: str
    bus_group: str | None
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _ScoringToken:
    token: str
    derived_reason: str | None


def _sha1_token(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _normalize_lr_token(token: str) -> str:
    if token == "l":
        return "l"
    if token == "r":
        return "r"
    if token in _LEFT_LONG_TOKENS:
        return "left"
    if token in _RIGHT_LONG_TOKENS:
        return "right"
    return token


def _tokenize_value(value: str) -> list[str]:
    lowered = value.lower()
    normalized = _TRACK_PREFIX_RE.sub("", lowered, count=1)
    parts = [part for part in _TOKEN_SPLIT_RE.split(normalized) if part]
    return [_normalize_lr_token(part) for part in parts]


def _normalize_keywords(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    normalized = {
        value.strip().lower()
        for value in values
        if isinstance(value, str) and value.strip()
    }
    return tuple(sorted(normalized))


def _normalize_regex(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    normalized = {
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    }
    return tuple(sorted(normalized))


def _is_pure_digit_token(token: str) -> bool:
    return bool(_PURE_DIGIT_TOKEN_RE.fullmatch(token))


def _derive_scoring_tokens(token: str) -> list[_ScoringToken]:
    normalized = token.lower()
    if not normalized or _is_pure_digit_token(normalized):
        return []

    derived: list[_ScoringToken] = []
    seen: set[tuple[str, str | None]] = set()

    def _append(derived_token: str, derived_reason: str | None = None) -> None:
        if not derived_token or _is_pure_digit_token(derived_token):
            return
        key = (derived_token, derived_reason)
        if key in seen:
            return
        seen.add(key)
        derived.append(_ScoringToken(token=derived_token, derived_reason=derived_reason))

    _append(normalized)
    split_candidates = [normalized]
    match = _TRAILING_DIGIT_TOKEN_RE.fullmatch(normalized)
    if match is not None:
        base = match.group(1)
        if base:
            _append(base, f"token_norm:{normalized}->{base}")
            split_candidates.append(base)

    for split_source in split_candidates:
        split_target = _COMPOUND_TOKEN_SPLITS.get(split_source)
        if split_target is None:
            continue
        left, right = split_target
        split_reason = f"token_split:{split_source}->{left}+{right}"
        _append(left, split_reason)
        _append(right, split_reason)

    return derived


def _build_scoring_tokens(values: Any) -> list[_ScoringToken]:
    if not isinstance(values, list):
        return []
    scoring_tokens: list[_ScoringToken] = []
    for token in values:
        if not isinstance(token, str):
            continue
        scoring_tokens.extend(_derive_scoring_tokens(token))
    return scoring_tokens


def _token_reason_index(scoring_tokens: list[_ScoringToken]) -> dict[str, tuple[str, ...]]:
    reasons_by_token: dict[str, list[str]] = {}
    for scoring_token in scoring_tokens:
        reason = scoring_token.derived_reason
        if reason is None:
            continue
        token_reasons = reasons_by_token.setdefault(scoring_token.token, [])
        if reason not in token_reasons:
            token_reasons.append(reason)
    return {
        token: tuple(reasons)
        for token, reasons in sorted(reasons_by_token.items(), key=lambda item: item[0])
    }


def _append_unique_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _compiled_external_lexicon(
    role_lexicon: dict[str, Any] | None,
) -> dict[str, CompiledRoleLexiconEntry]:
    if not isinstance(role_lexicon, dict):
        return {}

    compiled: dict[str, CompiledRoleLexiconEntry] = {}
    invalid_patterns: list[str] = []
    for role_id in sorted(role_lexicon.keys()):
        if not isinstance(role_id, str):
            continue
        entry = role_lexicon.get(role_id)
        if isinstance(entry, CompiledRoleLexiconEntry):
            compiled[role_id] = entry
            continue
        if not isinstance(entry, dict):
            continue

        keywords = _normalize_keywords(entry.get("keywords"))
        regex = _normalize_regex(entry.get("regex"))
        compiled_regex: list[re.Pattern[str]] = []
        for pattern in regex:
            try:
                compiled_regex.append(re.compile(pattern))
            except re.error:
                invalid_patterns.append(f"{role_id}: {pattern}")
        compiled[role_id] = CompiledRoleLexiconEntry(
            keywords=keywords,
            regex=regex,
            compiled_regex=tuple(compiled_regex),
        )

    if invalid_patterns:
        raise ValueError(
            "Role lexicon regex patterns failed to compile: "
            + ", ".join(sorted(invalid_patterns))
        )
    return compiled


def _compile_role_rules(
    roles_payload: dict[str, Any],
    role_lexicon: dict[str, Any] | None,
) -> dict[str, _RoleRule]:
    roles = roles_payload.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("Roles registry payload must include a roles mapping.")

    compiled_lexicon = _compiled_external_lexicon(role_lexicon)
    invalid_patterns: list[str] = []
    rules: dict[str, _RoleRule] = {}

    for role_id in sorted(roles.keys()):
        if role_id == "_meta":
            continue
        entry = roles.get(role_id)
        if not isinstance(role_id, str) or not isinstance(entry, dict):
            continue

        inference = entry.get("inference")
        inference_mapping = inference if isinstance(inference, dict) else {}

        role_keywords = set(_normalize_keywords(inference_mapping.get("keywords")))
        role_regex = set(_normalize_regex(inference_mapping.get("regex")))

        lex_entry = compiled_lexicon.get(role_id)
        if lex_entry is not None:
            role_keywords.update(lex_entry.keywords)
            role_regex.update(lex_entry.regex)

        sorted_keywords = tuple(sorted(role_keywords))
        sorted_regex = tuple(sorted(role_regex))

        compiled_regex: list[re.Pattern[str]] = []
        for pattern in sorted_regex:
            try:
                compiled_regex.append(re.compile(pattern))
            except re.error:
                invalid_patterns.append(f"{role_id}: {pattern}")

        folder_match_tokens = sorted(
            {
                token
                for keyword in sorted_keywords
                for token in _tokenize_value(keyword)
                if token
            }
        )

        default_bus_group = (
            entry.get("default_bus_group")
            if isinstance(entry.get("default_bus_group"), str)
            else None
        )
        kind = entry.get("kind") if isinstance(entry.get("kind"), str) else "other"

        rules[role_id] = _RoleRule(
            role_id=role_id,
            kind=kind,
            default_bus_group=default_bus_group,
            keywords=sorted_keywords,
            regex=sorted_regex,
            compiled_regex=tuple(compiled_regex),
            folder_match_tokens=tuple(folder_match_tokens),
        )

    if invalid_patterns:
        raise ValueError(
            "Role inference regex patterns failed to compile: "
            + ", ".join(sorted(invalid_patterns))
        )
    return rules


def _match_phrase(
    tokens: list[_ScoringToken],
    phrase_tokens: list[str],
) -> tuple[bool, tuple[str, ...]]:
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return False, ()

    window = len(phrase_tokens)
    for idx in range(0, len(tokens) - window + 1):
        candidate_window = tokens[idx : idx + window]
        candidate_tokens = [item.token for item in candidate_window]
        if candidate_tokens != phrase_tokens:
            continue
        matched_reasons: list[str] = []
        for item in candidate_window:
            reason = item.derived_reason
            if reason is not None and reason not in matched_reasons:
                matched_reasons.append(reason)
        return True, tuple(matched_reasons)

    return False, ()


def _score_role(
    file_entry: dict[str, Any],
    *,
    rule: _RoleRule,
) -> _RoleEvidence:
    tokens = [
        token.lower()
        for token in file_entry.get("tokens", [])
        if isinstance(token, str) and token
    ]
    folder_tokens = [
        token.lower()
        for token in file_entry.get("folder_tokens", [])
        if isinstance(token, str) and token
    ]
    scoring_tokens = _build_scoring_tokens(tokens)
    folder_scoring_tokens = _build_scoring_tokens(folder_tokens)
    folder_token_set = {item.token for item in folder_scoring_tokens}
    folder_token_reasons = _token_reason_index(folder_scoring_tokens)

    rel_path = file_entry.get("rel_path") if isinstance(file_entry.get("rel_path"), str) else ""
    basename = file_entry.get("basename") if isinstance(file_entry.get("basename"), str) else ""
    searchable_text = f"{rel_path}\n{basename}"

    score = 0
    reasons: list[str] = []
    folder_hits: set[str] = set()

    for keyword in rule.keywords:
        keyword_tokens = _tokenize_value(keyword)
        if not keyword_tokens:
            continue
        phrase_hit, phrase_derived_reasons = _match_phrase(scoring_tokens, keyword_tokens)
        if phrase_hit:
            points = _SCORE_KEYWORD_PHRASE if len(keyword_tokens) > 1 else _SCORE_KEYWORD_TOKEN
            score += points
            _append_unique_reason(reasons, f"keyword={keyword}(+{points})")
            for derived_reason in phrase_derived_reasons:
                _append_unique_reason(reasons, derived_reason)
            continue
        if len(keyword_tokens) == 1:
            token = keyword_tokens[0]
            if token in folder_token_set and token not in folder_hits:
                folder_hits.add(token)
                score += _SCORE_FOLDER_TOKEN
                _append_unique_reason(reasons, f"folder_token={token}(+{_SCORE_FOLDER_TOKEN})")
                for derived_reason in folder_token_reasons.get(token, ()):
                    _append_unique_reason(reasons, derived_reason)

    for token in rule.folder_match_tokens:
        if token in folder_token_set and token not in folder_hits:
            folder_hits.add(token)
            score += _SCORE_FOLDER_TOKEN
            _append_unique_reason(reasons, f"folder_token={token}(+{_SCORE_FOLDER_TOKEN})")
            for derived_reason in folder_token_reasons.get(token, ()):
                _append_unique_reason(reasons, derived_reason)

    for pattern, compiled in zip(rule.regex, rule.compiled_regex):
        if compiled.search(searchable_text):
            score += _SCORE_REGEX
            reasons.append(f"regex={pattern}(+{_SCORE_REGEX})")

    return _RoleEvidence(
        role_id=rule.role_id,
        kind=rule.kind,
        bus_group=rule.default_bus_group,
        score=score,
        reasons=tuple(reasons),
    )


def _rounded_confidence(score: int) -> float:
    if score <= 0:
        return 0.0
    confidence = min(1.0, score / _SCORE_STRONG_THRESHOLD)
    return round(confidence, 3)


def _select_best_role(
    evidences: list[_RoleEvidence],
) -> tuple[_RoleEvidence | None, list[str], list[_RoleEvidence]]:
    matches = [evidence for evidence in evidences if evidence.score > 0]
    ranked = sorted(matches, key=lambda item: (-item.score, item.role_id))
    if not ranked:
        return None, [], ranked

    top_score = ranked[0].score
    top_roles = [item for item in ranked if item.score == top_score]
    preferred_roles = list(top_roles)
    preference_reasons: list[str] = []

    has_bus_match = any(item.kind == "bus" for item in top_roles)
    if has_bus_match and top_score >= _SCORE_STRONG_MATCH_MIN:
        specific_candidates = [
            item
            for item in ranked
            if (
                item.kind != "bus"
                and item.score >= _SCORE_STRONG_MATCH_MIN
                and item.score >= top_score - _BUS_PREFERENCE_MARGIN
            )
        ]
        if specific_candidates:
            best_specific = max(item.score for item in specific_candidates)
            preferred_roles = [
                item for item in specific_candidates if item.score == best_specific
            ]
            preference_reasons.append("prefer_specific_over_bus")

    winner = min(preferred_roles, key=lambda item: item.role_id)
    if len(preferred_roles) > 1:
        preference_reasons.append("tie_break=lex")
    return winner, preference_reasons, ranked


def _group_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts.keys())}


def _detect_link_group_ids(files: list[dict[str, Any]]) -> dict[str, str]:
    buckets: dict[tuple[str, tuple[str, ...]], dict[str, list[str]]] = {}
    for file_entry in files:
        file_id = file_entry.get("file_id")
        if not isinstance(file_id, str):
            continue

        set_id = file_entry.get("set_id") if isinstance(file_entry.get("set_id"), str) else ""
        tokens = [
            token.lower()
            for token in file_entry.get("tokens", [])
            if isinstance(token, str) and token
        ]
        has_left = any(token in _LEFT_SIDE_TOKENS for token in tokens)
        has_right = any(token in _RIGHT_SIDE_TOKENS for token in tokens)
        if has_left == has_right:
            continue

        side = "L" if has_left else "R"
        base_tokens = tuple(
            token
            for token in tokens
            if token not in _LEFT_SIDE_TOKENS and token not in _RIGHT_SIDE_TOKENS
        )
        if not base_tokens:
            continue

        key = (set_id, base_tokens)
        if key not in buckets:
            buckets[key] = {"L": [], "R": []}
        buckets[key][side].append(file_id)

    link_ids: dict[str, str] = {}
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        left_ids = sorted(bucket["L"])
        right_ids = sorted(bucket["R"])
        if not left_ids or not right_ids:
            continue

        digest = _sha1_token(f"{key[0]}|{'/'.join(key[1])}")
        link_group_id = f"LINK.{digest}"
        for file_id in left_ids + right_ids:
            link_ids[file_id] = link_group_id
    return link_ids


def classify_stems_with_evidence(
    stems_index: dict[str, Any],
    roles: dict[str, Any],
    role_lexicon: dict[str, Any] | None = None,
    *,
    stems_index_ref: str = "stems_index.json",
    roles_ref: str = DEFAULT_ROLES_REF,
    role_lexicon_ref: str | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rules = _compile_role_rules(roles, role_lexicon)
    unknown_rule = rules.get(UNKNOWN_ROLE_ID)

    files = stems_index.get("files")
    file_rows = [item for item in files if isinstance(item, dict)] if isinstance(files, list) else []
    file_rows = sorted(
        file_rows,
        key=lambda item: (
            item.get("rel_path") if isinstance(item.get("rel_path"), str) else "",
            item.get("file_id") if isinstance(item.get("file_id"), str) else "",
        ),
    )

    link_group_ids = _detect_link_group_ids(file_rows)
    assignments: list[dict[str, Any]] = []
    explanations: dict[str, dict[str, Any]] = {}

    for file_entry in file_rows:
        rel_path = file_entry.get("rel_path") if isinstance(file_entry.get("rel_path"), str) else ""
        file_id = file_entry.get("file_id") if isinstance(file_entry.get("file_id"), str) else ""

        evidences = [
            _score_role(file_entry, rule=rule)
            for _, rule in sorted(rules.items(), key=lambda item: item[0])
        ]
        winner, winner_flags, ranked = _select_best_role(evidences)

        if winner is None:
            winner_role_id = unknown_rule.role_id if unknown_rule is not None else UNKNOWN_ROLE_ID
            winner_bus_group = (
                unknown_rule.default_bus_group if unknown_rule is not None else None
            )
            winner_score = 0
            winner_reasons = ["no_match", f"fallback={winner_role_id}"]
        else:
            winner_role_id = winner.role_id
            winner_bus_group = winner.bus_group
            winner_score = winner.score
            winner_reasons = list(winner.reasons)
            winner_reasons.extend(winner_flags)
            winner_reasons.append(f"score={winner_score}")

        confidence = _rounded_confidence(winner_score)
        winner_reasons.append(f"confidence={confidence:.3f}")

        assignments.append(
            {
                "file_id": file_id,
                "rel_path": rel_path,
                "role_id": winner_role_id,
                "confidence": confidence,
                "bus_group": winner_bus_group,
                "reasons": winner_reasons,
                "link_group_id": link_group_ids.get(file_id),
            }
        )

        explanations[file_id] = {
            "file_id": file_id,
            "rel_path": rel_path,
            "tokens": [
                token
                for token in file_entry.get("tokens", [])
                if isinstance(token, str) and token
            ],
            "folder_tokens": [
                token
                for token in file_entry.get("folder_tokens", [])
                if isinstance(token, str) and token
            ],
            "selected_role_id": winner_role_id,
            "selected_score": winner_score,
            "selected_reasons": winner_reasons,
            "candidates": [
                {
                    "role_id": evidence.role_id,
                    "kind": evidence.kind,
                    "bus_group": evidence.bus_group,
                    "score": evidence.score,
                    "reasons": list(evidence.reasons),
                }
                for evidence in ranked
            ],
        }

    assignments.sort(
        key=lambda item: (
            item["rel_path"],
            item["file_id"],
        )
    )

    counts_by_role = _group_counts(
        [
            assignment["role_id"]
            for assignment in assignments
            if isinstance(assignment.get("role_id"), str)
        ]
    )
    counts_by_bus_group = _group_counts(
        [
            assignment["bus_group"]
            for assignment in assignments
            if isinstance(assignment.get("bus_group"), str) and assignment.get("bus_group")
        ]
    )
    unknown_files = sum(
        1 for assignment in assignments if assignment.get("role_id") == UNKNOWN_ROLE_ID
    )

    stems_map: dict[str, Any] = {
        "version": STEMS_MAP_VERSION,
        "stems_index_ref": stems_index_ref,
        "roles_ref": roles_ref,
        "assignments": assignments,
        "summary": {
            "counts_by_role": counts_by_role,
            "counts_by_bus_group": counts_by_bus_group,
            "unknown_files": unknown_files,
        },
    }
    if role_lexicon_ref is not None:
        stems_map["role_lexicon_ref"] = role_lexicon_ref

    return stems_map, explanations


def classify_stems(
    stems_index: dict[str, Any],
    roles: dict[str, Any],
    role_lexicon: dict[str, Any] | None = None,
    *,
    stems_index_ref: str = "stems_index.json",
    roles_ref: str = DEFAULT_ROLES_REF,
    role_lexicon_ref: str | None = None,
) -> dict[str, Any]:
    payload, _ = classify_stems_with_evidence(
        stems_index,
        roles,
        role_lexicon=role_lexicon,
        stems_index_ref=stems_index_ref,
        roles_ref=roles_ref,
        role_lexicon_ref=role_lexicon_ref,
    )
    return payload
