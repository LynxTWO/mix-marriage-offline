import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.dsp.io import sha256_file


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


def _build_report(
    *,
    report_id: str,
    stems_dir: Path,
    recommendation_id: str,
    gain_db: float,
    channel_count: int | None = None,
) -> dict:
    stem_payload = {
        "stem_id": "kick",
        "file_path": "drums/kick.wav",
    }
    if isinstance(channel_count, int):
        stem_payload["channel_count"] = channel_count

    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [stem_payload],
        },
        "issues": [],
        "recommendations": [
            {
                "recommendation_id": recommendation_id,
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "low",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [
                    {
                        "param_id": "PARAM.GAIN.DB",
                        "value": gain_db,
                    }
                ],
            }
        ],
    }


def _find_renderer_manifest(manifest: dict, renderer_id: str) -> dict | None:
    return next(
        (
            item
            for item in manifest.get("renderer_manifests", [])
            if isinstance(item, dict) and item.get("renderer_id") == renderer_id
        ),
        None,
    )


class TestCliApply(unittest.TestCase):
    def test_apply_builds_routing_plan_from_cli_layout_flags(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "apply_manifest.json"
            out_dir = temp_path / "applied"
            _write_wav_16bit(source_path)

            report = _build_report(
                report_id="REPORT.CLI.APPLY.ROUTING.CLI",
                stems_dir=stems_dir,
                recommendation_id="REC.APPLY.GAIN.ROUTING.CLI",
                gain_db=-2.0,
                channel_count=1,
            )
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "apply",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                    "--source-layout",
                    "LAYOUT.1_0",
                    "--target-layout",
                    "LAYOUT.2_0",
                ]
            )
            self.assertEqual(exit_code, 0)
            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _find_renderer_manifest(manifest, "PLUGIN.RENDERER.GAIN_TRIM")
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return

            output = outputs[0]
            self.assertEqual(output.get("channel_count"), 2)
            metadata = output.get("metadata")
            self.assertIsInstance(metadata, dict)
            if not isinstance(metadata, dict):
                return
            self.assertTrue(metadata.get("routing_applied"))
            self.assertEqual(metadata.get("source_layout_id"), "LAYOUT.1_0")
            self.assertEqual(metadata.get("target_layout_id"), "LAYOUT.2_0")

            output_file = out_dir / Path(output["file_path"])
            self.assertTrue(output_file.exists())
            with wave.open(str(output_file), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 2)

    def test_apply_writes_output_and_manifest_hash(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (repo_root / "schemas" / "apply_manifest.schema.json").read_text(encoding="utf-8")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "apply_manifest.json"
            out_dir = temp_path / "applied"
            _write_wav_16bit(source_path)

            report = _build_report(
                report_id="REPORT.CLI.APPLY.GAIN",
                stems_dir=stems_dir,
                recommendation_id="REC.APPLY.GAIN.001",
                gain_db=-2.0,
            )
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "apply",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_manifest_path.exists())

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(manifest)
            self.assertEqual(manifest.get("context"), "auto_apply")

            gain_manifest = _find_renderer_manifest(manifest, "PLUGIN.RENDERER.GAIN_TRIM")
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return

            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return

            output = outputs[0]
            output_file = out_dir / Path(output["file_path"])
            self.assertTrue(output_file.exists())
            self.assertEqual(output["sha256"], sha256_file(output_file))
            self.assertEqual(output["target_stem_id"], "kick")

    def test_apply_with_out_report_rewrites_stems_dir_and_stem_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "apply_manifest.json"
            out_report_path = temp_path / "report_applied.json"
            out_dir = temp_path / "applied"
            _write_wav_16bit(source_path)

            report = _build_report(
                report_id="REPORT.CLI.APPLY.OUT.REPORT",
                stems_dir=stems_dir,
                recommendation_id="REC.APPLY.GAIN.002",
                gain_db=-2.0,
            )
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "apply",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                    "--out-report",
                    str(out_report_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_manifest_path.exists())
            self.assertTrue(out_report_path.exists())

            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))
            gain_manifest = _find_renderer_manifest(manifest, "PLUGIN.RENDERER.GAIN_TRIM")
            self.assertIsNotNone(gain_manifest)
            if gain_manifest is None:
                return
            outputs = gain_manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            self.assertEqual(len(outputs), 1)
            if not isinstance(outputs, list) or not outputs:
                return
            output = outputs[0]

            updated_report = json.loads(out_report_path.read_text(encoding="utf-8"))
            session = updated_report.get("session")
            self.assertIsInstance(session, dict)
            if not isinstance(session, dict):
                return
            self.assertEqual(session.get("stems_dir"), out_dir.resolve().as_posix())
            stems = session.get("stems")
            self.assertIsInstance(stems, list)
            if not isinstance(stems, list) or not stems:
                return
            stem = stems[0]
            self.assertEqual(stem.get("stem_id"), "kick")
            self.assertEqual(stem.get("file_path"), output.get("file_path"))
            self.assertEqual(stem.get("sha256"), output.get("sha256"))

            output_file = out_dir / Path(stem["file_path"])
            self.assertTrue(output_file.exists())
            self.assertEqual(stem["sha256"], sha256_file(output_file))

            original_report = json.loads(report_path.read_text(encoding="utf-8"))
            original_session = original_report.get("session", {})
            self.assertEqual(original_session.get("stems_dir"), stems_dir.resolve().as_posix())
            original_stems = original_session.get("stems", [])
            self.assertEqual(original_stems[0].get("file_path"), "drums/kick.wav")

    def test_apply_blocks_assist_gain_that_is_render_eligible(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            report_path = temp_path / "report.json"
            out_manifest_path = temp_path / "apply_manifest.json"
            out_dir = temp_path / "applied"
            _write_wav_16bit(source_path)

            report = _build_report(
                report_id="REPORT.CLI.APPLY.BLOCKED",
                stems_dir=stems_dir,
                recommendation_id="REC.APPLY.GAIN.BLOCKED",
                gain_db=-8.0,
            )
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "apply",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out-manifest",
                    str(out_manifest_path),
                    "--out-dir",
                    str(out_dir),
                    "--profile",
                    "PROFILE.ASSIST",
                ]
            )
            self.assertEqual(exit_code, 0)
            manifest = json.loads(out_manifest_path.read_text(encoding="utf-8"))

            safe_manifest = _find_renderer_manifest(manifest, "PLUGIN.RENDERER.SAFE")
            self.assertIsNotNone(safe_manifest)
            if safe_manifest is None:
                return
            self.assertEqual(safe_manifest.get("received_recommendation_ids"), [])

            skipped = safe_manifest.get("skipped")
            self.assertIsInstance(skipped, list)
            if not isinstance(skipped, list):
                return
            blocked = next(
                (
                    item
                    for item in skipped
                    if isinstance(item, dict)
                    and item.get("recommendation_id") == "REC.APPLY.GAIN.BLOCKED"
                    and item.get("reason") == "blocked_by_gates"
                ),
                None,
            )
            self.assertIsNotNone(blocked)
            if blocked is None:
                return
            summary = blocked.get("gate_summary", "")
            self.assertIn("auto_apply:", summary)
            self.assertNotIn("render:", summary)
            self.assertIn("GATE.MAX_GAIN_DB", summary)


if __name__ == "__main__":
    unittest.main()
