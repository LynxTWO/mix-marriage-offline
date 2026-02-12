import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.project_file import new_project, update_project_last_run, write_project


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _sample_report_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.CLI.BUNDLE.POINTERS.TEST",
        "project_id": "PROJECT.CLI.BUNDLE.POINTERS.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": [],
    }


class TestCliBundlePointers(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_bundle_command_embeds_project_subset_and_pointers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            out_dir = temp_path / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            report_path = temp_path / "report.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            deliverables_index_path = out_dir / "deliverables_index.json"
            deliverables_index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "root_out_dir": out_dir.resolve().as_posix(),
                        "mode": "single",
                        "entries": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            project_path = temp_path / "project.json"
            project_payload = new_project(stems_dir, notes=None)
            project_payload = update_project_last_run(
                project_payload,
                {
                    "mode": "single",
                    "out_dir": out_dir.resolve().as_posix(),
                    "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                },
            )
            write_project(project_path, project_payload)

            out_bundle_path = temp_path / "ui_bundle.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "bundle",
                    "--report",
                    str(report_path),
                    "--project",
                    str(project_path),
                    "--deliverables-index",
                    str(deliverables_index_path),
                    "--out",
                    str(out_bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_bundle_path.exists())

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)

            self.assertEqual(
                bundle.get("pointers"),
                {
                    "project_path": project_path.resolve().as_posix(),
                    "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                },
            )
            self.assertEqual(
                bundle.get("project"),
                {
                    "project_id": project_payload["project_id"],
                    "stems_dir": project_payload["stems_dir"],
                    "last_run": project_payload["last_run"],
                    "updated_at_utc": project_payload["updated_at_utc"],
                },
            )

    def test_bundle_command_embeds_optional_gui_state_pointer(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            out_dir = temp_path / "out"
            out_dir.mkdir(parents=True, exist_ok=True)

            report_path = temp_path / "report.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            deliverables_index_path = out_dir / "deliverables_index.json"
            deliverables_index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "root_out_dir": out_dir.resolve().as_posix(),
                        "mode": "single",
                        "entries": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            project_path = temp_path / "project.json"
            project_payload = new_project(stems_dir, notes=None)
            project_payload = update_project_last_run(
                project_payload,
                {
                    "mode": "single",
                    "out_dir": out_dir.resolve().as_posix(),
                    "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                },
            )
            write_project(project_path, project_payload)

            gui_state_path = temp_path / "gui_state.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "bundle",
                    "--report",
                    str(report_path),
                    "--project",
                    str(project_path),
                    "--deliverables-index",
                    str(deliverables_index_path),
                    "--gui-state",
                    str(gui_state_path),
                    "--out",
                    str(out_bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_bundle_path.exists())

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)

            self.assertEqual(
                bundle.get("pointers"),
                {
                    "project_path": project_path.resolve().as_posix(),
                    "deliverables_index_path": deliverables_index_path.resolve().as_posix(),
                    "gui_state_path": gui_state_path.resolve().as_posix(),
                },
            )


if __name__ == "__main__":
    unittest.main()
