import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def _minimal_scene(stems_dir: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.RENDER.PLANNER.TEST",
        "source": {
            "stems_dir": stems_dir,
            "created_from": "analyze",
        },
        "objects": [],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _scene_with_policy_signals(stems_dir: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.RENDER.PLANNER.PLACEMENT.TEST",
        "source": {
            "stems_dir": stems_dir,
            "created_from": "draft",
        },
        "objects": [
            {
                "object_id": "OBJ.STEM.KICK",
                "stem_id": "STEM.KICK",
                "role_id": "ROLE.DRUM.KICK",
                "group_bus": "BUS.DRUMS",
                "label": "Kick",
                "channel_count": 1,
                "width_hint": 0.2,
                "depth_hint": 0.25,
                "confidence": 0.95,
                "intent": {
                    "confidence": 0.95,
                    "width": 0.2,
                    "depth": 0.25,
                    "locks": [],
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.STEM.PAD",
                "stem_id": "STEM.PAD",
                "role_id": "ROLE.SYNTH.PAD",
                "group_bus": "BUS.MUSIC",
                "label": "Pad",
                "channel_count": 1,
                "width_hint": 0.9,
                "depth_hint": 0.6,
                "confidence": 0.86,
                "intent": {
                    "confidence": 0.86,
                    "width": 0.9,
                    "depth": 0.6,
                    "locks": [],
                },
                "notes": ["long texture"],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _minimal_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.2_0",
        "scene_path": scene_path,
    }


def _request_with_options(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.5_1",
        "scene_path": scene_path,
        "options": {
            "output_formats": ["wav", "flac"],
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "gates_policy_id": "POLICY.GATES.CORE_V0",
            "loudness_profile_id": "LOUD.EBU_R128_PROGRAM",
            "lfe_derivation_profile_id": "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
            "lfe_mode": "stereo",
        },
    }


def _request_with_explicit_target_ids(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.7_1"],
        "scene_path": scene_path,
        "options": {
            "target_ids": ["TARGET.SURROUND.7_1", "TARGET.STEREO.2_0"],
            "output_formats": ["wav"],
        },
    }


def _request_with_stereo_target_variants(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0"],
        "scene_path": scene_path,
        "options": {
            "target_ids": ["TARGET.STEREO.2_0_ALT", "TARGET.STEREO.2_0"],
            "output_formats": ["wav"],
        },
    }


def _routing_plan() -> dict:
    return {
        "schema_version": "0.1.0",
        "source_layout_id": "LAYOUT.5_1",
        "target_layout_id": "LAYOUT.2_0",
        "routes": [
            {
                "stem_id": "STEM.001",
                "stem_channels": 2,
                "target_channels": 2,
                "mapping": [
                    {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                    {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
                ],
                "notes": [],
            }
        ],
    }


class TestRenderPlanFromRequestCli(unittest.TestCase):
    def test_happy_path_produces_schema_valid_render_plan(self) -> None:
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            # Verify request echo.
            self.assertIn("request", payload)
            self.assertEqual(
                payload["request"]["target_layout_id"], "LAYOUT.2_0",
            )
            self.assertEqual(payload["request"]["scene_path"], scene_posix)

            # Verify resolved section.
            self.assertIn("resolved", payload)
            self.assertEqual(
                payload["resolved"]["target_layout_id"], "LAYOUT.2_0",
            )
            self.assertIsInstance(payload["resolved"]["channel_order"], list)
            self.assertGreater(len(payload["resolved"]["channel_order"]), 0)

            # Verify jobs.
            jobs = payload["jobs"]
            self.assertIsInstance(jobs, list)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["job_id"], "JOB.001")
            self.assertEqual(jobs[0]["status"], "planned")
            self.assertIsInstance(jobs[0]["inputs"], list)
            self.assertIsInstance(jobs[0]["outputs"], list)
            self.assertGreater(len(jobs[0]["outputs"]), 0)
            self.assertEqual(jobs[0]["resolved_target_id"], "TARGET.STEREO.2_0")
            self.assertIn("downmix_routes", jobs[0])
            self.assertIsInstance(jobs[0]["downmix_routes"], list)
            self.assertEqual(len(jobs[0]["downmix_routes"]), 1)
            self.assertEqual(
                jobs[0]["downmix_routes"][0]["from_layout_id"],
                "LAYOUT.2_0",
            )
            self.assertEqual(
                jobs[0]["downmix_routes"][0]["to_layout_id"],
                "LAYOUT.2_0",
            )
            self.assertEqual(
                jobs[0]["downmix_routes"][0]["kind"],
                "direct",
            )

    def test_happy_path_includes_render_intent_when_scene_has_policy_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _scene_with_policy_signals(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            jobs = payload.get("jobs")
            self.assertIsInstance(jobs, list)
            if not isinstance(jobs, list) or not jobs:
                return
            render_intent = jobs[0].get("render_intent")
            self.assertIsInstance(render_intent, dict)
            if not isinstance(render_intent, dict):
                return
            self.assertEqual(
                render_intent.get("policy_id"),
                "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1",
            )
            self.assertEqual(render_intent.get("target_layout_id"), "LAYOUT.2_0")
            stem_sends = render_intent.get("stem_sends")
            self.assertIsInstance(stem_sends, list)
            if not isinstance(stem_sends, list):
                return
            self.assertGreaterEqual(len(stem_sends), 2)
            kick_rows = [
                row
                for row in stem_sends
                if isinstance(row, dict) and row.get("stem_id") == "STEM.KICK"
            ]
            self.assertEqual(len(kick_rows), 1)

    def test_happy_path_with_options_and_routing_plan(self) -> None:
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            routing_plan_path = temp_path / "routing_plan.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))
            _write_json(routing_plan_path, _routing_plan())

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--routing-plan", str(routing_plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            # Policies resolved from request options.
            self.assertEqual(
                payload["resolved"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )
            self.assertEqual(
                payload["resolved"]["gates_policy_id"],
                "POLICY.GATES.CORE_V0",
            )
            self.assertEqual(
                payload["resolved"]["lfe_derivation_profile_id"],
                "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
            )
            self.assertEqual(payload["resolved"]["lfe_mode"], "stereo")

            # Output formats from request options.
            self.assertEqual(
                payload["jobs"][0]["output_formats"], ["wav", "flac"],
            )
            self.assertEqual(
                payload["request"]["options"]["loudness_profile_id"],
                "LOUD.EBU_R128_PROGRAM",
            )
            self.assertEqual(
                payload["jobs"][0]["downmix_routes"],
                [
                    {
                        "from_layout_id": "LAYOUT.5_1",
                        "kind": "direct",
                        "policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                        "to_layout_id": "LAYOUT.2_0",
                    }
                ],
            )
            self.assertEqual(
                payload["policies"]["lfe_derivation_profile_id"],
                "LFE_DERIVE.MUSIC_80_LR24_TRIM_10",
            )

    def test_overwrite_refusal_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            # Pre-create the output file.
            out_path.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-plan", "plan",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--out", str(out_path),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_overwrite_allowed_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            # Pre-create the output file.
            out_path.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")

    def test_determinism_two_runs_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out1 = temp_path / "plan1.json"
            out2 = temp_path / "plan2.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))

            exit1 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out1),
            ])
            exit2 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            bytes1 = out1.read_bytes()
            bytes2 = out2.read_bytes()
            self.assertEqual(bytes1, bytes2)

    def test_rejects_backslash_in_request_scene_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes\\bad\\path.json",
            })

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-plan", "plan",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--out", str(out_path),
                ])
            self.assertNotEqual(exit_code, 0)

    def test_existing_render_plan_build_still_works(self) -> None:
        """Regression: the existing render-plan build subcommand must not break."""
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            out_path = temp_path / "render_plan.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))

            exit_code = main([
                "render-plan", "build",
                "--scene", str(scene_path),
                "--targets", "TARGET.STEREO.2_0",
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertIn("plan_id", payload)
            self.assertIn("targets", payload)


class TestRenderPlanFromRequestErrorPaths(unittest.TestCase):
    """Deterministic, stable error messages for invalid inputs."""

    def _run_plan(
        self,
        temp_path: Path,
        request_payload: dict,
        *,
        with_routing_plan: bool = False,
    ) -> tuple[int, str]:
        stems_dir = temp_path / "stems"
        stems_dir.mkdir(exist_ok=True)

        scene_path = temp_path / "scene.json"
        request_path = temp_path / "render_request.json"
        out_path = temp_path / "render_plan.json"

        _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
        _write_json(request_path, request_payload)

        args = [
            "render-plan", "plan",
            "--request", str(request_path),
            "--scene", str(scene_path),
            "--out", str(out_path),
        ]
        if with_routing_plan:
            rp_path = temp_path / "routing_plan.json"
            _write_json(rp_path, _routing_plan())
            args.extend(["--routing-plan", str(rp_path)])

        stderr_capture = StringIO()
        with redirect_stderr(stderr_capture):
            exit_code = main(args)
        return exit_code, stderr_capture.getvalue()

    def test_unknown_layout_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.DOES_NOT_EXIST",
                "scene_path": scene_posix,
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown layout_id", err)
            self.assertIn("LAYOUT.DOES_NOT_EXIST", err)
            # Known IDs listed and sorted.
            self.assertIn("LAYOUT.1_0", err)
            self.assertIn("LAYOUT.2_0", err)
            self.assertLess(err.index("LAYOUT.1_0"), err.index("LAYOUT.2_0"))

    def test_unknown_downmix_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "downmix_policy_id": "POLICY.DOWNMIX.FAKE_V99",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown policy_id", err)
            self.assertIn("POLICY.DOWNMIX.FAKE_V99", err)
            self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", err)

    def test_unknown_gates_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "gates_policy_id": "POLICY.GATES.NONEXISTENT",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown gates_policy_id", err)
            self.assertIn("POLICY.GATES.NONEXISTENT", err)
            self.assertIn("POLICY.GATES.CORE_V0", err)

    def test_unknown_loudness_profile_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "loudness_profile_id": "LOUD.NONEXISTENT_PROFILE",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown loudness_profile_id", err)
            self.assertIn("LOUD.NONEXISTENT_PROFILE", err)
            self.assertIn("LOUD.EBU_R128_PROGRAM", err)

    def test_unknown_target_id_in_options_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "target_ids": ["TARGET.DOES.NOT.EXIST"],
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown target_id: TARGET.DOES.NOT.EXIST", err)
            self.assertIn("Known target_ids:", err)
            self.assertIn("TARGET.STEREO.2_0", err)

    def test_known_policy_without_route_fails_stably(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(tp, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "downmix_policy_id": "POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("No downmix route found: LAYOUT.5_1 -> LAYOUT.2_0", err)
            self.assertIn("policy_id=POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0", err)
            self.assertIn("Known policy_ids:", err)
            self.assertIn("POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0", err)
            self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", err)
            self.assertLess(
                err.index("POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0"),
                err.index("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"),
            )
            self.assertIn("Known layout_ids:", err)
            self.assertIn("LAYOUT.1_0", err)
            self.assertIn("LAYOUT.2_0", err)
            known_layouts_section = err.split("Known layout_ids:", 1)[1].splitlines()[0]
            self.assertLess(
                known_layouts_section.index("LAYOUT.1_0"),
                known_layouts_section.index("LAYOUT.2_0"),
            )

    def test_routing_plan_path_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, err = self._run_plan(
                tp,
                {
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": scene_posix,
                    "routing_plan_path": "routing/plan.json",
                },
                with_routing_plan=False,
            )
            self.assertEqual(rc, 1)
            self.assertIn("routing_plan_path is set", err)
            self.assertIn("routing/plan.json", err)


def _multi_target_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
        "scene_path": scene_path,
    }


class TestRenderPlanFromRequestMultiTarget(unittest.TestCase):
    """Multi-target render plan from request tests."""

    def test_multi_target_produces_schema_valid_plan(self) -> None:
        validator = _schema_validator("render_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _multi_target_request(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            # Verify request echo uses target_layout_ids.
            self.assertIn("request", payload)
            self.assertIn("target_layout_ids", payload["request"])
            self.assertNotIn("target_layout_id", payload["request"])
            self.assertEqual(
                payload["request"]["target_layout_ids"],
                ["LAYOUT.2_0", "LAYOUT.5_1"],
            )

            # Verify resolved section (first layout).
            self.assertIn("resolved", payload)
            self.assertEqual(
                payload["resolved"]["target_layout_id"], "LAYOUT.2_0",
            )

            # Verify resolved_layouts has entries for both layouts.
            self.assertIn("resolved_layouts", payload)
            self.assertEqual(len(payload["resolved_layouts"]), 2)
            self.assertEqual(
                payload["resolved_layouts"][0]["target_layout_id"], "LAYOUT.2_0",
            )
            self.assertEqual(
                payload["resolved_layouts"][1]["target_layout_id"], "LAYOUT.5_1",
            )

            # Verify jobs: 2 jobs, sorted by layout_id.
            jobs = payload["jobs"]
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["job_id"], "JOB.001")
            self.assertEqual(jobs[0]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(jobs[0]["resolved_target_id"], "TARGET.STEREO.2_0")
            self.assertEqual(jobs[1]["job_id"], "JOB.002")
            self.assertEqual(jobs[1]["target_layout_id"], "LAYOUT.5_1")
            self.assertEqual(jobs[1]["resolved_target_id"], "TARGET.SURROUND.5_1")

    def test_multi_target_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out1 = temp_path / "plan1.json"
            out2 = temp_path / "plan2.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _multi_target_request(scene_posix))

            exit1 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out1),
            ])
            exit2 = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_multi_target_job_order_by_layout_id(self) -> None:
        """Reverse-order input still produces sorted jobs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, {
                "schema_version": "0.1.0",
                "target_layout_ids": ["LAYOUT.5_1", "LAYOUT.2_0"],
                "scene_path": scene_posix,
            })

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            jobs = payload["jobs"]
            self.assertEqual(jobs[0]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(jobs[1]["target_layout_id"], "LAYOUT.5_1")
            self.assertEqual(jobs[0]["resolved_target_id"], "TARGET.STEREO.2_0")
            self.assertEqual(jobs[1]["resolved_target_id"], "TARGET.SURROUND.5_1")

    def test_explicit_target_ids_are_resolved_per_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_explicit_target_ids(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            jobs = payload["jobs"]
            self.assertEqual(jobs[0]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(jobs[0]["resolved_target_id"], "TARGET.STEREO.2_0")
            self.assertEqual(jobs[1]["target_layout_id"], "LAYOUT.7_1")
            self.assertEqual(jobs[1]["resolved_target_id"], "TARGET.SURROUND.7_1")

    def test_explicit_stereo_target_variants_emit_distinct_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            out_path = temp_path / "render_plan.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_stereo_target_variants(scene_posix))

            exit_code = main([
                "render-plan", "plan",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            jobs = payload["jobs"]
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(jobs[1]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(jobs[0]["resolved_target_id"], "TARGET.STEREO.2_0")
            self.assertEqual(jobs[1]["resolved_target_id"], "TARGET.STEREO.2_0_ALT")

            output_paths = [
                jobs[0]["outputs"][0]["path"],
                jobs[1]["outputs"][0]["path"],
            ]
            self.assertEqual(len(set(output_paths)), 2)


if __name__ == "__main__":
    unittest.main()
