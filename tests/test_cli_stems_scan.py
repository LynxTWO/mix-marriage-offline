import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.cli import main


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


class TestCliStemsScan(unittest.TestCase):
    def test_scan_repeat_runs_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_path = temp_path / "stems_index.json"

            _write_tiny_wav(root / "stems" / "01_Kick.wav")
            _write_tiny_wav(root / "stems" / "02_Snare.wav")

            first_stdout = io.StringIO()
            with contextlib.redirect_stdout(first_stdout):
                first_exit = main(
                    [
                        "stems",
                        "scan",
                        "--root",
                        str(root),
                        "--out",
                        str(out_path),
                        "--format",
                        "json",
                    ]
                )
            first_file_text = out_path.read_text(encoding="utf-8")

            second_stdout = io.StringIO()
            with contextlib.redirect_stdout(second_stdout):
                second_exit = main(
                    [
                        "stems",
                        "scan",
                        "--root",
                        str(root),
                        "--out",
                        str(out_path),
                        "--format",
                        "json",
                    ]
                )
            second_file_text = out_path.read_text(encoding="utf-8")

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_file_text, second_file_text)

            first_stdout_payload = json.loads(first_stdout.getvalue())
            second_stdout_payload = json.loads(second_stdout.getvalue())
            self.assertEqual(first_stdout_payload, second_stdout_payload)
            self.assertEqual(json.loads(first_file_text), first_stdout_payload)

    def test_sets_text_output_lists_sorted_candidates_for_ambiguous_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "tracks" / "a.wav")
            _write_tiny_wav(root / "tracks" / "b.wav")
            _write_tiny_wav(root / "stems" / "lead.wav")
            _write_tiny_wav(root / "alpha" / "kick.wav")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "stems",
                        "sets",
                        "--root",
                        str(root),
                        "--format",
                        "text",
                    ]
                )

            self.assertEqual(exit_code, 0)
            text = stdout.getvalue()
            self.assertIn("found 3 sets", text)
            listed = [line for line in text.splitlines() if line.startswith("- ")]
            self.assertEqual(len(listed), 3)
            self.assertTrue(listed[0].startswith("- tracks"))
            self.assertTrue(listed[1].startswith("- stems"))
            self.assertTrue(listed[2].startswith("- alpha"))


if __name__ == "__main__":
    unittest.main()
