"""Unit checks for the packaged desktop smoke harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "smoke_packaged_desktop.py"
    spec = importlib.util.spec_from_file_location("smoke_packaged_desktop", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load smoke_packaged_desktop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPackagedDesktopSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def _valid_summary(self, root: Path) -> dict[str, object]:
        artifact_paths: dict[str, str] = {}
        for key in (
            "busPlanCsvPath",
            "busPlanPath",
            "projectValidationPath",
            "renderManifestPath",
            "renderQaPath",
            "renderReceiptPath",
            "reportPath",
            "scanReportPath",
            "sceneLintPath",
            "scenePath",
            "stemsMapPath",
        ):
            artifact_path = root / f"{key}.json"
            artifact_path.write_text("{}", encoding="utf-8")
            artifact_paths[key] = artifact_path.as_posix()

        workspace_dir = root / "workspace"
        workspace_dir.mkdir()
        render_dir = workspace_dir / "render" / "LAYOUT.2_0"
        render_dir.mkdir(parents=True, exist_ok=True)
        master_path = render_dir / "master.wav"
        self.module._write_wave(master_path, channels=2, frequency_hz=220.0, sample_rate_hz=44_100)

        deliverables_summary = {
            "overall_status": "success",
            "deliverable_count": 1,
            "success_count": 1,
            "failed_count": 0,
            "partial_count": 0,
            "invalid_master_count": 0,
            "valid_master_count": 1,
            "mixed_outcomes": False,
            "result_bucket": "valid_master",
            "top_failure_reason": None,
            "top_failure_status": None,
        }
        result_summary = {
            "title": "Valid master render",
            "message": "MMO rendered 1 valid master output. Primary file: LAYOUT.2_0/master.wav.",
            "remedy": "Review any remaining warnings, then use the valid master deliverable.",
            "result_bucket": "valid_master",
            "overall_status": "success",
            "top_failure_reason": None,
            "deliverable_count": 1,
            "valid_master_count": 1,
            "primary_output_path": "LAYOUT.2_0/master.wav",
        }
        deliverable_summary_rows = [
            {
                "deliverable_id": "DELIV.LAYOUT.2_0.SMOKE",
                "output_id": "OUT.STEREO.SMOKE",
                "layout": "LAYOUT.2_0",
                "file_path": "LAYOUT.2_0/master.wav",
                "channel_count": 2,
                "sample_rate_hz": 44_100,
                "rendered_frame_count": 6615,
                "duration_seconds": 0.15,
                "status": "success",
                "validity": "valid_master",
                "failure_reason": None,
            }
        ]
        render_manifest = {
            "deliverables": [
                {
                    "deliverable_id": "DELIV.LAYOUT.2_0.SMOKE",
                    "artifact_role": "master",
                    "target_layout_id": "LAYOUT.2_0",
                    "status": "success",
                    "is_valid_master": True,
                    "decoded_stem_count": 3,
                    "rendered_frame_count": 6615,
                    "duration_seconds": 0.15,
                    "output_ids": ["OUT.STEREO.SMOKE"],
                    "warning_codes": [],
                }
            ],
            "deliverables_summary": deliverables_summary,
            "deliverable_summary_rows": deliverable_summary_rows,
            "result_summary": result_summary,
            "renderer_manifests": [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [
                        {
                            "output_id": "OUT.STEREO.SMOKE",
                            "file_path": "LAYOUT.2_0/master.wav",
                            "format": "wav",
                            "layout_id": "LAYOUT.2_0",
                            "channel_count": 2,
                            "sample_rate_hz": 44_100,
                            "metadata": {
                                "resampling": {
                                    "uniform_source_sample_rate_hz": 44_100,
                                    "output_sample_rate_hz": 44_100,
                                    "sample_rate_policy": "uniform_source_rate_preserve",
                                    "sample_rate_policy_reason": "all_decodable_stems_share_one_rate",
                                    "resample_applied": False,
                                    "resample_stage": "not_applied",
                                    "resample_method_id": "linear_interpolation_v1",
                                    "resampled_stem_count": 0,
                                }
                            },
                        }
                    ],
                    "skipped": [],
                }
            ],
        }
        render_receipt = {
            "status": "completed",
            "deliverables_summary": deliverables_summary,
            "deliverable_summary_rows": deliverable_summary_rows,
            "result_summary": result_summary,
        }
        render_qa = {
            "deliverables_summary": deliverables_summary,
            "issues": [],
        }
        render_manifest_path = root / "renderManifestPath.json"
        render_receipt_path = root / "renderReceiptPath.json"
        render_qa_path = root / "renderQaPath.json"
        render_manifest_path.write_text(json.dumps(render_manifest), encoding="utf-8")
        render_receipt_path.write_text(json.dumps(render_receipt), encoding="utf-8")
        render_qa_path.write_text(json.dumps(render_qa), encoding="utf-8")
        artifact_paths["renderManifestPath"] = render_manifest_path.as_posix()
        artifact_paths["renderReceiptPath"] = render_receipt_path.as_posix()
        artifact_paths["renderQaPath"] = render_qa_path.as_posix()
        artifact_paths["workspaceDir"] = workspace_dir.as_posix()

        return {
            "appLaunchVerified": True,
            "artifactPaths": artifact_paths,
            "doctor": {
                "checks": {
                    "cache_dir_writable": True,
                    "data_root_readable": True,
                    "ffmpeg_available": True,
                    "ffprobe_available": True,
                    "numpy_available": True,
                    "reportlab_available": True,
                    "temp_dir_writable": True,
                },
                "dataRoot": (root / "bundled-data").as_posix(),
                "envDoctorExitCode": 0,
                "ok": True,
                "pluginsExitCode": 0,
                "versionExitCode": 0,
            },
            "ok": True,
            "resultsInspection": {
                "deliverableSummaryRowsLoaded": True,
                "deliverablesSummaryLoaded": True,
                "manifestLoaded": True,
                "qaLoaded": True,
                "receiptLoaded": True,
                "resultSummaryLoaded": True,
            },
            "workflowStagesCompleted": ["doctor", "validate", "analyze", "scene", "render"],
        }

    def test_sidecar_name_detection_matches_staged_and_bundled_names(self) -> None:
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-x86_64-pc-windows-msvc.exe", "windows")
        )
        self.assertTrue(self.module._looks_like_sidecar_name("mmo.exe", "windows"))
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-aarch64-apple-darwin", "macos")
        )
        self.assertTrue(self.module._looks_like_sidecar_name("mmo", "macos"))
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-x86_64-unknown-linux-gnu", "linux")
        )
        self.assertTrue(self.module._looks_like_sidecar_name("mmo", "linux"))
        self.assertFalse(
            self.module._looks_like_sidecar_name("mmo-desktop-tauri.exe", "windows")
        )

    def test_path_is_under_is_casefolded_and_separator_safe(self) -> None:
        root = Path("/tmp/MMO Repo")
        self.assertTrue(self.module._path_is_under("/tmp/mmo repo/build/data", root))
        self.assertFalse(self.module._path_is_under("/tmp/mmo-other/build", root))

    def test_create_tiny_fixture_writes_expected_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = self.module._create_tiny_fixture(Path(temp_dir))
            self.assertTrue((stems_dir / "kick.wav").is_file())
            self.assertTrue((stems_dir / "snare.wav").is_file())
            self.assertTrue((stems_dir / "pad_stereo.wav").is_file())
            with self.module.wave.open(str(stems_dir / "kick.wav"), "rb") as handle:
                self.assertEqual(handle.getframerate(), 44_100)

    def test_main_app_score_prefers_product_name_over_sidecar(self) -> None:
        product_name = "MMO Desktop"
        sidecar = Path("mmo-x86_64-pc-windows-msvc.exe")
        desktop = Path("MMO Desktop.exe")
        self.assertGreater(
            self.module._main_app_score(desktop, platform_tag="windows", product_name=product_name),
            self.module._main_app_score(sidecar, platform_tag="windows", product_name=product_name),
        )

    def test_probe_packaged_sidecar_checks_version_plugins_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            sidecar_path = bundle_root / "bin" / "mmo-x86_64-pc-windows-msvc.exe"
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text("placeholder", encoding="utf-8")

            responses = [
                subprocess.CompletedProcess(
                    [str(sidecar_path), "--version"],
                    0,
                    stdout="mmo 0.1.0\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    [
                        str(sidecar_path),
                        "plugins",
                        "validate",
                        "--bundled-only",
                        "--format",
                        "json",
                    ],
                    0,
                    stdout=json.dumps({"bundled_only": True, "ok": True}),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    [str(sidecar_path), "env", "doctor", "--format", "json"],
                    0,
                    stdout=json.dumps({"checks": {"data_root_readable": True}}),
                    stderr="",
                ),
            ]

            with mock.patch.object(self.module.subprocess, "run", side_effect=responses) as run_mock:
                resolved = self.module._probe_packaged_sidecar(
                    bundle_root=bundle_root,
                    platform_tag="windows",
                    env={"MMO_CACHE_DIR": "cache"},
                )

            self.assertEqual(resolved, sidecar_path)
            self.assertEqual(
                [call.args[0] for call in run_mock.call_args_list],
                [
                    [str(sidecar_path), "--version"],
                    [
                        str(sidecar_path),
                        "plugins",
                        "validate",
                        "--bundled-only",
                        "--format",
                        "json",
                    ],
                    [str(sidecar_path), "env", "doctor", "--format", "json"],
                ],
            )

    def test_find_sidecar_binary_prefers_exact_mmo_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            staged_sidecar = bundle_root / "Contents" / "MacOS" / "mmo-aarch64-apple-darwin"
            bundled_sidecar = bundle_root / "Contents" / "MacOS" / "mmo"
            staged_sidecar.parent.mkdir(parents=True, exist_ok=True)
            staged_sidecar.write_text("staged", encoding="utf-8")
            bundled_sidecar.write_text("bundled", encoding="utf-8")

            resolved = self.module._find_sidecar_binary(bundle_root, platform_tag="macos")

            self.assertEqual(resolved, bundled_sidecar)

    def test_find_artifact_windows_prefers_nsis_setup_exe_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            msi_path = bundle_root / "msi" / "MMO Desktop_1.0.0_x64_en-US.msi"
            nsis_path = bundle_root / "nsis" / "MMO Desktop_1.0.0_x64-setup.exe"
            msi_path.parent.mkdir(parents=True, exist_ok=True)
            nsis_path.parent.mkdir(parents=True, exist_ok=True)
            msi_path.write_text("msi", encoding="utf-8")
            nsis_path.write_text("nsis", encoding="utf-8")

            resolved = self.module._find_artifact(bundle_root=bundle_root, platform_tag="windows")

            self.assertEqual(resolved, nsis_path)

    def test_find_sidecar_binaries_returns_all_windows_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            exact_sidecar = bundle_root / "mmo.exe"
            staged_sidecar = bundle_root / "bin" / "mmo-x86_64-pc-windows-msvc.exe"
            app_exe = bundle_root / "MMO Desktop.exe"
            staged_sidecar.parent.mkdir(parents=True, exist_ok=True)
            exact_sidecar.write_text("exact", encoding="utf-8")
            staged_sidecar.write_text("staged", encoding="utf-8")
            app_exe.write_text("app", encoding="utf-8")

            resolved = self.module._find_sidecar_binaries(bundle_root, platform_tag="windows")

            self.assertEqual(resolved, [staged_sidecar, exact_sidecar])

    def test_choose_windows_installed_app_prefers_new_path_over_preexisting(self) -> None:
        product_name = "MMO Desktop"
        existing = Path("C:/Users/test/AppData/Local/Programs/MMO Desktop/MMO Desktop.exe")
        fresh = Path("C:/Program Files/MMO Desktop/MMO Desktop.exe")

        resolved = self.module._choose_windows_installed_app(
            [existing, fresh],
            preexisting_candidates={self.module._normalize_path_text(existing)},
            product_name=product_name,
        )

        self.assertEqual(resolved, fresh)

    def test_windows_install_receipt_lists_log_and_launch_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_root = root / "Programs" / "MMO Desktop"
            install_root.mkdir(parents=True, exist_ok=True)
            (install_root / "MMO Desktop.exe").write_text("app", encoding="utf-8")
            install_log = root / "install.log"
            install_log.write_text("install ok\nsecond line\n", encoding="utf-8")

            receipt = self.module._windows_install_receipt(
                product_name="MMO Desktop",
                env={"LOCALAPPDATA": str(root)},
                installer_path=root / "MMO Desktop-setup.exe",
                install_log_path=install_log,
                install_root=install_root,
                launch_stdout="stdout line",
                launch_stderr="stderr line",
            )

            self.assertIn("installer path", receipt)
            self.assertIn(str(install_log), receipt)
            self.assertIn("stdout line", receipt)
            self.assertIn("stderr line", receipt)
            self.assertIn("MMO Desktop.exe", receipt)

    def test_choose_windows_uninstall_command_prefers_uninstall_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_root = root / "Programs" / "MMO Desktop"
            install_root.mkdir(parents=True, exist_ok=True)
            uninstall_exe = install_root / "uninstall.exe"
            uninstall_exe.write_text("stub", encoding="utf-8")
            artifact_path = root / "MMO Desktop-setup.exe"
            artifact_path.write_text("nsis", encoding="utf-8")
            uninstall_log_path = root / "windows-uninstall.log"

            strategy, command, notes = self.module._choose_windows_uninstall_command(
                install_root=install_root,
                installer_kind="nsis",
                artifact_path=artifact_path,
                product_name="MMO Desktop",
                uninstall_log_path=uninstall_log_path,
            )

            self.assertEqual(strategy, "uninstall-exe")
            self.assertEqual(command, [str(uninstall_exe), "/S"])
            self.assertEqual(notes, ())

    def test_choose_windows_uninstall_command_normalizes_registry_msiexec(self) -> None:
        install_root = Path("C:/Users/test/AppData/Local/Programs/MMO Desktop")
        uninstall_log_path = Path("C:/Temp/windows-uninstall.log")
        registry_entry = self.module.WindowsInstallEntry(
            display_name="MMO Desktop",
            install_location=install_root,
            display_icon=install_root / "MMO Desktop.exe",
            uninstall_command='MsiExec.exe /I{12345678-ABCD-4321-DCBA-87654321ABCD}',
            quiet_uninstall_command=None,
        )

        with mock.patch.object(self.module, "_read_windows_install_entries", return_value=[registry_entry]):
            strategy, command, notes = self.module._choose_windows_uninstall_command(
                install_root=install_root,
                installer_kind="msi",
                artifact_path=Path("C:/Temp/MMO Desktop.msi"),
                product_name="MMO Desktop",
                uninstall_log_path=uninstall_log_path,
            )

        self.assertEqual(strategy, "registry-msiexec")
        self.assertEqual(
            command,
            [
                "msiexec",
                "/x",
                "{12345678-ABCD-4321-DCBA-87654321ABCD}",
                "/qn",
                "/norestart",
                "/l*v",
                str(uninstall_log_path),
            ],
        )
        self.assertEqual(notes, ())

    def test_cleanup_windows_install_removes_residual_root_after_uninstall_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_root = root / "AppData" / "Local" / "Programs" / "MMO Desktop"
            install_root.mkdir(parents=True, exist_ok=True)
            (install_root / "uninstall.exe").write_text("stub", encoding="utf-8")
            (install_root / "MMO Desktop.exe").write_text("app", encoding="utf-8")
            artifact_path = root / "MMO Desktop-setup.exe"
            artifact_path.write_text("nsis", encoding="utf-8")
            install_log_path = root / "nsis-install.log"
            install_log_path.write_text("install ok", encoding="utf-8")
            cleanup_completed = subprocess.CompletedProcess(
                [str(install_root / "uninstall.exe"), "/S"],
                1,
                stdout="cleanup stdout",
                stderr="cleanup stderr",
            )

            with mock.patch.object(
                self.module,
                "_run_windows_cleanup_command",
                return_value=cleanup_completed,
            ) as cleanup_mock:
                result = self.module._cleanup_windows_install(
                    state={
                        "artifact_path": artifact_path.as_posix(),
                        "install_log_path": install_log_path.as_posix(),
                        "install_root": install_root.as_posix(),
                        "installer_kind": "nsis",
                        "product_name": "MMO Desktop",
                    },
                    env={"LOCALAPPDATA": str(root / "AppData" / "Local")},
                )

            self.assertTrue(result.attempted)
            self.assertTrue(result.ok)
            self.assertTrue(result.removed_install_root)
            self.assertIn("residual-rmtree", result.strategy or "")
            self.assertTrue(any("exited 1" in note for note in result.notes))
            self.assertFalse(install_root.exists())
            self.assertEqual(
                cleanup_mock.call_args.kwargs["uninstall_log_path"],
                install_log_path.with_name("windows-uninstall.log"),
            )

    def test_find_sidecar_binary_error_lists_likely_macos_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            macos_dir = bundle_root / "Contents" / "MacOS"
            frameworks_dir = bundle_root / "Contents" / "Frameworks"
            resources_dir = bundle_root / "Contents" / "Resources"
            macos_dir.mkdir(parents=True, exist_ok=True)
            frameworks_dir.mkdir(parents=True, exist_ok=True)
            resources_dir.mkdir(parents=True, exist_ok=True)
            (macos_dir / "MMO Desktop").write_text("app", encoding="utf-8")
            (frameworks_dir / "MMO Desktop Helper").write_text("helper", encoding="utf-8")

            with self.assertRaisesRegex(self.module.SmokeError, "Contents/MacOS") as context:
                self.module._find_sidecar_binary(bundle_root, platform_tag="macos")

            message = str(context.exception)
            self.assertIn("Contents/MacOS", message)
            self.assertIn("Contents/Frameworks", message)
            self.assertIn("Contents/Resources", message)
            self.assertIn("MMO Desktop", message)

    def test_validate_summary_requires_zero_doctor_probe_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            summary_root = Path(temp_dir) / "summary"
            summary_root.mkdir()
            summary = self._valid_summary(summary_root)
            summary["doctor"]["versionExitCode"] = 2

            with self.assertRaisesRegex(self.module.SmokeError, "--version"):
                self.module._validate_summary(
                    summary=summary,
                    repo_root=repo_root,
                    allow_repo_data_root=False,
                )

    def test_validate_summary_requires_results_inspection_and_render_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            summary_root = Path(temp_dir) / "summary"
            summary_root.mkdir()
            summary = self._valid_summary(summary_root)

            truth = self.module._validate_summary(
                summary=summary,
                repo_root=repo_root,
                allow_repo_data_root=False,
            )

            self.assertTrue(truth.get("has_valid_master_audio_output"))
            self.assertTrue(truth.get("has_uniform_rate_preservation_output"))

    def test_validate_summary_rejects_missing_results_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            repo_root.mkdir()
            summary_root = Path(temp_dir) / "summary"
            summary_root.mkdir()
            summary = self._valid_summary(summary_root)
            summary["resultsInspection"] = {
                "deliverableSummaryRowsLoaded": False,
                "deliverablesSummaryLoaded": True,
                "manifestLoaded": True,
                "qaLoaded": True,
                "receiptLoaded": True,
                "resultSummaryLoaded": True,
            }

            with self.assertRaisesRegex(self.module.SmokeError, "Results view"):
                self.module._validate_summary(
                    summary=summary,
                    repo_root=repo_root,
                    allow_repo_data_root=False,
                )


if __name__ == "__main__":
    unittest.main()
