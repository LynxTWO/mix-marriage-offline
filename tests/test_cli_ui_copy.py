import json
import os
import subprocess
import sys
import unittest


class TestCliUiCopy(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def test_ui_copy_list_json_is_sorted_and_deterministic(self) -> None:
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "ui-copy",
            "list",
            "--locale",
            "en-US",
            "--format",
            "json",
        ]
        first = subprocess.run(command, check=False, capture_output=True, text=True)
        second = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)

        payload = json.loads(first.stdout)
        self.assertEqual(payload.get("locale"), "en-US")
        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        if not isinstance(entries, list):
            return
        copy_ids = [
            item.get("copy_id")
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("copy_id"), str)
        ]
        self.assertEqual(copy_ids, sorted(copy_ids))
        self.assertIn("COPY.NAV.DASHBOARD", copy_ids)

    def test_ui_copy_show_text_is_deterministic(self) -> None:
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "ui-copy",
            "show",
            "COPY.NAV.DASHBOARD",
            "--locale",
            "en-US",
            "--format",
            "text",
        ]
        first = subprocess.run(command, check=False, capture_output=True, text=True)
        second = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("COPY.NAV.DASHBOARD", first.stdout)
        self.assertIn("Dashboard", first.stdout)
        self.assertIn("Locale: en-US", first.stdout)

    def test_ui_copy_show_json_missing_key_uses_placeholder(self) -> None:
        result = subprocess.run(
            [
                self._python_cmd(),
                "-m",
                "mmo",
                "ui-copy",
                "show",
                "COPY.MISSING.EXAMPLE",
                "--locale",
                "en-US",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("copy_id"), "COPY.MISSING.EXAMPLE")
        self.assertEqual(payload.get("text"), "COPY.MISSING.EXAMPLE")
        self.assertEqual(payload.get("tooltip"), "Missing copy entry")


if __name__ == "__main__":
    unittest.main()
