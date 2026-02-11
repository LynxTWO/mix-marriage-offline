import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.project_file import (
    load_project,
    new_project,
    update_project_last_run,
    write_project,
)


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


def _minimal_report_payload(run_config: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.PROJECT.FILE.TEST",
        "project_id": "PROJECT.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {},
        "issues": [],
        "recommendations": [],
        "run_config": run_config,
    }


class TestProjectFile(unittest.TestCase):
    def test_new_project_is_schema_valid_with_posix_stems_dir(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "project.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"

            project = new_project(stems_dir, notes="demo")
            validator.validate(project)
            self.assertEqual(project.get("stems_dir"), stems_dir.resolve().as_posix())
            self.assertNotIn("\\", str(project.get("stems_dir")))

            write_project(project_path, project)
            loaded = load_project(project_path)
            self.assertEqual(project, loaded)
            self.assertEqual(
                project_path.read_text(encoding="utf-8"),
                json.dumps(project, indent=2, sort_keys=True) + "\n",
            )

    def test_update_project_last_run_updates_timestamp_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)

            with mock.patch(
                "mmo.core.project_file._utc_now_iso",
                side_effect=["2026-02-06T12:00:00Z", "2026-02-06T12:00:05Z"],
            ):
                project = new_project(stems_dir, notes=None)
                updated = update_project_last_run(
                    project,
                    {
                        "deliverables_index_path": (
                            temp_path / "out" / "deliverables_index.json"
                        ).resolve().as_posix(),
                        "out_dir": (temp_path / "out").resolve().as_posix(),
                        "mode": "single",
                    },
                )

            self.assertEqual(project.get("updated_at_utc"), "2026-02-06T12:00:00Z")
            self.assertEqual(updated.get("updated_at_utc"), "2026-02-06T12:00:05Z")
            self.assertEqual(
                updated.get("last_run"),
                {
                    "mode": "single",
                    "out_dir": (temp_path / "out").resolve().as_posix(),
                    "deliverables_index_path": (
                        temp_path / "out" / "deliverables_index.json"
                    ).resolve().as_posix(),
                },
            )

    def test_project_run_updates_single_mode_last_run_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "project.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"

            run_config = {
                "schema_version": "0.1.0",
                "profile_id": "PROFILE.ASSIST",
            }
            write_project(project_path, new_project(stems_dir, notes=None))

            def _fake_run_one_shot_workflow(**kwargs: object) -> int:
                target_out_dir = kwargs["out_dir"]
                if not isinstance(target_out_dir, Path):
                    return 1
                target_out_dir.mkdir(parents=True, exist_ok=True)
                report_path = target_out_dir / "report.json"
                report_path.write_text(
                    json.dumps(_minimal_report_payload(run_config), indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                deliverables_index_path = target_out_dir / "deliverables_index.json"
                deliverables_index_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "0.1.0",
                            "root_out_dir": target_out_dir.resolve().as_posix(),
                            "mode": "single",
                            "entries": [],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0

            with mock.patch(
                "mmo.cli._run_one_shot_workflow",
                side_effect=_fake_run_one_shot_workflow,
            ) as patched_single_run:
                exit_code = main(
                    [
                        "project",
                        "run",
                        "--project",
                        str(project_path),
                        "--out",
                        str(out_dir),
                        "--deliverables-index",
                        "--cache",
                        "off",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(patched_single_run.called)
            self.assertEqual(patched_single_run.call_args.kwargs["stems_dir"], stems_dir)

            project = load_project(project_path)
            validator.validate(project)
            self.assertEqual(project["last_run"]["mode"], "single")
            self.assertEqual(project["last_run"]["out_dir"], out_dir.resolve().as_posix())
            self.assertEqual(
                project["last_run"]["deliverables_index_path"],
                (out_dir / "deliverables_index.json").resolve().as_posix(),
            )
            self.assertNotIn("variant_plan_path", project["last_run"])
            self.assertNotIn("variant_result_path", project["last_run"])
            self.assertEqual(project.get("run_config_defaults"), run_config)
            self.assertEqual(
                project.get("lockfile_path"),
                (out_dir / "lockfile.json").resolve().as_posix(),
            )
            self.assertIsInstance(project.get("lock_hash"), str)
            self.assertTrue(project["lock_hash"])

    def test_project_run_render_many_updates_variants_last_run_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "project.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"
            write_project(project_path, new_project(stems_dir, notes=None))

            base_run_config = {
                "schema_version": "0.1.0",
                "profile_id": "PROFILE.ASSIST",
            }

            def _fake_run_render_many_workflow(**kwargs: object) -> int:
                target_out_dir = kwargs["out_dir"]
                if not isinstance(target_out_dir, Path):
                    return 1
                target_out_dir.mkdir(parents=True, exist_ok=True)

                scene_path = target_out_dir / "scene.json"
                render_plan_path = target_out_dir / "render_plan.json"
                variant_plan_path = target_out_dir / "variant_plan.json"
                variant_result_path = target_out_dir / "variant_result.json"
                deliverables_index_path = target_out_dir / "deliverables_index.json"
                scene_path.write_text('{"schema_version":"0.1.0"}\n', encoding="utf-8")
                render_plan_path.write_text(
                    '{"schema_version":"0.1.0","plan_id":"PLAN.TEST","targets":[],"jobs":[]}\n',
                    encoding="utf-8",
                )
                variant_plan_payload = {
                    "schema_version": "0.1.0",
                    "stems_dir": stems_dir.resolve().as_posix(),
                    "base_run_config": base_run_config,
                    "variants": [],
                }
                variant_plan_path.write_text(
                    json.dumps(variant_plan_payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                variant_result_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "0.1.0",
                            "plan": variant_plan_payload,
                            "results": [],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                deliverables_index_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "0.1.0",
                            "root_out_dir": target_out_dir.resolve().as_posix(),
                            "mode": "variants",
                            "entries": [],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0

            with mock.patch(
                "mmo.cli._run_render_many_workflow",
                side_effect=_fake_run_render_many_workflow,
            ) as patched_render_many:
                exit_code = main(
                    [
                        "project",
                        "run",
                        "--project",
                        str(project_path),
                        "--out",
                        str(out_dir),
                        "--render-many",
                        "--targets",
                        "Stereo (streaming),5.1 (home theater)",
                        "--deliverables-index",
                        "--cache",
                        "off",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(patched_render_many.called)
            self.assertEqual(patched_render_many.call_args.kwargs["stems_dir"], stems_dir)
            self.assertEqual(
                patched_render_many.call_args.kwargs["target_ids"],
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1"],
            )

            project = load_project(project_path)
            validator.validate(project)
            self.assertEqual(project["last_run"]["mode"], "variants")
            self.assertEqual(project["last_run"]["out_dir"], out_dir.resolve().as_posix())
            self.assertEqual(
                project["last_run"]["variant_plan_path"],
                (out_dir / "variant_plan.json").resolve().as_posix(),
            )
            self.assertEqual(
                project["last_run"]["variant_result_path"],
                (out_dir / "variant_result.json").resolve().as_posix(),
            )
            self.assertEqual(
                project["last_run"]["deliverables_index_path"],
                (out_dir / "deliverables_index.json").resolve().as_posix(),
            )
            self.assertIsInstance(project.get("run_config_defaults"), dict)
            if isinstance(project.get("run_config_defaults"), dict):
                self.assertEqual(
                    project["run_config_defaults"].get("profile_id"),
                    "PROFILE.ASSIST",
                )

    def test_project_schema_accepts_optional_timeline_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "project.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"
            timeline_path = temp_path / "timeline.json"
            timeline_path.write_text('{"schema_version":"0.1.0","sections":[]}\n', encoding="utf-8")

            project_payload = new_project(stems_dir, notes=None)
            project_payload["timeline_path"] = timeline_path.resolve().as_posix()
            write_project(project_path, project_payload)

            loaded_project = load_project(project_path)
            validator.validate(loaded_project)
            self.assertEqual(
                loaded_project.get("timeline_path"),
                timeline_path.resolve().as_posix(),
            )


if __name__ == "__main__":
    unittest.main()
