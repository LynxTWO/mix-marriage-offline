"""Plugin manifest validator."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None


ISSUE_PLUGIN_PARSE_ERROR = "ISSUE.VALIDATION.PLUGIN_PARSE_ERROR"
ISSUE_PLUGIN_SCHEMA_INVALID = "ISSUE.VALIDATION.PLUGIN_SCHEMA_INVALID"
ISSUE_PLUGIN_ENTRYPOINT_INVALID = "ISSUE.VALIDATION.PLUGIN_ENTRYPOINT_INVALID"
ISSUE_PLUGIN_ID_TYPE_MISMATCH = "ISSUE.VALIDATION.PLUGIN_ID_TYPE_MISMATCH"
ISSUE_PLUGIN_ID_DUPLICATE = "ISSUE.VALIDATION.PLUGIN_ID_DUPLICATE"
ISSUE_PLUGIN_CAPABILITIES_INVALID = "ISSUE.VALIDATION.PLUGIN_CAPABILITIES_INVALID"
ISSUE_PLUGIN_LAYOUT_ID_UNKNOWN = "ISSUE.VALIDATION.PLUGIN_LAYOUT_ID_UNKNOWN"

PLUGIN_PREFIX_BY_TYPE = {
    "detector": "PLUGIN.DETECTOR.",
    "resolver": "PLUGIN.RESOLVER.",
    "renderer": "PLUGIN.RENDERER.",
}


def _add_issue(
    issues: List[Dict[str, Any]],
    issue_id: str,
    severity_label: str,
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    item: Dict[str, Any] = {
        "issue_id": issue_id,
        "severity_label": severity_label,
        "message": message,
    }
    if evidence:
        item["evidence"] = evidence
    issues.append(item)


def _load_yaml(path: Path, issues: List[Dict[str, Any]]) -> Optional[Any]:
    if yaml is None:
        _add_issue(
            issues,
            ISSUE_PLUGIN_PARSE_ERROR,
            "error",
            "PyYAML is not installed; cannot parse YAML files.",
            {"file_path": str(path)},
        )
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:  # pragma: no cover - parse failures vary
        _add_issue(
            issues,
            ISSUE_PLUGIN_PARSE_ERROR,
            "error",
            f"Failed to parse YAML: {exc}",
            {"file_path": str(path)},
        )
        return None


def _load_schema(path: Path, issues: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if jsonschema is None:
        _add_issue(
            issues,
            ISSUE_PLUGIN_SCHEMA_INVALID,
            "error",
            "jsonschema is not installed; cannot validate plugin manifests.",
            {"file_path": str(path)},
        )
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - parse failures vary
        _add_issue(
            issues,
            ISSUE_PLUGIN_SCHEMA_INVALID,
            "error",
            f"Failed to load schema: {exc}",
            {"file_path": str(path)},
        )
        return None


def _collect_manifests(plugins_dir: Path) -> List[Path]:
    patterns = ["plugin.yaml", "plugin.yml", "*.plugin.yaml"]
    paths: set[Path] = set()
    for pattern in patterns:
        for match in plugins_dir.rglob(pattern):
            if match.is_file():
                paths.add(match)
    return sorted(paths, key=lambda p: str(p))


def _validate_schema(
    schema: Dict[str, Any],
    data: Any,
    manifest_path: Path,
    issues: List[Dict[str, Any]],
) -> bool:
    if jsonschema is None:
        return False
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
    for err in errors:
        _add_issue(
            issues,
            ISSUE_PLUGIN_SCHEMA_INVALID,
            "error",
            f"Schema validation failed: {err.message}",
            {"file_path": str(manifest_path)},
        )
    return not errors


def _validate_entrypoint(
    entrypoint: str,
    manifest_path: Path,
    issues: List[Dict[str, Any]],
) -> None:
    if ":" not in entrypoint:
        _add_issue(
            issues,
            ISSUE_PLUGIN_ENTRYPOINT_INVALID,
            "error",
            "Entrypoint must be in module:Symbol format.",
            {"file_path": str(manifest_path), "entrypoint": entrypoint},
        )
        return

    module_name, symbol_name = entrypoint.split(":", 1)
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        _add_issue(
            issues,
            ISSUE_PLUGIN_ENTRYPOINT_INVALID,
            "error",
            f"Failed to import entrypoint module: {exc}",
            {"file_path": str(manifest_path), "entrypoint": entrypoint},
        )
        return

    if not hasattr(module, symbol_name):
        _add_issue(
            issues,
            ISSUE_PLUGIN_ENTRYPOINT_INVALID,
            "error",
            "Entrypoint symbol not found on module.",
            {"file_path": str(manifest_path), "entrypoint": entrypoint},
        )


def _validate_id_prefix(
    plugin_id: str,
    plugin_type: str,
    manifest_path: Path,
    issues: List[Dict[str, Any]],
) -> None:
    expected_prefix = PLUGIN_PREFIX_BY_TYPE.get(plugin_type)
    if expected_prefix is None:
        return
    if not plugin_id.startswith(expected_prefix):
        _add_issue(
            issues,
            ISSUE_PLUGIN_ID_TYPE_MISMATCH,
            "error",
            "plugin_id prefix does not match plugin_type.",
            {
                "file_path": str(manifest_path),
                "plugin_id": plugin_id,
                "plugin_type": plugin_type,
            },
        )


def _load_layout_ids(layouts_path: Path, issues: List[Dict[str, Any]]) -> Optional[set[str]]:
    data = _load_yaml(layouts_path, issues)
    if not isinstance(data, dict):
        _add_issue(
            issues,
            ISSUE_PLUGIN_CAPABILITIES_INVALID,
            "error",
            "Failed to load layout registry for plugin capability checks.",
            {"file_path": str(layouts_path)},
        )
        return None
    layouts = data.get("layouts")
    if not isinstance(layouts, dict):
        _add_issue(
            issues,
            ISSUE_PLUGIN_CAPABILITIES_INVALID,
            "error",
            "layouts.yaml is missing the layouts mapping.",
            {"file_path": str(layouts_path)},
        )
        return None
    return {
        layout_id
        for layout_id in layouts.keys()
        if isinstance(layout_id, str) and not layout_id.startswith("_")
    }


def _validate_capabilities(
    capabilities: Dict[str, Any],
    manifest_path: Path,
    layout_ids: Optional[set[str]],
    issues: List[Dict[str, Any]],
) -> None:
    max_channels = capabilities.get("max_channels")
    if (
        max_channels is not None
        and (
            not isinstance(max_channels, int)
            or isinstance(max_channels, bool)
            or max_channels < 1
        )
    ):
        _add_issue(
            issues,
            ISSUE_PLUGIN_CAPABILITIES_INVALID,
            "error",
            "capabilities.max_channels must be an integer >= 1.",
            {
                "file_path": str(manifest_path),
                "max_channels": max_channels,
            },
        )

    supported_layout_ids = capabilities.get("supported_layout_ids")
    if supported_layout_ids is not None:
        if not isinstance(supported_layout_ids, list):
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                "capabilities.supported_layout_ids must be a list of layout IDs.",
                {"file_path": str(manifest_path)},
            )
        else:
            for layout_id in supported_layout_ids:
                if not isinstance(layout_id, str):
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        "capabilities.supported_layout_ids must contain only strings.",
                        {"file_path": str(manifest_path), "layout_id": layout_id},
                    )
                    continue
                if layout_ids is not None and layout_id not in layout_ids:
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_LAYOUT_ID_UNKNOWN,
                        "error",
                        "capabilities.supported_layout_ids references an unknown layout ID.",
                        {"file_path": str(manifest_path), "layout_id": layout_id},
                    )

    supported_contexts = capabilities.get("supported_contexts")
    if supported_contexts is not None:
        allowed_contexts = {"suggest", "auto_apply", "render"}
        if not isinstance(supported_contexts, list):
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                "capabilities.supported_contexts must be a list of strings.",
                {"file_path": str(manifest_path)},
            )
        else:
            for context in supported_contexts:
                if not isinstance(context, str) or context not in allowed_contexts:
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        "capabilities.supported_contexts contains an invalid context.",
                        {"file_path": str(manifest_path), "context": context},
                    )

    notes = capabilities.get("notes")
    if notes is not None:
        if not isinstance(notes, list):
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                "capabilities.notes must be a list of strings.",
                {"file_path": str(manifest_path)},
            )
        else:
            for note in notes:
                if not isinstance(note, str):
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        "capabilities.notes must contain only strings.",
                        {"file_path": str(manifest_path)},
                    )


def validate_plugins(plugins_dir: Path, schema_path: Path) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    schema = _load_schema(schema_path, issues)
    if schema is None:
        return _result(plugins_dir, issues)

    manifest_paths = _collect_manifests(plugins_dir)
    plugin_id_index: Dict[str, List[str]] = {}
    layout_ids: Optional[set[str]] = None
    loaded_layout_ids = False
    layouts_path = Path(__file__).resolve().parents[1] / "ontology" / "layouts.yaml"

    for manifest_path in manifest_paths:
        data = _load_yaml(manifest_path, issues)
        if data is None:
            continue

        schema_ok = _validate_schema(schema, data, manifest_path, issues)
        if isinstance(data, dict):
            plugin_id = data.get("plugin_id")
            if isinstance(plugin_id, str):
                plugin_id_index.setdefault(plugin_id, []).append(str(manifest_path))

            plugin_type = data.get("plugin_type")
            if isinstance(plugin_id, str) and isinstance(plugin_type, str):
                _validate_id_prefix(plugin_id, plugin_type, manifest_path, issues)

            entrypoint = data.get("entrypoint")
            if isinstance(entrypoint, str):
                _validate_entrypoint(entrypoint, manifest_path, issues)
            elif schema_ok:
                _add_issue(
                    issues,
                    ISSUE_PLUGIN_ENTRYPOINT_INVALID,
                    "error",
                    "Manifest entrypoint is missing or invalid.",
                    {"file_path": str(manifest_path)},
                )

            capabilities = data.get("capabilities")
            if isinstance(capabilities, dict):
                if not loaded_layout_ids:
                    layout_ids = _load_layout_ids(layouts_path, issues)
                    loaded_layout_ids = True
                _validate_capabilities(
                    capabilities,
                    manifest_path,
                    layout_ids,
                    issues,
                )

    for plugin_id, paths in sorted(plugin_id_index.items()):
        if len(paths) > 1:
            _add_issue(
                issues,
                ISSUE_PLUGIN_ID_DUPLICATE,
                "error",
                "Duplicate plugin_id found across manifests.",
                {"plugin_id": plugin_id, "file_paths": paths},
            )

    return _result(plugins_dir, issues)


def _result(plugins_dir: Path, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    error_count = sum(1 for issue in issues if issue["severity_label"] == "error")
    warn_count = sum(1 for issue in issues if issue["severity_label"] == "warn")
    return {
        "registry_file": str(plugins_dir),
        "ok": error_count == 0,
        "issue_counts": {"error": error_count, "warn": warn_count},
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate plugin manifests.")
    parser.add_argument(
        "plugins_dir",
        nargs="?",
        default=None,
        help="Path to the plugins directory.",
    )
    parser.add_argument(
        "--plugins",
        dest="plugins",
        default=None,
        help=(
            "Optional explicit path to the plugins directory. "
            "If provided, this overrides the positional plugins_dir."
        ),
    )
    parser.add_argument(
        "--schema",
        dest="schema",
        default="schemas/plugin.schema.json",
        help="Path to the plugin manifest schema.",
    )
    args = parser.parse_args()

    plugins_value = args.plugins or args.plugins_dir or "plugins"
    plugins_dir = Path(plugins_value)
    schema_path = Path(args.schema)

    result = validate_plugins(plugins_dir, schema_path)
    print(json.dumps(result, indent=2))
    return 1 if result["issue_counts"]["error"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
