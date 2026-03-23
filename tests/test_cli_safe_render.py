"""Tests for ``mmo safe-render`` CLI command.

Covers:
- Dry-run mode (detect → resolve → gate → receipt, no audio).
- Full render: low-risk auto-applied, audio written, receipt + QA produced.
- Blocked high-risk recs visible in receipt.
- --approve all unblocks high-risk and allows full render.
- Schema validity of receipt output.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import jsonschema

from mmo.cli import main
from mmo.dsp.meters import iter_wav_float64_samples

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_BASELINE_STEMS_DIR = _REPO_ROOT / "tests" / "fixtures" / "safe_render_baseline_stems"
_SAFE_RENDER_EXPLICIT_SCENE_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "scene" / "safe_render_explicit_scene.json"
)
_SAFE_RENDER_EXPLICIT_LOCKS_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "scene" / "safe_render_explicit_scene_locks.yaml"
)
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_safe_render" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_16bit_wav(
    path: Path,
    *,
    channels: int = 1,
    rate: int = 48000,
    duration_s: float = 0.1,
    amplitude: float = 0.45,
) -> None:
    frames = max(8, int(rate * duration_s))
    samples: list[int] = []
    for i in range(frames):
        v = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * 220.0 * i / rate))
        for _ in range(channels):
            samples.append(v)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_hot_wav(
    path: Path,
    *,
    channels: int = 1,
    rate: int = 48000,
    duration_s: float = 0.1,
) -> None:
    """WAV with near-clipping peak (> -1 dBFS) to trigger headroom issue."""
    _write_16bit_wav(path, channels=channels, rate=rate, duration_s=duration_s, amplitude=0.98)


def _write_24bit_wav(
    path: Path,
    *,
    channels: int = 1,
    rate: int = 48000,
    duration_s: float = 0.1,
    amplitude: float = 0.45,
) -> None:
    frames = max(8, int(rate * duration_s))
    frame_bytes = bytearray()
    for i in range(frames):
        value = amplitude * math.sin(2.0 * math.pi * 220.0 * i / rate)
        sample = int(max(-1.0, min(1.0, value)) * 8388607.0)
        packed = int(sample).to_bytes(4, byteorder="little", signed=True)[:3]
        for _ in range(channels):
            frame_bytes.extend(packed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(3)
        handle.setframerate(rate)
        handle.writeframes(bytes(frame_bytes))


def _make_report(
    stems_dir: Path,
    stem_path_relative: str,
    stem_id: str,
    *,
    clip_count: int = 0,
    peak_dbfs: float = -6.0,
    recommendations: list[dict] | None = None,
) -> dict:
    report: dict = {
        "schema_version": "0.1.0",
        "report_id": f"REPORT.SAFE_RENDER.TEST.{stem_id.upper()}",
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": stem_id,
                    "file_path": stem_path_relative,
                    "measurements": [
                        {
                            "evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT",
                            "value": clip_count,
                        },
                        {
                            "evidence_id": "EVID.METER.PEAK_DBFS",
                            "value": peak_dbfs,
                        },
                    ],
                }
            ],
        },
        "issues": [],
        "recommendations": recommendations if recommendations is not None else [],
        "features": {},
    }
    return report


def _make_baseline_fixture_report() -> dict:
    stem_rows: list[dict] = []
    for stem_path in sorted(_BASELINE_STEMS_DIR.glob("*.wav")):
        with wave.open(str(stem_path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate_hz = handle.getframerate()
            frame_count = handle.getnframes()
        stem_rows.append(
            {
                "stem_id": stem_path.stem,
                "file_path": stem_path.name,
                "channel_count": channels,
                "sample_rate_hz": sample_rate_hz,
                "frame_count": frame_count,
                "measurements": [
                    {
                        "evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT",
                        "value": 0,
                    },
                    {
                        "evidence_id": "EVID.METER.PEAK_DBFS",
                        "value": -12.0,
                    },
                ],
            }
        )

    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.SAFE_RENDER.BASELINE_FIXTURE",
        "project_id": "PROJECT.BASELINE_FIXTURE",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": _BASELINE_STEMS_DIR.resolve().as_posix(),
            "stems": stem_rows,
        },
        "issues": [],
        "recommendations": [],
        "features": {},
    }


def _write_stub_only_plugins_dir(path: Path) -> Path:
    renderers_dir = path / "renderers"
    renderers_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _PLUGINS_DIR / "renderers" / "safe_renderer.plugin.yaml"
    renderers_dir.joinpath(source_manifest.name).write_text(
        source_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _write_placement_only_plugins_dir(path: Path) -> Path:
    renderers_dir = path / "renderers"
    renderers_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _PLUGINS_DIR / "renderers" / "placement_mixdown_renderer.plugin.yaml"
    renderers_dir.joinpath(source_manifest.name).write_text(
        source_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _materialize_explicit_scene_fixture(*, scene_out_path: Path) -> Path:
    payload = json.loads(_SAFE_RENDER_EXPLICIT_SCENE_FIXTURE.read_text(encoding="utf-8"))
    source = payload.get("source")
    if isinstance(source, dict):
        source["stems_dir"] = _BASELINE_STEMS_DIR.resolve().as_posix()
    scene_out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return scene_out_path


def _peak_abs_wav(path: Path) -> float:
    peak = 0.0
    for chunk in iter_wav_float64_samples(
        path,
        error_context="safe-render baseline test",
    ):
        if not chunk:
            continue
        chunk_peak = max(abs(sample) for sample in chunk)
        if chunk_peak > peak:
            peak = chunk_peak
    return peak


class TestSafeRenderDryRun(unittest.TestCase):
    """Dry-run: receipt written, no audio produced."""

    def test_dry_run_writes_receipt_no_audio(self) -> None:
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            stem_path = stems_dir / "kick.wav"
            _write_hot_wav(stem_path)

            report = _make_report(stems_dir, "kick.wav", "kick", peak_dbfs=-0.3)
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            receipt_path = temp / "receipt.json"
            out_dir = temp / "renders"

            exit_code, _stdout, _stderr = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--dry-run",
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(receipt_path.exists(), "receipt file should be written")
            self.assertFalse(out_dir.exists(), "no renders dir should be created in dry-run")

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertTrue(receipt["dry_run"])


class TestSafeRenderWorkspaceResolution(unittest.TestCase):
    def test_workspace_relative_source_ref_uses_shared_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            workspace_dir = temp / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            source_path = workspace_dir / "sources" / "kick.wav"
            _write_16bit_wav(source_path)

            report = {
                "schema_version": "0.1.0",
                "report_id": "REPORT.SAFE_RENDER.WORKSPACE.RESOLUTION",
                "project_id": "PROJECT.TEST",
                "generated_at": "2000-01-01T00:00:00Z",
                "engine_version": "0.1.0",
                "ontology_version": "0.1.0",
                "session": {
                    "stems_dir": (workspace_dir / "missing_stems").resolve().as_posix(),
                    "stems": [
                        {
                            "stem_id": "kick",
                            "file_path": "missing.wav",
                            "workspace_relative_path": "sources/kick.wav",
                            "source_ref": "sources/kick.wav",
                            "channel_count": 1,
                            "sample_rate_hz": 48000,
                            "bits_per_sample": 16,
                        }
                    ],
                },
                "issues": [],
                "recommendations": [],
            }

            report_path = workspace_dir / "report.json"
            out_dir = workspace_dir / "render"
            manifest_path = workspace_dir / "render_manifest.json"
            receipt_path = workspace_dir / "receipt.json"
            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(plugins_dir),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--out-manifest", str(manifest_path),
                    "--receipt-out", str(receipt_path),
                    "--force",
                ]
            )
            self.assertEqual(exit_code, 0, stderr)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            renderer_manifests = manifest.get("renderer_manifests")
            self.assertIsInstance(renderer_manifests, list)
            if not isinstance(renderer_manifests, list) or not renderer_manifests:
                return

            placement_manifest = renderer_manifests[0]
            stem_resolution = placement_manifest.get("stem_resolution")
            self.assertIsInstance(stem_resolution, list)
            if not isinstance(stem_resolution, list) or not stem_resolution:
                return

            row = stem_resolution[0]
            self.assertEqual(row.get("stem_id"), "kick")
            self.assertEqual(row.get("resolution_mode"), "workspace_relative_source_ref")
            self.assertEqual(row.get("resolved_path"), source_path.resolve().as_posix())
            outputs = placement_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if isinstance(outputs, list):
                self.assertGreaterEqual(len(outputs), 1)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["context"], "safe_render")
            self.assertEqual(receipt["target"], "stereo")
            self.assertIn(
                receipt["status"], ("completed", "dry_run_only", "blocked"),
                "status must reflect a valid safe-render outcome",
            )

    def test_dry_run_binaural_tokens_resolve_and_emit_virtualization_notes(self) -> None:
        binaural_tokens = (
            "binaural",
            "TARGET.HEADPHONES.BINAURAL",
            "LAYOUT.BINAURAL",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            stem_path = stems_dir / "kick.wav"
            _write_16bit_wav(stem_path, channels=1, amplitude=0.45)
            report = _make_report(stems_dir, "kick.wav", "kick", peak_dbfs=-6.0)
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            for token in binaural_tokens:
                with self.subTest(token=token):
                    receipt_path = temp / f"receipt.{token.replace('.', '_')}.json"
                    exit_code, _stdout, _stderr = _run_main(
                        [
                            "safe-render",
                            "--report",
                            str(report_path),
                            "--plugins",
                            str(_PLUGINS_DIR),
                            "--target",
                            token,
                            "--dry-run",
                            "--receipt-out",
                            str(receipt_path),
                        ]
                    )
                    self.assertEqual(exit_code, 0)
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    notes = receipt.get("notes", [])
                    self.assertIn("binaural_virtualization=true", notes)
                    self.assertTrue(
                        any(
                            isinstance(note, str)
                            and note.startswith("binaural_source_layout=")
                            for note in notes
                        )
                    )

    def test_dry_run_no_audio_with_low_risk_recs(self) -> None:
        """Low-risk recommendations visible in dry-run receipt but no audio."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        recs = [
            {
                "recommendation_id": "REC.TEST.GAIN.001",
                "issue_id": "ISSUE.SAFETY.CLIPPING_SAMPLES",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -3.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_hot_wav(stems_dir / "kick.wav")

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=5, peak_dbfs=-0.2,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            receipt_path = temp / "receipt.json"
            exit_code, _o, _e = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            summary = receipt["recommendations_summary"]
            # total includes recs from report + any added by detectors
            self.assertGreaterEqual(summary["total"], 1)
            self.assertEqual(receipt["renderer_manifests"], [])


class TestSafeRenderFullRender(unittest.TestCase):
    """Full render: audio is written, receipt + manifest produced."""

    def test_full_render_low_risk_auto_applied(self) -> None:
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            (_SCHEMAS_DIR / "render_manifest.schema.json").read_text(encoding="utf-8")
        )
        recs = [
            {
                "recommendation_id": "REC.TEST.GAIN.001",
                "issue_id": "ISSUE.SAFETY.CLIPPING_SAMPLES",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -3.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--out-manifest", str(manifest_path),
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            self.assertTrue(manifest_path.exists(), "render manifest should be written")
            self.assertTrue(receipt_path.exists(), "receipt should be written")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(manifest_schema).validate(manifest)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertFalse(receipt["dry_run"])
            self.assertEqual(receipt["status"], "completed")
            self.assertIsInstance(receipt["renderer_manifests"], list)

    def test_full_render_writes_qa_report(self) -> None:
        """Full render with --qa-out produces QA JSON with spectral slopes."""
        recs = [
            {
                "recommendation_id": "REC.TEST.GAIN.001",
                "issue_id": "ISSUE.SAFETY.CLIPPING_SAMPLES",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -3.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            qa_path = temp / "qa.json"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--qa-out", str(qa_path),
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            self.assertTrue(qa_path.exists(), "QA report should be written")

            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            self.assertIn("outputs", qa)
            self.assertIn("issues", qa)
            self.assertIn("thresholds", qa)
            self.assertIsInstance(qa["outputs"], list)
            self.assertIsInstance(qa["issues"], list)

    def test_full_render_manifest_receipt_qa_and_cli_share_deliverable_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir,
                "kick.wav",
                "kick",
                clip_count=0,
                peak_dbfs=-6.0,
                recommendations=[],
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            qa_path = temp / "qa.json"
            receipt_path = temp / "receipt.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--target",
                    "stereo",
                    "--out-dir",
                    str(out_dir),
                    "--out-manifest",
                    str(manifest_path),
                    "--qa-out",
                    str(qa_path),
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            qa = json.loads(qa_path.read_text(encoding="utf-8"))

            manifest_summary = manifest.get("deliverables_summary")
            receipt_summary = receipt.get("deliverables_summary")
            qa_summary = qa.get("deliverables_summary")
            self.assertIsInstance(manifest_summary, dict)
            self.assertIsInstance(receipt_summary, dict)
            self.assertIsInstance(qa_summary, dict)
            if not isinstance(manifest_summary, dict):
                return
            if not isinstance(receipt_summary, dict):
                return
            if not isinstance(qa_summary, dict):
                return

            self.assertEqual(receipt_summary, manifest_summary)
            self.assertEqual(qa_summary, manifest_summary)
            self.assertGreater(manifest_summary.get("deliverable_count", 0), 0)

            deliverables = manifest.get("deliverables")
            self.assertIsInstance(deliverables, list)
            if not isinstance(deliverables, list) or not deliverables:
                return
            for deliverable in deliverables:
                self.assertIsInstance(deliverable, dict)
                if not isinstance(deliverable, dict):
                    continue
                self.assertIn("status", deliverable)
                self.assertIn("is_valid_master", deliverable)
                self.assertIn("planned_stem_count", deliverable)
                self.assertIn("decoded_stem_count", deliverable)
                self.assertIn("prepared_stem_count", deliverable)
                self.assertIn("skipped_stem_count", deliverable)
                self.assertIn("rendered_frame_count", deliverable)
                self.assertIn("duration_seconds", deliverable)
                self.assertIn("failure_reason", deliverable)
                self.assertIn("warning_codes", deliverable)

            overall_status = str(manifest_summary.get("overall_status") or "").strip()
            self.assertTrue(overall_status)
            self.assertIn(f"result={overall_status}", stderr)
            self.assertIn(
                f"deliverables={manifest_summary.get('deliverable_count', 0)}",
                stderr,
            )

    def test_full_render_zero_decoded_artifacts_are_preserved_but_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            report = _make_report(
                stems_dir,
                "missing.wav",
                "kick",
                clip_count=0,
                peak_dbfs=-6.0,
                recommendations=[],
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            qa_path = temp / "qa.json"
            receipt_path = temp / "receipt.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "stereo",
                    "--out-dir",
                    str(out_dir),
                    "--out-manifest",
                    str(manifest_path),
                    "--qa-out",
                    str(qa_path),
                    "--receipt-out",
                    str(receipt_path),
                    "--force",
                ]
            )
            self.assertEqual(exit_code, 1, msg=stderr)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            qa = json.loads(qa_path.read_text(encoding="utf-8"))

            manifest_summary = manifest.get("deliverables_summary")
            self.assertIsInstance(manifest_summary, dict)
            if not isinstance(manifest_summary, dict):
                return
            self.assertEqual(manifest_summary.get("overall_status"), "failed")
            self.assertEqual(manifest_summary.get("valid_master_count"), 0)

            deliverables = manifest.get("deliverables")
            self.assertIsInstance(deliverables, list)
            if not isinstance(deliverables, list) or not deliverables:
                return
            master_deliverables = [
                item
                for item in deliverables
                if isinstance(item, dict) and item.get("artifact_role") == "master"
            ]
            self.assertTrue(master_deliverables)
            self.assertTrue(all(item.get("status") == "failed" for item in master_deliverables))

            outputs = [
                output
                for renderer_manifest in manifest.get("renderer_manifests", [])
                if isinstance(renderer_manifest, dict)
                for output in renderer_manifest.get("outputs", [])
                if isinstance(output, dict)
            ]
            self.assertTrue(outputs)
            first_output_path = out_dir / str(outputs[0].get("file_path", ""))
            self.assertTrue(first_output_path.exists())
            with wave.open(str(first_output_path), "rb") as handle:
                self.assertEqual(handle.getnframes(), 0)

            self.assertEqual(receipt.get("status"), "blocked")
            self.assertEqual(receipt.get("deliverables_summary"), manifest_summary)
            error_ids = {
                issue.get("issue_id")
                for issue in qa.get("issues", [])
                if isinstance(issue, dict) and issue.get("severity") == "error"
            }
            self.assertIn("ISSUE.RENDER.ALL_MASTERS_INVALID", error_ids)
            self.assertIn("ISSUE.RENDER.QA.SILENT_OUTPUT", error_ids)
            self.assertIn("all rendered masters are invalid", stderr)

    def test_full_render_preview_headphones_writes_binaural_outputs(self) -> None:
        recs = [
            {
                "recommendation_id": "REC.TEST.GAIN.001",
                "issue_id": "ISSUE.SAFETY.CLIPPING_SAMPLES",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -3.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--out-manifest", str(manifest_path),
                    "--receipt-out", str(receipt_path),
                    "--preview-headphones",
                ]
            )
            self.assertEqual(exit_code, 0, msg=err)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifests = manifest.get("renderer_manifests", [])
            self.assertIsInstance(manifests, list)

            preview_manifest = None
            for row in manifests:
                if isinstance(row, dict) and row.get("renderer_id") == "PLUGIN.RENDERER.BINAURAL_PREVIEW_V0":
                    preview_manifest = row
                    break
            self.assertIsNotNone(preview_manifest, "expected headphone preview renderer manifest")

            outputs = preview_manifest.get("outputs", []) if isinstance(preview_manifest, dict) else []
            self.assertGreater(len(outputs), 0, "expected at least one headphone preview output")

            first_output = outputs[0]
            self.assertEqual(first_output.get("format"), "wav")
            self.assertEqual(first_output.get("channel_count"), 2)
            metadata = first_output.get("metadata", {})
            self.assertIn("preview_of_output_id", metadata)
            preview_path = out_dir / Path(first_output.get("file_path", ""))
            self.assertTrue(preview_path.exists(), f"missing preview file: {preview_path}")

    def test_receipt_blocked_recs_visible(self) -> None:
        """High-risk recs appear in blocked_recommendations without --approve."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        # Build a report with no recs; the detectors will find issues.
        # We also manually add a high-risk rec to ensure it appears blocked.
        recs = [
            {
                "recommendation_id": "REC.TEST.HIGH.001",
                "issue_id": "ISSUE.TONE.RESHAPE",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "high",
                "requires_approval": True,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"

            exit_code, _o, _e = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            blocked = receipt.get("blocked_recommendations", [])
            rec_ids = [b.get("recommendation_id") for b in blocked]
            self.assertIn("REC.TEST.HIGH.001", rec_ids)
            self.assertGreater(receipt["recommendations_summary"]["blocked"], 0)

    def test_stub_renderer_only_fails_and_emits_no_outputs_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)
            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=[],
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            plugins_dir = _write_stub_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"
            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "stereo",
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertNotEqual(exit_code, 0, msg=stderr)
            self.assertTrue(receipt_path.exists(), "receipt should be written on no-output failure")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            issue_ids = [
                issue.get("issue_id")
                for issue in receipt.get("qa_issues", [])
                if isinstance(issue, dict)
            ]
            self.assertIn("ISSUE.RENDER.NO_OUTPUTS", issue_ids)
            self.assertIn("ISSUE.RENDER.NO_OUTPUTS", stderr)

    def test_allow_empty_outputs_keeps_warning_but_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)
            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=[],
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            plugins_dir = _write_stub_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"
            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "stereo",
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                    "--allow-empty-outputs",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            issue_ids = [
                issue.get("issue_id")
                for issue in receipt.get("qa_issues", [])
                if isinstance(issue, dict)
            ]
            self.assertIn("ISSUE.RENDER.NO_OUTPUTS", issue_ids)


class TestSafeRenderBaselineMixdown(unittest.TestCase):
    def test_safe_render_zero_recommendations_writes_all_layout_masters(self) -> None:
        expected_layouts = (
            "LAYOUT.2_0",
            "LAYOUT.5_1",
            "LAYOUT.7_1",
            "LAYOUT.7_1_4",
            "LAYOUT.9_1_6",
        )
        target_peak_linear = math.pow(10.0, -1.0 / 20.0)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            out_dir = temp / "renders"
            qa_path = temp / "qa.json"
            receipt_path = temp / "receipt.json"
            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--target",
                    "LAYOUT.2_0",
                    "--out-dir",
                    str(out_dir),
                    "--qa-out",
                    str(qa_path),
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            for layout_id in expected_layouts:
                layout_slug = layout_id.replace(".", "_")
                master_path = out_dir / layout_slug / "master.wav"
                self.assertTrue(master_path.exists(), f"missing baseline output: {master_path}")
                self.assertGreater(master_path.stat().st_size, 44)
                self.assertLessEqual(
                    _peak_abs_wav(master_path),
                    target_peak_linear + 1e-3,
                )

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            manifests = receipt.get("renderer_manifests", [])
            baseline_manifest = next(
                (
                    item
                    for item in manifests
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.MIXDOWN_BASELINE"
                ),
                None,
            )
            self.assertIsNotNone(baseline_manifest)
            if baseline_manifest is None:
                return
            outputs = baseline_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return
            self.assertEqual(len(outputs), len(expected_layouts))
            self.assertEqual(
                {
                    item.get("layout_id")
                    for item in outputs
                    if isinstance(item, dict)
                },
                set(expected_layouts),
            )

            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa_outputs = qa.get("outputs")
            self.assertIsInstance(qa_outputs, list)
            if not isinstance(qa_outputs, list):
                return
            self.assertGreaterEqual(len(qa_outputs), len(expected_layouts))

    def test_safe_render_baseline_render_many_hashes_are_deterministic(self) -> None:
        targets = (
            "LAYOUT.2_0",
            "LAYOUT.5_1",
            "LAYOUT.7_1",
            "LAYOUT.7_1_4",
            "LAYOUT.9_1_6",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            hashes_by_run: list[dict[str, str]] = []
            for run_index in (1, 2):
                out_dir = temp / f"renders_{run_index}"
                receipt_path = temp / f"receipt_{run_index}.json"
                exit_code, _stdout, stderr = _run_main(
                    [
                        "safe-render",
                        "--report",
                        str(report_path),
                        "--plugins",
                        str(_PLUGINS_DIR),
                        "--render-many",
                        "--render-many-targets",
                        ",".join(targets),
                        "--out-dir",
                        str(out_dir),
                        "--receipt-out",
                        str(receipt_path),
                        "--force",
                    ]
                )
                self.assertEqual(exit_code, 0, msg=stderr)

                run_hashes: dict[str, str] = {}
                for layout_id in targets:
                    layout_slug = layout_id.replace(".", "_")
                    master_path = out_dir / layout_slug / "master.wav"
                    self.assertTrue(
                        master_path.exists(),
                        f"missing baseline output for {layout_id}: {master_path}",
                    )
                    self.assertGreater(master_path.stat().st_size, 44)
                    run_hashes[layout_id] = hashlib.sha256(
                        master_path.read_bytes()
                    ).hexdigest()
                hashes_by_run.append(run_hashes)

            self.assertEqual(hashes_by_run[0], hashes_by_run[1])


class TestSafeRenderExplicitScene(unittest.TestCase):
    def test_full_render_from_explicit_scene_records_sources_and_writes_outputs(self) -> None:
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            scene_path = _materialize_explicit_scene_fixture(scene_out_path=temp / "scene.json")
            scene_locks_path = temp / "scene_locks.yaml"
            scene_locks_path.write_text(
                _SAFE_RENDER_EXPLICIT_LOCKS_FIXTURE.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            receipt_path = temp / "receipt.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--scene",
                    str(scene_path),
                    "--scene-locks",
                    str(scene_locks_path),
                    "--scene-strict",
                    "--target",
                    "LAYOUT.2_0",
                    "--out-dir",
                    str(out_dir),
                    "--out-manifest",
                    str(manifest_path),
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            master_path = out_dir / "LAYOUT_2_0" / "master.wav"
            self.assertTrue(master_path.exists(), f"missing rendered output: {master_path}")

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertEqual(receipt.get("scene_mode"), "explicit")
            self.assertEqual(
                receipt.get("scene_source_path"),
                scene_path.resolve().as_posix(),
            )
            self.assertEqual(
                receipt.get("scene_locks_source_path"),
                scene_locks_path.resolve().as_posix(),
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            placement_manifest = next(
                (
                    item
                    for item in manifest.get("renderer_manifests", [])
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1"
                ),
                None,
            )
            self.assertIsNotNone(placement_manifest, "placement renderer manifest missing")
            if not isinstance(placement_manifest, dict):
                return

            saw_locked_width_source = False
            for output in placement_manifest.get("outputs", []):
                if not isinstance(output, dict):
                    continue
                metadata = output.get("metadata")
                if not isinstance(metadata, dict):
                    continue
                stem_rows = metadata.get("stem_send_summary")
                if not isinstance(stem_rows, list):
                    continue
                for row in stem_rows:
                    if not isinstance(row, dict):
                        continue
                    if row.get("stem_id") != "vox_mono":
                        continue
                    notes = row.get("notes")
                    if isinstance(notes, list) and "width_source:locked" in notes:
                        saw_locked_width_source = True
                        break
                if saw_locked_width_source:
                    break
            self.assertTrue(saw_locked_width_source, "scene locks were not applied before placement")

    def test_scene_exports_stems_and_buses_with_master_toggle_and_layout_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            scene_path = _materialize_explicit_scene_fixture(scene_out_path=temp / "scene.json")
            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--scene",
                    str(scene_path),
                    "--target",
                    "LAYOUT.2_0",
                    "--out-dir",
                    str(out_dir),
                    "--out-manifest",
                    str(manifest_path),
                    "--export-stems",
                    "--export-buses",
                    "--no-export-master",
                    "--export-layouts",
                    "stereo",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            renderer_manifests = manifest.get("renderer_manifests", [])
            self.assertIsInstance(renderer_manifests, list)
            placement_manifest = next(
                (
                    item
                    for item in renderer_manifests
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1"
                ),
                None,
            )
            self.assertIsNotNone(placement_manifest)
            if not isinstance(placement_manifest, dict):
                return
            outputs = placement_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if not isinstance(outputs, list):
                return

            master_rows = [
                row for row in outputs
                if isinstance(row, dict)
                and str(row.get("file_path", "")).endswith("/master.wav")
            ]
            self.assertEqual(master_rows, [], "master outputs should be disabled")

            stem_rows = [
                row for row in outputs
                if isinstance(row, dict)
                and str(row.get("target_stem_id", "")).strip()
            ]
            self.assertGreaterEqual(len(stem_rows), 3, "expected stem copy outputs")
            for row in stem_rows:
                file_path = str(row.get("file_path", ""))
                sha256 = str(row.get("sha256", ""))
                self.assertTrue(file_path.startswith("stems/"), f"unexpected stem path: {file_path}")
                self.assertEqual(len(sha256), 64, "expected sha256 on stem artifact")
                self.assertTrue((out_dir / file_path).is_file(), f"missing stem artifact: {file_path}")

            bus_rows = [
                row for row in outputs
                if isinstance(row, dict)
                and str(row.get("target_bus_id", "")).strip().startswith("BUS.")
                and "/buses/" in str(row.get("file_path", ""))
            ]
            self.assertGreaterEqual(len(bus_rows), 2, "expected subbus outputs")
            self.assertTrue(
                any(str(row.get("layout_id", "")) == "LAYOUT.2_0" for row in bus_rows),
                "subbus exports should honor --export-layouts=stereo",
            )
            for row in bus_rows:
                file_path = str(row.get("file_path", ""))
                sha256 = str(row.get("sha256", ""))
                self.assertIn("/buses/", file_path, f"unexpected bus path: {file_path}")
                self.assertEqual(len(sha256), 64, "expected sha256 on bus artifact")
                self.assertTrue((out_dir / file_path).is_file(), f"missing bus artifact: {file_path}")

    def test_receipt_reports_deterministic_fallback_attempts(self) -> None:
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            scene_path = _materialize_explicit_scene_fixture(scene_out_path=temp / "scene.json")
            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            out_dir = temp / "renders"
            manifest_path = temp / "render_manifest.json"
            receipt_path = temp / "receipt.json"

            fail_result = {
                "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
                "gate_version": "1.0.0",
                "source_layout_id": "LAYOUT.5_1",
                "target_layout_id": "LAYOUT.2_0",
                "matrix_id": "MATRIX.TEST.FAIL",
                "passed": False,
                "risk_level": "high",
                "metrics": {
                    "loudness_delta_lufs": 3.0,
                    "correlation_over_time_min": 0.0,
                    "spectral_distance_db": 8.0,
                    "peak_delta_dbfs": 4.0,
                    "true_peak_delta_dbtp": 3.0,
                },
                "thresholds": {
                    "loudness_delta_warn_abs": 1.0,
                    "correlation_time_warn_lte": 0.5,
                    "spectral_distance_warn_db": 3.0,
                    "peak_delta_warn_abs": 1.5,
                    "true_peak_delta_warn_abs": 1.0,
                },
                "notes": ["forced_fail"],
            }
            pass_result = {
                "gate_id": "GATE.DOWNMIX_SIMILARITY_RENDER_COMPARE",
                "gate_version": "1.0.0",
                "source_layout_id": "LAYOUT.5_1",
                "target_layout_id": "LAYOUT.2_0",
                "matrix_id": "MATRIX.TEST.PASS",
                "passed": True,
                "risk_level": "low",
                "metrics": {
                    "loudness_delta_lufs": 0.1,
                    "correlation_over_time_min": 0.9,
                    "spectral_distance_db": 0.2,
                    "peak_delta_dbfs": 0.1,
                    "true_peak_delta_dbtp": 0.1,
                },
                "thresholds": {
                    "loudness_delta_warn_abs": 1.0,
                    "correlation_time_warn_lte": 0.5,
                    "spectral_distance_warn_db": 3.0,
                    "peak_delta_warn_abs": 1.5,
                    "true_peak_delta_warn_abs": 1.0,
                },
                "notes": ["forced_pass"],
            }

            with mock.patch(
                "mmo.plugins.renderers.placement_mixdown_renderer.compare_rendered_surround_to_stereo_reference",
                side_effect=[fail_result, pass_result],
            ):
                exit_code, _stdout, stderr = _run_main(
                    [
                        "safe-render",
                        "--report",
                        str(report_path),
                        "--plugins",
                        str(plugins_dir),
                        "--scene",
                        str(scene_path),
                        "--target",
                        "LAYOUT.2_0",
                        "--out-dir",
                        str(out_dir),
                        "--out-manifest",
                        str(manifest_path),
                        "--receipt-out",
                        str(receipt_path),
                        "--export-layouts",
                        "stereo,5.1",
                    ]
                )
            self.assertEqual(exit_code, 0, msg=stderr)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertEqual(receipt["fallback_final"]["final_outcome"], "pass")
            attempts = receipt.get("fallback_attempts")
            self.assertIsInstance(attempts, list)
            if not isinstance(attempts, list):
                return
            self.assertGreaterEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["step_id"], "reduce_surround")
            self.assertIn("fallback_applied=true", receipt.get("notes", []))

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            placement_manifest = next(
                (
                    item
                    for item in manifest.get("renderer_manifests", [])
                    if isinstance(item, dict)
                    and item.get("renderer_id") == "PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1"
                ),
                None,
            )
            self.assertIsInstance(placement_manifest, dict)
            if not isinstance(placement_manifest, dict):
                return
            outputs = placement_manifest.get("outputs", [])
            immersive_row = next(
                (
                    row
                    for row in outputs
                    if isinstance(row, dict)
                    and row.get("layout_id") == "LAYOUT.5_1"
                    and str(row.get("file_path", "")).endswith("/master.wav")
                ),
                None,
            )
            self.assertIsInstance(immersive_row, dict)
            if not isinstance(immersive_row, dict):
                return
            metadata = immersive_row.get("metadata", {})
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertIn("fallback_applied=true", metadata.get("manifest_tags", []))

    def test_scene_strict_rejects_missing_stems_or_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            scene_payload = json.loads(
                _SAFE_RENDER_EXPLICIT_SCENE_FIXTURE.read_text(encoding="utf-8")
            )
            source = scene_payload.get("source")
            if isinstance(source, dict):
                source["stems_dir"] = _BASELINE_STEMS_DIR.resolve().as_posix()
            objects = scene_payload.get("objects")
            if isinstance(objects, list) and objects:
                first = objects[0]
                if isinstance(first, dict):
                    first["stem_id"] = "missing_stem"
                    first["role_id"] = "ROLE.MISSING.NOT_IN_REGISTRY"
            scene_path = temp / "scene_invalid_strict.json"
            scene_path.write_text(
                json.dumps(scene_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--scene",
                    str(scene_path),
                    "--scene-strict",
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 1, msg=stderr)
            self.assertIn("Scene lint failed", stderr)
            self.assertIn("safe-render: scene validation stopped the render.", stderr)
            self.assertIn("--scene-strict found 1 error(s), 0 warning(s)", stderr)
            self.assertIn("ISSUE.SCENE_LINT.MISSING_STEM_FILE", stderr)

    def test_scene_strict_rejects_scene_lint_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report = _make_baseline_fixture_report()
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            scene_payload = json.loads(
                _SAFE_RENDER_EXPLICIT_SCENE_FIXTURE.read_text(encoding="utf-8")
            )
            source = scene_payload.get("source")
            if isinstance(source, dict):
                source["stems_dir"] = _BASELINE_STEMS_DIR.resolve().as_posix()
            objects = scene_payload.get("objects")
            if isinstance(objects, list) and objects:
                first = objects[0]
                if isinstance(first, dict):
                    first_intent = first.get("intent")
                    if isinstance(first_intent, dict):
                        first_intent["width"] = 1.5
            scene_path = temp / "scene_lint_invalid.json"
            scene_path.write_text(
                json.dumps(scene_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--scene",
                    str(scene_path),
                    "--scene-strict",
                    "--dry-run",
                ]
            )
            self.assertEqual(exit_code, 1, msg=stderr)
            self.assertIn("Scene lint failed", stderr)
            self.assertIn("safe-render: scene validation stopped the render.", stderr)
            self.assertIn("--scene-strict found 1 error(s), 0 warning(s)", stderr)
            self.assertIn("ISSUE.SCENE_LINT.OUT_OF_RANGE_WIDTH", stderr)


class TestSafeRenderApprove(unittest.TestCase):
    """--approve overrides blocked recs."""

    def test_approve_all_unblocks_high_risk(self) -> None:
        """With --approve all, high-risk recs become eligible and audio is written."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        recs = [
            {
                "recommendation_id": "REC.TEST.HIGH.001",
                "issue_id": "ISSUE.TONE.RESHAPE",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "high",
                "requires_approval": True,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--approve", "all",
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertEqual(receipt["status"], "completed")
            self.assertGreater(receipt["recommendations_summary"]["approved_by_user"], 0)
            self.assertEqual(receipt["approved_by"], ["all"])

    def test_approve_specific_id_unblocks_matching_rec(self) -> None:
        """--approve with specific recommendation_id unblocks only that rec."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        recs = [
            {
                "recommendation_id": "REC.TEST.HIGH.001",
                "issue_id": "ISSUE.TONE.RESHAPE",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "high",
                "requires_approval": True,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [{"param_id": "PARAM.GAIN.DB", "value": -1.0}],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=0, peak_dbfs=-6.0,
                recommendations=recs,
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--approve", "REC.TEST.HIGH.001",
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertEqual(receipt["status"], "completed")


class TestSafeRenderDetectResolveChain(unittest.TestCase):
    """Detectors and resolvers run inline (full plugin chain)."""

    def test_detectors_add_issues_and_resolvers_add_recs(self) -> None:
        """A session with clipping triggers ClippingHeadroomDetector,
        which adds an issue, and HeadroomGainResolver adds a recommendation."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        # Report with NO pre-existing recommendations; detectors will generate them.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_hot_wav(stems_dir / "kick.wav")

            report = _make_report(
                stems_dir, "kick.wav", "kick",
                clip_count=12, peak_dbfs=-0.2,
                recommendations=[],  # empty — detectors will add
            )
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            out_dir = temp / "renders"
            receipt_path = temp / "receipt.json"

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--target", "stereo",
                    "--out-dir", str(out_dir),
                    "--receipt-out", str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(receipt)
            # Detectors should have found the clipping and resolvers produced a gain rec
            total = receipt["recommendations_summary"]["total"]
            self.assertGreater(total, 0, "detectors+resolvers should have generated recommendations")


class TestBuildSafeRenderQA(unittest.TestCase):
    """Unit tests for build_safe_render_qa from render_qa module."""

    def test_empty_entries_returns_valid_payload(self) -> None:
        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        qa = build_safe_render_qa(output_entries=[])
        self.assertIn("outputs", qa)
        self.assertIn("issues", qa)
        self.assertEqual(qa["outputs"], [])
        self.assertEqual(qa["issues"], [])

    def test_nonexistent_file_handled_gracefully(self) -> None:
        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        qa = build_safe_render_qa(
            output_entries=[
                {
                    "path": "/nonexistent/file.wav",
                    "sha256": "abc123",
                    "channels": 2,
                    "sample_rate_hz": 48000,
                }
            ]
        )
        self.assertEqual(len(qa["outputs"]), 1)
        self.assertIsInstance(qa["issues"], list)
        issue_map = {
            issue.get("issue_id"): issue
            for issue in qa["issues"]
            if isinstance(issue, dict)
        }
        self.assertEqual(
            issue_map["ISSUE.RENDER.QA.LOUDNESS_NON_MEASURABLE"]["measurement_state"],
            "measurement_failed",
        )
        self.assertEqual(
            issue_map["ISSUE.RENDER.QA.PEAK_NON_MEASURABLE"]["measurement_state"],
            "measurement_failed",
        )

    def test_valid_wav_file_produces_spectral_data(self) -> None:
        """When numpy is available, a WAV file produces spectral slope metrics."""
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            wav_path = temp / "tone.wav"
            _write_16bit_wav(wav_path, channels=2, rate=48000, duration_s=0.5)

            qa = build_safe_render_qa(
                output_entries=[
                    {
                        "path": wav_path.as_posix(),
                        "sha256": "dummy",
                        "channels": 2,
                        "sample_rate_hz": 48000,
                    }
                ]
            )
            self.assertEqual(len(qa["outputs"]), 1)
            output = qa["outputs"][0]
            spectral = output.get("spectral", {})
            # spectral must have the standard keys
            self.assertIn("centers_hz", spectral)
            self.assertIn("levels_db", spectral)
            self.assertIn("tilt_db_per_oct", spectral)
            self.assertIn("section_tilt_db_per_oct", spectral)
            self.assertIn("adjacent_band_slopes_db_per_oct", spectral)

    def test_all_zero_output_is_reported_as_silent_error(self) -> None:
        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            wav_path = temp / "silent.wav"
            _write_16bit_wav(wav_path, channels=2, rate=48000, duration_s=0.5, amplitude=0.0)

            qa = build_safe_render_qa(
                output_entries=[
                    {
                        "path": wav_path.as_posix(),
                        "sha256": "silent",
                        "channels": 2,
                        "sample_rate_hz": 48000,
                    }
                ]
            )
            error_ids = {
                issue.get("issue_id")
                for issue in qa.get("issues", [])
                if isinstance(issue, dict) and issue.get("severity") == "error"
            }
            self.assertIn("ISSUE.RENDER.QA.SILENT_OUTPUT", error_ids)
            self.assertIn("ISSUE.RENDER.QA.LOUDNESS_NON_MEASURABLE", error_ids)
            self.assertIn("ISSUE.RENDER.QA.PEAK_NON_MEASURABLE", error_ids)
            self.assertIn("ISSUE.RENDER.QA.CORRELATION_NON_MEASURABLE", error_ids)

    def test_output_just_below_silence_threshold_is_reported(self) -> None:
        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            wav_path = temp / "below_threshold.wav"
            _write_24bit_wav(wav_path, channels=2, rate=48000, duration_s=0.5, amplitude=5e-7)

            qa = build_safe_render_qa(
                output_entries=[
                    {
                        "path": wav_path.as_posix(),
                        "sha256": "below-threshold",
                        "channels": 2,
                        "sample_rate_hz": 48000,
                    }
                ]
            )
            error_ids = {
                issue.get("issue_id")
                for issue in qa.get("issues", [])
                if isinstance(issue, dict) and issue.get("severity") == "error"
            }
            self.assertIn("ISSUE.RENDER.QA.SILENT_OUTPUT", error_ids)

    def test_very_quiet_but_non_silent_output_above_threshold_passes(self) -> None:
        from mmo.core.render_qa import build_safe_render_qa  # noqa: WPS433

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            wav_path = temp / "above_threshold.wav"
            _write_24bit_wav(wav_path, channels=2, rate=48000, duration_s=0.5, amplitude=2e-6)

            qa = build_safe_render_qa(
                output_entries=[
                    {
                        "path": wav_path.as_posix(),
                        "sha256": "above-threshold",
                        "channels": 2,
                        "sample_rate_hz": 48000,
                    }
                ]
            )
            error_ids = {
                issue.get("issue_id")
                for issue in qa.get("issues", [])
                if isinstance(issue, dict) and issue.get("severity") == "error"
            }
            self.assertNotIn("ISSUE.RENDER.QA.SILENT_OUTPUT", error_ids)

    def test_schema_in_all_exports(self) -> None:
        """build_safe_render_qa must appear in __all__ of render_qa."""
        import mmo.core.render_qa as rqa  # noqa: WPS433

        self.assertIn("build_safe_render_qa", rqa.__all__)


class TestSafeRenderForce(unittest.TestCase):
    """--force allows overwriting existing output files."""

    def test_force_overwrites_existing_receipt(self) -> None:
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            receipt_path = temp / "receipt.json"
            # pre-write a stale file
            receipt_path.write_text("{}", encoding="utf-8")

            exit_code, _o, err = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--receipt-out", str(receipt_path),
                    "--force",
                ]
            )
            self.assertEqual(exit_code, 0, f"stderr: {err}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            # Valid receipt (not the stale {})
            jsonschema.Draft202012Validator(schema).validate(receipt)

    def test_no_force_blocks_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)

            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            receipt_path = temp / "receipt.json"
            receipt_path.write_text("{}", encoding="utf-8")

            exit_code, _o, _e = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--receipt-out", str(receipt_path),
                    # no --force
                ]
            )
            self.assertEqual(exit_code, 1, "should fail when receipt exists and --force not given")


class TestSafeRenderLiveProgressAndCancel(unittest.TestCase):
    def test_live_progress_emits_explainable_log_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)
            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--live-progress",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            live_lines = [
                line[len("[MMO-LIVE] "):]
                for line in stderr.splitlines()
                if line.startswith("[MMO-LIVE] ")
            ]
            self.assertGreater(len(live_lines), 0, msg=stderr)
            for raw in live_lines:
                payload = json.loads(raw)
                self.assertIn("what", payload)
                self.assertIn("why", payload)
                self.assertIn("where", payload)
                self.assertIn("confidence", payload)
                self.assertIn("progress", payload)

    def test_cancel_file_stops_safe_render_with_exit_130(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_16bit_wav(stems_dir / "kick.wav", amplitude=0.45)
            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            cancel_file = temp / "cancel.flag"
            cancel_file.write_text("cancel\n", encoding="utf-8")

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report", str(report_path),
                    "--plugins", str(_PLUGINS_DIR),
                    "--dry-run",
                    "--cancel-file", str(cancel_file),
                ]
            )
            self.assertEqual(exit_code, 130, msg=stderr)
            self.assertIn("cancelled", stderr.lower())
