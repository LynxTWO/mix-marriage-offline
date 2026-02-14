"""Post-refactor regression smoke test.

Verifies that after moving handlers to cli_commands/, the following
commands still complete successfully with identical behavior:
  - project init
  - project refresh
  - stems audition (with --overwrite)
  - bundle (pointer check)

Also verifies backward-compatible re-exports from mmo.cli.
"""
import contextlib
import io
import json
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_refactor_smoke"


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


def _make_stems_root(base: Path) -> Path:
    root = base / "stems_root"
    _write_tiny_wav(root / "stems" / "kick.wav")
    _write_tiny_wav(root / "stems" / "snare.wav")
    return root


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestCliRefactorSmoke(unittest.TestCase):
    """Regression smoke tests for the cli_commands refactor."""

    def test_reexport_parse_output_formats_csv(self) -> None:
        """_parse_output_formats_csv must remain importable from mmo.cli."""
        from mmo.cli import _parse_output_formats_csv  # noqa: F811
        result = _parse_output_formats_csv("wav,flac")
        self.assertIn("wav", result)
        self.assertIn("flac", result)

    def test_reexport_run_ui_workflow_importable(self) -> None:
        """_run_ui_workflow must remain importable from mmo.cli."""
        from mmo.cli import _run_ui_workflow  # noqa: F811
        self.assertTrue(callable(_run_ui_workflow))

    def test_project_init(self) -> None:
        """project init produces exit 0 and expected artifacts."""
        base = _SANDBOX / "init"
        stems = _make_stems_root(base)
        out_dir = base / "project"

        exit_code, stdout, stderr = _run_main([
            "project", "init",
            "--stems-root", str(stems),
            "--out-dir", str(out_dir),
        ])
        self.assertEqual(exit_code, 0, msg=f"stderr: {stderr}")
        self.assertTrue(
            (out_dir / "stems" / "stems_map.json").exists(),
            "stems_map.json should be created",
        )
        parsed = json.loads(stdout)
        self.assertTrue(parsed.get("ok"), msg=f"stdout: {stdout}")

    def test_project_refresh(self) -> None:
        """project refresh succeeds after init."""
        base = _SANDBOX / "refresh"
        stems = _make_stems_root(base)
        out_dir = base / "project"

        # init first
        code, _, err = _run_main([
            "project", "init",
            "--stems-root", str(stems),
            "--out-dir", str(out_dir),
        ])
        self.assertEqual(code, 0, msg=f"init failed: {err}")

        # then refresh
        exit_code, stdout, stderr = _run_main([
            "project", "refresh",
            "--project-dir", str(out_dir),
            "--stems-root", str(stems),
        ])
        self.assertEqual(exit_code, 0, msg=f"stderr: {stderr}")
        parsed = json.loads(stdout)
        self.assertTrue(parsed.get("ok"), msg=f"stdout: {stdout}")

    def test_stems_audition(self) -> None:
        """stems audition produces exit 0 after init."""
        base = _SANDBOX / "audition"
        stems = _make_stems_root(base)
        out_dir = base / "project"

        # init first
        code, _, err = _run_main([
            "project", "init",
            "--stems-root", str(stems),
            "--out-dir", str(out_dir),
        ])
        self.assertEqual(code, 0, msg=f"init failed: {err}")

        map_path = out_dir / "stems" / "stems_map.json"
        exit_code, stdout, stderr = _run_main([
            "stems", "audition",
            "--stems-map", str(map_path),
            "--stems-dir", str(stems),
            "--out-dir", str(out_dir),
            "--segment", "1.0",
            "--overwrite",
        ])
        self.assertEqual(exit_code, 0, msg=f"stderr: {stderr}")

    def test_bundle_pointers(self) -> None:
        """bundle produces valid JSON with a report key."""
        base = _SANDBOX / "bundle"
        report_payload = {
            "schema_version": "0.1.0",
            "report_id": "REPORT.SMOKE",
            "project_id": "PROJECT.SMOKE",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [],
        }
        report_path = base / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        bundle_path = base / "bundle.json"

        exit_code, stdout, stderr = _run_main([
            "bundle",
            "--report", str(report_path),
            "--out", str(bundle_path),
        ])
        self.assertEqual(exit_code, 0, msg=f"stderr: {stderr}")
        self.assertTrue(bundle_path.exists(), "bundle.json should be created")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        self.assertIn("report", bundle)


if __name__ == "__main__":
    unittest.main()
