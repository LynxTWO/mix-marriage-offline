import json
import contextlib
import io
import math
import os
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


def _write_stereo_wav_16bit(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.1,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    left = [
        int(0.45 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    right = [
        int(0.35 * 32767.0 * math.sin(2.0 * math.pi * 330.0 * index / sample_rate_hz))
        for index in range(frames)
    ]
    interleaved: list[int] = []
    for left_value, right_value in zip(left, right):
        interleaved.extend([left_value, right_value])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _write_multichannel_wav_16bit(
    path: Path,
    *,
    channels: int,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.1,
) -> None:
    frames = int(sample_rate_hz * duration_s)
    interleaved: list[int] = []
    for frame_index in range(frames):
        for channel_index in range(channels):
            frequency = 180.0 + (55.0 * channel_index)
            amplitude = max(0.1, 0.45 - (0.03 * channel_index))
            sample = int(
                amplitude
                * 32767.0
                * math.sin(2.0 * math.pi * frequency * frame_index / sample_rate_hz)
            )
            interleaved.append(sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _mock_render_many_run_variant_plan(
    *,
    out_dir: Path,
    include_stereo_deliverable: bool,
    surround_target_ids: set[str] | None = None,
):
    enabled_surround_targets = set(surround_target_ids or set())
    surround_layouts = {
        "TARGET.SURROUND.5_1": ("LAYOUT.5_1", 6),
        "TARGET.SURROUND.7_1": ("LAYOUT.7_1", 8),
    }

    def _fake_run_variant_plan(
        variant_plan: dict,
        repo_root: Path,
        **_: object,
    ) -> dict:
        source_report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
        results: list[dict[str, object]] = []
        variants = variant_plan.get("variants")
        if not isinstance(variants, list):
            variants = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant_id = str(variant.get("variant_id", "VARIANT.000"))
            variant_slug = str(variant.get("variant_slug", "variant"))
            variant_label = str(variant.get("label", ""))
            variant_dir = out_dir / f"{variant_id}__{variant_slug}"
            variant_dir.mkdir(parents=True, exist_ok=True)

            report_path = variant_dir / "report.json"
            report_path.write_text(
                json.dumps(source_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            render_manifest_path = variant_dir / "render_manifest.json"
            bundle_path = variant_dir / "ui_bundle.json"

            outputs: list[dict[str, object]] = []
            deliverables: list[dict[str, object]] = []
            if include_stereo_deliverable and variant_label == "TARGET.STEREO.2_0":
                stereo_file_path = variant_dir / "render" / "mix.stereo.wav"
                _write_stereo_wav_16bit(stereo_file_path)
                outputs.append(
                    {
                        "output_id": "OUTPUT.STEREO.001",
                        "file_path": "mix.stereo.wav",
                        "format": "wav",
                        "channel_count": 2,
                        "metadata": {
                            "routing_applied": True,
                            "target_layout_id": "LAYOUT.2_0",
                        },
                    }
                )
                deliverables.append(
                    {
                        "deliverable_id": "DELIV.LAYOUT.2_0.2CH",
                        "label": "LAYOUT.2_0 deliverable",
                        "target_layout_id": "LAYOUT.2_0",
                        "channel_count": 2,
                        "formats": ["wav"],
                        "output_ids": ["OUTPUT.STEREO.001"],
                    }
                )
            elif variant_label in enabled_surround_targets and variant_label in surround_layouts:
                target_layout_id, channel_count = surround_layouts[variant_label]
                rendered_name = f"mix.{variant_label.lower().replace('.', '_')}.wav"
                surround_file_path = variant_dir / "render" / rendered_name
                _write_multichannel_wav_16bit(
                    surround_file_path,
                    channels=channel_count,
                )
                output_id = f"OUTPUT.{variant_label}.001"
                outputs.append(
                    {
                        "output_id": output_id,
                        "file_path": rendered_name,
                        "format": "wav",
                        "channel_count": channel_count,
                        "metadata": {
                            "routing_applied": True,
                            "target_layout_id": target_layout_id,
                        },
                    }
                )
                deliverables.append(
                    {
                        "deliverable_id": f"DELIV.{target_layout_id}.{channel_count}CH",
                        "label": f"{target_layout_id} deliverable",
                        "target_layout_id": target_layout_id,
                        "channel_count": channel_count,
                        "formats": ["wav"],
                        "output_ids": [output_id],
                    }
                )

            render_manifest: dict[str, object] = {
                "schema_version": "0.1.0",
                "report_id": str(source_report.get("report_id", "")),
                "renderer_manifests": [
                    {
                        "renderer_id": "PLUGIN.RENDERER.SAFE",
                        "outputs": outputs,
                        "skipped": [],
                    }
                ],
            }
            if deliverables:
                render_manifest["deliverables"] = deliverables
            render_manifest_path.write_text(
                json.dumps(render_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            results.append(
                {
                    "variant_id": variant_id,
                    "out_dir": variant_dir.resolve().as_posix(),
                    "report_path": report_path.resolve().as_posix(),
                    "render_manifest_path": render_manifest_path.resolve().as_posix(),
                    "bundle_path": bundle_path.resolve().as_posix(),
                    "ok": True,
                    "errors": [],
                }
            )

        return {
            "schema_version": "0.1.0",
            "plan": variant_plan,
            "results": results,
        }

    return _fake_run_variant_plan


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
    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        src_dir = str((repo_root / "src").resolve())
        self._original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = (
            src_dir
            if not self._original_pythonpath
            else f"{src_dir}{os.pathsep}{self._original_pythonpath}"
        )

    def tearDown(self) -> None:
        if self._original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
            return
        os.environ["PYTHONPATH"] = self._original_pythonpath

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
                "Stereo (streaming),5.1 (home theater)",
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

    def test_run_render_many_translation_patches_report_and_bundle_deterministically(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        bundle_validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
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
                "Stereo (streaming),5.1 (home theater)",
                "--translation",
                "--translation-audition",
                "--listen-pack",
                "--translation-audition-segment",
                "0.05",
                "--cache",
                "off",
            ]

            with mock.patch(
                "mmo.cli_commands._workflows.run_variant_plan",
                side_effect=_mock_render_many_run_variant_plan(
                    out_dir=out_dir,
                    include_stereo_deliverable=True,
                ),
            ):
                first_exit = main(command)
                self.assertEqual(first_exit, 0)

                report_path = out_dir / "report.json"
                first_report = json.loads(report_path.read_text(encoding="utf-8"))
                first_translation_results = first_report.get("translation_results")
                self.assertIsInstance(first_translation_results, list)
                if not isinstance(first_translation_results, list):
                    return
                self.assertEqual(
                    [
                        item.get("profile_id")
                        for item in first_translation_results
                        if isinstance(item, dict)
                    ],
                    [
                        "TRANS.DEVICE.PHONE",
                        "TRANS.DEVICE.SMALL_SPEAKER",
                        "TRANS.MONO.COLLAPSE",
                    ],
                )
                first_translation_summary = first_report.get("translation_summary")
                self.assertIsInstance(first_translation_summary, list)
                if not isinstance(first_translation_summary, list):
                    return
                self.assertEqual(
                    [
                        item.get("profile_id")
                        for item in first_translation_summary
                        if isinstance(item, dict)
                    ],
                    [
                        "TRANS.DEVICE.PHONE",
                        "TRANS.DEVICE.SMALL_SPEAKER",
                        "TRANS.MONO.COLLAPSE",
                    ],
                )
                self.assertTrue(
                    all(
                        isinstance(item, dict)
                        and item.get("status") in {"pass", "warn", "fail"}
                        and isinstance(item.get("short_reason"), str)
                        and bool(item.get("short_reason"))
                        for item in first_translation_summary
                    )
                )
                audition_manifest_path = (
                    out_dir / "listen_pack" / "translation_auditions" / "manifest.json"
                )
                self.assertTrue(audition_manifest_path.exists())
                first_audition_manifest = json.loads(
                    audition_manifest_path.read_text(encoding="utf-8")
                )
                first_audition_renders = first_audition_manifest.get("renders")
                self.assertIsInstance(first_audition_renders, list)
                if not isinstance(first_audition_renders, list):
                    return
                observed_audition_profiles = sorted(
                    item.get("profile_id")
                    for item in first_audition_renders
                    if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
                )
                self.assertEqual(
                    observed_audition_profiles,
                    [
                        "TRANS.DEVICE.PHONE",
                        "TRANS.DEVICE.SMALL_SPEAKER",
                        "TRANS.MONO.COLLAPSE",
                    ],
                )
                for item in first_audition_renders:
                    if not isinstance(item, dict):
                        continue
                    rendered_path = item.get("path")
                    self.assertIsInstance(rendered_path, str)
                    if isinstance(rendered_path, str):
                        self.assertTrue(Path(rendered_path).exists())

                listen_pack_path = out_dir / "listen_pack.json"
                self.assertTrue(listen_pack_path.exists())
                first_listen_pack = json.loads(listen_pack_path.read_text(encoding="utf-8"))
                first_translation_auditions = first_listen_pack.get("translation_auditions")
                self.assertIsInstance(first_translation_auditions, dict)
                if not isinstance(first_translation_auditions, dict):
                    return
                self.assertEqual(
                    first_translation_auditions.get("manifest_path"),
                    "listen_pack/translation_auditions/manifest.json",
                )
                self.assertEqual(
                    first_translation_auditions.get("segment"),
                    {"start_s": 0.0, "end_s": 0.05},
                )
                index_renders = first_translation_auditions.get("renders")
                self.assertIsInstance(index_renders, list)
                if not isinstance(index_renders, list):
                    return
                self.assertEqual(
                    [
                        item.get("profile_id")
                        for item in index_renders
                        if isinstance(item, dict)
                    ],
                    [
                        "TRANS.DEVICE.PHONE",
                        "TRANS.DEVICE.SMALL_SPEAKER",
                        "TRANS.MONO.COLLAPSE",
                    ],
                )
                self.assertTrue(
                    all(
                        isinstance(item, dict)
                        and isinstance(item.get("path"), str)
                        and item.get("path", "").startswith("listen_pack/translation_auditions/")
                        and "\\" not in item.get("path", "")
                        for item in index_renders
                    )
                )

                variant_result = json.loads(
                    (out_dir / "variant_result.json").read_text(encoding="utf-8")
                )
                plan = variant_result.get("plan")
                plan_variants = (
                    {
                        item.get("variant_id"): item
                        for item in plan.get("variants", [])
                        if isinstance(item, dict) and isinstance(item.get("variant_id"), str)
                    }
                    if isinstance(plan, dict)
                    else {}
                )
                results = variant_result.get("results")
                self.assertIsInstance(results, list)
                if not isinstance(results, list):
                    return
                stereo_result = next(
                    (
                        item
                        for item in results
                        if isinstance(item, dict)
                        and isinstance(item.get("variant_id"), str)
                        and isinstance(plan_variants.get(item["variant_id"]), dict)
                        and plan_variants[item["variant_id"]].get("label")
                        == "TARGET.STEREO.2_0"
                    ),
                    None,
                )
                self.assertIsInstance(stereo_result, dict)
                if not isinstance(stereo_result, dict):
                    return
                stereo_bundle_path_value = stereo_result.get("bundle_path")
                self.assertIsInstance(stereo_bundle_path_value, str)
                if not isinstance(stereo_bundle_path_value, str):
                    return
                stereo_bundle_path = Path(stereo_bundle_path_value)
                self.assertTrue(stereo_bundle_path.exists())
                stereo_bundle = json.loads(stereo_bundle_path.read_text(encoding="utf-8"))
                bundle_validator.validate(stereo_bundle)
                self.assertEqual(
                    stereo_bundle.get("translation_results"),
                    first_translation_results,
                )
                self.assertEqual(
                    stereo_bundle.get("translation_summary"),
                    first_translation_summary,
                )
                self.assertEqual(
                    stereo_bundle.get("translation_auditions"),
                    first_translation_auditions,
                )

                second_exit = main(command)
                self.assertEqual(second_exit, 0)
                second_report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    second_report.get("translation_results"),
                    first_translation_results,
                )
                self.assertEqual(
                    second_report.get("translation_summary"),
                    first_translation_summary,
                )
                second_audition_manifest = json.loads(
                    audition_manifest_path.read_text(encoding="utf-8")
                )
                self.assertEqual(second_audition_manifest, first_audition_manifest)
                second_listen_pack = json.loads(listen_pack_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    second_listen_pack.get("translation_auditions"),
                    first_translation_auditions,
                )

    def test_run_render_many_translation_uses_downmix_fallback_when_stereo_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
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
                "5.1 (home theater)",
                "--translation",
                "--cache",
                "off",
            ]
            with mock.patch(
                "mmo.cli_commands._workflows.run_variant_plan",
                side_effect=_mock_render_many_run_variant_plan(
                    out_dir=out_dir,
                    include_stereo_deliverable=False,
                    surround_target_ids={"TARGET.SURROUND.5_1"},
                ),
            ):
                first_exit_code = main(command)
                self.assertEqual(first_exit_code, 0)

                report_path = out_dir / "report.json"
                first_report = json.loads(report_path.read_text(encoding="utf-8"))
                first_translation_results = first_report.get("translation_results")
                self.assertIsInstance(first_translation_results, list)
                if not isinstance(first_translation_results, list):
                    return
                self.assertGreater(len(first_translation_results), 0)
                first_translation_reference = first_report.get("translation_reference")
                self.assertIsInstance(first_translation_reference, dict)
                if not isinstance(first_translation_reference, dict):
                    return
                self.assertEqual(
                    first_translation_reference.get("source_target_id"),
                    "TARGET.SURROUND.5_1",
                )
                self.assertEqual(first_translation_reference.get("method"), "downmix_fallback")
                self.assertEqual(first_translation_reference.get("source_channels"), 6)
                self.assertEqual(
                    first_translation_reference.get("audio_path"),
                    "translation_reference/translation_reference.stereo.wav",
                )

                first_audio_rel_path = first_translation_reference.get("audio_path")
                self.assertIsInstance(first_audio_rel_path, str)
                if not isinstance(first_audio_rel_path, str):
                    return
                first_audio_path = out_dir / first_audio_rel_path
                self.assertTrue(first_audio_path.exists())
                first_audio_bytes = first_audio_path.read_bytes()

                second_exit_code = main(command)
                self.assertEqual(second_exit_code, 0)

                second_report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    second_report.get("translation_results"),
                    first_translation_results,
                )
                self.assertEqual(
                    second_report.get("translation_summary"),
                    first_report.get("translation_summary"),
                )
                self.assertEqual(
                    second_report.get("translation_reference"),
                    first_translation_reference,
                )
                self.assertEqual(first_audio_path.read_bytes(), first_audio_bytes)

    def test_run_render_many_translation_prefers_7_1_when_5_1_and_7_1_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            with mock.patch(
                "mmo.cli_commands._workflows.run_variant_plan",
                side_effect=_mock_render_many_run_variant_plan(
                    out_dir=out_dir,
                    include_stereo_deliverable=False,
                    surround_target_ids={"TARGET.SURROUND.5_1", "TARGET.SURROUND.7_1"},
                ),
            ):
                exit_code = main(
                    [
                        "run",
                        "--stems",
                        str(stems_dir),
                        "--out",
                        str(out_dir),
                        "--preset",
                        "PRESET.SAFE_CLEANUP",
                        "--render-many",
                        "--targets",
                        "5.1 (home theater),7.1 (cinematic)",
                        "--translation",
                        "--cache",
                        "off",
                    ]
                )
            self.assertEqual(exit_code, 0)

            report_payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            translation_reference = report_payload.get("translation_reference")
            self.assertIsInstance(translation_reference, dict)
            if not isinstance(translation_reference, dict):
                return
            self.assertEqual(
                translation_reference.get("source_target_id"),
                "TARGET.SURROUND.7_1",
            )
            self.assertEqual(translation_reference.get("method"), "downmix_fallback")
            self.assertEqual(translation_reference.get("source_channels"), 8)

    def test_run_render_many_translation_soft_skips_when_no_audio_deliverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            with mock.patch(
                "mmo.cli_commands._workflows.run_variant_plan",
                side_effect=_mock_render_many_run_variant_plan(
                    out_dir=out_dir,
                    include_stereo_deliverable=False,
                ),
            ):
                exit_code = main(
                    [
                        "run",
                        "--stems",
                        str(stems_dir),
                        "--out",
                        str(out_dir),
                        "--preset",
                        "PRESET.SAFE_CLEANUP",
                        "--render-many",
                        "--targets",
                        "5.1 (home theater)",
                        "--translation",
                        "--translation-audition",
                        "--listen-pack",
                        "--cache",
                        "off",
                    ]
                )
            self.assertEqual(exit_code, 0)

            report_payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            self.assertNotIn("translation_results", report_payload)
            self.assertNotIn("translation_reference", report_payload)

            listen_pack_path = out_dir / "listen_pack.json"
            self.assertTrue(listen_pack_path.exists())
            listen_pack_payload = json.loads(listen_pack_path.read_text(encoding="utf-8"))
            self.assertNotIn("translation_auditions", listen_pack_payload)

            variant_result_payload = json.loads(
                (out_dir / "variant_result.json").read_text(encoding="utf-8")
            )
            results = variant_result_payload.get("results")
            self.assertIsInstance(results, list)
            if not isinstance(results, list):
                return
            for item in results:
                if not isinstance(item, dict):
                    continue
                bundle_path = item.get("bundle_path")
                self.assertIsInstance(bundle_path, str)
                if not isinstance(bundle_path, str):
                    continue
                bundle_file = Path(bundle_path)
                if not bundle_file.exists():
                    continue
                bundle_payload = json.loads(bundle_file.read_text(encoding="utf-8"))
                self.assertNotIn("translation_auditions", bundle_payload)

    def test_run_render_many_applies_scene_templates_before_render_plan_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            captured_scene_payload: dict[str, object] = {}
            original_build_render_plan = main.__globals__["_build_validated_render_plan_payload"]

            def _capture_render_plan_call(*args: object, **kwargs: object) -> dict[str, object]:
                scene_payload = kwargs.get("scene_payload")
                if isinstance(scene_payload, dict):
                    captured_scene_payload["scene_payload"] = json.loads(
                        json.dumps(scene_payload)
                    )
                return original_build_render_plan(*args, **kwargs)

            with mock.patch(
                "mmo.cli_commands._workflows._build_validated_render_plan_payload",
                side_effect=_capture_render_plan_call,
            ):
                exit_code = main(
                    [
                        "run",
                        "--stems",
                        str(stems_dir),
                        "--out",
                        str(out_dir),
                        "--preset",
                        "PRESET.SAFE_CLEANUP",
                        "--render-many",
                        "--targets",
                        "Stereo (streaming)",
                        "--scene-templates",
                        "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                        "--cache",
                        "off",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("scene_payload", captured_scene_payload)
            captured_scene = captured_scene_payload["scene_payload"]
            self.assertIsInstance(captured_scene, dict)
            if not isinstance(captured_scene, dict):
                return

            objects = captured_scene.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list):
                return
            self.assertGreaterEqual(len(objects), 1)
            for item in objects:
                if not isinstance(item, dict):
                    continue
                intent = item.get("intent")
                self.assertIsInstance(intent, dict)
                if not isinstance(intent, dict):
                    continue
                self.assertEqual(intent.get("width"), 0.6)
                self.assertEqual(intent.get("depth"), 0.4)
                self.assertEqual(intent.get("loudness_bias"), "neutral")
                self.assertEqual(intent.get("locks"), [])

            scene_path = out_dir / "scene.json"
            self.assertTrue(scene_path.exists())
            scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
            scene_objects = scene_payload.get("objects")
            self.assertIsInstance(scene_objects, list)


if __name__ == "__main__":
    unittest.main()
