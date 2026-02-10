import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REQUIRED_CHECK_IDS = [
    "UI.SPECS",
    "UI.EXAMPLES",
    "ONTOLOGY.REFS",
    "PLUGINS",
    "SCHEMAS",
]

REQUIRED_TOOL_SCRIPTS = [
    "validate_ui_specs.py",
    "validate_ui_examples.py",
    "validate_ontology_refs.py",
    "validate_plugins.py",
]

REQUIRED_REPO_DIRS = [
    "examples",
    "ontology",
    "plugins",
    "schemas",
    "src",
]


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
            shutil.copytree(repo_root / rel_dir, destination / rel_dir)

        tools_dir = destination / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for script_name in REQUIRED_TOOL_SCRIPTS:
            shutil.copy2(repo_root / "tools" / script_name, tools_dir / script_name)

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


if __name__ == "__main__":
    unittest.main()
