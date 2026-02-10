import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.speaker_positions import (
    get_layout_positions,
    load_speaker_positions,
)


class TestSpeakerPositionsRegistry(unittest.TestCase):
    def test_speaker_positions_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "speaker_positions.schema.json"
        registry_path = repo_root / "ontology" / "speaker_positions.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_and_get_layout_positions_are_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "speaker_positions.yaml"

        first = load_speaker_positions(registry_path)
        second = load_speaker_positions(registry_path)
        self.assertEqual(first, second)

        layouts = first.get("layouts")
        self.assertIsInstance(layouts, dict)
        if not isinstance(layouts, dict):
            return
        self.assertEqual(list(layouts.keys()), sorted(layouts.keys()))
        self.assertIn("LAYOUT.2_0", layouts)

        layout_positions = get_layout_positions("LAYOUT.5_1", registry_path)
        self.assertIsInstance(layout_positions, list)
        if isinstance(layout_positions, list):
            channels = [
                item.get("ch")
                for item in layout_positions
                if isinstance(item, dict)
            ]
            self.assertEqual(channels, sorted(ch for ch in channels if isinstance(ch, int)))

        self.assertIsNone(get_layout_positions("LAYOUT.UNKNOWN", registry_path))

    def test_load_speaker_positions_rejects_unsorted_channels(self) -> None:
        payload = """\
schema_version: "0.1.0"
layouts:
  LAYOUT.2_0:
    channels:
      - ch: 1
        name: "R"
        azimuth_deg: 30
        elevation_deg: 0
      - ch: 0
        name: "L"
        azimuth_deg: -30
        elevation_deg: 0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "speaker_positions_unsorted.yaml"
            path.write_text(payload, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sorted by ch"):
                load_speaker_positions(path)

    def test_load_speaker_positions_rejects_duplicate_channels(self) -> None:
        payload = """\
schema_version: "0.1.0"
layouts:
  LAYOUT.2_0:
    channels:
      - ch: 0
        name: "L"
        azimuth_deg: -30
        elevation_deg: 0
      - ch: 0
        name: "R"
        azimuth_deg: 30
        elevation_deg: 0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "speaker_positions_duplicate.yaml"
            path.write_text(payload, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate ch values"):
                load_speaker_positions(path)


if __name__ == "__main__":
    unittest.main()
