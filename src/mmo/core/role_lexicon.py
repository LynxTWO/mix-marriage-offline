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
