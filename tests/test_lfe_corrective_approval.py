from __future__ import annotations

import contextlib
import io
import json
import math
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main
from mmo.dsp.meters import iter_wav_float64_samples

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_FIXTURES_DIR = _REPO_ROOT / "fixtures"


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_lfe_plugins_dir(path: Path) -> Path:
    for relative_path in (
        Path("renderers/gain_trim_renderer.plugin.yaml"),
        Path("detectors/lfe_corrective_detector.plugin.yaml"),
        Path("resolvers/lfe_corrective_resolver.plugin.yaml"),
    ):
        source_path = _PLUGINS_DIR / relative_path
        target_path = path / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    return path


def _base_gain_render_recommendations() -> list[dict]:
    return [
        {
            "recommendation_id": "REC.RENDER.MAINS.001",
            "action_id": "ACTION.UTILITY.GAIN",
            "risk": "low",
            "requires_approval": False,
            "scope": {"stem_id": "mains"},
            "params": [{"param_id": "PARAM.GAIN.DB", "value": 0.0}],
        },
        {
            "recommendation_id": "REC.RENDER.LFE.001",
            "action_id": "ACTION.UTILITY.GAIN",
            "risk": "low",
            "requires_approval": False,
            "scope": {"stem_id": "lfe"},
            "params": [{"param_id": "PARAM.GAIN.DB", "value": 0.0}],
        },
    ]


def _lfe_channel_rows_measurements() -> list[dict]:
    return [
        {
            "evidence_id": "EVID.LFE.CHANNEL_ROWS",
            "value": [
                {
                    "channel_index": 0,
                    "inband_energy_db": -12.0,
                    "out_of_band_energy_db": -6.0,
                    "infrasonic_energy_db": -90.0,
                    "crest_factor_db": 8.0,
                    "peak_dbfs": -9.0,
                    "true_peak_dbtp": -8.8,
                    "mains_inband_energy_db": -14.0,
                    "lfe_to_mains_ratio_db": 2.0,
                    "out_of_band_high": True,
                    "infrasonic_rumble": False,
                    "headroom_low": False,
                    "band_level_low": False,
                    "band_level_high": False,
                }
            ],
        }
    ]


def _report_payload(
    *,
    fixture_dir: Path,
    lfe_measurements: list[dict] | None,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": f"REPORT.LFE.CORRECTIVE.{fixture_dir.name.upper()}",
        "project_id": "PROJECT.LFE.CORRECTIVE",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": fixture_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": "mains",
                    "file_path": "mains.wav",
                    "channel_count": 2,
                    "speaker_id": "SPK.L",
                    "role_id": "ROLE.MAINS",
                    "measurements": [],
                },
                {
                    "stem_id": "lfe",
                    "file_path": "lfe.wav",
                    "channel_count": 1,
                    "speaker_id": "SPK.LFE",
                    "role_id": "ROLE.LFE",
                    "measurements": lfe_measurements or [],
                },
            ],
        },
        "routing_plan": {
            "schema_version": "0.1.0",
            "source_layout_id": "LAYOUT.5_1",
            "target_layout_id": "LAYOUT.5_1",
            "routes": [
                {
                    "stem_id": "mains",
                    "stem_channels": 2,
                    "target_channels": 6,
                    "mapping": [
                        {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                        {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
                    ],
                    "notes": ["Stereo mains routed to FL/FR only."],
                },
                {
                    "stem_id": "lfe",
                    "stem_channels": 1,
                    "target_channels": 6,
                    "mapping": [
                        {"src_ch": 0, "dst_ch": 3, "gain_db": 0.0},
                    ],
                    "notes": ["Explicit LFE routed only to the LFE channel."],
                },
            ],
        },
        "issues": [],
        "recommendations": _base_gain_render_recommendations(),
        "features": {},
    }


def _write_report(path: Path, *, fixture_dir: Path, lfe_measurements: list[dict] | None) -> None:
    payload = _report_payload(
        fixture_dir=fixture_dir,
        lfe_measurements=lfe_measurements,
    )
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _blocked_corrective_rec_id(receipt: dict) -> str:
    blocked = receipt.get("blocked_recommendations")
    if not isinstance(blocked, list):
        raise AssertionError("blocked_recommendations missing from receipt")
    for entry in blocked:
        if not isinstance(entry, dict):
            continue
        if entry.get("action_id") != "ACTION.LFE.CORRECTIVE_FILTER":
            continue
        rec_id = str(entry.get("recommendation_id", "")).strip()
        if rec_id:
            return rec_id
    raise AssertionError("missing blocked corrective recommendation")


def _renderer_manifest(receipt: dict, renderer_id: str) -> dict | None:
    manifests = receipt.get("renderer_manifests")
    if not isinstance(manifests, list):
        return None
    return next(
        (
            manifest
            for manifest in manifests
            if isinstance(manifest, dict) and manifest.get("renderer_id") == renderer_id
        ),
        None,
    )


def _output_for_stem(receipt: dict, stem_id: str) -> dict:
    manifest = _renderer_manifest(receipt, "PLUGIN.RENDERER.GAIN_TRIM")
    if not isinstance(manifest, dict):
        raise AssertionError("missing gain-trim renderer manifest")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise AssertionError("gain-trim outputs missing")
    for output in outputs:
        if not isinstance(output, dict):
            continue
        if output.get("target_stem_id") == stem_id:
            return output
    raise AssertionError(f"missing gain-trim output for stem {stem_id}")


def _read_channel_samples(path: Path, *, channel_index: int) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_rate_hz = handle.getframerate()
    samples: list[float] = []
    for chunk in iter_wav_float64_samples(path, error_context="lfe corrective test"):
        if not chunk:
            continue
        usable = len(chunk) - (len(chunk) % channels)
        for frame_offset in range(0, usable, channels):
            samples.append(float(chunk[frame_offset + channel_index]))
    return sample_rate_hz, samples


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / float(len(samples)))


def _tone_magnitude(samples: list[float], *, sample_rate_hz: int, freq_hz: float) -> float:
    if not samples:
        return 0.0
    cos_acc = 0.0
    sin_acc = 0.0
    for index, sample in enumerate(samples):
        angle = 2.0 * math.pi * freq_hz * index / float(sample_rate_hz)
        cos_acc += float(sample) * math.cos(angle)
        sin_acc += float(sample) * math.sin(angle)
    return math.hypot(cos_acc, sin_acc) / float(len(samples))


class TestLfeCorrectiveApproval(unittest.TestCase):
    def test_lfe_corrective_filter_blocked_without_approval(self) -> None:
        fixture_dir = _FIXTURES_DIR / "lfe_out_of_band"
        lfe_measurements = _lfe_channel_rows_measurements()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            plugins_dir = _write_lfe_plugins_dir(temp / "plugins")
            report_path = temp / "report.json"
            receipt_path = temp / "receipt.json"
            _write_report(
                report_path,
                fixture_dir=fixture_dir,
                lfe_measurements=lfe_measurements,
            )

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "LAYOUT.5_1",
                    "--dry-run",
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            rec_id = _blocked_corrective_rec_id(receipt)
            self.assertEqual(rec_id, "REC.LFE.CORRECTIVE_FILTER.001")
            blocked = receipt.get("blocked_recommendations", [])
            corrective = next(
                (
                    row
                    for row in blocked
                    if isinstance(row, dict)
                    and row.get("recommendation_id") == rec_id
                ),
                None,
            )
            self.assertIsNotNone(corrective)
            if not isinstance(corrective, dict):
                return
            self.assertTrue(corrective.get("requires_approval"))
            self.assertFalse(corrective.get("eligible_render", False))
            self.assertIn("will not silently fold or reroute", corrective.get("notes", ""))

    def test_lfe_corrective_filter_with_approval_applies_and_reruns_qa(self) -> None:
        fixture_dir = _FIXTURES_DIR / "lfe_out_of_band"
        lfe_measurements = _lfe_channel_rows_measurements()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            plugins_dir = _write_lfe_plugins_dir(temp / "plugins")
            report_path = temp / "report.json"
            dry_receipt_path = temp / "receipt.dry.json"
            receipt_path = temp / "receipt.json"
            qa_path = temp / "qa.json"
            out_dir = temp / "renders"
            _write_report(
                report_path,
                fixture_dir=fixture_dir,
                lfe_measurements=lfe_measurements,
            )

            dry_exit_code, _stdout, dry_stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "LAYOUT.5_1",
                    "--dry-run",
                    "--receipt-out",
                    str(dry_receipt_path),
                ]
            )
            self.assertEqual(dry_exit_code, 0, msg=dry_stderr)
            dry_receipt = json.loads(dry_receipt_path.read_text(encoding="utf-8"))
            rec_id = _blocked_corrective_rec_id(dry_receipt)

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "LAYOUT.5_1",
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                    "--qa-out",
                    str(qa_path),
                    "--approve-rec",
                    rec_id,
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIn(
                rec_id,
                [
                    row.get("recommendation_id")
                    for row in receipt.get("approved_by_user", [])
                    if isinstance(row, dict)
                ],
            )
            self.assertIn(
                rec_id,
                [
                    row.get("recommendation_id")
                    for row in receipt.get("applied_recommendations", [])
                    if isinstance(row, dict)
                ],
            )
            self.assertIn("lfe_corrective_qa_rerun_count=1", receipt.get("notes", []))
            post_manifest = _renderer_manifest(receipt, "PLUGIN.RENDERER.LFE_CORRECTIVE_POST")
            self.assertIsNotNone(post_manifest)
            if not isinstance(post_manifest, dict):
                return
            self.assertIn(rec_id, post_manifest.get("received_recommendation_ids", []))

            output = _output_for_stem(receipt, "lfe")
            metadata = output.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertEqual(metadata.get("lfe_corrective_recommendation_id"), rec_id)
            qa_compare = metadata.get("lfe_corrective_qa")
            self.assertIsInstance(qa_compare, dict)
            if not isinstance(qa_compare, dict):
                return
            self.assertTrue(qa_compare.get("passed"))

            rendered_path = out_dir / str(output.get("file_path"))
            fixture_lfe_path = fixture_dir / "lfe.wav"
            fixture_sr, fixture_samples = _read_channel_samples(fixture_lfe_path, channel_index=0)
            rendered_sr, rendered_lfe_samples = _read_channel_samples(rendered_path, channel_index=3)
            before_250 = _tone_magnitude(
                fixture_samples,
                sample_rate_hz=fixture_sr,
                freq_hz=250.0,
            )
            after_250 = _tone_magnitude(
                rendered_lfe_samples,
                sample_rate_hz=rendered_sr,
                freq_hz=250.0,
            )
            self.assertLess(after_250, before_250 * 0.25)

    def test_explicit_lfe_never_silently_folded(self) -> None:
        fixture_dir = _FIXTURES_DIR / "lfe_explicit"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            plugins_dir = _write_lfe_plugins_dir(temp / "plugins")
            report_path = temp / "report.json"
            receipt_path = temp / "receipt.json"
            out_dir = temp / "renders"
            _write_report(
                report_path,
                fixture_dir=fixture_dir,
                lfe_measurements=[],
            )

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--target",
                    "LAYOUT.5_1",
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIn("explicit_lfe_no_silent_fix=true", receipt.get("notes", []))

            output = _output_for_stem(receipt, "lfe")
            rendered_path = out_dir / str(output.get("file_path"))
            _, lfe_channel = _read_channel_samples(rendered_path, channel_index=3)
            lfe_rms = _rms(lfe_channel)
            self.assertGreater(lfe_rms, 0.05)
            for channel_index in (0, 1, 2, 4, 5):
                _, samples = _read_channel_samples(rendered_path, channel_index=channel_index)
                self.assertLess(_rms(samples), lfe_rms * 0.05)
