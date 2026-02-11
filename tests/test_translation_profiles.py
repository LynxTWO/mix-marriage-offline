import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.translation_profiles import (
    get_translation_profile,
    list_translation_profiles,
    load_translation_profiles,
)


class TestTranslationProfiles(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_translation_profiles_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "translation_profiles.schema.json"
        registry_path = repo_root / "ontology" / "translation_profiles.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_list_translation_profiles_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "translation_profiles.yaml"

        first = list_translation_profiles(registry_path)
        second = list_translation_profiles(registry_path)
        self.assertEqual(first, second)

        profile_ids = [
            item.get("profile_id")
            for item in first
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        ]
        self.assertEqual(profile_ids, sorted(profile_ids))
        self.assertEqual(
            profile_ids,
            [
                "TRANS.DEVICE.CAR",
                "TRANS.DEVICE.EARBUDS",
                "TRANS.DEVICE.PHONE",
                "TRANS.DEVICE.SMALL_SPEAKER",
                "TRANS.MONO.COLLAPSE",
            ],
        )

    def test_get_translation_profile_unknown_id_error_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "translation_profiles.yaml"
        unknown_profile_id = "TRANS.UNKNOWN.PROFILE"

        known_ids = [
            item.get("profile_id")
            for item in list_translation_profiles(registry_path)
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        ]
        expected = (
            f"Unknown translation profile_id: {unknown_profile_id}. "
            f"Known profile_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            get_translation_profile(unknown_profile_id, registry_path)
        with self.assertRaises(ValueError) as second:
            get_translation_profile(unknown_profile_id, registry_path)

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_load_translation_profiles_schema_failure_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "translation_profiles.yaml"

        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        if not isinstance(payload, dict):
            return

        profile = payload.get("TRANS.DEVICE.CAR")
        self.assertIsInstance(profile, dict)
        if not isinstance(profile, dict):
            return

        thresholds = profile.get("default_thresholds")
        self.assertIsInstance(thresholds, dict)
        if not isinstance(thresholds, dict):
            return
        thresholds["max_lufs_delta"] = "not-a-number"

        scoring = profile.get("scoring")
        self.assertIsInstance(scoring, dict)
        if not isinstance(scoring, dict):
            return
        scoring["unknown_metric"] = 0.2

        with tempfile.TemporaryDirectory() as temp_dir:
            broken_registry_path = Path(temp_dir) / "translation_profiles.invalid.yaml"
            broken_registry_path.write_text(
                yaml.safe_dump(payload, sort_keys=False),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as first:
                load_translation_profiles(broken_registry_path)
            with self.assertRaises(ValueError) as second:
                load_translation_profiles(broken_registry_path)

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertIn("Translation profiles registry schema validation failed", str(first.exception))
        self.assertIn("max_lufs_delta", str(first.exception))
        self.assertIn("unknown_metric", str(first.exception))

    def test_cli_translation_list_json_is_sorted_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "translation",
            "list",
            "--format",
            "json",
        ]

        first = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        second = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        profile_ids = [
            item.get("profile_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        ]
        self.assertEqual(profile_ids, sorted(profile_ids))
        self.assertIn("TRANS.MONO.COLLAPSE", profile_ids)

    def test_cli_translation_show_text_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "translation",
            "show",
            "TRANS.MONO.COLLAPSE",
            "--format",
            "text",
        ]

        first = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )
        second = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=self._env(repo_root),
        )

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("TRANS.MONO.COLLAPSE", first.stdout)
        self.assertIn("intent: compatibility", first.stdout)
        self.assertIn("default_thresholds:", first.stdout)
        self.assertIn("scoring:", first.stdout)


if __name__ == "__main__":
    unittest.main()
