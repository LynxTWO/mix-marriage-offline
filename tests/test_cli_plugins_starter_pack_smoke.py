import contextlib
import io
import json
import unittest
from pathlib import Path

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = REPO_ROOT / "plugins"
EXAMPLE_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_GAIN_V0"
EXAMPLE_TILT_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_TILT_EQ_V0"
EXAMPLE_COMPRESSOR_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_SIMPLE_COMPRESSOR_V0"
EXAMPLE_MULTIBAND_COMPRESSOR_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_MULTIBAND_COMPRESSOR_V0"
EXAMPLE_MULTIBAND_EXPANDER_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_MULTIBAND_EXPANDER_V0"
EXAMPLE_MULTIBAND_DYNAMIC_AUTO_PLUGIN_ID = "PLUGIN.RENDERER.EXAMPLE_MULTIBAND_DYNAMIC_AUTO_V0"


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

        tilt_command = [
            "plugins",
            "show",
            EXAMPLE_TILT_PLUGIN_ID,
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]
        tilt_exit_a, tilt_stdout_a, tilt_stderr_a = _run_main(tilt_command)
        tilt_exit_b, tilt_stdout_b, tilt_stderr_b = _run_main(tilt_command)

        self.assertEqual(tilt_exit_a, 0, msg=tilt_stderr_a)
        self.assertEqual(tilt_exit_b, 0, msg=tilt_stderr_b)
        self.assertEqual(tilt_stdout_a, tilt_stdout_b)
        self.assertEqual(tilt_stderr_a, "")
        self.assertEqual(tilt_stderr_b, "")
        self.assertIn(f"plugin_id: {EXAMPLE_TILT_PLUGIN_ID}", tilt_stdout_a)
        self.assertIn("ui_layout_snapshot.violations_count: 0", tilt_stdout_a)
        self.assertIn("ui_hints.hint_count: 4", tilt_stdout_a)
        self.assertIn('"/properties/tilt_db/x_mmo_ui"', tilt_stdout_a)
        self.assertIn('"/properties/pivot_hz/x_mmo_ui"', tilt_stdout_a)

        compressor_command = [
            "plugins",
            "show",
            EXAMPLE_COMPRESSOR_PLUGIN_ID,
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]
        compressor_exit_a, compressor_stdout_a, compressor_stderr_a = _run_main(compressor_command)
        compressor_exit_b, compressor_stdout_b, compressor_stderr_b = _run_main(compressor_command)

        self.assertEqual(compressor_exit_a, 0, msg=compressor_stderr_a)
        self.assertEqual(compressor_exit_b, 0, msg=compressor_stderr_b)
        self.assertEqual(compressor_stdout_a, compressor_stdout_b)
        self.assertEqual(compressor_stderr_a, "")
        self.assertEqual(compressor_stderr_b, "")
        self.assertIn(f"plugin_id: {EXAMPLE_COMPRESSOR_PLUGIN_ID}", compressor_stdout_a)
        self.assertIn("ui_layout_snapshot.violations_count: 0", compressor_stdout_a)
        self.assertIn("ui_hints.hint_count: 8", compressor_stdout_a)
        self.assertIn('"/properties/threshold_db/x_mmo_ui"', compressor_stdout_a)
        self.assertIn('"/properties/detector_mode/x_mmo_ui"', compressor_stdout_a)
        self.assertIn('"/properties/macro_mix/x_mmo_ui"', compressor_stdout_a)

        mb_comp_command = [
            "plugins",
            "show",
            EXAMPLE_MULTIBAND_COMPRESSOR_PLUGIN_ID,
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]
        mb_comp_exit_a, mb_comp_stdout_a, mb_comp_stderr_a = _run_main(mb_comp_command)
        mb_comp_exit_b, mb_comp_stdout_b, mb_comp_stderr_b = _run_main(mb_comp_command)

        self.assertEqual(mb_comp_exit_a, 0, msg=mb_comp_stderr_a)
        self.assertEqual(mb_comp_exit_b, 0, msg=mb_comp_stderr_b)
        self.assertEqual(mb_comp_stdout_a, mb_comp_stdout_b)
        self.assertEqual(mb_comp_stderr_a, "")
        self.assertEqual(mb_comp_stderr_b, "")
        self.assertIn(f"plugin_id: {EXAMPLE_MULTIBAND_COMPRESSOR_PLUGIN_ID}", mb_comp_stdout_a)
        self.assertIn("ui_layout_snapshot.violations_count: 0", mb_comp_stdout_a)
        self.assertIn("ui_hints.hint_count: 13", mb_comp_stdout_a)
        self.assertIn('"/properties/slope_sensitivity/x_mmo_ui"', mb_comp_stdout_a)
        self.assertIn('"/properties/min_band_count/x_mmo_ui"', mb_comp_stdout_a)
        self.assertIn('"/properties/oversampling/x_mmo_ui"', mb_comp_stdout_a)

        mb_exp_command = [
            "plugins",
            "show",
            EXAMPLE_MULTIBAND_EXPANDER_PLUGIN_ID,
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]
        mb_exp_exit_a, mb_exp_stdout_a, mb_exp_stderr_a = _run_main(mb_exp_command)
        mb_exp_exit_b, mb_exp_stdout_b, mb_exp_stderr_b = _run_main(mb_exp_command)

        self.assertEqual(mb_exp_exit_a, 0, msg=mb_exp_stderr_a)
        self.assertEqual(mb_exp_exit_b, 0, msg=mb_exp_stderr_b)
        self.assertEqual(mb_exp_stdout_a, mb_exp_stdout_b)
        self.assertEqual(mb_exp_stderr_a, "")
        self.assertEqual(mb_exp_stderr_b, "")
        self.assertIn(f"plugin_id: {EXAMPLE_MULTIBAND_EXPANDER_PLUGIN_ID}", mb_exp_stdout_a)
        self.assertIn("ui_layout_snapshot.violations_count: 0", mb_exp_stdout_a)
        self.assertIn("ui_hints.hint_count: 13", mb_exp_stdout_a)
        self.assertIn('"/properties/lookahead_ms/x_mmo_ui"', mb_exp_stdout_a)

        mb_auto_command = [
            "plugins",
            "show",
            EXAMPLE_MULTIBAND_DYNAMIC_AUTO_PLUGIN_ID,
            "--plugins",
            str(PLUGINS_DIR),
            "--include-ui-hints",
            "--include-ui-layout-snapshot",
        ]
        mb_auto_exit_a, mb_auto_stdout_a, mb_auto_stderr_a = _run_main(mb_auto_command)
        mb_auto_exit_b, mb_auto_stdout_b, mb_auto_stderr_b = _run_main(mb_auto_command)

        self.assertEqual(mb_auto_exit_a, 0, msg=mb_auto_stderr_a)
        self.assertEqual(mb_auto_exit_b, 0, msg=mb_auto_stderr_b)
        self.assertEqual(mb_auto_stdout_a, mb_auto_stdout_b)
        self.assertEqual(mb_auto_stderr_a, "")
        self.assertEqual(mb_auto_stderr_b, "")
        self.assertIn(
            f"plugin_id: {EXAMPLE_MULTIBAND_DYNAMIC_AUTO_PLUGIN_ID}",
            mb_auto_stdout_a,
        )
        self.assertIn("ui_layout_snapshot.violations_count: 0", mb_auto_stdout_a)
        self.assertIn("ui_hints.hint_count: 13", mb_auto_stdout_a)
        self.assertIn('"/properties/detector_mode/x_mmo_ui"', mb_auto_stdout_a)

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

        tilt_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict) and row.get("plugin_id") == EXAMPLE_TILT_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(tilt_row, dict)
        if not isinstance(tilt_row, dict):
            return

        tilt_schema = tilt_row.get("config_schema")
        self.assertIsInstance(tilt_schema, dict)
        if isinstance(tilt_schema, dict):
            self.assertTrue(tilt_schema.get("present"))
            self.assertEqual(tilt_schema.get("parameter_count"), 4)

        tilt_layout = tilt_row.get("ui_layout")
        self.assertIsInstance(tilt_layout, dict)
        if isinstance(tilt_layout, dict):
            self.assertTrue(tilt_layout.get("present"))
            self.assertEqual(tilt_layout.get("snapshot_violations"), 0)

        tilt_hints = tilt_row.get("ui_hints")
        self.assertIsInstance(tilt_hints, dict)
        if isinstance(tilt_hints, dict):
            self.assertEqual(tilt_hints.get("hint_count"), 4)

        tilt_issue_counts = tilt_row.get("issue_counts")
        self.assertIsInstance(tilt_issue_counts, dict)
        if isinstance(tilt_issue_counts, dict):
            self.assertEqual(tilt_issue_counts.get("error"), 0)
            self.assertEqual(tilt_issue_counts.get("warn"), 0)

        compressor_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict) and row.get("plugin_id") == EXAMPLE_COMPRESSOR_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(compressor_row, dict)
        if not isinstance(compressor_row, dict):
            return

        compressor_schema = compressor_row.get("config_schema")
        self.assertIsInstance(compressor_schema, dict)
        if isinstance(compressor_schema, dict):
            self.assertTrue(compressor_schema.get("present"))
            self.assertEqual(compressor_schema.get("parameter_count"), 8)

        compressor_layout = compressor_row.get("ui_layout")
        self.assertIsInstance(compressor_layout, dict)
        if isinstance(compressor_layout, dict):
            self.assertTrue(compressor_layout.get("present"))
            self.assertEqual(compressor_layout.get("snapshot_violations"), 0)

        compressor_hints = compressor_row.get("ui_hints")
        self.assertIsInstance(compressor_hints, dict)
        if isinstance(compressor_hints, dict):
            self.assertEqual(compressor_hints.get("hint_count"), 8)

        compressor_issue_counts = compressor_row.get("issue_counts")
        self.assertIsInstance(compressor_issue_counts, dict)
        if isinstance(compressor_issue_counts, dict):
            self.assertEqual(compressor_issue_counts.get("error"), 0)
            self.assertEqual(compressor_issue_counts.get("warn"), 0)

        mb_comp_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict) and row.get("plugin_id") == EXAMPLE_MULTIBAND_COMPRESSOR_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(mb_comp_row, dict)
        if not isinstance(mb_comp_row, dict):
            return

        mb_comp_schema = mb_comp_row.get("config_schema")
        self.assertIsInstance(mb_comp_schema, dict)
        if isinstance(mb_comp_schema, dict):
            self.assertTrue(mb_comp_schema.get("present"))
            self.assertEqual(mb_comp_schema.get("parameter_count"), 13)

        mb_comp_layout = mb_comp_row.get("ui_layout")
        self.assertIsInstance(mb_comp_layout, dict)
        if isinstance(mb_comp_layout, dict):
            self.assertTrue(mb_comp_layout.get("present"))
            self.assertEqual(mb_comp_layout.get("snapshot_violations"), 0)

        mb_comp_hints = mb_comp_row.get("ui_hints")
        self.assertIsInstance(mb_comp_hints, dict)
        if isinstance(mb_comp_hints, dict):
            self.assertEqual(mb_comp_hints.get("hint_count"), 13)

        mb_comp_issue_counts = mb_comp_row.get("issue_counts")
        self.assertIsInstance(mb_comp_issue_counts, dict)
        if isinstance(mb_comp_issue_counts, dict):
            self.assertEqual(mb_comp_issue_counts.get("error"), 0)
            self.assertEqual(mb_comp_issue_counts.get("warn"), 0)

        mb_exp_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict) and row.get("plugin_id") == EXAMPLE_MULTIBAND_EXPANDER_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(mb_exp_row, dict)
        if not isinstance(mb_exp_row, dict):
            return

        mb_exp_schema = mb_exp_row.get("config_schema")
        self.assertIsInstance(mb_exp_schema, dict)
        if isinstance(mb_exp_schema, dict):
            self.assertTrue(mb_exp_schema.get("present"))
            self.assertEqual(mb_exp_schema.get("parameter_count"), 13)

        mb_exp_layout = mb_exp_row.get("ui_layout")
        self.assertIsInstance(mb_exp_layout, dict)
        if isinstance(mb_exp_layout, dict):
            self.assertTrue(mb_exp_layout.get("present"))
            self.assertEqual(mb_exp_layout.get("snapshot_violations"), 0)

        mb_exp_hints = mb_exp_row.get("ui_hints")
        self.assertIsInstance(mb_exp_hints, dict)
        if isinstance(mb_exp_hints, dict):
            self.assertEqual(mb_exp_hints.get("hint_count"), 13)

        mb_exp_issue_counts = mb_exp_row.get("issue_counts")
        self.assertIsInstance(mb_exp_issue_counts, dict)
        if isinstance(mb_exp_issue_counts, dict):
            self.assertEqual(mb_exp_issue_counts.get("error"), 0)
            self.assertEqual(mb_exp_issue_counts.get("warn"), 0)

        mb_auto_row = next(
            (
                row
                for row in plugins
                if isinstance(row, dict)
                and row.get("plugin_id") == EXAMPLE_MULTIBAND_DYNAMIC_AUTO_PLUGIN_ID
            ),
            None,
        )
        self.assertIsInstance(mb_auto_row, dict)
        if not isinstance(mb_auto_row, dict):
            return

        mb_auto_schema = mb_auto_row.get("config_schema")
        self.assertIsInstance(mb_auto_schema, dict)
        if isinstance(mb_auto_schema, dict):
            self.assertTrue(mb_auto_schema.get("present"))
            self.assertEqual(mb_auto_schema.get("parameter_count"), 13)

        mb_auto_layout = mb_auto_row.get("ui_layout")
        self.assertIsInstance(mb_auto_layout, dict)
        if isinstance(mb_auto_layout, dict):
            self.assertTrue(mb_auto_layout.get("present"))
            self.assertEqual(mb_auto_layout.get("snapshot_violations"), 0)

        mb_auto_hints = mb_auto_row.get("ui_hints")
        self.assertIsInstance(mb_auto_hints, dict)
        if isinstance(mb_auto_hints, dict):
            self.assertEqual(mb_auto_hints.get("hint_count"), 13)

        mb_auto_issue_counts = mb_auto_row.get("issue_counts")
        self.assertIsInstance(mb_auto_issue_counts, dict)
        if isinstance(mb_auto_issue_counts, dict):
            self.assertEqual(mb_auto_issue_counts.get("error"), 0)
            self.assertEqual(mb_auto_issue_counts.get("warn"), 0)


if __name__ == "__main__":
    unittest.main()
