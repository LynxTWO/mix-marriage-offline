import json
import tempfile
import unittest
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.compare import (
    build_compare_report,
    load_report_from_path_or_dir,
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


def _build_report(
    *,
    report_id: str,
    profile_id: str,
    preset_id: str,
    meters: str,
    output_formats: list[str],
    translation_risk: str,
    extreme_count: int,
    lufs_delta: float,
    true_peak_delta: float,
    corr_delta: float,
    density_mean: float,
    density_peak: int,
    masking_pairs_count: int,
) -> dict:
    recommendations = []
    for index in range(extreme_count):
        recommendations.append(
            {
                "recommendation_id": f"REC.EXTREME.{index + 1}",
                "action_id": "ACTION.UTILITY.GAIN",
                "risk": "medium",
                "requires_approval": False,
                "params": [],
                "extreme": True,
            }
        )

    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
        "project_id": "PROJECT.COMPARE.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": recommendations,
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": profile_id,
            "preset_id": preset_id,
            "meters": meters,
            "render": {"output_formats": output_formats},
        },
        "downmix_qa": {
            "src_path": "src.wav",
            "ref_path": "ref.wav",
            "issues": [],
            "measurements": [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": lufs_delta,
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": true_peak_delta,
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": corr_delta,
                    "unit_id": "UNIT.CORRELATION",
                },
            ],
            "log": "{}",
        },
        "mix_complexity": {
            "density_mean": density_mean,
            "density_peak": density_peak,
            "density_timeline": [],
            "top_masking_pairs": [],
            "top_masking_pairs_count": masking_pairs_count,
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class TestCompareCore(unittest.TestCase):
    def test_load_report_from_path_or_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_path = temp_path / "report.json"
            _write_json(
                report_path,
                _build_report(
                    report_id="REPORT.LOAD.TEST",
                    profile_id="PROFILE.ASSIST",
                    preset_id="PRESET.SAFE_CLEANUP",
                    meters="truth",
                    output_formats=["wav"],
                    translation_risk="low",
                    extreme_count=0,
                    lufs_delta=-0.3,
                    true_peak_delta=0.2,
                    corr_delta=-0.01,
                    density_mean=2.0,
                    density_peak=3,
                    masking_pairs_count=1,
                ),
            )

            from_dir, from_dir_path = load_report_from_path_or_dir(temp_path)
            from_file, from_file_path = load_report_from_path_or_dir(report_path)

            self.assertEqual(from_dir.get("report_id"), "REPORT.LOAD.TEST")
            self.assertEqual(from_file.get("report_id"), "REPORT.LOAD.TEST")
            self.assertEqual(from_dir_path, from_file_path)
            self.assertEqual(from_file_path, report_path.resolve())

    def test_build_compare_report_is_deterministic_and_schema_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "compare_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report_a_path = temp_path / "A" / "report.json"
            report_b_path = temp_path / "B" / "report.json"
            _write_json(
                report_a_path,
                _build_report(
                    report_id="REPORT.COMPARE.A",
                    profile_id="PROFILE.ASSIST",
                    preset_id="PRESET.SAFE_CLEANUP",
                    meters="truth",
                    output_formats=["wav"],
                    translation_risk="low",
                    extreme_count=0,
                    lufs_delta=-0.5,
                    true_peak_delta=0.2,
                    corr_delta=-0.01,
                    density_mean=2.0,
                    density_peak=3,
                    masking_pairs_count=2,
                ),
            )
            _write_json(
                report_b_path,
                _build_report(
                    report_id="REPORT.COMPARE.B",
                    profile_id="PROFILE.FULL_SEND",
                    preset_id="PRESET.VIBE.WARM_INTIMATE",
                    meters="basic",
                    output_formats=["wav", "flac"],
                    translation_risk="high",
                    extreme_count=2,
                    lufs_delta=-1.2,
                    true_peak_delta=0.7,
                    corr_delta=-0.2,
                    density_mean=3.3,
                    density_peak=5,
                    masking_pairs_count=6,
                ),
            )

            report_a, resolved_a = load_report_from_path_or_dir(report_a_path)
            report_b, resolved_b = load_report_from_path_or_dir(report_b_path)
            first = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )
            second = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

            self.assertEqual(first, second)
            validator.validate(first)
            self.assertEqual(first["diffs"]["profile_id"], {"a": "PROFILE.ASSIST", "b": "PROFILE.FULL_SEND"})
            self.assertEqual(first["diffs"]["preset_id"]["a"], "PRESET.SAFE_CLEANUP")
            self.assertEqual(first["diffs"]["preset_id"]["b"], "PRESET.VIBE.WARM_INTIMATE")
            self.assertEqual(first["diffs"]["meters"], {"a": "truth", "b": "basic"})
            self.assertEqual(first["diffs"]["output_formats"], {"a": ["wav"], "b": ["wav", "flac"]})
            self.assertAlmostEqual(
                first["diffs"]["metrics"]["downmix_qa"]["lufs_delta"]["delta"],
                -0.7,
            )
            self.assertAlmostEqual(
                first["diffs"]["metrics"]["mix_complexity"]["density_mean"]["delta"],
                1.3,
            )
            self.assertEqual(
                first["diffs"]["metrics"]["change_flags"]["translation_risk"],
                {"a": "low", "b": "high", "shift": 2},
            )
            warnings = first.get("warnings", [])
            self.assertTrue(
                any(
                    isinstance(item, str) and "Translation risk increased" in item
                    for item in warnings
                )
            )


if __name__ == "__main__":
    unittest.main()
