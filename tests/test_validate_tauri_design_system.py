import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestValidateTauriDesignSystem(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _validator_script(self) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        return repo_root / "tools" / "validate_tauri_design_system.py"

    def _copy_repo_slice(self, target_root: Path) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        for relative in (
            Path("ontology") / "gui_design.yaml",
            Path("schemas") / "gui_design.schema.json",
            Path("schemas") / "ui_layout.schema.json",
            Path("gui") / "desktop-tauri" / "index.html",
            Path("gui") / "desktop-tauri" / "src" / "styles.css",
            Path("gui") / "desktop-tauri" / "layouts",
        ):
            source = repo_root / relative
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)

    def test_validator_accepts_current_repo(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._validator_script())],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("missing_control_kinds"), [])
        self.assertEqual(payload.get("numeric_missing_units"), [])
        self.assertEqual(payload.get("numeric_missing_direct_entry"), [])
        self.assertEqual(payload.get("drag_missing_fine_adjust"), [])

    def test_validator_fails_when_numeric_units_metadata_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._copy_repo_slice(temp_root)

            index_path = temp_root / "gui" / "desktop-tauri" / "index.html"
            original = index_path.read_text(encoding="utf-8")
            mutated = original.replace(
                '            data-widget-id="widget.dashboard.slider_trim"\n'
                '            data-control-kind="SLIDER"\n'
                '            data-numeric-control="true"\n'
                '            data-direct-entry="true"\n'
                '            data-fine-adjust="true"\n'
                '            data-units="dB"\n',
                '            data-widget-id="widget.dashboard.slider_trim"\n'
                '            data-control-kind="SLIDER"\n'
                '            data-numeric-control="true"\n'
                '            data-direct-entry="true"\n'
                '            data-fine-adjust="true"\n',
                1,
            )
            index_path.write_text(mutated, encoding="utf-8")

            result = subprocess.run(
                [
                    self._python_cmd(),
                    os.fspath(self._validator_script()),
                    "--repo-root",
                    os.fspath(temp_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertIn("widget.dashboard.slider_trim", payload.get("numeric_missing_units", []))

    def test_validator_fails_when_required_control_kind_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._copy_repo_slice(temp_root)

            index_path = temp_root / "gui" / "desktop-tauri" / "index.html"
            original = index_path.read_text(encoding="utf-8")
            mutated = original.replace('data-control-kind="AB_TOGGLE"', 'data-control-kind="BROKEN_KIND"', 1)
            index_path.write_text(mutated, encoding="utf-8")

            result = subprocess.run(
                [
                    self._python_cmd(),
                    os.fspath(self._validator_script()),
                    "--repo-root",
                    os.fspath(temp_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertIn("AB_TOGGLE", payload.get("missing_control_kinds", []))


if __name__ == "__main__":
    unittest.main()
