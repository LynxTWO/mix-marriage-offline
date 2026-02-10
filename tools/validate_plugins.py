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
ISSUE_PLUGIN_TARGET_ID_UNKNOWN = "ISSUE.VALIDATION.PLUGIN_TARGET_ID_UNKNOWN"

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


def _load_target_layouts(
    render_targets_path: Path,
    issues: List[Dict[str, Any]],
) -> Optional[Dict[str, str | None]]:
    data = _load_yaml(render_targets_path, issues)
    if not isinstance(data, dict):
        _add_issue(
            issues,
            ISSUE_PLUGIN_CAPABILITIES_INVALID,
            "error",
            "Failed to load render target registry for plugin capability checks.",
            {"file_path": str(render_targets_path)},
        )
        return None
    targets = data.get("targets")
    if not isinstance(targets, list):
        _add_issue(
            issues,
            ISSUE_PLUGIN_CAPABILITIES_INVALID,
            "error",
            "render_targets.yaml is missing the targets list.",
            {"file_path": str(render_targets_path)},
        )
        return None

    target_layouts: Dict[str, str | None] = {}
    for item in targets:
        if not isinstance(item, dict):
            continue
        target_id = item.get("target_id")
        if not isinstance(target_id, str) or not target_id or target_id.startswith("_"):
            continue
        layout_id = item.get("layout_id")
        if isinstance(layout_id, str) and layout_id:
            target_layouts[target_id] = layout_id
        else:
            target_layouts[target_id] = None
    return target_layouts


def _validate_capabilities(
    capabilities: Dict[str, Any],
    manifest_path: Path,
    layout_ids: Optional[set[str]],
    target_layouts: Optional[Dict[str, str | None]],
    issues: List[Dict[str, Any]],
) -> None:
    allowed_capability_fields = {
        "max_channels",
        "supported_layout_ids",
        "supported_contexts",
        "scene",
        "notes",
    }
    for field_name in sorted(capabilities.keys()):
        if field_name not in allowed_capability_fields:
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                f"capabilities contains unsupported field: {field_name}.",
                {"file_path": str(manifest_path), "field_name": field_name},
            )

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
    layout_values: list[str] = []
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
                layout_values.append(layout_id)
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

    scene = capabilities.get("scene")
    target_ids: list[str] = []
    requires_speaker_positions = False
    if scene is not None:
        if not isinstance(scene, dict):
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                "capabilities.scene must be an object.",
                {"file_path": str(manifest_path)},
            )
        else:
            allowed_scene_fields = {
                "supports_objects",
                "supports_beds",
                "supports_locks",
                "requires_speaker_positions",
                "supported_target_ids",
            }
            for field_name in sorted(scene.keys()):
                if field_name not in allowed_scene_fields:
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        f"capabilities.scene contains unsupported field: {field_name}.",
                        {"file_path": str(manifest_path), "field_name": field_name},
                    )

            for bool_field_name in (
                "supports_objects",
                "supports_beds",
                "supports_locks",
                "requires_speaker_positions",
            ):
                bool_value = scene.get(bool_field_name)
                if bool_value is not None and not isinstance(bool_value, bool):
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        f"capabilities.scene.{bool_field_name} must be a boolean.",
                        {
                            "file_path": str(manifest_path),
                            "field_name": bool_field_name,
                            "value": bool_value,
                        },
                    )

            requires_speaker_positions = scene.get("requires_speaker_positions") is True
            supported_target_ids = scene.get("supported_target_ids")
            if supported_target_ids is not None:
                if not isinstance(supported_target_ids, list):
                    _add_issue(
                        issues,
                        ISSUE_PLUGIN_CAPABILITIES_INVALID,
                        "error",
                        "capabilities.scene.supported_target_ids must be a list of target IDs.",
                        {"file_path": str(manifest_path)},
                    )
                else:
                    for target_id in supported_target_ids:
                        if not isinstance(target_id, str):
                            _add_issue(
                                issues,
                                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                                "error",
                                (
                                    "capabilities.scene.supported_target_ids "
                                    "must contain only strings."
                                ),
                                {"file_path": str(manifest_path), "target_id": target_id},
                            )
                            continue
                        target_ids.append(target_id)
                        if target_layouts is not None and target_id not in target_layouts:
                            _add_issue(
                                issues,
                                ISSUE_PLUGIN_TARGET_ID_UNKNOWN,
                                "error",
                                (
                                    "capabilities.scene.supported_target_ids "
                                    "references an unknown target ID."
                                ),
                                {
                                    "file_path": str(manifest_path),
                                    "target_id": target_id,
                                },
                            )

    if requires_speaker_positions:
        has_layout_support = bool(layout_values)
        has_target_layout_support = False
        if target_ids:
            if target_layouts is None:
                has_target_layout_support = True
            else:
                for target_id in target_ids:
                    target_layout = target_layouts.get(target_id)
                    if isinstance(target_layout, str) and target_layout:
                        has_target_layout_support = True
                        break
        if not has_layout_support and not has_target_layout_support:
            _add_issue(
                issues,
                ISSUE_PLUGIN_CAPABILITIES_INVALID,
                "error",
                (
                    "capabilities.scene.requires_speaker_positions=true requires either "
                    "capabilities.supported_layout_ids or layout-backed "
                    "capabilities.scene.supported_target_ids."
                ),
                {"file_path": str(manifest_path)},
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
    target_layouts: Optional[Dict[str, str | None]] = None
    loaded_layout_ids = False
    loaded_target_layouts = False
    layouts_path = Path(__file__).resolve().parents[1] / "ontology" / "layouts.yaml"
    render_targets_path = (
        Path(__file__).resolve().parents[1] / "ontology" / "render_targets.yaml"
    )

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
                if not loaded_target_layouts:
                    target_layouts = _load_target_layouts(render_targets_path, issues)
                    loaded_target_layouts = True
                _validate_capabilities(
                    capabilities,
                    manifest_path,
                    layout_ids,
                    target_layouts,
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
