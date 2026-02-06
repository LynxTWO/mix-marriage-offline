import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.help_registry import load_help_registry, resolve_help_entries


class TestHelpRegistry(unittest.TestCase):
    def test_help_registry_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "help_registry.schema.json"
        registry_path = repo_root / "ontology" / "help.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_help_registry_returns_schema_version_and_entries(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_help_registry(repo_root / "ontology" / "help.yaml")

        self.assertEqual(registry.get("schema_version"), "0.1.0")
        entries = registry.get("entries")
        self.assertIsInstance(entries, dict)
        if not isinstance(entries, dict):
            return
        self.assertIn("HELP.PRESET.SAFE_CLEANUP", entries)

    def test_resolve_help_entries_is_deterministic_and_handles_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_help_registry(repo_root / "ontology" / "help.yaml")

        resolved = resolve_help_entries(
            [
                "HELP.PRESET.SAFE_CLEANUP",
                "HELP.MISSING.EXAMPLE",
                "HELP.PRESET.SAFE_CLEANUP",
            ],
            registry,
        )
        self.assertEqual(
            list(resolved.keys()),
            ["HELP.MISSING.EXAMPLE", "HELP.PRESET.SAFE_CLEANUP"],
        )
        missing_entry = resolved["HELP.MISSING.EXAMPLE"]
        self.assertEqual(missing_entry.get("title"), "HELP.MISSING.EXAMPLE")
        self.assertEqual(missing_entry.get("short"), "Missing help entry")

    def test_cli_help_list_json_is_sorted_and_deterministic(self) -> None:
        command = [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            "-m",
            "mmo",
            "help",
            "list",
            "--format",
            "json",
        ]

        first = subprocess.run(command, check=False, capture_output=True, text=True)
        second = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        help_ids = [
            item.get("help_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("help_id"), str)
        ]
        self.assertEqual(help_ids, sorted(help_ids))
        self.assertIn("HELP.PRESET.SAFE_CLEANUP", help_ids)

    def test_cli_help_show_text_is_deterministic(self) -> None:
        command = [
            os.fspath(os.getenv("PYTHON", "") or sys.executable),
            "-m",
            "mmo",
            "help",
            "show",
            "HELP.PRESET.SAFE_CLEANUP",
            "--format",
            "text",
        ]

        first = subprocess.run(command, check=False, capture_output=True, text=True)
        second = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("Safe cleanup", first.stdout)
        self.assertIn("Cues:", first.stdout)
        self.assertIn("Watch out for:", first.stdout)


if __name__ == "__main__":
    unittest.main()
