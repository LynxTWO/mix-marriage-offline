import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main

try:
    import reportlab  # noqa: F401
except ImportError:
    reportlab = None


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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_report(
    *,
    report_id: str,
    profile_id: str,
    preset_id: str,
    meters: str,
    translation_risk: str,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
        "project_id": "PROJECT.CLI.COMPARE.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": [],
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": profile_id,
            "preset_id": preset_id,
            "meters": meters,
        },
        "downmix_qa": {
            "src_path": "src.wav",
            "ref_path": "ref.wav",
            "issues": [],
            "measurements": [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": 0.1,
                    "unit_id": "UNIT.CORRELATION",
                }
            ],
            "log": "{}",
        },
        "mix_complexity": {
            "density_mean": 2.4,
            "density_peak": 4,
            "density_timeline": [],
            "top_masking_pairs": [],
            "top_masking_pairs_count": 3,
            "sample_rate_hz": 48000,
            "included_stem_ids": [],
            "skipped_stem_ids": [],
            "density": {},
            "masking_risk": {},
        },
        "vibe_signals": {
            "density_level": "medium",
            "masking_level": "medium",
            "translation_risk": translation_risk,
            "notes": [],
        },
    }


def _write_manifest(path: Path, *, output_format: str) -> None:
    _write_json(
        path,
        {
            "renderer_manifests": [
                {
                    "renderer_id": "PLUGIN.RENDERER.SAFE",
                    "outputs": [{"format": output_format}],
                }
            ]
        },
    )


class TestCliCompare(unittest.TestCase):
    def test_compare_cli_accepts_dir_or_report_path_and_writes_json(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "compare_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            out_a = temp_path / "variant_a"
            out_b = temp_path / "variant_b"
            report_a_path = out_a / "report.json"
            report_b_path = out_b / "report.json"
            compare_path = temp_path / "compare_report.json"

            _write_json(
                report_a_path,
                _build_report(
                    report_id="REPORT.CLI.COMPARE.A",
                    profile_id="PROFILE.ASSIST",
                    preset_id="PRESET.SAFE_CLEANUP",
                    meters="truth",
                    translation_risk="low",
                ),
            )
            _write_json(
                report_b_path,
                _build_report(
                    report_id="REPORT.CLI.COMPARE.B",
                    profile_id="PROFILE.FULL_SEND",
                    preset_id="PRESET.VIBE.BRIGHT_AIRY",
                    meters="basic",
                    translation_risk="high",
                ),
            )
            _write_manifest(out_a / "render_manifest.json", output_format="wav")
            _write_manifest(out_b / "apply_manifest.json", output_format="flac")

            exit_code = main(
                [
                    "compare",
                    "--a",
                    str(out_a),
                    "--b",
                    str(report_b_path),
                    "--out",
                    str(compare_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(compare_path.exists())

            payload = json.loads(compare_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertEqual(payload["a"]["label"], "variant_a")
            self.assertEqual(payload["b"]["label"], "variant_b")
            self.assertEqual(payload["diffs"]["output_formats"]["a"], ["wav"])
            self.assertEqual(payload["diffs"]["output_formats"]["b"], ["flac"])
            self.assertIsInstance(payload.get("notes"), list)
            self.assertIsInstance(payload.get("warnings"), list)

    def test_compare_cli_pdf_export_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            out_a = temp_path / "variant_a"
            out_b = temp_path / "variant_b"
            report_a_path = out_a / "report.json"
            report_b_path = out_b / "report.json"
            compare_path = temp_path / "compare_report.json"
            compare_pdf_path = temp_path / "compare_report.pdf"

            _write_json(
                report_a_path,
                _build_report(
                    report_id="REPORT.CLI.COMPARE.PDF.A",
                    profile_id="PROFILE.ASSIST",
                    preset_id="PRESET.SAFE_CLEANUP",
                    meters="truth",
                    translation_risk="low",
                ),
            )
            _write_json(
                report_b_path,
                _build_report(
                    report_id="REPORT.CLI.COMPARE.PDF.B",
                    profile_id="PROFILE.FULL_SEND",
                    preset_id="PRESET.VIBE.WIDE_CINEMATIC",
                    meters="truth",
                    translation_risk="medium",
                ),
            )
            _write_manifest(out_a / "render_manifest.json", output_format="wav")
            _write_manifest(out_b / "apply_manifest.json", output_format="flac")

            exit_code = main(
                [
                    "compare",
                    "--a",
                    str(out_a),
                    "--b",
                    str(out_b),
                    "--out",
                    str(compare_path),
                    "--pdf",
                    str(compare_pdf_path),
                ]
            )

            if reportlab is None:
                self.assertEqual(exit_code, 2)
                self.assertTrue(compare_path.exists())
                self.assertFalse(compare_pdf_path.exists())
            else:
                self.assertEqual(exit_code, 0)
                self.assertTrue(compare_path.exists())
                self.assertTrue(compare_pdf_path.exists())
                self.assertGreater(compare_pdf_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
