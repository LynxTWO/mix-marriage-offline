import unittest

from mmo.core.config import load_effective_run_config, resolved_presets_dir


class TestConfigModule(unittest.TestCase):
    def test_resolved_presets_dir_prefers_ontology_presets(self) -> None:
        presets_dir = resolved_presets_dir()
        self.assertTrue(presets_dir.is_dir())
        self.assertTrue((presets_dir / "index.json").is_file())
        self.assertEqual(presets_dir.name, "presets")
        self.assertEqual(presets_dir.parent.name, "ontology")

    def test_load_effective_run_config_merges_preset_and_overrides(self) -> None:
        effective = load_effective_run_config(
            None,
            {"profile_id": "PROFILE.ASSIST"},
            preset_id="PRESET.SAFE_CLEANUP",
        )
        self.assertEqual(effective.get("schema_version"), "0.1.0")
        self.assertEqual(effective.get("preset_id"), "PRESET.SAFE_CLEANUP")
        self.assertEqual(effective.get("profile_id"), "PROFILE.ASSIST")


if __name__ == "__main__":
    unittest.main()
