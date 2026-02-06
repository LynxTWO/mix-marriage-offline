import json
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.routing import build_routing_plan


class TestRoutingPlan(unittest.TestCase):
    def _schema_validator(self, schema_path: Path) -> jsonschema.Draft202012Validator:
        registry = Registry()
        for candidate in sorted(schema_path.parent.glob("*.schema.json")):
            schema = json.loads(candidate.read_text(encoding="utf-8"))
            resource = Resource.from_contents(schema, default_specification=DRAFT202012)
            registry = registry.with_resource(candidate.resolve().as_uri(), resource)
            schema_id = schema.get("$id")
            if isinstance(schema_id, str) and schema_id:
                registry = registry.with_resource(schema_id, resource)
        root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return jsonschema.Draft202012Validator(root_schema, registry=registry)

    def test_build_routing_plan_identity_when_channel_counts_match(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "stem_51",
                    "file_path": "stem_51.wav",
                    "channel_count": 6,
                }
            ]
        }
        plan = build_routing_plan(
            session,
            source_layout_id="LAYOUT.5_1",
            target_layout_id="LAYOUT.5_1",
        )

        route = plan["routes"][0]
        self.assertEqual(route["stem_id"], "stem_51")
        self.assertEqual(route["stem_channels"], 6)
        self.assertEqual(route["target_channels"], 6)
        self.assertEqual(route["notes"], [])
        self.assertEqual(
            route["mapping"],
            [
                {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
                {"src_ch": 2, "dst_ch": 2, "gain_db": 0.0},
                {"src_ch": 3, "dst_ch": 3, "gain_db": 0.0},
                {"src_ch": 4, "dst_ch": 4, "gain_db": 0.0},
                {"src_ch": 5, "dst_ch": 5, "gain_db": 0.0},
            ],
        )

    def test_build_routing_plan_mono_to_stereo_uses_minus_3db_on_lr(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "lead_vox",
                    "file_path": "lead_vox.wav",
                    "channel_count": 1,
                }
            ]
        }
        plan = build_routing_plan(
            session,
            source_layout_id="LAYOUT.1_0",
            target_layout_id="LAYOUT.2_0",
        )

        route = plan["routes"][0]
        self.assertEqual(route["mapping"], [
            {"src_ch": 0, "dst_ch": 0, "gain_db": -3.0},
            {"src_ch": 0, "dst_ch": 1, "gain_db": -3.0},
        ])
        self.assertIn("Mono routed equally to L/R at -3.0 dB each", route["notes"])

    def test_build_routing_plan_stereo_to_surround_front_only(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "music_bus",
                    "file_path": "music_bus.wav",
                    "channel_count": 2,
                }
            ]
        }
        plan = build_routing_plan(
            session,
            source_layout_id="LAYOUT.2_0",
            target_layout_id="LAYOUT.7_1",
        )

        route = plan["routes"][0]
        self.assertEqual(route["target_channels"], 8)
        self.assertEqual(
            route["mapping"],
            [
                {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
            ],
        )
        self.assertIn("Stereo routed to front L/R only", route["notes"])

    def test_build_routing_plan_unknown_mapping_is_empty_and_safe(self) -> None:
        session = {
            "stems": [
                {
                    "stem_id": "stem_51",
                    "file_path": "stem_51.wav",
                    "channel_count": 6,
                }
            ]
        }
        plan = build_routing_plan(
            session,
            source_layout_id="LAYOUT.5_1",
            target_layout_id="LAYOUT.2_0",
        )

        route = plan["routes"][0]
        self.assertEqual(route["mapping"], [])
        self.assertEqual(route["notes"], ["No safe default mapping"])

    def test_build_routing_plan_is_deterministic_and_schema_valid(self) -> None:
        session = {
            "stems": [
                {"stem_id": "zeta", "file_path": "zeta.wav", "channel_count": 2},
                {"stem_id": "alpha", "file_path": "alpha.wav", "channel_count": 1},
                {"stem_id": "beta", "file_path": "beta.wav", "channel_count": 6},
            ]
        }
        first = build_routing_plan(
            session,
            source_layout_id="LAYOUT.5_1",
            target_layout_id="LAYOUT.2_0",
        )
        second = build_routing_plan(
            session,
            source_layout_id="LAYOUT.5_1",
            target_layout_id="LAYOUT.2_0",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [route["stem_id"] for route in first["routes"]],
            ["alpha", "beta", "zeta"],
        )

        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas" / "routing_plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schema).validate(first)

    def test_report_schema_accepts_optional_routing_plan(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report_validator = self._schema_validator(repo_root / "schemas" / "report.schema.json")
        routing_plan = build_routing_plan(
            {
                "stems": [
                    {
                        "stem_id": "lead_vox",
                        "file_path": "lead_vox.wav",
                        "channel_count": 1,
                    }
                ]
            },
            source_layout_id="LAYOUT.1_0",
            target_layout_id="LAYOUT.2_0",
        )
        report_payload = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.ROUTING",
            "project_id": "PROJECT.ROUTING",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [],
            "routing_plan": routing_plan,
        }
        report_validator.validate(report_payload)


if __name__ == "__main__":
    unittest.main()
