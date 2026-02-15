from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from mmo.cli_commands._helpers import _load_json_object
from mmo.core.run_config import normalize_run_config

__all__ = [
    "_project_last_run_payload",
    "_project_run_config_defaults",
    "_render_project_text",
    "_run_project_pack",
    "_run_project_validate",
]


# ── project validate ─────────────────────────────────────────────

# (rel_path, schema_basename | None for YAML, required)
_VALIDATE_CHECKS: list[tuple[str, str | None, bool]] = [
    ("drafts/routing_plan.draft.json", "routing_plan.schema.json", True),
    ("drafts/scene.draft.json", "scene.schema.json", True),
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
    repo_root: Path,
) -> int:
    """Run project validate and print/write the result. Returns exit code."""
    schemas_dir = repo_root / "schemas"
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

    output_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(output_text)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")

    return 0 if ok else 2


# ── project pack ─────────────────────────────────────────────────

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
