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

import jsonschema

from mmo.cli import main
from mmo.dsp.meters import iter_wav_float64_samples

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_BASELINE_STEMS_DIR = _REPO_ROOT / "tests" / "fixtures" / "safe_render_baseline_stems"
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
            self.assertEqual(receipt["context"], "safe_render")
            self.assertEqual(receipt["target"], "stereo")
            self.assertIn(
                receipt["status"], ("dry_run_only", "blocked"),
                "status must be dry_run_only or blocked",
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
