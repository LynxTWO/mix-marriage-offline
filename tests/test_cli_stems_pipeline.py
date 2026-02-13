"""Tests for mmo stems pipeline — one-command scan + classify + overrides."""

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


class TestCliStemsPipeline(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_pipeline_produces_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare.wav")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)

            self.assertTrue((out_dir / "stems_index.json").exists())
            self.assertTrue((out_dir / "stems_map.json").exists())
            self.assertTrue((out_dir / "stems_overrides.yaml").exists())

            index_payload = json.loads(
                (out_dir / "stems_index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(index_payload.get("version"), "0.1.0")
            files = index_payload.get("files")
            self.assertIsInstance(files, list)
            self.assertEqual(len(files), 2)

            map_payload = json.loads(
                (out_dir / "stems_map.json").read_text(encoding="utf-8")
            )
            self.assertEqual(map_payload.get("version"), "0.1.0")
            assignments = map_payload.get("assignments")
            self.assertIsInstance(assignments, list)
            self.assertEqual(len(assignments), 2)

            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["assignment_count"], 2)
            self.assertTrue(result["overrides_written"])
            self.assertFalse(result["overrides_skipped"])

    def test_pipeline_output_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out1 = temp_path / "out1"
            out2 = temp_path / "out2"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare.wav")

            args1 = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out1),
            ]
            args2 = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out2),
            ]
            exit1, stdout1, _ = self._run_main(args1)
            exit2, stdout2, _ = self._run_main(args2)

            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            index1 = (out1 / "stems_index.json").read_text(encoding="utf-8")
            index2 = (out2 / "stems_index.json").read_text(encoding="utf-8")
            self.assertEqual(index1, index2)

            map1 = (out1 / "stems_map.json").read_text(encoding="utf-8")
            map2 = (out2 / "stems_map.json").read_text(encoding="utf-8")
            self.assertEqual(map1, map2)

    def test_pipeline_does_not_overwrite_existing_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            _write_tiny_wav(root / "stems" / "kick.wav")

            out_dir.mkdir(parents=True, exist_ok=True)
            overrides_path = out_dir / "stems_overrides.yaml"
            sentinel = "# user-edited overrides\nversion: \"0.1.0\"\noverrides: []\n"
            overrides_path.write_text(sentinel, encoding="utf-8")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertFalse(result["overrides_written"])
            self.assertTrue(result["overrides_skipped"])
            self.assertEqual(
                overrides_path.read_text(encoding="utf-8"),
                sentinel,
            )

    def test_pipeline_force_overwrites_existing_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            _write_tiny_wav(root / "stems" / "kick.wav")

            out_dir.mkdir(parents=True, exist_ok=True)
            overrides_path = out_dir / "stems_overrides.yaml"
            sentinel = "# user-edited overrides\nversion: \"0.1.0\"\noverrides: []\n"
            overrides_path.write_text(sentinel, encoding="utf-8")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
                "--force",
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertTrue(result["overrides_written"])
            self.assertFalse(result["overrides_skipped"])
            self.assertNotEqual(
                overrides_path.read_text(encoding="utf-8"),
                sentinel,
            )

    def test_pipeline_stable_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            _write_tiny_wav(root / "stems" / "kick.wav")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertIn("stems_index.json", result["stems_index"])
            self.assertIn("stems_map.json", result["stems_map"])
            self.assertIn("stems_overrides.yaml", result["stems_overrides"])

    def test_pipeline_bundle_writes_pointer_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            bundle_path = temp_path / "bundle" / "ui_bundle.json"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare.wav")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
                "--bundle", str(bundle_path),
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertEqual(result["bundle"], str(bundle_path))
            self.assertTrue(bundle_path.exists())

            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            self.assertIn("stems_index_path", bundle)
            self.assertIn("stems_map_path", bundle)
            self.assertIn("stems_summary", bundle)
            summary = bundle["stems_summary"]
            self.assertIn("counts_by_bus_group", summary)
            self.assertIn("unknown_files", summary)

    def test_pipeline_json_output_keys_are_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "stems_root"
            out_dir = temp_path / "out"
            _write_tiny_wav(root / "stems" / "kick.wav")

            args = [
                "stems", "pipeline",
                "--root", str(root),
                "--out-dir", str(out_dir),
            ]
            exit_code, stdout, stderr = self._run_main(args)

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertEqual(list(result.keys()), sorted(result.keys()))


if __name__ == "__main__":
    unittest.main()
