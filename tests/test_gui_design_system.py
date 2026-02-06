import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.gui_design import load_gui_design


class TestGuiDesignSystem(unittest.TestCase):
    def test_gui_design_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "gui_design.schema.json"
        gui_design_path = repo_root / "ontology" / "gui_design.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(gui_design_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_gui_design_palette_has_required_keys(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = load_gui_design(repo_root / "ontology" / "gui_design.yaml")
        palette = payload["theme"]["palette"]
        required_palette_keys = {
            "background",
            "surface",
            "surface_alt",
            "text",
            "text_muted",
            "accent_primary",
            "accent_secondary",
            "danger",
            "warning",
            "ok",
            "info",
        }
        self.assertTrue(required_palette_keys.issubset(set(palette.keys())))

    def test_gui_design_max_nav_depth_is_two(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = load_gui_design(repo_root / "ontology" / "gui_design.yaml")
        self.assertEqual(payload["layout_rules"]["max_nav_depth"], 2)


if __name__ == "__main__":
    unittest.main()
