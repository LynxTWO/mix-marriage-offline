import json
import unittest
from pathlib import Path

import jsonschema

from mmo.core.presets import list_presets, load_preset_index, load_preset_run_config


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

    def test_load_preset_run_config_stamps_preset_id(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        presets_dir = repo_root / "presets"

        run_config = load_preset_run_config(presets_dir, "PRESET.SAFE_CLEANUP")
        self.assertEqual(run_config.get("schema_version"), "0.1.0")
        self.assertEqual(run_config.get("preset_id"), "PRESET.SAFE_CLEANUP")


if __name__ == "__main__":
    unittest.main()
