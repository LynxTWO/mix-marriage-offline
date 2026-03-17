from __future__ import annotations

import unittest
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from mmo.core.pipeline import run_renderers
from mmo.core.plugin_loader import load_plugin_root_entries
from mmo.core.plugin_registry import (
    ISSUE_SEMANTICS_LAYOUT_SPECIFIC_NO_LAYOUT,
    validate_manifest,
)
from tools.validate_plugins import validate_plugins

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STARTER_ROOT = _REPO_ROOT / "examples" / "plugin_authoring" / "starter_pack"
_TEMPLATE_PATH = _REPO_ROOT / "examples" / "plugin_authoring" / "starter_manifest.template.yaml"
_INVALID_MANIFEST_PATH = (
    _REPO_ROOT
    / "examples"
    / "plugin_authoring"
    / "invalid"
    / "layout_specific_without_layout.plugin.yaml"
)
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "plugin.schema.json"

_PER_CHANNEL_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.PER_CHANNEL_GAIN"
_LINKED_GROUP_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.LINKED_GROUP_BED"
_TRUE_MULTICHANNEL_PLUGIN_ID = "PLUGIN.RENDERER.STARTER.TRUE_MULTICHANNEL_CHECKSUM"


@lru_cache(maxsize=1)
def _starter_entries() -> dict[str, Any]:
    return {
        entry.plugin_id: entry
        for entry in load_plugin_root_entries(_STARTER_ROOT)
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected mapping payload in {path}")
    return payload


class TestPluginAuthoringExamples(unittest.TestCase):
    def test_starter_pack_loads_and_template_manifest_is_schema_valid(self) -> None:
        entries = _starter_entries()

        self.assertEqual(
            sorted(entries),
            [
                _LINKED_GROUP_PLUGIN_ID,
                _PER_CHANNEL_PLUGIN_ID,
                _TRUE_MULTICHANNEL_PLUGIN_ID,
            ],
        )
        self.assertTrue(callable(getattr(entries[_PER_CHANNEL_PLUGIN_ID].instance, "render", None)))
        self.assertTrue(
            callable(getattr(entries[_LINKED_GROUP_PLUGIN_ID].instance, "process_linked_group", None))
        )
        self.assertTrue(
            callable(
                getattr(
                    entries[_TRUE_MULTICHANNEL_PLUGIN_ID].instance,
                    "process_true_multichannel",
                    None,
                )
            )
        )

        template_manifest = _load_yaml(_TEMPLATE_PATH)
        template_errors = validate_manifest(template_manifest, schema_path=_SCHEMA_PATH)
        self.assertEqual(template_errors, [], msg=template_errors)

    def test_validate_plugins_accepts_starter_pack(self) -> None:
        result = validate_plugins(_STARTER_ROOT, _SCHEMA_PATH)

        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["issue_counts"], {"error": 0, "warn": 0})
        self.assertEqual(result["issues"], [])

    def test_invalid_manifest_example_reports_layout_specific_mistake(self) -> None:
        invalid_manifest = _load_yaml(_INVALID_MANIFEST_PATH)

        errors = validate_manifest(invalid_manifest, schema_path=_SCHEMA_PATH)

        self.assertTrue(
            any(ISSUE_SEMANTICS_LAYOUT_SPECIFIC_NO_LAYOUT in error for error in errors),
            msg=errors,
        )

    def test_bed_only_example_receipt_is_explainable(self) -> None:
        plugin = _starter_entries()[_LINKED_GROUP_PLUGIN_ID]
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST.STARTER.BED_ONLY",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {
                "scene_payload": {
                    "objects": [{"object_id": "OBJECT.VOX", "stem_id": "vox_object"}],
                    "beds": [{"bed_id": "BED.MUSIC", "stem_ids": ["music_bed"]}],
                }
            },
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.RENDER.BED",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "music_bed"},
                },
                {
                    "recommendation_id": "REC.RENDER.OBJECT",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "vox_object"},
                },
            ],
        }

        manifests = run_renderers(report, [plugin], output_dir=None)

        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest.get("renderer_id"), _LINKED_GROUP_PLUGIN_ID)
        self.assertEqual(manifest.get("received_recommendation_ids"), ["REC.RENDER.BED"])
        self.assertIn(
            "plugin_safety_restriction:bed_only_kept=1,bed_only_skipped=1",
            str(manifest.get("notes")),
        )
        skipped = manifest.get("skipped")
        self.assertIsInstance(skipped, list)
        if not isinstance(skipped, list):
            return
        restricted = next(
            (
                item
                for item in skipped
                if isinstance(item, dict)
                and item.get("recommendation_id") == "REC.RENDER.OBJECT"
                and item.get("reason") == "plugin_scene_scope_restricted"
            ),
            None,
        )
        self.assertIsInstance(restricted, dict)
        if not isinstance(restricted, dict):
            return
        details = restricted.get("details")
        self.assertIsInstance(details, dict)
        if isinstance(details, dict):
            self.assertEqual(details.get("scene_scope"), "bed_only")
            self.assertEqual(details.get("stem_id"), "vox_object")
            self.assertEqual(details.get("plugin_id"), _LINKED_GROUP_PLUGIN_ID)

    def test_layout_specific_example_bypass_is_explainable(self) -> None:
        plugin = _starter_entries()[_TRUE_MULTICHANNEL_PLUGIN_ID]
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST.STARTER.LAYOUT",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"target_layout_id": "LAYOUT.9_1_6"},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": "REC.RENDER.LAYOUT",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "eligible_render": True,
                    "target": {"scope": "stem", "stem_id": "music_bed"},
                }
            ],
        }

        manifests = run_renderers(report, [plugin], output_dir=None)

        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest.get("renderer_id"), _TRUE_MULTICHANNEL_PLUGIN_ID)
        self.assertEqual(manifest.get("outputs"), [])
        self.assertIn(
            "plugin_safety_bypass:layout_unsupported=LAYOUT.9_1_6",
            str(manifest.get("notes")),
        )
        skipped = manifest.get("skipped")
        self.assertIsInstance(skipped, list)
        if not isinstance(skipped, list):
            return
        skipped_row = next(
            (
                item
                for item in skipped
                if isinstance(item, dict)
                and item.get("recommendation_id") == "REC.RENDER.LAYOUT"
                and item.get("reason") == "plugin_layout_unsupported"
            ),
            None,
        )
        self.assertIsInstance(skipped_row, dict)
        if not isinstance(skipped_row, dict):
            return
        details = skipped_row.get("details")
        self.assertIsInstance(details, dict)
        if isinstance(details, dict):
            self.assertEqual(details.get("target_layout_id"), "LAYOUT.9_1_6")
            self.assertEqual(
                details.get("supported_layout_ids"),
                ["LAYOUT.5_1", "LAYOUT.7_1_4"],
            )


if __name__ == "__main__":
    unittest.main()
