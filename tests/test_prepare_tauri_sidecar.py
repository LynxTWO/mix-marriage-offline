from __future__ import annotations

import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "prepare_tauri_sidecar.py"
    spec = importlib.util.spec_from_file_location("prepare_tauri_sidecar", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load prepare_tauri_sidecar.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPrepareTauriSidecar(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_sidecar_binary_name_uses_target_triple(self) -> None:
        self.assertEqual(
            self.module.sidecar_binary_name(target_triple="x86_64-unknown-linux-gnu"),
            "mmo-x86_64-unknown-linux-gnu",
        )
        self.assertEqual(
            self.module.sidecar_binary_name(target_triple="x86_64-pc-windows-msvc"),
            "mmo-x86_64-pc-windows-msvc.exe",
        )

    def test_build_binary_name_for_target_maps_platform_and_arch(self) -> None:
        self.assertEqual(
            self.module.build_binary_name_for_target(
                target_triple="x86_64-unknown-linux-gnu"
            ),
            "mmo-linux-x86_64",
        )
        self.assertEqual(
            self.module.build_binary_name_for_target(
                target_triple="aarch64-apple-darwin"
            ),
            "mmo-macos-arm64",
        )
        self.assertEqual(
            self.module.build_binary_name_for_target(
                target_triple="x86_64-pc-windows-msvc"
            ),
            "mmo-windows-x86_64.exe",
        )

    def test_is_sidecar_up_to_date_tracks_source_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            sidecar_path = repo_root / "gui" / "desktop-tauri" / "src-tauri" / "binaries" / "mmo"
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text("sidecar", encoding="utf-8")

            src_dir = repo_root / "src" / "mmo"
            src_dir.mkdir(parents=True, exist_ok=True)
            source_file = src_dir / "cli.py"
            source_file.write_text("print('ok')\n", encoding="utf-8")
            for ancillary in (
                repo_root / "pyproject.toml",
                repo_root / "tools" / "build_binaries.py",
                repo_root / "tools" / "prepare_tauri_sidecar.py",
            ):
                ancillary.parent.mkdir(parents=True, exist_ok=True)
                ancillary.write_text("# test\n", encoding="utf-8")

            old_time = time.time() - 120
            new_time = time.time()
            for path in (
                repo_root / "pyproject.toml",
                repo_root / "tools" / "build_binaries.py",
                repo_root / "tools" / "prepare_tauri_sidecar.py",
                source_file,
            ):
                path.touch()
                path.chmod(path.stat().st_mode)
            sidecar_path.touch()
            sidecar_path.chmod(sidecar_path.stat().st_mode)

            os_utime = __import__("os").utime
            os_utime(repo_root / "pyproject.toml", (old_time, old_time))
            os_utime(repo_root / "tools" / "build_binaries.py", (old_time, old_time))
            os_utime(
                repo_root / "tools" / "prepare_tauri_sidecar.py",
                (old_time, old_time),
            )
            os_utime(sidecar_path, (new_time, new_time))
            os_utime(source_file, (old_time, old_time))
            self.assertTrue(
                self.module.is_sidecar_up_to_date(sidecar_path, repo_root=repo_root)
            )

            os_utime(source_file, (new_time + 5, new_time + 5))
            self.assertFalse(
                self.module.is_sidecar_up_to_date(sidecar_path, repo_root=repo_root)
            )


if __name__ == "__main__":
    unittest.main()
