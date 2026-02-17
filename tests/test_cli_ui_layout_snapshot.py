import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
SANDBOX_ROOT = REPO_ROOT / "sandbox_tmp" / "test_cli_ui_layout_snapshot" / str(os.getpid())


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exit_code = main(args)
    return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()


def _clean_layout() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "layout_id": "LAYOUT.GUI.DEFAULT",
        "grid": {
            "columns": 12,
            "gap_px": 16,
            "row_height_px": 48,
            "margin_px": 24,
        },
        "container": {
            "section_gap_px": 20,
        },
        "breakpoints": [
            {
                "breakpoint_id": "mobile",
                "max_viewport_width_px": 640,
                "grid_overrides": {"gap_px": 8},
            },
            {
                "breakpoint_id": "desktop",
                "min_viewport_width_px": 1000,
                "grid_overrides": {"gap_px": 16},
            },
        ],
        "sections": [
            {
                "section_id": "header",
                "widgets": [
                    {
                        "widget_id": "widget.header.status",
                        "col_span": 6,
                        "row_span": 1,
                        "param_ref": "PARAM.HEADER.STATUS",
                    },
                    {
                        "widget_id": "widget.header.title",
                        "col_span": 6,
                        "row_span": 1,
                        "param_ref": "PARAM.HEADER.TITLE",
                    },
                ],
            },
            {
                "section_id": "mix",
                "widgets": [
                    {
                        "widget_id": "widget.mix.eq",
                        "col_span": 4,
                        "row_span": 2,
                        "min_width_px": 120,
                    },
                    {
                        "widget_id": "widget.mix.comp",
                        "col_span": 4,
                        "row_span": 2,
                    },
                    {
                        "widget_id": "widget.mix.pan",
                        "col_span": 4,
                        "row_span": 2,
                    },
                ],
            },
        ],
    }


def _violation_layout() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "layout_id": "LAYOUT.GUI.VIOLATION",
        "grid": {
            "columns": 12,
            "gap_px": 12,
            "row_height_px": 40,
            "margin_px": 24,
        },
        "container": {
            "section_gap_px": 16,
        },
        "sections": [
            {
                "section_id": "main",
                "widgets": [
                    {
                        "widget_id": "widget.main.a",
                        "col_start": 1,
                        "row_start": 1,
                        "col_span": 8,
                        "row_span": 2,
                    },
                    {
                        "widget_id": "widget.main.b",
                        "col_start": 4,
                        "row_start": 1,
                        "col_span": 6,
                        "row_span": 2,
                    },
                    {
                        "widget_id": "widget.main.c",
                        "col_start": 11,
                        "row_start": 3,
                        "col_span": 4,
                        "row_span": 1,
                        "min_width_px": 200,
                    },
                ],
            }
        ],
    }


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(issue.get("severity", "")),
        str(issue.get("issue_id", "")),
        str(issue.get("message", "")),
        json.dumps(issue.get("evidence", {}), sort_keys=True, separators=(",", ":")),
    )


def _case_dir(case_id: str) -> Path:
    case_path = SANDBOX_ROOT / case_id
    case_path.mkdir(parents=True, exist_ok=True)
    return case_path


def setUpModule() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if SANDBOX_ROOT.exists():
        shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)


class TestUiLayoutSnapshotCli(unittest.TestCase):
    def test_ui_layout_snapshot_is_deterministic_and_schema_valid(self) -> None:
        validator = _schema_validator("ui_layout_snapshot.schema.json")
        temp_path = _case_dir("determinism")
        layout_path = temp_path / "ui_layout.json"
        out_a = temp_path / "snapshot_a.json"
        out_b = temp_path / "snapshot_b.json"
        _write_json(layout_path, _clean_layout())

        exit_a, stdout_a, stderr_a = _run_main(
            [
                "ui",
                "layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "1280x720",
                "--out",
                str(out_a),
                "--force",
            ]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            [
                "ui",
                "layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "1280x720",
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
        validator.validate(payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["violations"], [])
        self.assertEqual(payload["selected_breakpoint_id"], "desktop")
        widget_ids = [row["widget_id"] for row in payload["widgets"]]
        self.assertEqual(widget_ids, sorted(widget_ids))
        self.assertNotIn("\\", out_a.read_text(encoding="utf-8"))

    def test_ui_layout_snapshot_violations_exit_2_and_sorted(self) -> None:
        validator = _schema_validator("ui_layout_snapshot.schema.json")
        temp_path = _case_dir("violations")
        layout_path = temp_path / "ui_layout.json"
        out_a = temp_path / "snapshot_a.json"
        out_b = temp_path / "snapshot_b.json"
        _write_json(layout_path, _violation_layout())

        exit_a, stdout_a, stderr_a = _run_main(
            [
                "ui-layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "480x220",
                "--out",
                str(out_a),
                "--force",
            ]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            [
                "ui-layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "480x220",
                "--out",
                str(out_b),
                "--force",
            ]
        )

        self.assertEqual(exit_a, 2, msg=stderr_a)
        self.assertEqual(exit_b, 2, msg=stderr_b)
        self.assertEqual(stdout_a, "")
        self.assertEqual(stdout_b, "")
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

        payload = json.loads(out_a.read_text(encoding="utf-8"))
        validator.validate(payload)
        self.assertFalse(payload["ok"])
        violations = payload["violations"]
        issue_ids = [issue["issue_id"] for issue in violations]
        self.assertIn("ISSUE.UI.LAYOUT.OVERLAP", issue_ids)
        self.assertIn("ISSUE.UI.LAYOUT.OFF_SCREEN", issue_ids)
        self.assertEqual(violations, sorted(violations, key=_issue_sort_key))

    def test_ui_layout_snapshot_overwrite_requires_force(self) -> None:
        temp_path = _case_dir("overwrite")
        layout_path = temp_path / "ui_layout.json"
        out_path = temp_path / "snapshot.json"
        _write_json(layout_path, _clean_layout())
        out_path.write_text("{}", encoding="utf-8")

        exit_refused, stdout_refused, stderr_refused = _run_main(
            [
                "ui-layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "1280x720",
                "--out",
                str(out_path),
            ]
        )
        self.assertEqual(exit_refused, 1)
        self.assertEqual(stdout_refused, "")
        self.assertIn("File exists", stderr_refused)
        self.assertIn("--force", stderr_refused)
        self.assertEqual(out_path.read_text(encoding="utf-8"), "{}")

        exit_allowed, stdout_allowed, stderr_allowed = _run_main(
            [
                "ui-layout-snapshot",
                "--layout",
                str(layout_path),
                "--viewport",
                "1280x720",
                "--out",
                str(out_path),
                "--force",
            ]
        )
        self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
        self.assertEqual(stdout_allowed, "")
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
