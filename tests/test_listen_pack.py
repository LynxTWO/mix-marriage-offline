import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.listen_pack import build_listen_pack


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
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


def _variant_steps_payload() -> dict[str, Any]:
    return {
        "analyze": True,
        "export_pdf": False,
        "export_csv": False,
        "apply": False,
        "render": False,
        "bundle": True,
    }


def _build_fake_variant_result(temp_path: Path, *, first_risk: str) -> dict[str, Any]:
    out_root = temp_path / "variants_out"
    stems_dir = temp_path / "stems"
    variant_one_dir = out_root / "VARIANT.001__warm__wavonly"
    variant_two_dir = out_root / "VARIANT.002__safe_cleanup__lossless"

    report_one_path = variant_one_dir / "report.json"
    report_two_path = variant_two_dir / "report.json"
    bundle_one_path = variant_one_dir / "ui_bundle.json"
    bundle_two_path = variant_two_dir / "ui_bundle.json"

    report_one = {
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": "PROFILE.ASSIST",
            "preset_id": "PRESET.VIBE.WARM_INTIMATE",
        },
        "vibe_signals": {
            "density_level": "low",
            "masking_level": "low",
            "translation_risk": first_risk,
            "notes": [],
        },
    }
    report_two = {
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": "PROFILE.ASSIST",
            "preset_id": "PRESET.SAFE_CLEANUP",
        },
        "vibe_signals": {
            "density_level": "low",
            "masking_level": "low",
            "translation_risk": "low",
            "notes": [],
        },
    }
    bundle_one = {
        "dashboard": {
            "profile_id": "PROFILE.ASSIST",
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "low",
                "translation_risk": first_risk,
                "notes": [],
            },
        }
    }
    bundle_two = {
        "dashboard": {
            "profile_id": "PROFILE.ASSIST",
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "low",
                "translation_risk": "low",
                "notes": [],
            },
        }
    }

    _write_json(report_one_path, report_one)
    _write_json(report_two_path, report_two)
    _write_json(bundle_one_path, bundle_one)
    _write_json(bundle_two_path, bundle_two)

    return {
        "schema_version": "0.1.0",
        "plan": {
            "schema_version": "0.1.0",
            "stems_dir": stems_dir.resolve().as_posix(),
            "base_run_config": {
                "schema_version": "0.1.0",
                "profile_id": "PROFILE.ASSIST",
            },
            "variants": [
                {
                    "variant_id": "VARIANT.001",
                    "variant_slug": "warm__wavonly",
                    "label": "PRESET.VIBE.WARM_INTIMATE [wavonly]",
                    "preset_id": "PRESET.VIBE.WARM_INTIMATE",
                    "steps": _variant_steps_payload(),
                },
                {
                    "variant_id": "VARIANT.002",
                    "variant_slug": "safe_cleanup__lossless",
                    "label": "PRESET.SAFE_CLEANUP [lossless]",
                    "preset_id": "PRESET.SAFE_CLEANUP",
                    "steps": _variant_steps_payload(),
                },
            ],
        },
        "results": [
            {
                "variant_id": "VARIANT.002",
                "out_dir": variant_two_dir.resolve().as_posix(),
                "report_path": report_two_path.resolve().as_posix(),
                "bundle_path": bundle_two_path.resolve().as_posix(),
                "ok": True,
                "errors": [],
            },
            {
                "variant_id": "VARIANT.001",
                "out_dir": variant_one_dir.resolve().as_posix(),
                "report_path": report_one_path.resolve().as_posix(),
                "bundle_path": bundle_one_path.resolve().as_posix(),
                "ok": True,
                "errors": [],
            },
        ],
    }


class TestListenPack(unittest.TestCase):
    def test_build_listen_pack_schema_valid_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "listen_pack.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            variant_result = _build_fake_variant_result(temp_path, first_risk="low")

            first = build_listen_pack(variant_result, repo_root / "presets")
            second = build_listen_pack(variant_result, repo_root / "presets")

            validator.validate(first)
            self.assertEqual(first, second)

            entries = first.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list):
                return

            self.assertEqual(
                [item.get("variant_id") for item in entries],
                [
                    "VARIANT.001__warm__wavonly",
                    "VARIANT.002__safe_cleanup__lossless",
                ],
            )
            self.assertEqual(
                [item.get("label") for item in entries],
                ["Warm intimate (wavonly)", "Safe cleanup (lossless)"],
            )
            self.assertEqual(
                [item.get("audition_order") for item in entries],
                [1, 2],
            )

    def test_variants_listen_pack_cli_command(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "listen_pack.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            variant_result = _build_fake_variant_result(temp_path, first_risk="high")
            variant_result_path = temp_path / "variant_result.json"
            out_path = temp_path / "listen_pack.json"
            _write_json(variant_result_path, variant_result)

            exit_code = main(
                [
                    "variants",
                    "listen-pack",
                    "--variant-result",
                    str(variant_result_path),
                    "--out",
                    str(out_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            entries = payload.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list):
                return
            order_by_variant = {
                item.get("variant_id"): item.get("audition_order")
                for item in entries
                if isinstance(item, dict)
            }
            self.assertEqual(order_by_variant.get("VARIANT.002__safe_cleanup__lossless"), 1)
            self.assertEqual(order_by_variant.get("VARIANT.001__warm__wavonly"), 2)


if __name__ == "__main__":
    unittest.main()
