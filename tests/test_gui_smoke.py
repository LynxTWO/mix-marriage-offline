"""Smoke + determinism parity tests for the CustomTkinter GUI wrapper."""

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

from mmo.cli import main as cli_main
from mmo.gui.main import (
    _build_target_picker_map,
    _try_cli_passthrough,
    GuiPipelinePaths,
    GuiRunConfig,
    build_plugin_discover_cards,
    build_pipeline_cli_argvs,
    build_safe_render_cli_argv,
    build_watch_cli_argv,
    has_high_risk_blocked_recommendations,
    main as gui_main,
    normalize_render_many_layout_ids,
    render_target_layout_map,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = (_REPO_ROOT / "plugins").resolve()


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = cli_main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_wav(path: Path, *, rate: int = 48000, duration_s: float = 0.1) -> None:
    frames = max(8, int(rate * duration_s))
    samples = [
        int(0.35 * 32767.0 * math.sin(2.0 * math.pi * 220.0 * i / rate))
        for i in range(frames)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_report(path: Path, stems_dir: Path) -> None:
    payload = {
        "schema_version": "0.1.0",
        "report_id": "REPORT.GUI.SMOKE",
        "project_id": "PROJECT.GUI.SMOKE",
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
        "recommendations": [],
        "features": {},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestGuiSmoke(unittest.TestCase):
    def test_gui_entrypoint_smoke_flag_exits_zero_without_tk_launch(self) -> None:
        self.assertEqual(gui_main(["--smoke"]), 0)

    def test_render_many_layout_ids_are_sorted_and_deterministic(self) -> None:
        target_layouts = {
            "TARGET.STEREO.2_0": "LAYOUT.2_0",
            "TARGET.STEREO.2_0_ALT": "LAYOUT.2_0",
            "TARGET.SURROUND.5_1": "LAYOUT.5_1",
            "TARGET.SURROUND.7_1": "LAYOUT.7_1",
        }
        tokens = (
            "TARGET.SURROUND.7_1",
            "TARGET.STEREO.2_0_ALT",
            "LAYOUT.5_1",
            "stereo",
            "5.1",
        )
        first = normalize_render_many_layout_ids(tokens, target_layouts=target_layouts)
        second = normalize_render_many_layout_ids(tokens, target_layouts=target_layouts)
        self.assertEqual(first, second)
        self.assertEqual(first, ("LAYOUT.2_0", "LAYOUT.5_1", "LAYOUT.7_1"))

    def test_pipeline_cli_args_are_stable_and_include_required_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            config = GuiRunConfig(
                stems_dir=temp_root / "stems",
                out_dir=temp_root / "out",
                target_id="TARGET.STEREO.2_0",
                render_many=True,
                render_many_target_ids=(
                    "TARGET.SURROUND.7_1",
                    "TARGET.STEREO.2_0",
                    "TARGET.SURROUND.5_1",
                ),
                layout_standard="FILM",
                preview_headphones=False,
                plugins_dir=_PLUGINS_DIR,
            )
            workspace = temp_root / "work"
            first = build_pipeline_cli_argvs(config, workspace_dir=workspace, approve=None)
            second = build_pipeline_cli_argvs(config, workspace_dir=workspace, approve=None)
            self.assertEqual(first[:3], second[:3])
            analyze_argv, dry_argv, final_argv, _paths = first

            self.assertIn("--render-many", dry_argv)
            self.assertIn("--render-many-targets", dry_argv)
            csv_idx = dry_argv.index("--render-many-targets")
            self.assertEqual(
                dry_argv[csv_idx + 1],
                "LAYOUT.2_0,LAYOUT.5_1,LAYOUT.7_1",
            )
            self.assertIn("--layout-standard", final_argv)
            layout_idx = final_argv.index("--layout-standard")
            self.assertEqual(final_argv[layout_idx + 1], "FILM")
            self.assertIn("--out-report", analyze_argv)

    def test_watch_cli_args_include_targets_and_once_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            watch_dir = temp_root / "incoming"
            out_dir = temp_root / "watch_out"
            first = build_watch_cli_argv(
                watch_dir,
                out_dir=out_dir,
                target_ids=("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
                once=True,
                include_existing=False,
            )
            second = build_watch_cli_argv(
                watch_dir,
                out_dir=out_dir,
                target_ids=("TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"),
                once=True,
                include_existing=False,
            )

            self.assertEqual(first, second)
            self.assertEqual(first[0], "watch")
            self.assertIn("--out", first)
            self.assertIn("--targets", first)
            self.assertIn("TARGET.STEREO.2_0,TARGET.SURROUND.5_1", first)
            self.assertIn("--once", first)
            self.assertIn("--no-existing", first)

    def test_watch_cli_args_support_visual_queue_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            watch_dir = temp_root / "incoming"
            argv = build_watch_cli_argv(
                watch_dir,
                visual_queue=True,
                cinematic_progress=True,
            )
            self.assertIn("--visual-queue", argv)
            self.assertIn("--cinematic-progress", argv)

    def test_plugin_discover_cards_are_sorted_and_deterministic(self) -> None:
        payload = {
            "entries": [
                {
                    "plugin_id": "PLUGIN.RENDERER.SAFE",
                    "plugin_type": "renderer",
                    "name": "Safe Renderer",
                    "summary": "Conservative deterministic rendering.",
                    "version": "0.1.0",
                    "tags": ["render", "safety"],
                    "preview": {
                        "tagline": "Bounded-authority final print path.",
                        "gradient": "sunset",
                        "chips": ["Safe", "Render", "Deterministic"],
                    },
                    "install_state": "available",
                    "installable": True,
                },
                {
                    "plugin_id": "PLUGIN.DETECTOR.MUD",
                    "plugin_type": "detector",
                    "name": "Mud Detector",
                    "summary": "Find low-mid masking.",
                    "version": "0.1.0",
                    "tags": ["analysis", "tonal"],
                    "install_state": "installed",
                    "installable": True,
                },
            ]
        }
        first = build_plugin_discover_cards(payload)
        second = build_plugin_discover_cards(payload)
        self.assertEqual(first, second)
        self.assertEqual(tuple(card.plugin_id for card in first), ("PLUGIN.DETECTOR.MUD", "PLUGIN.RENDERER.SAFE"))
        self.assertEqual(first[0].preview_gradient, "ember")
        self.assertEqual(first[1].preview_gradient, "sunset")

    def test_cli_and_gui_safe_render_dry_run_parity_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            stems_dir = temp_root / "stems"
            _write_wav(stems_dir / "kick.wav")

            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            paths = GuiPipelinePaths(
                report_path=workspace / "report.json",
                dry_receipt_path=workspace / "receipt.json",
                final_receipt_path=workspace / "receipt.final.json",
                dry_manifest_path=workspace / "manifest.json",
                final_manifest_path=workspace / "manifest.final.json",
                cancel_token_path=workspace / "cancel.token",
            )
            _write_report(paths.report_path, stems_dir)

            config = GuiRunConfig(
                stems_dir=stems_dir,
                out_dir=temp_root / "out",
                target_id="TARGET.STEREO.2_0",
                render_many=False,
                render_many_target_ids=(),
                layout_standard="SMPTE",
                preview_headphones=False,
                plugins_dir=_PLUGINS_DIR,
            )
            config.out_dir.mkdir(parents=True, exist_ok=True)

            gui_dry_argv = build_safe_render_cli_argv(
                config,
                paths,
                dry_run=True,
                approve=None,
            )
            manual_dry_argv = [
                "safe-render",
                "--report",
                paths.report_path.resolve().as_posix(),
                "--plugins",
                _PLUGINS_DIR.resolve().as_posix(),
                "--profile",
                "PROFILE.ASSIST",
                "--layout-standard",
                "SMPTE",
                "--out-dir",
                config.out_dir.resolve().as_posix(),
                "--out-manifest",
                paths.dry_manifest_path.resolve().as_posix(),
                "--receipt-out",
                paths.dry_receipt_path.resolve().as_posix(),
                "--force",
                "--dry-run",
                "--target",
                "LAYOUT.2_0",
            ]
            self.assertEqual(gui_dry_argv, manual_dry_argv)

            exit_a, stdout_a, stderr_a = _run_main(gui_dry_argv)
            self.assertEqual(exit_a, 0, msg=stderr_a)
            bytes_a = paths.dry_receipt_path.read_bytes()

            exit_b, stdout_b, stderr_b = _run_main(manual_dry_argv)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            bytes_b = paths.dry_receipt_path.read_bytes()

            self.assertEqual(stdout_a, stdout_b)
            self.assertEqual(stderr_a, stderr_b)
            self.assertEqual(bytes_a, bytes_b)

    def test_preview_headphones_flag_is_forwarded_to_safe_render_argv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            config = GuiRunConfig(
                stems_dir=temp_root / "stems",
                out_dir=temp_root / "out",
                target_id="TARGET.STEREO.2_0",
                render_many=False,
                render_many_target_ids=(),
                layout_standard="SMPTE",
                preview_headphones=True,
                plugins_dir=_PLUGINS_DIR,
            )
            workspace = temp_root / "workspace"
            paths = GuiPipelinePaths(
                report_path=workspace / "report.json",
                dry_receipt_path=workspace / "dry.receipt.json",
                final_receipt_path=workspace / "final.receipt.json",
                dry_manifest_path=workspace / "dry.manifest.json",
                final_manifest_path=workspace / "final.manifest.json",
                cancel_token_path=workspace / "cancel.token",
            )
            argv = build_safe_render_cli_argv(
                config,
                paths,
                dry_run=True,
                approve=None,
            )
            self.assertIn("--preview-headphones", argv)

    def test_binaural_target_picker_label_resolves_to_binaural_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            config = GuiRunConfig(
                stems_dir=temp_root / "stems",
                out_dir=temp_root / "out",
                target_id="Binaural (headphones)",
                render_many=False,
                render_many_target_ids=(),
                layout_standard="SMPTE",
                preview_headphones=False,
                plugins_dir=_PLUGINS_DIR,
            )
            workspace = temp_root / "workspace"
            paths = GuiPipelinePaths(
                report_path=workspace / "report.json",
                dry_receipt_path=workspace / "dry.receipt.json",
                final_receipt_path=workspace / "final.receipt.json",
                dry_manifest_path=workspace / "dry.manifest.json",
                final_manifest_path=workspace / "final.manifest.json",
                cancel_token_path=workspace / "cancel.token",
            )
            argv = build_safe_render_cli_argv(
                config,
                paths,
                dry_run=True,
                approve=None,
            )
            target_idx = argv.index("--target")
            self.assertEqual(argv[target_idx + 1], "LAYOUT.BINAURAL")

    def test_high_risk_detection_helper(self) -> None:
        self.assertTrue(
            has_high_risk_blocked_recommendations(
                {"blocked_recommendations": [{"risk": "high"}]}
            )
        )
        self.assertFalse(
            has_high_risk_blocked_recommendations(
                {"blocked_recommendations": [{"risk": "medium"}]}
            )
        )
        self.assertFalse(has_high_risk_blocked_recommendations({}))

    def test_render_targets_registry_map_has_core_targets(self) -> None:
        target_layouts = render_target_layout_map()
        self.assertEqual(
            target_layouts.get("TARGET.HEADPHONES.BINAURAL"),
            "LAYOUT.BINAURAL",
        )
        self.assertEqual(target_layouts.get("TARGET.STEREO.2_1"), "LAYOUT.2_1")
        self.assertEqual(target_layouts.get("TARGET.FRONT.3_0"), "LAYOUT.3_0")
        self.assertEqual(target_layouts.get("TARGET.FRONT.3_1"), "LAYOUT.3_1")
        self.assertEqual(target_layouts.get("TARGET.SURROUND.4_0"), "LAYOUT.4_0")
        self.assertEqual(target_layouts.get("TARGET.SURROUND.4_1"), "LAYOUT.4_1")
        self.assertEqual(target_layouts.get("TARGET.STEREO.2_0"), "LAYOUT.2_0")
        self.assertEqual(target_layouts.get("TARGET.SURROUND.5_1"), "LAYOUT.5_1")
        self.assertEqual(target_layouts.get("TARGET.SURROUND.7_1"), "LAYOUT.7_1")

    def test_target_picker_labels_sort_deterministically(self) -> None:
        picker_map = _build_target_picker_map(
            (
                "TARGET.SURROUND.7_1",
                "TARGET.FRONT.3_1",
                "TARGET.STEREO.2_1",
                "TARGET.HEADPHONES.BINAURAL",
                "TARGET.SURROUND.4_0",
                "TARGET.STEREO.2_0",
            )
        )
        self.assertEqual(
            tuple(sorted(picker_map)),
            (
                "Binaural (headphones)",
                "LCR + LFE (3.1)",
                "Quad (4.0)",
                "Stereo (2.0)",
                "Stereo + LFE (2.1)",
                "Surround (7.1)",
            ),
        )


class TestGuiCliPassthrough(unittest.TestCase):
    def test_passthrough_dispatches_help_and_returns_zero(self) -> None:
        rc = _try_cli_passthrough(["-m", "mmo", "--help"])
        self.assertEqual(rc, 0)

    def test_passthrough_dispatches_tool_help_and_returns_zero(self) -> None:
        for module in (
            "mmo.tools.analyze_stems",
            "mmo.tools.scan_session",
            "mmo.tools.export_report",
        ):
            with self.subTest(module=module):
                rc = _try_cli_passthrough(["-m", module, "--help"])
                self.assertEqual(rc, 0)

    def test_passthrough_returns_none_for_smoke_flag(self) -> None:
        self.assertIsNone(_try_cli_passthrough(["--smoke"]))

    def test_passthrough_returns_none_for_empty_argv(self) -> None:
        self.assertIsNone(_try_cli_passthrough([]))

    def test_passthrough_returns_none_when_m_without_mmo(self) -> None:
        self.assertIsNone(_try_cli_passthrough(["-m", "other"]))

    def test_main_passthrough_dispatches_mmo_help_and_returns_zero(self) -> None:
        self.assertEqual(gui_main(["-m", "mmo", "--help"]), 0)

    def test_main_passthrough_dispatches_tools_help_and_returns_zero(self) -> None:
        for module in (
            "mmo.tools.analyze_stems",
            "mmo.tools.scan_session",
            "mmo.tools.export_report",
        ):
            with self.subTest(module=module):
                self.assertEqual(gui_main(["-m", module, "--help"]), 0)

    def test_main_smoke_is_unaffected_by_passthrough(self) -> None:
        # --smoke must still exit 0 without launching Tk or dispatching CLI.
        self.assertEqual(gui_main(["--smoke"]), 0)


if __name__ == "__main__":
    unittest.main()
