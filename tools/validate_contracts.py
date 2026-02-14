"""Umbrella validator for core repository contracts."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SRC_DIR = SCRIPT_REPO_ROOT / "src"
if str(SCRIPT_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_SRC_DIR))

from mmo.core.schema_registry import (  # noqa: E402
    build_schema_registry,
    load_json_schema,
    unresolved_schema_refs,
)


@dataclass(frozen=True)
class ExternalCheckSpec:
    check_id: str
    tool: str
    args: tuple[str, ...]


EXTERNAL_CHECKS: tuple[ExternalCheckSpec, ...] = (
    ExternalCheckSpec("UI.SPECS", "tools/validate_ui_specs.py", ("--repo-root", ".")),
    ExternalCheckSpec("UI.EXAMPLES", "tools/validate_ui_examples.py", ("--repo-root", ".")),
    ExternalCheckSpec("ONTOLOGY.REFS", "tools/validate_ontology_refs.py", ("--ontology", "ontology")),
    ExternalCheckSpec(
        "PLUGINS",
        "tools/validate_plugins.py",
        ("plugins", "--schema", "schemas/plugin.schema.json"),
    ),
)

SCHEMA_SMOKE_CHECK_ID = "SCHEMAS"
SCHEMA_SMOKE_TOOL = "src/mmo/core/schema_registry.py"
SCHEMA_ANCHORS: tuple[str, ...] = (
    "schemas/report.schema.json",
    "schemas/ui_bundle.schema.json",
    "schemas/gui_state.schema.json",
    "schemas/scene.schema.json",
    "schemas/render_targets.schema.json",
    "schemas/roles.schema.json",
    "schemas/translation_profiles.schema.json",
    "schemas/render_plan.schema.json",
    "schemas/presets_index.schema.json",
    "schemas/lockfile.schema.json",
    "schemas/role_lexicon.schema.json",
    "schemas/stems_index.schema.json",
    "schemas/stems_map.schema.json",
    "schemas/stems_overrides.schema.json",
    "schemas/stems_audition_manifest.schema.json",
)

SCENE_REGISTRIES_CHECK_ID = "SCENE.REGISTRIES"
SCENE_REGISTRIES_TOOL = (
    "src/mmo/core/{speaker_positions.py,scene_locks.py,scene_templates.py,intent_params.py,render_targets.py}"
)
SCENE_REGISTRY_LOADERS: tuple[tuple[str, str, str], ...] = (
    (
        "load_speaker_positions",
        "mmo.core.speaker_positions",
        "ontology/speaker_positions.yaml",
    ),
    ("load_scene_locks", "mmo.core.scene_locks", "ontology/scene_locks.yaml"),
    (
        "list_scene_templates",
        "mmo.core.scene_templates",
        "ontology/scene_templates.yaml",
    ),
    ("load_intent_params", "mmo.core.intent_params", "ontology/intent_params.yaml"),
    ("list_render_targets", "mmo.core.render_targets", "ontology/render_targets.yaml"),
)

TRANSLATION_REGISTRIES_CHECK_ID = "TRANSLATION.REGISTRIES"
TRANSLATION_REGISTRIES_TOOL = "src/mmo/core/translation_profiles.py"
TRANSLATION_REGISTRY_LOADER: tuple[str, str, str] = (
    "list_translation_profiles",
    "mmo.core.translation_profiles",
    "ontology/translation_profiles.yaml",
)

ROLES_REGISTRIES_CHECK_ID = "ROLES.REGISTRIES"
ROLES_REGISTRIES_TOOL = "src/mmo/core/roles.py"
ROLES_REGISTRY_LOADER: tuple[str, str, str] = (
    "load_roles",
    "mmo.core.roles",
    "ontology/roles.yaml",
)
ROLE_LEXICON_COMMON_CHECK_ID = "ROLE_LEXICON.COMMON"
ROLE_LEXICON_COMMON_TOOL = "src/mmo/core/role_lexicon.py"
ROLE_LEXICON_COMMON_REL_PATH = "ontology/role_lexicon_common.yaml"


def _tail_text(value: str, *, max_lines: int = 20, max_chars: int = 2000) -> str:
    text = value.strip()
    if not text:
        return ""
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def _build_check_payload(
    *,
    check_id: str,
    ok: bool,
    exit_code: int,
    tool: str,
    details: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "ok": ok,
        "exit_code": exit_code,
        "tool": tool,
        "details": details,
        "errors": errors,
    }


def _standalone_command(check: ExternalCheckSpec) -> str:
    return " ".join(["python", check.tool, *check.args])


def _build_subprocess_env(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    src_dir = repo_root / "src"
    if src_dir.exists():
        existing = env.get("PYTHONPATH", "")
        src = os.fspath(src_dir)
        env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    return env


def _parse_json_stdout(stdout: str) -> tuple[Any | None, str | None]:
    text = stdout.strip()
    if not text:
        return None, "Validator produced empty stdout; expected JSON output."
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return (
            None,
            (
                "Validator stdout was not valid JSON: "
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}."
            ),
        )


def _details_from_unparsed_output(stdout: str, stderr: str) -> dict[str, Any]:
    details: dict[str, Any] = {}
    stdout_tail = _tail_text(stdout)
    stderr_tail = _tail_text(stderr)
    if stdout_tail:
        details["stdout_tail"] = stdout_tail
    if stderr_tail:
        details["stderr_tail"] = stderr_tail
    return details


def _run_external_check(
    check: ExternalCheckSpec,
    *,
    repo_root: Path,
    strict: bool,
) -> dict[str, Any]:
    tool_path = repo_root / check.tool
    if not tool_path.exists():
        errors = [
            f"Required validator tool is missing: {check.tool}",
            f"Run alone: {_standalone_command(check)}",
        ]
        details = {"expected_path": str(tool_path)}
        return _build_check_payload(
            check_id=check.check_id,
            ok=False,
            exit_code=2,
            tool=check.tool,
            details=details,
            errors=errors,
        )

    command = [sys.executable, os.fspath(tool_path), *check.args]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=_build_subprocess_env(repo_root),
        )
    except OSError as exc:
        errors = [
            f"Failed to execute validator {check.tool}: {exc}",
            f"Run alone: {_standalone_command(check)}",
        ]
        details = {"expected_path": str(tool_path)}
        return _build_check_payload(
            check_id=check.check_id,
            ok=False,
            exit_code=2,
            tool=check.tool,
            details=details,
            errors=errors,
        )

    parsed_output, parse_error = _parse_json_stdout(completed.stdout)
    if isinstance(parsed_output, dict):
        details: dict[str, Any] = parsed_output
    elif parsed_output is not None:
        details = {"parsed_json": parsed_output}
    else:
        details = _details_from_unparsed_output(completed.stdout, completed.stderr)

    exit_code = 0 if completed.returncode == 0 else 1
    if completed.returncode == 0 and parse_error is not None and strict:
        exit_code = 2

    ok = exit_code == 0
    errors: list[str] = []
    if not ok:
        if completed.returncode != 0:
            errors.append(f"Validator exited with code {completed.returncode}.")
        if parse_error is not None:
            errors.append(parse_error)
        stderr_tail = _tail_text(completed.stderr)
        if stderr_tail:
            errors.append(f"stderr tail:\n{stderr_tail}")
        errors.append(f"Run alone: {_standalone_command(check)}")
    elif parse_error is not None:
        details = dict(details)
        details["parse_warning"] = parse_error

    return _build_check_payload(
        check_id=check.check_id,
        ok=ok,
        exit_code=exit_code,
        tool=check.tool,
        details=details,
        errors=errors,
    )


def _anchor_schema_status(
    *,
    repo_root: Path,
    anchor: str,
    registry: Any,
) -> dict[str, Any]:
    anchor_path = repo_root / anchor
    anchor_result: dict[str, Any] = {"schema": anchor, "ok": True}
    anchor_errors: list[str] = []
    unresolved_refs: list[str] = []

    if not anchor_path.exists():
        anchor_result["ok"] = False
        anchor_errors.append(f"Missing required schema anchor: {anchor}")
    else:
        try:
            schema = load_json_schema(anchor_path)
            if jsonschema is None:
                raise RuntimeError("jsonschema is required to validate schema anchors.")
            jsonschema.Draft202012Validator.check_schema(schema)
            unresolved_refs = unresolved_schema_refs(
                schema,
                registry=registry,
                default_base_uri=anchor_path.resolve().as_uri(),
            )
            if unresolved_refs:
                anchor_result["ok"] = False
                anchor_errors.append(
                    f"Schema anchor has unresolved $ref values: {anchor}"
                )
        except Exception as exc:
            anchor_result["ok"] = False
            anchor_errors.append(f"Failed to load schema anchor {anchor}: {exc}")

    if unresolved_refs:
        anchor_result["unresolved_refs"] = unresolved_refs
    if anchor_errors:
        anchor_result["errors"] = anchor_errors
    return anchor_result


def _scene_registry_summary(*, loader_name: str, payload: Any) -> dict[str, int]:
    if loader_name == "load_speaker_positions":
        layouts = payload.get("layouts") if isinstance(payload, dict) else None
        return {"layouts": len(layouts) if isinstance(layouts, dict) else 0}
    if loader_name == "load_scene_locks":
        locks = payload.get("locks") if isinstance(payload, dict) else None
        return {"locks": len(locks) if isinstance(locks, dict) else 0}
    if loader_name == "list_scene_templates":
        return {"templates": len(payload) if isinstance(payload, list) else 0}
    if loader_name == "load_intent_params":
        params = payload.get("params") if isinstance(payload, dict) else None
        return {"params": len(params) if isinstance(params, dict) else 0}
    if loader_name == "list_render_targets":
        return {"targets": len(payload) if isinstance(payload, list) else 0}
    return {}


def _translation_registry_summary(*, loader_name: str, payload: Any) -> dict[str, int]:
    if loader_name == "list_translation_profiles":
        return {"profiles": len(payload) if isinstance(payload, list) else 0}
    return {}


def _roles_registry_summary(*, loader_name: str, payload: Any) -> dict[str, int]:
    if loader_name == "load_roles":
        roles = payload.get("roles") if isinstance(payload, dict) else None
        if not isinstance(roles, dict):
            return {"roles": 0}
        count = sum(
            1
            for role_id, role_payload in roles.items()
            if (
                isinstance(role_id, str)
                and role_id != "_meta"
                and isinstance(role_payload, dict)
            )
        )
        return {"roles": count}
    return {}


def _run_scene_registries_check(*, repo_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {"loaders": []}
    errors: list[str] = []

    for loader_name, module_name, relative_path in SCENE_REGISTRY_LOADERS:
        registry_path = repo_root / relative_path
        loader_details: dict[str, Any] = {
            "loader": loader_name,
            "module": module_name,
            "path": relative_path,
            "ok": True,
        }

        if not registry_path.is_file():
            loader_details["ok"] = False
            loader_details["error"] = f"Required registry is missing: {relative_path}"
            errors.append(f"Required registry is missing: {relative_path}")
            details["loaders"].append(loader_details)
            continue

        try:
            module = importlib.import_module(module_name)
            loader = getattr(module, loader_name)
        except Exception as exc:
            loader_details["ok"] = False
            loader_details["error"] = str(exc)
            errors.append(f"Failed to import {module_name}.{loader_name}: {exc}")
            details["loaders"].append(loader_details)
            continue

        try:
            payload = loader(registry_path)
        except Exception as exc:
            loader_details["ok"] = False
            loader_details["error"] = str(exc)
            errors.append(f"{loader_name} failed for {relative_path}: {exc}")
            details["loaders"].append(loader_details)
            continue

        loader_details["summary"] = _scene_registry_summary(
            loader_name=loader_name,
            payload=payload,
        )
        details["loaders"].append(loader_details)

    ok = not errors
    if not ok:
        errors.append("Run alone: python tools/validate_contracts.py --strict")
    return _build_check_payload(
        check_id=SCENE_REGISTRIES_CHECK_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        tool=SCENE_REGISTRIES_TOOL,
        details=details,
        errors=errors,
    )


def _run_translation_registries_check(*, repo_root: Path) -> dict[str, Any]:
    loader_name, module_name, relative_path = TRANSLATION_REGISTRY_LOADER
    details: dict[str, Any] = {"loaders": []}
    errors: list[str] = []

    registry_path = repo_root / relative_path
    loader_details: dict[str, Any] = {
        "loader": loader_name,
        "module": module_name,
        "path": relative_path,
        "ok": True,
    }

    if not registry_path.is_file():
        loader_details["ok"] = False
        loader_details["error"] = f"Required registry is missing: {relative_path}"
        errors.append(f"Required registry is missing: {relative_path}")
        details["loaders"].append(loader_details)
    else:
        try:
            module = importlib.import_module(module_name)
            loader = getattr(module, loader_name)
        except Exception as exc:
            loader_details["ok"] = False
            loader_details["error"] = str(exc)
            errors.append(f"Failed to import {module_name}.{loader_name}: {exc}")
            details["loaders"].append(loader_details)
        else:
            try:
                payload = loader(registry_path)
            except Exception as exc:
                loader_details["ok"] = False
                loader_details["error"] = str(exc)
                errors.append(f"{loader_name} failed for {relative_path}: {exc}")
                details["loaders"].append(loader_details)
            else:
                loader_details["summary"] = _translation_registry_summary(
                    loader_name=loader_name,
                    payload=payload,
                )
                details["loaders"].append(loader_details)

    ok = not errors
    if not ok:
        errors.append("Run alone: python tools/validate_contracts.py --strict")
    return _build_check_payload(
        check_id=TRANSLATION_REGISTRIES_CHECK_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        tool=TRANSLATION_REGISTRIES_TOOL,
        details=details,
        errors=errors,
    )


def _run_roles_registries_check(*, repo_root: Path) -> dict[str, Any]:
    loader_name, module_name, relative_path = ROLES_REGISTRY_LOADER
    details: dict[str, Any] = {"loaders": []}
    errors: list[str] = []

    registry_path = repo_root / relative_path
    loader_details: dict[str, Any] = {
        "loader": loader_name,
        "module": module_name,
        "path": relative_path,
        "ok": True,
    }

    if not registry_path.is_file():
        loader_details["ok"] = False
        loader_details["error"] = f"Required registry is missing: {relative_path}"
        errors.append(f"Required registry is missing: {relative_path}")
        details["loaders"].append(loader_details)
    else:
        try:
            module = importlib.import_module(module_name)
            loader = getattr(module, loader_name)
        except Exception as exc:
            loader_details["ok"] = False
            loader_details["error"] = str(exc)
            errors.append(f"Failed to import {module_name}.{loader_name}: {exc}")
            details["loaders"].append(loader_details)
        else:
            try:
                payload = loader(registry_path)
            except Exception as exc:
                loader_details["ok"] = False
                loader_details["error"] = str(exc)
                errors.append(f"{loader_name} failed for {relative_path}: {exc}")
                details["loaders"].append(loader_details)
            else:
                loader_details["summary"] = _roles_registry_summary(
                    loader_name=loader_name,
                    payload=payload,
                )
                role_lexicon_rel_path = "ontology/role_lexicon.yaml"
                role_lexicon_path = repo_root / role_lexicon_rel_path
                role_lexicon_details: dict[str, Any] = {
                    "path": role_lexicon_rel_path,
                    "present": role_lexicon_path.is_file(),
                    "ok": True,
                }
                if role_lexicon_path.is_file():
                    try:
                        lexicon_module = importlib.import_module("mmo.core.role_lexicon")
                        load_role_lexicon = getattr(lexicon_module, "load_role_lexicon")
                        lexicon_payload = load_role_lexicon(
                            role_lexicon_path,
                            roles_payload=payload,
                        )
                        role_lexicon_details["entries"] = len(lexicon_payload)
                    except Exception as exc:
                        role_lexicon_details["ok"] = False
                        role_lexicon_details["error"] = str(exc)
                        loader_details["ok"] = False
                        errors.append(
                            f"load_role_lexicon failed for {role_lexicon_rel_path}: {exc}"
                        )
                loader_details["role_lexicon"] = role_lexicon_details
                details["loaders"].append(loader_details)

    ok = not errors
    if not ok:
        errors.append("Run alone: python tools/validate_contracts.py --strict")
    return _build_check_payload(
        check_id=ROLES_REGISTRIES_CHECK_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        tool=ROLES_REGISTRIES_TOOL,
        details=details,
        errors=errors,
    )


def _run_role_lexicon_common_check(*, repo_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {
        "path": ROLE_LEXICON_COMMON_REL_PATH,
        "schema": "schemas/role_lexicon.schema.json",
        "ok": True,
    }
    errors: list[str] = []

    roles_registry_path = repo_root / ROLES_REGISTRY_LOADER[2]
    common_lexicon_path = repo_root / ROLE_LEXICON_COMMON_REL_PATH
    if not common_lexicon_path.is_file():
        details["ok"] = False
        details["present"] = False
        errors.append(f"Required role lexicon is missing: {ROLE_LEXICON_COMMON_REL_PATH}")
    else:
        details["present"] = True

    if not roles_registry_path.is_file():
        details["ok"] = False
        errors.append(f"Required registry is missing: {ROLES_REGISTRY_LOADER[2]}")

    if not errors:
        try:
            roles_module = importlib.import_module(ROLES_REGISTRY_LOADER[1])
            load_roles = getattr(roles_module, ROLES_REGISTRY_LOADER[0])
            lexicon_module = importlib.import_module("mmo.core.role_lexicon")
            load_common_role_lexicon = getattr(lexicon_module, "load_common_role_lexicon")
            roles_payload = load_roles(roles_registry_path)
            lexicon_payload = load_common_role_lexicon(
                common_lexicon_path,
                roles_payload=roles_payload,
            )
        except Exception as exc:
            details["ok"] = False
            details["error"] = str(exc)
            errors.append(f"load_common_role_lexicon failed for {ROLE_LEXICON_COMMON_REL_PATH}: {exc}")
        else:
            details["entries"] = len(lexicon_payload)
            details["role_ids"] = sorted(lexicon_payload.keys())

    ok = not errors
    if not ok:
        errors.append("Run alone: python tools/validate_contracts.py --strict")
    return _build_check_payload(
        check_id=ROLE_LEXICON_COMMON_CHECK_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        tool=ROLE_LEXICON_COMMON_TOOL,
        details=details,
        errors=errors,
    )


def _run_schema_smoke_check(*, repo_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {"anchors": []}
    errors: list[str] = []

    if jsonschema is None:
        errors.append("jsonschema is not installed; cannot validate schema anchors.")
        errors.append("Run: python -m pip install jsonschema")
        return _build_check_payload(
            check_id=SCHEMA_SMOKE_CHECK_ID,
            ok=False,
            exit_code=2,
            tool=SCHEMA_SMOKE_TOOL,
            details=details,
            errors=errors,
        )

    schemas_dir = repo_root / "schemas"
    if not schemas_dir.exists() or not schemas_dir.is_dir():
        errors.append(f"Required schemas directory is missing: {schemas_dir}")
        errors.append("Run alone: python tools/validate_contracts.py --strict")
        return _build_check_payload(
            check_id=SCHEMA_SMOKE_CHECK_ID,
            ok=False,
            exit_code=1,
            tool=SCHEMA_SMOKE_TOOL,
            details=details,
            errors=errors,
        )

    try:
        registry = build_schema_registry(schemas_dir)
    except RuntimeError as exc:
        errors.append(str(exc))
        errors.append("Run: python -m pip install referencing")
        return _build_check_payload(
            check_id=SCHEMA_SMOKE_CHECK_ID,
            ok=False,
            exit_code=2,
            tool=SCHEMA_SMOKE_TOOL,
            details=details,
            errors=errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
        errors.append("Run alone: python tools/validate_contracts.py --strict")
        return _build_check_payload(
            check_id=SCHEMA_SMOKE_CHECK_ID,
            ok=False,
            exit_code=1,
            tool=SCHEMA_SMOKE_TOOL,
            details=details,
            errors=errors,
        )

    for anchor in SCHEMA_ANCHORS:
        anchor_result = _anchor_schema_status(
            repo_root=repo_root,
            anchor=anchor,
            registry=registry,
        )
        details["anchors"].append(anchor_result)
        if not anchor_result.get("ok"):
            for message in anchor_result.get("errors", []):
                if isinstance(message, str):
                    errors.append(message)

    ok = not errors
    if not ok:
        errors.append("Run alone: python tools/validate_contracts.py --strict")
    return _build_check_payload(
        check_id=SCHEMA_SMOKE_CHECK_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        tool=SCHEMA_SMOKE_TOOL,
        details=details,
        errors=errors,
    )


def run_contract_checks(*, repo_root: Path, strict: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for check in EXTERNAL_CHECKS:
        checks.append(_run_external_check(check, repo_root=repo_root, strict=strict))
    checks.append(_run_scene_registries_check(repo_root=repo_root))
    checks.append(_run_translation_registries_check(repo_root=repo_root))
    checks.append(_run_roles_registries_check(repo_root=repo_root))
    checks.append(_run_role_lexicon_common_check(repo_root=repo_root))
    checks.append(_run_schema_smoke_check(repo_root=repo_root))

    failed = [check["check_id"] for check in checks if not check.get("ok")]
    passed = [check["check_id"] for check in checks if check.get("ok")]
    return {
        "ok": not failed,
        "checks": checks,
        "summary": {
            "failed": failed,
            "passed": passed,
        },
    }


def _output_payload(result: dict[str, Any], *, quiet: bool) -> dict[str, Any]:
    if not quiet:
        return result
    return {
        "ok": bool(result.get("ok")),
        "summary": result.get("summary", {"failed": [], "passed": []}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository core contracts.")
    parser.add_argument(
        "--repo-root",
        default=str(SCRIPT_REPO_ROOT),
        help="Repository root containing tools/, schemas/, ontology/, and plugins/.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write deterministic JSON output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail checks that do not emit valid JSON output.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only minimal deterministic summary JSON.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    result = run_contract_checks(repo_root=repo_root, strict=args.strict)
    output = _output_payload(result, quiet=args.quiet)
    serialized = json.dumps(output, sort_keys=True, indent=2)
    print(serialized)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized + "\n", encoding="utf-8")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
