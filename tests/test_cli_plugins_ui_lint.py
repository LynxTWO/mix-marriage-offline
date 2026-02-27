import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_ROOT = REPO_ROOT / "sandbox_tmp" / "test_cli_plugins_ui_lint" / str(os.getpid())


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_config_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "gain_db": {
                "type": "number",
                "x_mmo_ui": {
                    "widget": "fader",
                    "units": "dB",
                    "step": 0.5,
                },
            },
            "mode": {
                "type": "string",
                "enum": ["safe", "wide"],
                "x_mmo_ui": {
                    "widget": "selector",
                    "options": [
                        {"value": "safe", "label": "Safe"},
                        {"value": "wide", "label": "Wide"},
                    ],
                },
            },
        },
    }


def _base_layout_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "layout_id": "LAYOUT.PLUGIN.UI_LINT.TEST",
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
                        "col_span": 6,
                        "row_span": 1,
                        "param_ref": "PARAM.RENDERER.GAIN_DB",
                    },
                    {
                        "widget_id": "widget.main.mode",
                        "col_span": 6,
                        "row_span": 1,
                        "param_ref": "PARAM.RENDERER.MODE",
                    },
                ],
            }
        ],
    }


def _write_plugin_fixture(
    *,
    case_dir: Path,
    plugin_id: str,
    config_schema: dict[str, object] | None,
    layout_payload: dict[str, object] | None,
) -> Path:
    plugins_dir = case_dir / "plugins"
    plugin_dir = plugins_dir / "renderers"
    manifest_path = plugin_dir / "ui_lint_fixture.plugin.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "plugin_id": plugin_id,
        "plugin_type": "renderer",
        "name": "Plugin UI Lint Fixture",
        "version": "0.1.0",
        "entrypoint": "mmo.plugins.renderers.safe_renderer:SafeRenderer",
    }
    if config_schema is not None:
        manifest["config_schema"] = config_schema
    if layout_payload is not None:
        layout_path = plugin_dir / "ui" / "layout.json"
        _write_json(layout_path, layout_payload)
        manifest["ui_layout"] = "ui/layout.json"

    _write_json(manifest_path, manifest)
    return plugins_dir


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


class TestCliPluginsUiLint(unittest.TestCase):
    def test_plugins_ui_lint_json_is_deterministic(self) -> None:
        case_dir = _case_dir("deterministic")
        plugins_dir = _write_plugin_fixture(
            case_dir=case_dir,
            plugin_id="PLUGIN.RENDERER.UI_LINT_DETERMINISTIC",
            config_schema=_base_config_schema(),
            layout_payload=_base_layout_payload(),
        )

        exit_a, stdout_a, stderr_a = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertTrue(payload.get("ok"))
        issue_counts = payload.get("issue_counts", {})
        self.assertEqual(issue_counts.get("error"), 0)
        self.assertEqual(issue_counts.get("warn"), 0)

    def test_plugins_ui_lint_missing_layout_param_exits_2(self) -> None:
        case_dir = _case_dir("missing_layout_param")
        layout_payload = _base_layout_payload()
        layout_sections = layout_payload.get("sections")
        self.assertIsInstance(layout_sections, list)
        if isinstance(layout_sections, list):
            widgets = layout_sections[0].get("widgets")
            self.assertIsInstance(widgets, list)
            if isinstance(widgets, list):
                widgets[1]["param_ref"] = "PARAM.RENDERER.DOES_NOT_EXIST"

        plugins_dir = _write_plugin_fixture(
            case_dir=case_dir,
            plugin_id="PLUGIN.RENDERER.UI_LINT_MISSING_PARAM",
            config_schema=_base_config_schema(),
            layout_payload=layout_payload,
        )

        exit_a, stdout_a, stderr_a = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )

        self.assertEqual(exit_a, 2, msg=stderr_a)
        self.assertEqual(exit_b, 2, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertFalse(payload.get("ok"))
        issues = payload.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertTrue(
            any(
                isinstance(issue, dict)
                and issue.get("issue_id") == "ISSUE.UI.PLUGIN.WIDGET_PARAM_REF_UNKNOWN"
                and "does not match any config parameter" in str(issue.get("message", ""))
                for issue in issues
            ),
            msg=issues,
        )

    def test_plugins_ui_lint_hint_without_parameter_exits_2(self) -> None:
        case_dir = _case_dir("missing_hint_param")
        config_schema = _base_config_schema()
        config_schema["x_mmo_ui"] = {"widget": "toggle"}
        plugins_dir = _write_plugin_fixture(
            case_dir=case_dir,
            plugin_id="PLUGIN.RENDERER.UI_LINT_HINT_MISSING_PARAM",
            config_schema=config_schema,
            layout_payload=None,
        )

        exit_code, stdout, stderr = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )
        self.assertEqual(exit_code, 2, msg=stderr)
        self.assertEqual(stderr, "")

        payload = json.loads(stdout)
        issues = payload.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertTrue(
            any(
                isinstance(issue, dict)
                and issue.get("issue_id") == "ISSUE.UI.PLUGIN.HINT_PARAM_REF_UNKNOWN"
                and issue.get("evidence", {}).get("json_pointer") == "/x_mmo_ui"
                for issue in issues
            ),
            msg=issues,
        )

    def test_plugins_ui_lint_reports_layout_violations(self) -> None:
        case_dir = _case_dir("layout_violations")
        layout_payload = _base_layout_payload()
        layout_sections = layout_payload.get("sections")
        self.assertIsInstance(layout_sections, list)
        if isinstance(layout_sections, list):
            widgets = layout_sections[0].get("widgets")
            self.assertIsInstance(widgets, list)
            if isinstance(widgets, list):
                widgets[0]["col_start"] = 1
                widgets[0]["row_start"] = 1
                widgets[0]["col_span"] = 8
                widgets[1]["col_start"] = 4
                widgets[1]["row_start"] = 1
                widgets[1]["col_span"] = 8

        plugins_dir = _write_plugin_fixture(
            case_dir=case_dir,
            plugin_id="PLUGIN.RENDERER.UI_LINT_LAYOUT_VIOLATION",
            config_schema=_base_config_schema(),
            layout_payload=layout_payload,
        )

        exit_code, stdout, stderr = _run_main(
            ["plugins", "ui-lint", "--plugins", str(plugins_dir), "--format", "json"]
        )
        self.assertEqual(exit_code, 2, msg=stderr)
        self.assertEqual(stderr, "")

        payload = json.loads(stdout)
        issues = payload.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertTrue(
            any(
                isinstance(issue, dict)
                and issue.get("issue_id") == "ISSUE.UI.PLUGIN.LAYOUT_VIOLATION"
                for issue in issues
            ),
            msg=issues,
        )


if __name__ == "__main__":
    unittest.main()
