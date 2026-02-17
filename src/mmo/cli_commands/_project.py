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
    "_run_project_render_init",
    "_run_project_render_run",
    "_run_project_validate",
]


# ── project validate ─────────────────────────────────────────────

# (rel_path, schema_basename | None for YAML, required)
_VALIDATE_CHECKS: list[tuple[str, str | None, bool]] = [
    ("drafts/routing_plan.draft.json", "routing_plan.schema.json", True),
    ("drafts/scene.draft.json", "scene.schema.json", True),
    ("renders/event_log.jsonl", "event.schema.json", False),
    ("renders/render_plan.json", "render_plan.schema.json", False),
    ("renders/render_report.json", "render_report.schema.json", False),
    ("renders/render_request.json", "render_request.schema.json", False),
    ("report.json", "report.schema.json", False),
    ("stems/stems_index.json", "stems_index.schema.json", True),
    ("stems/stems_map.json", "stems_map.schema.json", True),
    ("stems/stems_overrides.yaml", "stems_overrides.schema.json", True),
    ("stems_auditions/manifest.json", "stems_audition_manifest.schema.json", False),
    ("ui_bundle.json", "ui_bundle.schema.json", False),
]

_PROJECT_BUNDLE_ALLOWLIST: tuple[str, ...] = (
    "report.json",
    "listen_pack.json",
    "stems/stems_index.json",
    "stems/stems_map.json",
    "drafts/scene.draft.json",
    "drafts/routing_plan.draft.json",
    "renders/render_request.json",
    "renders/render_plan.json",
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
        from mmo.cli_commands._helpers import _build_schema_registry
        registry = _build_schema_registry(schemas_dir)
    except (ValueError, RuntimeError):
        registry = None

    validator_kwargs: dict[str, Any] = {"schema": schema}
    if registry is not None:
        validator_kwargs["registry"] = registry
    validator = jsonschema.Draft202012Validator(**validator_kwargs)
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

    result: dict[str, Any] = {
        "ok": ok,
        "project_dir": project_dir.resolve().as_posix(),
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

    selected = {
        item.strip()
        for item in raw_value.split(",")
        if isinstance(item, str) and item.strip()
    }
    if not selected:
        raise ValueError("target-ids must include at least one target ID.")

    normalized_target_ids = sorted(selected)
    from mmo.core.registries.render_targets_registry import (  # noqa: WPS433
        load_render_targets_registry,
    )

    target_registry = load_render_targets_registry()
    for target_id in normalized_target_ids:
        target_registry.get_target(target_id)
    return normalized_target_ids


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
    event_log_force: bool,
) -> int:
    """Run deterministic render-run using project-standard scaffold paths."""
    validate_exit = _validate_required_project_artifacts(project_dir)
    if validate_exit != 0:
        return validate_exit

    request_path = project_dir / "renders" / "render_request.json"
    scene_path = project_dir / "drafts" / "scene.draft.json"
    plan_out_path = project_dir / "renders" / "render_plan.json"
    report_out_path = project_dir / "renders" / "render_report.json"
    event_log_out_path: Path | None = None
    if event_log:
        event_log_out_path = project_dir / "renders" / "event_log.jsonl"

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
        )
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

    summary: dict[str, Any] = {
        "job_count": job_count,
        "paths_written": paths_written,
        "plan_id": str(plan_payload.get("plan_id", "")),
        "targets": targets,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


# ── project pack ─────────────────────────────────────────────────

# ƒ"?ƒ"? project bundle ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?ƒ"?

def _run_project_bundle(
    *,
    project_dir: Path,
    out_path: Path,
    force: bool,
) -> int:
    """Build ui_bundle.json from allowlisted project artifacts."""
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

    from mmo.core.ui_bundle import build_ui_bundle  # noqa: WPS433

    render_plan_path = existing_paths.get("renders/render_plan.json")
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
        render_report_path=existing_paths.get("renders/render_report.json"),
        event_log_path=existing_paths.get("renders/event_log.jsonl"),
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
_PACK_ARTIFACTS: list[str] = [
    rel for rel, _, _ in _VALIDATE_CHECKS
] + [
    "listen_pack.json",
]

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
