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


def _minimal_render_plan(scene_path: str) -> dict:
    """A minimal render_plan that passes schema validation."""
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.test.abcdef01",
        "scene_path": scene_path,
        "targets": ["TARGET.STEREO.2_0"],
        "policies": {},
        "jobs": [
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "output_formats": ["wav"],
                "contexts": ["render"],
                "notes": ["Test job."],
            },
        ],
        "request": {
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path,
        },
    }


def _render_plan_with_policies(scene_path: str) -> dict:
    """A render_plan with policies and multiple jobs."""
    return {
        "schema_version": "0.1.0",
        "plan_id": "PLAN.multi.12345678",
        "scene_path": scene_path,
        "targets": ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
        "policies": {
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "gates_policy_id": "POLICY.GATES.CORE_V0",
        },
        "jobs": [
            {
                "job_id": "JOB.001",
                "target_id": "TARGET.STEREO.2_0",
                "target_layout_id": "LAYOUT.2_0",
                "output_formats": ["wav"],
                "contexts": ["render"],
                "notes": ["Stereo target."],
            },
            {
                "job_id": "JOB.002",
                "target_id": "TARGET.SURROUND.5_1",
                "target_layout_id": "LAYOUT.5_1",
                "output_formats": ["wav", "flac"],
                "contexts": ["render"],
                "notes": ["Surround target."],
            },
        ],
        "request": {
            "target_layout_id": "LAYOUT.2_0",
            "scene_path": scene_path,
        },
    }


def _render_plan_with_loudness_profile(scene_path: str, profile_id: str) -> dict:
    payload = _render_plan_with_policies(scene_path)
    payload["request"]["options"] = {"loudness_profile_id": profile_id}
    payload["policies"]["loudness_profile_id"] = profile_id
    return payload


def _render_plan_with_render_intent(scene_path: str) -> dict:
    payload = _minimal_render_plan(scene_path)
    payload["jobs"][0]["render_intent"] = {
        "schema_version": "0.1.0",
        "policy_id": "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1",
        "target_layout_id": "LAYOUT.2_0",
        "channel_order": ["SPK.L", "SPK.R"],
        "bus_gain_staging": {
            "master_gain_db": 0.0,
            "group_trims_db": {
                "BUS.DRUMS": 0.0,
            },
        },
        "stem_sends": [
            {
                "stem_id": "STEM.KICK",
                "role_id": "ROLE.DRUM.KICK",
                "group_bus": "BUS.DRUMS",
                "policy_class": "ANCHOR.TRANSIENT_FRONT_ONLY",
                "confidence": 0.95,
                "width_hint": 0.2,
                "depth_hint": 0.25,
                "locks": [],
                "bus_trim_db": 0.0,
                "gains": {"SPK.L": 0.86, "SPK.R": 0.86},
                "nonzero_channels": ["SPK.L", "SPK.R"],
                "notes": [],
            }
        ],
        "notes": [
            "Conservative front-heavy placement policy.",
        ],
    }
    return payload


def _render_plan_with_stage_inputs(scene_path: str) -> dict:
    payload = _render_plan_with_policies(scene_path)
    payload["request"]["options"] = {"sample_rate_hz": 48000}
    payload["jobs"][0]["outputs"] = [
        {"path": "renders/job_001.wav", "format": "wav"},
    ]
    payload["jobs"][1]["outputs"] = [
        {"path": "renders/job_002.wav", "format": "wav"},
        {"path": "renders/job_002.flac", "format": "flac"},
    ]
    return payload


class TestRenderReportCli(unittest.TestCase):
    def test_produces_schema_valid_render_report(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

    def test_report_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")

            # request summary
            self.assertEqual(payload["request"]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(payload["request"]["scene_path"], scene_posix)

            # jobs default to skipped
            self.assertEqual(len(payload["jobs"]), 1)
            self.assertEqual(payload["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(payload["jobs"][0]["status"], "skipped")
            self.assertEqual(payload["jobs"][0]["output_files"], [])
            self.assertIn("reason: dry_run", payload["jobs"][0]["notes"])

            # policies_applied
            self.assertIsNone(payload["policies_applied"]["downmix_policy_id"])
            self.assertIsNone(payload["policies_applied"]["gates_policy_id"])
            self.assertIsNone(payload["policies_applied"]["matrix_id"])

            # qa_gates not run
            self.assertEqual(payload["qa_gates"]["status"], "not_run")
            self.assertEqual(payload["qa_gates"]["gates"], [])

    def test_report_with_policies_and_multiple_jobs(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_policies(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            self.assertEqual(len(payload["jobs"]), 2)
            self.assertEqual(payload["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(payload["jobs"][1]["job_id"], "JOB.002")
            for job in payload["jobs"]:
                self.assertEqual(job["status"], "skipped")

            self.assertEqual(
                payload["policies_applied"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )
            self.assertEqual(
                payload["policies_applied"]["gates_policy_id"],
                "POLICY.GATES.CORE_V0",
            )

    def test_report_carries_render_intent_receipt(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_render_intent(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            job = payload["jobs"][0]
            self.assertIn("render_intent", job)
            self.assertEqual(
                job["render_intent"]["policy_id"],
                "POLICY.PLACEMENT.CONSERVATIVE_SURROUND_V1",
            )

    def test_report_includes_selected_loudness_profile_receipt(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan_with_loudness_profile(
                    scene_posix,
                    "LOUD.ATSC_A85_FIXED_DIALNORM",
                ),
            )

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            receipt = payload.get("loudness_profile_receipt")
            self.assertIsInstance(receipt, dict)
            if not isinstance(receipt, dict):
                return
            self.assertEqual(receipt["loudness_profile_id"], "LOUD.ATSC_A85_FIXED_DIALNORM")
            self.assertEqual(receipt["target_loudness"], -24.0)
            self.assertEqual(receipt["target_unit"], "LKFS")
            self.assertEqual(receipt["tolerance_lu"], 2.0)
            self.assertEqual(receipt["max_true_peak_dbtp"], -2.0)
            self.assertEqual(receipt["method_id"], "BS.1770-5")

    def test_report_includes_informational_profile_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(
                plan_path,
                _render_plan_with_loudness_profile(
                    scene_posix,
                    "LOUD.SPOTIFY_PLAYBACK_NORMALIZATION",
                ),
            )

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            receipt = payload["loudness_profile_receipt"]
            joined_warnings = " ".join(receipt["warnings"])
            self.assertIn("informational playback normalization guidance", joined_warnings)

    def test_report_includes_deterministic_stage_sections(self) -> None:
        validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_stage_inputs(scene_posix))

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            self.assertIn("stage_metrics", payload)
            self.assertIn("stage_evidence", payload)
            self.assertNotIn("wall_clock", payload)

            required_stage_ids = {
                "planning",
                "resampling",
                "dsp_hooks",
                "export_finalize",
                "qa_gates",
            }
            self.assertTrue(
                required_stage_ids.issubset({row["stage_id"] for row in payload["stage_metrics"]})
            )
            self.assertTrue(
                required_stage_ids.issubset({row["stage_id"] for row in payload["stage_evidence"]})
            )
            export_rows = [
                row
                for row in payload["stage_evidence"]
                if row["stage_id"] == "export_finalize"
            ]
            self.assertTrue(export_rows)
            first_export = export_rows[0]["evidence"].get("export_finalization_receipt")
            self.assertIsInstance(first_export, dict)
            if isinstance(first_export, dict):
                self.assertEqual(first_export.get("bit_depth"), 24)
                self.assertEqual(first_export.get("dither_policy"), "none")

    def test_stage_sections_are_sorted_by_job_then_stage_then_where(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            payload = _render_plan_with_stage_inputs(scene_posix)
            payload["jobs"] = list(reversed(payload["jobs"]))
            _write_json(plan_path, payload)

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0)

            report_payload = json.loads(out_path.read_text(encoding="utf-8"))

            for key in ("stage_metrics", "stage_evidence"):
                rows = report_payload[key]
                actual = [
                    (row["where"][0], row["stage_id"], tuple(row["where"]))
                    for row in rows
                ]
                self.assertEqual(actual, sorted(actual))


class TestRenderReportOverwrite(unittest.TestCase):
    def test_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))
            out_path.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-report",
                    "--plan", str(plan_path),
                    "--out", str(out_path),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_allows_overwrite_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out_path = temp_path / "render_report.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _minimal_render_plan(scene_posix))
            out_path.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out_path),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")


class TestRenderReportDeterminism(unittest.TestCase):
    def test_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "render_plan.json"
            out1 = temp_path / "report1.json"
            out2 = temp_path / "report2.json"

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            _write_json(plan_path, _render_plan_with_policies(scene_posix))

            exit1 = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out1),
            ])
            exit2 = main([
                "render-report",
                "--plan", str(plan_path),
                "--out", str(out2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            bytes1 = out1.read_bytes()
            bytes2 = out2.read_bytes()
            self.assertEqual(bytes1, bytes2)

    def test_core_function_deterministic(self) -> None:
        from mmo.core.render_reporting import build_render_report_from_plan

        plan = _minimal_render_plan("scenes/test/scene.json")
        first = build_render_report_from_plan(plan)
        second = build_render_report_from_plan(plan)
        self.assertNotIn("wall_clock", first)
        self.assertNotIn("wall_clock", second)
        self.assertEqual(
            json.dumps(first, indent=2, sort_keys=True),
            json.dumps(second, indent=2, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
