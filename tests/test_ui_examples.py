import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from mmo.core.ui_screen_examples import load_ui_screen_example, load_ui_screen_examples


class TestUiExamples(unittest.TestCase):
    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        src_dir = str((repo_root / "src").resolve())
        self._original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = (
            src_dir
            if not self._original_pythonpath
            else f"{src_dir}{os.pathsep}{self._original_pythonpath}"
        )

    def tearDown(self) -> None:
        if self._original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
            return
        os.environ["PYTHONPATH"] = self._original_pythonpath

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_validate_ui_examples_tool_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), "tools/validate_ui_examples.py"],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertGreaterEqual(payload.get("count", 0), 10)
        self.assertEqual(payload.get("failures"), [])

    def test_loader_order_is_deterministic_and_covers_all_screens(self) -> None:
        repo_root = self._repo_root()
        examples_dir = repo_root / "examples" / "ui_screens"
        paths = sorted(examples_dir.glob("*.json"), key=lambda path: path.name)

        first = load_ui_screen_examples(examples_dir)
        second = load_ui_screen_examples(examples_dir)
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(paths))
        self.assertEqual(
            first,
            [load_ui_screen_example(path) for path in paths],
        )

        screen_ids = {
            item.get("screen_id")
            for item in first
            if isinstance(item, dict) and isinstance(item.get("screen_id"), str)
        }
        self.assertEqual(
            screen_ids,
            {
                "DASHBOARD",
                "PRESETS",
                "RUN",
                "RUN_TRANSLATION",
                "RESULTS",
                "COMPARE",
                "STEMS_REVIEW",
            },
        )

        modes = {
            item.get("mode")
            for item in first
            if isinstance(item, dict) and isinstance(item.get("mode"), str)
        }
        self.assertIn("default", modes)
        self.assertIn("nerd", modes)

    def test_cli_ui_examples_list_json_is_deterministic(self) -> None:
        command = [self._python_cmd(), "-m", "mmo", "ui-examples", "list", "--format", "json"]
        first = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        second = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertIsInstance(payload, list)
        if not isinstance(payload, list):
            return
        filenames = [
            item.get("filename")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("filename"), str)
        ]
        self.assertEqual(filenames, sorted(filenames))
        self.assertIn("dashboard_default_safe.json", filenames)

    def test_cli_ui_examples_show_text(self) -> None:
        result = subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "ui-examples",
                "show",
                "dashboard_default_safe.json",
                "--format",
                "text",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("screen_id: DASHBOARD", result.stdout)
        self.assertIn("mode: default", result.stdout)
        self.assertIn("title:", result.stdout)

    def test_stems_review_example_uses_canonical_stem_identity_fields(self) -> None:
        example = load_ui_screen_example(
            self._repo_root() / "examples" / "ui_screens" / "stems_review.json"
        )

        self.assertIsInstance(example, dict)
        if not isinstance(example, dict):
            return

        bundle = example.get("bundle")
        self.assertIsInstance(bundle, dict)
        if not isinstance(bundle, dict):
            return

        stems_summary = bundle.get("stems_summary")
        self.assertIsInstance(stems_summary, dict)
        if not isinstance(stems_summary, dict):
            return

        assignments_preview = stems_summary.get("assignments_preview")
        self.assertIsInstance(assignments_preview, list)
        if not isinstance(assignments_preview, list):
            return

        for row in assignments_preview:
            self.assertIsInstance(row, dict)
            if not isinstance(row, dict):
                continue
            self.assertNotIn("file_id", row)
            self.assertIsInstance(row.get("stem_id"), str)
            self.assertTrue(str(row.get("stem_id", "")).strip())
            source_file_id = row.get("source_file_id")
            if source_file_id is not None:
                self.assertIsInstance(source_file_id, str)
                self.assertRegex(str(source_file_id), r"^SOURCEFILE\.[0-9a-f]{10}$")


if __name__ == "__main__":
    unittest.main()
