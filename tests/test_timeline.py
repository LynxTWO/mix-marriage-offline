import json
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main
from mmo.core.timeline import load_timeline


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestTimeline(unittest.TestCase):
    def test_valid_timeline_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timeline_path = Path(temp_dir) / "timeline.json"
            payload = {
                "schema_version": "0.1.0",
                "sections": [
                    {
                        "id": "SEC.001",
                        "label": "Intro",
                        "start_s": 0.0,
                        "end_s": 12.0,
                    },
                    {
                        "id": "SEC.002",
                        "label": "Verse 1",
                        "start_s": 12.0,
                        "end_s": 32.0,
                    },
                ],
            }
            _write_json(timeline_path, payload)

            normalized = load_timeline(timeline_path)
            self.assertEqual(normalized, payload)

    def test_overlap_fails_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timeline_path = Path(temp_dir) / "timeline.json"
            payload = {
                "schema_version": "0.1.0",
                "sections": [
                    {
                        "id": "SEC.001",
                        "label": "Verse 1",
                        "start_s": 10.0,
                        "end_s": 20.0,
                    },
                    {
                        "id": "SEC.002",
                        "label": "Chorus 1",
                        "start_s": 19.5,
                        "end_s": 30.0,
                    },
                ],
            }
            _write_json(timeline_path, payload)

            with self.assertRaises(ValueError) as raised:
                load_timeline(timeline_path)
            self.assertIn("overlap", str(raised.exception).lower())

    def test_unsorted_input_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timeline_path = Path(temp_dir) / "timeline.json"
            payload = {
                "schema_version": "0.1.0",
                "sections": [
                    {
                        "id": "SEC.002",
                        "label": "Verse 1",
                        "start_s": 12.0,
                        "end_s": 32.0,
                    },
                    {
                        "id": "SEC.001",
                        "label": "Intro",
                        "start_s": 0.0,
                        "end_s": 12.0,
                    },
                ],
            }
            _write_json(timeline_path, payload)

            normalized = load_timeline(timeline_path)
            self.assertEqual(
                [section["id"] for section in normalized["sections"]],
                ["SEC.001", "SEC.002"],
            )
            self.assertEqual(
                [section["start_s"] for section in normalized["sections"]],
                [0.0, 12.0],
            )

    def test_cli_timeline_validate_and_show(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timeline_path = Path(temp_dir) / "timeline.json"
            payload = {
                "schema_version": "0.1.0",
                "sections": [
                    {
                        "id": "SEC.001",
                        "label": "Verse 1",
                        "start_s": 0.0,
                        "end_s": 16.0,
                    }
                ],
            }
            _write_json(timeline_path, payload)

            validate_stdout = StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(
                    [
                        "timeline",
                        "validate",
                        "--timeline",
                        str(timeline_path),
                    ]
                )
            self.assertEqual(validate_exit, 0)
            self.assertIn("Timeline is valid.", validate_stdout.getvalue())

            show_stdout = StringIO()
            with redirect_stdout(show_stdout):
                show_exit = main(
                    [
                        "timeline",
                        "show",
                        "--timeline",
                        str(timeline_path),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(show_exit, 0)
            shown = json.loads(show_stdout.getvalue())
            self.assertEqual(shown, payload)


if __name__ == "__main__":
    unittest.main()
