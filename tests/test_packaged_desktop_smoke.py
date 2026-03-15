"""Unit checks for the packaged desktop smoke harness."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
