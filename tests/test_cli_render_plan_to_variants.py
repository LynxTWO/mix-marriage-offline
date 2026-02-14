import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestCliRenderPlanToVariants(unittest.TestCase):
    def test_render_plan_to_variants_cli_generates_deterministic_variant_plan(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "variant_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            scene_path = temp_path / "scene.json"
            render_plan_path = temp_path / "render_plan.json"
            variant_plan_path = temp_path / "variant_plan.json"
            out_dir = temp_path / "variants_out"
            stems_dir.mkdir(parents=True, exist_ok=True)

            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.CLI.BRIDGE.TEST",
                    "source": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "created_from": "analyze",
                    },
                    "objects": [],
                    "beds": [],
                    "metadata": {
                        "preset_id": "PRESET.SAFE_CLEANUP",
                        "profile_id": "PROFILE.ASSIST",
                    },
                },
            )
            _write_json(
                render_plan_path,
                {
                    "schema_version": "0.1.0",
                    "plan_id": "PLAN.SCENE.CLI.BRIDGE.TEST.1234abcd",
                    "scene_path": scene_path.resolve().as_posix(),
                    "targets": [
                        "TARGET.STEREO.2_0",
                        "TARGET.STEREO.2_0",
                    ],
                    "policies": {"downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"},
                    "jobs": [
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav", "flac"],
                            "contexts": ["render"],
                            "notes": [],
                        },
                        {
                            "job_id": "JOB.002",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.5_1",
                            "routing_plan_path": (temp_path / "routing_plan.json").resolve().as_posix(),
                            "output_formats": ["wav"],
                            "contexts": ["render", "auto_apply"],
                            "notes": [],
                        },
                    ],
                },
            )

            first_exit = main(
                [
                    "render-plan",
                    "to-variants",
                    "--render-plan",
                    str(render_plan_path),
                    "--scene",
                    str(scene_path),
                    "--out",
                    str(variant_plan_path),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(first_exit, 0)
            self.assertTrue(variant_plan_path.exists())
            first_payload = json.loads(variant_plan_path.read_text(encoding="utf-8"))
            validator.validate(first_payload)

            second_exit = main(
                [
                    "render-plan",
                    "to-variants",
                    "--render-plan",
                    str(render_plan_path),
                    "--scene",
                    str(scene_path),
                    "--out",
                    str(variant_plan_path),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(second_exit, 0)
            second_payload = json.loads(variant_plan_path.read_text(encoding="utf-8"))
            self.assertEqual(first_payload, second_payload)

            self.assertEqual(
                first_payload.get("metadata"),
                {
                    "scene_path": scene_path.resolve().as_posix(),
                    "render_plan_path": render_plan_path.resolve().as_posix(),
                },
            )

            variants = first_payload.get("variants")
            self.assertIsInstance(variants, list)
            if not isinstance(variants, list) or len(variants) < 2:
                return
            self.assertEqual(variants[0].get("variant_slug"), "target_stereo_2_0")
            self.assertEqual(variants[1].get("variant_slug"), "target_stereo_2_0__a")
            self.assertEqual(
                variants[0].get("steps", {}).get("render_output_formats"),
                ["wav", "flac"],
            )
            first_variant_out_dir = (
                out_dir.resolve() / "VARIANT.001__target_stereo_2_0"
            ).as_posix()
            self.assertEqual(
                variants[0].get("run_config_overrides", {}).get("render", {}).get("out_dir"),
                first_variant_out_dir,
            )

    def test_render_plan_to_variants_cli_run_executes_runner_and_writes_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            scene_path = temp_path / "scene.json"
            render_plan_path = temp_path / "render_plan.json"
            variant_plan_path = temp_path / "variant_plan.json"
            out_dir = temp_path / "variants_out"
            stems_dir.mkdir(parents=True, exist_ok=True)

            _write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.CLI.BRIDGE.RUN",
                    "source": {
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "created_from": "analyze",
                    },
                    "objects": [],
                    "beds": [],
                    "metadata": {},
                },
            )
            _write_json(
                render_plan_path,
                {
                    "schema_version": "0.1.0",
                    "plan_id": "PLAN.SCENE.CLI.BRIDGE.RUN.1234abcd",
                    "scene_path": scene_path.resolve().as_posix(),
                    "targets": ["TARGET.STEREO.2_0"],
                    "policies": {},
                    "jobs": [
                        {
                            "job_id": "JOB.001",
                            "target_id": "TARGET.STEREO.2_0",
                            "target_layout_id": "LAYOUT.2_0",
                            "output_formats": ["wav"],
                            "contexts": ["render"],
                            "notes": [],
                        }
                    ],
                },
            )

            def _fake_run_variant_plan(
                plan: dict,
                repo_root: Path,
                *,
                cache_enabled: bool = True,
                cache_dir: Path | None = None,
                **kwargs: object,
            ) -> dict:
                del repo_root, cache_dir, kwargs
                variants = plan.get("variants")
                if not isinstance(variants, list):
                    variants = []
                results: list[dict[str, object]] = []
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    variant_id = variant.get("variant_id")
                    out_dir_value = (
                        variant.get("run_config_overrides", {})
                        .get("render", {})
                        .get("out_dir")
                    )
                    if not isinstance(variant_id, str) or not isinstance(out_dir_value, str):
                        continue
                    results.append(
                        {
                            "variant_id": variant_id,
                            "out_dir": out_dir_value,
                            "report_path": (Path(out_dir_value) / "report.json").as_posix(),
                            "ok": True,
                            "errors": [],
                        }
                    )
                return {
                    "schema_version": "0.1.0",
                    "plan": plan,
                    "results": results,
                }

            with mock.patch("mmo.cli_commands._scene.run_variant_plan", side_effect=_fake_run_variant_plan) as patched:
                exit_code = main(
                    [
                        "render-plan",
                        "to-variants",
                        "--render-plan",
                        str(render_plan_path),
                        "--scene",
                        str(scene_path),
                        "--out",
                        str(variant_plan_path),
                        "--out-dir",
                        str(out_dir),
                        "--run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(variant_plan_path.exists())
            result_path = out_dir / "variant_result.json"
            self.assertTrue(result_path.exists())
            self.assertTrue(patched.called)
            self.assertTrue(patched.call_args.kwargs.get("cache_enabled"))


if __name__ == "__main__":
    unittest.main()
