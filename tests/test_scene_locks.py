import json
import re
import tempfile
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.scene_locks import (
    get_scene_lock,
    list_scene_locks,
    load_scene_locks,
)


class TestSceneLocksRegistry(unittest.TestCase):
    def test_scene_locks_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "scene_locks.schema.json"
        registry_path = repo_root / "ontology" / "scene_locks.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_scene_locks_returns_schema_version_and_locks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_scene_locks(repo_root / "ontology" / "scene_locks.yaml")

        self.assertEqual(registry.get("schema_version"), "0.1.0")
        locks = registry.get("locks")
        self.assertIsInstance(locks, dict)
        if not isinstance(locks, dict):
            return
        self.assertIn("LOCK.PRESERVE_DYNAMICS", locks)

    def test_list_and_get_scene_locks_are_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        scene_locks_path = repo_root / "ontology" / "scene_locks.yaml"

        first = list_scene_locks(scene_locks_path)
        second = list_scene_locks(scene_locks_path)
        self.assertEqual(first, second)

        lock_ids = [
            item.get("lock_id")
            for item in first
            if isinstance(item, dict) and isinstance(item.get("lock_id"), str)
        ]
        self.assertEqual(lock_ids, sorted(lock_ids))
        self.assertIn("LOCK.PRESERVE_DYNAMICS", lock_ids)

        lock = get_scene_lock("LOCK.PRESERVE_DYNAMICS", scene_locks_path)
        self.assertIsInstance(lock, dict)
        if isinstance(lock, dict):
            self.assertEqual(lock.get("label"), "Preserve dynamics")
            self.assertEqual(lock.get("severity"), "hard")

    def test_scene_locks_include_help_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        scene_locks_path = repo_root / "ontology" / "scene_locks.yaml"

        help_ids = [
            item.get("help_id")
            for item in list_scene_locks(scene_locks_path)
            if isinstance(item, dict) and isinstance(item.get("help_id"), str)
        ]
        self.assertTrue(help_ids)
        for help_id in help_ids:
            self.assertRegex(help_id, re.compile(r"^HELP\.LOCK\.[A-Z0-9_.]+$"))

    def test_load_scene_locks_rejects_unsorted_lock_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bad_registry_path = temp_path / "scene_locks.yaml"
            bad_registry_path.write_text(
                "\n".join(
                    [
                        'schema_version: "0.1.0"',
                        "locks:",
                        "  LOCK.Z_LAST:",
                        '    label: "Z lock"',
                        '    description: "Placed first on purpose."',
                        '    applies_to: ["scene"]',
                        '    severity: "hard"',
                        "  LOCK.A_FIRST:",
                        '    label: "A lock"',
                        '    description: "Should be first in deterministic order."',
                        '    applies_to: ["scene"]',
                        '    severity: "taste"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "sorted by lock_id"):
                load_scene_locks(bad_registry_path)


if __name__ == "__main__":
    unittest.main()
