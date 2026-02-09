import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.ui_copy import load_ui_copy, resolve_ui_copy


class TestUiCopyRegistry(unittest.TestCase):
    def test_ui_copy_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "ui_copy.schema.json"
        registry_path = repo_root / "ontology" / "ui_copy.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_ui_copy_returns_default_locale_and_entries(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_ui_copy(repo_root / "ontology" / "ui_copy.yaml")

        self.assertEqual(registry.get("schema_version"), "0.1.0")
        self.assertEqual(registry.get("default_locale"), "en-US")

        locales = registry.get("locales")
        self.assertIsInstance(locales, dict)
        if not isinstance(locales, dict):
            return
        locale_payload = locales.get("en-US")
        self.assertIsInstance(locale_payload, dict)
        if not isinstance(locale_payload, dict):
            return
        entries = locale_payload.get("entries")
        self.assertIsInstance(entries, dict)
        if not isinstance(entries, dict):
            return
        self.assertIn("COPY.NAV.DASHBOARD", entries)
        self.assertIn("COPY.BADGE.BLOCKED", entries)

    def test_resolve_ui_copy_is_deterministic_and_handles_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_ui_copy(repo_root / "ontology" / "ui_copy.yaml")

        resolved = resolve_ui_copy(
            [
                "COPY.ACTION.RUN",
                "COPY.MISSING.EXAMPLE",
                "COPY.ACTION.RUN",
            ],
            registry,
            locale="en-US",
        )
        self.assertEqual(
            list(resolved.keys()),
            ["COPY.ACTION.RUN", "COPY.MISSING.EXAMPLE"],
        )
        self.assertEqual(resolved["COPY.ACTION.RUN"].get("text"), "Run")
        missing_entry = resolved["COPY.MISSING.EXAMPLE"]
        self.assertEqual(missing_entry.get("text"), "COPY.MISSING.EXAMPLE")
        self.assertEqual(missing_entry.get("tooltip"), "Missing copy entry")


if __name__ == "__main__":
    unittest.main()
