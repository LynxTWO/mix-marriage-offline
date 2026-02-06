import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.deliverables_index import (
    build_deliverables_index_single,
    build_deliverables_index_variants,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


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


def _report_payload(*, preset_id: str, profile_id: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.DELIVERABLES.INDEX.TEST.001",
        "generated_at": "2000-01-01T00:00:00Z",
        "run_config": {
            "schema_version": "0.1.0",
            "preset_id": preset_id,
            "profile_id": profile_id,
        },
        "session": {"stems_dir": "/tmp/stems", "stems": []},
        "issues": [],
        "recommendations": [],
    }


def _manifest_payload(deliverables: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.DELIVERABLES.INDEX.TEST.001",
        "renderer_manifests": [
            {
                "renderer_id": "PLUGIN.RENDERER.GAIN_TRIM",
                "outputs": outputs,
                "skipped": [],
            }
        ],
        "deliverables": deliverables,
    }


class TestDeliverablesIndex(unittest.TestCase):
    def test_deliverables_index_cli_single_mode_discovers_known_files(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "deliverables_index.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "single_out"
            report_path = out_dir / "report.json"
            render_manifest_path = out_dir / "render_manifest.json"
            out_path = Path(temp_dir) / "deliverables_index.json"

            _write_json(
                report_path,
                _report_payload(
                    preset_id="PRESET.SAFE_CLEANUP",
                    profile_id="PROFILE.ASSIST",
                ),
            )
            _write_json(out_dir / "ui_bundle.json", {"schema_version": "0.1.0"})
            _write_text(out_dir / "report.pdf", "pdf")
            _write_text(out_dir / "recall.csv", "csv")
            _write_json(out_dir / "listen_pack.json", {"schema_version": "0.1.0", "entries": []})
            _write_json(
                render_manifest_path,
                _manifest_payload(
                    deliverables=[
                        {
                            "deliverable_id": "DELIV.A",
                            "label": "a",
                            "formats": ["wav"],
                            "output_ids": ["OUT.A.WAV"],
                        }
                    ],
                    outputs=[
                        {
                            "output_id": "OUT.A.WAV",
                            "file_path": "render/a.wav",
                            "format": "wav",
                            "sha256": "a" * 16,
                        }
                    ],
                ),
            )

            exit_code = main(
                [
                    "deliverables",
                    "index",
                    "--out-dir",
                    str(out_dir),
                    "--out",
                    str(out_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(payload.get("mode"), "single")

    def test_build_single_deliverables_index_schema_valid_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "deliverables_index.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "single_out"
            report_path = out_dir / "report.json"
            bundle_path = out_dir / "ui_bundle.json"
            pdf_path = out_dir / "report.pdf"
            csv_path = out_dir / "recall.csv"
            render_manifest_path = out_dir / "render_manifest.json"
            apply_manifest_path = out_dir / "apply_manifest.json"
            listen_pack_path = out_dir / "listen_pack.json"

            _write_json(
                report_path,
                _report_payload(
                    preset_id="PRESET.SAFE_CLEANUP",
                    profile_id="PROFILE.ASSIST",
                ),
            )
            _write_json(bundle_path, {"schema_version": "0.1.0"})
            _write_text(pdf_path, "pdf")
            _write_text(csv_path, "csv")
            _write_json(listen_pack_path, {"schema_version": "0.1.0", "entries": []})

            _write_json(
                render_manifest_path,
                _manifest_payload(
                    deliverables=[
                        {
                            "deliverable_id": "DELIV.Z",
                            "label": "z",
                            "formats": ["wav"],
                            "output_ids": ["OUT.Z.WAV"],
                        },
                        {
                            "deliverable_id": "DELIV.A",
                            "label": "a",
                            "target_layout_id": "LAYOUT.2_0",
                            "channel_count": 2,
                            "formats": ["wav", "flac"],
                            "output_ids": ["OUT.A.WAV", "OUT.A.FLAC"],
                        },
                    ],
                    outputs=[
                        {
                            "output_id": "OUT.A.WAV",
                            "file_path": "render/a.wav",
                            "format": "wav",
                            "sha256": "a" * 16,
                        },
                        {
                            "output_id": "OUT.Z.WAV",
                            "file_path": "render/z.wav",
                            "format": "wav",
                            "sha256": "z" * 16,
                        },
                        {
                            "output_id": "OUT.A.FLAC",
                            "file_path": "render/a.flac",
                            "format": "flac",
                            "sha256": "b" * 16,
                        },
                    ],
                ),
            )
            _write_json(
                apply_manifest_path,
                _manifest_payload(
                    deliverables=[
                        {
                            "deliverable_id": "DELIV.B",
                            "label": "b",
                            "formats": ["wav"],
                            "output_ids": ["OUT.B.WAV"],
                        },
                        {
                            "deliverable_id": "DELIV.A",
                            "label": "a apply",
                            "formats": ["wav"],
                            "output_ids": ["OUT.A.APPLY.WAV"],
                        },
                    ],
                    outputs=[
                        {
                            "output_id": "OUT.B.WAV",
                            "file_path": "apply/b.wav",
                            "format": "wav",
                            "sha256": "c" * 16,
                        },
                        {
                            "output_id": "OUT.A.APPLY.WAV",
                            "file_path": "apply/a.wav",
                            "format": "wav",
                            "sha256": "d" * 16,
                        },
                    ],
                ),
            )

            first = build_deliverables_index_single(
                out_dir=out_dir,
                report_path=report_path,
                apply_manifest_path=apply_manifest_path,
                render_manifest_path=render_manifest_path,
                bundle_path=bundle_path,
                pdf_path=pdf_path,
                csv_path=csv_path,
            )
            second = build_deliverables_index_single(
                out_dir=out_dir,
                report_path=report_path,
                apply_manifest_path=apply_manifest_path,
                render_manifest_path=render_manifest_path,
                bundle_path=bundle_path,
                pdf_path=pdf_path,
                csv_path=csv_path,
            )

            validator.validate(first)
            self.assertEqual(first, second)
            self.assertEqual(first.get("mode"), "single")
            entries = first.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list) or not entries:
                return

            entry = entries[0]
            self.assertEqual(entry.get("entry_id"), "ENTRY.SINGLE")
            self.assertEqual(entry.get("preset_id"), "PRESET.SAFE_CLEANUP")
            self.assertEqual(entry.get("profile_id"), "PROFILE.ASSIST")

            deliverables = entry.get("deliverables")
            self.assertIsInstance(deliverables, list)
            if not isinstance(deliverables, list):
                return
            self.assertEqual(
                [item.get("deliverable_id") for item in deliverables],
                ["DELIV.A", "DELIV.B", "DELIV.Z"],
            )

            first_deliverable = deliverables[0]
            files = first_deliverable.get("files")
            self.assertIsInstance(files, list)
            if not isinstance(files, list):
                return
            self.assertEqual(
                [(item.get("format"), item.get("path")) for item in files],
                [
                    ("flac", "render/a.flac"),
                    ("wav", "apply/a.wav"),
                    ("wav", "render/a.wav"),
                ],
            )

            artifacts = entry.get("artifacts")
            self.assertIsInstance(artifacts, dict)
            if not isinstance(artifacts, dict):
                return
            self.assertIn("listen_pack", artifacts)

    def test_build_variants_deliverables_index_schema_valid_and_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "deliverables_index.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            root_out_dir = Path(temp_dir) / "variants_out"
            variant_one_dir = root_out_dir / "VARIANT.001__safe"
            variant_two_dir = root_out_dir / "VARIANT.002__warm"

            variant_one_report = variant_one_dir / "report.json"
            variant_two_report = variant_two_dir / "report.json"
            variant_one_render_manifest = variant_one_dir / "render_manifest.json"
            variant_two_apply_manifest = variant_two_dir / "apply_manifest.json"
            listen_pack_path = root_out_dir / "listen_pack.json"

            _write_json(
                variant_one_report,
                _report_payload(
                    preset_id="PRESET.SAFE_CLEANUP",
                    profile_id="PROFILE.ASSIST",
                ),
            )
            _write_json(
                variant_two_report,
                _report_payload(
                    preset_id="PRESET.VIBE.WARM_INTIMATE",
                    profile_id="PROFILE.ASSIST",
                ),
            )
            _write_json(listen_pack_path, {"schema_version": "0.1.0", "entries": []})

            _write_json(
                variant_one_render_manifest,
                _manifest_payload(
                    deliverables=[
                        {
                            "deliverable_id": "DELIV.B",
                            "label": "b",
                            "formats": ["wav"],
                            "output_ids": ["OUT.B.WAV"],
                        },
                        {
                            "deliverable_id": "DELIV.A",
                            "label": "a",
                            "formats": ["flac", "wav"],
                            "output_ids": ["OUT.A.WAV", "OUT.A.FLAC"],
                        },
                    ],
                    outputs=[
                        {
                            "output_id": "OUT.A.WAV",
                            "file_path": "render/a.wav",
                            "format": "wav",
                            "sha256": "e" * 16,
                        },
                        {
                            "output_id": "OUT.B.WAV",
                            "file_path": "render/b.wav",
                            "format": "wav",
                            "sha256": "f" * 16,
                        },
                        {
                            "output_id": "OUT.A.FLAC",
                            "file_path": "render/a.flac",
                            "format": "flac",
                            "sha256": "g" * 16,
                        },
                    ],
                ),
            )
            _write_json(
                variant_two_apply_manifest,
                _manifest_payload(
                    deliverables=[
                        {
                            "deliverable_id": "DELIV.C",
                            "label": "c",
                            "formats": ["wav"],
                            "output_ids": ["OUT.C.WAV"],
                        }
                    ],
                    outputs=[
                        {
                            "output_id": "OUT.C.WAV",
                            "file_path": "apply/c.wav",
                            "format": "wav",
                            "sha256": "h" * 16,
                        }
                    ],
                ),
            )

            variant_result = {
                "schema_version": "0.1.0",
                "plan": {
                    "schema_version": "0.1.0",
                    "stems_dir": "/tmp/stems",
                    "base_run_config": {"schema_version": "0.1.0"},
                    "variants": [
                        {
                            "variant_id": "VARIANT.002",
                            "label": "Warm",
                            "preset_id": "PRESET.VIBE.WARM_INTIMATE",
                        },
                        {
                            "variant_id": "VARIANT.001",
                            "label": "Safe",
                            "preset_id": "PRESET.SAFE_CLEANUP",
                        },
                    ],
                },
                "results": [
                    {
                        "variant_id": "VARIANT.002",
                        "out_dir": variant_two_dir.resolve().as_posix(),
                        "report_path": variant_two_report.resolve().as_posix(),
                        "apply_manifest_path": variant_two_apply_manifest.resolve().as_posix(),
                        "ok": True,
                        "errors": [],
                    },
                    {
                        "variant_id": "VARIANT.001",
                        "out_dir": variant_one_dir.resolve().as_posix(),
                        "report_path": variant_one_report.resolve().as_posix(),
                        "render_manifest_path": variant_one_render_manifest.resolve().as_posix(),
                        "ok": True,
                        "errors": [],
                    },
                ],
            }

            first = build_deliverables_index_variants(
                root_out_dir=root_out_dir,
                variant_result=variant_result,
            )
            second = build_deliverables_index_variants(
                root_out_dir=root_out_dir,
                variant_result=variant_result,
            )

            validator.validate(first)
            self.assertEqual(first, second)
            self.assertEqual(first.get("mode"), "variants")
            entries = first.get("entries")
            self.assertIsInstance(entries, list)
            if not isinstance(entries, list):
                return

            self.assertEqual(
                [item.get("variant_id") for item in entries],
                ["VARIANT.001", "VARIANT.002"],
            )
            self.assertEqual(
                [item.get("entry_id") for item in entries],
                ["ENTRY.VARIANT.001", "ENTRY.VARIANT.002"],
            )

            variant_one_entry = entries[0]
            variant_one_deliverables = variant_one_entry.get("deliverables")
            self.assertIsInstance(variant_one_deliverables, list)
            if not isinstance(variant_one_deliverables, list):
                return
            self.assertEqual(
                [item.get("deliverable_id") for item in variant_one_deliverables],
                ["DELIV.A", "DELIV.B"],
            )

            files = variant_one_deliverables[0].get("files")
            self.assertIsInstance(files, list)
            if not isinstance(files, list):
                return
            self.assertEqual(
                [(item.get("format"), item.get("path")) for item in files],
                [("flac", "render/a.flac"), ("wav", "render/a.wav")],
            )

            artifacts = variant_one_entry.get("artifacts")
            self.assertIsInstance(artifacts, dict)
            if not isinstance(artifacts, dict):
                return
            self.assertIn("listen_pack", artifacts)


if __name__ == "__main__":
    unittest.main()
