"""Tests for deterministic DSP hook pipeline scaffolding (PR8)."""

from __future__ import annotations

import json
import unittest

from mmo.core.dsp_dispatch import StemJob, dispatch_stems
from mmo.core.dsp_pipeline_hooks import (
    DspStemSpec,
    ConservativeHpfRumblePlugin,
    run_dsp_pipeline_hooks,
    validate_dsp_plugin_manifest,
)


class TestDspPluginManifest(unittest.TestCase):
    def test_default_hpf_manifest_is_valid(self) -> None:
        plugin = ConservativeHpfRumblePlugin()
        errors = validate_dsp_plugin_manifest(plugin.manifest)
        self.assertEqual(errors, [])

    def test_missing_required_field_is_rejected(self) -> None:
        plugin = ConservativeHpfRumblePlugin()
        bad_manifest = json.loads(json.dumps(plugin.manifest))
        del bad_manifest["stage_scope"]

        errors = validate_dsp_plugin_manifest(bad_manifest)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("stage_scope" in item for item in errors))

    def test_unknown_field_is_rejected(self) -> None:
        plugin = ConservativeHpfRumblePlugin()
        bad_manifest = json.loads(json.dumps(plugin.manifest))
        bad_manifest["unknown_field"] = "nope"

        errors = validate_dsp_plugin_manifest(bad_manifest)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("Additional properties" in item for item in errors))

    def test_invalid_bounds_error_is_deterministic(self) -> None:
        plugin = ConservativeHpfRumblePlugin()
        bad_manifest = json.loads(json.dumps(plugin.manifest))
        bad_manifest["action"]["parameter_bounds"]["cutoff_hz"] = {
            "min": 50.0,
            "max": 10.0,
        }

        errors_a = validate_dsp_plugin_manifest(bad_manifest)
        errors_b = validate_dsp_plugin_manifest(bad_manifest)

        self.assertEqual(errors_a, errors_b)
        self.assertTrue(any("min must be <= max" in item for item in errors_a))


class TestDspPipelineHooks(unittest.TestCase):
    def _stem_results(self) -> list:
        jobs = [
            StemJob("STEM.BASS", "LAYOUT.5_1", "SMPTE"),
            StemJob("STEM.GTR", "LAYOUT.5_1", "SMPTE"),
            StemJob("STEM.VOX", "LAYOUT.5_1", "SMPTE"),
        ]
        return dispatch_stems(jobs, max_workers=4)

    def _stem_specs(self) -> list[DspStemSpec]:
        return [
            DspStemSpec(
                stem_id="STEM.BASS",
                role_id="ROLE.BASS.DI",
                bus_id="BUS.BASS",
                evidence={"rumble_confidence": 0.99},
            ),
            DspStemSpec(
                stem_id="STEM.GTR",
                role_id="ROLE.GTR.ELECTRIC",
                bus_id="BUS.MUSIC",
                evidence={"rumble_confidence": 0.40},
            ),
            DspStemSpec(
                stem_id="STEM.VOX",
                role_id="ROLE.VOCAL.LEAD",
                bus_id="BUS.VOX",
                evidence={"rumble_confidence": 0.93},
            ),
        ]

    def test_hpf_applies_only_to_non_bass_with_high_rumble_evidence(self) -> None:
        receipt = run_dsp_pipeline_hooks(
            stem_results=self._stem_results(),
            stem_specs=self._stem_specs(),
        )

        actions = receipt.get("actions")
        self.assertIsInstance(actions, list)
        self.assertEqual(len(actions), 1)

        action = actions[0]
        self.assertEqual(action.get("target_id"), "STEM.VOX")
        self.assertEqual(action.get("action_id"), "ACTION.DSP.HPF.STEM")
        self.assertEqual(action.get("stage_scope"), "pre_bus_stem")
        params = action.get("params", {})
        self.assertGreaterEqual(float(params.get("cutoff_hz", 0.0)), 20.0)
        self.assertLessEqual(float(params.get("cutoff_hz", 999.0)), 45.0)
        self.assertEqual(float(params.get("slope_db_per_oct", 0.0)), 12.0)

    def test_all_events_emit_what_why_where_confidence(self) -> None:
        receipt = run_dsp_pipeline_hooks(
            stem_results=self._stem_results(),
            stem_specs=self._stem_specs(),
        )

        events = receipt.get("events")
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)

        for event in events:
            self.assertIsInstance(event.get("what"), str)
            self.assertTrue(event.get("what"))
            self.assertIsInstance(event.get("why"), str)
            self.assertTrue(event.get("why"))
            self.assertIsInstance(event.get("where"), list)
            self.assertGreaterEqual(len(event.get("where", [])), 1)
            confidence = event.get("confidence")
            self.assertIsInstance(confidence, float)
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)

    def test_bus_and_post_master_default_to_guardrail_skip(self) -> None:
        receipt = run_dsp_pipeline_hooks(
            stem_results=self._stem_results(),
            stem_specs=self._stem_specs(),
            enable_bus_stage=False,
            enable_post_master_stage=False,
        )

        actions = receipt.get("actions")
        self.assertIsInstance(actions, list)
        self.assertTrue(all(item.get("stage_scope") == "pre_bus_stem" for item in actions))

        events = receipt.get("events")
        self.assertIsInstance(events, list)
        what_rows = [event.get("what") for event in events if isinstance(event, dict)]
        self.assertIn("bus DSP stage skipped", what_rows)
        self.assertIn("post-master DSP stage skipped", what_rows)

    def test_receipt_is_deterministic_across_repeated_runs(self) -> None:
        stem_results = self._stem_results()
        stem_specs = self._stem_specs()

        receipt_a = run_dsp_pipeline_hooks(
            stem_results=stem_results,
            stem_specs=stem_specs,
        )
        receipt_b = run_dsp_pipeline_hooks(
            stem_results=stem_results,
            stem_specs=stem_specs,
        )
        self.assertEqual(receipt_a, receipt_b)

    def test_receipt_is_deterministic_across_dispatch_worker_counts(self) -> None:
        jobs = [
            StemJob("STEM.BASS", "LAYOUT.5_1", "SMPTE"),
            StemJob("STEM.GTR", "LAYOUT.5_1", "SMPTE"),
            StemJob("STEM.VOX", "LAYOUT.5_1", "SMPTE"),
        ]
        stem_specs = self._stem_specs()
        serial_results = dispatch_stems(jobs, max_workers=1)
        parallel_results = dispatch_stems(jobs, max_workers=4)

        serial_receipt = run_dsp_pipeline_hooks(
            stem_results=serial_results,
            stem_specs=stem_specs,
        )
        parallel_receipt = run_dsp_pipeline_hooks(
            stem_results=parallel_results,
            stem_specs=stem_specs,
        )
        self.assertEqual(serial_receipt, parallel_receipt)


if __name__ == "__main__":
    unittest.main()
