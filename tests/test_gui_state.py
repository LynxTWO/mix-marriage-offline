import json
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.gui_state import default_gui_state, validate_gui_state
from mmo.core.render_targets import list_render_targets


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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestGuiState(unittest.TestCase):
    def test_default_gui_state_is_schema_valid_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "gui_state.schema.json")

        first = default_gui_state()
        second = default_gui_state()

        validator.validate(first)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            {
                "schema_version": "0.1.0",
                "last_opened_project_path": "",
                "selected_targets": [],
                "selected_preset_id": None,
                "selected_template_ids": [],
                "nerd_mode": False,
                "selected_tab": "dashboard",
            },
        )

    def test_validate_gui_state_unknown_tab_fails_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gui_state_path = Path(temp_dir) / "gui_state.json"
            payload = default_gui_state()
            payload["selected_tab"] = "mixbus"
            _write_json(gui_state_path, payload)

            with self.assertRaises(ValueError) as raised:
                validate_gui_state(gui_state_path)

        self.assertEqual(
            str(raised.exception),
            (
                "Unknown selected_tab: mixbus. Allowed tabs: "
                "dashboard, scene, targets, run, results"
            ),
        )

    def test_validate_gui_state_selected_targets_must_be_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gui_state_path = Path(temp_dir) / "gui_state.json"
            payload = default_gui_state()
            payload["selected_targets"] = ["TARGET.UNKNOWN.TEST"]
            _write_json(gui_state_path, payload)

            with self.assertRaises(ValueError) as raised:
                validate_gui_state(gui_state_path)

        available_targets = sorted(
            target_id
            for target in list_render_targets()
            for target_id in [target.get("target_id")]
            if isinstance(target_id, str) and target_id
        )
        self.assertEqual(
            str(raised.exception),
            (
                "Unknown selected_targets: TARGET.UNKNOWN.TEST. "
                f"Available target IDs: {', '.join(available_targets)}"
            ),
        )

    def test_cli_gui_state_default_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gui_state_path = Path(temp_dir) / "gui_state.json"

            default_exit = main(
                [
                    "gui-state",
                    "default",
                    "--out",
                    str(gui_state_path),
                ]
            )
            self.assertEqual(default_exit, 0)
            self.assertTrue(gui_state_path.exists())
            self.assertEqual(
                json.loads(gui_state_path.read_text(encoding="utf-8")),
                default_gui_state(),
            )

            validate_stdout = StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(
                    [
                        "gui-state",
                        "validate",
                        "--in",
                        str(gui_state_path),
                    ]
                )
            self.assertEqual(validate_exit, 0)
            self.assertIn("GUI state is valid.", validate_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
