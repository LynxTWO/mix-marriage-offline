"""Regression checks for the Tauri desktop sidecar workflow surface."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAURI_ROOT = _REPO_ROOT / "gui" / "desktop-tauri"


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

        backend_path = _TAURI_ROOT / "src-tauri" / "src" / "lib.rs"
        backend_source = backend_path.read_text(encoding="utf-8")
        self.assertIn('MMO_DESKTOP_SMOKE_SUMMARY_PATH', backend_source)
        self.assertIn('fn desktop_smoke_config()', backend_source)
        self.assertIn('tauri::generate_handler![desktop_smoke_config]', backend_source)


if __name__ == "__main__":
    unittest.main()
