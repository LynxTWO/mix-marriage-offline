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

    def _sample_layout_payload(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "layout_id": "LAYOUT.PLUGIN.RENDERER.BUNDLE",
            "grid": {
                "columns": 12,
                "gap_px": 16,
                "row_height_px": 48,
                "margin_px": 24,
            },
            "container": {"section_gap_px": 16},
            "sections": [
                {
                    "section_id": "main",
                    "widgets": [
                        {
                            "widget_id": "widget.main.gain_db",
                            "col_span": 12,
                            "row_span": 1,
                            "param_ref": "PARAM.RENDERER.GAIN_DB",
                        }
                    ],
                }
            ],
        }

    def _write_temp_plugin_with_layout(self, plugins_dir: Path) -> tuple[str, Path]:
        plugin_id = "PLUGIN.RENDERER.BUNDLE_LAYOUT"
        manifest_path = plugins_dir / "renderers" / "bundle_layout.plugin.yaml"
        layout_path = manifest_path.parent / "ui" / "layout.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.write_text(
            json.dumps(self._sample_layout_payload(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            "\n".join(
                [
                    f'plugin_id: "{plugin_id}"',
                    'plugin_type: "renderer"',
                    'name: "Bundle Layout Renderer"',
                    'version: "0.1.0"',
                    'license: "Apache-2.0"',
                    'description: "Renderer fixture for plugin layout bundle tests."',
                    'mmo_min_version: "0.1.0"',
                    'ontology_min_version: "0.1.0"',
                    'entrypoint: "plugins.renderers.safe_renderer:SafeRenderer"',
                    'ui_layout: "ui/layout.json"',
                    "config_schema:",
                    '  "$schema": "https://json-schema.org/draft/2020-12/schema"',
                    '  "type": "object"',
                    '  "additionalProperties": false',
                    '  "properties":',
                    '    "gain_db":',
                    '      "type": "number"',
                    '      "minimum": -6',
                    '      "maximum": 6',
                    '      "x_mmo_ui":',
                    '        "widget": "fader"',
                    '        "units": "dB"',
                    '        "step": 0.5',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return plugin_id, layout_path

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

    def test_bundle_command_optional_plugins_block(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
                    "--include-plugins",
                    "--plugins",
                    str(repo_root / "plugins"),
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
            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)

            plugins_payload = bundle.get("plugins")
            self.assertIsInstance(plugins_payload, dict)
            if not isinstance(plugins_payload, dict):
                return

            self.assertEqual(
                plugins_payload.get("plugins_dir"),
                (repo_root / "plugins").resolve().as_posix(),
            )
            entries = plugins_payload.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list):
                return
            self.assertTrue(len(entries) >= 2)

    def test_bundle_command_include_plugin_layouts_requires_include_plugins(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
                    "--include-plugin-layouts",
                    "--out",
                    str(out_bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("--include-plugin-layouts requires --include-plugins", result.stderr)

    def test_bundle_command_include_plugin_layout_snapshots_requires_layouts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
                    "--include-plugins",
                    "--include-plugin-layout-snapshots",
                    "--plugins",
                    str(repo_root / "plugins"),
                    "--out",
                    str(out_bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "--include-plugin-layout-snapshots requires --include-plugin-layouts",
                result.stderr,
            )

    def test_bundle_command_include_plugin_ui_hints_requires_include_plugins(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
                    "--include-plugin-ui-hints",
                    "--out",
                    str(out_bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("--include-plugin-ui-hints requires --include-plugins", result.stderr)

    def test_bundle_command_include_plugin_layouts_snapshots_and_ui_hints_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "ui_bundle.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            out_bundle_path = temp_path / "ui_bundle.json"
            plugins_dir = temp_path / "plugins"
            plugin_id, layout_path = self._write_temp_plugin_with_layout(plugins_dir)
            expected_layout_path = layout_path.resolve().as_posix()
            report_path.write_text(
                json.dumps(_sample_report_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src")
            args = [
                self._python_cmd(),
                "-m",
                "mmo",
                "bundle",
                "--report",
                str(report_path),
                "--include-plugins",
                "--include-plugin-layouts",
                "--include-plugin-layout-snapshots",
                "--include-plugin-ui-hints",
                "--plugins",
                str(plugins_dir),
                "--out",
                str(out_bundle_path),
            ]
            first = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            first_bytes = out_bundle_path.read_bytes()

            second = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            second_bytes = out_bundle_path.read_bytes()
            self.assertEqual(first_bytes, second_bytes)

            bundle = json.loads(out_bundle_path.read_text(encoding="utf-8"))
            validator.validate(bundle)
            plugins_payload = bundle.get("plugins")
            self.assertIsInstance(plugins_payload, dict)
            if not isinstance(plugins_payload, dict):
                return
            entries = plugins_payload.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list):
                return

            plugin_entry = next(
                (
                    item
                    for item in entries
                    if isinstance(item, dict)
                    and item.get("plugin_id") == plugin_id
                ),
                None,
            )
            self.assertIsInstance(plugin_entry, dict)
            if not isinstance(plugin_entry, dict):
                return

            ui_layout = plugin_entry.get("ui_layout")
            self.assertIsInstance(ui_layout, dict)
            if not isinstance(ui_layout, dict):
                return
            self.assertTrue(ui_layout.get("present"))
            self.assertEqual(ui_layout.get("path"), expected_layout_path)
            self.assertIsInstance(ui_layout.get("sha256"), str)
            self.assertEqual(len(ui_layout.get("sha256", "")), 64)

            snapshot = plugin_entry.get("ui_layout_snapshot")
            self.assertIsInstance(snapshot, dict)
            if not isinstance(snapshot, dict):
                return
            self.assertTrue(snapshot.get("present"))
            self.assertEqual(snapshot.get("path"), expected_layout_path)
            self.assertIsInstance(snapshot.get("sha256"), str)
            self.assertEqual(len(snapshot.get("sha256", "")), 64)
            self.assertEqual(snapshot.get("violations_count"), 0)

            ui_hints = plugin_entry.get("ui_hints")
            self.assertIsInstance(ui_hints, dict)
            if not isinstance(ui_hints, dict):
                return
            self.assertTrue(ui_hints.get("present"))
            self.assertEqual(ui_hints.get("hint_count"), 1)
            self.assertIsInstance(ui_hints.get("sha256"), str)
            self.assertEqual(len(ui_hints.get("sha256", "")), 64)
            hints = ui_hints.get("hints")
            self.assertIsInstance(hints, list)
            if isinstance(hints, list) and hints:
                self.assertEqual(
                    hints[0].get("json_pointer"),
                    "/properties/gain_db/x_mmo_ui",
                )


if __name__ == "__main__":
    unittest.main()
