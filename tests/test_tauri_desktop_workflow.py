"""Regression checks for the Tauri desktop sidecar workflow surface."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import os
import re
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAURI_ROOT = _REPO_ROOT / "gui" / "desktop-tauri"


def _load_packaged_smoke_module():
    module_path = _REPO_ROOT / "tools" / "smoke_packaged_desktop.py"
    spec = importlib.util.spec_from_file_location("smoke_packaged_desktop", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load smoke_packaged_desktop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PACKAGED_SMOKE = _load_packaged_smoke_module()


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    original_cwd = Path.cwd()
    try:
        os.chdir(_REPO_ROOT)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
    finally:
        os.chdir(original_cwd)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_wave(
    path: Path,
    *,
    channels: int,
    frequency_hz: float,
    phase_offset: float = 0.0,
    duration_s: float = 0.18,
    sample_rate_hz: int = 44_100,
) -> None:
    frames = max(128, int(duration_s * sample_rate_hz))
    samples: list[int] = []
    for index in range(frames):
        base = 0.32 * math.sin((2.0 * math.pi * frequency_hz * index / sample_rate_hz) + phase_offset)
        for channel_index in range(channels):
            sample = base if channel_index == 0 else 0.28 * math.sin(
                (2.0 * math.pi * (frequency_hz * 1.01) * index / sample_rate_hz) + phase_offset
            )
            samples.append(int(max(-1.0, min(1.0, sample)) * 32767.0))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(b"".join(sample.to_bytes(2, byteorder="little", signed=True) for sample in samples))


def _desktop_workflow_paths(workspace_dir: Path) -> dict[str, Path]:
    project_dir = workspace_dir / "project"
    return {
        "workspaceDir": workspace_dir,
        "busPlanCsvPath": workspace_dir / "bus_plan.summary.csv",
        "busPlanPath": workspace_dir / "bus_plan.json",
        "projectDir": project_dir,
        "projectValidationPath": project_dir / "validation.json",
        "renderDir": workspace_dir / "render",
        "renderManifestPath": workspace_dir / "render_manifest.json",
        "renderQaPath": workspace_dir / "render_qa.json",
        "renderReceiptPath": workspace_dir / "safe_render_receipt.json",
        "reportPath": workspace_dir / "report.json",
        "scanReportPath": workspace_dir / "report.scan.json",
        "sceneLintPath": workspace_dir / "scene_lint.json",
        "scenePath": workspace_dir / "scene.json",
        "stemsMapPath": workspace_dir / "stems_map.json",
    }


def _render_artifact_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {
        "renderManifestPath": paths["renderManifestPath"].as_posix(),
        "renderQaPath": paths["renderQaPath"].as_posix(),
        "renderReceiptPath": paths["renderReceiptPath"].as_posix(),
        "workspaceDir": paths["workspaceDir"].as_posix(),
    }


def _run_desktop_cli_workflow(*, stems_dir: Path, workspace_dir: Path) -> dict[str, Path]:
    paths = _desktop_workflow_paths(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    commands = (
        (
            "stems classify",
            [
                "stems",
                "classify",
                "--root",
                str(stems_dir),
                "--out",
                str(paths["stemsMapPath"]),
            ],
        ),
        (
            "stems bus-plan",
            [
                "stems",
                "bus-plan",
                "--map",
                str(paths["stemsMapPath"]),
                "--out",
                str(paths["busPlanPath"]),
                "--csv",
                str(paths["busPlanCsvPath"]),
            ],
        ),
        (
            "scene build",
            [
                "scene",
                "build",
                "--map",
                str(paths["stemsMapPath"]),
                "--bus",
                str(paths["busPlanPath"]),
                "--out",
                str(paths["scenePath"]),
                "--profile",
                "PROFILE.ASSIST",
            ],
        ),
        (
            "scene lint",
            [
                "scene",
                "lint",
                "--scene",
                str(paths["scenePath"]),
                "--out",
                str(paths["sceneLintPath"]),
            ],
        ),
        (
            "analyze",
            [
                "analyze",
                str(stems_dir),
                "--out-report",
                str(paths["reportPath"]),
                "--cache",
                "off",
                "--keep-scan",
            ],
        ),
        (
            "safe-render",
            [
                "safe-render",
                "--report",
                str(paths["reportPath"]),
                "--scene",
                str(paths["scenePath"]),
                "--target",
                "TARGET.STEREO.2_0",
                "--out-dir",
                str(paths["renderDir"]),
                "--out-manifest",
                str(paths["renderManifestPath"]),
                "--receipt-out",
                str(paths["renderReceiptPath"]),
                "--qa-out",
                str(paths["renderQaPath"]),
                "--layout-standard",
                "SMPTE",
                "--force",
            ],
        ),
    )

    for label, command in commands:
        exit_code, _stdout, stderr = _run_main(command)
        if exit_code != 0:
            raise AssertionError(f"{label} failed:\n{stderr}")
    return paths


def _scene_stem_ids(scene_payload: dict[str, object]) -> set[str]:
    stem_ids: set[str] = set()
    objects = scene_payload.get("objects")
    if isinstance(objects, list):
        for row in objects:
            if isinstance(row, dict) and isinstance(row.get("stem_id"), str):
                stem_ids.add(row["stem_id"])
    beds = scene_payload.get("beds")
    if isinstance(beds, list):
        for row in beds:
            if not isinstance(row, dict):
                continue
            stem_rows = row.get("stem_ids")
            if not isinstance(stem_rows, list):
                continue
            for stem_id in stem_rows:
                if isinstance(stem_id, str):
                    stem_ids.add(stem_id)
    return stem_ids


def _session_stem_ids(report_payload: dict[str, object]) -> set[str]:
    session = report_payload.get("session")
    if not isinstance(session, dict):
        return set()
    stems = session.get("stems")
    if not isinstance(stems, list):
        return set()
    return {
        row["stem_id"]
        for row in stems
        if isinstance(row, dict) and isinstance(row.get("stem_id"), str)
    }


class TestTauriDesktopWorkflow(unittest.TestCase):
    def test_capabilities_allow_sidecar_execute_and_spawn(self) -> None:
        capability_path = _TAURI_ROOT / "src-tauri" / "capabilities" / "default.json"
        payload = json.loads(capability_path.read_text(encoding="utf-8"))
        permissions = payload["permissions"]

        execute_permission = next(
            item for item in permissions
            if isinstance(item, dict) and item.get("identifier") == "shell:allow-execute"
        )
        spawn_permission = next(
            item for item in permissions
            if isinstance(item, dict) and item.get("identifier") == "shell:allow-spawn"
        )

        expected_allow = [{"name": "binaries/mmo", "sidecar": True, "args": True}]
        self.assertEqual(execute_permission.get("allow"), expected_allow)
        self.assertEqual(spawn_permission.get("allow"), expected_allow)
        self.assertIn("fs:default", permissions)
        self.assertTrue(
            any(
                isinstance(item, dict) and item.get("identifier") == "fs:allow-read-text-file"
                for item in permissions
            )
        )

        tauri_conf_path = _TAURI_ROOT / "src-tauri" / "tauri.conf.json"
        tauri_conf = json.loads(tauri_conf_path.read_text(encoding="utf-8"))
        asset_protocol = tauri_conf["app"]["security"]["assetProtocol"]
        self.assertTrue(asset_protocol["enable"])
        self.assertIn("$HOME/**", asset_protocol["scope"])
        self.assertIn("$TEMP/**", asset_protocol["scope"])

    def test_index_exposes_direct_workflow_controls(self) -> None:
        html_path = _TAURI_ROOT / "index.html"
        html = html_path.read_text(encoding="utf-8")

        for token in (
            "workflow-validate-button",
            "workflow-analyze-button",
            "workflow-scene-button",
            "workflow-render-button",
            "workflow-compare-button",
            "workflow-run-all-button",
            "render-cancel-button",
            "results-refresh-button",
            "workspace-reveal-button",
            "artifact-preview-actions",
            "results-summary-actions",
            "results-qa-actions",
            "timeline-list",
            "scene-locks-inspect-button",
            "scene-locks-save-button",
            "scene-locks-editor",
            "scene-locks-perspective-select",
            "artifact-preview-play-button",
            "artifact-preview-pause-button",
            "artifact-preview-stop-button",
            "compare-transport-play-button",
            "compare-transport-pause-button",
            "compare-transport-stop-button",
            "audition-audio",
            "screen-validate",
            "screen-analyze",
            "screen-scene",
            "screen-render",
            "screen-results",
            "screen-compare",
        ):
            self.assertIn(token, html)

        self.assertIn("safe-render --live-progress", html)
        self.assertIn("No Node server is launched.", html)
        self.assertIn("compare_report.json", html)
        self.assertIn("scene_lint.json", html)
        self.assertIn("Validate Project Contract", html)
        self.assertIn("workspace/project", html)

    def test_typescript_wrapper_uses_sidecar_execute_and_spawn(self) -> None:
        wrapper_path = _TAURI_ROOT / "src" / "mmo-sidecar.ts"
        source = wrapper_path.read_text(encoding="utf-8")

        self.assertIn('const SIDECAR_NAME = "binaries/mmo";', source)
        self.assertRegex(source, re.compile(r"Command\.sidecar\(SIDECAR_NAME,\s*args"))
        self.assertIn(".execute()", source)
        self.assertIn(".spawn()", source)
        self.assertIn('["gui", "rpc"]', source)
        self.assertIn("spawnedChild.write", source)
        self.assertIn('projectValidationPath: joinPath(projectDir, "validation.json")', source)
        self.assertIn('scenePath: joinPath(normalizedWorkspaceDir, "scene.json")', source)
        self.assertIn('compareReportPath: joinPath(normalizedWorkspaceDir, "compare_report.json")', source)
        self.assertIn("readTextFile", source)

    def test_typescript_results_quick_actions_are_wired(self) -> None:
        frontend_path = _TAURI_ROOT / "src" / "main.ts"
        source = frontend_path.read_text(encoding="utf-8")

        self.assertIn("copyTextToClipboard", source)
        self.assertIn("queueCompareFromArtifact", source)
        self.assertIn("queueRenderFromWorkspace", source)
        self.assertIn("buildResultsOpenButtons", source)
        self.assertIn("renderResultsActionRows", source)
        self.assertIn("playResultsAudition", source)
        self.assertIn("playCompareAudition", source)
        self.assertIn("refreshCompareAuditionSources", source)
        self.assertIn('label: "Copy path"', source)
        self.assertIn('label: "Reveal"', source)
        self.assertIn('receipt: "Open receipt"', source)
        self.assertIn('qa: "Open QA"', source)
        self.assertIn('label: "Open QA"', source)

    def test_packaged_smoke_automation_contract_exists(self) -> None:
        frontend_path = _TAURI_ROOT / "src" / "main.ts"
        frontend_source = frontend_path.read_text(encoding="utf-8")
        self.assertIn('invoke<DesktopSmokeConfig | null>("desktop_smoke_config")', frontend_source)
        self.assertIn("writeDesktopSmokeSummary(config.summaryPath, summary)", frontend_source)
        self.assertIn("runDesktopSmoke(ui, controller, desktopSmokeConfig)", frontend_source)
        self.assertIn("workflowStagesCompleted", frontend_source)
        self.assertIn("resultsInspection", frontend_source)

        backend_path = _TAURI_ROOT / "src-tauri" / "src" / "lib.rs"
        backend_source = backend_path.read_text(encoding="utf-8")
        self.assertIn('MMO_DESKTOP_SMOKE_SUMMARY_PATH', backend_source)
        self.assertIn('fn desktop_smoke_config()', backend_source)
        self.assertIn('tauri::generate_handler![desktop_smoke_config]', backend_source)

    def test_packaged_smoke_runs_validate_analyze_scene_render_in_order(self) -> None:
        frontend_path = _TAURI_ROOT / "src" / "main.ts"
        source = frontend_path.read_text(encoding="utf-8")

        validate_pos = source.index('await runWithBusyStrict(ui, "validate"')
        analyze_pos = source.index('await runWithBusyStrict(ui, "analyze"')
        scene_pos = source.index('await runWithBusyStrict(ui, "scene"')
        render_pos = source.index('await runWithBusyStrict(ui, "render"')

        self.assertLess(validate_pos, analyze_pos)
        self.assertLess(analyze_pos, scene_pos)
        self.assertLess(scene_pos, render_pos)
        self.assertIn('workflowStagesCompleted.push("render")', source)
        self.assertIn('deliverableSummaryRowsLoaded', source)
        self.assertIn('resultSummaryLoaded', source)


class TestTauriDesktopWorkflowRealPath(unittest.TestCase):
    def test_real_desktop_cli_path_renders_valid_master(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            stems_dir = temp_root / "stems"
            workspace_dir = temp_root / "workspace"

            _write_wave(stems_dir / "kick.wav", channels=1, frequency_hz=55.0)
            _write_wave(stems_dir / "snare.wav", channels=1, frequency_hz=190.0, phase_offset=0.35)
            _write_wave(stems_dir / "pad_stereo.wav", channels=2, frequency_hz=330.0, phase_offset=0.7)

            paths = _run_desktop_cli_workflow(stems_dir=stems_dir, workspace_dir=workspace_dir)

            truth = _PACKAGED_SMOKE._validate_workspace_render_truth(
                artifact_paths=_render_artifact_paths(paths)
            )
            self.assertTrue(truth.get("has_valid_master_audio_output"))
            self.assertTrue(truth.get("has_non_zero_scene_report_overlap"))
            self.assertEqual(
                truth.get("preflight_summary", {}).get("scene_stem_overlap_summary", {}).get("status"),
                "clean",
            )
            self.assertGreater(
                truth.get("preflight_summary", {})
                .get("scene_stem_overlap_summary", {})
                .get("matched_count", 0),
                0,
            )
            self.assertEqual(truth.get("scene_binding_summary", {}).get("status"), "clean")

            manifest = json.loads(paths["renderManifestPath"].read_text(encoding="utf-8"))
            receipt = json.loads(paths["renderReceiptPath"].read_text(encoding="utf-8"))
            scene_payload = json.loads(paths["scenePath"].read_text(encoding="utf-8"))
            report_payload = json.loads(paths["reportPath"].read_text(encoding="utf-8"))

            self.assertEqual(receipt.get("status"), "completed")
            self.assertIn(
                receipt.get("deliverables_summary", {}).get("result_bucket"),
                {"valid_master", "partial_success"},
            )
            self.assertGreater(
                receipt.get("deliverables_summary", {}).get("valid_master_count", 0),
                0,
            )
            scene_stem_ids = _scene_stem_ids(scene_payload)
            report_stem_ids = _session_stem_ids(report_payload)
            self.assertTrue(scene_stem_ids)
            self.assertTrue(report_stem_ids)
            self.assertEqual(scene_stem_ids, report_stem_ids)
            self.assertTrue(all(not stem_id.startswith("STEMFILE.") for stem_id in scene_stem_ids))

            valid_master_outputs = truth.get("valid_master_outputs")
            self.assertIsInstance(valid_master_outputs, list)
            if not isinstance(valid_master_outputs, list) or not valid_master_outputs:
                return
            first_output = valid_master_outputs[0]
            self.assertGreater(first_output.get("decoded_stem_count", 0), 0)
            self.assertGreater(first_output.get("duration_seconds", 0.0), 0.11)
            self.assertFalse(first_output.get("audio_all_zero"))
            self.assertEqual(first_output.get("sample_rate_hz"), 44_100)
            self.assertEqual(
                manifest.get("preflight_summary", {})
                .get("scene_stem_overlap_summary", {})
                .get("matched_count"),
                receipt.get("preflight_summary", {})
                .get("scene_stem_overlap_summary", {})
                .get("matched_count"),
            )

    def test_real_desktop_cli_path_keeps_duplicate_basenames_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            stems_dir = temp_root / "stems"
            workspace_dir = temp_root / "workspace"

            _write_wave(stems_dir / "album_a" / "Kick.wav", channels=1, frequency_hz=55.0)
            _write_wave(stems_dir / "album_b" / "Kick.wav", channels=1, frequency_hz=63.0, phase_offset=0.2)
            _write_wave(stems_dir / "album_b" / "Snare.wav", channels=1, frequency_hz=190.0, phase_offset=0.4)
            _write_wave(stems_dir / "album_b" / "Pad.wav", channels=2, frequency_hz=300.0, phase_offset=0.8)

            paths = _run_desktop_cli_workflow(stems_dir=stems_dir, workspace_dir=workspace_dir)

            truth = _PACKAGED_SMOKE._validate_workspace_render_truth(
                artifact_paths=_render_artifact_paths(paths)
            )
            self.assertTrue(truth.get("has_valid_master_audio_output"))
            self.assertTrue(truth.get("has_non_zero_scene_report_overlap"))
            self.assertEqual(
                truth.get("preflight_summary", {}).get("scene_stem_overlap_summary", {}).get("status"),
                "clean",
            )

            stems_map = json.loads(paths["stemsMapPath"].read_text(encoding="utf-8"))
            assignments = stems_map.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list):
                return
            by_rel_path = {
                row["rel_path"]: row["stem_id"]
                for row in assignments
                if isinstance(row, dict)
                and isinstance(row.get("rel_path"), str)
                and isinstance(row.get("stem_id"), str)
            }
            self.assertEqual(by_rel_path["album_a/Kick.wav"], "album_a_kick")
            self.assertEqual(by_rel_path["album_b/Kick.wav"], "album_b_kick")
            self.assertEqual(by_rel_path["album_b/Snare.wav"], "snare")
            self.assertEqual(len(set(by_rel_path.values())), len(by_rel_path))

            scene_payload = json.loads(paths["scenePath"].read_text(encoding="utf-8"))
            report_payload = json.loads(paths["reportPath"].read_text(encoding="utf-8"))
            scene_stem_ids = _scene_stem_ids(scene_payload)
            report_stem_ids = _session_stem_ids(report_payload)

            self.assertIn("album_a_kick", scene_stem_ids)
            self.assertIn("album_b_kick", scene_stem_ids)
            self.assertEqual(scene_stem_ids, report_stem_ids)
            self.assertTrue(all(not stem_id.startswith("STEMFILE.") for stem_id in scene_stem_ids))


if __name__ == "__main__":
    unittest.main()
