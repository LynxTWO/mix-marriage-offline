import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable
from unittest import mock

from mmo.cli import _run_ui_workflow


def _input_provider(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)

    def _provider(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:  # pragma: no cover - defensive test surface
            raise AssertionError(f"Unexpected prompt: {prompt}") from exc

    return _provider


class TestTuiUi(unittest.TestCase):
    def test_ui_single_mode_uses_selected_preset_and_writes_outputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        tools_dir = repo_root / "tools"
        presets_dir = repo_root / "presets"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            stems_dir.mkdir(parents=True, exist_ok=True)

            def _fake_run_analyze(*args: object, **kwargs: object) -> int:
                del kwargs
                out_report_path = args[2]
                if not isinstance(out_report_path, Path):
                    return 1
                out_report_path.parent.mkdir(parents=True, exist_ok=True)
                out_report_path.write_text(
                    json.dumps(
                        {
                            "vibe_signals": {
                                "density_level": "medium",
                                "masking_level": "low",
                                "translation_risk": "medium",
                            }
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0

            def _fake_run_one_shot_workflow(**kwargs: object) -> int:
                out_path = kwargs.get("out_dir")
                preset_id = kwargs.get("preset_id")
                deliverables_index = kwargs.get("deliverables_index")
                if not isinstance(out_path, Path):
                    return 1
                out_path.mkdir(parents=True, exist_ok=True)
                (out_path / "ui_bundle.json").write_text("{}\n", encoding="utf-8")
                if deliverables_index is True:
                    (out_path / "deliverables_index.json").write_text(
                        "{}\n",
                        encoding="utf-8",
                    )
                (out_path / "report.json").write_text(
                    json.dumps(
                        {
                            "run_config": {
                                "preset_id": preset_id,
                                "profile_id": "PROFILE.ASSIST",
                            }
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0

            with mock.patch("mmo.cli_commands._workflows._run_analyze", side_effect=_fake_run_analyze):
                with mock.patch(
                    "mmo.cli_commands._workflows._run_one_shot_workflow",
                    side_effect=_fake_run_one_shot_workflow,
                ) as patched_single_run:
                    exit_code = _run_ui_workflow(
                        repo_root=repo_root,
                        tools_dir=tools_dir,
                        presets_dir=presets_dir,
                        stems_dir=stems_dir,
                        out_dir=out_dir,
                        project_path=None,
                        nerd=False,
                        input_provider=_input_provider(["3", "2", "1", "n", ""]),
                        output=lambda _line: None,
                    )

            self.assertEqual(exit_code, 0)
            self.assertTrue(patched_single_run.called)
            self.assertEqual(
                patched_single_run.call_args.kwargs["preset_id"],
                "PRESET.SAFE_CLEANUP",
            )
            self.assertTrue(patched_single_run.call_args.kwargs["bundle"])
            self.assertTrue(patched_single_run.call_args.kwargs["deliverables_index"])
            self.assertTrue((out_dir / "ui_bundle.json").exists())
            self.assertTrue((out_dir / "deliverables_index.json").exists())

    def test_ui_variants_mode_toggles_listen_pack_and_deliverables(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        tools_dir = repo_root / "tools"
        presets_dir = repo_root / "presets"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            out_dir = temp_path / "out"
            stems_dir.mkdir(parents=True, exist_ok=True)

            def _fake_run_analyze(*args: object, **kwargs: object) -> int:
                del kwargs
                out_report_path = args[2]
                if not isinstance(out_report_path, Path):
                    return 1
                out_report_path.parent.mkdir(parents=True, exist_ok=True)
                out_report_path.write_text(
                    json.dumps(
                        {
                            "vibe_signals": {
                                "density_level": "medium",
                                "masking_level": "low",
                                "translation_risk": "medium",
                            }
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0

            def _fake_run_variants_workflow(**kwargs: object) -> int:
                out_path = kwargs.get("out_dir")
                if not isinstance(out_path, Path):
                    return 1
                out_path.mkdir(parents=True, exist_ok=True)

                variant_dir = out_path / "VARIANT.001__safe_cleanup"
                variant_dir.mkdir(parents=True, exist_ok=True)
                bundle_path = variant_dir / "ui_bundle.json"
                bundle_path.write_text("{}\n", encoding="utf-8")
                report_path = variant_dir / "report.json"
                report_path.write_text("{}\n", encoding="utf-8")

                result_payload = {
                    "schema_version": "0.1.0",
                    "plan": {
                        "schema_version": "0.1.0",
                        "stems_dir": stems_dir.resolve().as_posix(),
                        "base_run_config": {"schema_version": "0.1.0"},
                        "variants": [],
                    },
                    "results": [
                        {
                            "variant_id": "VARIANT.001",
                            "out_dir": variant_dir.resolve().as_posix(),
                            "report_path": report_path.resolve().as_posix(),
                            "bundle_path": bundle_path.resolve().as_posix(),
                            "ok": True,
                            "errors": [],
                        }
                    ],
                }
                (out_path / "variant_result.json").write_text(
                    json.dumps(result_payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if kwargs.get("deliverables_index") is True:
                    (out_path / "deliverables_index.json").write_text(
                        "{}\n",
                        encoding="utf-8",
                    )
                if kwargs.get("listen_pack") is True:
                    (out_path / "listen_pack.json").write_text("{}\n", encoding="utf-8")
                return 0

            with mock.patch("mmo.cli_commands._workflows._run_analyze", side_effect=_fake_run_analyze):
                with mock.patch(
                    "mmo.cli_commands._workflows._run_variants_workflow",
                    side_effect=_fake_run_variants_workflow,
                ) as patched_variants_run:
                    exit_code = _run_ui_workflow(
                        repo_root=repo_root,
                        tools_dir=tools_dir,
                        presets_dir=presets_dir,
                        stems_dir=stems_dir,
                        out_dir=out_dir,
                        project_path=None,
                        nerd=False,
                        input_provider=_input_provider(["3", "2", "1", "y", "8", ""]),
                        output=lambda _line: None,
                    )

            self.assertEqual(exit_code, 0)
            self.assertTrue(patched_variants_run.called)
            self.assertEqual(
                patched_variants_run.call_args.kwargs["preset_values"],
                ["PRESET.SAFE_CLEANUP"],
            )
            self.assertTrue(patched_variants_run.call_args.kwargs["bundle"])
            self.assertTrue(patched_variants_run.call_args.kwargs["deliverables_index"])
            self.assertTrue(patched_variants_run.call_args.kwargs["listen_pack"])
            self.assertTrue((out_dir / "VARIANT.001__safe_cleanup" / "ui_bundle.json").exists())
            self.assertTrue((out_dir / "deliverables_index.json").exists())
            self.assertTrue((out_dir / "listen_pack.json").exists())


if __name__ == "__main__":
    unittest.main()
