"""Tests for ``mmo project bundle``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_bundle" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_tiny_wav(path: Path, *, channels: int = 1, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 8 * channels)


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((_SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _run_project_bundle(
    project_dir: Path,
    out_path: Path,
    *,
    force: bool = False,
) -> tuple[int, str, str]:
    args = [
        "project", "bundle", str(project_dir),
        "--out", str(out_path),
    ]
    if force:
        args.append("--force")
    return _run_main(args)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _init_full_render_project(base: Path) -> Path:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")
    project_dir = base / "project"

    exit_code, _, stderr = _run_main([
        "project", "init",
        "--stems-root", str(stems_root),
        "--out-dir", str(project_dir),
    ])
    assert exit_code == 0, f"project init failed: {stderr}"

    report_path = project_dir / "report.json"
    exit_code, _, stderr = _run_main([
        "scan", str(stems_root),
        "--out", str(report_path),
    ])
    assert exit_code == 0, f"scan failed: {stderr}"

    exit_code, _, stderr = _run_main([
        "project", "render-init", str(project_dir),
        "--target-layout", "LAYOUT.2_0",
    ])
    assert exit_code == 0, f"project render-init failed: {stderr}"

    exit_code, _, stderr = _run_main([
        "project", "render-run", str(project_dir),
        "--event-log",
    ])
    assert exit_code == 0, f"project render-run failed: {stderr}"
    return project_dir


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestProjectBundle(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_full_render_project(_SANDBOX / "full")
        cls.validator = _schema_validator("ui_bundle.schema.json")

    def test_happy_path_writes_schema_valid_ui_bundle(self) -> None:
        out_path = _SANDBOX / "full" / "ui_bundle_happy.json"
        exit_code, stdout, stderr = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertTrue(out_path.is_file())

        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        self.validator.validate(bundle)

        summary = json.loads(stdout)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["project_dir"], self.project_dir.resolve().as_posix())
        self.assertEqual(summary["out"], out_path.resolve().as_posix())
        self.assertNotIn("\\", stdout)

    def test_deterministic_bytes_identical_across_runs(self) -> None:
        out_path = _SANDBOX / "full" / "ui_bundle_determinism.json"
        exit_code_a, _, stderr_a = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_code_a, 0, msg=stderr_a)
        bytes_a = out_path.read_bytes()

        exit_code_b, _, stderr_b = _run_project_bundle(
            self.project_dir, out_path, force=True,
        )
        self.assertEqual(exit_code_b, 0, msg=stderr_b)
        bytes_b = out_path.read_bytes()

        self.assertEqual(bytes_a, bytes_b)

    def test_includes_render_and_event_log_pointers_when_present(self) -> None:
        out_path = _SANDBOX / "full" / "ui_bundle_render_ptrs.json"
        exit_code, _, stderr = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_code, 0, msg=stderr)

        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        render = bundle.get("render")
        self.assertIsInstance(render, dict)
        if not isinstance(render, dict):
            return

        for key, rel in (
            ("render_request", "renders/render_request.json"),
            ("render_plan", "renders/render_plan.json"),
            ("render_report", "renders/render_report.json"),
        ):
            pointer = render.get(key)
            self.assertIsInstance(pointer, dict)
            if not isinstance(pointer, dict):
                continue
            self.assertTrue(pointer["exists"])
            self.assertTrue(pointer["path"].endswith(rel))
            self.assertNotIn("\\", pointer["path"])

        event_log_pointer = bundle.get("event_log")
        self.assertIsInstance(event_log_pointer, dict)
        if isinstance(event_log_pointer, dict):
            self.assertTrue(event_log_pointer["exists"])
            self.assertTrue(event_log_pointer["path"].endswith("renders/event_log.jsonl"))
            self.assertNotIn("\\", event_log_pointer["path"])

    def test_overwrite_refusal_and_allow(self) -> None:
        out_path = _SANDBOX / "full" / "ui_bundle_overwrite.json"
        exit_first, _, stderr_first = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_first, 0, msg=stderr_first)
        original_bytes = out_path.read_bytes()

        exit_refused, _, stderr_refused = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_refused, 1)
        self.assertIn("File exists", stderr_refused)
        self.assertIn("--force", stderr_refused)
        self.assertEqual(original_bytes, out_path.read_bytes())

        exit_forced, _, stderr_forced = _run_project_bundle(
            self.project_dir, out_path, force=True,
        )
        self.assertEqual(exit_forced, 0, msg=stderr_forced)
        self.assertEqual(original_bytes, out_path.read_bytes())

    def test_no_scanning_behavior(self) -> None:
        # Add non-allowlisted files that must not be discovered.
        extra_a = self.project_dir / "renders" / "ignored.non_allowlisted.json"
        extra_b = self.project_dir / "logs" / "event_log.jsonl"
        extra_a.parent.mkdir(parents=True, exist_ok=True)
        extra_b.parent.mkdir(parents=True, exist_ok=True)
        extra_a.write_text('{"ignored": true}\n', encoding="utf-8")
        extra_b.write_text('{"ignored": true}\n', encoding="utf-8")

        project_root = self.project_dir.resolve()
        project_glob_calls: list[tuple[str, str]] = []
        project_rglob_calls: list[tuple[str, str]] = []
        original_glob = Path.glob
        original_rglob = Path.rglob

        def _guarded_glob(path_obj: Path, pattern: str):  # type: ignore[no-untyped-def]
            resolved = path_obj.resolve()
            if resolved == project_root or _is_within(resolved, project_root):
                project_glob_calls.append((resolved.as_posix(), pattern))
            return original_glob(path_obj, pattern)

        def _guarded_rglob(path_obj: Path, pattern: str):  # type: ignore[no-untyped-def]
            resolved = path_obj.resolve()
            if resolved == project_root or _is_within(resolved, project_root):
                project_rglob_calls.append((resolved.as_posix(), pattern))
            return original_rglob(path_obj, pattern)

        out_path = _SANDBOX / "full" / "ui_bundle_no_scan.json"
        with patch("pathlib.Path.glob", new=_guarded_glob), patch(
            "pathlib.Path.rglob", new=_guarded_rglob,
        ):
            exit_code, _, stderr = _run_project_bundle(self.project_dir, out_path)
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(project_glob_calls, [])
        self.assertEqual(project_rglob_calls, [])

        bundle_text = out_path.read_text(encoding="utf-8")
        self.assertNotIn("ignored.non_allowlisted.json", bundle_text)
        self.assertNotIn("logs/event_log.jsonl", bundle_text)


if __name__ == "__main__":
    unittest.main()
