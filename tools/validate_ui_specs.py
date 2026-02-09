"""Validate GUI/UI copy/help specs and cross-references."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


HELP_ID_PATTERN = re.compile(r"\bHELP\.[A-Z0-9_.]+\b")


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _load_yaml(path: Path, errors: list[str]) -> Any | None:
    if yaml is None:
        errors.append("PyYAML is not installed; cannot parse YAML files.")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        errors.append(f"Failed to read YAML file {path}: {exc}")
    except yaml.YAMLError as exc:
        errors.append(f"Failed to parse YAML file {path}: {exc}")
    return None


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"Failed to read schema file {path}: {exc}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"Failed to parse schema JSON {path}: {exc}")
        return None
    if not isinstance(schema, dict):
        errors.append(f"Schema root must be an object: {path}")
        return None
    return schema


def _validate_schema(
    payload_name: str,
    payload: Any,
    schema: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if schema is None:
        return
    if jsonschema is None:
        errors.append("jsonschema is not installed; cannot run schema validation.")
        return

    validator = jsonschema.Draft202012Validator(schema)
    validation_errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: list(err.absolute_path),
    )
    for err in validation_errors:
        path = ".".join(str(part) for part in err.absolute_path) or "$"
        errors.append(f"{payload_name} schema invalid at {path}: {err.message}")


def _default_locale(ui_copy_payload: dict[str, Any]) -> str | None:
    default_locale = ui_copy_payload.get("default_locale")
    if isinstance(default_locale, str) and default_locale.strip():
        return default_locale.strip()
    return None


def _ui_copy_entries(ui_copy_payload: Any) -> dict[str, Any]:
    if not isinstance(ui_copy_payload, dict):
        return {}

    locales = ui_copy_payload.get("locales")
    if not isinstance(locales, dict):
        return {}

    preferred_locale = _default_locale(ui_copy_payload)
    locale_candidates: list[str] = []
    if preferred_locale is not None:
        locale_candidates.append(preferred_locale)
    locale_candidates.extend(
        locale_id
        for locale_id in sorted(locales.keys())
        if isinstance(locale_id, str) and locale_id not in locale_candidates
    )

    for locale_id in locale_candidates:
        locale_payload = locales.get(locale_id)
        if not isinstance(locale_payload, dict):
            continue
        entries = locale_payload.get("entries")
        if isinstance(entries, dict):
            return entries
    return {}


def _required_ui_copy_keys(gui_design_payload: Any) -> set[str]:
    if not isinstance(gui_design_payload, dict):
        return set()

    required: set[str] = set()

    badges = (
        gui_design_payload.get("micro_interactions", {})
        .get("badges", {})
        .get("allowed", [])
    )
    if isinstance(badges, list):
        for badge in badges:
            if isinstance(badge, str) and badge.strip():
                required.add(f"COPY.BADGE.{badge.strip()}")

    screen_templates = gui_design_payload.get("screen_templates", {})
    if isinstance(screen_templates, dict):
        for screen_name in screen_templates.keys():
            if isinstance(screen_name, str) and screen_name.strip():
                required.add(f"COPY.NAV.{screen_name.strip()}")

    return required


def _ui_copy_texts(ui_copy_payload: Any) -> list[str]:
    if not isinstance(ui_copy_payload, dict):
        return []

    locales = ui_copy_payload.get("locales")
    if not isinstance(locales, dict):
        return []

    texts: list[str] = []
    for locale_payload in locales.values():
        if not isinstance(locale_payload, dict):
            continue
        entries = locale_payload.get("entries")
        if not isinstance(entries, dict):
            continue
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            for field in ("text", "tooltip", "long"):
                value = entry.get(field)
                if isinstance(value, str):
                    texts.append(value)
    return texts


def _missing_glossary_terms(gui_design_payload: Any, ui_copy_payload: Any) -> list[str]:
    if not isinstance(gui_design_payload, dict):
        return []

    preferred_terms = gui_design_payload.get("glossary", {}).get("preferred_terms", [])
    if not isinstance(preferred_terms, list):
        return []

    text_blob = "\n".join(_ui_copy_texts(ui_copy_payload)).lower()
    missing: list[str] = []
    for term in preferred_terms:
        if isinstance(term, str) and term and term.lower() not in text_blob:
            missing.append(term)
    return sorted(set(missing))


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
        return
    if isinstance(value, list):
        for nested in value:
            yield from _iter_strings(nested)


def _referenced_help_ids(*payloads: Any) -> set[str]:
    refs: set[str] = set()
    for payload in payloads:
        for text in _iter_strings(payload):
            refs.update(HELP_ID_PATTERN.findall(text))
    return refs


def _known_help_ids(help_payload: Any) -> set[str]:
    if not isinstance(help_payload, dict):
        return set()
    entries = help_payload.get("entries")
    if not isinstance(entries, dict):
        return set()
    return {
        help_id
        for help_id in entries.keys()
        if isinstance(help_id, str) and help_id.strip()
    }


def validate_ui_specs(
    *,
    gui_design_path: Path,
    ui_copy_path: Path,
    help_path: Path,
    gui_design_schema_path: Path,
    ui_copy_schema_path: Path,
    help_schema_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []

    gui_design_payload = _load_yaml(gui_design_path, errors)
    ui_copy_payload = _load_yaml(ui_copy_path, errors)
    help_payload = _load_yaml(help_path, errors)

    gui_design_schema = _load_json(gui_design_schema_path, errors)
    ui_copy_schema = _load_json(ui_copy_schema_path, errors)
    help_schema = _load_json(help_schema_path, errors)

    _validate_schema("gui_design.yaml", gui_design_payload, gui_design_schema, errors)
    _validate_schema("ui_copy.yaml", ui_copy_payload, ui_copy_schema, errors)
    _validate_schema("help.yaml", help_payload, help_schema, errors)

    required_ui_copy_keys = _required_ui_copy_keys(gui_design_payload)
    available_ui_copy_keys = set(_ui_copy_entries(ui_copy_payload).keys())
    missing_ui_copy_keys = sorted(required_ui_copy_keys - available_ui_copy_keys)

    referenced_help_ids = _referenced_help_ids(gui_design_payload, ui_copy_payload)
    missing_help_ids = sorted(referenced_help_ids - _known_help_ids(help_payload))

    missing_glossary_terms = _missing_glossary_terms(gui_design_payload, ui_copy_payload)

    ok = not errors and not missing_ui_copy_keys and not missing_help_ids
    result: dict[str, Any] = {
        "ok": ok,
        "missing_ui_copy_keys": missing_ui_copy_keys,
        "missing_help_ids": missing_help_ids,
        "missing_glossary_terms": missing_glossary_terms,
    }
    if errors:
        result["errors"] = errors
    return result


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate GUI design/UI copy/help schemas and cross-references."
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing ontology/ and schemas/.",
    )
    parser.add_argument(
        "--gui-design",
        default="ontology/gui_design.yaml",
        help="Path to gui_design YAML (absolute or relative to --repo-root).",
    )
    parser.add_argument(
        "--ui-copy",
        default="ontology/ui_copy.yaml",
        help="Path to ui_copy YAML (absolute or relative to --repo-root).",
    )
    parser.add_argument(
        "--help-registry",
        default="ontology/help.yaml",
        help="Path to help YAML (absolute or relative to --repo-root).",
    )
    parser.add_argument(
        "--gui-design-schema",
        default="schemas/gui_design.schema.json",
        help="Path to GUI design schema (absolute or relative to --repo-root).",
    )
    parser.add_argument(
        "--ui-copy-schema",
        default="schemas/ui_copy.schema.json",
        help="Path to UI copy schema (absolute or relative to --repo-root).",
    )
    parser.add_argument(
        "--help-schema",
        default="schemas/help_registry.schema.json",
        help="Path to help schema (absolute or relative to --repo-root).",
    )
    args = parser.parse_args()

    root = Path(args.repo_root)
    result = validate_ui_specs(
        gui_design_path=_resolve_path(args.gui_design, repo_root=root),
        ui_copy_path=_resolve_path(args.ui_copy, repo_root=root),
        help_path=_resolve_path(args.help_registry, repo_root=root),
        gui_design_schema_path=_resolve_path(args.gui_design_schema, repo_root=root),
        ui_copy_schema_path=_resolve_path(args.ui_copy_schema, repo_root=root),
        help_schema_path=_resolve_path(args.help_schema, repo_root=root),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
