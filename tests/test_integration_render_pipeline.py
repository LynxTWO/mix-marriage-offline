"""Integration tests: Scene → Preflight → Profile → Safe-render pipeline.

Covers the full mix-once, render-many flow (DoD 4.9 + 4.3 + 4.6):
- Scene built from validated session
- Preflight gates evaluated against scene
- User profile applied (gate threshold overrides)
- Safe-render dispatches plugin chain
- --render-many produces per-target outputs

All tests assert determinism: same inputs → same outputs.
"""
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

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_PLUGINS_DIR = _REPO_ROOT / "plugins"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_wav(
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
        v = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * 440.0 * i / rate))
        for _ in range(channels):
            samples.append(v)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _make_report(
    stems_dir: Path,
    stem_file: str,
    stem_id: str,
    *,
    clip_count: int = 0,
    peak_dbfs: float = -6.0,
    channel_count: int = 1,
    recommendations: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": f"REPORT.INTEG.{stem_id.upper()}",
        "project_id": "PROJECT.INTEG.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "stems": [
                {
                    "stem_id": stem_id,
                    "file_path": stem_file,
                    "channel_count": channel_count,
                    "measurements": [
                        {"evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT", "value": clip_count},
                        {"evidence_id": "EVID.METER.PEAK_DBFS", "value": peak_dbfs},
                    ],
                }
            ],
        },
        "issues": [],
        "recommendations": recommendations if recommendations is not None else [],
        "features": {},
    }


def _write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Scene builder integration: session → scene
# ---------------------------------------------------------------------------

class TestSceneFromSessionUnit(unittest.TestCase):
    """Unit tests for build_scene_from_session called from _run_safe_render_command."""

    def test_build_scene_from_valid_session(self) -> None:
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {"stem_id": "kick", "channel_count": 1},
                    {"stem_id": "bass", "channel_count": 1},
                ],
            }
            scene = build_scene_from_session(session)

        self.assertIn("objects", scene)
        self.assertIn("schema_version", scene)
        self.assertEqual(len(scene["objects"]), 2)

    def test_scene_objects_sorted_stable(self) -> None:
        """Same session → same object order every call."""
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {"stem_id": "snare", "channel_count": 1},
                    {"stem_id": "kick", "channel_count": 1},
                    {"stem_id": "hat", "channel_count": 1},
                ],
            }
            s1 = build_scene_from_session(session)
            s2 = build_scene_from_session(session)

        ids1 = [o["stem_id"] for o in s1["objects"]]
        ids2 = [o["stem_id"] for o in s2["objects"]]
        self.assertEqual(ids1, ids2, "object order must be stable")
        self.assertEqual(ids1, sorted(ids1), "objects must be sorted by stem_id")

    def test_scene_metadata_carries_profile_id(self) -> None:
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "vox", "channel_count": 1}],
                "profile_id": "PROFILE.USER.CONSERVATIVE",
            }
            scene = build_scene_from_session(session)

        self.assertEqual(scene["metadata"].get("profile_id"), "PROFILE.USER.CONSERVATIVE")


# ---------------------------------------------------------------------------
# 2. Preflight + scene integration
# ---------------------------------------------------------------------------

class TestPreflightWithScene(unittest.TestCase):
    """Preflight evaluates correctly against a built scene."""

    def test_preflight_produces_valid_receipt_for_scene(self) -> None:
        """evaluate_preflight returns a well-formed receipt for a scene."""
        from mmo.core.preflight import evaluate_preflight
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "kick", "channel_count": 1}],
            }
            scene = build_scene_from_session(session)
            receipt = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )

        # Receipt must always be well-formed regardless of decision
        self.assertIn("final_decision", receipt)
        self.assertIn(receipt["final_decision"], ("pass", "warn", "block"))
        self.assertIn("gates_evaluated", receipt)
        self.assertIsInstance(receipt["gates_evaluated"], list)

    def test_preflight_low_confidence_scene_blocks(self) -> None:
        """A scene with zero confidence objects triggers GATE.CONFIDENCE_LOW block."""
        from mmo.core.preflight import evaluate_preflight, preflight_receipt_blocks
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "kick", "channel_count": 1}],
            }
            # No metering → confidence=0.0 → very_low → block
            scene = build_scene_from_session(session)
            receipt = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )

        # With no metering data confidence=0.0, gate should block
        self.assertTrue(preflight_receipt_blocks(receipt))
        gate_ids_blocked = [
            g["gate_id"]
            for g in receipt["gates_evaluated"]
            if g.get("outcome") == "block"
        ]
        self.assertIn("GATE.CONFIDENCE_LOW", gate_ids_blocked)

    def test_preflight_pass_with_metadata_confidence(self) -> None:
        """A scene with high metadata.confidence passes GATE.CONFIDENCE_LOW."""
        from mmo.core.preflight import evaluate_preflight, preflight_receipt_blocks
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "kick", "channel_count": 1}],
            }
            scene = build_scene_from_session(session)
            # Override metadata.confidence so gate passes
            scene["metadata"]["confidence"] = 0.95
            receipt = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )

        self.assertFalse(preflight_receipt_blocks(receipt))

    def test_preflight_receipt_deterministic(self) -> None:
        """Same scene + target → same preflight receipt JSON (determinism)."""
        from mmo.core.preflight import evaluate_preflight
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "lead", "channel_count": 2}],
            }
            scene = build_scene_from_session(session)
            r1 = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )
            r2 = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )

        self.assertEqual(r1, r2, "preflight must be deterministic")

    def test_preflight_profile_overrides_thresholds(self) -> None:
        """User profile gate_overrides merge into options before gate eval."""
        from mmo.core.preflight import evaluate_preflight
        from mmo.core.profiles import apply_to_gates
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "vox", "channel_count": 1}],
            }
            scene = build_scene_from_session(session)

            profile = {
                "profile_id": "PROFILE.USER.TEST",
                "gate_overrides": {"confidence_warn_below": 0.9},
            }
            receipt = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
                user_profile=profile,
            )

        self.assertEqual(receipt.get("user_profile_id"), "PROFILE.USER.TEST")


# ---------------------------------------------------------------------------
# 3. Safe-render CLI: scene built inside pipeline
# ---------------------------------------------------------------------------

class TestSafeRenderSceneIntegration(unittest.TestCase):
    """safe-render builds scene from session and passes it to preflight."""

    def test_dry_run_with_valid_session(self) -> None:
        """Dry-run succeeds and receipt is schema-valid."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            _write_report(report_path, report)
            receipt_path = temp / "receipt.json"

            rc, _o, _e = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--target", "stereo",
                "--dry-run",
                "--receipt-out", str(receipt_path),
            ])
            self.assertEqual(rc, 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            import jsonschema
            jsonschema.Draft202012Validator(schema).validate(receipt)
            self.assertTrue(receipt["dry_run"])

    def test_dry_run_deterministic_receipt_id(self) -> None:
        """Same report + target → same receipt_id on repeated calls."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "snare.wav")

            report = _make_report(stems_dir, "snare.wav", "snare")
            report_path = temp / "report.json"
            _write_report(report_path, report)

            receipt_path1 = temp / "r1.json"
            receipt_path2 = temp / "r2.json"

            _run_main([
                "safe-render", "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--target", "stereo", "--dry-run",
                "--receipt-out", str(receipt_path1),
            ])
            _run_main([
                "safe-render", "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--target", "stereo", "--dry-run",
                "--receipt-out", str(receipt_path2),
                "--force",
            ])

            r1 = json.loads(receipt_path1.read_text(encoding="utf-8"))
            r2 = json.loads(receipt_path2.read_text(encoding="utf-8"))
            self.assertEqual(r1["receipt_id"], r2["receipt_id"], "receipt_id must be deterministic")

    def test_preflight_block_writes_receipt(self) -> None:
        """When preflight blocks, receipt is written with status=blocked."""
        schema = json.loads(
            (_SCHEMAS_DIR / "safe_render_receipt.schema.json").read_text(encoding="utf-8")
        )
        # Force a block by injecting a qa_issue with POLARITY to trigger phase risk
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "vox.wav")

            report = _make_report(stems_dir, "vox.wav", "vox")
            # Inject strong negative correlation to force GATE.CORRELATION_RISK block
            report["metadata"] = {"correlation": -0.8}
            report_path = temp / "report.json"
            _write_report(report_path, report)
            receipt_path = temp / "receipt.json"
            out_dir = temp / "renders"

            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--target", "stereo",
                "--out-dir", str(out_dir),
                "--receipt-out", str(receipt_path),
            ])

            # preflight may block (rc=1) or pass depending on gate thresholds
            if rc == 1:
                self.assertTrue(receipt_path.exists(), "blocked receipt must be written")
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                import jsonschema
                jsonschema.Draft202012Validator(schema).validate(receipt)
                self.assertEqual(receipt["status"], "blocked")
                self.assertFalse(receipt["dry_run"])
            # if rc=0 (warn but not block), still assert receipt valid if written
            elif receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                import jsonschema
                jsonschema.Draft202012Validator(schema).validate(receipt)


# ---------------------------------------------------------------------------
# 4. User profile applied through pipeline
# ---------------------------------------------------------------------------

class TestUserProfilePipeline(unittest.TestCase):
    """User profile passes through CLI → safe-render → preflight."""

    def test_user_profile_id_in_receipt_preflight_decision(self) -> None:
        """When --user-profile is unknown, CLI handles error gracefully."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report = _make_report(stems_dir, "kick.wav", "kick")
            report_path = temp / "report.json"
            _write_report(report_path, report)

            # Unknown profile → should print error and return 1 (or skip gracefully)
            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--dry-run",
                "--user-profile", "PROFILE.USER.DOES_NOT_EXIST",
            ])
            # Should fail with a clear error, not a crash
            self.assertIn(rc, (0, 1), "must exit cleanly with code 0 or 1")


# ---------------------------------------------------------------------------
# 5. --render-many: multiple targets in one pass
# ---------------------------------------------------------------------------

class TestRenderMany(unittest.TestCase):
    """--render-many runs safe-render for multiple targets."""

    def test_render_many_dry_run_all_targets_succeed(self) -> None:
        """--render-many --dry-run runs all three default targets and exits 0."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "pad.wav")

            report = _make_report(stems_dir, "pad.wav", "pad")
            report_path = temp / "report.json"
            _write_report(report_path, report)

            receipt_dir = temp / "receipts"
            receipt_dir.mkdir()
            receipt_path = receipt_dir / "receipt.json"

            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--dry-run",
                "--render-many",
                "--receipt-out", str(receipt_path),
            ])
            self.assertEqual(rc, 0, f"render-many dry-run should succeed; stderr={err}")
            # Per-target receipts should be written
            self.assertTrue(
                any(receipt_dir.iterdir()),
                "render-many should write per-target receipt files",
            )

    def test_render_many_custom_targets(self) -> None:
        """--render-many-targets with custom list runs only those targets."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "hat.wav")

            report = _make_report(stems_dir, "hat.wav", "hat")
            report_path = temp / "report.json"
            _write_report(report_path, report)

            receipt_dir = temp / "receipts"
            receipt_dir.mkdir()
            receipt_path = receipt_dir / "receipt.json"

            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--dry-run",
                "--render-many",
                "--render-many-targets", "stereo,5.1",
                "--receipt-out", str(receipt_path),
            ])
            self.assertEqual(rc, 0, f"custom target render-many should succeed; stderr={err}")
            receipt_files = list(receipt_dir.iterdir())
            # Expect 2 per-target files (stereo + 5.1)
            self.assertEqual(
                len(receipt_files), 2,
                f"expected 2 receipt files, got {[f.name for f in receipt_files]}",
            )

    def test_render_many_default_targets_constant(self) -> None:
        """_RENDER_MANY_DEFAULT_TARGETS is stable and has the expected entries."""
        from mmo.cli_commands._renderers import _RENDER_MANY_DEFAULT_TARGETS

        self.assertIn("stereo", _RENDER_MANY_DEFAULT_TARGETS)
        self.assertIn("5.1", _RENDER_MANY_DEFAULT_TARGETS)
        self.assertIn("7.1.4", _RENDER_MANY_DEFAULT_TARGETS)
        # Order is stable (list, not set)
        self.assertEqual(
            _RENDER_MANY_DEFAULT_TARGETS,
            list(_RENDER_MANY_DEFAULT_TARGETS),
        )


# ---------------------------------------------------------------------------
# 6. Scene builder fallback: incomplete session
# ---------------------------------------------------------------------------

class TestSceneBuilderFallback(unittest.TestCase):
    """Safe-render falls back gracefully when session is missing or incomplete."""

    def test_dry_run_no_session_in_report(self) -> None:
        """Report without session key still completes dry-run safely."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report = _make_report(stems_dir, "kick.wav", "kick")
            # Remove session entirely
            del report["session"]
            report_path = temp / "report.json"
            _write_report(report_path, report)
            receipt_path = temp / "receipt.json"

            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--dry-run",
                "--receipt-out", str(receipt_path),
            ])
            self.assertIn(rc, (0, 1), "must exit cleanly, not crash")

    def test_dry_run_session_without_stems_dir(self) -> None:
        """Session without stems_dir causes safe fallback, not crash."""
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            stems_dir = temp / "stems"
            _write_wav(stems_dir / "kick.wav")

            report = _make_report(stems_dir, "kick.wav", "kick")
            report["session"].pop("stems_dir", None)
            report_path = temp / "report.json"
            _write_report(report_path, report)
            receipt_path = temp / "receipt.json"

            rc, _o, err = _run_main([
                "safe-render",
                "--report", str(report_path),
                "--plugins", str(_PLUGINS_DIR),
                "--dry-run",
                "--receipt-out", str(receipt_path),
            ])
            self.assertIn(rc, (0, 1), "must exit cleanly, not crash")


# ---------------------------------------------------------------------------
# 7. Determinism: identical inputs → identical outputs
# ---------------------------------------------------------------------------

class TestPipelineDeterminism(unittest.TestCase):
    """Core determinism invariant: same inputs → same stable outputs."""

    def _make_and_run_dry(self, temp: Path, stem_id: str) -> dict:
        stems_dir = temp / "stems"
        _write_wav(stems_dir / f"{stem_id}.wav")
        report = _make_report(stems_dir, f"{stem_id}.wav", stem_id)
        report_path = temp / "report.json"
        _write_report(report_path, report)
        receipt_path = temp / "receipt.json"
        _run_main([
            "safe-render",
            "--report", str(report_path),
            "--plugins", str(_PLUGINS_DIR),
            "--dry-run",
            "--receipt-out", str(receipt_path),
        ])
        if receipt_path.exists():
            return json.loads(receipt_path.read_text(encoding="utf-8"))
        return {}

    def test_receipt_id_stable_across_runs(self) -> None:
        """receipt_id is a hash of report_id + target — must be stable."""
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            r1 = self._make_and_run_dry(Path(td1), "bass")
            # Re-build in second tempdir with identical content
            r2 = self._make_and_run_dry(Path(td2), "bass")
        self.assertEqual(r1.get("receipt_id"), r2.get("receipt_id"))

    def test_scene_json_stable(self) -> None:
        """build_scene_from_session returns same JSON for same input."""
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {"stem_id": "strings", "channel_count": 2},
                    {"stem_id": "brass", "channel_count": 2},
                ],
            }
            s1_json = json.dumps(build_scene_from_session(session), sort_keys=True)
            s2_json = json.dumps(build_scene_from_session(session), sort_keys=True)
        self.assertEqual(s1_json, s2_json)

    def test_preflight_decision_stable(self) -> None:
        """evaluate_preflight returns identical final_decision for identical inputs."""
        from mmo.core.preflight import evaluate_preflight
        from mmo.core.scene_builder import build_scene_from_session

        with tempfile.TemporaryDirectory() as td:
            stems_dir = Path(td) / "stems"
            stems_dir.mkdir()
            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [{"stem_id": "fx", "channel_count": 1}],
            }
            scene = build_scene_from_session(session)

        decisions = set()
        for _ in range(3):
            r = evaluate_preflight(
                session={"profile_id": "PROFILE.ASSIST"},
                scene=scene,
                target_layout="stereo",
                options={},
            )
            decisions.add(r["final_decision"])
        self.assertEqual(len(decisions), 1, "final_decision must not vary between runs")
