import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

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
        "routing": True,
        "downmix_qa": True,
        "export_pdf": False,
        "export_csv": False,
        "apply": False,
        "render": False,
        "bundle": False,
    }


class TestVariantsSurroundReady(unittest.TestCase):
    def test_listen_pack_notes_include_routing_and_downmix_qa_summary(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_root = temp_path / "variants_out"
            variant_dir = out_root / "VARIANT.001__safe_cleanup"
            report_path = variant_dir / "report.json"

            report_payload = {
                "run_config": {
                    "schema_version": "0.1.0",
                    "profile_id": "PROFILE.ASSIST",
                    "preset_id": "PRESET.SAFE_CLEANUP",
                },
                "routing_plan": {
                    "schema_version": "0.1.0",
                    "source_layout_id": "LAYOUT.5_1",
                    "target_layout_id": "LAYOUT.2_0",
                    "routes": [],
                },
                "downmix_qa": {
                    "issues": [
                        {
                            "issue_id": "ISSUE.DOWNMIX.QA.LUFS_MISMATCH",
                            "severity": 60,
                            "message": "Mismatch",
                        }
                    ],
                    "measurements": [
                        {
                            "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                            "value": 1.2,
                            "unit_id": "UNIT.LUFS",
                        },
                        {
                            "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                            "value": -0.4,
                            "unit_id": "UNIT.DBTP",
                        },
                        {
                            "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                            "value": -0.03,
                            "unit_id": "UNIT.CORRELATION",
                        },
                    ],
                },
            }
            _write_json(report_path, report_payload)

            variant_result = {
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
                            "variant_slug": "safe_cleanup",
                            "label": "PRESET.SAFE_CLEANUP",
                            "preset_id": "PRESET.SAFE_CLEANUP",
                            "source_layout_id": "LAYOUT.5_1",
                            "target_layout_id": "LAYOUT.2_0",
                            "qa_ref_path": (temp_path / "ref.wav").resolve().as_posix(),
                            "qa_meters": "truth",
                            "qa_max_seconds": 60.0,
                            "steps": _variant_steps_payload(),
                        }
                    ],
                },
                "results": [
                    {
                        "variant_id": "VARIANT.001",
                        "out_dir": variant_dir.resolve().as_posix(),
                        "report_path": report_path.resolve().as_posix(),
                        "ok": True,
                        "errors": [],
                    }
                ],
            }

            listen_pack = build_listen_pack(variant_result, repo_root / "presets")
            entries = listen_pack.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list) or not entries:
                return

            notes = entries[0].get("notes")
            self.assertIsInstance(notes, list)
            if not isinstance(notes, list):
                return
            self.assertLessEqual(len(notes), 3)
            self.assertTrue(
                any(
                    note == "Routing plan: LAYOUT.5_1 -> LAYOUT.2_0 (safe mapping)"
                    for note in notes
                    if isinstance(note, str)
                )
            )
            qa_lines = [
                note
                for note in notes
                if isinstance(note, str) and note.startswith("Downmix QA:")
            ]
            self.assertEqual(len(qa_lines), 1)
            qa_line = qa_lines[0]
            self.assertIn("issues present", qa_line)
            self.assertIn("LUFS Δ", qa_line)
            self.assertIn("TP Δ", qa_line)
            self.assertIn("Corr", qa_line)

    def test_variants_run_cli_emits_schema_valid_surround_ready_plan(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "variant_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "variants_out"
            qa_ref = temp_path / "reference.wav"
            stems_dir.mkdir(parents=True, exist_ok=True)
            qa_ref.write_bytes(b"")

            def _fake_run_variant_plan(
                plan: dict[str, Any],
                repo_root: Path,
                *,
                cache_enabled: bool = True,
                cache_dir: Path | None = None,
            ) -> dict[str, Any]:
                del repo_root, cache_enabled, cache_dir
                variants = plan.get("variants")
                if not isinstance(variants, list):
                    variants = []
                results: list[dict[str, Any]] = []
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    variant_id = str(variant.get("variant_id") or "VARIANT.000")
                    variant_slug = str(variant.get("variant_slug") or "variant")
                    variant_out_dir = out_dir / f"{variant_id}__{variant_slug}"
                    report_path = variant_out_dir / "report.json"
                    results.append(
                        {
                            "variant_id": variant_id,
                            "out_dir": variant_out_dir.resolve().as_posix(),
                            "report_path": report_path.resolve().as_posix(),
                            "ok": True,
                            "errors": [],
                        }
                    )
                return {
                    "schema_version": "0.1.0",
                    "plan": plan,
                    "results": results,
                }

            with mock.patch("mmo.cli.run_variant_plan", side_effect=_fake_run_variant_plan):
                exit_code = main(
                    [
                        "variants",
                        "run",
                        "--stems",
                        str(stems_dir),
                        "--out",
                        str(out_dir),
                        "--preset",
                        "PRESET.SAFE_CLEANUP",
                        "--routing",
                        "--source-layout",
                        "LAYOUT.5_1",
                        "--target-layout",
                        "LAYOUT.2_0",
                        "--downmix-qa",
                        "--qa-ref",
                        str(qa_ref),
                        "--qa-meters",
                        "basic",
                        "--qa-max-seconds",
                        "45",
                        "--cache",
                        "off",
                    ]
                )
            self.assertEqual(exit_code, 0)

            plan = json.loads((out_dir / "variant_plan.json").read_text(encoding="utf-8"))
            validator.validate(plan)
            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list) or not variants:
                return
            variant = variants[0]
            self.assertIsInstance(variant, dict)
            if not isinstance(variant, dict):
                return

            steps = variant.get("steps")
            self.assertIsInstance(steps, dict)
            if isinstance(steps, dict):
                self.assertIs(steps.get("routing"), True)
                self.assertIs(steps.get("downmix_qa"), True)

            self.assertEqual(variant.get("source_layout_id"), "LAYOUT.5_1")
            self.assertEqual(variant.get("target_layout_id"), "LAYOUT.2_0")
            self.assertEqual(variant.get("qa_meters"), "basic")
            self.assertEqual(variant.get("qa_max_seconds"), 45.0)
            qa_ref_path = variant.get("qa_ref_path")
            self.assertIsInstance(qa_ref_path, str)
            if isinstance(qa_ref_path, str):
                self.assertTrue(qa_ref_path.endswith("/reference.wav"))
                self.assertNotIn("\\", qa_ref_path)


if __name__ == "__main__":
    unittest.main()
