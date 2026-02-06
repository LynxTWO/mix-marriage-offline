import unittest
from pathlib import Path

from mmo.core.preset_recommendations import derive_preset_recommendations


def _presets_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "presets"


class TestPresetRecommendations(unittest.TestCase):
    def test_translation_high_prefers_safe_presets_in_order(self) -> None:
        report = {
            "profile_id": "PROFILE.FULL_SEND",
            "recommendations": [{"extreme": True}],
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "medium",
                "translation_risk": "high",
                "notes": [],
            },
        }

        recommendations = derive_preset_recommendations(report, _presets_dir(), n=3)
        self.assertEqual(
            [item.get("preset_id") for item in recommendations],
            [
                "PRESET.SAFE_CLEANUP",
                "PRESET.VIBE.TRANSLATION_SAFE",
                "PRESET.VIBE.BRIGHT_AIRY",
            ],
        )

    def test_density_and_masking_high_prefers_punch_then_glue_then_vocal(self) -> None:
        report = {
            "vibe_signals": {
                "density_level": "high",
                "masking_level": "high",
                "translation_risk": "medium",
                "notes": [],
            }
        }

        recommendations = derive_preset_recommendations(report, _presets_dir(), n=3)
        self.assertEqual(
            [item.get("preset_id") for item in recommendations],
            [
                "PRESET.VIBE.PUNCHY_TIGHT",
                "PRESET.VIBE.DENSE_GLUE",
                "PRESET.VIBE.VOCAL_FORWARD",
            ],
        )

    def test_excludes_current_preset_when_enough_alternatives(self) -> None:
        report = {
            "run_config": {"preset_id": "PRESET.VIBE.WIDE_CINEMATIC"},
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "low",
                "translation_risk": "low",
                "notes": [],
            },
        }

        recommendations = derive_preset_recommendations(report, _presets_dir(), n=3)
        self.assertEqual(
            [item.get("preset_id") for item in recommendations],
            [
                "PRESET.VIBE.WARM_INTIMATE",
                "PRESET.SAFE_CLEANUP",
                "PRESET.TURBO_DRAFT",
            ],
        )
        self.assertNotIn(
            "PRESET.VIBE.WIDE_CINEMATIC",
            [item.get("preset_id") for item in recommendations],
        )

    def test_deterministic_and_stable_reasons(self) -> None:
        report = {
            "vibe_signals": {
                "density_level": "high",
                "masking_level": "high",
                "translation_risk": "high",
                "notes": [],
            },
            "recommendations": [{"extreme": True}],
            "run_config": {"profile_id": "PROFILE.TURBO"},
        }

        first = derive_preset_recommendations(report, _presets_dir(), n=5)
        second = derive_preset_recommendations(report, _presets_dir(), n=5)
        self.assertEqual(first, second)
        self.assertTrue(first)
        for item in first:
            reasons = item.get("reasons")
            self.assertIsInstance(reasons, list)
            if not isinstance(reasons, list):
                continue
            self.assertTrue(reasons)
            for reason in reasons:
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip())


if __name__ == "__main__":
    unittest.main()
