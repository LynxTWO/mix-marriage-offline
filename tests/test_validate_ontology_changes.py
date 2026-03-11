import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


class TestValidateOntologyChanges(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _source_validator_script(self) -> Path:
        return self._repo_root() / "tools" / "validate_ontology_changes.py"

    def _load_validator_module(self):
        module_path = self._source_validator_script()
        spec = importlib.util.spec_from_file_location(
            "validate_ontology_changes_for_tests",
            module_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        if spec is None or spec.loader is None:
            raise AssertionError("Failed to load validate_ontology_changes module spec.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

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

    def test_missing_base_manifest_reports_single_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            script_path = self._init_temp_repo(temp_root)

            subprocess.run(["git", "checkout", "main"], check=True, cwd=temp_root)
            subprocess.run(
                ["git", "rm", "ontology/ontology.yaml"],
                check=True,
                cwd=temp_root,
            )
            subprocess.run(
                ["git", "commit", "-m", "remove base ontology manifest"],
                check=True,
                cwd=temp_root,
            )
            subprocess.run(["git", "checkout", "feature"], check=True, cwd=temp_root)

            result = self._run_validator(temp_root, script_path)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(
            payload.get("errors"),
            ["Missing ontology/ontology.yaml in base ref main."],
        )
        self.assertEqual(payload.get("warnings"), [])
        self.assertFalse(payload.get("skipped_diff"))

    def test_invalid_utf8_from_git_show_uses_warning_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            script_path = self._init_temp_repo(temp_root)

            subprocess.run(["git", "checkout", "main"], check=True, cwd=temp_root)
            roles_path = temp_root / "ontology" / "roles.yaml"
            roles_bytes = roles_path.read_bytes()
            roles_path.write_bytes(b"# decode fallback \x96\n" + roles_bytes)
            subprocess.run(["git", "add", "ontology/roles.yaml"], check=True, cwd=temp_root)
            subprocess.run(
                ["git", "commit", "-m", "introduce invalid utf8 in base"],
                check=True,
                cwd=temp_root,
            )
            subprocess.run(["git", "checkout", "feature"], check=True, cwd=temp_root)

            result = self._run_validator(temp_root, script_path)

        self.assertEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"), msg=payload)
        self.assertEqual(payload.get("errors"), [])
        warnings = payload.get("warnings", [])
        self.assertTrue(
            any(
                "Decoded git output with utf-8 replacement while reading ontology/roles.yaml"
                in str(msg)
                for msg in warnings
            ),
            msg=payload,
        )

    def test_failed_base_show_does_not_emit_missing_manifest_or_yaml_parse_error(self) -> None:
        module = self._load_validator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(self._repo_root() / "ontology", temp_root / "ontology")
            (temp_root / "docs").mkdir(parents=True, exist_ok=True)
            units_text = (temp_root / "ontology" / "units.yaml").read_text(encoding="utf-8")

            def fake_run_git(repo_root: Path, args: list[str]):
                if args == ["rev-parse", "--is-inside-work-tree"]:
                    return module.GitCommandResult(tuple(args), 0, "true\n", "", False)
                if args == ["rev-parse", "--verify", "--quiet", "main"]:
                    return module.GitCommandResult(tuple(args), 0, "deadbeef\n", "", False)
                if args == ["ls-tree", "-r", "--name-only", "main", "--", "ontology"]:
                    return module.GitCommandResult(
                        tuple(args),
                        0,
                        "ontology/ontology.yaml\nontology/units.yaml\n",
                        "",
                        False,
                    )
                if args == ["show", "main:ontology/ontology.yaml"]:
                    return module.GitCommandResult(
                        tuple(args),
                        128,
                        "",
                        "fatal: unable to read main:ontology/ontology.yaml\n",
                        False,
                    )
                if args == ["show", "main:ontology/units.yaml"]:
                    return module.GitCommandResult(tuple(args), 0, units_text, "", False)
                self.fail(f"Unexpected git args: {args}")

            with mock.patch.object(module, "_run_git", side_effect=fake_run_git):
                payload = module.validate_ontology_changes(
                    repo_root=temp_root,
                    base_ref="main",
                    require_base_ref=True,
                )

        self.assertFalse(payload.get("ok"))
        self.assertTrue(payload.get("skipped_diff"))
        self.assertEqual(payload.get("added_ids"), [])
        self.assertEqual(payload.get("removed_ids"), [])
        errors = payload.get("errors", [])
        self.assertTrue(
            any(
                "Failed to read ontology/ontology.yaml from main: fatal: unable to read"
                in str(msg)
                for msg in errors
            ),
            msg=payload,
        )
        self.assertFalse(
            any("Missing ontology/ontology.yaml in base ref main." == str(msg) for msg in errors),
            msg=payload,
        )
        self.assertFalse(
            any("Failed to parse YAML in ontology/ontology.yaml" in str(msg) for msg in errors),
            msg=payload,
        )


if __name__ == "__main__":
    unittest.main()
