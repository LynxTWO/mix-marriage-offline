"""Tests for ``mmo project write-render-request`` CLI command."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT
    / "sandbox_tmp"
    / "test_cli_project_write_render_request"
    / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _init_project(base: Path) -> Path:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")

    project_dir = base / "project"
    exit_code, _, stderr = _run_main(
        [
            "project",
            "init",
            "--stems-root",
            str(stems_root),
            "--out-dir",
            str(project_dir),
        ]
    )
    assert exit_code == 0, f"project init failed: {stderr}"

    exit_code, _, stderr = _run_main(
        [
            "project",
            "render-init",
            str(project_dir),
            "--target-layout",
            "LAYOUT.2_0",
        ]
    )
    assert exit_code == 0, f"project render-init failed: {stderr}"
    return project_dir


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil

    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestProjectWriteRenderRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "project")

    def _write_args(self) -> list[str]:
        return [
            "project",
            "write-render-request",
            str(self.project_dir),
            "--set",
            "dry_run=false",
            "--set",
            "max_theoretical_quality=true",
            "--set",
            "target_ids=TARGET.SURROUND.5_1,TARGET.STEREO.2_0,TARGET.SURROUND.5_1",
            "--set",
            "target_layout_ids=LAYOUT.5_1,LAYOUT.2_0",
            "--set",
            (
                "policies={"
                "\"gates_policy_id\":\"POLICY.GATES.CORE_V0\","
                "\"downmix_policy_id\":\"POLICY.DOWNMIX.STANDARD_FOLDOWN_V0\""
                "}"
            ),
            "--set",
            "plugin_chain=[{\"plugin_id\":\"gain_v0\",\"params\":{\"gain_db\":-3.0}}]",
        ]

    def test_writes_deterministically_with_allowlisted_fields_only(self) -> None:
        exit_a, stdout_a, stderr_a = _run_main(self._write_args())
        self.assertEqual(exit_a, 0, msg=stderr_a)
        request_path = self.project_dir / "renders" / "render_request.json"
        bytes_a = request_path.read_bytes()

        exit_b, stdout_b, stderr_b = _run_main(self._write_args())
        self.assertEqual(exit_b, 0, msg=stderr_b)
        bytes_b = request_path.read_bytes()

        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(bytes_a, bytes_b)

        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertNotIn("target_layout_id", payload)
        self.assertEqual(payload["target_layout_ids"], ["LAYOUT.2_0", "LAYOUT.5_1"])
        self.assertEqual(
            payload["options"]["target_ids"],
            ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
        )
        self.assertFalse(payload["options"]["dry_run"])
        self.assertTrue(payload["options"]["max_theoretical_quality"])
        self.assertEqual(
            payload["options"]["downmix_policy_id"],
            "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        )
        self.assertEqual(
            payload["options"]["gates_policy_id"],
            "POLICY.GATES.CORE_V0",
        )
        self.assertEqual(
            payload["options"]["plugin_chain"],
            [
                {
                    "plugin_id": "gain_v0",
                    "params": {"gain_db": -3.0},
                }
            ],
        )

        summary = json.loads(stdout_a)
        self.assertEqual(
            summary["updated_fields"],
            [
                "dry_run",
                "max_theoretical_quality",
                "plugin_chain",
                "policies",
                "target_ids",
                "target_layout_ids",
            ],
        )

    def test_refuses_unknown_set_key_with_stable_error(self) -> None:
        args = [
            "project",
            "write-render-request",
            str(self.project_dir),
            "--set",
            "scene_path=drafts/scene.draft.json",
        ]
        exit_a, _, stderr_a = _run_main(args)
        exit_b, _, stderr_b = _run_main(args)

        self.assertEqual(exit_a, 1)
        self.assertEqual(exit_b, 1)
        self.assertEqual(stderr_a, stderr_b)
        self.assertIn("Unknown editable field(s): scene_path.", stderr_a)
        self.assertIn(
            (
                "Allowed keys: dry_run, max_theoretical_quality, plugin_chain, "
                "policies, target_ids, target_layout_ids."
            ),
            stderr_a,
        )

    def test_refuses_invalid_plugin_chain_params_with_stable_order(self) -> None:
        args = [
            "project",
            "write-render-request",
            str(self.project_dir),
            "--set",
            (
                "plugin_chain=[{"
                "\"plugin_id\":\"gain_v0\","
                "\"params\":{\"gain_db\":-6.0,\"bypass\":\"yes\",\"macro_mix\":\"bad\",\"junk\":1}"
                "}]"
            ),
        ]
        exit_a, _, stderr_a = _run_main(args)
        exit_b, _, stderr_b = _run_main(args)

        self.assertEqual(exit_a, 1)
        self.assertEqual(exit_b, 1)
        self.assertEqual(stderr_a, stderr_b)
        self.assertIn(
            "plugin_chain validation failed:",
            stderr_a,
        )
        self.assertIn("plugin_chain[1].params has unknown key(s): junk.", stderr_a)
        self.assertIn("plugin_chain[1].params.bypass must be a boolean.", stderr_a)
        self.assertIn("plugin_chain[1].params.macro_mix must be a number.", stderr_a)
        self.assertLess(
            stderr_a.index("unknown key(s): junk"),
            stderr_a.index("params.bypass must be a boolean"),
        )
        self.assertLess(
            stderr_a.index("params.bypass must be a boolean"),
            stderr_a.index("params.macro_mix must be a number"),
        )

    def test_clamps_numeric_plugin_params_and_reports_notes(self) -> None:
        args = [
            "project",
            "write-render-request",
            str(self.project_dir),
            "--set",
            (
                "plugin_chain=[{"
                "\"plugin_id\":\"gain_v0\","
                "\"params\":{\"gain_db\":99.0,\"macro_mix\":200.0}"
                "}]"
            ),
        ]
        exit_code, stdout, stderr = _run_main(args)
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(stderr, "")

        summary = json.loads(stdout)
        self.assertIn("plugin_chain_notes", summary)
        self.assertEqual(
            summary["plugin_chain"],
            [
                {
                    "plugin_id": "gain_v0",
                    "params": {"gain_db": 24.0, "macro_mix": 100.0},
                }
            ],
        )
        self.assertTrue(
            any(
                "plugin_chain[1].params.gain_db clamped from 99.0 to 24.0"
                in note
                for note in summary["plugin_chain_notes"]
            )
        )
        self.assertTrue(
            any(
                "plugin_chain[1].params.macro_mix clamped from 200.0 to 100.0"
                in note
                for note in summary["plugin_chain_notes"]
            )
        )

        request_path = self.project_dir / "renders" / "render_request.json"
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["options"]["plugin_chain"],
            [
                {
                    "plugin_id": "gain_v0",
                    "params": {"gain_db": 24.0, "macro_mix": 100.0},
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
