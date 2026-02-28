import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.loudness_profiles import (
    DEFAULT_LOUDNESS_PROFILE_ID,
    get_loudness_profile,
    list_loudness_profile_ids,
    resolve_loudness_profile_receipt,
)


class TestLoudnessProfiles(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_registry_yaml_validates_against_schema(self) -> None:
        repo_root = self._repo_root()
        schema_path = repo_root / "schemas" / "loudness_profiles.schema.json"
        registry_path = repo_root / "ontology" / "loudness_profiles.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_profile_ids_are_sorted_and_deterministic(self) -> None:
        first = list_loudness_profile_ids()
        second = list_loudness_profile_ids()
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))
        self.assertEqual(
            first,
            [
                "LOUD.ATSC_A85_FIXED_DIALNORM",
                "LOUD.EBU_R128_PROGRAM",
                "LOUD.NETFLIX_QC_FULL_PROGRAM",
                "LOUD.SPOTIFY_PLAYBACK_NORMALIZATION",
            ],
        )

    def test_get_unknown_profile_raises_sorted_known_ids(self) -> None:
        unknown = "LOUD.UNKNOWN.PROFILE"
        known = list_loudness_profile_ids()
        expected = (
            f"Unknown loudness_profile_id: {unknown}. "
            f"Known loudness_profile_ids: {', '.join(known)}"
        )
        with self.assertRaises(ValueError) as first:
            get_loudness_profile(unknown)
        with self.assertRaises(ValueError) as second:
            get_loudness_profile(unknown)
        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_resolve_default_receipt(self) -> None:
        receipt = resolve_loudness_profile_receipt(None)
        self.assertEqual(receipt["loudness_profile_id"], DEFAULT_LOUDNESS_PROFILE_ID)
        self.assertEqual(receipt["method_id"], "BS.1770-5")
        self.assertTrue(receipt["method_implemented"])

    def test_informational_and_best_effort_warnings_are_reported(self) -> None:
        spotify = resolve_loudness_profile_receipt("LOUD.SPOTIFY_PLAYBACK_NORMALIZATION")
        spotify_warnings = " ".join(spotify["warnings"])
        self.assertIn("informational playback normalization guidance", spotify_warnings)

        netflix = resolve_loudness_profile_receipt("LOUD.NETFLIX_QC_FULL_PROGRAM")
        netflix_warnings = " ".join(netflix["warnings"])
        self.assertIn("Best-effort mapping", netflix_warnings)

    def test_unsupported_method_emits_warning_without_hard_failure(self) -> None:
        repo_root = self._repo_root()
        registry_path = repo_root / "ontology" / "loudness_profiles.yaml"
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        if not isinstance(payload, dict):
            return

        profiles = payload.get("profiles")
        self.assertIsInstance(profiles, dict)
        if not isinstance(profiles, dict):
            return

        ebu = profiles.get("LOUD.EBU_R128_PROGRAM")
        self.assertIsInstance(ebu, dict)
        if not isinstance(ebu, dict):
            return
        ebu["method_id"] = "BS.1770-5-DIALOG-GATED"

        with tempfile.TemporaryDirectory() as temp_dir:
            custom_registry = Path(temp_dir) / "loudness_profiles.yaml"
            custom_registry.write_text(
                yaml.safe_dump(payload, sort_keys=False),
                encoding="utf-8",
            )
            receipt = resolve_loudness_profile_receipt(
                "LOUD.EBU_R128_PROGRAM",
                path=custom_registry,
            )

        self.assertEqual(receipt["method_id"], "BS.1770-5-DIALOG-GATED")
        self.assertFalse(receipt["method_implemented"])
        joined = " ".join(receipt["warnings"])
        self.assertIn("not implemented yet", joined)


if __name__ == "__main__":
    unittest.main()
