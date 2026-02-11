import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mmo.cli import main
from mmo.core.project_file import new_project, write_project
from mmo.core.render_targets import (
    list_render_targets,
    resolve_render_target_id as resolve_target_id_from_registry,
)
from mmo.core.scene_templates import list_scene_templates


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sample_scene_payload(*, stems_dir: Path) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.CLI.ERRORS.DETERMINISTIC",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [],
        "beds": [],
        "metadata": {},
    }


def _write_ambiguous_targets_registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                'schema_version: "0.1.0"',
                "targets:",
                "  - target_id: TARGET.ALPHA.2_0",
                "    label: Alpha",
                "    layout_id: LAYOUT.2_0",
                "    channel_order_ref: SMPTE",
                "    speaker_positions_ref: LAYOUT.2_0",
                "    aliases:",
                "      - Shared Alias",
                "    notes:",
                "      - Alpha fixture",
                "  - target_id: TARGET.BETA.2_0",
                "    label: Beta",
                "    layout_id: LAYOUT.2_0",
                "    channel_order_ref: SMPTE",
                "    speaker_positions_ref: LAYOUT.2_0",
                "    aliases:",
                "      - shared   alias",
                "    notes:",
                "      - Beta fixture",
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestCliErrorOutputDeterminism(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _assert_nonzero_and_deterministic(self, args: list[str]) -> tuple[str, str]:
        first_exit, first_stdout, first_stderr = self._run_main(args)
        second_exit, second_stdout, second_stderr = self._run_main(args)
        self.assertNotEqual(first_exit, 0)
        self.assertNotEqual(second_exit, 0)
        self.assertEqual(first_stdout, second_stdout)
        self.assertEqual(first_stderr, second_stderr)
        return first_stdout, first_stderr

    def _expected_unknown_template_message(
        self,
        *,
        repo_root: Path,
        unknown_ids: list[str],
    ) -> str:
        template_rows = list_scene_templates(repo_root / "ontology" / "scene_templates.yaml")
        available_ids = sorted(
            item.get("template_id")
            for item in template_rows
            if isinstance(item, dict) and isinstance(item.get("template_id"), str)
        )
        unknown_label = ", ".join(sorted({item.strip() for item in unknown_ids if item.strip()}))
        available_label = ", ".join(available_ids)
        if available_label:
            return f"Unknown template_id: {unknown_label}. Available templates: {available_label}"
        return f"Unknown template_id: {unknown_label}. No scene templates are available."

    def _expected_unknown_target_message(
        self,
        *,
        repo_root: Path,
        token: str,
    ) -> str:
        target_rows = list_render_targets(repo_root / "ontology" / "render_targets.yaml")
        available_ids = sorted(
            item.get("target_id")
            for item in target_rows
            if isinstance(item, dict) and isinstance(item.get("target_id"), str)
        )
        available_label = ", ".join(available_ids)
        if available_label:
            return f"Unknown render target token: {token}. Available targets: {available_label}"
        return f"Unknown render target token: {token}. No render targets are available."

    def test_scene_template_show_unknown_ids_error_is_stable(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        unknown_ids = ["TEMPLATE.SCENE.UNKNOWN.ZZZ", "TEMPLATE.SCENE.UNKNOWN.AAA"]
        _, stderr = self._assert_nonzero_and_deterministic(
            [
                "scene",
                "template",
                "show",
                *unknown_ids,
                "--format",
                "json",
            ]
        )
        self.assertEqual(
            stderr.strip(),
            self._expected_unknown_template_message(repo_root=repo_root, unknown_ids=unknown_ids),
        )

    def test_scene_template_apply_unknown_ids_error_is_stable(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        unknown_ids = ["TEMPLATE.SCENE.UNKNOWN.ZZZ", "TEMPLATE.SCENE.UNKNOWN.AAA"]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            scene_path = temp_path / "scene.json"
            out_path = temp_path / "scene.out.json"
            stems_dir.mkdir(parents=True, exist_ok=True)
            _write_json(scene_path, _sample_scene_payload(stems_dir=stems_dir))

            _, stderr = self._assert_nonzero_and_deterministic(
                [
                    "scene",
                    "template",
                    "apply",
                    *unknown_ids,
                    "--scene",
                    str(scene_path),
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(
                stderr.strip(),
                self._expected_unknown_template_message(
                    repo_root=repo_root,
                    unknown_ids=unknown_ids,
                ),
            )
            self.assertFalse(out_path.exists())

    def test_unknown_target_alias_error_is_stable_across_targets_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        unknown_token = "UNKNOWN_TARGET_ALIAS"
        expected_message = self._expected_unknown_target_message(
            repo_root=repo_root,
            token=unknown_token,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"
            write_project(project_path, new_project(stems_dir, notes=None))

            commands = [
                [
                    "render-plan",
                    "build",
                    "--scene",
                    str(temp_path / "scene.json"),
                    "--targets",
                    unknown_token,
                    "--out",
                    str(temp_path / "render_plan.json"),
                ],
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(temp_path / "run_out"),
                    "--render-many",
                    "--targets",
                    unknown_token,
                    "--cache",
                    "off",
                ],
                [
                    "project",
                    "run",
                    "--project",
                    str(project_path),
                    "--out",
                    str(temp_path / "project_out"),
                    "--render-many",
                    "--targets",
                    unknown_token,
                    "--cache",
                    "off",
                ],
            ]

            for command in commands:
                stdout, stderr = self._assert_nonzero_and_deterministic(command)
                self.assertEqual(stdout, "")
                self.assertEqual(stderr.strip(), expected_message)

    def test_ambiguous_target_alias_error_is_stable_across_targets_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            project_path = temp_path / ".mmo_project.json"
            write_project(project_path, new_project(stems_dir, notes=None))

            targets_path = temp_path / "render_targets.ambiguous.yaml"
            _write_ambiguous_targets_registry(targets_path)

            commands = [
                [
                    "render-plan",
                    "build",
                    "--scene",
                    str(temp_path / "scene.json"),
                    "--targets",
                    "shared alias",
                    "--out",
                    str(temp_path / "render_plan.json"),
                ],
                [
                    "run",
                    "--stems",
                    str(stems_dir),
                    "--out",
                    str(temp_path / "run_out"),
                    "--render-many",
                    "--targets",
                    "shared alias",
                    "--cache",
                    "off",
                ],
                [
                    "project",
                    "run",
                    "--project",
                    str(project_path),
                    "--out",
                    str(temp_path / "project_out"),
                    "--render-many",
                    "--targets",
                    "shared alias",
                    "--cache",
                    "off",
                ],
            ]

            def _resolve_from_local_registry(token: str, _: Path) -> str:
                return resolve_target_id_from_registry(token, targets_path)

            with mock.patch(
                "mmo.cli.resolve_render_target_id",
                side_effect=_resolve_from_local_registry,
            ):
                for command in commands:
                    stdout, stderr = self._assert_nonzero_and_deterministic(command)
                    self.assertEqual(stdout, "")
                    self.assertEqual(
                        stderr.strip(),
                        (
                            "Ambiguous render target token: shared alias. "
                            "Matching targets: TARGET.ALPHA.2_0, TARGET.BETA.2_0"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
