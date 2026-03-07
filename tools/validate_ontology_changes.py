"""Validate ontology ID changes are additive unless guarded by migration policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_MANIFEST_REL_PATH = "ontology/ontology.yaml"
MIGRATIONS_DIR_REL_PATH = "docs/ontology_migrations"

ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*(?:\.[A-Z0-9_]+)+$")
SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class DefinitionEntry:
    id_value: str
    file_path: str
    deprecated: bool
    replaced_by: str | None


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )


def _is_git_repo(repo_root: Path) -> bool:
    probe = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def _resolve_base_ref(repo_root: Path, requested: str) -> str | None:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
        if "/" not in requested:
            candidates.append(f"origin/{requested}")

    github_base_ref = os.getenv("GITHUB_BASE_REF", "").strip()
    if github_base_ref:
        candidates.append(github_base_ref)
        candidates.append(f"origin/{github_base_ref}")

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        probe = _run_git(repo_root, ["rev-parse", "--verify", "--quiet", candidate])
        if probe.returncode == 0:
            return candidate
    return None


def _load_yaml_text(text: str, *, file_path: str, errors: list[str]) -> Any | None:
    if yaml is None:
        errors.append("PyYAML is not installed; cannot parse ontology YAML.")
        return None
    try:
        parsed = yaml.safe_load(text)
    except Exception as exc:  # pragma: no cover - parser output varies
        errors.append(f"Failed to parse YAML in {file_path}: {exc}")
        return None
    return parsed


def _walk_path(node: Any, path: tuple[str, ...]) -> list[Any]:
    if not path:
        return [node]
    if not isinstance(node, dict):
        return []
    head = path[0]
    tail = path[1:]
    if head == "*":
        out: list[Any] = []
        for value in node.values():
            out.extend(_walk_path(value, tail))
        return out
    if head not in node:
        return []
    return _walk_path(node[head], tail)


def _definition_entry(
    *,
    id_value: str,
    file_path: str,
    payload: Any,
) -> DefinitionEntry:
    deprecated = False
    replaced_by: str | None = None
    if isinstance(payload, dict):
        deprecated = payload.get("deprecated") is True
        raw_replaced_by = payload.get("replaced_by")
        if isinstance(raw_replaced_by, str) and raw_replaced_by.strip():
            replaced_by = raw_replaced_by.strip()
    return DefinitionEntry(
        id_value=id_value,
        file_path=file_path,
        deprecated=deprecated,
        replaced_by=replaced_by,
    )


def _collect_map_keys(
    *,
    root: Any,
    file_path: str,
    map_path: tuple[str, ...],
    required_prefix: str,
) -> list[DefinitionEntry]:
    found: list[DefinitionEntry] = []
    for candidate_map in _walk_path(root, map_path):
        if not isinstance(candidate_map, dict):
            continue
        for raw_key, payload in sorted(candidate_map.items(), key=lambda item: str(item[0])):
            if not isinstance(raw_key, str):
                continue
            if not raw_key.startswith(required_prefix):
                continue
            if not ID_PATTERN.match(raw_key):
                continue
            found.append(
                _definition_entry(
                    id_value=raw_key,
                    file_path=file_path,
                    payload=payload,
                )
            )
    return found


def _collect_list_field(
    *,
    root: Any,
    file_path: str,
    list_path: tuple[str, ...],
    field_name: str,
    required_prefix: str,
) -> list[DefinitionEntry]:
    found: list[DefinitionEntry] = []
    for candidate_list in _walk_path(root, list_path):
        if not isinstance(candidate_list, list):
            continue
        for item in candidate_list:
            if not isinstance(item, dict):
                continue
            raw_value = item.get(field_name)
            if not isinstance(raw_value, str):
                continue
            id_value = raw_value.strip()
            if not id_value.startswith(required_prefix):
                continue
            if not ID_PATTERN.match(id_value):
                continue
            found.append(
                _definition_entry(
                    id_value=id_value,
                    file_path=file_path,
                    payload=item,
                )
            )
    return found


def _collect_scalar_field(
    *,
    root: Any,
    file_path: str,
    field_path: tuple[str, ...],
    required_prefix: str,
) -> list[DefinitionEntry]:
    found: list[DefinitionEntry] = []
    for value in _walk_path(root, field_path):
        if not isinstance(value, str):
            continue
        id_value = value.strip()
        if not id_value.startswith(required_prefix):
            continue
        if not ID_PATTERN.match(id_value):
            continue
        found.append(
            DefinitionEntry(
                id_value=id_value,
                file_path=file_path,
                deprecated=False,
                replaced_by=None,
            )
        )
    return found


def _extract_definitions_from_document(file_path: str, payload: Any) -> list[DefinitionEntry]:
    definitions: list[DefinitionEntry] = []

    map_specs: list[tuple[tuple[str, ...], str]] = []
    list_specs: list[tuple[tuple[str, ...], str, str]] = []
    scalar_specs: list[tuple[tuple[str, ...], str]] = []

    if file_path == "ontology/actions.yaml":
        map_specs.append((("actions",), "ACTION."))
    elif file_path == "ontology/evidence.yaml":
        map_specs.append((("evidence",), "EVID."))
    elif file_path == "ontology/features.yaml":
        map_specs.append((("features",), "FEATURE."))
    elif file_path == "ontology/issues.yaml":
        map_specs.append((("issues",), "ISSUE."))
    elif file_path == "ontology/layouts.yaml":
        map_specs.append((("layouts",), "LAYOUT."))
    elif file_path == "ontology/params.yaml":
        map_specs.append((("params",), "PARAM."))
    elif file_path == "ontology/reasons.yaml":
        map_specs.append((("reasons",), "REASON."))
    elif file_path == "ontology/roles.yaml":
        map_specs.append((("roles",), "ROLE."))
    elif file_path == "ontology/speakers.yaml":
        map_specs.append((("speakers",), "SPK."))
    elif file_path == "ontology/units.yaml":
        map_specs.append((("units",), "UNIT."))
    elif file_path == "ontology/loudness_profiles.yaml":
        map_specs.append((("profiles",), "LOUD."))
    elif file_path == "ontology/lfe_derivation_profiles.yaml":
        map_specs.append((("profiles",), "LFE_DERIVE."))
    elif file_path == "ontology/profiles.yaml":
        map_specs.append((("profiles",), "PROFILE."))
    elif file_path == "ontology/translation_profiles.yaml":
        map_specs.append((tuple(), "TRANS."))
    elif file_path == "ontology/scene_locks.yaml":
        map_specs.append((("locks",), "LOCK."))
    elif file_path == "ontology/scene_templates.yaml":
        map_specs.append((("templates",), "TEMPLATE."))
    elif file_path == "ontology/intent_params.yaml":
        map_specs.append((("params",), "INTENT."))
    elif file_path == "ontology/help.yaml":
        map_specs.append((("entries",), "HELP."))
    elif file_path == "ontology/ui_copy.yaml":
        map_specs.append((("locales", "*", "entries"), "COPY."))
    elif file_path == "ontology/gates.yaml":
        map_specs.append((("gates",), "GATE."))
    elif file_path == "ontology/render_targets.yaml":
        list_specs.append((("targets",), "target_id", "TARGET."))
    elif file_path == "ontology/plugin_index.yaml":
        list_specs.append((("entries",), "plugin_id", "PLUGIN."))
        scalar_specs.append((("market_id",), "MARKET."))
    elif file_path == "ontology/policies/downmix.yaml":
        map_specs.append((("downmix", "policies"), "POLICY.DOWNMIX."))
    elif file_path == "ontology/policies/gates.yaml":
        map_specs.append((("gates",), "GATE."))
        scalar_specs.append((("gates", "_meta", "policy_id"), "POLICY.GATES."))
    elif file_path == "ontology/policies/authority_profiles.yaml":
        map_specs.append((("profiles",), "PROFILE."))
        scalar_specs.append(
            (("profiles", "_meta", "policy_id"), "POLICY.AUTHORITY_PROFILES.")
        )
    elif file_path.startswith("ontology/policies/downmix_policies/"):
        map_specs.append((("downmix_policy_pack", "matrices"), "DMX."))
        scalar_specs.append((("downmix_policy_pack", "policy_id"), "POLICY.DOWNMIX."))

    for map_path, required_prefix in map_specs:
        definitions.extend(
            _collect_map_keys(
                root=payload,
                file_path=file_path,
                map_path=map_path,
                required_prefix=required_prefix,
            )
        )
    for list_path, field_name, required_prefix in list_specs:
        definitions.extend(
            _collect_list_field(
                root=payload,
                file_path=file_path,
                list_path=list_path,
                field_name=field_name,
                required_prefix=required_prefix,
            )
        )
    for field_path, required_prefix in scalar_specs:
        definitions.extend(
            _collect_scalar_field(
                root=payload,
                file_path=file_path,
                field_path=field_path,
                required_prefix=required_prefix,
            )
        )

    return definitions


def _is_ontology_yaml_path(path: str) -> bool:
    lower = path.lower()
    if not lower.startswith("ontology/"):
        return False
    return lower.endswith(".yaml") or lower.endswith(".yml")


def _load_current_documents(
    *,
    repo_root: Path,
    errors: list[str],
) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    ontology_root = repo_root / "ontology"
    if not ontology_root.exists():
        errors.append("Missing ontology directory: ontology/")
        return documents
    for path in sorted(ontology_root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(repo_root).as_posix()
        if not _is_ontology_yaml_path(rel_path):
            continue
        text = path.read_text(encoding="utf-8")
        payload = _load_yaml_text(text, file_path=rel_path, errors=errors)
        if payload is None:
            continue
        documents[rel_path] = payload
    return documents


def _load_base_documents(
    *,
    repo_root: Path,
    base_ref: str,
    errors: list[str],
) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    listed = _run_git(
        repo_root,
        ["ls-tree", "-r", "--name-only", base_ref, "--", "ontology"],
    )
    if listed.returncode != 0:
        stderr = listed.stderr.strip()
        errors.append(
            "Failed to list ontology files from base ref "
            f"{base_ref}: {stderr or 'unknown git error'}"
        )
        return documents
    for rel_path in sorted(line.strip() for line in listed.stdout.splitlines() if line.strip()):
        if not _is_ontology_yaml_path(rel_path):
            continue
        shown = _run_git(repo_root, ["show", f"{base_ref}:{rel_path}"])
        if shown.returncode != 0:
            stderr = shown.stderr.strip()
            errors.append(
                f"Failed to read {rel_path} from {base_ref}: {stderr or 'unknown git error'}"
            )
            continue
        payload = _load_yaml_text(shown.stdout, file_path=rel_path, errors=errors)
        if payload is None:
            continue
        documents[rel_path] = payload
    return documents


def _collect_definition_map(documents: dict[str, Any]) -> dict[str, list[DefinitionEntry]]:
    by_id: dict[str, list[DefinitionEntry]] = {}
    for file_path, payload in sorted(documents.items()):
        for entry in _extract_definitions_from_document(file_path, payload):
            by_id.setdefault(entry.id_value, []).append(entry)
    return by_id


def _ontology_version_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    ontology_section = payload.get("ontology")
    if isinstance(ontology_section, dict):
        raw_version = ontology_section.get("ontology_version")
        if isinstance(raw_version, str) and raw_version.strip():
            return raw_version.strip()
    raw_version = payload.get("ontology_version")
    if isinstance(raw_version, str) and raw_version.strip():
        return raw_version.strip()
    return None


def _parse_semver(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = SEMVER_PATTERN.match(value.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _version_is_bumped(base_version: str | None, current_version: str | None) -> bool | None:
    base_semver = _parse_semver(base_version)
    current_semver = _parse_semver(current_version)
    if base_semver is None or current_semver is None:
        return None
    return current_semver > base_semver


def _check_deprecations(
    *,
    current_entries: dict[str, list[DefinitionEntry]],
    current_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for id_value in sorted(current_entries.keys()):
        entries = current_entries[id_value]
        for entry in entries:
            if not entry.deprecated:
                continue
            if not entry.replaced_by:
                errors.append(
                    f"{id_value} is deprecated in {entry.file_path} but missing replaced_by."
                )
                continue
            if entry.replaced_by == id_value:
                errors.append(
                    f"{id_value} in {entry.file_path} cannot replace itself."
                )
                continue
            if entry.replaced_by not in current_ids:
                errors.append(
                    f"{id_value} in {entry.file_path} has replaced_by={entry.replaced_by} "
                    "which is not a known ontology ID."
                )
    return errors


def validate_ontology_changes(
    *,
    repo_root: Path,
    base_ref: str,
    require_base_ref: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    current_documents = _load_current_documents(repo_root=repo_root, errors=errors)
    current_entries = _collect_definition_map(current_documents)
    current_ids = set(current_entries.keys())
    deprecation_errors = _check_deprecations(
        current_entries=current_entries,
        current_ids=current_ids,
    )
    errors.extend(deprecation_errors)

    current_manifest = current_documents.get(ONTOLOGY_MANIFEST_REL_PATH)
    current_version = _ontology_version_from_payload(current_manifest)
    if current_manifest is None:
        errors.append(f"Missing ontology manifest: {ONTOLOGY_MANIFEST_REL_PATH}")
    elif current_version is None:
        errors.append(
            "Missing ontology version in ontology/ontology.yaml "
            "(expected ontology.ontology_version)."
        )

    base_version: str | None = None
    resolved_base_ref: str | None = None
    skipped_diff = False
    removed_ids: list[str] = []
    added_ids: list[str] = []
    migration_note_path: str | None = None

    if not _is_git_repo(repo_root):
        if require_base_ref:
            errors.append("Repository is not a git worktree; cannot diff ontology against base ref.")
        else:
            skipped_diff = True
            warnings.append("Not a git worktree; ontology diff against base ref was skipped.")
    else:
        resolved_base_ref = _resolve_base_ref(repo_root, base_ref)
        if resolved_base_ref is None:
            if require_base_ref:
                errors.append(
                    f"Could not resolve base ref '{base_ref}' (or origin/{base_ref})."
                )
            else:
                skipped_diff = True
                warnings.append(
                    f"Could not resolve base ref '{base_ref}'; ontology diff was skipped."
                )
        else:
            base_documents = _load_base_documents(
                repo_root=repo_root,
                base_ref=resolved_base_ref,
                errors=errors,
            )
            base_entries = _collect_definition_map(base_documents)
            base_ids = set(base_entries.keys())

            added_ids = sorted(current_ids - base_ids)
            removed_ids = sorted(base_ids - current_ids)

            base_manifest = base_documents.get(ONTOLOGY_MANIFEST_REL_PATH)
            base_version = _ontology_version_from_payload(base_manifest)
            if base_manifest is None:
                errors.append(
                    f"Missing {ONTOLOGY_MANIFEST_REL_PATH} in base ref {resolved_base_ref}."
                )
            elif base_version is None:
                errors.append(
                    "Missing ontology version in base ontology/ontology.yaml "
                    "(expected ontology.ontology_version)."
                )

            if removed_ids:
                bumped = _version_is_bumped(base_version, current_version)
                if bumped is None:
                    errors.append(
                        "Cannot validate ontology version bump: expected semver (X.Y.Z) in "
                        "current and base ontology manifest versions."
                    )
                elif not bumped:
                    errors.append(
                        "Removed ontology IDs require an ontology version bump. "
                        f"Base={base_version!r}, current={current_version!r}."
                    )

                if current_version:
                    migration_note = repo_root / MIGRATIONS_DIR_REL_PATH / f"{current_version}.md"
                    migration_note_path = migration_note.relative_to(repo_root).as_posix()
                    if not migration_note.is_file():
                        errors.append(
                            "Removed ontology IDs require a migration note at "
                            f"{migration_note_path}."
                        )
                    else:
                        migration_text = migration_note.read_text(encoding="utf-8").strip()
                        if not migration_text:
                            errors.append(f"Migration note is empty: {migration_note_path}")
                        missing_mentions = [
                            id_value for id_value in removed_ids if id_value not in migration_text
                        ]
                        if missing_mentions:
                            preview = ", ".join(missing_mentions[:10])
                            if len(missing_mentions) > 10:
                                preview += ", ..."
                            errors.append(
                                "Migration note must mention every removed ontology ID. Missing: "
                                f"{preview}"
                            )

    payload = {
        "ok": len(errors) == 0,
        "base_ref": base_ref,
        "resolved_base_ref": resolved_base_ref,
        "require_base_ref": require_base_ref,
        "skipped_diff": skipped_diff,
        "ontology_version": {
            "base": base_version,
            "current": current_version,
            "bumped": _version_is_bumped(base_version, current_version),
        },
        "counts": {
            "current_ids": len(current_ids),
            "added_ids": len(added_ids),
            "removed_ids": len(removed_ids),
        },
        "added_ids": added_ids,
        "removed_ids": removed_ids,
        "migration_note_path": migration_note_path,
        "errors": sorted(errors),
        "warnings": sorted(warnings),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate ontology ID changes are additive-only unless guarded by "
            "version bump + migration notes."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(SCRIPT_REPO_ROOT),
        help="Repository root containing ontology/ and docs/.",
    )
    parser.add_argument(
        "--base-ref",
        default="main",
        help="Git base ref used for ontology ID diff (default: main).",
    )
    parser.add_argument(
        "--require-base-ref",
        action="store_true",
        help="Fail if base ref cannot be resolved (recommended in CI).",
    )
    args = parser.parse_args()

    result = validate_ontology_changes(
        repo_root=Path(args.repo_root),
        base_ref=args.base_ref,
        require_base_ref=args.require_base_ref,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
