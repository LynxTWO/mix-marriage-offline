"""Full contract coverage for src/mmo/core/plugin_registry.py.

Tests:
- validate_manifest() schema enforcement
- validate_manifest() semantics enforcement per ontology/plugin_semantics.yaml
- Determinism: same inputs => same output (no randomness in validation)
- Invalid plugin rejection at load time (PluginRegistryError)
- load_and_validate_plugins() with real plugins dir passes
- Semantics YAML version is stable
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from mmo.core.plugin_registry import (
    ISSUE_SEMANTICS_BED_ONLY_OBJECT_CONFLICT,
    ISSUE_SEMANTICS_CHANNEL_MODE_INVALID,
    ISSUE_SEMANTICS_LATENCY_FIXED_MISSING_SAMPLES,
    ISSUE_SEMANTICS_LATENCY_TYPE_INVALID,
    ISSUE_SEMANTICS_LINK_GROUPS_INVALID,
    ISSUE_SEMANTICS_LINK_GROUPS_REQUIRES_LINKED_MODE,
    ISSUE_SEMANTICS_SEED_POLICY_INVALID,
    ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT,
    PluginRegistryError,
    SemanticsDoc,
    load_and_validate_plugins,
    load_semantics,
    validate_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path("schemas/plugin.schema.json")
_PLUGINS_DIR = Path("plugins")


def _base_manifest(**overrides: Any) -> Dict[str, Any]:
    """Return a minimal valid manifest dict."""
    base: Dict[str, Any] = {
        "plugin_id": "PLUGIN.DETECTOR.TEST_OK",
        "plugin_type": "detector",
        "name": "Test Plugin",
        "version": "0.1.0",
        "entrypoint": "mmo.plugins.detectors.clipping_headroom_detector:ClippingHeadroomDetector",
    }
    base.update(overrides)
    return base


def _renderer_manifest(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "plugin_id": "PLUGIN.RENDERER.TEST_OK",
        "plugin_type": "renderer",
        "name": "Test Renderer",
        "version": "0.1.0",
        "entrypoint": "mmo.plugins.renderers.safe_renderer:SafeRenderer",
    }
    base.update(overrides)
    return base


def _errors_contain(errors: list[str], fragment: str) -> bool:
    return any(fragment in e for e in errors)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation(unittest.TestCase):
    def test_minimal_valid_manifest_passes(self) -> None:
        errors = validate_manifest(_base_manifest(), schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_missing_required_field_rejected(self) -> None:
        manifest = _base_manifest()
        del manifest["version"]
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0, msg="Expected schema error for missing version")
        self.assertTrue(
            _errors_contain(errors, "[schema]"),
            msg=f"Expected schema error prefix; got: {errors}",
        )

    def test_invalid_plugin_id_pattern_rejected(self) -> None:
        manifest = _base_manifest(plugin_id="BAD.ID")
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(_errors_contain(errors, "[schema]"))

    def test_invalid_version_pattern_rejected(self) -> None:
        manifest = _base_manifest(version="not-semver")
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(_errors_contain(errors, "[schema]"))

    def test_additional_properties_rejected(self) -> None:
        manifest = _base_manifest()
        manifest["unknown_field"] = "oops"
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(_errors_contain(errors, "[schema]"))

    def test_invalid_entrypoint_format_rejected(self) -> None:
        manifest = _base_manifest(entrypoint="no-colon-here")
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(_errors_contain(errors, "[schema]"))

    def test_invalid_supported_context_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "supported_contexts": ["render", "hack_the_planet"],
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(_errors_contain(errors, "[schema]"))

    def test_valid_capabilities_object_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 32,
                "supported_contexts": ["render", "auto_apply"],
                "notes": ["Deterministic gain/trim rendering; no boosts."],
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_latency_zero_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "latency": {"type": "zero"},
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_latency_fixed_with_samples_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "latency": {"type": "fixed", "samples": 512},
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_channel_mode_per_channel_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "channel_mode": "per_channel",
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_channel_mode_linked_group_with_groups_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "channel_mode": "linked_group",
                "link_groups": ["front", "surrounds"],
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_bed_only_flag_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "bed_only": True,
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)

    def test_valid_seed_policy_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "deterministic_seed_policy": "seed_required",
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(errors, [], msg=errors)


# ---------------------------------------------------------------------------
# Semantics validation
# ---------------------------------------------------------------------------


class TestSemanticsValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.semantics = load_semantics()

    def test_invalid_channel_mode_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={"max_channels": 2, "channel_mode": "bogus_mode"}
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        # Schema also rejects this via enum; semantics check backs it up
        self.assertTrue(len(errors) > 0)
        # At least one error must reference the semantics issue ID or schema
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_CHANNEL_MODE_INVALID)
            or _errors_contain(errors, "[schema]"),
            msg=f"Expected channel_mode error; got: {errors}",
        )

    def test_invalid_link_group_value_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "channel_mode": "linked_group",
                "link_groups": ["front", "not_a_group"],
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_LINK_GROUPS_INVALID)
            or _errors_contain(errors, "[schema]"),
            msg=f"Expected link_groups error; got: {errors}",
        )

    def test_link_groups_without_linked_mode_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "channel_mode": "per_channel",
                "link_groups": ["front"],
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_LINK_GROUPS_REQUIRES_LINKED_MODE),
            msg=f"Expected link_groups mode mismatch error; got: {errors}",
        )

    def test_invalid_latency_type_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "latency": {"type": "magic"},
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_LATENCY_TYPE_INVALID)
            or _errors_contain(errors, "[schema]"),
            msg=f"Expected latency type error; got: {errors}",
        )

    def test_fixed_latency_missing_samples_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "latency": {"type": "fixed"},
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_LATENCY_FIXED_MISSING_SAMPLES),
            msg=f"Expected fixed latency missing samples error; got: {errors}",
        )

    def test_fixed_latency_negative_samples_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "latency": {"type": "fixed", "samples": -1},
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_LATENCY_FIXED_MISSING_SAMPLES)
            or _errors_contain(errors, "[schema]"),
            msg=f"Expected negative samples error; got: {errors}",
        )

    def test_invalid_seed_policy_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 2,
                "deterministic_seed_policy": "random_vibes",
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_SEED_POLICY_INVALID)
            or _errors_contain(errors, "[schema]"),
            msg=f"Expected seed policy error; got: {errors}",
        )

    def test_bed_only_conflicts_with_supports_objects(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "bed_only": True,
                "scene": {
                    "supports_objects": True,
                },
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_BED_ONLY_OBJECT_CONFLICT),
            msg=f"Expected bed_only/supports_objects conflict error; got: {errors}",
        )

    def test_requires_speaker_positions_without_layout_rejected(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "scene": {
                    "requires_speaker_positions": True,
                },
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(
            _errors_contain(errors, ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT),
            msg=f"Expected speaker_positions/layout error; got: {errors}",
        )

    def test_requires_speaker_positions_with_layout_ids_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "supported_layout_ids": ["LAYOUT.STEREO.2_0"],
                "scene": {
                    "requires_speaker_positions": True,
                },
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        speaker_pos_errors = [
            e for e in errors if ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT in e
        ]
        self.assertEqual(speaker_pos_errors, [], msg=errors)

    def test_requires_speaker_positions_with_target_ids_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "scene": {
                    "requires_speaker_positions": True,
                    "supported_target_ids": ["TARGET.STEREO.2_0"],
                },
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        speaker_pos_errors = [
            e for e in errors if ISSUE_SEMANTICS_SPEAKER_POSITIONS_NO_LAYOUT in e
        ]
        self.assertEqual(speaker_pos_errors, [], msg=errors)

    def test_bed_only_false_with_supports_objects_passes(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 8,
                "bed_only": False,
                "scene": {
                    "supports_objects": True,
                },
            }
        )
        errors = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=self.semantics)
        conflict_errors = [
            e for e in errors if ISSUE_SEMANTICS_BED_ONLY_OBJECT_CONFLICT in e
        ]
        self.assertEqual(conflict_errors, [], msg=errors)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    """validate_manifest() must return identical results on repeated calls."""

    def test_valid_manifest_deterministic(self) -> None:
        manifest = _renderer_manifest(
            capabilities={
                "max_channels": 32,
                "channel_mode": "per_channel",
                "latency": {"type": "fixed", "samples": 256},
                "deterministic_seed_policy": "none",
                "supported_contexts": ["render"],
            }
        )
        semantics = load_semantics()
        results = [
            validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=semantics)
            for _ in range(3)
        ]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_invalid_manifest_deterministic(self) -> None:
        manifest = _renderer_manifest(
            capabilities={"channel_mode": "bad_mode", "latency": {"type": "invalid"}}
        )
        semantics = load_semantics()
        results = [
            validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=semantics)
            for _ in range(3)
        ]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_error_list_is_sorted_stable(self) -> None:
        """Error list ordering must be deterministic (no set-based iteration)."""
        manifest = _renderer_manifest(
            capabilities={
                "channel_mode": "bad",
                "link_groups": ["nope"],
                "latency": {"type": "bad"},
                "deterministic_seed_policy": "also_bad",
                "bed_only": True,
                "scene": {"supports_objects": True},
            }
        )
        semantics = load_semantics()
        r1 = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=semantics)
        r2 = validate_manifest(manifest, schema_path=_SCHEMA_PATH, semantics=semantics)
        self.assertEqual(r1, r2)
        self.assertTrue(len(r1) > 0)


# ---------------------------------------------------------------------------
# load_and_validate_plugins with real plugins dir
# ---------------------------------------------------------------------------


class TestLoadAndValidatePlugins(unittest.TestCase):
    def test_real_plugins_dir_passes(self) -> None:
        """All bundled plugin manifests must pass schema + semantics validation."""
        plugins = load_and_validate_plugins(
            _PLUGINS_DIR, schema_path=_SCHEMA_PATH
        )
        self.assertTrue(len(plugins) > 0, msg="Expected at least one plugin to load")

    def test_invalid_manifest_raises_registry_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins_dir = Path(tmp)
            bad_manifest_path = plugins_dir / "bad.plugin.yaml"
            bad_manifest_path.write_text(
                "\n".join([
                    'plugin_id: "BAD.ID.NO_PREFIX"',
                    'plugin_type: "detector"',
                    'name: "Bad Plugin"',
                    'version: "0.1.0"',
                    'entrypoint: "mmo.plugins.detectors.clipping_headroom_detector:ClippingHeadroomDetector"',
                    "",
                ]),
                encoding="utf-8",
            )
            with self.assertRaises(PluginRegistryError) as ctx:
                load_and_validate_plugins(plugins_dir, schema_path=_SCHEMA_PATH)
            self.assertIn("validation failed", str(ctx.exception).lower())

    def test_registry_error_contains_path_and_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins_dir = Path(tmp)
            bad_path = plugins_dir / "invalid.plugin.yaml"
            bad_path.write_text(
                "\n".join([
                    'plugin_id: "BAD"',
                    'plugin_type: "detector"',
                    "",
                ]),
                encoding="utf-8",
            )
            with self.assertRaises(PluginRegistryError) as ctx:
                load_and_validate_plugins(plugins_dir, schema_path=_SCHEMA_PATH)
            exc = ctx.exception
            self.assertIsInstance(exc.errors_by_path, dict)
            self.assertTrue(len(exc.errors_by_path) > 0)
            # Each value must be a non-empty list of strings
            for path_key, errs in exc.errors_by_path.items():
                self.assertIsInstance(path_key, str)
                self.assertIsInstance(errs, list)
                self.assertTrue(len(errs) > 0)


# ---------------------------------------------------------------------------
# SemanticsDoc contract
# ---------------------------------------------------------------------------


class TestSemanticsDoc(unittest.TestCase):
    def test_load_semantics_succeeds(self) -> None:
        s = load_semantics()
        self.assertIsInstance(s, SemanticsDoc)

    def test_semantics_version_is_string(self) -> None:
        s = load_semantics()
        self.assertIsInstance(s.version, str)
        self.assertTrue(len(s.version) > 0)

    def test_valid_channel_modes_complete(self) -> None:
        s = load_semantics()
        self.assertIn("per_channel", s.valid_channel_modes)
        self.assertIn("linked_group", s.valid_channel_modes)
        self.assertIn("true_multichannel", s.valid_channel_modes)

    def test_valid_link_groups_complete(self) -> None:
        s = load_semantics()
        for grp in ("front", "surrounds", "heights", "all", "custom"):
            self.assertIn(grp, s.valid_link_groups)

    def test_valid_latency_types_complete(self) -> None:
        s = load_semantics()
        for lt in ("zero", "fixed", "dynamic"):
            self.assertIn(lt, s.valid_latency_types)

    def test_valid_seed_policies_complete(self) -> None:
        s = load_semantics()
        for sp in ("none", "seed_required", "seed_optional"):
            self.assertIn(sp, s.valid_seed_policies)

    def test_semantics_sets_are_frozenset(self) -> None:
        s = load_semantics()
        self.assertIsInstance(s.valid_channel_modes, frozenset)
        self.assertIsInstance(s.valid_link_groups, frozenset)
        self.assertIsInstance(s.valid_latency_types, frozenset)
        self.assertIsInstance(s.valid_seed_policies, frozenset)


# ---------------------------------------------------------------------------
# PluginRegistryError contract
# ---------------------------------------------------------------------------


class TestPluginRegistryError(unittest.TestCase):
    def test_str_contains_plugin_count(self) -> None:
        exc = PluginRegistryError({"a.yaml": ["err1"], "b.yaml": ["err2"]})
        self.assertIn("2 plugin", str(exc))

    def test_str_contains_paths(self) -> None:
        exc = PluginRegistryError({"my/plugin.yaml": ["bad field"]})
        self.assertIn("my/plugin.yaml", str(exc))
        self.assertIn("bad field", str(exc))

    def test_errors_by_path_is_accessible(self) -> None:
        exc = PluginRegistryError({"p.yaml": ["e1", "e2"]})
        self.assertEqual(exc.errors_by_path["p.yaml"], ["e1", "e2"])


if __name__ == "__main__":
    unittest.main()
