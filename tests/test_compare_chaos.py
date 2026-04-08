from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mmo.core.compare import build_compare_report, load_report_from_path_or_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _report(*, report_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_id": report_id,
        "project_id": "PROJECT.CHAOS.TEST",
        "generated_at": "2000-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        "session": {"stems": []},
        "issues": [],
        "recommendations": [],
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": "PROFILE.ASSIST",
            "preset_id": "PRESET.SAFE_CLEANUP",
            "meters": "truth",
            "render": {"output_formats": ["wav"]},
        },
        "downmix_qa": {
            "src_path": "src.wav",
            "ref_path": "ref.wav",
            "issues": [],
            "measurements": [
                {
                    "evidence_id": "EVID.DOWNMIX.QA.LUFS_DELTA",
                    "value": -0.5,
                    "unit_id": "UNIT.LUFS",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
                    "value": 0.2,
                    "unit_id": "UNIT.DBTP",
                },
                {
                    "evidence_id": "EVID.DOWNMIX.QA.CORR_DELTA",
                    "value": -0.01,
                    "unit_id": "UNIT.CORRELATION",
                },
            ],
            "log": "{}",
        },
        "mix_complexity": {
            "density_mean": 2.0,
            "density_peak": 3,
            "density_timeline": [],
            "top_masking_pairs": [],
            "top_masking_pairs_count": 1,
            "sample_rate_hz": 48000,
            "included_stem_ids": [],
            "skipped_stem_ids": [],
            "density": {},
            "masking_risk": {},
        },
        "vibe_signals": {
            "density_level": "medium",
            "masking_level": "medium",
            "translation_risk": "low",
            "notes": [],
        },
    }


def _write_render_qa(path: Path, *, integrated_lufs: float, rms_dbfs: float) -> None:
    _write_json(
        path,
        {
            "jobs": [
                {
                    "job_id": "JOB.CHAOS.TEST",
                    "outputs": [
                        {
                            "path": "render/mix.wav",
                            "metrics": {
                                "integrated_lufs": integrated_lufs,
                                "rms_dbfs": rms_dbfs,
                            },
                        }
                    ],
                }
            ]
        },
    )


class TestCompareChaos(unittest.TestCase):
    def test_directory_with_non_json_report_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "report.json").write_text("not json\n", encoding="utf-8")

            with self.assertRaises(ValueError) as exc_info:
                load_report_from_path_or_dir(root)

        message = str(exc_info.exception)
        self.assertIn("not valid json", message.lower())
        self.assertIn("report", message.lower())

    def test_directory_with_objectless_report_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "report.json").write_text("[]\n", encoding="utf-8")

            with self.assertRaises(ValueError) as exc_info:
                load_report_from_path_or_dir(root)

        message = str(exc_info.exception)
        self.assertIn("must be an object", message.lower())

    def test_report_path_that_is_actually_directory_explains_shape_problem(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bogus = Path(temp_dir) / "report.json"
            bogus.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(ValueError) as exc_info:
                load_report_from_path_or_dir(bogus)

        message = str(exc_info.exception)
        self.assertIn("expected a `report.json` file", message.lower())

    def test_build_compare_report_marks_loudness_match_unavailable_when_render_qa_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "A" / "report.json"
            b_path = root / "B" / "report.json"
            _write_json(a_path, _report(report_id="REPORT.A"))
            _write_json(b_path, _report(report_id="REPORT.B"))

            report_a, resolved_a = load_report_from_path_or_dir(a_path)
            report_b, resolved_b = load_report_from_path_or_dir(b_path)
            payload = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

        self.assertEqual(payload["loudness_match"]["status"], "unavailable")
        self.assertFalse(payload["loudness_match"]["enabled_by_default"])
        self.assertTrue(
            any("fair-listen compensation was unavailable" in item.lower() for item in payload["warnings"])
        )

    def test_build_compare_report_handles_partial_render_qa_without_fake_precision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "A" / "report.json"
            b_path = root / "B" / "report.json"
            _write_json(a_path, _report(report_id="REPORT.A"))
            _write_json(b_path, _report(report_id="REPORT.B"))
            _write_render_qa(a_path.parent / "render_qa.json", integrated_lufs=-14.0, rms_dbfs=-10.0)

            report_a, resolved_a = load_report_from_path_or_dir(a_path)
            report_b, resolved_b = load_report_from_path_or_dir(b_path)
            payload = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

        loudness = payload["loudness_match"]
        self.assertEqual(loudness["status"], "unavailable")
        self.assertIsNone(loudness["measurement_b"])
        self.assertEqual(loudness["compensation_db"], 0.0)

    def test_build_compare_report_uses_folder_name_when_report_stem_is_generic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            variant = root / "messy human export"
            report_path = variant / "report.json"
            _write_json(report_path, _report(report_id="REPORT.FOLDER.LABEL"))

            _, resolved = load_report_from_path_or_dir(report_path)
            payload = build_compare_report(
                _report(report_id="REPORT.FOLDER.LABEL.A"),
                _report(report_id="REPORT.FOLDER.LABEL.B"),
                label_a=variant.name,
                label_b="other",
                report_path_a=resolved,
                report_path_b=resolved,
            )

        self.assertEqual(payload["a"]["label"], "messy human export")

    def test_translation_risk_increase_adds_warning(self) -> None:
        def _report_with_risk(risk: str) -> dict:
            r = _report(report_id=f"REPORT.RISK.{risk.upper()}")
            r["vibe_signals"]["translation_risk"] = risk
            return r

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "A" / "report.json"
            b_path = root / "B" / "report.json"
            _write_json(a_path, _report_with_risk("low"))
            _write_json(b_path, _report_with_risk("high"))

            report_a, resolved_a = load_report_from_path_or_dir(a_path)
            report_b, resolved_b = load_report_from_path_or_dir(b_path)
            payload = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

        self.assertTrue(
            any("translation risk" in w.lower() for w in payload["warnings"]),
            f"Expected translation risk warning, got: {payload['warnings']}",
        )
        self.assertTrue(
            any("upward" in n.lower() for n in payload["notes"]),
            f"Expected upward note, got: {payload['notes']}",
        )

    def test_more_extreme_recs_in_b_adds_warning(self) -> None:
        def _report_with_extreme_recs(count: int) -> dict:
            r = _report(report_id=f"REPORT.EXTREME.{count}")
            r["recommendations"] = [
                {"recommendation_id": f"REC.{i:03d}", "extreme": True}
                for i in range(count)
            ]
            return r

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "A" / "report.json"
            b_path = root / "B" / "report.json"
            _write_json(a_path, _report_with_extreme_recs(0))
            _write_json(b_path, _report_with_extreme_recs(3))

            report_a, resolved_a = load_report_from_path_or_dir(a_path)
            report_b, resolved_b = load_report_from_path_or_dir(b_path)
            payload = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

        self.assertTrue(
            any("extreme" in w.lower() for w in payload["warnings"]),
            f"Expected extreme rec warning, got: {payload['warnings']}",
        )
        self.assertTrue(
            any("extreme recommendation count" in n.lower() for n in payload["notes"]),
            f"Expected extreme count note, got: {payload['notes']}",
        )

    def test_translation_risk_decrease_noted_without_warning(self) -> None:
        def _report_with_risk(risk: str) -> dict:
            r = _report(report_id=f"REPORT.RISK.{risk.upper()}")
            r["vibe_signals"]["translation_risk"] = risk
            return r

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "A" / "report.json"
            b_path = root / "B" / "report.json"
            _write_json(a_path, _report_with_risk("high"))
            _write_json(b_path, _report_with_risk("low"))

            report_a, resolved_a = load_report_from_path_or_dir(a_path)
            report_b, resolved_b = load_report_from_path_or_dir(b_path)
            payload = build_compare_report(
                report_a,
                report_b,
                label_a="A",
                label_b="B",
                report_path_a=resolved_a,
                report_path_b=resolved_b,
            )

        # A decrease should appear in notes, not warnings
        self.assertTrue(
            any("downward" in n.lower() for n in payload["notes"]),
            f"Expected downward note, got: {payload['notes']}",
        )
        self.assertFalse(
            any("translation risk" in w.lower() for w in payload["warnings"]),
            f"Unexpected translation risk warning on decrease: {payload['warnings']}",
        )


if __name__ == "__main__":
    unittest.main()
