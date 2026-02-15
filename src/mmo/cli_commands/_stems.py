from __future__ import annotations

from pathlib import Path
from typing import Any

from mmo.cli_commands._helpers import _load_json_object, _validate_json_payload
from mmo.core.stems_index import build_stems_index
from mmo.resources import schemas_dir

__all__ = [
    "_render_stem_sets_text",
    "_path_ref",
    "_load_stems_index_for_classification",
    "_default_stems_overrides_template",
    "_load_stems_map",
    "_render_stems_map_text",
    "_build_stem_explain_payload",
    "_render_stem_explain_text",
]


def _render_stem_sets_text(stem_sets: list[dict[str, Any]]) -> str:
    lines = [f"found {len(stem_sets)} sets"]
    for item in stem_sets:
        rel_dir = item.get("rel_dir") if isinstance(item.get("rel_dir"), str) else ""
        file_count = item.get("file_count") if isinstance(item.get("file_count"), int) else 0
        why = item.get("why") if isinstance(item.get("why"), str) else ""
        lines.append(
            f"- {rel_dir or '.'}  file_count={file_count}  why={why or 'n/a'}"
        )
    return "\n".join(lines)


def _path_ref(path_value: str) -> str:
    return Path(path_value).as_posix()


def _load_stems_index_for_classification(
    *,
    repo_root: Path,
    index_path: str | None,
    root_path: str | None,
) -> tuple[dict[str, Any], str]:
    if isinstance(index_path, str) and index_path.strip():
        path = Path(index_path)
        payload = _load_json_object(path, label="Stems index")
        _validate_json_payload(
            payload,
            schema_path=schemas_dir() /"stems_index.schema.json",
            payload_name="Stems index",
        )
        return payload, _path_ref(index_path)

    if isinstance(root_path, str) and root_path.strip():
        payload = build_stems_index(Path(root_path), root_dir=root_path)
        _validate_json_payload(
            payload,
            schema_path=schemas_dir() /"stems_index.schema.json",
            payload_name="Stems index",
        )
        return payload, _path_ref(root_path)

    raise ValueError("Provide either --index or --root.")


def _default_stems_overrides_template() -> str:
    return (
        "# Stem assignment overrides.\n"
        "# Keep overrides sorted by override_id for deterministic behavior.\n"
        "# If multiple overrides match one file, the first sorted override_id wins.\n"
        "version: \"0.1.0\"\n"
        "overrides:\n"
        "  - override_id: \"OVERRIDE.001\"\n"
        "    match:\n"
        "      rel_path: \"stems/kick.wav\"\n"
        "    role_id: \"ROLE.DRUM.KICK\"\n"
        "    note: \"Optional note for reviewers\"\n"
        "  - override_id: \"OVERRIDE.010\"\n"
        "    match:\n"
        "      regex: \"^stems/vox.*\\\\.wav$\"\n"
        "    role_id: \"ROLE.VOCAL.LEAD\"\n"
    )


def _load_stems_map(*, repo_root: Path, map_path: Path) -> dict[str, Any]:
    payload = _load_json_object(map_path, label="Stems map")
    _validate_json_payload(
        payload,
        schema_path=schemas_dir() /"stems_map.schema.json",
        payload_name="Stems map",
    )
    return payload


def _render_stems_map_text(stems_map: dict[str, Any]) -> str:
    assignments = stems_map.get("assignments")
    rows = [("rel_path", "role_id", "conf", "bus_group")]

    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            rel_path = item.get("rel_path") if isinstance(item.get("rel_path"), str) else ""
            role_id = item.get("role_id") if isinstance(item.get("role_id"), str) else ""
            confidence = (
                item.get("confidence")
                if isinstance(item.get("confidence"), (int, float))
                else 0.0
            )
            bus_group = (
                item.get("bus_group")
                if isinstance(item.get("bus_group"), str) and item.get("bus_group")
                else "-"
            )
            rows.append((rel_path, role_id, f"{float(confidence):.3f}", bus_group))

    widths = [max(len(row[idx]) for row in rows) for idx in range(4)]
    lines = [
        (
            f"{rows[0][0]:<{widths[0]}} | {rows[0][1]:<{widths[1]}} | "
            f"{rows[0][2]:<{widths[2]}} | {rows[0][3]:<{widths[3]}}"
        ),
        (
            f"{'-' * widths[0]}-+-{'-' * widths[1]}-+-"
            f"{'-' * widths[2]}-+-{'-' * widths[3]}"
        ),
    ]
    for row in rows[1:]:
        lines.append(
            f"{row[0]:<{widths[0]}} | {row[1]:<{widths[1]}} | "
            f"{row[2]:<{widths[2]}} | {row[3]:<{widths[3]}}"
        )

    summary = stems_map.get("summary")
    if isinstance(summary, dict):
        unknown_files = (
            summary.get("unknown_files")
            if isinstance(summary.get("unknown_files"), int)
            else 0
        )
        lines.append(f"unknown_files={unknown_files}")
    return "\n".join(lines)


def _build_stem_explain_payload(
    *,
    stems_map: dict[str, Any],
    explanations: dict[str, dict[str, Any]],
    file_selector: str,
) -> dict[str, Any]:
    selector = file_selector.strip()
    if not selector:
        raise ValueError("Stem selector must be a non-empty string.")

    explanation = explanations.get(selector)
    if explanation is None:
        by_rel = sorted(
            (
                payload
                for payload in explanations.values()
                if isinstance(payload, dict) and payload.get("rel_path") == selector
            ),
            key=lambda item: (
                item.get("file_id") if isinstance(item.get("file_id"), str) else "",
                item.get("rel_path") if isinstance(item.get("rel_path"), str) else "",
            ),
        )
        if by_rel:
            explanation = by_rel[0]

    if explanation is None:
        known = sorted(
            {
                value
                for payload in explanations.values()
                if isinstance(payload, dict)
                for value in (payload.get("file_id"), payload.get("rel_path"))
                if isinstance(value, str) and value
            }
        )
        if known:
            raise ValueError(
                f"Unknown stem file selector: {selector}. "
                f"Known selectors: {', '.join(known)}"
            )
        raise ValueError(f"Unknown stem file selector: {selector}. No stems are available.")

    file_id = explanation.get("file_id") if isinstance(explanation.get("file_id"), str) else ""
    rel_path = (
        explanation.get("rel_path")
        if isinstance(explanation.get("rel_path"), str)
        else ""
    )

    selected_assignment: dict[str, Any] | None = None
    assignments = stems_map.get("assignments")
    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            assignment_file_id = item.get("file_id")
            assignment_rel_path = item.get("rel_path")
            if assignment_file_id == file_id or assignment_rel_path == rel_path:
                selected_assignment = item
                break

    if selected_assignment is None:
        selected_assignment = {}

    reasons = (
        selected_assignment.get("reasons")
        if isinstance(selected_assignment.get("reasons"), list)
        else explanation.get("selected_reasons", [])
    )
    derived_evidence: list[str] = []
    if isinstance(reasons, list):
        for reason in reasons:
            if not isinstance(reason, str):
                continue
            if not (
                reason.startswith("token_norm:")
                or reason.startswith("token_split:")
            ):
                continue
            if reason not in derived_evidence:
                derived_evidence.append(reason)

    return {
        "file_id": file_id,
        "rel_path": rel_path,
        "tokens": (
            explanation.get("tokens")
            if isinstance(explanation.get("tokens"), list)
            else []
        ),
        "folder_tokens": (
            explanation.get("folder_tokens")
            if isinstance(explanation.get("folder_tokens"), list)
            else []
        ),
        "role_id": (
            selected_assignment.get("role_id")
            if isinstance(selected_assignment.get("role_id"), str)
            else explanation.get("selected_role_id", "")
        ),
        "confidence": (
            selected_assignment.get("confidence")
            if isinstance(selected_assignment.get("confidence"), (int, float))
            else 0.0
        ),
        "bus_group": (
            selected_assignment.get("bus_group")
            if isinstance(selected_assignment.get("bus_group"), str)
            else None
        ),
        "link_group_id": (
            selected_assignment.get("link_group_id")
            if isinstance(selected_assignment.get("link_group_id"), str)
            else None
        ),
        "reasons": reasons if isinstance(reasons, list) else [],
        "derived_evidence": derived_evidence,
        "candidates": (
            explanation.get("candidates")
            if isinstance(explanation.get("candidates"), list)
            else []
        ),
    }


def _render_stem_explain_text(payload: dict[str, Any]) -> str:
    confidence = payload.get("confidence") if isinstance(payload.get("confidence"), (int, float)) else 0.0
    bus_group = payload.get("bus_group") if isinstance(payload.get("bus_group"), str) else "-"
    link_group_id = (
        payload.get("link_group_id")
        if isinstance(payload.get("link_group_id"), str)
        else "-"
    )
    reasons = payload.get("reasons") if isinstance(payload.get("reasons"), list) else []
    derived_evidence = (
        payload.get("derived_evidence")
        if isinstance(payload.get("derived_evidence"), list)
        else []
    )

    lines = [
        f"file_id: {payload.get('file_id', '')}",
        f"rel_path: {payload.get('rel_path', '')}",
        f"role_id: {payload.get('role_id', '')}",
        f"confidence: {float(confidence):.3f}",
        f"bus_group: {bus_group}",
        f"link_group_id: {link_group_id}",
        f"tokens: {', '.join(str(item) for item in payload.get('tokens', []))}",
        f"folder_tokens: {', '.join(str(item) for item in payload.get('folder_tokens', []))}",
        "reasons:",
    ]
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- (none)")

    lines.append("derived_evidence:")
    if derived_evidence:
        for reason in derived_evidence:
            lines.append(f"- {reason}")
    else:
        lines.append("- (none)")

    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    lines.append("candidates:")
    if not candidates:
        lines.append("- (none)")
        return "\n".join(lines)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        role_id = candidate.get("role_id") if isinstance(candidate.get("role_id"), str) else ""
        kind = candidate.get("kind") if isinstance(candidate.get("kind"), str) else ""
        score = candidate.get("score") if isinstance(candidate.get("score"), int) else 0
        bus_label = candidate.get("bus_group") if isinstance(candidate.get("bus_group"), str) else "-"
        candidate_reasons = (
            candidate.get("reasons")
            if isinstance(candidate.get("reasons"), list)
            else []
        )
        reason_label = "; ".join(str(reason) for reason in candidate_reasons) if candidate_reasons else "none"
        lines.append(
            f"- {role_id}  score={score}  kind={kind}  bus_group={bus_label}  reasons={reason_label}"
        )
    return "\n".join(lines)
