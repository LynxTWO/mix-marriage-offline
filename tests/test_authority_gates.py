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

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"
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


def _report_with_medium_rec(stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.AUTHORITY.GATES.TEST",
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
        "recommendations": [
            {
                "recommendation_id": "REC.TEST.MEDIUM.001",
                "action_id": "ACTION.UTILITY.GAIN",
                "impact": "medium",
                "risk": "medium",
                "requires_approval": False,
                "target": {"scope": "stem", "stem_id": "kick"},
                "params": [
                    {
                        "param_id": "PARAM.GAIN.DB",
                        "value": -1.5,
                        "unit_id": "UNIT.DB",
                    }
                ],
            }
        ],
    }


class TestAuthorityGates(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt_schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )

    def test_medium_impact_recommendation_is_blocked_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(_report_with_medium_rec(stems_dir), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            receipt_path = temp / "receipt.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--dry-run",
                    "--receipt-out",
                    str(receipt_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(receipt)

            self.assertEqual(receipt["recommendations_summary"]["approved_by_user"], 0)
            self.assertEqual(receipt["recommendations_summary"]["applied"], 0)
            self.assertEqual(receipt["approved_by_user"], [])
            self.assertEqual(receipt["applied_recommendations"], [])
            self.assertEqual(len(receipt["blocked_recommendations"]), 1)

            blocked = receipt["blocked_recommendations"][0]
            self.assertEqual(blocked["recommendation_id"], "REC.TEST.MEDIUM.001")
            self.assertEqual(blocked["impact"], "medium")
            self.assertEqual(blocked["scope"], {"stem_id": "kick"})
            self.assertEqual(
                blocked["deltas"],
                [
                    {
                        "param_id": "PARAM.GAIN.DB",
                        "from": None,
                        "to": -1.5,
                        "unit": "UNIT.DB",
                        "confidence": 1.0,
                        "evidence_ref": "REC.TEST.MEDIUM.001",
                    }
                ],
            )
            self.assertEqual(len(blocked["rollback"]), 1)

    def test_medium_impact_recommendation_with_approval_gets_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(_report_with_medium_rec(stems_dir), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            receipt_path = temp / "receipt.json"
            out_dir = temp / "renders"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                    "--approve-rec",
                    "REC.TEST.MEDIUM.001",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(receipt)

            self.assertEqual(receipt["recommendations_summary"]["approved_by_user"], 1)
            self.assertGreaterEqual(receipt["recommendations_summary"]["applied"], 1)
            self.assertEqual(
                [row["recommendation_id"] for row in receipt["approved_by_user"]],
                ["REC.TEST.MEDIUM.001"],
            )
            self.assertIn(
                "REC.TEST.MEDIUM.001",
                [row["recommendation_id"] for row in receipt["applied_recommendations"]],
            )

            applied = next(
                row
                for row in receipt["applied_recommendations"]
                if row["recommendation_id"] == "REC.TEST.MEDIUM.001"
            )
            self.assertEqual(applied["impact"], "medium")
            self.assertEqual(applied["scope"], {"stem_id": "kick"})
            self.assertEqual(applied["deltas"][0]["param_id"], "PARAM.GAIN.DB")
            self.assertEqual(applied["deltas"][0]["to"], -1.5)
            self.assertEqual(applied["rollback"][0]["action"], "capture_and_restore_parameter")

    def test_medium_impact_recommendation_can_be_approved_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report_path = temp / "report.json"
            report_path.write_text(
                json.dumps(_report_with_medium_rec(stems_dir), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            approvals_path = temp / "approvals.json"
            approvals_path.write_text(
                json.dumps(["REC.TEST.MEDIUM.001"], indent=2) + "\n",
                encoding="utf-8",
            )
            receipt_path = temp / "receipt.json"
            out_dir = temp / "renders"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(_PLUGINS_DIR),
                    "--out-dir",
                    str(out_dir),
                    "--receipt-out",
                    str(receipt_path),
                    "--approve-file",
                    str(approvals_path),
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(self.receipt_schema).validate(receipt)
            self.assertEqual(receipt["recommendations_summary"]["approved_by_user"], 1)
            self.assertEqual(
                [row["recommendation_id"] for row in receipt["approved_by_user"]],
                ["REC.TEST.MEDIUM.001"],
            )


if __name__ == "__main__":
    unittest.main()
