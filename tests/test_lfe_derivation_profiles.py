import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.lfe_derivation_profiles import (
    DEFAULT_LFE_DERIVATION_PROFILE_ID,
    get_lfe_derivation_profile,
    list_lfe_derivation_profile_ids,
)


class TestLfeDerivationProfiles(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_registry_yaml_validates_against_schema(self) -> None:
        repo_root = self._repo_root()
        schema_path = repo_root / "schemas" / "lfe_derivation_profiles.schema.json"
        registry_path = repo_root / "ontology" / "lfe_derivation_profiles.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_profile_ids_are_sorted_and_deterministic(self) -> None:
        first = list_lfe_derivation_profile_ids()
        second = list_lfe_derivation_profile_ids()
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))
        self.assertEqual(
            first,
            [
                "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
                "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
            ],
        )

    def test_get_profile_defaults_to_cinema_profile(self) -> None:
        profile = get_lfe_derivation_profile(None)
        self.assertEqual(
            profile["lfe_derivation_profile_id"],
            DEFAULT_LFE_DERIVATION_PROFILE_ID,
        )
        self.assertEqual(profile["lowpass_hz"], 120.0)
        self.assertEqual(profile["slope_db_per_oct"], 24)
        self.assertEqual(profile["gain_trim_db"], -10.0)

    def test_get_unknown_profile_raises_sorted_known_ids(self) -> None:
        unknown = "LFE_DERIVE.UNKNOWN_PROFILE"
        known = list_lfe_derivation_profile_ids()
        expected = (
            f"Unknown lfe_derivation_profile_id: {unknown}. "
            f"Known lfe_derivation_profile_ids: {', '.join(known)}"
        )
        with self.assertRaises(ValueError) as first:
            get_lfe_derivation_profile(unknown)
        with self.assertRaises(ValueError) as second:
            get_lfe_derivation_profile(unknown)
        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)


if __name__ == "__main__":
    unittest.main()
