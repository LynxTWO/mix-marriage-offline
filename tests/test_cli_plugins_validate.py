import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestCliPluginsValidate(unittest.TestCase):
    def test_plugins_validate_bundled_json_is_stable(self) -> None:
        exit_a, stdout_a, stderr_a = _run_main(
            ["plugins", "validate", "--bundled-only", "--format", "json"]
        )
        exit_b, stdout_b, stderr_b = _run_main(
            ["plugins", "validate", "--bundled-only", "--format", "json"]
        )

        self.assertEqual(exit_a, 0, msg=stderr_a)
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertTrue(payload.get("bundled_only"))
        self.assertTrue(payload.get("ok"))
        self.assertGreater(payload.get("plugin_count", 0), 0)
        self.assertEqual(payload.get("issue_counts", {}).get("error"), 0)
        self.assertIn("/plugins", payload.get("plugins_dir", ""))
        plugins = payload.get("plugins", [])
        self.assertIsInstance(plugins, list)
        self.assertTrue(
            any(
                isinstance(plugin, dict)
                and plugin.get("plugin_id") == "PLUGIN.RENDERER.SAFE"
                for plugin in plugins
            ),
            msg=plugins,
        )

    def test_plugins_validate_invalid_manifest_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugins_dir = Path(temp_dir) / "plugins"
            manifest_path = plugins_dir / "renderers" / "broken.plugin.yaml"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                "\n".join(
                    [
                        'plugin_id: "PLUGIN.RENDERER.BROKEN"',
                        'plugin_type: "renderer"',
                        'name: "Broken Renderer"',
                        'version: "0.1.0"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            exit_a, stdout_a, stderr_a = _run_main(
                ["plugins", "validate", "--plugins", str(plugins_dir), "--format", "json"]
            )
            exit_b, stdout_b, stderr_b = _run_main(
                ["plugins", "validate", "--plugins", str(plugins_dir), "--format", "json"]
            )

        self.assertEqual(exit_a, 2, msg=stderr_a)
        self.assertEqual(exit_b, 2, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)
        self.assertEqual(stderr_a, "")
        self.assertEqual(stderr_b, "")

        payload = json.loads(stdout_a)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("plugin_count"), 0)
        self.assertGreater(payload.get("issue_counts", {}).get("error", 0), 0)
        issues = payload.get("issues", [])
        self.assertIsInstance(issues, list)
        self.assertTrue(
            any(
                isinstance(issue, dict)
                and "entrypoint" in str(issue.get("message", ""))
                for issue in issues
            ),
            msg=issues,
        )


if __name__ == "__main__":
    unittest.main()
