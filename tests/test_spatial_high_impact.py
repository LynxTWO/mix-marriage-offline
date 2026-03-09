from __future__ import annotations

import contextlib
import io
import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.core.gates import apply_gates_to_report

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_wav(path: Path, *, amplitude: float = 0.45) -> None:
    rate = 48000
    frames = int(rate * 0.1)
    samples: list[int] = []
    for i in range(frames):
        value = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * 220.0 * i / rate))
        samples.append(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_stub_only_plugins_dir(path: Path) -> Path:
    renderers_dir = path / "renderers"
    renderers_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _REPO_ROOT / "plugins" / "renderers" / "safe_renderer.plugin.yaml"
    renderers_dir.joinpath(source_manifest.name).write_text(
        source_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _scene_payload(stems_dir: Path) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.TEST.SPATIAL.HIGH_IMPACT",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "draft",
        },
        "intent": {
            "confidence": 0.0,
            "locks": [],
        },
        "objects": [
            {
                "object_id": "OBJ.kick",
                "stem_id": "kick",
                "role_id": "ROLE.DRUM.KICK",
                "group_bus": "BUS.DRUMS",
                "label": "Kick",
                "channel_count": 1,
                "confidence": 0.9,
                "intent": {
                    "confidence": 0.9,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "beds": [],
        "metadata": {
            "profile_id": "PROFILE.ASSIST",
        },
    }


def _report_payload(stems_dir: Path, recommendations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.TEST.SPATIAL.HIGH_IMPACT",
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": "kick",
                    "file_path": "kick.wav",
                    "channel_count": 1,
                }
            ],
        },
        "issues": [],
        "recommendations": recommendations,
    }


def _classification_rec() -> dict[str, object]:
    rec_id = "REC.SPATIAL.CLASSIFY.001"
    return {
        "recommendation_id": rec_id,
        "action_id": "ACTION.SCENE.CLASSIFY",
        "risk": "low",
        "requires_approval": False,
        "target": {"scope": "stem", "stem_id": "kick"},
        "params": [
            {
                "param_id": "PARAM.SCENE.CLASSIFICATION",
                "value": "bed",
                "unit_id": "UNIT.NONE",
            }
        ],
        "deltas": [
            {
                "param_id": "PARAM.SCENE.CLASSIFICATION",
                "from": "object",
                "to": "bed",
                "unit": "UNIT.NONE",
                "confidence": 1.0,
                "evidence_ref": rec_id,
            }
        ],
    }


def _surround_send_rec() -> dict[str, object]:
    rec_id = "REC.SPATIAL.SURROUND.001"
    target_caps = {"side_max_gain": 0.08, "rear_max_gain": 0.06}
    return {
        "recommendation_id": rec_id,
        "action_id": "ACTION.UTILITY.PAN",
        "risk": "low",
        "requires_approval": False,
        "target": {"scope": "stem", "stem_id": "kick"},
        "params": [
            {
                "param_id": "PARAM.SPATIAL.SURROUND_SEND_CAPS",
                "value": target_caps,
                "unit_id": "UNIT.NONE",
            }
        ],
        "deltas": [
            {
                "param_id": "PARAM.SPATIAL.SURROUND_SEND_CAPS",
                "from": {"side_max_gain": 0.0, "rear_max_gain": 0.0},
                "to": target_caps,
                "unit": "UNIT.NONE",
                "confidence": 1.0,
                "evidence_ref": rec_id,
            }
        ],
    }


class TestSpatialHighImpact(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt_schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )

    def test_object_to_bed_change_requires_lock_or_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            scene_path = temp / "scene.json"
            scene_path.write_text(
                json.dumps(_scene_payload(stems_dir), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(_report_payload(stems_dir, [_classification_rec()]), indent=2) + "\n",
                encoding="utf-8",
            )
            plugins_dir = _write_stub_only_plugins_dir(temp / "plugins")
            blocked_receipt_path = temp / "receipt_blocked.json"

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
                    "stereo",
                    "--dry-run",
                    "--receipt-out",
                    str(blocked_receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            blocked_receipt = json.loads(blocked_receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(blocked_receipt)
            blocked = blocked_receipt["blocked_recommendations"]
            self.assertEqual(len(blocked), 1)
            blocked_entry = blocked[0]
            self.assertEqual(
                blocked_entry.get("required_lock_ids"),
                ["scene_build_override:kick:bus_id"],
            )
            self.assertTrue(blocked_entry.get("spatial_change"))
            self.assertEqual(blocked_entry.get("impact"), "high")
            self.assertTrue(blocked_entry.get("requires_approval"))
            self.assertIn(
                "REASON.SPATIAL_LOCK_OR_APPROVAL_REQUIRED",
                blocked_entry.get("gate_summary", ""),
            )
            self.assertIn(
                "scene_build_override:kick:bus_id",
                blocked_entry.get("notes", ""),
            )
            self.assertIn("approve this recommendation", blocked_entry.get("notes", ""))

            approved_receipt_path = temp / "receipt_approved.json"
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
                    "stereo",
                    "--dry-run",
                    "--approve-rec",
                    "REC.SPATIAL.CLASSIFY.001",
                    "--receipt-out",
                    str(approved_receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            approved_receipt = json.loads(approved_receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(approved_receipt)
            self.assertEqual(approved_receipt["recommendations_summary"]["approved_by_user"], 1)
            self.assertEqual(approved_receipt["blocked_recommendations"], [])
            self.assertEqual(
                [row["recommendation_id"] for row in approved_receipt["approved_by_user"]],
                ["REC.SPATIAL.CLASSIFY.001"],
            )

    def test_surround_send_change_requires_lock_or_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            scene_path = temp / "scene.json"
            scene_path.write_text(
                json.dumps(_scene_payload(stems_dir), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(_report_payload(stems_dir, [_surround_send_rec()]), indent=2) + "\n",
                encoding="utf-8",
            )
            plugins_dir = _write_stub_only_plugins_dir(temp / "plugins")
            blocked_receipt_path = temp / "receipt_blocked.json"

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
                    "stereo",
                    "--dry-run",
                    "--receipt-out",
                    str(blocked_receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            blocked_receipt = json.loads(blocked_receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(blocked_receipt)
            blocked_entry = blocked_receipt["blocked_recommendations"][0]
            self.assertEqual(
                blocked_entry.get("required_lock_ids"),
                ["scene_build_override:kick:surround_send_caps"],
            )
            self.assertEqual(blocked_entry.get("impact"), "high")

            scene_locks_path = temp / "scene_locks.yaml"
            scene_locks_path.write_text(
                "\n".join(
                    [
                        'version: "0.1.0"',
                        "overrides:",
                        "  kick:",
                        "    surround_send_caps:",
                        "      side_max_gain: 0.08",
                        "      rear_max_gain: 0.06",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            unlocked_receipt_path = temp / "receipt_locked.json"
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
                    "--target",
                    "stereo",
                    "--dry-run",
                    "--receipt-out",
                    str(unlocked_receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            unlocked_receipt = json.loads(unlocked_receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(unlocked_receipt)
            self.assertEqual(unlocked_receipt["blocked_recommendations"], [])
            eligible_entry = unlocked_receipt["eligible_recommendations"][0]
            self.assertEqual(eligible_entry.get("impact"), "low")
            self.assertIn("matches explicit intent lock", eligible_entry.get("notes", ""))

    def test_permissive_profile_can_keep_spatial_change_eligible_without_lock(self) -> None:
        report = _report_payload(Path("/tmp/ignored"), [_classification_rec()])
        scene_payload = _scene_payload(Path("/tmp/ignored"))

        apply_gates_to_report(
            report,
            policy_path=Path("ontology/policies/gates.yaml"),
            profile_id="PROFILE.FULL_SEND",
            profiles_path=Path("ontology/policies/authority_profiles.yaml"),
            scene_payload=scene_payload,
        )

        recommendation = report["recommendations"][0]
        self.assertTrue(recommendation["eligible_auto_apply"])
        self.assertTrue(recommendation["eligible_render"])
        self.assertEqual(recommendation["impact"], "low")
        self.assertEqual(
            recommendation.get("required_lock_ids"),
            ["scene_build_override:kick:bus_id"],
        )
        self.assertIn("PROFILE.FULL_SEND", recommendation.get("notes", ""))


if __name__ == "__main__":
    unittest.main()
