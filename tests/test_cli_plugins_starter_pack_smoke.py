import contextlib
import io
import json
import unittest
from pathlib import Path

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = REPO_ROOT / "plugins"
EXAMPLE_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_GAIN_V0"


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestCliPluginsStarterPackSmoke(unittest.TestCase):
    def test_plugins_show_with_ui_metadata_is_deterministic(self) -> None:
        command = [
            "plugins",
            "show",
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]

        exit_a, stdout_a, stderr_a = _run_main(command)
        exit_b, stdout_b, stderr_b = _run_main(command)

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        self.assertIn(f"plugin_id: {EXAMPLE_PLUGIN_ID}", stdout_a)
        self.assertIn("config_schema.present: True", stdout_a)
        self.assertIn("ui_layout.present: True", stdout_a)
        self.assertIn("ui_layout_snapshot.present: True", stdout_a)
        self.assertIn("ui_layout_snapshot.violations_count: 0", stdout_a)
        self.assertIn("ui_hints.present: True", stdout_a)
        self.assertIn("ui_hints.hint_count: 3", stdout_a)
        self.assertIn('"/properties/bypass/x_mmo_ui"', stdout_a)
        self.assertIn('"/properties/gain_db/x_mmo_ui"', stdout_a)
        self.assertIn('"/properties/macro_mix/x_mmo_ui"', stdout_a)

    def test_plugins_ui_lint_is_deterministic_and_example_has_no_issues(self) -> None:
        text_command = [
            "plugins",
            "ui-lint",
            "--plugins",
            str(PLUGINS_DIR),
        ]
        exit_a, stdout_a, stderr_a = _run_main(text_command)
        exit_b, stdout_b, stderr_b = _run_main(text_command)

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")
        self.assertIn("Plugin UI lint OK", stdout_a)

        json_command = text_command + ["--format", "json"]
        json_exit, json_stdout, json_stderr = _run_main(json_command)
        self.assertEqual(json_exit, 0, msg=json_stderr)
        self.assertEqual(json_stderr, "")

        payload = json.loads(json_stdout)
        plugins = payload.get("plugins")
        self.assertIsInstance(plugins, list)
        if not isinstance(plugins, list):
            return

        example_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict) and row.get("plugin_id") == EXAMPLE_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(example_row, dict)
        if not isinstance(example_row, dict):
            return

        config_schema = example_row.get("config_schema")
        self.assertIsInstance(config_schema, dict)
        if isinstance(config_schema, dict):
            self.assertTrue(config_schema.get("present"))
            self.assertEqual(config_schema.get("parameter_count"), 3)

        ui_layout = example_row.get("ui_layout")
        self.assertIsInstance(ui_layout, dict)
        if isinstance(ui_layout, dict):
            self.assertTrue(ui_layout.get("present"))
            self.assertEqual(ui_layout.get("snapshot_violations"), 0)

        ui_hints = example_row.get("ui_hints")
        self.assertIsInstance(ui_hints, dict)
        if isinstance(ui_hints, dict):
            self.assertEqual(ui_hints.get("hint_count"), 3)

        issue_counts = example_row.get("issue_counts")
        self.assertIsInstance(issue_counts, dict)
        if isinstance(issue_counts, dict):
            self.assertEqual(issue_counts.get("error"), 0)
            self.assertEqual(issue_counts.get("warn"), 0)


if __name__ == "__main__":
    unittest.main()
