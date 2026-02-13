from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


@dataclass(frozen=True)
class CompiledRoleLexiconEntry:
    keywords: tuple[str, ...]
    regex: tuple[str, ...]
    compiled_regex: tuple[re.Pattern[str], ...]


COMMON_ROLE_LEXICON_REL_PATH = Path("ontology") / "role_lexicon_common.yaml"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load role lexicon mappings.")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(f"Failed to read {label} YAML from {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} YAML is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} YAML root must be a mapping: {path}")
    return payload


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _validate_payload_against_schema(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate role lexicon mappings.")

    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: (list(err.path), err.message),
    )
    if not errors:
        return

    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _known_role_ids(roles_payload: dict[str, Any]) -> list[str]:
    roles = roles_payload.get("roles")
    if not isinstance(roles, dict):
        return []
    return sorted(
        role_id
        for role_id, entry in roles.items()
        if (
            isinstance(role_id, str)
            and role_id != "_meta"
            and isinstance(entry, dict)
        )
    )


def _role_lexicon_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    role_lexicon = payload.get("role_lexicon")
    if not isinstance(role_lexicon, dict):
        return {}
    return {
        role_id: dict(entry)
        for role_id, entry in role_lexicon.items()
        if isinstance(role_id, str) and isinstance(entry, dict)
    }


def _normalize_keywords(raw_keywords: Any) -> tuple[str, ...]:
    if not isinstance(raw_keywords, list):
        return ()
    normalized = {
        keyword.strip().lower()
        for keyword in raw_keywords
        if isinstance(keyword, str) and keyword.strip()
    }
    return tuple(sorted(normalized))


def _normalize_regex(raw_regex: Any) -> tuple[str, ...]:
    if not isinstance(raw_regex, list):
        return ()
    normalized = {
        pattern.strip()
        for pattern in raw_regex
        if isinstance(pattern, str) and pattern.strip()
    }
    return tuple(sorted(normalized))


def _validate_role_ids(
    role_lexicon: dict[str, dict[str, Any]],
    *,
    known_role_ids: list[str],
) -> None:
    unknown = sorted(role_id for role_id in role_lexicon.keys() if role_id not in known_role_ids)
    if not unknown:
        return
    unknown_label = ", ".join(unknown)
    if known_role_ids:
        raise ValueError(
            f"Unknown role_id in role_lexicon: {unknown_label}. "
            f"Known role_ids: {', '.join(known_role_ids)}"
        )
    raise ValueError(
        f"Unknown role_id in role_lexicon: {unknown_label}. No roles are available."
    )


def _compile_role_lexicon_entries(
    role_lexicon: dict[str, dict[str, Any]],
) -> dict[str, CompiledRoleLexiconEntry]:
    compiled: dict[str, CompiledRoleLexiconEntry] = {}
    invalid_patterns: list[str] = []

    for role_id in sorted(role_lexicon.keys()):
        entry = role_lexicon[role_id]
        keywords = _normalize_keywords(entry.get("keywords"))
        regex_patterns = _normalize_regex(entry.get("regex"))

        compiled_regex: list[re.Pattern[str]] = []
        for pattern in regex_patterns:
            try:
                compiled_regex.append(re.compile(pattern))
            except re.error:
                invalid_patterns.append(f"{role_id}: {pattern}")
        compiled[role_id] = CompiledRoleLexiconEntry(
            keywords=keywords,
            regex=regex_patterns,
            compiled_regex=tuple(compiled_regex),
        )

    if invalid_patterns:
        raise ValueError(
            "Role lexicon regex patterns failed to compile: "
            + ", ".join(sorted(invalid_patterns))
        )
    return compiled


def _load_compiled_role_lexicon(
    path: Path,
    *,
    label: str,
    roles_payload: dict[str, Any] | None = None,
) -> dict[str, CompiledRoleLexiconEntry]:
    if roles_payload is None:
        from mmo.core.roles import load_roles  # noqa: WPS433

        roles_payload = load_roles()

    payload = _load_yaml_object(path, label=label)
    _validate_payload_against_schema(
        payload,
        schema_path=_repo_root() / "schemas" / "role_lexicon.schema.json",
        payload_name=label,
    )

    role_lexicon = _role_lexicon_map(payload)
    _validate_role_ids(role_lexicon, known_role_ids=_known_role_ids(roles_payload))
    return _compile_role_lexicon_entries(role_lexicon)


def load_role_lexicon(
    path: Path,
    *,
    roles_payload: dict[str, Any] | None = None,
) -> dict[str, CompiledRoleLexiconEntry]:
    return _load_compiled_role_lexicon(
        path,
        label="Role lexicon",
        roles_payload=roles_payload,
    )


def load_common_role_lexicon(
    path: Path | None = None,
    *,
    roles_payload: dict[str, Any] | None = None,
) -> dict[str, CompiledRoleLexiconEntry]:
    common_path = path if isinstance(path, Path) else _repo_root() / COMMON_ROLE_LEXICON_REL_PATH
    return _load_compiled_role_lexicon(
        common_path,
        label="Common role lexicon",
        roles_payload=roles_payload,
    )


def merge_role_lexicons(
    *lexicons: dict[str, CompiledRoleLexiconEntry] | None,
) -> dict[str, CompiledRoleLexiconEntry]:
    merged_keywords: dict[str, set[str]] = {}
    merged_regex: dict[str, set[str]] = {}

    for lexicon in lexicons:
        if not isinstance(lexicon, dict):
            continue
        for role_id in sorted(lexicon.keys()):
            entry = lexicon.get(role_id)
            if not isinstance(role_id, str) or not isinstance(entry, CompiledRoleLexiconEntry):
                continue
            merged_keywords.setdefault(role_id, set()).update(entry.keywords)
            merged_regex.setdefault(role_id, set()).update(entry.regex)

    merged_entries: dict[str, dict[str, Any]] = {}
    all_role_ids = sorted(set(merged_keywords.keys()) | set(merged_regex.keys()))
    for role_id in all_role_ids:
        merged_entries[role_id] = {
            "keywords": sorted(merged_keywords.get(role_id, set())),
            "regex": sorted(merged_regex.get(role_id, set())),
        }
    return _compile_role_lexicon_entries(merged_entries)


# ---------------------------------------------------------------------------
# Merge suggestions into a user role lexicon (keywords only, no regex).
# ---------------------------------------------------------------------------

_DIGIT_ONLY_RE = re.compile(r"^\d+$")


def _is_valid_keyword(token: str) -> bool:
    """Return True if the token passes default hygiene (len>=2, not digit-only)."""
    return len(token) >= 2 and not _DIGIT_ONLY_RE.match(token)


def merge_suggestions_into_lexicon(
    suggestions: dict[str, Any],
    *,
    base: dict[str, Any] | None = None,
    deny: frozenset[str] | None = None,
    allow: frozenset[str] | None = None,
    max_per_role: int = 100,
) -> dict[str, Any]:
    """Merge a suggestions YAML payload into a base role_lexicon YAML payload.

    Returns a dict with:
      - ``merged``: the merged role_lexicon payload (``{"role_lexicon": {...}}``).
      - ``roles_added_count``: number of roles that gained new keywords.
      - ``keywords_added_count``: total new keywords added.
      - ``keywords_skipped``: dict mapping skip reason to sorted list of tokens.
      - ``max_per_role_applied``: True if any role was clamped.
    """
    deny_set = deny if deny is not None else frozenset()
    allow_set = allow if allow is not None else None

    # Parse base lexicon keywords.
    base_keywords: dict[str, set[str]] = {}
    if isinstance(base, dict):
        base_rl = base.get("role_lexicon")
        if isinstance(base_rl, dict):
            for role_id, entry in sorted(base_rl.items()):
                if isinstance(entry, dict):
                    kws = entry.get("keywords")
                    if isinstance(kws, list):
                        base_keywords[role_id] = {
                            k.strip().lower()
                            for k in kws
                            if isinstance(k, str) and k.strip()
                        }

    # Parse suggestions keywords.
    sugg_rl = suggestions.get("role_lexicon")
    if not isinstance(sugg_rl, dict):
        sugg_rl = {}

    skipped_deny: list[str] = []
    skipped_allow_miss: list[str] = []
    skipped_duplicate: list[str] = []
    skipped_clamp: list[str] = []
    skipped_invalid: list[str] = []

    merged_keywords: dict[str, list[str]] = {}
    roles_with_additions: set[str] = set()
    total_added = 0
    max_per_role_applied = False

    for role_id in sorted(sugg_rl.keys()):
        entry = sugg_rl[role_id]
        if not isinstance(entry, dict):
            continue
        raw_kws = entry.get("keywords")
        if not isinstance(raw_kws, list):
            continue

        existing = base_keywords.get(role_id, set())
        # Start merged result with existing base keywords.
        result_kws: list[str] = sorted(existing)
        candidates: list[str] = []

        for raw in raw_kws:
            if not isinstance(raw, str):
                continue
            token = raw.strip().lower()
            if not token:
                continue

            # Deny filter.
            if token in deny_set:
                skipped_deny.append(token)
                continue

            # Allow filter: if provided, only include tokens in the allow set.
            if allow_set is not None and token not in allow_set:
                skipped_allow_miss.append(token)
                continue

            # Duplicate check.
            if token in existing:
                skipped_duplicate.append(token)
                continue

            # Validity check (allow-list can override this).
            if allow_set is None and not _is_valid_keyword(token):
                skipped_invalid.append(token)
                continue

            candidates.append(token)

        # Dedup candidates themselves.
        seen: set[str] = set()
        deduped: list[str] = []
        for c in sorted(candidates):
            if c not in seen:
                seen.add(c)
                deduped.append(c)

        # Clamp.
        if len(deduped) > max_per_role:
            max_per_role_applied = True
            skipped_clamp.extend(deduped[max_per_role:])
            deduped = deduped[:max_per_role]

        if deduped:
            roles_with_additions.add(role_id)
            total_added += len(deduped)
            result_kws = sorted(set(result_kws) | set(deduped))

        if result_kws:
            merged_keywords[role_id] = result_kws

    # Include base roles that had no suggestions.
    for role_id, kws in sorted(base_keywords.items()):
        if role_id not in merged_keywords and kws:
            merged_keywords[role_id] = sorted(kws)

    # Build output payload.
    merged_rl: dict[str, dict[str, list[str]]] = {}
    for role_id in sorted(merged_keywords.keys()):
        merged_rl[role_id] = {"keywords": merged_keywords[role_id]}

    keywords_skipped: dict[str, list[str]] = {}
    if skipped_deny:
        keywords_skipped["deny"] = sorted(set(skipped_deny))
    if skipped_allow_miss:
        keywords_skipped["allow_miss"] = sorted(set(skipped_allow_miss))
    if skipped_duplicate:
        keywords_skipped["duplicate"] = sorted(set(skipped_duplicate))
    if skipped_clamp:
        keywords_skipped["clamp"] = sorted(set(skipped_clamp))
    if skipped_invalid:
        keywords_skipped["invalid"] = sorted(set(skipped_invalid))

    return {
        "merged": {"role_lexicon": merged_rl},
        "roles_added_count": len(roles_with_additions),
        "keywords_added_count": total_added,
        "keywords_skipped": keywords_skipped,
        "max_per_role_applied": max_per_role_applied,
    }


def render_role_lexicon_yaml(payload: dict[str, Any]) -> str:
    """Render a role_lexicon payload as deterministic YAML."""
    role_lexicon = payload.get("role_lexicon")
    if not isinstance(role_lexicon, dict) or not role_lexicon:
        return "role_lexicon: {}\n"

    lines = ["role_lexicon:"]
    for role_id in sorted(role_lexicon.keys()):
        entry = role_lexicon[role_id]
        lines.append(f"  {role_id}:")
        keywords = entry.get("keywords") if isinstance(entry, dict) else None
        keyword_values = (
            sorted(item for item in keywords if isinstance(item, str) and item)
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
