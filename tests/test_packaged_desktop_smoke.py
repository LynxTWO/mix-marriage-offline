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
        }

    def test_sidecar_name_detection_matches_target_triples(self) -> None:
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-x86_64-pc-windows-msvc.exe", "windows")
        )
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-aarch64-apple-darwin", "macos")
        )
        self.assertTrue(
            self.module._looks_like_sidecar_name("mmo-x86_64-unknown-linux-gnu", "linux")
        )
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


if __name__ == "__main__":
    unittest.main()
