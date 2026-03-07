import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class TestValidateOntologyChanges(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _source_validator_script(self) -> Path:
        return self._repo_root() / "tools" / "validate_ontology_changes.py"

    def _init_temp_repo(self, temp_root: Path) -> Path:
        if shutil.which("git") is None:
            self.skipTest("git is required for ontology change validator tests.")

        shutil.copytree(self._repo_root() / "ontology", temp_root / "ontology")
        (temp_root / "docs").mkdir(parents=True, exist_ok=True)
        tools_dir = temp_root / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._source_validator_script(), tools_dir / "validate_ontology_changes.py")

        subprocess.run(["git", "-c", "init.defaultBranch=main", "init"], check=True, cwd=temp_root)
        subprocess.run(["git", "checkout", "-B", "main"], check=True, cwd=temp_root)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], check=True, cwd=temp_root)
        subprocess.run(["git", "config", "user.name", "MMO Tests"], check=True, cwd=temp_root)
        subprocess.run(["git", "add", "."], check=True, cwd=temp_root)
        subprocess.run(["git", "commit", "-m", "baseline"], check=True, cwd=temp_root)
        subprocess.run(["git", "checkout", "-b", "feature"], check=True, cwd=temp_root)
        return temp_root / "tools" / "validate_ontology_changes.py"

    def _run_validator(self, repo_root: Path, script_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self._python_cmd(),
                os.fspath(script_path),
                "--repo-root",
                os.fspath(repo_root),
                "--base-ref",
                "main",
                "--require-base-ref",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

    def test_validate_ontology_changes_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [
                self._python_cmd(),
                os.fspath(self._source_validator_script()),
                "--repo-root",
                os.fspath(self._repo_root()),
                "--base-ref",
                "main",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("errors"), [])

    def test_removed_id_requires_version_bump_and_migration_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            script_path = self._init_temp_repo(temp_root)

            units_path = temp_root / "ontology" / "units.yaml"
            units_doc = yaml.safe_load(units_path.read_text(encoding="utf-8"))
            self.assertIsInstance(units_doc, dict)
            if not isinstance(units_doc, dict):
                return
            units_map = units_doc.get("units")
            self.assertIsInstance(units_map, dict)
            if not isinstance(units_map, dict):
                return
            removed_id = sorted(units_map.keys())[0]
            units_map.pop(removed_id)
            units_path.write_text(yaml.safe_dump(units_doc, sort_keys=False), encoding="utf-8")

            result = self._run_validator(temp_root, script_path)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        errors = payload.get("errors", [])
        self.assertTrue(
            any("Removed ontology IDs require an ontology version bump." in str(msg) for msg in errors),
            msg=payload,
        )
        self.assertTrue(
            any("Removed ontology IDs require a migration note" in str(msg) for msg in errors),
            msg=payload,
        )

    def test_removed_id_with_version_bump_and_migration_note_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            script_path = self._init_temp_repo(temp_root)

            units_path = temp_root / "ontology" / "units.yaml"
            units_doc = yaml.safe_load(units_path.read_text(encoding="utf-8"))
            self.assertIsInstance(units_doc, dict)
            if not isinstance(units_doc, dict):
                return
            units_map = units_doc.get("units")
            self.assertIsInstance(units_map, dict)
            if not isinstance(units_map, dict):
                return
            removed_id = sorted(units_map.keys())[0]
            units_map.pop(removed_id)
            units_path.write_text(yaml.safe_dump(units_doc, sort_keys=False), encoding="utf-8")

            manifest_path = temp_root / "ontology" / "ontology.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            self.assertIsInstance(manifest, dict)
            if not isinstance(manifest, dict):
                return
            ontology_section = manifest.get("ontology")
            self.assertIsInstance(ontology_section, dict)
            if not isinstance(ontology_section, dict):
                return
            ontology_section["ontology_version"] = "0.2.0"
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

            migrations_dir = temp_root / "docs" / "ontology_migrations"
            migrations_dir.mkdir(parents=True, exist_ok=True)
            (migrations_dir / "0.2.0.md").write_text(
                "# Ontology Migration 0.2.0\n\n"
                f"- Removed ID: {removed_id}\n"
                "- Replacement: N/A\n",
                encoding="utf-8",
            )

            result = self._run_validator(temp_root, script_path)

        self.assertEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"), msg=payload)
        self.assertEqual(payload.get("removed_ids"), [removed_id])
        self.assertEqual(payload.get("errors"), [])

    def test_deprecated_entries_require_replaced_by(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            script_path = self._init_temp_repo(temp_root)

            roles_path = temp_root / "ontology" / "roles.yaml"
            roles_doc = yaml.safe_load(roles_path.read_text(encoding="utf-8"))
            self.assertIsInstance(roles_doc, dict)
            if not isinstance(roles_doc, dict):
                return
            roles_map = roles_doc.get("roles")
            self.assertIsInstance(roles_map, dict)
            if not isinstance(roles_map, dict):
                return
            role_id = sorted(roles_map.keys())[0]
            role_payload = roles_map.get(role_id)
            self.assertIsInstance(role_payload, dict)
            if not isinstance(role_payload, dict):
                return
            role_payload["deprecated"] = True
            role_payload.pop("replaced_by", None)
            roles_path.write_text(yaml.safe_dump(roles_doc, sort_keys=False), encoding="utf-8")

            result = self._run_validator(temp_root, script_path)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        errors = payload.get("errors", [])
        self.assertTrue(
            any("missing replaced_by" in str(msg) for msg in errors),
            msg=payload,
        )


if __name__ == "__main__":
    unittest.main()
