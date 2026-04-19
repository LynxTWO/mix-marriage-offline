from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from mmo.cli_commands._helpers import (
    _load_json_object,
    _validate_json_payload,
    _write_json_file,
)
from mmo.core.config import (
    default_project_session_path,
    load_project_session_into_project,
    save_project_session,
)
from mmo.core.event_log import validate_event_log_jsonl
from mmo.core.run_config import normalize_run_config
from mmo.resources import (
    ontology_dir as _ontology_dir_fn,
    schemas_dir as _schemas_dir_fn,
)

__all__ = [
    "_run_project_build_gui",
    "_project_last_run_payload",
    "_project_run_config_defaults",
    "_render_project_text",
    "_run_project_bundle",
    "_run_project_pack",
    "_run_project_load",
    "_run_project_render_init",
    "_run_project_render_run",
    "_run_project_save",
    "_run_project_write_render_request",
    "_run_project_show",
    "_run_project_validate",
]


# ── project validate ─────────────────────────────────────────────

# (rel_path, schema_basename | None for YAML, required)
_VALIDATE_CHECKS: list[tuple[str, str | None, bool]] = [
    ("drafts/routing_plan.draft.json", "routing_plan.schema.json", True),
    ("drafts/scene.draft.json", "scene.schema.json", True),
    ("renders/event_log.jsonl", "event.schema.json", False),
    ("renders/render_execute.json", "render_execute.schema.json", False),
    ("renders/render_plan.json", "render_plan.schema.json", False),
    ("renders/render_preflight.json", "render_preflight.schema.json", False),
    ("renders/render_qa.json", "render_qa.schema.json", False),
    ("renders/render_report.json", "render_report.schema.json", False),
    ("renders/render_request.json", "render_request.schema.json", False),
    ("report.json", "report.schema.json", False),
    ("stems/stems_index.json", "stems_index.schema.json", True),
    ("stems/stems_map.json", "stems_map.schema.json", True),
    ("stems/stems_overrides.yaml", "stems_overrides.schema.json", True),
    ("stems_auditions/manifest.json", "stems_audition_manifest.schema.json", False),
    ("ui_bundle.json", "ui_bundle.schema.json", False),
]

# Keep bundled project artifacts on a narrow allowlist.
# Adding files here makes them part of the GUI-facing project contract.
_PROJECT_BUNDLE_ALLOWLIST: tuple[str, ...] = (
    "report.json",
    "listen_pack.json",
    "stems/stems_index.json",
    "stems/stems_map.json",
    "drafts/scene.draft.json",
    "drafts/routing_plan.draft.json",
    "renders/render_request.json",
    "renders/render_plan.json",
    "renders/render_execute.json",
    "renders/render_preflight.json",
    "renders/render_qa.json",
    "renders/render_report.json",
    "renders/event_log.jsonl",
)

_PROJECT_BUNDLE_REQUIRED: frozenset[str] = frozenset(
    {
        "report.json",
        "stems/stems_index.json",
        "stems/stems_map.json",
    }
)

_PROJECT_SHOW_ALLOWLIST: tuple[str, ...] = tuple(
    sorted(
        set(rel for rel, _, _ in _VALIDATE_CHECKS)
        | set(_PROJECT_BUNDLE_ALLOWLIST)
        | {"listen_pack.json"}
    )
)
_PROJECT_SHOW_REQUIRED: frozenset[str] = frozenset(
    {
        rel
        for rel, _, required in _VALIDATE_CHECKS
        if required
    }
)
_PROJECT_SHOW_SCHEMA_BY_ARTIFACT: dict[str, str | None] = {
    rel: schema_basename
    for rel, schema_basename, _ in _VALIDATE_CHECKS
}
_PROJECT_SHOW_SCHEMA_BY_ARTIFACT["listen_pack.json"] = "listen_pack.schema.json"

# project.write_render_request is a safe-edit surface, not a generic JSON patch.
# New writable fields need explicit validation and ownership review.
_PROJECT_RENDER_REQUEST_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "dry_run",
        "lfe_derivation_profile_id",
        "lfe_mode",
        "max_theoretical_quality",
        "plugin_chain",
        "policies",
        "target_ids",
        "target_layout_ids",
    }
)
_PROJECT_RENDER_REQUEST_POLICY_FIELDS: frozenset[str] = frozenset(
    {
        "downmix_policy_id",
        "gates_policy_id",
    }
)
# These outputs belong to the surrounding workspace flow.
# project validate reports them as references so it does not overclaim scope.
_PROJECT_VALIDATE_WORKSPACE_ROOT_OUTPUTS: tuple[str, ...] = (
    "scene.json",
    "render_manifest.json",
    "render_qa.json",
    "safe_render_receipt.json",
    "compare_report.json",
)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _load_json_object_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _render_compat_issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str, str]:
    try:
        evidence = json.dumps(
            issue.get("evidence", {}),
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError:
        evidence = "{}"
    return (
        _coerce_str(issue.get("severity")).strip(),
        _coerce_str(issue.get("issue_id")).strip(),
        _coerce_str(issue.get("message")).strip(),
        evidence,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _schema_version_from_schema_payload(
    payload: dict[str, Any],
) -> str | None:
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        return None
    for key in ("schema_version", "version"):
        raw_schema_version = properties.get(key)
        if not isinstance(raw_schema_version, dict):
            continue

        schema_version = raw_schema_version.get("const")
        if isinstance(schema_version, str) and schema_version.strip():
            return schema_version.strip()

        enum_values = raw_schema_version.get("enum")
        if (
            isinstance(enum_values, list)
            and len(enum_values) == 1
            and isinstance(enum_values[0], str)
            and enum_values[0].strip()
        ):
            return enum_values[0].strip()
    return None


def _schema_version_for_basename(
    *,
    schema_basename: str,
    schemas_dir: Path,
) -> str | None:
    schema_path = schemas_dir / schema_basename
    if not schema_path.is_file():
        return None
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _schema_version_from_schema_payload(payload)


def _build_project_show_payload(*, project_dir: Path) -> dict[str, Any]:
    if not project_dir.exists():
        raise ValueError(f"Project directory does not exist: {project_dir.as_posix()}")
    if not project_dir.is_dir():
        raise ValueError(f"Project path is not a directory: {project_dir.as_posix()}")

    resolved_project_dir = project_dir.resolve()
    schemas_dir = _schemas_dir_fn()

    schema_versions: dict[str, str | None] = {}
    for schema_basename in sorted(
        {
            schema_name
            for schema_name in _PROJECT_SHOW_SCHEMA_BY_ARTIFACT.values()
            if isinstance(schema_name, str) and schema_name.strip()
        }
    ):
        schema_versions[schema_basename] = _schema_version_for_basename(
            schema_basename=schema_basename,
            schemas_dir=schemas_dir,
        )

    artifacts: list[dict[str, Any]] = []
    artifact_markers: dict[str, str] = {}
    for rel_path in _PROJECT_SHOW_ALLOWLIST:
        full_path = resolved_project_dir / rel_path
        exists = full_path.is_file()
        sha256_hex: str | None = None
        if exists:
            try:
                sha256_hex = _sha256_file(full_path)
            except OSError as exc:
                raise ValueError(
                    (
                        "Failed to read allowlisted project artifact: "
                        f"{full_path.as_posix()}: {exc}"
                    )
                ) from exc

        last_built_marker = f"sha256:{sha256_hex}" if sha256_hex else "missing"
        artifact_markers[rel_path] = last_built_marker
        artifacts.append(
            {
                "path": rel_path,
                "absolute_path": full_path.as_posix(),
                "required": rel_path in _PROJECT_SHOW_REQUIRED,
                "schema": _PROJECT_SHOW_SCHEMA_BY_ARTIFACT.get(rel_path),
                "exists": exists,
                "sha256": sha256_hex,
                "last_built_marker": last_built_marker,
            }
        )

    marker_seed = (
        "\n".join(
            f"{rel_path}:{artifact_markers[rel_path]}"
            for rel_path in _PROJECT_SHOW_ALLOWLIST
        )
        + "\n"
    ).encode("utf-8")
    project_marker = f"sha256:{hashlib.sha256(marker_seed).hexdigest()}"

    return {
        "project_dir": resolved_project_dir.as_posix(),
        "schema_versions": schema_versions,
        "artifacts": artifacts,
        "last_built_markers": {
            "project": project_marker,
            "artifacts": artifact_markers,
        },
    }


def _build_project_show_shared_payload(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list):
        for artifact in raw_artifacts:
            if not isinstance(artifact, dict):
                continue
            artifacts.append(
                {
                    "path": artifact.get("path"),
                    "required": artifact.get("required"),
                    "schema": artifact.get("schema"),
                    "exists": artifact.get("exists"),
                    "sha256": artifact.get("sha256"),
                    "last_built_marker": artifact.get("last_built_marker"),
                }
            )

    # This profile is for issue threads, shell captures, and shared logs. It
    # keeps the allowlisted artifact summary but drops machine-local paths.
    return {
        "artifacts": artifacts,
        "last_built_markers": payload.get("last_built_markers"),
        "paths_redacted": True,
        "schema_versions": payload.get("schema_versions"),
    }


def _path_text_is_absolute(path_text: str) -> bool:
    return path_text.startswith("/") or (
        len(path_text) >= 3
        and path_text[0].isalpha()
        and path_text[1] == ":"
        and path_text[2] == "/"
    )


def _shared_project_path_ref(path_value: Any, *, project_dir: Any) -> str | None:
    if not isinstance(path_value, str):
        return None
    normalized_path = path_value.replace("\\", "/").strip()
    if not normalized_path:
        return None
    if not _path_text_is_absolute(normalized_path):
        return normalized_path

    normalized_project_dir = ""
    if isinstance(project_dir, str):
        normalized_project_dir = project_dir.replace("\\", "/").strip()

    if normalized_project_dir and _path_text_is_absolute(normalized_project_dir):
        if normalized_path == normalized_project_dir:
            return "."
        prefix = normalized_project_dir.rstrip("/") + "/"
        if normalized_path.startswith(prefix):
            return normalized_path[len(prefix):]

    return Path(normalized_path).name


def _build_project_session_shared_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in payload.items()
        if key not in {"project_dir", "scene_path", "session_path", "written"}
    }
    project_dir = payload.get("project_dir")

    session_path = _shared_project_path_ref(payload.get("session_path"), project_dir=project_dir)
    if isinstance(session_path, str):
        result["session_path"] = session_path

    scene_path = _shared_project_path_ref(payload.get("scene_path"), project_dir=project_dir)
    if isinstance(scene_path, str):
        result["scene_path"] = scene_path

    raw_written = payload.get("written")
    if isinstance(raw_written, list):
        written: list[str] = []
        for item in raw_written:
            shared_ref = _shared_project_path_ref(item, project_dir=project_dir)
            if isinstance(shared_ref, str):
                written.append(shared_ref)
        result["written"] = written

    # This profile keeps the machine-readable save/load summary but narrows
    # machine-local path fields before shell captures or issue threads share it.
    result["paths_redacted"] = True
    return result


def _render_project_show_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    project_dir = payload.get("project_dir", "")
    lines.append(f"project_dir: {project_dir}")

    markers = payload.get("last_built_markers")
    if isinstance(markers, dict):
        project_marker = markers.get("project")
        if isinstance(project_marker, str):
            lines.append(f"project_marker: {project_marker}")

    lines.append("schema_versions:")
    schema_versions = payload.get("schema_versions")
    if isinstance(schema_versions, dict) and schema_versions:
        for schema_basename in sorted(schema_versions.keys()):
            raw_version = schema_versions.get(schema_basename)
            version = raw_version if isinstance(raw_version, str) else "(unknown)"
            lines.append(f"  {schema_basename}: {version}")
    else:
        lines.append("  (none)")

    lines.append("artifacts:")
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list) and raw_artifacts:
        for artifact in raw_artifacts:
            if not isinstance(artifact, dict):
                continue
            rel_path = _coerce_str(artifact.get("path")).strip()
            exists = bool(artifact.get("exists"))
            exists_text = "true" if exists else "false"
            sha256_hex = artifact.get("sha256")
            sha256_text = sha256_hex if isinstance(sha256_hex, str) else "-"
            marker = artifact.get("last_built_marker")
            marker_text = marker if isinstance(marker, str) else "missing"
            lines.append(
                (
                    f"  {rel_path}  exists={exists_text}  "
                    f"sha256={sha256_text}  marker={marker_text}"
                )
            )
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def _validate_one_check(
    project_dir: Path,
    schemas_dir: Path,
    rel_path: str,
    schema_basename: str | None,
    required: bool,
) -> dict[str, Any]:
    """Validate a single project artifact. Returns a check dict."""
    file_path = project_dir / rel_path
    entry: dict[str, Any] = {"file": rel_path, "required": required}

    if not file_path.is_file():
        entry["status"] = "missing"
        return entry

    # YAML files: validate by loading through the typed loader.
    if rel_path.endswith(".yaml"):
        try:
            from mmo.core.stems_overrides import load_stems_overrides
            load_stems_overrides(file_path)
        except (ValueError, RuntimeError) as exc:
            entry["status"] = "invalid"
            entry["errors"] = [str(exc)]
            return entry
        entry["status"] = "valid"
        return entry

    if rel_path.endswith(".jsonl"):
        try:
            report = validate_event_log_jsonl(file_path)
        except (RuntimeError, ValueError) as exc:
            entry["status"] = "invalid"
            entry["errors"] = [str(exc)]
            return entry

        raw_issues = report.get("issues")
        if not isinstance(raw_issues, list) or not raw_issues:
            entry["status"] = "valid"
            return entry

        normalized_issues: list[dict[str, Any]] = []
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                continue
            line = raw_issue.get("line")
            issue_id = raw_issue.get("issue_id")
            message = raw_issue.get("message")
            if not isinstance(line, int):
                continue
            if not isinstance(issue_id, str) or not issue_id.strip():
                continue
            if not isinstance(message, str) or not message.strip():
                continue
            normalized_issues.append(
                {
                    "line": line,
                    "issue_id": issue_id.strip(),
                    "message": message.strip(),
                }
            )

        normalized_issues.sort(
            key=lambda issue: (
                issue["line"],
                issue["issue_id"],
                issue["message"],
            )
        )
        entry["status"] = "invalid"
        entry["issues"] = normalized_issues
        entry["errors"] = [
            (
                f"line {issue['line']}: "
                f"{issue['issue_id']}: "
                f"{issue['message']}"
            )
            for issue in normalized_issues
        ]
        return entry

    # JSON files: load + schema-validate.
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        entry["status"] = "invalid"
        entry["errors"] = [f"JSON parse error: {exc}"]
        return entry

    if not isinstance(data, dict):
        entry["status"] = "invalid"
        entry["errors"] = ["JSON root must be an object."]
        return entry

    if schema_basename is None:
        entry["status"] = "valid"
        return entry

    try:
        import jsonschema
    except ImportError:
        entry["status"] = "valid"
        return entry

    schema_path = schemas_dir / schema_basename
    if not schema_path.is_file():
        entry["status"] = "valid"
        return entry

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        entry["status"] = "valid"
        return entry

    try:
        from mmo.cli_commands._helpers import _build_schema_registry, _build_schema_store
        registry = _build_schema_registry(schemas_dir)
        store = _build_schema_store(schemas_dir)
    except (ValueError, RuntimeError):
        registry = None
        store = {}

    validator_kwargs: dict[str, Any] = {"schema": schema}
    if registry is not None:
        validator_kwargs["registry"] = registry
    try:
        validator = jsonschema.Draft202012Validator(**validator_kwargs)
    except TypeError:
        # jsonschema<4.22 does not accept a registry kwarg.
        resolver_cls = getattr(jsonschema, "RefResolver", None)
        if resolver_cls is not None and store:
            resolver = resolver_cls.from_schema(schema, store=store)
            validator = jsonschema.Draft202012Validator(schema, resolver=resolver)
        else:
            validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        entry["status"] = "invalid"
        entry["errors"] = [
            f"{'.'.join(str(p) for p in err.path) or '$'}: {err.message}"
            for err in errors
        ]
        return entry

    entry["status"] = "valid"
    return entry


def _run_project_validate(
    *,
    project_dir: Path,
    out_path: Path | None,
    repo_root: Path | None,
    render_compat: bool = False,
) -> int:
    """Run project validate and print/write the result. Returns exit code."""
    schemas_dir = _schemas_dir_fn()
    checks: list[dict[str, Any]] = []

    for rel_path, schema_basename, required in _VALIDATE_CHECKS:
        check = _validate_one_check(
            project_dir, schemas_dir, rel_path, schema_basename, required,
        )
        checks.append(check)

    valid_count = sum(1 for c in checks if c["status"] == "valid")
    missing_count = sum(1 for c in checks if c["status"] == "missing")
    invalid_count = sum(1 for c in checks if c["status"] == "invalid")

    # ok = no invalid AND no missing-required
    has_missing_required = any(
        c["status"] == "missing" and c["required"] for c in checks
    )
    ok = invalid_count == 0 and not has_missing_required
    has_compat_errors = False

    # Keep scope explicit in the payload. Callers use this validator for project
    # scaffolds, not as proof that every workspace-root artifact is valid.
    result: dict[str, Any] = {
        "ok": ok,
        "project_dir": project_dir.resolve().as_posix(),
        "scope": {
            "artifact_root_ref": "project",
            "kind": "project_contract",
            "root_path": project_dir.resolve().as_posix(),
            "workspace_root_output_refs": list(_PROJECT_VALIDATE_WORKSPACE_ROOT_OUTPUTS),
            "workspace_root_outputs_in_scope": False,
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "valid": valid_count,
            "missing": missing_count,
            "invalid": invalid_count,
        },
    }

    if render_compat:
        issues: list[dict[str, Any]] = []
        render_request_path = project_dir / "renders" / "render_request.json"
        render_plan_path = project_dir / "renders" / "render_plan.json"
        render_report_path = project_dir / "renders" / "render_report.json"

        request_payload = _load_json_object_if_exists(render_request_path)
        plan_payload = _load_json_object_if_exists(render_plan_path)
        report_payload = _load_json_object_if_exists(render_report_path)

        if request_payload is not None and plan_payload is not None:
            from mmo.core.render_compat import (  # noqa: WPS433
                validate_plan_report_compat,
                validate_request_plan_compat,
            )

            issues.extend(validate_request_plan_compat(request_payload, plan_payload))
            if report_payload is not None:
                issues.extend(validate_plan_report_compat(plan_payload, report_payload))

        issues = [item for item in issues if isinstance(item, dict)]
        issues.sort(key=_render_compat_issue_sort_key)
        has_compat_errors = any(
            _coerce_str(item.get("severity")).strip() == "error"
            for item in issues
        )
        if has_compat_errors:
            result["ok"] = False
        result["render_compat"] = {"issues": issues}

    output_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(output_text)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")

    return 2 if (not result["ok"] or has_compat_errors) else 0


def _run_project_show(
    *,
    project_dir: Path,
    output_format: str,
) -> int:
    try:
        payload = _build_project_show_payload(project_dir=project_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if output_format == "json-shared":
        print(json.dumps(_build_project_show_shared_payload(payload), indent=2, sort_keys=True))
        return 0

    if output_format == "text":
        print(_render_project_show_text(payload))
        return 0

    print(f"Unsupported format: {output_format}", file=sys.stderr)
    return 2


def _run_project_save(
    *,
    project_dir: Path,
    session_path: Path | None,
    force: bool,
    output_format: str,
) -> int:
    try:
        payload = save_project_session(
            project_dir,
            session_path=session_path,
            force=force,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if output_format == "json-shared":
        print(json.dumps(_build_project_session_shared_payload(payload), indent=2, sort_keys=True))
        return 0

    print(f"Unsupported format: {output_format}", file=sys.stderr)
    return 2


def _run_project_load(
    *,
    project_dir: Path,
    session_path: Path | None,
    force: bool,
    output_format: str,
) -> int:
    resolved_session_path = (
        session_path.resolve()
        if session_path is not None
        else default_project_session_path(project_dir.resolve())
    )
    if not resolved_session_path.is_file():
        print(
            f"Project session file is missing: {resolved_session_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    try:
        payload = load_project_session_into_project(
            project_dir,
            session_path=resolved_session_path,
            force=force,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if output_format == "json-shared":
        print(json.dumps(_build_project_session_shared_payload(payload), indent=2, sort_keys=True))
        return 0

    print(f"Unsupported format: {output_format}", file=sys.stderr)
    return 2


def _run_project_build_gui(
    *,
    project_dir: Path,
    pack_out_path: Path,
    force: bool,
    scan: bool,
    scan_stems_dir: Path | None,
    scan_out_path: Path | None,
    event_log: bool,
    event_log_force: bool,
    include_plugins: bool = False,
    include_plugin_layouts: bool = False,
    include_plugin_layout_snapshots: bool = False,
    include_plugin_ui_hints: bool = False,
    plugins_dir: Path | None = None,
) -> int:
    """Run deterministic project GUI build pipeline with explicit-safe flags."""
    project_dir_resolved = project_dir.resolve()
    bundle_out_path = project_dir / "ui_bundle.json"
    validation_out_path = project_dir / "validation.json"
    render_plan_path = project_dir / "renders" / "render_plan.json"
    render_report_path = project_dir / "renders" / "render_report.json"
    event_log_path = project_dir / "renders" / "event_log.jsonl"
    default_scan_out_path = project_dir / "report.json"

    if event_log_force and not event_log:
        print("--event-log-force requires --event-log.", file=sys.stderr)
        return 1

    normalized_scan_out: Path | None = None
    if scan:
        if scan_stems_dir is None:
            print("--scan requires --scan-stems.", file=sys.stderr)
            return 1
        if scan_out_path is None:
            print("--scan requires --scan-out.", file=sys.stderr)
            return 1
        normalized_scan_out = scan_out_path.resolve()
        expected_scan_out = default_scan_out_path.resolve()
        if normalized_scan_out != expected_scan_out:
            print(
                (
                    "--scan-out must be the allowlisted project report path: "
                    f"{expected_scan_out.as_posix()}"
                ),
                file=sys.stderr,
            )
            return 1
    else:
        if scan_stems_dir is not None:
            print("--scan-stems requires --scan.", file=sys.stderr)
            return 1
        if scan_out_path is not None:
            print("--scan-out requires --scan.", file=sys.stderr)
            return 1

    # Core outputs share --force because this helper rebuilds them as one pipeline.
    # Event logs keep a separate flag so audit history is harder to overwrite.
    blocked_force_paths: list[Path] = []
    if scan and normalized_scan_out is not None and normalized_scan_out.exists() and not force:
        blocked_force_paths.append(normalized_scan_out)
    if render_plan_path.exists() and not force:
        blocked_force_paths.append(render_plan_path)
    if render_report_path.exists() and not force:
        blocked_force_paths.append(render_report_path)
    if bundle_out_path.exists() and not force:
        blocked_force_paths.append(bundle_out_path)
    if validation_out_path.exists() and not force:
        blocked_force_paths.append(validation_out_path)
    if pack_out_path.exists() and not force:
        blocked_force_paths.append(pack_out_path)

    blocked_event_log_path: Path | None = None
    if event_log and event_log_path.exists() and not event_log_force:
        blocked_event_log_path = event_log_path

    if blocked_force_paths or blocked_event_log_path is not None:
        for blocked_path in blocked_force_paths:
            print(
                f"File exists (use --force to overwrite): {blocked_path.as_posix()}",
                file=sys.stderr,
            )
        if blocked_event_log_path is not None:
            print(
                (
                    "File exists (use --event-log-force to overwrite): "
                    f"{blocked_event_log_path.as_posix()}"
                ),
                file=sys.stderr,
            )
        return 1

    step_rows: list[dict[str, Any]] = []
    paths_written: list[str] = []

    if scan:
        from mmo.cli_commands._analysis import _run_scan  # noqa: WPS433

        if normalized_scan_out is None or scan_stems_dir is None:
            print("Scan configuration error.", file=sys.stderr)
            return 1
        scan_exit = _run_scan(
            tools_dir=project_dir,
            stems_dir=scan_stems_dir,
            out_path=normalized_scan_out,
            meters=None,
            include_peak=False,
        )
        if scan_exit != 0:
            return scan_exit
        step_rows.append(
            {
                "name": "scan",
                "out": normalized_scan_out.as_posix(),
                "ran": True,
                "stems_dir": scan_stems_dir.resolve().as_posix(),
            }
        )
        paths_written.append(normalized_scan_out.as_posix())
    else:
        step_rows.append({"name": "scan", "ran": False})

    with contextlib.redirect_stdout(io.StringIO()):
        render_run_exit = _run_project_render_run(
            project_dir=project_dir,
            force=force,
            event_log=event_log,
            event_log_force=event_log_force,
        )
    if render_run_exit != 0:
        return render_run_exit
    step_rows.append(
        {
            "event_log": event_log,
            "name": "project-render-run",
            "ran": True,
        }
    )
    paths_written.append(render_plan_path.resolve().as_posix())
    paths_written.append(render_report_path.resolve().as_posix())
    if event_log:
        paths_written.append(event_log_path.resolve().as_posix())

    with contextlib.redirect_stdout(io.StringIO()):
        bundle_exit = _run_project_bundle(
            project_dir=project_dir,
            out_path=bundle_out_path,
            force=force,
            include_plugins=include_plugins,
            include_plugin_layouts=include_plugin_layouts,
            include_plugin_layout_snapshots=include_plugin_layout_snapshots,
            include_plugin_ui_hints=include_plugin_ui_hints,
            plugins_dir=plugins_dir,
        )
    if bundle_exit != 0:
        return bundle_exit
    step_rows.append(
        {
            "name": "project-bundle",
            "out": bundle_out_path.resolve().as_posix(),
            "ran": True,
        }
    )
    paths_written.append(bundle_out_path.resolve().as_posix())

    with contextlib.redirect_stdout(io.StringIO()):
        validate_exit = _run_project_validate(
            project_dir=project_dir,
            out_path=validation_out_path,
            repo_root=None,
            render_compat=False,
        )
    if validate_exit != 0:
        return validate_exit
    step_rows.append(
        {
            "name": "project-validate",
            "out": validation_out_path.resolve().as_posix(),
            "ran": True,
        }
    )
    paths_written.append(validation_out_path.resolve().as_posix())

    with contextlib.redirect_stdout(io.StringIO()):
        pack_exit = _run_project_pack(
            project_dir=project_dir,
            out_path=pack_out_path,
            include_wavs=False,
            force=force,
        )
    if pack_exit != 0:
        return pack_exit
    step_rows.append(
        {
            "name": "project-pack",
            "out": pack_out_path.resolve().as_posix(),
            "ran": True,
        }
    )
    paths_written.append(pack_out_path.resolve().as_posix())

    summary: dict[str, Any] = {
        "ok": True,
        "pack_out": pack_out_path.resolve().as_posix(),
        "paths_written": sorted(set(paths_written)),
        "project_dir": project_dir_resolved.as_posix(),
        "steps": step_rows,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _validate_required_project_artifacts(project_dir: Path) -> int:
    """Validate required project artifacts needed by project render commands."""
    schemas_dir = _schemas_dir_fn()
    for rel_path, schema_basename, required in _VALIDATE_CHECKS:
        if not required:
            continue
        check = _validate_one_check(
            project_dir, schemas_dir, rel_path, schema_basename, required,
        )
        if check["status"] == "missing":
            print(
                f"Required project artifact missing: {rel_path}",
                file=sys.stderr,
            )
            return 1
        if check["status"] == "invalid":
            errors_str = "; ".join(check.get("errors", []))
            print(
                f"Required project artifact invalid: {rel_path}: {errors_str}",
                file=sys.stderr,
            )
            return 1
    return 0


# ── project render-init ──────────────────────────────────────────


def _parse_layout_ids_csv(raw_value: str, *, flag_name: str) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError(f"{flag_name} must be a comma-separated string.")

    selected = {
        item.strip()
        for item in raw_value.split(",")
        if isinstance(item, str) and item.strip()
    }
    if not selected:
        raise ValueError(f"{flag_name} must include at least one layout ID.")
    return sorted(selected)


def _parse_target_ids_csv(raw_value: str) -> list[str]:
    if not isinstance(raw_value, str):
        raise ValueError("target-ids must be a comma-separated string.")

    from mmo.core.target_tokens import resolve_target_token  # noqa: WPS433
    from mmo.core.registries.render_targets_registry import (  # noqa: WPS433
        load_render_targets_registry,
    )

    target_registry = load_render_targets_registry()
    selected: set[str] = set()
    for raw_item in raw_value.split(","):
        token = raw_item.strip()
        if not token:
            continue
        resolved = resolve_target_token(token)
        if isinstance(resolved.target_id, str) and resolved.target_id:
            target_registry.get_target(resolved.target_id)
            selected.add(resolved.target_id)
            continue

        candidates = sorted(
            {
                _coerce_str(row.get("target_id")).strip()
                for row in target_registry.find_targets_for_layout(resolved.layout_id)
                if isinstance(row, dict)
                and _coerce_str(row.get("target_id")).strip()
            }
        )
        if len(candidates) == 1:
            selected.add(candidates[0])
            continue
        if len(candidates) > 1:
            raise ValueError(
                (
                    f"Ambiguous target token: {token}. "
                    f"Candidates: {', '.join(candidates)}"
                )
            )
        raise ValueError(
            (
                f"Target token resolved to {resolved.layout_id}, "
                "but no render target maps to that layout."
            )
        )

    if not selected:
        raise ValueError("target-ids must include at least one target token.")
    return sorted(selected)


def _parse_write_render_request_set_entries(
    set_entries: list[str],
) -> dict[str, str]:
    if not isinstance(set_entries, list) or not set_entries:
        raise ValueError("Provide at least one --set key=value entry.")

    updates: dict[str, str] = {}
    for raw_entry in set_entries:
        if not isinstance(raw_entry, str):
            raise ValueError("Each --set entry must be a key=value string.")
        key_part, separator, value_part = raw_entry.partition("=")
        key = key_part.strip()
        if not separator or not key:
            raise ValueError("Each --set entry must use key=value with a non-empty key.")
        if key in updates:
            raise ValueError(f"Duplicate --set key: {key}")
        updates[key] = value_part.strip()
    return updates


def _parse_write_render_request_bool(
    raw_value: Any,
    *,
    field_name: str,
) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{field_name} must be a boolean (true or false).")


def _parse_write_render_request_id_list(
    raw_value: Any,
    *,
    field_name: str,
) -> list[str]:
    if isinstance(raw_value, list):
        normalized: list[str] = []
        for item in raw_value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"{field_name} entries must be non-empty strings.",
                )
            normalized.append(item.strip())
        deduped = sorted(set(normalized))
        if not deduped:
            raise ValueError(f"{field_name} must include at least one ID.")
        return deduped

    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} must be a comma-separated string or list.")

    raw_text = raw_value.strip()
    if not raw_text:
        raise ValueError(f"{field_name} must include at least one ID.")

    if raw_text.startswith("["):
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{field_name} must be valid JSON when using list syntax.",
            ) from exc
        return _parse_write_render_request_id_list(parsed, field_name=field_name)

    deduped = sorted(
        {
            item.strip()
            for item in raw_text.split(",")
            if isinstance(item, str) and item.strip()
        }
    )
    if not deduped:
        raise ValueError(f"{field_name} must include at least one ID.")
    return deduped


def _normalize_write_render_request_target_layout_ids(
    raw_value: Any,
) -> list[str]:
    layout_ids = _parse_write_render_request_id_list(
        raw_value,
        field_name="target_layout_ids",
    )

    from mmo.core.registries.layout_registry import (  # noqa: WPS433
        load_layout_registry,
    )

    registry = load_layout_registry()
    for layout_id in layout_ids:
        registry.get_layout(layout_id)
    return layout_ids


def _normalize_write_render_request_target_ids(raw_value: Any) -> list[str]:
    target_ids = _parse_write_render_request_id_list(
        raw_value,
        field_name="target_ids",
    )
    return _parse_target_ids_csv(",".join(target_ids))


def _normalize_write_render_request_lfe_derivation_profile_id(raw_value: Any) -> str:
    profile_id = _coerce_str(raw_value).strip()
    if not profile_id:
        raise ValueError("lfe_derivation_profile_id must be a non-empty string.")

    from mmo.core.lfe_derivation_profiles import get_lfe_derivation_profile  # noqa: WPS433

    get_lfe_derivation_profile(profile_id)
    return profile_id


def _normalize_write_render_request_lfe_mode(raw_value: Any) -> str:
    mode = _coerce_str(raw_value).strip().lower()
    if mode not in {"mono", "stereo"}:
        raise ValueError("lfe_mode must be 'mono' or 'stereo'.")
    return mode


def _normalize_write_render_request_policies(
    raw_value: Any,
) -> dict[str, str]:
    parsed: dict[str, Any]
    if isinstance(raw_value, dict):
        parsed = dict(raw_value)
    elif isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            raise ValueError("policies must include at least one policy key.")
        if raw_text.startswith("{"):
            try:
                parsed_json = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "policies must be valid JSON when using object syntax.",
                ) from exc
            if not isinstance(parsed_json, dict):
                raise ValueError("policies must decode to an object.")
            parsed = dict(parsed_json)
        else:
            parsed = {}
            for raw_pair in raw_text.split(","):
                pair = raw_pair.strip()
                if not pair:
                    continue
                key_part, separator, value_part = pair.partition("=")
                key = key_part.strip()
                value = value_part.strip()
                if not separator or not key or not value:
                    raise ValueError(
                        "policies must use comma-separated key=value pairs.",
                    )
                if key in parsed:
                    raise ValueError(f"Duplicate policies key: {key}")
                parsed[key] = value
            if not parsed:
                raise ValueError("policies must include at least one policy key.")
    else:
        raise ValueError("policies must be an object or string value.")

    unknown_policy_keys = sorted(
        key
        for key in parsed
        if key not in _PROJECT_RENDER_REQUEST_POLICY_FIELDS
    )
    if unknown_policy_keys:
        allowed = ", ".join(sorted(_PROJECT_RENDER_REQUEST_POLICY_FIELDS))
        joined = ", ".join(unknown_policy_keys)
        raise ValueError(
            f"Unknown policies key(s): {joined}. Allowed keys: {allowed}.",
        )

    normalized: dict[str, str] = {}
    for key in sorted(parsed):
        raw_policy_id = parsed[key]
        if not isinstance(raw_policy_id, str) or not raw_policy_id.strip():
            raise ValueError(
                f"policies.{key} must be a non-empty string.",
            )
        normalized[key] = raw_policy_id.strip()
    return normalized


def _normalize_write_render_request_plugin_chain(
    raw_value: Any,
) -> list[dict[str, Any]]:
    parsed: Any = raw_value
    if isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            raise ValueError("plugin_chain must be a non-empty JSON array.")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("plugin_chain must be a valid JSON array.") from exc

    if not isinstance(parsed, list) or not parsed:
        raise ValueError("plugin_chain must be a non-empty list.")

    return list(parsed)


def _validate_render_request_plugin_chain(
    raw_chain: Any,
    *,
    chain_label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    from mmo.core.render_run_audio import (  # noqa: WPS433
        validate_and_normalize_plugin_chain,
    )

    try:
        return validate_and_normalize_plugin_chain(
            raw_chain,
            chain_label=chain_label,
            lenient_numeric_bounds=True,
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _normalize_write_render_request_updates(
    raw_updates: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_updates, dict) or not raw_updates:
        raise ValueError("Provide at least one editable field update.")

    unknown_fields = sorted(
        key
        for key in raw_updates
        if key not in _PROJECT_RENDER_REQUEST_EDITABLE_FIELDS
    )
    if unknown_fields:
        allowed = ", ".join(sorted(_PROJECT_RENDER_REQUEST_EDITABLE_FIELDS))
        joined = ", ".join(unknown_fields)
        raise ValueError(f"Unknown editable field(s): {joined}. Allowed keys: {allowed}.")

    normalized: dict[str, Any] = {}
    if "dry_run" in raw_updates:
        normalized["dry_run"] = _parse_write_render_request_bool(
            raw_updates.get("dry_run"),
            field_name="dry_run",
        )
    if "lfe_derivation_profile_id" in raw_updates:
        normalized["lfe_derivation_profile_id"] = (
            _normalize_write_render_request_lfe_derivation_profile_id(
                raw_updates.get("lfe_derivation_profile_id"),
            )
        )
    if "lfe_mode" in raw_updates:
        normalized["lfe_mode"] = _normalize_write_render_request_lfe_mode(
            raw_updates.get("lfe_mode"),
        )
    if "max_theoretical_quality" in raw_updates:
        normalized["max_theoretical_quality"] = _parse_write_render_request_bool(
            raw_updates.get("max_theoretical_quality"),
            field_name="max_theoretical_quality",
        )
    if "plugin_chain" in raw_updates:
        normalized["plugin_chain"] = _normalize_write_render_request_plugin_chain(
            raw_updates.get("plugin_chain"),
        )
    if "target_ids" in raw_updates:
        normalized["target_ids"] = _normalize_write_render_request_target_ids(
            raw_updates.get("target_ids"),
        )
    if "target_layout_ids" in raw_updates:
        normalized["target_layout_ids"] = _normalize_write_render_request_target_layout_ids(
            raw_updates.get("target_layout_ids"),
        )
    if "policies" in raw_updates:
        normalized["policies"] = _normalize_write_render_request_policies(
            raw_updates.get("policies"),
        )
    return normalized


def _run_project_write_render_request(
    *,
    project_dir: Path,
    set_entries: list[str] | None = None,
    updates: dict[str, Any] | None = None,
) -> int:
    if not project_dir.exists():
        print(
            f"Project directory does not exist: {project_dir.as_posix()}",
            file=sys.stderr,
        )
        return 1
    if not project_dir.is_dir():
        print(
            f"Project path is not a directory: {project_dir.as_posix()}",
            file=sys.stderr,
        )
        return 1

    if set_entries is not None and updates is not None:
        print(
            "Specify updates from either --set entries or RPC params, not both.",
            file=sys.stderr,
        )
        return 1

    request_path = project_dir / "renders" / "render_request.json"
    if request_path.exists() and not request_path.is_file():
        print(
            f"Render request path is not a file: {request_path.as_posix()}",
            file=sys.stderr,
        )
        return 1
    if not request_path.is_file():
        print(
            (
                "Render request file is missing: "
                f"{request_path.as_posix()} (run `mmo project render-init` first)."
            ),
            file=sys.stderr,
        )
        return 1

    try:
        request_payload = _load_json_object(request_path, label="Render request")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        if updates is not None:
            raw_updates = dict(updates)
        else:
            raw_updates = _parse_write_render_request_set_entries(
                set_entries if isinstance(set_entries, list) else [],
            )
        normalized_updates = _normalize_write_render_request_updates(raw_updates)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    options_payload = request_payload.get("options")
    options = dict(options_payload) if isinstance(options_payload, dict) else {}
    plugin_chain_before = options.get("plugin_chain")
    updated_fields: list[str] = []
    plugin_chain_notes: list[str] = []

    # Only the allowlisted fields below may change.
    # render_request.json stays a contract artifact, not an open-ended settings bag.
    if "dry_run" in normalized_updates:
        options["dry_run"] = normalized_updates["dry_run"]
        updated_fields.append("dry_run")
    if "lfe_derivation_profile_id" in normalized_updates:
        options["lfe_derivation_profile_id"] = normalized_updates["lfe_derivation_profile_id"]
        updated_fields.append("lfe_derivation_profile_id")
    if "lfe_mode" in normalized_updates:
        options["lfe_mode"] = normalized_updates["lfe_mode"]
        updated_fields.append("lfe_mode")
    if "max_theoretical_quality" in normalized_updates:
        options["max_theoretical_quality"] = normalized_updates["max_theoretical_quality"]
        updated_fields.append("max_theoretical_quality")

    if "target_ids" in normalized_updates:
        options["target_ids"] = normalized_updates["target_ids"]
        updated_fields.append("target_ids")

    if "policies" in normalized_updates:
        policies = normalized_updates["policies"]
        if isinstance(policies, dict):
            for policy_key in sorted(policies):
                options[policy_key] = policies[policy_key]
        updated_fields.append("policies")

    if "plugin_chain" in normalized_updates:
        options["plugin_chain"] = normalized_updates["plugin_chain"]
        updated_fields.append("plugin_chain")

    if "plugin_chain" in options:
        try:
            normalized_chain, plugin_chain_notes = _validate_render_request_plugin_chain(
                options.get("plugin_chain"),
                chain_label="plugin_chain",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        options["plugin_chain"] = normalized_chain
        if normalized_chain != plugin_chain_before and "plugin_chain" not in updated_fields:
            updated_fields.append("plugin_chain")

    if updated_fields:
        request_payload["options"] = options

    if "target_layout_ids" in normalized_updates:
        request_payload["target_layout_ids"] = normalized_updates["target_layout_ids"]
        request_payload.pop("target_layout_id", None)
        updated_fields.append("target_layout_ids")

    # Revalidate the full artifact after safe edits.
    # Field-level parsing alone does not catch cross-field contract drift.
    try:
        _validate_json_payload(
            request_payload,
            schema_path=_schemas_dir_fn() / "render_request.schema.json",
            payload_name="Render request",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    _write_json_file(request_path, request_payload)

    summary: dict[str, Any] = {
        "ok": True,
        "project_dir": project_dir.resolve().as_posix(),
        "updated_fields": sorted(updated_fields),
        "written": ["renders/render_request.json"],
    }
    for key in (
        "dry_run",
        "lfe_derivation_profile_id",
        "lfe_mode",
        "max_theoretical_quality",
        "target_ids",
        "target_layout_ids",
        "policies",
    ):
        if key in normalized_updates:
            summary[key] = normalized_updates[key]
    if "plugin_chain" in updated_fields and "plugin_chain" in options:
        summary["plugin_chain"] = options["plugin_chain"]
    if plugin_chain_notes:
        summary["plugin_chain_notes"] = plugin_chain_notes

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _run_project_render_init(
    *,
    project_dir: Path,
    target_layout: str | None,
    target_layouts: str | None,
    target_ids: str | None,
    force: bool,
) -> int:
    """Create a render scaffold inside an existing project. Returns exit code."""
    schemas_dir = _schemas_dir_fn()

    # 1. Validate required project artifacts.
    validate_exit = _validate_required_project_artifacts(project_dir)
    if validate_exit != 0:
        return validate_exit

    # 2. Build render request using existing core builder.
    from mmo.core.render_request_template import (  # noqa: WPS433
        build_multi_render_request_template,
        build_render_request_template,
    )

    has_single = isinstance(target_layout, str) and bool(target_layout.strip())
    has_multi = isinstance(target_layouts, str) and bool(target_layouts.strip())
    if has_single == has_multi:
        print(
            "Specify exactly one of --target-layout or --target-layouts.",
            file=sys.stderr,
        )
        return 1

    routing_plan_path: str | None = None
    routing_plan_file = project_dir / "drafts" / "routing_plan.draft.json"
    if routing_plan_file.is_file():
        routing_plan_path = "drafts/routing_plan.draft.json"

    try:
        if has_multi:
            normalized_layout_ids = _parse_layout_ids_csv(
                target_layouts if target_layouts is not None else "",
                flag_name="target-layouts",
            )
            payload = build_multi_render_request_template(
                normalized_layout_ids,
                scene_path="drafts/scene.draft.json",
                routing_plan_path=routing_plan_path,
            )
        else:
            normalized_layout_id = (
                target_layout.strip()
                if isinstance(target_layout, str)
                else ""
            )
            payload = build_render_request_template(
                normalized_layout_id,
                scene_path="drafts/scene.draft.json",
                routing_plan_path=routing_plan_path,
            )

        if target_ids is not None:
            normalized_target_ids = _parse_target_ids_csv(target_ids)
            options = payload.get("options")
            options_payload = dict(options) if isinstance(options, dict) else {}
            options_payload["target_ids"] = normalized_target_ids
            payload["options"] = options_payload
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 3. Validate against schema.
    try:
        _validate_json_payload(
            payload,
            schema_path=schemas_dir / "render_request.schema.json",
            payload_name="Render request template",
        )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    # 4. Check overwrite.
    renders_dir = project_dir / "renders"
    request_path = renders_dir / "render_request.json"
    if request_path.exists() and not force:
        print(
            f"File exists (use --force to overwrite): {request_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    # 5. Ensure renders/ dir exists and write file.
    renders_dir.mkdir(parents=True, exist_ok=True)
    _write_json_file(request_path, payload)

    written: list[str] = ["renders/render_request.json"]
    skipped: list[str] = []

    # 6. Deterministic summary.
    result: dict[str, Any] = {
        "ok": True,
        "project_dir": project_dir.resolve().as_posix(),
        "skipped": skipped,
        "written": written,
    }
    if has_multi:
        target_layout_ids = payload.get("target_layout_ids")
        if isinstance(target_layout_ids, list):
            result["target_layout_ids"] = list(target_layout_ids)
    else:
        target_layout_id = payload.get("target_layout_id")
        if isinstance(target_layout_id, str):
            result["target_layout_id"] = target_layout_id
    options_payload = payload.get("options")
    if isinstance(options_payload, dict):
        target_ids_payload = options_payload.get("target_ids")
        if isinstance(target_ids_payload, list):
            result["target_ids"] = list(target_ids_payload)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _routing_plan_path_from_request(
    *,
    project_dir: Path,
    request_payload: dict[str, Any],
) -> Path | None:
    raw_routing_path = request_payload.get("routing_plan_path")
    if not isinstance(raw_routing_path, str):
        return None
    normalized = raw_routing_path.strip()
    if not normalized:
        return None
    routing_plan_path = Path(normalized)
    if routing_plan_path.is_absolute():
        return routing_plan_path
    return project_dir / routing_plan_path


def _run_project_render_run(
    *,
    project_dir: Path,
    force: bool,
    event_log: bool,
    event_log_force: bool = False,
    preflight: bool = False,
    preflight_force: bool = False,
    execute: bool = False,
    execute_out_path: Path | None = None,
    execute_force: bool = False,
    qa: bool = False,
    qa_out_path: Path | None = None,
    qa_force: bool = False,
    qa_enforce: bool = False,
    recall_sheet: bool = False,
    recall_sheet_force: bool = False,
) -> int:
    """Run deterministic render-run using project-standard scaffold paths."""
    validate_exit = _validate_required_project_artifacts(project_dir)
    if validate_exit != 0:
        return validate_exit

    if event_log_force and not event_log:
        print("--event-log-force requires --event-log.", file=sys.stderr)
        return 1
    if preflight_force and not preflight:
        print("--preflight-force requires --preflight.", file=sys.stderr)
        return 1
    if execute_force and not execute and execute_out_path is None:
        print("--execute-force requires --execute or --execute-out.", file=sys.stderr)
        return 1
    if qa_force and not qa and qa_out_path is None:
        print("--qa-force requires --qa or --qa-out.", file=sys.stderr)
        return 1
    if qa_enforce and not qa and qa_out_path is None:
        print("--qa-enforce requires --qa or --qa-out.", file=sys.stderr)
        return 1
    if recall_sheet_force and not recall_sheet:
        print("--recall-sheet-force requires --recall-sheet.", file=sys.stderr)
        return 1

    # Keep overwrite flags split by artifact class. QA, preflight, execute, and
    # recall outputs are operator-facing evidence, not one disposable temp blob.
    request_path = project_dir / "renders" / "render_request.json"
    scene_path = project_dir / "drafts" / "scene.draft.json"
    plan_out_path = project_dir / "renders" / "render_plan.json"
    report_out_path = project_dir / "renders" / "render_report.json"
    event_log_out_path: Path | None = None
    if event_log:
        event_log_out_path = project_dir / "renders" / "event_log.jsonl"
    preflight_out_path: Path | None = None
    if preflight:
        preflight_out_path = project_dir / "renders" / "render_preflight.json"
    resolved_execute_out_path: Path | None = execute_out_path
    if resolved_execute_out_path is None and execute:
        resolved_execute_out_path = project_dir / "renders" / "render_execute.json"
    resolved_qa_out_path: Path | None = qa_out_path
    if resolved_qa_out_path is None and qa:
        resolved_qa_out_path = project_dir / "renders" / "render_qa.json"
    recall_sheet_out_path: Path | None = None
    if recall_sheet:
        recall_sheet_out_path = project_dir / "renders" / "recall_sheet.csv"

    # Guard overwrite for recall sheet independently.
    if recall_sheet_out_path is not None and recall_sheet_out_path.exists() and not recall_sheet_force:
        print(
            f"File exists (use --recall-sheet-force to overwrite): "
            f"{recall_sheet_out_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    try:
        request_payload = _load_json_object(request_path, label="Render request")
        _validate_json_payload(
            request_payload,
            schema_path=_schemas_dir_fn() / "render_request.schema.json",
            payload_name="Render request",
        )
        routing_plan_path = _routing_plan_path_from_request(
            project_dir=project_dir,
            request_payload=request_payload,
        )

        from mmo.cli_commands._scene import _run_render_run_command  # noqa: WPS433

        # Reuse the canonical scene render path so project and non-project runs
        # stay aligned. The project wrapper owns the only JSON summary it emits.
        # Reuse canonical render-run internals while keeping project wrapper
        # summary deterministic and command-specific.
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = _run_render_run_command(
                repo_root=None,
                request_path=request_path,
                scene_path=scene_path,
                routing_plan_path=routing_plan_path,
                plan_out_path=plan_out_path,
                report_out_path=report_out_path,
                force=force,
                event_log_out_path=event_log_out_path,
                event_log_force=event_log_force,
                preflight_out_path=preflight_out_path,
                preflight_force=preflight_force,
                execute_out_path=resolved_execute_out_path,
                execute_force=execute_force,
                qa_out_path=resolved_qa_out_path,
                qa_force=qa_force,
                qa_enforce=qa_enforce,
            )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    if exit_code != 0:
        return exit_code

    plan_payload = _load_json_object(plan_out_path, label="Render plan")
    raw_targets = plan_payload.get("targets")
    if isinstance(raw_targets, list):
        targets = sorted(
            {
                item.strip()
                for item in raw_targets
                if isinstance(item, str) and item.strip()
            }
        )
    else:
        targets = []
    jobs = plan_payload.get("jobs")
    job_count = len(jobs) if isinstance(jobs, list) else 0

    paths_written = [
        plan_out_path.resolve().as_posix(),
        report_out_path.resolve().as_posix(),
    ]
    if event_log_out_path is not None:
        paths_written.append(event_log_out_path.resolve().as_posix())
    if preflight_out_path is not None:
        paths_written.append(preflight_out_path.resolve().as_posix())
    run_id: str | None = None
    if resolved_execute_out_path is not None and resolved_execute_out_path.is_file():
        paths_written.append(resolved_execute_out_path.resolve().as_posix())
        execute_payload = _load_json_object_if_exists(resolved_execute_out_path)
        if isinstance(execute_payload, dict):
            raw_run_id = execute_payload.get("run_id")
            if isinstance(raw_run_id, str) and raw_run_id.strip():
                run_id = raw_run_id.strip()
    if resolved_qa_out_path is not None and resolved_qa_out_path.is_file():
        paths_written.append(resolved_qa_out_path.resolve().as_posix())
        if run_id is None:
            qa_payload = _load_json_object_if_exists(resolved_qa_out_path)
            if isinstance(qa_payload, dict):
                raw_run_id = qa_payload.get("run_id")
                if isinstance(raw_run_id, str) and raw_run_id.strip():
                    run_id = raw_run_id.strip()

    if recall_sheet_out_path is not None:
        from mmo.exporters.recall_sheet import export_recall_sheet  # noqa: WPS433

        # Load analysis report (report.json) for profile_id and issues/recommendations.
        report_json_path = project_dir / "report.json"
        report_payload = _load_json_object_if_exists(report_json_path) or {}

        # Load scene draft for scene context.
        scene_payload = _load_json_object_if_exists(scene_path)

        # Load request payload for target_layout_ids.
        request_payload_for_recall = _load_json_object_if_exists(request_path)
        render_report_payload_for_recall = _load_json_object_if_exists(report_out_path)

        # Load preflight if it was produced this run.
        preflight_payload: dict[str, Any] | None = None
        if preflight_out_path is not None and preflight_out_path.is_file():
            preflight_payload = _load_json_object_if_exists(preflight_out_path)

        export_recall_sheet(
            report_payload,
            recall_sheet_out_path,
            scene=scene_payload,
            preflight=preflight_payload,
            request=request_payload_for_recall,
            render_report=render_report_payload_for_recall,
        )
        paths_written.append(recall_sheet_out_path.resolve().as_posix())

    summary: dict[str, Any] = {
        "job_count": job_count,
        "paths_written": paths_written,
        "plan_id": str(plan_payload.get("plan_id", "")),
        "targets": targets,
    }
    if run_id is not None:
        summary["run_id"] = run_id
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


# ── project pack ─────────────────────────────────────────────────

# ƒ"?ƒ"? project bundle ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?

def _run_project_bundle(
    *,
    project_dir: Path,
    out_path: Path,
    force: bool,
    include_plugins: bool = False,
    include_plugin_layouts: bool = False,
    include_plugin_layout_snapshots: bool = False,
    include_plugin_ui_hints: bool = False,
    plugins_dir: Path | None = None,
    render_preflight_path: Path | None = None,
) -> int:
    """Build ui_bundle.json from allowlisted project artifacts."""
    if include_plugin_layout_snapshots and not include_plugin_layouts:
        print(
            "--include-plugin-layout-snapshots requires --include-plugin-layouts.",
            file=sys.stderr,
        )
        return 1
    if (include_plugin_layouts or include_plugin_layout_snapshots) and not include_plugins:
        print("--include-plugin-layouts requires --include-plugins.", file=sys.stderr)
        return 1
    if include_plugin_ui_hints and not include_plugins:
        print("--include-plugin-ui-hints requires --include-plugins.", file=sys.stderr)
        return 1

    if out_path.exists() and not force:
        print(
            f"File exists (use --force to overwrite): {out_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    existing_paths: dict[str, Path] = {}
    for rel in _PROJECT_BUNDLE_ALLOWLIST:
        candidate = project_dir / rel
        if candidate.is_file():
            existing_paths[rel] = candidate

    missing_required = sorted(
        rel for rel in _PROJECT_BUNDLE_REQUIRED
        if rel not in existing_paths
    )
    if missing_required:
        for rel in missing_required:
            print(f"Required project artifact missing: {rel}", file=sys.stderr)
        return 1

    report = _load_json_object(existing_paths["report.json"], label="Report")
    plugins_payload: dict[str, Any] | None = None
    if include_plugins:
        from mmo.core.plugin_schema_index import (  # noqa: WPS433
            build_plugins_config_schema_index,
        )

        normalized_plugins_dir = plugins_dir if plugins_dir is not None else Path("plugins")
        plugins_payload = build_plugins_config_schema_index(
            plugins_dir=normalized_plugins_dir,
            include_schema=False,
            include_ui_layout=include_plugin_layouts,
            include_ui_layout_snapshot=include_plugin_layout_snapshots,
            include_ui_hints=include_plugin_ui_hints,
        )

    from mmo.core.ui_bundle import build_ui_bundle  # noqa: WPS433

    render_plan_path = existing_paths.get("renders/render_plan.json")
    render_preflight_artifact_path = (
        render_preflight_path
        if render_preflight_path is not None
        else existing_paths.get("renders/render_preflight.json")
    )
    bundle = build_ui_bundle(
        report,
        None,
        help_registry_path=_ontology_dir_fn() / "help.yaml",
        ui_copy_path=_ontology_dir_fn() / "ui_copy.yaml",
        listen_pack_path=existing_paths.get("listen_pack.json"),
        scene_path=existing_paths.get("drafts/scene.draft.json"),
        render_plan_path=render_plan_path,
        stems_index_path=existing_paths.get("stems/stems_index.json"),
        stems_map_path=existing_paths.get("stems/stems_map.json"),
        render_request_path=existing_paths.get("renders/render_request.json"),
        render_plan_artifact_path=render_plan_path,
        render_execute_path=existing_paths.get("renders/render_execute.json"),
        render_preflight_path=render_preflight_artifact_path,
        render_report_path=existing_paths.get("renders/render_report.json"),
        event_log_path=existing_paths.get("renders/event_log.jsonl"),
        plugins=plugins_payload,
    )
    _validate_json_payload(
        bundle,
        schema_path=_schemas_dir_fn() / "ui_bundle.schema.json",
        payload_name="UI bundle",
    )
    _write_json_file(out_path, bundle)

    result: dict[str, Any] = {
        "included": [
            rel for rel in _PROJECT_BUNDLE_ALLOWLIST
            if rel in existing_paths
        ],
        "missing": [
            rel for rel in _PROJECT_BUNDLE_ALLOWLIST
            if rel not in existing_paths
        ],
        "ok": True,
        "out": out_path.resolve().as_posix(),
        "project_dir": project_dir.resolve().as_posix(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


# Allowlisted artifact relative paths eligible for packing.
_PACK_ARTIFACTS: list[str] = list(_PROJECT_SHOW_ALLOWLIST)

# Fixed date_time for all zip entries (no real timestamps).
_ZIP_DATE_TIME = (2000, 1, 1, 0, 0, 0)


def _run_project_pack(
    *,
    project_dir: Path,
    out_path: Path,
    include_wavs: bool,
    force: bool,
) -> int:
    """Pack project artifacts into a deterministic zip. Returns exit code."""
    if out_path.exists() and not force:
        print(
            f"File exists (use --force to overwrite): {out_path.as_posix()}",
            file=sys.stderr,
        )
        return 1

    # Collect existing allowlisted files.
    collected: list[tuple[str, Path]] = []
    for rel in _PACK_ARTIFACTS:
        fp = project_dir / rel
        if fp.is_file():
            collected.append((rel, fp))

    # Optionally include audition WAVs.
    if include_wavs:
        auditions_dir = project_dir / "stems_auditions"
        if auditions_dir.is_dir():
            for wav in sorted(auditions_dir.glob("*.wav")):
                rel = f"stems_auditions/{wav.name}"
                collected.append((rel, wav))

    # Sort by relative path for determinism.
    collected.sort(key=lambda item: item[0])

    # Build manifest entries.
    manifest_files: list[dict[str, Any]] = []
    for rel, fp in collected:
        data = fp.read_bytes()
        manifest_files.append({
            "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })

    manifest: dict[str, Any] = {
        "file_count": len(manifest_files),
        "files": manifest_files,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    # Write the zip.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, fp in collected:
            info = zipfile.ZipInfo(filename=rel, date_time=_ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, fp.read_bytes())
        # Manifest last.
        info = zipfile.ZipInfo(filename="manifest.json", date_time=_ZIP_DATE_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, manifest_bytes)

    result: dict[str, Any] = {
        "file_count": len(collected),
        "ok": True,
        "out": out_path.resolve().as_posix(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _project_last_run_payload(*, mode: str, out_dir: Path) -> dict[str, Any]:
    resolved_out_dir = out_dir.resolve()
    payload: dict[str, Any] = {
        "mode": mode,
        "out_dir": resolved_out_dir.as_posix(),
    }

    deliverables_index_path = resolved_out_dir / "deliverables_index.json"
    if deliverables_index_path.exists():
        payload["deliverables_index_path"] = deliverables_index_path.as_posix()

    listen_pack_path = resolved_out_dir / "listen_pack.json"
    if listen_pack_path.exists():
        payload["listen_pack_path"] = listen_pack_path.as_posix()

    if mode == "variants":
        variant_plan_path = resolved_out_dir / "variant_plan.json"
        variant_result_path = resolved_out_dir / "variant_result.json"
        if variant_plan_path.exists():
            payload["variant_plan_path"] = variant_plan_path.as_posix()
        if variant_result_path.exists():
            payload["variant_result_path"] = variant_result_path.as_posix()
    return payload


def _project_run_config_defaults(
    *,
    mode: str,
    out_dir: Path,
) -> dict[str, Any] | None:
    resolved_out_dir = out_dir.resolve()
    try:
        if mode == "single":
            report_path = resolved_out_dir / "report.json"
            if not report_path.exists():
                return None
            report = _load_json_object(report_path, label="Report")
            run_config = report.get("run_config")
            if isinstance(run_config, dict):
                return normalize_run_config(run_config)
            return None

        if mode == "variants":
            plan_path = resolved_out_dir / "variant_plan.json"
            if not plan_path.exists():
                return None
            variant_plan = _load_json_object(plan_path, label="Variant plan")
            base_run_config = variant_plan.get("base_run_config")
            if isinstance(base_run_config, dict):
                return normalize_run_config(base_run_config)
            return None
    except ValueError:
        return None
    return None


def _render_project_text(project: dict[str, Any]) -> str:
    lines = [
        f"project_id: {project.get('project_id', '')}",
        f"stems_dir: {project.get('stems_dir', '')}",
        f"created_at_utc: {project.get('created_at_utc', '')}",
        f"updated_at_utc: {project.get('updated_at_utc', '')}",
    ]

    timeline_path = project.get("timeline_path")
    if isinstance(timeline_path, str):
        lines.append(f"timeline_path: {timeline_path}")

    lockfile_path = project.get("lockfile_path")
    if isinstance(lockfile_path, str):
        lines.append(f"lockfile_path: {lockfile_path}")

    lock_hash = project.get("lock_hash")
    if isinstance(lock_hash, str):
        lines.append(f"lock_hash: {lock_hash}")

    last_run = project.get("last_run")
    if isinstance(last_run, dict):
        lines.append("last_run:")
        lines.append(json.dumps(last_run, indent=2, sort_keys=True))

    run_config_defaults = project.get("run_config_defaults")
    if isinstance(run_config_defaults, dict):
        lines.append("run_config_defaults:")
        lines.append(json.dumps(run_config_defaults, indent=2, sort_keys=True))

    notes = project.get("notes")
    if isinstance(notes, str):
        lines.append(f"notes: {notes}")

    return "\n".join(lines)
