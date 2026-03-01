"""Tests for ``mmo project render-init`` CLI command."""

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
_SCHEMA_PATH = _SCHEMAS_DIR / "render_request.schema.json"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_project_render_init" / str(os.getpid())
)


# -- helpers -----------------------------------------------------------------

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


def _init_project(base: Path) -> Path:
    """Create a valid project scaffold and return the project_dir."""
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
    return project_dir


def _schema_validator() -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(_SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _extract_known_ids(stderr_text: str, *, marker: str) -> list[str]:
    marker_idx = stderr_text.find(marker)
    if marker_idx < 0:
        return []
    suffix = stderr_text[marker_idx + len(marker):]
    first_line = suffix.splitlines()[0]
    return [
        item.strip()
        for item in first_line.split(",")
        if isinstance(item, str) and item.strip()
    ]


# -- module setup / teardown -------------------------------------------------

def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


# -- tests -------------------------------------------------------------------

class TestRenderInitHappyPath(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "happy")
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(cls.project_dir),
            "--target-layout", "LAYOUT.5_1",
        ])
        assert exit_code == 0, f"project render-init failed: {stderr}"

    def test_creates_render_request_and_exits_zero(self) -> None:
        project_dir = _init_project(_SANDBOX / "happy_create_only")
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.5_1",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        rr_path = project_dir / "renders" / "render_request.json"
        self.assertTrue(rr_path.is_file())

    def test_render_request_is_schema_valid(self) -> None:
        rr_path = self.project_dir / "renders" / "render_request.json"
        payload = json.loads(rr_path.read_text(encoding="utf-8"))
        validator = _schema_validator()
        validator.validate(payload)

    def test_scene_path_is_drafts_scene(self) -> None:
        rr_path = self.project_dir / "renders" / "render_request.json"
        payload = json.loads(rr_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["scene_path"], "drafts/scene.draft.json")

    def test_routing_plan_path_present_when_file_exists(self) -> None:
        rr_path = self.project_dir / "renders" / "render_request.json"
        payload = json.loads(rr_path.read_text(encoding="utf-8"))
        # project init creates routing_plan.draft.json, so it should be present.
        self.assertEqual(
            payload["routing_plan_path"],
            "drafts/routing_plan.draft.json",
        )

    def test_default_options(self) -> None:
        rr_path = self.project_dir / "renders" / "render_request.json"
        payload = json.loads(rr_path.read_text(encoding="utf-8"))
        opts = payload["options"]
        self.assertTrue(opts["dry_run"])
        self.assertEqual(
            opts["downmix_policy_id"],
            "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        )
        self.assertEqual(opts["gates_policy_id"], "POLICY.GATES.CORE_V0")
        self.assertEqual(opts["loudness_profile_id"], "LOUD.EBU_R128_PROGRAM")
        self.assertEqual(
            opts["lfe_derivation_profile_id"],
            "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
        )
        self.assertEqual(opts["lfe_mode"], "mono")

    def test_stdout_summary_is_valid_json(self) -> None:
        # Re-run with --force since file already exists from earlier test.
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--force",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["written"], ["renders/render_request.json"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["target_layout_id"], "LAYOUT.5_1")


class TestRenderInitDeterminism(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = _SANDBOX / "determinism"
        cls.project_dir = _init_project(cls.base)

    def test_deterministic_bytes_across_runs(self) -> None:
        # First run.
        exit_code_a, stdout_a, stderr_a = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.5_1",
        ])
        self.assertEqual(exit_code_a, 0, msg=stderr_a)
        rr_path = self.project_dir / "renders" / "render_request.json"
        bytes_a = rr_path.read_bytes()

        # Second run (--force to overwrite).
        exit_code_b, stdout_b, stderr_b = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--force",
        ])
        self.assertEqual(exit_code_b, 0, msg=stderr_b)
        bytes_b = rr_path.read_bytes()

        self.assertEqual(
            bytes_a, bytes_b,
            "Two runs with identical inputs must produce identical bytes.",
        )

    def test_stdout_identical_across_runs(self) -> None:
        exit_code_a, stdout_a, _ = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--force",
        ])
        exit_code_b, stdout_b, _ = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--force",
        ])
        self.assertEqual(exit_code_a, 0)
        self.assertEqual(exit_code_b, 0)
        self.assertEqual(stdout_a, stdout_b)

    def test_multi_target_deterministic_bytes_across_runs(self) -> None:
        exit_code_a, _, stderr_a = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layouts", "LAYOUT.5_1,LAYOUT.2_0",
            "--force",
        ])
        self.assertEqual(exit_code_a, 0, msg=stderr_a)
        rr_path = self.project_dir / "renders" / "render_request.json"
        payload_a = json.loads(rr_path.read_text(encoding="utf-8"))
        bytes_a = rr_path.read_bytes()

        exit_code_b, _, stderr_b = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layouts", "LAYOUT.2_0,LAYOUT.5_1",
            "--force",
        ])
        self.assertEqual(exit_code_b, 0, msg=stderr_b)
        payload_b = json.loads(rr_path.read_text(encoding="utf-8"))
        bytes_b = rr_path.read_bytes()

        self.assertNotIn("target_layout_id", payload_a)
        self.assertNotIn("target_layout_id", payload_b)
        self.assertEqual(payload_a["target_layout_ids"], ["LAYOUT.2_0", "LAYOUT.5_1"])
        self.assertEqual(payload_b["target_layout_ids"], ["LAYOUT.2_0", "LAYOUT.5_1"])
        self.assertEqual(bytes_a, bytes_b)


class TestRenderInitOverwrite(unittest.TestCase):

    def test_refuses_overwrite_without_force(self) -> None:
        base = _SANDBOX / "overwrite_refuse"
        project_dir = _init_project(base)

        # First run creates the file.
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        rr_path = project_dir / "renders" / "render_request.json"
        original_bytes = rr_path.read_bytes()

        # Second run without --force should fail.
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("File exists", stderr)
        self.assertIn("--force", stderr)
        # Original content preserved.
        self.assertEqual(rr_path.read_bytes(), original_bytes)

    def test_allows_overwrite_with_force(self) -> None:
        base = _SANDBOX / "overwrite_force"
        project_dir = _init_project(base)

        # First run.
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

        # Overwrite with --force and different layout.
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--force",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(
            (project_dir / "renders" / "render_request.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(payload["target_layout_id"], "LAYOUT.5_1")


class TestRenderInitRoutingPlanOmission(unittest.TestCase):

    def test_routing_plan_path_omitted_when_file_missing(self) -> None:
        base = _SANDBOX / "no_routing"
        project_dir = _init_project(base)

        # Remove the routing plan draft.
        routing_path = project_dir / "drafts" / "routing_plan.draft.json"
        routing_path.unlink()

        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        # routing_plan.draft.json is required by validate, so this should fail.
        self.assertEqual(exit_code, 1)
        self.assertIn("missing", stderr.lower())


class TestRenderInitRoutingPlanOmissionWithFile(unittest.TestCase):
    """When routing_plan.draft.json is valid but we want to verify its inclusion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "routing_present")

    def test_routing_plan_path_included_when_exists(self) -> None:
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(
            (self.project_dir / "renders" / "render_request.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("routing_plan_path", payload)
        self.assertEqual(
            payload["routing_plan_path"],
            "drafts/routing_plan.draft.json",
        )


class TestRenderInitForwardSlashPaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = _init_project(_SANDBOX / "fwd_slash")

    def test_no_backslashes_in_render_request_json(self) -> None:
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        rr_path = self.project_dir / "renders" / "render_request.json"
        raw = rr_path.read_text(encoding="utf-8")
        self.assertNotIn("\\", raw, "Backslashes found in render_request.json")

    def test_no_backslashes_in_stdout_summary(self) -> None:
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(self.project_dir),
            "--target-layout", "LAYOUT.2_0",
            "--force",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertNotIn("\\", stdout, "Backslashes found in stdout summary")


class TestRenderInitTargetSelection(unittest.TestCase):

    def test_target_ids_written_sorted_without_inference(self) -> None:
        project_dir = _init_project(_SANDBOX / "target_ids_sorted")
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.5_1",
            "--target-ids", "TARGET.SURROUND.5_1,TARGET.STEREO.2_0,TARGET.SURROUND.5_1",
        ])
        self.assertEqual(exit_code, 0, msg=stderr)

        payload = json.loads(
            (project_dir / "renders" / "render_request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["options"]["target_ids"],
            ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
        )

    def test_unknown_target_id_fails_with_sorted_known_ids(self) -> None:
        project_dir = _init_project(_SANDBOX / "target_id_unknown")
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
            "--target-ids", "TARGET.DOES_NOT_EXIST",
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("Unknown render target token: TARGET.DOES_NOT_EXIST", stderr)
        known_ids = _extract_known_ids(stderr, marker="Available targets:")
        self.assertGreater(len(known_ids), 0)
        self.assertEqual(known_ids, sorted(known_ids))


class TestRenderInitInvalidScaffold(unittest.TestCase):

    def test_empty_dir_fails(self) -> None:
        empty_dir = _SANDBOX / "empty_scaffold" / "project"
        empty_dir.mkdir(parents=True, exist_ok=True)
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(empty_dir),
            "--target-layout", "LAYOUT.2_0",
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("missing", stderr.lower())

    def test_unknown_layout_fails(self) -> None:
        project_dir = _init_project(_SANDBOX / "bad_layout")
        exit_code, stdout, stderr = _run_main([
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.DOES_NOT_EXIST",
        ])
        self.assertEqual(exit_code, 1)
        self.assertIn("LAYOUT.DOES_NOT_EXIST", stderr)
        known_ids = _extract_known_ids(stderr, marker="Known layout_ids:")
        self.assertGreater(len(known_ids), 0)
        self.assertEqual(known_ids, sorted(known_ids))


class TestRenderInitMutualExclusivity(unittest.TestCase):

    def test_both_target_flags_error_is_deterministic(self) -> None:
        project_dir = _init_project(_SANDBOX / "target_flags_both")
        args = [
            "project", "render-init", str(project_dir),
            "--target-layout", "LAYOUT.2_0",
            "--target-layouts", "LAYOUT.2_0,LAYOUT.5_1",
        ]
        exit_a, _, stderr_a = _run_main(args)
        exit_b, _, stderr_b = _run_main(args)

        self.assertEqual(exit_a, 1)
        self.assertEqual(exit_b, 1)
        self.assertEqual(stderr_a, stderr_b)
        self.assertEqual(
            stderr_a.strip(),
            "Specify exactly one of --target-layout or --target-layouts.",
        )

    def test_neither_target_flag_errors(self) -> None:
        project_dir = _init_project(_SANDBOX / "target_flags_neither")
        exit_code, _, stderr = _run_main([
            "project", "render-init", str(project_dir),
        ])
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.strip(),
            "Specify exactly one of --target-layout or --target-layouts.",
        )


if __name__ == "__main__":
    unittest.main()
