import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core import variants as variants_module
from mmo.core.variants import build_variant_plan


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


class TestVariantsRunner(unittest.TestCase):
    def test_build_variant_plan_resolves_slug_collisions_deterministically(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "kick.wav")

            plan = build_variant_plan(
                stems_dir=stems_dir,
                out_dir=out_dir,
                preset_ids=["PRESET.VIBE.WARM_INTIMATE", "PRESET.VIBE.WARM_INTIMATE"],
                config_paths=None,
                cli_run_config_overrides={},
                steps={"analyze": True, "bundle": True},
                presets_dir=repo_root / "presets",
            )

            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list):
                return

            self.assertEqual(
                [item.get("variant_id") for item in variants],
                ["VARIANT.001", "VARIANT.002"],
            )
            self.assertEqual(
                [item.get("variant_slug") for item in variants],
                ["warm", "warm__a"],
            )

    def test_variants_run_two_presets_analyze_and_bundle(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        plan_validator = _schema_validator(repo_root / "schemas" / "variant_plan.schema.json")
        result_validator = _schema_validator(repo_root / "schemas" / "variant_result.schema.json")
        listen_pack_validator = _schema_validator(
            repo_root / "schemas" / "listen_pack.schema.json"
        )
        deliverables_index_validator = _schema_validator(
            repo_root / "schemas" / "deliverables_index.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "variants_out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

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
                    "--preset",
                    "PRESET.VIBE.WARM_INTIMATE",
                    "--bundle",
                    "--listen-pack",
                    "--deliverables-index",
                ]
            )
            self.assertEqual(exit_code, 0)

            plan_path = out_dir / "variant_plan.json"
            result_path = out_dir / "variant_result.json"
            listen_pack_path = out_dir / "listen_pack.json"
            deliverables_index_path = out_dir / "deliverables_index.json"
            self.assertTrue(plan_path.exists())
            self.assertTrue(result_path.exists())
            self.assertTrue(listen_pack_path.exists())
            self.assertTrue(deliverables_index_path.exists())

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            listen_pack = json.loads(listen_pack_path.read_text(encoding="utf-8"))
            deliverables_index = json.loads(deliverables_index_path.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            result_validator.validate(result)
            listen_pack_validator.validate(listen_pack)
            deliverables_index_validator.validate(deliverables_index)
            listen_entries = listen_pack.get("entries")
            self.assertIsInstance(listen_entries, list)
            if isinstance(listen_entries, list):
                self.assertEqual(len(listen_entries), 2)

            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list):
                return
            self.assertEqual(len(variants), 2)

            results = result.get("results")
            self.assertIsInstance(results, list)
            if not isinstance(results, list):
                return
            self.assertEqual(len(results), 2)
            self.assertTrue(
                all(
                    isinstance(item, dict) and item.get("ok") is True
                    for item in results
                )
            )

            seen_presets: set[str] = set()
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_id = variant.get("variant_id")
                variant_slug = variant.get("variant_slug")
                self.assertIsInstance(variant_id, str)
                self.assertIsInstance(variant_slug, str)
                if not isinstance(variant_id, str) or not isinstance(variant_slug, str):
                    continue

                variant_dir = out_dir / f"{variant_id}__{variant_slug}"
                self.assertTrue(variant_dir.exists())

                report_path = variant_dir / "report.json"
                bundle_path = variant_dir / "ui_bundle.json"
                self.assertTrue(report_path.exists())
                self.assertTrue(bundle_path.exists())

                report = json.loads(report_path.read_text(encoding="utf-8"))
                run_config = report.get("run_config")
                self.assertIsInstance(run_config, dict)
                if not isinstance(run_config, dict):
                    continue
                preset_id = run_config.get("preset_id")
                self.assertIsInstance(preset_id, str)
                if not isinstance(preset_id, str):
                    continue
                seen_presets.add(preset_id)

                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    bundle.get("pointers"),
                    {
                        "listen_pack_path": listen_pack_path.resolve().as_posix(),
                        "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                    },
                )
                help_entries = bundle.get("help")
                self.assertIsInstance(help_entries, dict)
                if not isinstance(help_entries, dict):
                    continue
                if preset_id == "PRESET.SAFE_CLEANUP":
                    self.assertIn("HELP.PRESET.SAFE_CLEANUP", help_entries)
                if preset_id == "PRESET.VIBE.WARM_INTIMATE":
                    self.assertIn("HELP.PRESET.VIBE.WARM_INTIMATE", help_entries)

            self.assertEqual(
                seen_presets,
                {"PRESET.SAFE_CLEANUP", "PRESET.VIBE.WARM_INTIMATE"},
            )

    def test_variants_run_with_timeline_embeds_report_timeline_and_bundle_pointer(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "variants_out"
            timeline_path = temp_path / "timeline.json"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")
            timeline_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "sections": [
                            {
                                "id": "SEC.002",
                                "label": "Verse 1",
                                "start_s": 12.0,
                                "end_s": 32.0,
                            },
                            {
                                "id": "SEC.001",
                                "label": "Intro",
                                "start_s": 0.0,
                                "end_s": 12.0,
                            },
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

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
                    "--bundle",
                    "--timeline",
                    str(timeline_path),
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            plan = json.loads((out_dir / "variant_plan.json").read_text(encoding="utf-8"))
            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list) or not variants:
                return
            first = variants[0]
            self.assertIsInstance(first, dict)
            if not isinstance(first, dict):
                return

            variant_id = first.get("variant_id")
            variant_slug = first.get("variant_slug")
            self.assertIsInstance(variant_id, str)
            self.assertIsInstance(variant_slug, str)
            if not isinstance(variant_id, str) or not isinstance(variant_slug, str):
                return

            variant_dir = out_dir / f"{variant_id}__{variant_slug}"
            report_payload = json.loads((variant_dir / "report.json").read_text(encoding="utf-8"))
            bundle_payload = json.loads((variant_dir / "ui_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(
                report_payload.get("timeline"),
                {
                    "schema_version": "0.1.0",
                    "sections": [
                        {
                            "id": "SEC.001",
                            "label": "Intro",
                            "start_s": 0.0,
                            "end_s": 12.0,
                        },
                        {
                            "id": "SEC.002",
                            "label": "Verse 1",
                            "start_s": 12.0,
                            "end_s": 32.0,
                        },
                    ],
                },
            )
            self.assertEqual(
                bundle_payload.get("pointers"),
                {"timeline_path": timeline_path.resolve().as_posix()},
            )

    def test_variants_run_output_formats_propagate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "variants_out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            with mock.patch(
                "mmo.core.variants.run_renderers",
                wraps=variants_module.run_renderers,
            ) as patched_run_renderers:
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
                        "--render",
                        "--apply",
                        "--output-formats",
                        "wav,flac",
                    ]
                )
            self.assertEqual(exit_code, 0)

            plan = json.loads((out_dir / "variant_plan.json").read_text(encoding="utf-8"))
            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list) or not variants:
                return
            overrides = variants[0].get("run_config_overrides")
            self.assertIsInstance(overrides, dict)
            if not isinstance(overrides, dict):
                return
            self.assertEqual(
                overrides.get("render", {}).get("output_formats"),
                ["wav", "flac"],
            )
            self.assertEqual(
                overrides.get("apply", {}).get("output_formats"),
                ["wav", "flac"],
            )
            contexts_and_formats = [
                (
                    call.kwargs.get("context"),
                    call.kwargs.get("output_formats"),
                )
                for call in patched_run_renderers.call_args_list
                if call.kwargs.get("context") in {"render", "auto_apply"}
            ]
            self.assertEqual(
                contexts_and_formats,
                [("render", ["wav", "flac"]), ("auto_apply", ["wav", "flac"])],
            )


if __name__ == "__main__":
    unittest.main()
