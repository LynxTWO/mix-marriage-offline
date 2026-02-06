import json
import re
import unittest
from pathlib import Path

import jsonschema

from mmo.core.presets import (
    get_preset_help_id,
    list_presets,
    load_preset_index,
    load_preset_run_config,
)


class TestPresets(unittest.TestCase):
    def test_index_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        index_path = repo_root / "presets" / "index.json"
        schema_path = repo_root / "schemas" / "presets_index.schema.json"

        index = json.loads(index_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(index)

    def test_each_preset_validates_against_run_config_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"
        run_config_schema = json.loads(
            (repo_root / "schemas" / "run_config.schema.json").read_text(encoding="utf-8")
        )
        validator = jsonschema.Draft202012Validator(run_config_schema)

        index = load_preset_index(presets_dir)
        for preset_entry in index.get("presets", []):
            preset_file = presets_dir / str(preset_entry["file"])
            payload = json.loads(preset_file.read_text(encoding="utf-8"))
            validator.validate(payload)

    def test_list_presets_deterministic_sorted_order(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"

        first = list_presets(presets_dir)
        second = list_presets(presets_dir)
        self.assertEqual(first, second)

        preset_ids = [item.get("preset_id") for item in first]
        self.assertEqual(preset_ids, sorted(preset_ids))

    def test_list_presets_filtering_deterministic_sorted_order(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"

        tag_first = list_presets(presets_dir, tag="translation")
        tag_second = list_presets(presets_dir, tag="translation")
        self.assertEqual(tag_first, tag_second)
        tag_ids = [item.get("preset_id") for item in tag_first]
        self.assertEqual(tag_ids, sorted(tag_ids))
        self.assertEqual(
            tag_ids,
            [
                "PRESET.SAFE_CLEANUP",
                "PRESET.VIBE.LIVE_YOU_ARE_THERE",
                "PRESET.VIBE.TRANSLATION_SAFE",
                "PRESET.VIBE.VOCAL_FORWARD",
            ],
        )

        category_ids = [
            item.get("preset_id")
            for item in list_presets(presets_dir, category="vibe")
        ]
        self.assertEqual(
            category_ids,
            [
                "PRESET.TURBO_DRAFT",
                "PRESET.VIBE.BRIGHT_AIRY",
                "PRESET.VIBE.DENSE_GLUE",
                "PRESET.VIBE.LIVE_YOU_ARE_THERE",
                "PRESET.VIBE.PUNCHY_TIGHT",
                "PRESET.VIBE.TRANSLATION_SAFE",
                "PRESET.VIBE.VOCAL_FORWARD",
                "PRESET.VIBE.WARM_INTIMATE",
                "PRESET.VIBE.WIDE_CINEMATIC",
            ],
        )

    def test_load_preset_run_config_stamps_preset_id(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"

        run_config = load_preset_run_config(presets_dir, "PRESET.SAFE_CLEANUP")
        self.assertEqual(run_config.get("schema_version"), "0.1.0")
        self.assertEqual(run_config.get("preset_id"), "PRESET.SAFE_CLEANUP")

    def test_vibe_presets_include_help_id_and_overlay(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"
        preset_items = list_presets(presets_dir)
        vibe_presets = [
            item
            for item in preset_items
            if isinstance(item, dict) and item.get("category") == "VIBE"
        ]

        self.assertTrue(vibe_presets)
        for preset in vibe_presets:
            preset_id = preset.get("preset_id")
            self.assertIsInstance(preset_id, str)
            if not isinstance(preset_id, str):
                continue

            help_id = preset.get("help_id")
            self.assertIsInstance(help_id, str, msg=f"Missing help_id for {preset_id}")
            if isinstance(help_id, str):
                self.assertRegex(help_id, re.compile(r"^HELP\.[A-Z0-9_.]+$"))
                self.assertEqual(get_preset_help_id(preset_id), help_id)

            overlay = preset.get("overlay")
            self.assertIsInstance(overlay, str, msg=f"Missing overlay for {preset_id}")
            if isinstance(overlay, str):
                words = [word for word in overlay.split() if word]
                self.assertGreaterEqual(len(words), 1)
                self.assertLessEqual(len(words), 3)

        by_id = {
            item.get("preset_id"): item
            for item in preset_items
            if isinstance(item, dict)
        }
        safe_cleanup = by_id.get("PRESET.SAFE_CLEANUP")
        self.assertIsInstance(safe_cleanup, dict)
        if isinstance(safe_cleanup, dict):
            self.assertEqual(
                safe_cleanup.get("help_id"),
                "HELP.PRESET.SAFE_CLEANUP",
            )

        live_you_are_there = by_id.get("PRESET.VIBE.LIVE_YOU_ARE_THERE")
        self.assertIsInstance(live_you_are_there, dict)
        if isinstance(live_you_are_there, dict):
            self.assertEqual(
                live_you_are_there.get("help_id"),
                "HELP.PRESET.VIBE.LIVE_YOU_ARE_THERE",
            )
            overlay = live_you_are_there.get("overlay")
            self.assertIsInstance(overlay, str)
            if isinstance(overlay, str):
                words = [word for word in overlay.split() if word]
                self.assertGreaterEqual(len(words), 1)
                self.assertLessEqual(len(words), 3)


if __name__ == "__main__":
    unittest.main()
