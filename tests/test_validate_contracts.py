import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REQUIRED_CHECK_IDS = [
    "UI.SPECS",
    "UI.EXAMPLES",
    "ONTOLOGY.REFS",
    "ONTOLOGY.CHANGES",
    "PLUGINS",
    "PLUGINS.UI",
    "PKG.MIRROR",
    "DOCS.MILESTONES",
    "DOCS.GUI_PARITY",
    "GUI.TAURI_DESIGN",
    "DOCS.USER_MANUAL",
    "MSI.VERSION",
    "SCENE.REGISTRIES",
    "TRANSLATION.REGISTRIES",
    "ROLES.REGISTRIES",
    "ROLE_LEXICON.COMMON",
    "GATES.REGISTRIES",
    "TARGETS.REGISTRIES",
    "SCHEMAS",
]

REQUIRED_TOOL_SCRIPTS = [
    "validate_ui_specs.py",
    "validate_ui_examples.py",
    "validate_ontology_refs.py",
    "validate_ontology_changes.py",
    "validate_plugins.py",
    "validate_plugins_ui.py",
    "validate_packaged_data_mirror.py",
    "validate_milestones.py",
    "validate_gui_parity.py",
    "validate_tauri_design_system.py",
    "validate_user_manual.py",
    "validate_msi_version.py",
]

REQUIRED_REPO_DIRS = [
    "docs",
    "examples",
    "gui",
    "ontology",
    "plugins",
    "schemas",
    "src",
]

COPYTREE_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
)


class TestValidateContracts(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _validator_script(self) -> Path:
        return self._repo_root() / "tools" / "validate_contracts.py"

    def _copy_repo_subset(self, destination: Path) -> None:
        repo_root = self._repo_root()
        for rel_dir in REQUIRED_REPO_DIRS:
            shutil.copytree(
                repo_root / rel_dir,
                destination / rel_dir,
                ignore=COPYTREE_IGNORE,
            )

        tools_dir = destination / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for script_name in REQUIRED_TOOL_SCRIPTS:
            shutil.copy2(repo_root / "tools" / script_name, tools_dir / script_name)

    def test_copy_repo_subset_preserves_canonical_preset_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._copy_repo_subset(temp_root)

            self.assertFalse((temp_root / "presets").exists())
            self.assertTrue((temp_root / "ontology" / "presets").is_dir())
            self.assertTrue((temp_root / "ontology" / "presets" / "index.json").is_file())

    def test_validate_contracts_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._validator_script())],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))

        checks = payload.get("checks")
        self.assertIsInstance(checks, list)
        if not isinstance(checks, list):
            return

        check_ids = [item.get("check_id") for item in checks if isinstance(item, dict)]
        self.assertEqual(check_ids, REQUIRED_CHECK_IDS)

        checks_by_id = {
            item.get("check_id"): item
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("check_id"), str)
        }
        for check_id in REQUIRED_CHECK_IDS:
            self.assertIn(check_id, checks_by_id)
            self.assertTrue(checks_by_id[check_id].get("ok"), msg=checks_by_id[check_id])

    def test_validate_contracts_reports_schema_breakage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._copy_repo_subset(temp_root)

            ui_bundle_schema_path = temp_root / "schemas" / "ui_bundle.schema.json"
            ui_bundle_schema = json.loads(ui_bundle_schema_path.read_text(encoding="utf-8"))
            ui_bundle_schema["properties"]["report"]["$ref"] = "missing.schema.json"
            ui_bundle_schema_path.write_text(
                json.dumps(ui_bundle_schema, indent=2) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    self._python_cmd(),
                    os.fspath(self._validator_script()),
                    "--repo-root",
                    os.fspath(temp_root),
                    "--strict",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=self._repo_root(),
            )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertIn("SCHEMAS", payload.get("summary", {}).get("failed", []))

        checks = payload.get("checks")
        self.assertIsInstance(checks, list)
        if not isinstance(checks, list):
            return
        checks_by_id = {
            item.get("check_id"): item
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("check_id"), str)
        }
        self.assertIn("SCHEMAS", checks_by_id)
        self.assertFalse(checks_by_id["SCHEMAS"].get("ok"))

    def test_validate_contracts_reports_scene_registry_duplicate_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            self._copy_repo_subset(temp_root)

            speaker_positions_path = temp_root / "ontology" / "speaker_positions.yaml"
            registry = yaml.safe_load(speaker_positions_path.read_text(encoding="utf-8"))
            self.assertIsInstance(registry, dict)
            if not isinstance(registry, dict):
                return

            layouts = registry.get("layouts")
            self.assertIsInstance(layouts, dict)
            if not isinstance(layouts, dict):
                return

            target_layout = None
            for layout_id in sorted(layouts.keys()):
                if not isinstance(layout_id, str):
                    continue
                layout = layouts.get(layout_id)
                if not isinstance(layout, dict):
                    continue
                channels = layout.get("channels")
                if (
                    isinstance(channels, list)
                    and len(channels) >= 2
                    and isinstance(channels[0], dict)
                    and isinstance(channels[1], dict)
                ):
                    target_layout = layout_id
                    break
            self.assertIsInstance(target_layout, str)
            if not isinstance(target_layout, str):
                return

            channels = layouts[target_layout]["channels"]
            first_ch = channels[0].get("ch")
            channels[1]["ch"] = first_ch
            speaker_positions_path.write_text(
                yaml.safe_dump(registry, sort_keys=False),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    self._python_cmd(),
                    os.fspath(self._validator_script()),
                    "--repo-root",
                    os.fspath(temp_root),
                    "--strict",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=self._repo_root(),
            )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertIn("SCENE.REGISTRIES", payload.get("summary", {}).get("failed", []))

        checks = payload.get("checks")
        self.assertIsInstance(checks, list)
        if not isinstance(checks, list):
            return

        checks_by_id = {
            item.get("check_id"): item
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("check_id"), str)
        }
        self.assertIn("SCENE.REGISTRIES", checks_by_id)
        scene_registries = checks_by_id["SCENE.REGISTRIES"]
        self.assertFalse(scene_registries.get("ok"))

        errors = scene_registries.get("errors")
        self.assertIsInstance(errors, list)
        if not isinstance(errors, list):
            return
        self.assertTrue(
            any("duplicate ch" in str(error).lower() for error in errors),
            msg=scene_registries,
        )

    def test_validate_contracts_includes_ui_hints_schema_anchor(self) -> None:
        script_text = self._validator_script().read_text(encoding="utf-8")
        self.assertIn("schemas/ui_hints.schema.json", script_text)


if __name__ == "__main__":
    unittest.main()
