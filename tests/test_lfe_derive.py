import json
import math
import unittest
from pathlib import Path

import jsonschema

from mmo.core.lfe_derivation_profiles import (
    DEFAULT_LFE_DERIVATION_PROFILE_ID,
    get_lfe_derivation_profile,
)
from mmo.dsp.lfe_derive import PHASE_DELTA_THRESHOLD_DB, derive_missing_lfe


def _sine_wave(
    *,
    freq_hz: float,
    sample_rate_hz: int,
    sample_count: int,
    phase_radians: float = 0.0,
) -> list[float]:
    return [
        math.sin(
            (2.0 * math.pi * float(freq_hz) * float(index) / float(sample_rate_hz))
            + float(phase_radians)
        )
        for index in range(sample_count)
    ]


def _receipt_validator() -> jsonschema.Draft202012Validator:
    repo_root = Path(__file__).resolve().parents[1]
    root_schema = json.loads(
        (repo_root / "schemas" / "render_plan.schema.json").read_text(encoding="utf-8")
    )
    wrapper_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": root_schema.get("$defs", {}),
        "allOf": [{"$ref": "#/$defs/lfe_derivation_receipt"}],
    }
    return jsonschema.Draft202012Validator(wrapper_schema)


class TestLfeDerive(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_rate_hz = 48000
        self.sample_count = 4800
        self.profile = get_lfe_derivation_profile(DEFAULT_LFE_DERIVATION_PROFILE_ID)

    def test_in_phase_lr_selects_l_plus_r(self) -> None:
        left = _sine_wave(
            freq_hz=50.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = list(left)

        channels, receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=1,
            profile=self.profile,
            lfe_mode="mono",
        )

        self.assertEqual(len(channels), 1)
        self.assertEqual(receipt["chosen_sum_mode"], "L+R")
        self.assertTrue(receipt["derivation_ran"])
        self.assertGreaterEqual(receipt["delta_db"], PHASE_DELTA_THRESHOLD_DB)

    def test_out_of_phase_lr_selects_l_minus_r(self) -> None:
        left = _sine_wave(
            freq_hz=50.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = [-sample for sample in left]

        channels, receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=1,
            profile=self.profile,
            lfe_mode="mono",
        )

        self.assertEqual(len(channels), 1)
        self.assertEqual(receipt["chosen_sum_mode"], "L-R")
        self.assertTrue(receipt["derivation_ran"])
        self.assertGreaterEqual(receipt["delta_db"], PHASE_DELTA_THRESHOLD_DB)

    def test_delta_below_threshold_keeps_default_l_plus_r(self) -> None:
        left = _sine_wave(
            freq_hz=60.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = [0.0 for _ in left]

        _, receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=1,
            profile=self.profile,
            lfe_mode="mono",
        )

        self.assertEqual(receipt["chosen_sum_mode"], "L+R")
        self.assertLess(receipt["delta_db"], PHASE_DELTA_THRESHOLD_DB)

    def test_dual_lfe_mono_mode_is_exact_mirror(self) -> None:
        left = _sine_wave(
            freq_hz=70.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = list(left)

        channels, receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=2,
            profile=self.profile,
            lfe_mode="mono",
        )

        self.assertEqual(len(channels), 2)
        self.assertEqual(channels[0], channels[1])
        self.assertEqual(receipt["target_lfe_channel_count"], 2)
        self.assertEqual(receipt["lfe_mode"], "mono")

    def test_stereo_lfe_mode_flips_right_for_out_of_phase(self) -> None:
        left = _sine_wave(
            freq_hz=40.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = [-sample for sample in left]

        channels, receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=2,
            profile=self.profile,
            lfe_mode="stereo",
        )

        self.assertEqual(len(channels), 2)
        self.assertEqual(receipt["chosen_sum_mode"], "flipped R")
        self.assertEqual(receipt["lfe_mode"], "stereo")
        self.assertGreaterEqual(receipt["delta_db"], PHASE_DELTA_THRESHOLD_DB)
        for left_sample, right_sample in zip(channels[0], channels[1]):
            self.assertAlmostEqual(left_sample, right_sample, places=12)

    def test_receipts_are_schema_valid(self) -> None:
        validator = _receipt_validator()
        left = _sine_wave(
            freq_hz=55.0,
            sample_rate_hz=self.sample_rate_hz,
            sample_count=self.sample_count,
        )
        right = list(left)

        _, mono_receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=1,
            profile=self.profile,
            lfe_mode="mono",
        )
        validator.validate(mono_receipt)

        _, stereo_receipt = derive_missing_lfe(
            left=left,
            right=right,
            sample_rate_hz=self.sample_rate_hz,
            target_lfe_channel_count=2,
            profile=self.profile,
            lfe_mode="stereo",
        )
        validator.validate(stereo_receipt)


if __name__ == "__main__":
    unittest.main()
