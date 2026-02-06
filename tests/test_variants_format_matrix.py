import contextlib
import io
import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any
from unittest import mock

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


def _build_scan_report(stems_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.VARIANTS.FORMAT_MATRIX.001",
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": "kick",
                    "file_path": "drums/kick.wav",
                }
            ],
        },
        "issues": [],
        "recommendations": [
            {
                "recommendation_id": "REC.TEST.GAIN.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -2.0}],
                "eligible_auto_apply": True,
                "eligible_render": True,
            }
        ],
    }


def _manifest_outputs(manifest_path: Path, output_root: Path) -> list[tuple[str, Path]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs_with_paths: list[tuple[str, Path]] = []
    renderer_manifests = payload.get("renderer_manifests")
    if not isinstance(renderer_manifests, list):
        return outputs_with_paths
    for renderer_manifest in renderer_manifests:
        if not isinstance(renderer_manifest, dict):
            continue
        outputs = renderer_manifest.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            output_format = output.get("format")
            file_path = output.get("file_path")
            if not isinstance(output_format, str) or not isinstance(file_path, str):
                continue
            outputs_with_paths.append((output_format, output_root / Path(file_path)))
    return outputs_with_paths


class TestVariantsFormatMatrix(unittest.TestCase):
    def test_variants_format_sets_expand_and_reuse_cache(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "variants_out"
            cache_dir = temp_path / ".mmo_cache"
            _write_wav_16bit(stems_dir / "drums" / "kick.wav")

            def _scan_builder(*args: object, **kwargs: object) -> dict[str, Any]:
                return _build_scan_report(stems_dir)

            stdout_capture = io.StringIO()
            with (
                mock.patch("mmo.core.variants._load_scan_builder", return_value=_scan_builder),
                mock.patch("mmo.core.variants.run_detectors", return_value=None),
                mock.patch("mmo.core.variants.run_resolvers", return_value=None),
                mock.patch("mmo.core.variants.apply_gates_to_report", return_value=None),
                contextlib.redirect_stdout(stdout_capture),
            ):
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
                        "--bundle",
                        "--cache",
                        "on",
                        "--cache-dir",
                        str(cache_dir),
                        "--format-set",
                        "wavonly:wav",
                        "--format-set",
                        "lossless:flac,wv",
                    ]
                )
            self.assertEqual(exit_code, 0)

            plan = json.loads((out_dir / "variant_plan.json").read_text(encoding="utf-8"))
            result = json.loads((out_dir / "variant_result.json").read_text(encoding="utf-8"))
            variants = plan.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list):
                return
            self.assertEqual(len(variants), 2)

            wavonly_dir: Path | None = None
            lossless_dir: Path | None = None
            expected_formats_by_out_dir: dict[str, list[str]] = {}

            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_id = variant.get("variant_id")
                variant_slug = variant.get("variant_slug")
                steps = variant.get("steps")
                self.assertIsInstance(variant_id, str)
                self.assertIsInstance(variant_slug, str)
                self.assertIsInstance(steps, dict)
                if (
                    not isinstance(variant_id, str)
                    or not isinstance(variant_slug, str)
                    or not isinstance(steps, dict)
                ):
                    continue

                variant_dir = out_dir / f"{variant_id}__{variant_slug}"
                self.assertTrue(variant_dir.exists())
                self.assertTrue((variant_dir / "ui_bundle.json").exists())
                self.assertTrue((variant_dir / "render_manifest.json").exists())
                self.assertTrue((variant_dir / "apply_manifest.json").exists())

                expected_formats: list[str]
                if variant_slug.endswith("__wavonly"):
                    wavonly_dir = variant_dir
                    expected_formats = ["wav"]
                elif variant_slug.endswith("__lossless"):
                    lossless_dir = variant_dir
                    expected_formats = ["flac", "wv"]
                else:
                    self.fail(f"Unexpected variant slug: {variant_slug}")

                self.assertEqual(steps.get("render_output_formats"), expected_formats)
                self.assertEqual(steps.get("apply_output_formats"), expected_formats)
                expected_formats_by_out_dir[variant_dir.resolve().as_posix()] = expected_formats

            self.assertIsNotNone(wavonly_dir)
            self.assertIsNotNone(lossless_dir)
            if wavonly_dir is None or lossless_dir is None:
                return

            results = result.get("results")
            self.assertIsInstance(results, list)
            if not isinstance(results, list):
                return
            self.assertEqual(len(results), 2)
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                out_dir_value = entry.get("out_dir")
                self.assertIsInstance(out_dir_value, str)
                if not isinstance(out_dir_value, str):
                    continue
                expected_formats = expected_formats_by_out_dir.get(out_dir_value)
                self.assertIsNotNone(expected_formats)
                if expected_formats is None:
                    continue
                self.assertEqual(entry.get("render_output_formats"), expected_formats)
                self.assertEqual(entry.get("apply_output_formats"), expected_formats)

            wavonly_render_outputs = _manifest_outputs(
                wavonly_dir / "render_manifest.json",
                wavonly_dir / "render",
            )
            wavonly_apply_outputs = _manifest_outputs(
                wavonly_dir / "apply_manifest.json",
                wavonly_dir / "apply",
            )
            self.assertEqual(
                {fmt for fmt, _ in wavonly_render_outputs},
                {"wav"},
            )
            self.assertEqual(
                {fmt for fmt, _ in wavonly_apply_outputs},
                {"wav"},
            )

            lossless_render_outputs = _manifest_outputs(
                lossless_dir / "render_manifest.json",
                lossless_dir / "render",
            )
            lossless_apply_outputs = _manifest_outputs(
                lossless_dir / "apply_manifest.json",
                lossless_dir / "apply",
            )
            self.assertTrue({"flac", "wv"}.issubset({fmt for fmt, _ in lossless_render_outputs}))
            self.assertTrue({"flac", "wv"}.issubset({fmt for fmt, _ in lossless_apply_outputs}))

            for output_format, output_path in lossless_render_outputs + lossless_apply_outputs:
                if output_format in {"flac", "wv"}:
                    self.assertTrue(output_path.exists(), f"missing output file: {output_path}")

            logs = stdout_capture.getvalue()
            self.assertEqual(logs.count("analysis cache: miss"), 1)
            self.assertEqual(logs.count("analysis cache: hit"), 1)


if __name__ == "__main__":
    unittest.main()
