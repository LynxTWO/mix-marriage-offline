import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class TestValidateUiSpecs(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _validator_script(self) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        return repo_root / "tools" / "validate_ui_specs.py"

    def test_validate_ui_specs_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._validator_script())],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("missing_ui_copy_keys"), [])
        self.assertEqual(payload.get("missing_help_ids"), [])
        self.assertEqual(payload.get("missing_glossary_terms"), [])

    def test_validate_ui_specs_missing_copy_key_fails(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            (temp_root / "ontology").mkdir(parents=True, exist_ok=True)
            (temp_root / "schemas").mkdir(parents=True, exist_ok=True)

            for source in (
                repo_root / "ontology" / "gui_design.yaml",
                repo_root / "ontology" / "ui_copy.yaml",
                repo_root / "ontology" / "help.yaml",
                repo_root / "ontology" / "scene_locks.yaml",
                repo_root / "schemas" / "gui_design.schema.json",
                repo_root / "schemas" / "ui_copy.schema.json",
                repo_root / "schemas" / "help_registry.schema.json",
            ):
                target = temp_root / source.relative_to(repo_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            ui_copy_path = temp_root / "ontology" / "ui_copy.yaml"
            ui_copy_payload = yaml.safe_load(ui_copy_path.read_text(encoding="utf-8"))
            ui_copy_payload["locales"]["en-US"]["entries"].pop("COPY.NAV.RUN", None)
            ui_copy_path.write_text(
                yaml.safe_dump(ui_copy_payload, sort_keys=False),
                encoding="utf-8",
            )

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
        self.assertIn("COPY.NAV.RUN", payload.get("missing_ui_copy_keys", []))

    def test_validate_ui_specs_missing_lock_help_id_fails(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            (temp_root / "ontology").mkdir(parents=True, exist_ok=True)
            (temp_root / "schemas").mkdir(parents=True, exist_ok=True)

            for source in (
                repo_root / "ontology" / "gui_design.yaml",
                repo_root / "ontology" / "ui_copy.yaml",
                repo_root / "ontology" / "help.yaml",
                repo_root / "ontology" / "scene_locks.yaml",
                repo_root / "schemas" / "gui_design.schema.json",
                repo_root / "schemas" / "ui_copy.schema.json",
                repo_root / "schemas" / "help_registry.schema.json",
            ):
                target = temp_root / source.relative_to(repo_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            help_path = temp_root / "ontology" / "help.yaml"
            help_payload = yaml.safe_load(help_path.read_text(encoding="utf-8"))
            help_payload["entries"].pop("HELP.LOCK.PRESERVE_DYNAMICS", None)
            help_path.write_text(
                yaml.safe_dump(help_payload, sort_keys=False),
                encoding="utf-8",
            )

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
        self.assertIn(
            "HELP.LOCK.PRESERVE_DYNAMICS",
            payload.get("missing_help_ids", []),
        )


if __name__ == "__main__":
    unittest.main()
