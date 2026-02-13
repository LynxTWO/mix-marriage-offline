"""CLI integration tests for mmo stems draft."""

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


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _build_stems_map_via_pipeline(temp_path: Path) -> Path:
    """Run the stems pipeline to produce a real stems_map.json for draft tests."""
    root = temp_path / "stems_root"
    out_dir = temp_path / "pipeline_out"
    _write_tiny_wav(root / "stems" / "kick.wav")
    _write_tiny_wav(root / "stems" / "snare.wav")

    exit_code, _, stderr = _run_main([
        "stems", "pipeline",
        "--root", str(root),
        "--out-dir", str(out_dir),
    ])
    if exit_code != 0:
        raise RuntimeError(f"Pipeline failed: {stderr}")
    return out_dir / "stems_map.json"


class TestCliStemsDraft(unittest.TestCase):
    def test_draft_produces_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            draft_out = temp_path / "draft_out"

            exit_code, stdout, stderr = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
            ])

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue((draft_out / "scene.draft.json").exists())
            self.assertTrue((draft_out / "routing_plan.draft.json").exists())

            scene = json.loads(
                (draft_out / "scene.draft.json").read_text(encoding="utf-8")
            )
            self.assertEqual(scene["schema_version"], "0.1.0")
            self.assertEqual(scene["source"]["created_from"], "draft")

            routing = json.loads(
                (draft_out / "routing_plan.draft.json").read_text(encoding="utf-8")
            )
            self.assertEqual(routing["schema_version"], "0.1.0")

    def test_draft_refuses_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            draft_out = temp_path / "draft_out"

            # First run — should succeed.
            exit_code1, _, stderr1 = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
            ])
            self.assertEqual(exit_code1, 0, msg=stderr1)

            # Second run — should fail because files exist.
            exit_code2, _, stderr2 = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
            ])
            self.assertNotEqual(exit_code2, 0)
            self.assertIn("already exists", stderr2)

    def test_draft_overwrite_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            draft_out = temp_path / "draft_out"

            _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
            ])

            exit_code, _, stderr = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
                "--overwrite",
            ])
            self.assertEqual(exit_code, 0, msg=stderr)

    def test_draft_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            draft_out = temp_path / "draft_out"

            exit_code, stdout, stderr = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
                "--format", "json",
            ])

            self.assertEqual(exit_code, 0, msg=stderr)
            result = json.loads(stdout)
            self.assertTrue(result["ok"])
            self.assertTrue(result["preview_only"])
            self.assertIsInstance(result["stems_count"], int)
            self.assertGreater(result["stems_count"], 0)
            self.assertIn("scene_out", result)
            self.assertIn("routing_out", result)

    def test_draft_text_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            draft_out = temp_path / "draft_out"

            exit_code, stdout, stderr = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(draft_out),
            ])

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertIn("preview", stdout.lower())
            self.assertIn("scene", stdout.lower())

    def test_draft_deterministic_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _build_stems_map_via_pipeline(temp_path)
            out1 = temp_path / "draft_out1"
            out2 = temp_path / "draft_out2"

            exit1, _, stderr1 = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(out1),
            ])
            exit2, _, stderr2 = _run_main([
                "stems", "draft",
                "--stems-map", str(map_path),
                "--out-dir", str(out2),
            ])

            self.assertEqual(exit1, 0, msg=stderr1)
            self.assertEqual(exit2, 0, msg=stderr2)

            scene1 = (out1 / "scene.draft.json").read_text(encoding="utf-8")
            scene2 = (out2 / "scene.draft.json").read_text(encoding="utf-8")
            self.assertEqual(scene1, scene2)

            routing1 = (out1 / "routing_plan.draft.json").read_text(encoding="utf-8")
            routing2 = (out2 / "routing_plan.draft.json").read_text(encoding="utf-8")
            self.assertEqual(routing1, routing2)


if __name__ == "__main__":
    unittest.main()
