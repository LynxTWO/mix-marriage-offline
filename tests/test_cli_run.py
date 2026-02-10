import json
import contextlib
import io
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd


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


class TestCliRun(unittest.TestCase):
    def test_run_writes_report_csv_and_bundle(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report_validator = _schema_validator(repo_root / "schemas" / "report.schema.json")
        bundle_validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            exit_code = main(
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--export-csv",
                    "--bundle",
                    "--deliverables-index",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            report_path = out_dir / "report.json"
            csv_path = out_dir / "recall.csv"
            bundle_path = out_dir / "ui_bundle.json"
            deliverables_index_path = out_dir / "deliverables_index.json"
            self.assertTrue(report_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(bundle_path.exists())
            self.assertTrue(deliverables_index_path.exists())

            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            report_validator.validate(report_payload)
            bundle_validator.validate(bundle_payload)
            self.assertEqual(
                bundle_payload.get("pointers"),
                {"deliverables_index_path": deliverables_index_path.resolve().as_posix()},
            )

    def test_run_with_timeline_includes_report_timeline_and_bundle_pointer(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report_validator = _schema_validator(repo_root / "schemas" / "report.schema.json")
        bundle_validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
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
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--timeline",
                    str(timeline_path),
                    "--bundle",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            report_path = out_dir / "report.json"
            bundle_path = out_dir / "ui_bundle.json"
            self.assertTrue(report_path.exists())
            self.assertTrue(bundle_path.exists())

            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            report_validator.validate(report_payload)
            bundle_validator.validate(bundle_payload)
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

    def test_run_with_scene_writes_scene_and_bundle_pointer(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        scene_validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")
        bundle_validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            exit_code = main(
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--bundle",
                    "--scene",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            scene_path = out_dir / "scene.json"
            bundle_path = out_dir / "ui_bundle.json"
            self.assertTrue(scene_path.exists())
            self.assertTrue(bundle_path.exists())

            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            scene_validator.validate(scene_payload)
            bundle_validator.validate(bundle_payload)
            self.assertEqual(
                bundle_payload.get("pointers"),
                {"scene_path": scene_path.resolve().as_posix()},
            )

    def test_run_with_scene_and_render_plan_writes_bundle_pointers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        scene_validator = _schema_validator(repo_root / "schemas" / "scene.schema.json")
        render_plan_validator = _schema_validator(
            repo_root / "schemas" / "render_plan.schema.json"
        )
        bundle_validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            exit_code = main(
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--bundle",
                    "--scene",
                    "--render-plan",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            scene_path = out_dir / "scene.json"
            render_plan_path = out_dir / "render_plan.json"
            bundle_path = out_dir / "ui_bundle.json"
            self.assertTrue(scene_path.exists())
            self.assertTrue(render_plan_path.exists())
            self.assertTrue(bundle_path.exists())

            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            render_plan_payload = json.loads(render_plan_path.read_text(encoding="utf-8"))
            bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            scene_validator.validate(scene_payload)
            render_plan_validator.validate(render_plan_payload)
            bundle_validator.validate(bundle_payload)
            self.assertEqual(
                bundle_payload.get("pointers"),
                {
                    "scene_path": scene_path.resolve().as_posix(),
                    "render_plan_path": render_plan_path.resolve().as_posix(),
                },
            )

    def test_run_apply_and_render_write_schema_valid_manifests(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        repo_root = Path(__file__).resolve().parents[1]
        report_validator = _schema_validator(repo_root / "schemas" / "report.schema.json")
        apply_validator = _schema_validator(repo_root / "schemas" / "apply_manifest.schema.json")
        render_validator = _schema_validator(repo_root / "schemas" / "render_manifest.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            exit_code = main(
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--apply",
                    "--render",
                    "--output-formats",
                    "wav",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            apply_manifest_path = out_dir / "apply_manifest.json"
            applied_report_path = out_dir / "applied_report.json"
            render_manifest_path = out_dir / "render_manifest.json"
            self.assertTrue(apply_manifest_path.exists())
            self.assertTrue(applied_report_path.exists())
            self.assertTrue(render_manifest_path.exists())

            apply_manifest = json.loads(apply_manifest_path.read_text(encoding="utf-8"))
            applied_report = json.loads(applied_report_path.read_text(encoding="utf-8"))
            render_manifest = json.loads(render_manifest_path.read_text(encoding="utf-8"))
            apply_validator.validate(apply_manifest)
            report_validator.validate(applied_report)
            render_validator.validate(render_manifest)

    def test_run_delegates_to_variants_when_multiple_presets_are_given(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        variant_plan_validator = _schema_validator(
            repo_root / "schemas" / "variant_plan.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            exit_code = main(
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(out_dir),
                    "--preset",
                    "PRESET.SAFE_CLEANUP",
                    "--preset",
                    "PRESET.VIBE.WARM_INTIMATE",
                    "--cache",
                    "off",
                ]
            )
            self.assertEqual(exit_code, 0)

            variant_plan_path = out_dir / "variant_plan.json"
            self.assertTrue(variant_plan_path.exists())
            variant_plan_payload = json.loads(variant_plan_path.read_text(encoding="utf-8"))
            variant_plan_validator.validate(variant_plan_payload)

    def test_run_render_many_builds_variants_and_reuses_cache(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        variant_plan_validator = _schema_validator(
            repo_root / "schemas" / "variant_plan.schema.json"
        )
        variant_result_validator = _schema_validator(
            repo_root / "schemas" / "variant_result.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            cache_dir = temp_path / ".cache"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            command = [
                "run",
                "--stems",
                str(stems_dir),
                "--out",
                str(out_dir),
                "--preset",
                "PRESET.SAFE_CLEANUP",
                "--render-many",
                "--targets",
                "TARGET.STEREO.2_0,TARGET.SURROUND.5_1",
                "--deliverables-index",
                "--cache",
                "on",
                "--cache-dir",
                str(cache_dir),
            ]

            stdout_first = io.StringIO()
            with contextlib.redirect_stdout(stdout_first):
                first_exit = main(command)
            self.assertEqual(first_exit, 0)

            scene_path = out_dir / "scene.json"
            render_plan_path = out_dir / "render_plan.json"
            variant_plan_path = out_dir / "variant_plan.json"
            variant_result_path = out_dir / "variant_result.json"
            deliverables_index_path = out_dir / "deliverables_index.json"
            self.assertTrue(scene_path.exists())
            self.assertTrue(render_plan_path.exists())
            self.assertTrue(variant_plan_path.exists())
            self.assertTrue(variant_result_path.exists())
            self.assertTrue(deliverables_index_path.exists())

            variant_plan_payload = json.loads(variant_plan_path.read_text(encoding="utf-8"))
            variant_result_payload = json.loads(variant_result_path.read_text(encoding="utf-8"))
            variant_plan_validator.validate(variant_plan_payload)
            variant_result_validator.validate(variant_result_payload)

            variants = variant_plan_payload.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list):
                return
            self.assertEqual(len(variants), 2)
            self.assertEqual(
                [item.get("label") for item in variants if isinstance(item, dict)],
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )

            results = variant_result_payload.get("results")
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
            for item in results:
                if not isinstance(item, dict):
                    continue
                bundle_path = item.get("bundle_path")
                self.assertIsInstance(bundle_path, str)
                if isinstance(bundle_path, str):
                    self.assertTrue(Path(bundle_path).exists())

            stdout_second = io.StringIO()
            with contextlib.redirect_stdout(stdout_second):
                second_exit = main(command)
            self.assertEqual(second_exit, 0)
            self.assertIn("analysis cache: hit", stdout_second.getvalue())


if __name__ == "__main__":
    unittest.main()
