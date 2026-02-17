"""Validate docs milestone registry for deterministic status tracking."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


DEFAULT_ALLOWED_STATES: tuple[str, ...] = (
    "blocked",
    "done",
    "in_progress",
    "planned",
)


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_doc_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _milestone_label(index: int, milestone_id: str | None) -> str:
    if milestone_id is None:
        return f"milestones[{index}]"
    return f"milestones[{index}] ('{milestone_id}')"


def _parse_link(value: str) -> tuple[str, str] | None:
    if "#" not in value:
        return None
    path_text, section = value.split("#", 1)
    normalized_path = _normalize_doc_path(path_text)
    section = section.strip()
    if not normalized_path or not section:
        return None
    return normalized_path, section


def validate_milestones(
    *,
    repo_root: Path,
    milestones_path: Path,
    allowed_states: tuple[str, ...] = DEFAULT_ALLOWED_STATES,
) -> dict[str, Any]:
    errors: list[str] = []
    milestone_ids: list[str] = []
    milestone_count = 0

    display_path = _display_path(milestones_path, repo_root=repo_root)
    allowed_states_text = ", ".join(allowed_states)

    if yaml is None:
        errors.append("PyYAML is not installed; cannot parse milestones YAML.")
        return {
            "ok": False,
            "path": display_path,
            "allowed_states": list(allowed_states),
            "milestone_count": 0,
            "milestone_ids": [],
            "errors": errors,
        }

    if not milestones_path.is_file():
        errors.append(f"Milestones file is missing: {display_path}")
        return {
            "ok": False,
            "path": display_path,
            "allowed_states": list(allowed_states),
            "milestone_count": 0,
            "milestone_ids": [],
            "errors": errors,
        }

    try:
        payload = yaml.safe_load(milestones_path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"Failed to read milestones file {display_path}: {exc}")
        return {
            "ok": False,
            "path": display_path,
            "allowed_states": list(allowed_states),
            "milestone_count": 0,
            "milestone_ids": [],
            "errors": errors,
        }
    except yaml.YAMLError as exc:
        errors.append(f"Failed to parse milestones YAML {display_path}: {exc}")
        return {
            "ok": False,
            "path": display_path,
            "allowed_states": list(allowed_states),
            "milestone_count": 0,
            "milestone_ids": [],
            "errors": errors,
        }

    if not isinstance(payload, dict):
        errors.append(f"{display_path} root must be a mapping with key 'milestones'.")
        payload = {}

    milestones = payload.get("milestones")
    if not isinstance(milestones, list):
        errors.append(f"{display_path} must define 'milestones' as a list.")
        milestones = []

    id_counts: dict[str, int] = {}
    for index, item in enumerate(milestones):
        milestone_count += 1
        if not isinstance(item, dict):
            errors.append(f"milestones[{index}] must be a mapping.")
            continue

        raw_id = item.get("id")
        milestone_id: str | None = None
        if isinstance(raw_id, str) and raw_id.strip():
            milestone_id = raw_id.strip()
            milestone_ids.append(milestone_id)
            id_counts[milestone_id] = id_counts.get(milestone_id, 0) + 1
        else:
            errors.append(f"milestones[{index}].id must be a non-empty string.")

        label = _milestone_label(index, milestone_id)

        raw_state = item.get("state")
        if not isinstance(raw_state, str) or not raw_state.strip():
            errors.append(f"{label}.state must be a non-empty string.")
        else:
            state = raw_state.strip()
            if state not in allowed_states:
                errors.append(
                    f"{label}.state must be one of [{allowed_states_text}]; got '{state}'."
                )

        raw_links = item.get("links")
        if not isinstance(raw_links, list) or not raw_links:
            errors.append(f"{label}.links must be a non-empty list.")
            continue

        for link_index, raw_link in enumerate(raw_links):
            if not isinstance(raw_link, str) or not raw_link.strip():
                errors.append(f"{label}.links[{link_index}] must be a non-empty string.")
                continue

            link_value = raw_link.strip()
            parsed = _parse_link(link_value)
            if parsed is None:
                errors.append(
                    f"{label}.links[{link_index}] must include a '#<section>' anchor."
                )
                continue

            doc_path_text, _section = parsed
            if not doc_path_text.startswith("docs/"):
                errors.append(
                    f"{label}.links[{link_index}] must reference a docs/ file path; got '{doc_path_text}'."
                )
                continue

            doc_path = repo_root / Path(doc_path_text)
            if not doc_path.is_file():
                errors.append(
                    f"{label}.links[{link_index}] references missing docs file: {doc_path_text}"
                )

    for milestone_id in sorted(id_counts):
        if id_counts[milestone_id] > 1:
            errors.append(f"Duplicate milestone id: {milestone_id}.")

    errors = sorted(errors)
    return {
        "ok": not errors,
        "path": display_path,
        "allowed_states": list(allowed_states),
        "milestone_count": milestone_count,
        "milestone_ids": sorted(set(milestone_ids)),
        "errors": errors,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate machine-readable milestone definitions."
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing docs/ and milestones YAML.",
    )
    parser.add_argument(
        "--milestones",
        default="docs/milestones.yaml",
        help="Path to milestones YAML (absolute or relative to --repo-root).",
    )
    args = parser.parse_args()

    root = Path(args.repo_root)
    milestones_path = _resolve_path(args.milestones, repo_root=root)
    result = validate_milestones(
        repo_root=root,
        milestones_path=milestones_path,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
