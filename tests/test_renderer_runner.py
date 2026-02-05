import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.core.gates import apply_gates_to_report
from mmo.core.pipeline import load_plugins, run_renderers


def _write_wav_16bit(path: Path, *, sample_rate_hz: int = 48000, duration_s: float = 0.1) -> None:
    frames = int(sample_rate_hz * duration_s)
    samples = [
        int(0.45 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestRendererRunner(unittest.TestCase):
    def test_run_renderers_filters_and_records_skipped(self) -> None:
        eligible_id = "REC.RENDER.ELIGIBLE"
        blocked_id = "REC.RENDER.BLOCKED"
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {},
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": eligible_id,
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.DOWNMIX.POLICY_ID",
                            "value": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        },
                        {
                            "param_id": "PARAM.DOWNMIX.TARGET_LAYOUT_ID",
                            "value": "LAYOUT.2_0",
                        },
                    ],
                },
                {
                    "recommendation_id": blocked_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [
                        {
                            "param_id": "PARAM.GAIN.DB",
                            "value": -20.0,
                        }
                    ],
                },
            ],
        }

        apply_gates_to_report(report, policy_path=Path("ontology/policies/gates.yaml"))
        plugins = load_plugins(Path("plugins"))
        manifests = run_renderers(report, plugins)

        manifests_by_id = {
            manifest.get("renderer_id"): manifest
            for manifest in manifests
            if isinstance(manifest, dict) and isinstance(manifest.get("renderer_id"), str)
        }
        self.assertIn("PLUGIN.RENDERER.SAFE", manifests_by_id)
        self.assertIn("PLUGIN.RENDERER.GAIN_TRIM", manifests_by_id)

        for manifest in manifests:
            skipped = manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            blocked_entries = [
                item
                for item in skipped
                if isinstance(item, dict)
                and item.get("recommendation_id") == blocked_id
                and item.get("reason") == "blocked_by_gates"
            ]
            self.assertEqual(len(blocked_entries), 1)
            self.assertIn("GATE.MAX_GAIN_DB", blocked_entries[0].get("gate_summary", ""))

        safe_manifest = manifests_by_id["PLUGIN.RENDERER.SAFE"]
        self.assertEqual(safe_manifest.get("received_recommendation_ids"), [eligible_id])

        schema_path = Path("schemas/render_manifest.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(
            {
                "schema_version": "0.1.0",
                "report_id": report["report_id"],
                "renderer_manifests": manifests,
            }
        )

    def test_run_renderers_merges_gate_and_plugin_skips(self) -> None:
        eligible_id = "REC.RENDER.GAIN.ELIGIBLE"
        blocked_id = "REC.RENDER.GAIN.BLOCKED"
        report = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.TEST.MERGE.SKIPPED",
            "project_id": "PROJECT.TEST",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {
                "stems": [
                    {
                        "stem_id": "kick",
                        "file_path": "kick.wav",
                    }
                ]
            },
            "issues": [],
            "recommendations": [
                {
                    "recommendation_id": eligible_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {"scope": "stem", "stem_id": "kick"},
                    "params": [{"param_id": "PARAM.GAIN.DB", "value": -6.0}],
                },
                {
                    "recommendation_id": blocked_id,
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {"scope": "stem", "stem_id": "kick"},
                    "params": [{"param_id": "PARAM.GAIN.DB", "value": -20.0}],
                },
            ],
        }

        apply_gates_to_report(report, policy_path=Path("ontology/policies/gates.yaml"))
        plugins = load_plugins(Path("plugins"))
        manifests = run_renderers(report, plugins, output_dir=None)

        gain_manifest = next(
            (
                item
                for item in manifests
                if isinstance(item, dict)
                and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
            ),
            None,
        )
        self.assertIsNotNone(gain_manifest)
        if gain_manifest is None:
            return

        skipped = gain_manifest.get("skipped")
        self.assertIsInstance(skipped, list)
        if not isinstance(skipped, list):
            return

        tuples = [
            (
                item.get("recommendation_id"),
                item.get("action_id"),
                item.get("reason"),
            )
            for item in skipped
            if isinstance(item, dict)
        ]
        self.assertIn(
            (eligible_id, "ACTION.UTILITY.GAIN", "missing_output_dir"),
            tuples,
        )
        self.assertIn(
            (blocked_id, "ACTION.UTILITY.GAIN", "blocked_by_gates"),
            tuples,
        )
        self.assertEqual(
            tuples,
            sorted(tuples, key=lambda item: (item[0] or "", item[1] or "", item[2] or "")),
        )

    def test_run_renderers_output_metadata_marks_extreme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "renders"
            _write_wav_16bit(stems_dir / "kick.wav")

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.TEST.EXTREME.MANIFEST",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "kick",
                            "file_path": "kick.wav",
                        }
                    ],
                },
                "issues": [],
                "recommendations": [
                    {
                        "recommendation_id": "REC.RENDER.GAIN.NORMAL",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "target": {"scope": "stem", "stem_id": "kick"},
                        "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.0}],
                        "eligible_render": True,
                        "extreme": False,
                    },
                    {
                        "recommendation_id": "REC.RENDER.GAIN.EXTREME",
                        "action_id": "ACTION.UTILITY.GAIN",
                        "risk": "low",
                        "requires_approval": False,
                        "target": {"scope": "stem", "stem_id": "kick"},
                        "params": [{"param_id": "PARAM.GAIN.DB", "value": -2.0}],
                        "eligible_render": True,
                        "extreme": True,
                    },
                ],
            }

            plugins = load_plugins(Path("plugins"))
            manifests = run_renderers(report, plugins, output_dir=out_dir)

            gain_manifest = next(
                (
                    item
                    for item in manifests
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.GAIN_TRIM"
                ),
                None,
            )
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return

            metadata = outputs[0].get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertTrue(metadata.get("extreme"))


if __name__ == "__main__":
    unittest.main()
