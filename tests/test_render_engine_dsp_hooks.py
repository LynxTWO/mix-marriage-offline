"""Integration tests for render-engine DSP hook scaffold logging."""

from __future__ import annotations

import unittest

from mmo.core.progress import ExplainableLogEvent
from mmo.core.render_contract import build_render_contract
from mmo.core.render_engine import render_scene_to_targets


def _scene() -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.DSP_HOOKS",
        "scene_path": "scenes/test/dsp_hooks_scene.json",
        "source": {
            "stems_dir": "stems/test",
            "layout_id": "LAYOUT.5_1",
            "created_from": "analyze",
        },
        "metadata": {},
    }


def _contract() -> dict:
    return build_render_contract(
        "TARGET.SURROUND.5_1",
        "LAYOUT.5_1",
        source_layout_id="LAYOUT.5_1",
        output_formats=["wav"],
    )


def _dsp_options(log_listener: list[ExplainableLogEvent]) -> dict:
    def _capture(event: ExplainableLogEvent) -> None:
        log_listener.append(event)

    return {
        "dry_run": True,
        "max_workers": 1,
        "stem_max_workers": 1,
        "dsp_stems": [
            {
                "stem_id": "STEM.BASS",
                "role_id": "ROLE.BASS.DI",
                "bus_id": "BUS.BASS",
                "evidence": {"rumble_confidence": 0.95},
            },
            {
                "stem_id": "STEM.VOX",
                "role_id": "ROLE.VOCAL.LEAD",
                "bus_id": "BUS.VOX",
                "evidence": {"rumble_confidence": 0.92},
            },
        ],
        "enable_bus_dsp": False,
        "enable_post_master_dsp": False,
        "log_listener": _capture,
    }


class TestRenderEngineDspHooks(unittest.TestCase):
    def test_dsp_logs_emit_what_why_where_confidence(self) -> None:
        captured: list[ExplainableLogEvent] = []
        report = render_scene_to_targets(_scene(), [_contract()], _dsp_options(captured))

        self.assertIn("jobs", report)
        dsp_events = [event for event in captured if event.scope == "dsp"]
        self.assertGreater(len(dsp_events), 0)

        for event in dsp_events:
            self.assertTrue(event.what)
            self.assertTrue(event.why)
            self.assertIsInstance(event.where, tuple)
            self.assertGreaterEqual(len(event.where), 1)
            self.assertIsInstance(event.confidence, float)
            self.assertGreaterEqual(event.confidence or 0.0, 0.0)
            self.assertLessEqual(event.confidence or 1.0, 1.0)

        whats = [event.what for event in dsp_events]
        self.assertIn("conservative HPF planned", whats)
        self.assertIn("bus DSP stage skipped", whats)
        self.assertIn("post-master DSP stage skipped", whats)

    def test_dsp_log_signature_is_deterministic(self) -> None:
        first_capture: list[ExplainableLogEvent] = []
        second_capture: list[ExplainableLogEvent] = []

        render_scene_to_targets(_scene(), [_contract()], _dsp_options(first_capture))
        render_scene_to_targets(_scene(), [_contract()], _dsp_options(second_capture))

        def _signature(rows: list[ExplainableLogEvent]) -> list[tuple]:
            dsp_rows = [event for event in rows if event.scope == "dsp"]
            return [
                (
                    event.scope,
                    event.what,
                    event.why,
                    tuple(event.where),
                    event.confidence,
                    tuple(event.evidence.get("codes") or []),
                )
                for event in dsp_rows
            ]

        self.assertEqual(_signature(first_capture), _signature(second_capture))

    def test_render_report_carries_required_stage_ids_without_wall_clock_by_default(self) -> None:
        captured: list[ExplainableLogEvent] = []
        report = render_scene_to_targets(_scene(), [_contract()], _dsp_options(captured))

        required_stage_ids = {
            "planning",
            "resampling",
            "dsp_hooks",
            "export_finalize",
            "qa_gates",
        }
        self.assertTrue(
            required_stage_ids.issubset({row["stage_id"] for row in report["stage_metrics"]})
        )
        self.assertTrue(
            required_stage_ids.issubset({row["stage_id"] for row in report["stage_evidence"]})
        )
        self.assertNotIn("wall_clock", report)


if __name__ == "__main__":
    unittest.main()
