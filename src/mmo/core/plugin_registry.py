"""Plugin manifest validation and registry loading with full semantics enforcement.

Validates manifests against:
  1. schemas/plugin.schema.json (structural/type correctness)
  2. ontology/plugin_semantics.yaml (semantic constraints from DoD 4.4.4 / 4.9.3)

Public API
----------
validate_manifest(manifest, schema_path, semantics) -> list[str]
    Return a list of error strings (empty == valid).

load_and_validate_plugins(plugins_dir, schema_path) -> list[PluginEntry]
    Load all plugins from plugins_dir, validate each, raise PluginRegistryError
    on any violation.

PluginRegistryError
    Raised when one or more plugins fail validation at registry load time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None

from mmo.core.plugin_behavior import validate_behavior_contract_definition
from mmo.resources import ontology_dir, schemas_dir

# ---------------------------------------------------------------------------
# Issue ID constants (mirror tools/validate_plugins.py naming convention)
# ---------------------------------------------------------------------------

ISSUE_SEMANTICS_CHANNEL_MODE_INVALID = "ISSUE.SEMANTICS.CHANNEL_MODE_INVALID"
ISSUE_SEMANTICS_LINK_GROUPS_INVALID = "ISSUE.SEMANTICS.LINK_GROUPS_INVALID"
ISSUE_SEMANTICS_LINK_GROUPS_REQUIRES_LINKED_MODE = (
    "ISSUE.SEMANTICS.LINK_GROUPS_REQUIRES_LINKED_MODE"
)
ISSUE_SEMANTICS_LATENCY_TYPE_INVALID = "ISSUE.SEMANTICS.LATENCY_TYPE_INVALID"
ISSUE_SEMANTICS_LATENCY_FIXED_MISSING_SAMPLES = (
    "ISSUE.SEMANTICS.LATENCY_FIXED_MISSING_SAMPLES"
)
ISSUE_SEMANTICS_SEED_POLICY_INVALID = "ISSUE.SEMANTICS.SEED_POLICY_INVALID"
ISSUE_SEMANTICS_PURITY_RANDOMNESS_CONFLICT = (
    "ISSUE.SEMANTICS.PURITY_RANDOMNESS_CONFLICT"
)
ISSUE_SEMANTICS_BED_ONLY_OBJECT_CONFLICT = "ISSUE.SEMANTICS.BED_ONLY_OBJECT_CONFLICT"
ISSUE_SEMANTICS_SCENE_SCOPE_INVALID = "ISSUE.SEMANTICS.SCENE_SCOPE_INVALID"
ISSUE_SEMANTICS_SCENE_SCOPE_OBJECT_CONFLICT = (
    "ISSUE.SEMANTICS.SCENE_SCOPE_OBJECT_CONFLICT"
)
ISSUE_SEMANTICS_LAYOUT_SAFETY_INVALID = "ISSUE.SEMANTICS.LAYOUT_SAFETY_INVALID"
ISSUE_SEMANTICS_LAYOUT_SPECIFIC_NO_LAYOUT = (
    "ISSUE.SEMANTICS.LAYOUT_SPECIFIC_NO_LAYOUT"
)
ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT = (
    "ISSUE.SEMANTICS.SPEAKER_POSITIONS_NO_LAYOUT"
)

# Canonical allowed values (kept in sync with ontology/plugin_semantics.yaml)
_VALID_CHANNEL_MODES = frozenset({"per_channel", "linked_group", "true_multichannel"})
_VALID_LINK_GROUPS = frozenset({"front", "surrounds", "heights", "all", "custom"})
_VALID_LATENCY_TYPES = frozenset({"zero", "fixed", "dynamic"})
_VALID_SEED_POLICIES = frozenset({"none", "seed_required", "seed_optional"})
_VALID_SCENE_SCOPES = frozenset({"bed_only", "object_capable"})
_VALID_LAYOUT_SAFETY = frozenset({"layout_agnostic", "layout_specific"})


# ---------------------------------------------------------------------------
# Semantics dataclass
# ---------------------------------------------------------------------------


class SemanticsDoc:
    """Loaded canonical semantics from ontology/plugin_semantics.yaml."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    @property
    def version(self) -> str:
        v = self._data.get("version")
        return str(v) if v is not None else "unknown"

    @property
    def valid_channel_modes(self) -> frozenset[str]:
        return _VALID_CHANNEL_MODES

    @property
    def valid_link_groups(self) -> frozenset[str]:
        return _VALID_LINK_GROUPS

    @property
    def valid_latency_types(self) -> frozenset[str]:
        return _VALID_LATENCY_TYPES

    @property
    def valid_seed_policies(self) -> frozenset[str]:
        return _VALID_SEED_POLICIES

    @property
    def valid_scene_scopes(self) -> frozenset[str]:
        return _VALID_SCENE_SCOPES

    @property
    def valid_layout_safety(self) -> frozenset[str]:
        return _VALID_LAYOUT_SAFETY


def load_semantics(semantics_path: Optional[Path] = None) -> SemanticsDoc:
    """Load plugin_semantics.yaml. Uses importlib.resources chain if path is None."""
    if semantics_path is None:
        semantics_path = ontology_dir() / "plugin_semantics.yaml"

    if _yaml is None:
        raise RuntimeError(
            "PyYAML is required to load plugin semantics. "
            "Install it with: pip install pyyaml"
        )
    with semantics_path.open("r", encoding="utf-8") as handle:
        data = _yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"plugin_semantics.yaml must be a mapping: {semantics_path}"
        )
    return SemanticsDoc(data)


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def _load_schema(schema_path: Path) -> Dict[str, Any]:
    with schema_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Schema must be a JSON object: {schema_path}")
    return data


# ---------------------------------------------------------------------------
# validate_manifest: schema + semantics checks
# ---------------------------------------------------------------------------


def validate_manifest(
    manifest: Dict[str, Any],
    schema_path: Optional[Path] = None,
    semantics: Optional[SemanticsDoc] = None,
) -> List[str]:
    """Validate a plugin manifest dict. Returns a list of error strings.

    Args:
        manifest: Parsed manifest dict (from YAML or JSON).
        schema_path: Path to plugin.schema.json. Defaults to the packaged schema.
        semantics: Pre-loaded SemanticsDoc. Loads from ontology if None.

    Returns:
        List of human-readable error strings. Empty list means valid.
    """
    errors: List[str] = []

    # 1. JSON schema validation
    if schema_path is None:
        schema_path = schemas_dir() / "plugin.schema.json"

    if jsonschema is not None:
        schema = _load_schema(schema_path)
        validator = jsonschema.Draft202012Validator(schema)
        schema_errors = sorted(
            validator.iter_errors(manifest), key=lambda e: list(e.path)
        )
        for err in schema_errors:
            path = ".".join(str(p) for p in err.path) or "$"
            errors.append(f"[schema] {path}: {err.message}")

    # 2. Semantics validation (ontology/plugin_semantics.yaml)
    if semantics is None:
        try:
            semantics = load_semantics()
        except Exception as exc:
            errors.append(f"[semantics] Could not load plugin_semantics.yaml: {exc}")
            return errors

    capabilities = manifest.get("capabilities")
    if isinstance(capabilities, dict):
        _validate_semantics(manifest, capabilities, semantics, errors)

    for message in validate_behavior_contract_definition(
        plugin_type=str(manifest.get("plugin_type", "")),
        capabilities=capabilities,
        behavior_contract=manifest.get("behavior_contract"),
    ):
        errors.append(f"[semantics] {message}")

    return errors


def _validate_semantics(
    manifest: Dict[str, Any],
    capabilities: Dict[str, Any],
    semantics: SemanticsDoc,
    errors: List[str],
) -> None:
    """Append semantic constraint violations to errors."""

    # --- channel_mode ---
    channel_mode = capabilities.get("channel_mode")
    if channel_mode is not None:
        if channel_mode not in semantics.valid_channel_modes:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_CHANNEL_MODE_INVALID}: "
                f"capabilities.channel_mode {channel_mode!r} is not a valid value. "
                f"Allowed: {sorted(semantics.valid_channel_modes)}"
            )

    # --- supported_link_groups ---
    supported_link_groups = capabilities.get("supported_link_groups")
    if supported_link_groups is not None:
        if isinstance(supported_link_groups, list):
            for grp in supported_link_groups:
                if not isinstance(grp, str) or grp not in semantics.valid_link_groups:
                    errors.append(
                        f"[semantics] {ISSUE_SEMANTICS_LINK_GROUPS_INVALID}: "
                        "capabilities.supported_link_groups contains invalid group "
                        f"{grp!r}. "
                        f"Allowed: {sorted(semantics.valid_link_groups)}"
                    )
            # supported_link_groups is meaningful for linked_group and
            # true_multichannel host planning.
            if channel_mode is not None and channel_mode not in {
                "linked_group",
                "true_multichannel",
            }:
                errors.append(
                    f"[semantics] {ISSUE_SEMANTICS_LINK_GROUPS_REQUIRES_LINKED_MODE}: "
                    "capabilities.supported_link_groups is declared but channel_mode "
                    "is neither 'linked_group' nor 'true_multichannel' "
                    f"(got {channel_mode!r})."
                )

    supported_group_sizes = capabilities.get("supported_group_sizes")
    if (
        channel_mode == "per_channel"
        and isinstance(supported_group_sizes, list)
        and supported_group_sizes
        and 1 not in supported_group_sizes
    ):
        errors.append(
            "[semantics] capabilities.supported_group_sizes must include 1 when "
            "channel_mode='per_channel'."
        )

    # --- latency ---
    latency = capabilities.get("latency")
    if latency is not None and isinstance(latency, dict):
        latency_type = latency.get("type")
        if latency_type not in semantics.valid_latency_types:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_LATENCY_TYPE_INVALID}: "
                f"capabilities.latency.type {latency_type!r} is not valid. "
                f"Allowed: {sorted(semantics.valid_latency_types)}"
            )
        if latency_type == "fixed":
            samples = latency.get("samples")
            if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
                errors.append(
                    f"[semantics] {ISSUE_SEMANTICS_LATENCY_FIXED_MISSING_SAMPLES}: "
                    "capabilities.latency.samples must be a non-negative integer "
                    "when latency.type is 'fixed'."
                )

    # --- deterministic_seed_policy ---
    seed_policy = capabilities.get("deterministic_seed_policy")
    if seed_policy is not None:
        if seed_policy not in semantics.valid_seed_policies:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SEED_POLICY_INVALID}: "
                f"capabilities.deterministic_seed_policy {seed_policy!r} is not valid. "
                f"Allowed: {sorted(semantics.valid_seed_policies)}"
            )

    purity = capabilities.get("purity")
    if isinstance(purity, dict):
        randomness = purity.get("randomness")
        if seed_policy == "none" and randomness == "process_context_seed":
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_PURITY_RANDOMNESS_CONFLICT}: "
                "capabilities.purity.randomness='process_context_seed' conflicts with "
                "capabilities.deterministic_seed_policy='none'."
            )
        if seed_policy in {"seed_required", "seed_optional"} and randomness == "forbidden":
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_PURITY_RANDOMNESS_CONFLICT}: "
                "capabilities.purity.randomness='forbidden' conflicts with "
                "a seed-enabled deterministic_seed_policy."
            )

    scene = capabilities.get("scene")
    scene_scope = capabilities.get("scene_scope")
    if scene_scope not in semantics.valid_scene_scopes:
        errors.append(
            f"[semantics] {ISSUE_SEMANTICS_SCENE_SCOPE_INVALID}: "
            "capabilities.scene_scope must explicitly declare "
            f"one of {sorted(semantics.valid_scene_scopes)}."
        )
    elif scene_scope == "bed_only":
        if capabilities.get("bed_only") is False:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SCENE_SCOPE_OBJECT_CONFLICT}: "
                "capabilities.scene_scope='bed_only' conflicts with "
                "capabilities.bed_only=false."
            )
        if isinstance(scene, dict) and scene.get("supports_objects") is True:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SCENE_SCOPE_OBJECT_CONFLICT}: "
                "capabilities.scene_scope='bed_only' conflicts with "
                "capabilities.scene.supports_objects=true."
            )
    elif scene_scope == "object_capable":
        if capabilities.get("bed_only") is True:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SCENE_SCOPE_OBJECT_CONFLICT}: "
                "capabilities.scene_scope='object_capable' conflicts with "
                "capabilities.bed_only=true."
            )
        if isinstance(scene, dict) and scene.get("supports_objects") is False:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SCENE_SCOPE_OBJECT_CONFLICT}: "
                "capabilities.scene_scope='object_capable' conflicts with "
                "capabilities.scene.supports_objects=false."
            )

    layout_safety = capabilities.get("layout_safety")
    if layout_safety not in semantics.valid_layout_safety:
        errors.append(
            f"[semantics] {ISSUE_SEMANTICS_LAYOUT_SAFETY_INVALID}: "
            "capabilities.layout_safety must explicitly declare "
            f"one of {sorted(semantics.valid_layout_safety)}."
        )
    elif layout_safety == "layout_specific":
        has_layout_ids = bool(capabilities.get("supported_layout_ids"))
        target_ids = scene.get("supported_target_ids") if isinstance(scene, dict) else None
        has_target_ids = isinstance(target_ids, list) and len(target_ids) > 0
        if not has_layout_ids and not has_target_ids:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_LAYOUT_SPECIFIC_NO_LAYOUT}: "
                "capabilities.layout_safety='layout_specific' requires either "
                "capabilities.supported_layout_ids or "
                "capabilities.scene.supported_target_ids to be non-empty."
            )

    # --- bed_only conflicts ---
    bed_only = capabilities.get("bed_only")
    if bed_only is True:
        if isinstance(scene, dict) and scene.get("supports_objects") is True:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_BED_ONLY_OBJECT_CONFLICT}: "
                "capabilities.bed_only=true conflicts with "
                "capabilities.scene.supports_objects=true."
            )

    # --- requires_speaker_positions layout cross-check ---
    scene = capabilities.get("scene")
    if isinstance(scene, dict) and scene.get("requires_speaker_positions") is True:
        has_layout_ids = bool(capabilities.get("supported_layout_ids"))
        target_ids = scene.get("supported_target_ids")
        has_target_ids = isinstance(target_ids, list) and len(target_ids) > 0
        if not has_layout_ids and not has_target_ids:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT}: "
                "capabilities.scene.requires_speaker_positions=true requires either "
                "capabilities.supported_layout_ids or "
                "capabilities.scene.supported_target_ids to be non-empty."
            )

    requires_speaker_positions = capabilities.get("requires_speaker_positions")
    if requires_speaker_positions is True:
        has_layout_ids = bool(capabilities.get("supported_layout_ids"))
        target_ids = scene.get("supported_target_ids") if isinstance(scene, dict) else None
        has_target_ids = isinstance(target_ids, list) and len(target_ids) > 0
        if not has_layout_ids and not has_target_ids:
            errors.append(
                f"[semantics] {ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT}: "
                "capabilities.requires_speaker_positions=true requires either "
                "capabilities.supported_layout_ids or "
                "capabilities.scene.supported_target_ids to be non-empty."
            )


# ---------------------------------------------------------------------------
# PluginRegistryError
# ---------------------------------------------------------------------------


class PluginRegistryError(Exception):
    """Raised when plugins fail validation at registry load time."""

    def __init__(self, errors_by_path: Dict[str, List[str]]) -> None:
        self.errors_by_path = errors_by_path
        lines = [f"Plugin registry validation failed ({len(errors_by_path)} plugin(s)):"]
        for path, errs in sorted(errors_by_path.items()):
            lines.append(f"  {path}:")
            for err in errs:
                lines.append(f"    - {err}")
        super().__init__("\n".join(lines))


# ---------------------------------------------------------------------------
# load_and_validate_plugins
# ---------------------------------------------------------------------------


def load_and_validate_plugins(
    plugins_dir: Path,
    schema_path: Optional[Path] = None,
    semantics: Optional[SemanticsDoc] = None,
) -> List[Any]:
    """Load plugins from plugins_dir and validate each manifest.

    Args:
        plugins_dir: Directory to scan for *.plugin.yaml manifests.
        schema_path: Override path to plugin.schema.json.
        semantics: Pre-loaded SemanticsDoc (loaded once and reused).

    Returns:
        List of PluginEntry objects (from mmo.core.pipeline.load_plugins).

    Raises:
        PluginRegistryError: If any manifest fails schema or semantics validation.
    """
    from mmo.core.pipeline import PluginEntry, _collect_manifests, _load_yaml  # noqa: WPS433

    if schema_path is None:
        schema_path = schemas_dir() / "plugin.schema.json"

    if semantics is None:
        semantics = load_semantics()

    manifest_paths = _collect_manifests(plugins_dir)
    errors_by_path: Dict[str, List[str]] = {}

    for manifest_path in manifest_paths:
        try:
            manifest = _load_yaml(manifest_path)
        except Exception as exc:
            errors_by_path[str(manifest_path)] = [f"[parse] {exc}"]
            continue

        errs = validate_manifest(manifest, schema_path=schema_path, semantics=semantics)
        if errs:
            errors_by_path[str(manifest_path)] = errs

    if errors_by_path:
        raise PluginRegistryError(errors_by_path)

    # Delegate actual loading to the single-root pipeline loader.
    from mmo.core.pipeline import _load_plugins_from_dir  # noqa: WPS433

    return _load_plugins_from_dir(plugins_dir)
