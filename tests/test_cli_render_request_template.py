"""Tests for ``mmo render-request template`` CLI command."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "render_request.schema.json"


class TestRenderRequestTemplateHappyPath(unittest.TestCase):
    """Happy path: output is schema-valid JSON."""

    def test_basic_template_is_schema_valid(self) -> None:
        validator = _schema_validator(SCHEMA_PATH)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.5_1",
                           "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(payload["schema_version"], "0.1.0")
            self.assertEqual(payload["target_layout_id"], "LAYOUT.5_1")
            self.assertEqual(payload["scene_path"], "scene.json")
            self.assertTrue(payload["options"]["dry_run"])

    def test_with_scene_and_routing_plan(self) -> None:
        validator = _schema_validator(SCHEMA_PATH)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.2_0",
                           "--scene", "project/my_scene.json",
                           "--routing-plan", "project/routing.json",
                           "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(payload["scene_path"], "project/my_scene.json")
            self.assertEqual(payload["routing_plan_path"], "project/routing.json")

    def test_canonical_defaults_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                main(["render-request", "template",
                      "--target-layout", "LAYOUT.7_1_4",
                      "--out", str(out)])
            payload = json.loads(out.read_text(encoding="utf-8"))
            opts = payload["options"]
            self.assertEqual(opts["downmix_policy_id"],
                             "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
            self.assertEqual(opts["gates_policy_id"],
                             "POLICY.GATES.CORE_V0")
            self.assertTrue(opts["dry_run"])


class TestRenderRequestTemplateDeterminism(unittest.TestCase):
    """Two runs with identical inputs must produce identical bytes."""

    def test_deterministic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_a = Path(td) / "a.json"
            out_b = Path(td) / "b.json"
            for out in (out_a, out_b):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    rc = main(["render-request", "template",
                               "--target-layout", "LAYOUT.5_1",
                               "--scene", "demo/scene.json",
                               "--routing-plan", "demo/routing.json",
                               "--out", str(out)])
                    self.assertEqual(rc, 0)
            self.assertEqual(
                out_a.read_bytes(),
                out_b.read_bytes(),
                "Two runs with identical inputs must produce identical bytes.",
            )


class TestRenderRequestTemplateUnknownLayout(unittest.TestCase):
    """Unknown layout ID should fail with sorted known IDs."""

    def test_unknown_layout_id_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stderr = StringIO()
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.DOES_NOT_EXIST",
                           "--out", str(out)])
            self.assertEqual(rc, 1)
            err_text = stderr.getvalue()
            self.assertIn("Unknown layout_id", err_text)
            self.assertIn("LAYOUT.DOES_NOT_EXIST", err_text)
            # Known IDs should be listed in sorted order.
            self.assertIn("LAYOUT.1_0", err_text)
            self.assertIn("LAYOUT.2_0", err_text)
            # Verify sorted ordering: LAYOUT.1_0 appears before LAYOUT.2_0.
            self.assertLess(
                err_text.index("LAYOUT.1_0"),
                err_text.index("LAYOUT.2_0"),
            )
            self.assertFalse(out.exists(), "Output must not be written on error.")


class TestRenderRequestTemplateOverwrite(unittest.TestCase):
    """Overwrite refusal without --force and allowed with --force."""

    def test_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            out.write_text("{}", encoding="utf-8")
            stderr = StringIO()
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.5_1",
                           "--out", str(out)])
            self.assertEqual(rc, 1)
            err_text = stderr.getvalue()
            self.assertIn("File exists", err_text)
            self.assertIn("--force", err_text)
            # Original content must be preserved.
            self.assertEqual(out.read_text(encoding="utf-8"), "{}")

    def test_allows_overwrite_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            out.write_text("{}", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.5_1",
                           "--out", str(out),
                           "--force"])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["target_layout_id"], "LAYOUT.5_1")


class TestRenderRequestTemplateBackslashNormalization(unittest.TestCase):
    """Backslash paths must be normalized to forward slashes in output."""

    def test_scene_backslash_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.2_0",
                           "--scene", "project\\subdir\\scene.json",
                           "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("\\", payload["scene_path"])
            self.assertEqual(payload["scene_path"], "project/subdir/scene.json")

    def test_routing_plan_backslash_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.2_0",
                           "--routing-plan", "project\\routing.json",
                           "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("\\", payload["routing_plan_path"])
            self.assertEqual(payload["routing_plan_path"], "project/routing.json")

    def test_output_json_has_no_backslashes_in_paths(self) -> None:
        """Raw JSON bytes must not contain backslash in path values."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rr.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["render-request", "template",
                           "--target-layout", "LAYOUT.2_0",
                           "--scene", "a\\b\\c.json",
                           "--routing-plan", "d\\e.json",
                           "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            # Verify no backslashes in path-valued fields.
            self.assertNotIn("\\", payload["scene_path"])
            self.assertNotIn("\\", payload["routing_plan_path"])


if __name__ == "__main__":
    unittest.main()
