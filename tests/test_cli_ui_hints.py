"""Tests for ``mmo ui-hints`` commands."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_ROOT = REPO_ROOT / "sandbox_tmp" / "test_cli_ui_hints" / str(os.getpid())


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _case_dir(case_id: str) -> Path:
    case_path = SANDBOX_ROOT / case_id
    case_path.mkdir(parents=True, exist_ok=True)
    return case_path


def _valid_config_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "enabled": {
                "type": "boolean",
                "x_mmo_ui": {
                    "widget": "toggle",
                    "group": "main",
                    "order": 0,
                    "help": "Enable the processor.",
                },
            },
            "gain_db": {
                "type": "number",
                "minimum": -12.0,
                "maximum": 12.0,
                "x_mmo_ui": {
                    "widget": "fader",
                    "units": "dB",
                    "step": 0.5,
                    "fine_step": 0.1,
                    "modifier_key": "shift",
                    "min": -12.0,
                    "max": 12.0,
                    "group": "main",
                    "order": 1,
                    "help": "Output gain.",
                },
            },
            "mode": {
                "type": "string",
                "enum": ["safe", "aggressive"],
                "x_mmo_ui": {
                    "widget": "selector",
                    "options": [
                        {"value": "safe", "label": "Safe"},
                        {"value": "aggressive", "label": "Aggressive"},
                    ],
                    "order": 2,
                    "help": "Processing mode.",
                },
            },
        },
    }


def _invalid_config_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "a_gain": {
                "type": "number",
                "x_mmo_ui": {
                    "widget": "bad_widget",
                    "order": -1,
                },
            },
            "m_select": {
                "type": "string",
                "x_mmo_ui": {
                    "widget": "selector",
                    "options": [
                        {"value": "safe", "label": ""},
                        {"label": "Missing value"},
                    ],
                },
            },
            "z_mode": {
                "type": "string",
                "x_mmo_ui": {
                    "widget": "selector",
                },
            },
        },
    }


def _lint_error_sort_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("json_pointer", "")),
        str(row.get("path", "")),
        str(row.get("message", "")),
    )


def setUpModule() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil

    if SANDBOX_ROOT.exists():
        shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)


class TestUiHintsLintCli(unittest.TestCase):
    def test_lint_json_is_deterministic(self) -> None:
        temp_path = _case_dir("lint_deterministic")
        schema_path = temp_path / "config_schema.json"
        _write_json(schema_path, _valid_config_schema())

        exit_a, stdout_a, stderr_a = _run_main(
            [
                "ui-hints",
                "lint",
                "--schema",
                str(schema_path),
                "--format",
                "json",
            ]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            [
                "ui-hints",
                "lint",
                "--schema",
                str(schema_path),
                "--format",
                "json",
            ]
        )

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error_count"], 0)
        self.assertEqual(payload["hint_count"], 3)
        self.assertNotIn("\\", payload["schema_path"])

    def test_lint_errors_exit_2_and_are_stably_sorted(self) -> None:
        temp_path = _case_dir("lint_errors_sorted")
        schema_path = temp_path / "config_schema_invalid.json"
        _write_json(schema_path, _invalid_config_schema())

        exit_a, stdout_a, stderr_a = _run_main(
            [
                "ui-hints",
                "lint",
                "--schema",
                str(schema_path),
                "--format",
                "json",
            ]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            [
                "ui-hints",
                "lint",
                "--schema",
                str(schema_path),
                "--format",
                "json",
            ]
        )

        self.assertEqual(exit_a, 2, msg=stderr_a)
        self.assertEqual(exit_b, 2, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertFalse(payload["ok"])
        self.assertGreater(payload["error_count"], 0)
        errors = payload.get("errors")
        self.assertIsInstance(errors, list)
        if not isinstance(errors, list):
            return
        self.assertEqual(errors, sorted(errors, key=_lint_error_sort_key))
        pointers = [row.get("json_pointer", "") for row in errors if isinstance(row, dict)]
        self.assertIn("/properties/a_gain/x_mmo_ui", pointers)
        self.assertIn("/properties/m_select/x_mmo_ui", pointers)
        self.assertIn("/properties/z_mode/x_mmo_ui", pointers)


class TestUiHintsExtractCli(unittest.TestCase):
    def test_extract_is_deterministic(self) -> None:
        temp_path = _case_dir("extract_deterministic")
        schema_path = temp_path / "config_schema.json"
        out_a = temp_path / "ui_hints_a.json"
        out_b = temp_path / "ui_hints_b.json"
        _write_json(schema_path, _valid_config_schema())

        exit_a, stdout_a, stderr_a = _run_main(
            [
                "ui-hints",
                "extract",
                "--schema",
                str(schema_path),
                "--out",
                str(out_a),
                "--force",
            ]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            [
                "ui-hints",
                "extract",
                "--schema",
                str(schema_path),
                "--out",
                str(out_b),
                "--force",
            ]
        )

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, "")
        self.assertEqual(stdout_b, "")
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

        payload = json.loads(out_a.read_text(encoding="utf-8"))
        self.assertEqual(payload["hint_count"], 3)
        pointers = [row["json_pointer"] for row in payload["hints"]]
        self.assertEqual(pointers, sorted(pointers))
        self.assertNotIn("\\", payload["schema_path"])

    def test_extract_overwrite_requires_force(self) -> None:
        temp_path = _case_dir("extract_overwrite")
        schema_path = temp_path / "config_schema.json"
        out_path = temp_path / "ui_hints.json"
        _write_json(schema_path, _valid_config_schema())
        out_path.write_text('{"seed":true}\n', encoding="utf-8")

        refused_exit, refused_stdout, refused_stderr = _run_main(
            [
                "ui-hints",
                "extract",
                "--schema",
                str(schema_path),
                "--out",
                str(out_path),
            ]
        )
        self.assertEqual(refused_exit, 1)
        self.assertEqual(refused_stdout, "")
        self.assertIn("File exists", refused_stderr)
        self.assertIn("--force", refused_stderr)
        self.assertEqual(out_path.read_text(encoding="utf-8"), '{"seed":true}\n')

        allowed_exit, allowed_stdout, allowed_stderr = _run_main(
            [
                "ui-hints",
                "extract",
                "--schema",
                str(schema_path),
                "--out",
                str(out_path),
                "--force",
            ]
        )
        self.assertEqual(allowed_exit, 0, msg=allowed_stderr)
        self.assertEqual(allowed_stdout, "")
        self.assertEqual(allowed_stderr, "")
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["hint_count"], 3)

    def test_extract_schema_path_uses_forward_slashes(self) -> None:
        temp_path = _case_dir("extract_hygiene")
        schema_path = temp_path / "config_schema.json"
        out_path = temp_path / "ui_hints.json"
        _write_json(schema_path, _valid_config_schema())

        schema_arg = str(schema_path).replace("/", "\\")
        exit_code, stdout, stderr = _run_main(
            [
                "ui-hints",
                "extract",
                "--schema",
                schema_arg,
                "--out",
                str(out_path),
                "--force",
            ]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertNotIn("\\", payload["schema_path"])
        self.assertTrue(payload["schema_path"].endswith("config_schema.json"))


if __name__ == "__main__":
    unittest.main()
