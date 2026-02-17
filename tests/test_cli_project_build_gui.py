"""Tests for ``mmo project build-gui``."""

import contextlib
import io
import json
import os
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_build_gui" / str(os.getpid())
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


def _init_project(base: Path) -> tuple[Path, Path]:
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

    exit_code, _, stderr = _run_main([
        "project", "render-init", str(project_dir),
        "--target-layout", "LAYOUT.2_0",
    ])
    assert exit_code == 0, f"project render-init failed: {stderr}"

    return project_dir, stems_root


def _run_build_gui(
    project_dir: Path,
    *,
    pack_out: Path,
    scan: bool,
    scan_stems: Path | None = None,
    scan_out: Path | None = None,
    force: bool = False,
    event_log: bool = False,
    event_log_force: bool = False,
    include_plugins: bool = False,
    plugins_dir: Path | None = None,
) -> tuple[int, str, str]:
    args = [
        "project", "build-gui", str(project_dir),
        "--pack-out", str(pack_out),
    ]
    if scan:
        args.append("--scan")
        args.extend(["--scan-stems", str(scan_stems if scan_stems is not None else project_dir)])
        args.extend(["--scan-out", str(scan_out if scan_out is not None else (project_dir / "report.json"))])
    if force:
        args.append("--force")
    if event_log:
        args.append("--event-log")
    if event_log_force:
        args.append("--event-log-force")
    if include_plugins:
        args.append("--include-plugins")
        args.extend(
            [
                "--plugins",
                str(plugins_dir if plugins_dir is not None else (_REPO_ROOT / "plugins")),
            ]
        )
    return _run_main(args)


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestProjectBuildGuiDeterminism(unittest.TestCase):
    def test_determinism_two_runs_identical(self) -> None:
        project_dir, stems_root = _init_project(_SANDBOX / "determinism")
        pack_out = project_dir / "project_gui.zip"
        scan_out = project_dir / "report.json"
        event_log_path = project_dir / "renders" / "event_log.jsonl"
        plan_path = project_dir / "renders" / "render_plan.json"
        render_report_path = project_dir / "renders" / "render_report.json"
        bundle_path = project_dir / "ui_bundle.json"
        validation_path = project_dir / "validation.json"

        exit_a, stdout_a, stderr_a = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_a, 0, msg=stderr_a)

        bytes_a = {
            "report": scan_out.read_bytes(),
            "plan": plan_path.read_bytes(),
            "render_report": render_report_path.read_bytes(),
            "event_log": event_log_path.read_bytes(),
            "ui_bundle": bundle_path.read_bytes(),
            "validation": validation_path.read_bytes(),
            "pack": pack_out.read_bytes(),
        }

        exit_b, stdout_b, stderr_b = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_b, 0, msg=stderr_b)
        self.assertEqual(stdout_a, stdout_b)

        bytes_b = {
            "report": scan_out.read_bytes(),
            "plan": plan_path.read_bytes(),
            "render_report": render_report_path.read_bytes(),
            "event_log": event_log_path.read_bytes(),
            "ui_bundle": bundle_path.read_bytes(),
            "validation": validation_path.read_bytes(),
            "pack": pack_out.read_bytes(),
        }
        self.assertEqual(bytes_a, bytes_b)

        summary = json.loads(stdout_a)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["project_dir"], project_dir.resolve().as_posix())
        self.assertNotIn("\\", stdout_a)


class TestProjectBuildGuiOverwriteGuards(unittest.TestCase):
    def test_refuses_overwrite_without_force(self) -> None:
        project_dir, stems_root = _init_project(_SANDBOX / "overwrite_guard")
        pack_out = project_dir / "project_gui.zip"
        scan_out = project_dir / "report.json"

        exit_first, _, stderr_first = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_first, 0, msg=stderr_first)
        pack_bytes_first = pack_out.read_bytes()

        exit_refused, _, stderr_refused = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            event_log=True,
        )
        self.assertEqual(exit_refused, 1)
        self.assertIn("File exists", stderr_refused)
        self.assertIn("--force", stderr_refused)
        self.assertEqual(pack_bytes_first, pack_out.read_bytes())

    def test_event_log_overwrite_requires_event_log_force(self) -> None:
        project_dir, stems_root = _init_project(_SANDBOX / "event_log_force")
        pack_out = project_dir / "project_gui.zip"
        scan_out = project_dir / "report.json"
        event_log_path = project_dir / "renders" / "event_log.jsonl"

        exit_first, _, stderr_first = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_first, 0, msg=stderr_first)
        event_log_bytes_first = event_log_path.read_bytes()

        exit_refused, _, stderr_refused = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
        )
        self.assertEqual(exit_refused, 1)
        self.assertIn("--event-log-force", stderr_refused)
        self.assertEqual(event_log_bytes_first, event_log_path.read_bytes())


class TestProjectBuildGuiArtifacts(unittest.TestCase):
    def test_artifacts_exist_and_are_schema_valid(self) -> None:
        project_dir, stems_root = _init_project(_SANDBOX / "artifacts")
        pack_out = project_dir / "project_gui.zip"
        scan_out = project_dir / "report.json"

        exit_code, stdout, stderr = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
        )
        self.assertEqual(exit_code, 0, msg=stderr)

        plan_path = project_dir / "renders" / "render_plan.json"
        render_report_path = project_dir / "renders" / "render_report.json"
        event_log_path = project_dir / "renders" / "event_log.jsonl"
        bundle_path = project_dir / "ui_bundle.json"
        validation_path = project_dir / "validation.json"

        self.assertTrue(scan_out.is_file())
        self.assertTrue(plan_path.is_file())
        self.assertTrue(render_report_path.is_file())
        self.assertTrue(event_log_path.is_file())
        self.assertTrue(bundle_path.is_file())
        self.assertTrue(validation_path.is_file())
        self.assertTrue(pack_out.is_file())

        _schema_validator("report.schema.json").validate(
            json.loads(scan_out.read_text(encoding="utf-8")),
        )
        _schema_validator("render_plan.schema.json").validate(
            json.loads(plan_path.read_text(encoding="utf-8")),
        )
        _schema_validator("render_report.schema.json").validate(
            json.loads(render_report_path.read_text(encoding="utf-8")),
        )
        _schema_validator("ui_bundle.schema.json").validate(
            json.loads(bundle_path.read_text(encoding="utf-8")),
        )

        validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertTrue(validation_payload.get("ok"))
        self.assertIsInstance(validation_payload.get("checks"), list)
        self.assertIsInstance(validation_payload.get("summary"), dict)

        summary = json.loads(stdout)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["pack_out"], pack_out.resolve().as_posix())
        self.assertEqual(summary["project_dir"], project_dir.resolve().as_posix())

    def test_build_gui_include_plugins_flag_embeds_plugins_block(self) -> None:
        project_dir, stems_root = _init_project(_SANDBOX / "plugins_block")
        pack_out = project_dir / "project_gui.zip"
        scan_out = project_dir / "report.json"

        exit_code, _, stderr = _run_build_gui(
            project_dir,
            pack_out=pack_out,
            scan=True,
            scan_stems=stems_root,
            scan_out=scan_out,
            force=True,
            event_log=True,
            event_log_force=True,
            include_plugins=True,
            plugins_dir=_REPO_ROOT / "plugins",
        )
        self.assertEqual(exit_code, 0, msg=stderr)

        bundle_path = project_dir / "ui_bundle.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        plugins_payload = bundle.get("plugins")
        self.assertIsInstance(plugins_payload, dict)
        if isinstance(plugins_payload, dict):
            self.assertEqual(
                plugins_payload.get("plugins_dir"),
                (_REPO_ROOT / "plugins").resolve().as_posix(),
            )


if __name__ == "__main__":
    unittest.main()
