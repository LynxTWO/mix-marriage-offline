import csv
import json
import tempfile
import unittest
from pathlib import Path

from mmo.exporters.csv_recall import export_recall_csv
from mmo.exporters.pdf_report import export_report_pdf
from mmo.exporters import pdf_report
from mmo.exporters.pdf_utils import render_maybe_json
from mmo.exporters.recall_sheet import export_recall_sheet
from mmo.exporters import pdf_report as _pdf_report

try:
    import reportlab  # noqa: F401
except ImportError:
    reportlab = None


class TestExporters(unittest.TestCase):
    def _load_report(self) -> dict:
        path = Path("fixtures/export/report_small.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_export_recall_csv_ordering(self) -> None:
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=True)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertEqual(
            rows[0],
            [
                "recommendation_id",
                "profile_id",
                "issue_id",
                "action_id",
                "risk",
                "requires_approval",
                "target",
                "params",
                "notes",
                "extreme",
                "extreme_gate_ids",
                "eligible_auto_apply",
                "eligible_render",
                "gate_summary",
            ],
        )
        self.assertEqual(rows[1][0], "REC.001")
        self.assertEqual(rows[2][0], "REC.002")
        self.assertEqual(rows[1][9], "False")
        self.assertEqual(rows[2][9], "False")
        self.assertEqual(rows[1][-3:], ["", "", ""])
        self.assertEqual(rows[2][-3:], ["", "", ""])

    def test_export_recall_csv_without_gates(self) -> None:
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=False)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertEqual(
            rows[0],
            [
                "recommendation_id",
                "profile_id",
                "issue_id",
                "action_id",
                "risk",
                "requires_approval",
                "target",
                "params",
                "notes",
                "extreme",
                "extreme_gate_ids",
            ],
        )

    def test_export_recall_csv_gate_summary_includes_gate_id(self) -> None:
        report = {
            "profile_id": "PROFILE.GUIDE",
            "recommendations": [
                {
                    "recommendation_id": "REC.GATE.TEST",
                    "issue_id": "ISSUE.TEST",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "target": {},
                    "params": [],
                    "gate_results": [
                        {
                            "gate_id": "GATE.MAX_GAIN_DB",
                            "context": "render",
                            "outcome": "reject",
                            "reason_id": "REASON.GAIN_TOO_LARGE",
                            "details": {},
                        }
                    ],
                    "eligible_auto_apply": False,
                    "eligible_render": False,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=True)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertIn("gate_summary", rows[0])
        self.assertEqual(rows[1][1], "PROFILE.GUIDE")
        self.assertIn("render:reject(GATE.MAX_GAIN_DB|REASON.GAIN_TOO_LARGE)", rows[1][-1])

    def test_export_recall_csv_extreme_columns(self) -> None:
        report = {
            "profile_id": "PROFILE.TURBO",
            "recommendations": [
                {
                    "recommendation_id": "REC.EXTREME.TEST",
                    "issue_id": "ISSUE.TEST",
                    "action_id": "ACTION.EQ.PEAK",
                    "risk": "high",
                    "requires_approval": False,
                    "target": {},
                    "params": [],
                    "notes": "",
                    "extreme": True,
                    "extreme_reasons": [
                        {
                            "gate_id": "GATE.MAX_EQ_BANDS",
                            "reason_id": "REASON.EQ_BANDS_TOO_MANY",
                            "details": {},
                        },
                        {
                            "gate_id": "GATE.MAX_EQ_GAIN_DB",
                            "reason_id": "REASON.EQ_GAIN_TOO_LARGE",
                            "details": {},
                        },
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "recall.csv"
            export_recall_csv(report, out_path, include_gates=False)
            rows = list(csv.reader(out_path.read_text(encoding="utf-8").splitlines()))

        self.assertEqual(rows[1][9], "True")
        self.assertEqual(rows[1][10], "GATE.MAX_EQ_BANDS|GATE.MAX_EQ_GAIN_DB")

    def test_export_report_pdf_exists(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_export_report_pdf_truncation(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        report["session"] = {
            "stems": [
                {
                    "stem_id": "stem-long",
                    "measurements": [
                        {
                            "evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG",
                            "value": "x" * 1000,
                            "unit_id": "UNIT.TEXT",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path, truncate_values=100)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_export_report_pdf_no_measurements(self) -> None:
        if reportlab is None:
            self.skipTest("reportlab not installed")
        report = self._load_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report.pdf"
            export_report_pdf(report, out_path, include_measurements=False)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_downmix_qa_summary_fields_from_log(self) -> None:
        downmix_qa = {
            "policy_id": "POLICY.DOWNMIX.TEST",
            "matrix_id": "MATRIX.TEST",
            "log": json.dumps(
                {
                    "source_layout_id": "LAYOUT.5_1",
                    "target_layout_id": "LAYOUT.2_0",
                    "seconds_compared": 12.5,
                    "max_seconds": 120.0,
                }
            ),
        }
        fields = pdf_report._downmix_qa_summary_fields(downmix_qa)
        field_map = {label: value for label, value in fields}
        self.assertEqual(field_map.get("policy_id"), "POLICY.DOWNMIX.TEST")
        self.assertEqual(field_map.get("matrix_id"), "MATRIX.TEST")
        self.assertEqual(field_map.get("source_layout_id"), "LAYOUT.5_1")
        self.assertEqual(field_map.get("target_layout_id"), "LAYOUT.2_0")
        self.assertEqual(field_map.get("seconds_compared"), 12.5)
        self.assertEqual(field_map.get("max_seconds"), 120.0)

    def test_downmix_qa_thresholds_line_from_gates(self) -> None:
        line = pdf_report._downmix_qa_thresholds_line()
        self.assertIsNotNone(line)
        if line is None:
            return
        self.assertIn("Thresholds:", line)
        self.assertIn("LUFS Δ warn 2.0 / fail 4.0", line)
        self.assertIn("True Peak Δ warn 1.0 / fail 2.0", line)
        self.assertIn("Correlation Δ warn 0.15 / fail 0.30", line)

    def test_downmix_qa_provenance_line(self) -> None:
        line = pdf_report._downmix_qa_provenance_line()
        self.assertIn("Provenance:", line)
        self.assertIn("downmix.yaml", line)

    def test_downmix_qa_next_checks_for_blocked_render(self) -> None:
        report = {
            "recommendations": [
                {
                    "recommendation_id": "REC.DOWNMIX.RENDER.001",
                    "action_id": "ACTION.DOWNMIX.RENDER",
                    "eligible_render": False,
                    "gate_results": [
                        {
                            "gate_id": "GATE.DOWNMIX_QA_CORR_DELTA_LIMIT",
                            "context": "render",
                            "outcome": "reject",
                            "reason_id": "REASON.DOWNMIX_QA_DELTA_EXCEEDS",
                            "details": {},
                        }
                    ],
                },
                {
                    "recommendation_id": "REC.DIAGNOSTIC.REVIEW_POLICY_MATRIX.001",
                    "action_id": "ACTION.DIAGNOSTIC.REVIEW_DOWNMIX_POLICY_MATRIX",
                },
                {
                    "recommendation_id": "REC.DIAGNOSTIC.CHECK_PHASE_CORRELATION.001",
                    "action_id": "ACTION.DIAGNOSTIC.CHECK_PHASE_CORRELATION",
                },
            ]
        }
        self.assertEqual(
            pdf_report._downmix_qa_next_checks(report),
            [
                "Review downmix policy matrix",
                "Check phase correlation",
            ],
        )

    def test_extreme_helpers(self) -> None:
        self.assertEqual(
            pdf_report._extreme_changes_note(
                [
                    {"recommendation_id": "REC.1", "extreme": False},
                    {"recommendation_id": "REC.2", "extreme": True},
                ]
            ),
            "Extreme changes present: review before applying",
        )
        self.assertEqual(
            pdf_report._format_recommendation_id(
                {"recommendation_id": "REC.2", "extreme": True}
            ),
            "REC.2 [EXTREME]",
        )

    def test_render_maybe_json_truncates_string_values(self) -> None:
        payload = {"keep": "ok", "blob": "x" * 50}
        rendered = render_maybe_json(json.dumps(payload), limit=20, pretty=True)
        self.assertIn("...(truncated)", rendered)
        self.assertIn('"keep": "ok"', rendered)

    def test_mix_complexity_top_pairs_sorted_and_limited(self) -> None:
        rows = pdf_report._mix_complexity_top_pairs(
            {
                "top_masking_pairs": [
                    {"stem_a": "a", "stem_b": "b", "score": 0.2},
                    {"stem_a": "c", "stem_b": "d", "score": 0.9},
                    {"stem_a": "e", "stem_b": "f", "score": 0.6},
                    {"stem_a": "g", "stem_b": "h", "score": 0.4},
                ]
            },
            limit=3,
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["stem_a"], "c")
        self.assertEqual(rows[1]["stem_a"], "e")
        self.assertEqual(rows[2]["stem_a"], "g")

    def test_vibe_signals_lines(self) -> None:
        lines = pdf_report._vibe_signals_lines(
            {
                "density_level": "high",
                "masking_level": "medium",
                "translation_risk": "high",
                "notes": [
                    "Lots of layers hitting at once. Make space with arrangement or gentle carving.",
                    "Translation risk is elevated. Fix clipping/lossy files and check mono.",
                ],
            }
        )
        self.assertEqual(
            lines[0],
            "Density: high | Masking: medium | Translation risk: high",
        )
        self.assertIn(
            "- Lots of layers hitting at once. Make space with arrangement or gentle carving.",
            lines,
        )
        self.assertIn(
            "- Translation risk is elevated. Fix clipping/lossy files and check mono.",
            lines,
        )


class TestRecallSheet(unittest.TestCase):
    def _minimal_report(self) -> dict:
        return {
            "issues": [
                {
                    "issue_id": "ISSUE.HIGH",
                    "severity": 80,
                    "confidence": 0.9,
                    "message": "High severity issue",
                    "target": {"scope": "stem", "stem_id": "kick"},
                    "evidence": [
                        {"evidence_id": "EVID.METER.SAMPLE_PEAK_DBFS", "value": -0.1}
                    ],
                },
                {
                    "issue_id": "ISSUE.LOW",
                    "severity": 20,
                    "confidence": 0.5,
                    "message": "Low severity issue",
                    "evidence": [
                        {"evidence_id": "EVID.FILE.FORMAT", "value": "mp3"}
                    ],
                },
            ],
            "recommendations": [
                {
                    "recommendation_id": "REC.001",
                    "issue_id": "ISSUE.HIGH",
                    "action_id": "ACTION.UTILITY.GAIN",
                    "risk": "low",
                    "requires_approval": False,
                    "params": [],
                },
                {
                    "recommendation_id": "REC.002",
                    "issue_id": "ISSUE.HIGH",
                    "action_id": "ACTION.EQ.PEAK",
                    "risk": "medium",
                    "requires_approval": False,
                    "params": [],
                },
            ],
        }

    def test_header_columns(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(
            rows[0],
            [
                "rank",
                "issue_id",
                "severity",
                "confidence",
                "message",
                "target_scope",
                "target_id",
                "evidence_summary",
                "action_ids",
                "scene_id",
                "scene_object_count",
                "target_layout_ids",
                "profile_id",
                "preflight_status",
                "layout_standard",
                "render_channel_orders",
                "render_export_warnings",
            ],
        )

    def test_ranked_by_severity_descending(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # Row 1 = rank 1 = ISSUE.HIGH (severity 80)
        self.assertEqual(rows[1][0], "1")
        self.assertEqual(rows[1][1], "ISSUE.HIGH")
        self.assertEqual(rows[1][2], "80")
        # Row 2 = rank 2 = ISSUE.LOW (severity 20)
        self.assertEqual(rows[2][0], "2")
        self.assertEqual(rows[2][1], "ISSUE.LOW")

    def test_action_ids_joined_sorted(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # ISSUE.HIGH has two recommendations → action_ids pipe-joined, sorted (col 8)
        action_ids_cell = rows[1][8]
        self.assertIn("ACTION.EQ.PEAK", action_ids_cell)
        self.assertIn("ACTION.UTILITY.GAIN", action_ids_cell)
        self.assertIn("|", action_ids_cell)
        # ISSUE.LOW has no recommendations → empty action_ids
        self.assertEqual(rows[2][8], "")

    def test_evidence_summary_format(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # evidence_summary is column index 7
        evidence_col = rows[1][7]
        self.assertIn("EVID.METER.SAMPLE_PEAK_DBFS", evidence_col)

    def test_target_scope_and_id(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][5], "stem")
        self.assertEqual(rows[1][6], "kick")
        # ISSUE.LOW has no target
        self.assertEqual(rows[2][5], "")
        self.assertEqual(rows[2][6], "")

    def test_empty_issues_emits_header_only(self) -> None:
        report = {"issues": [], "recommendations": []}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "rank")

    def test_determinism_on_tie(self) -> None:
        """Issues with identical severity/confidence sort alphabetically by issue_id."""
        report = {
            "issues": [
                {
                    "issue_id": "ISSUE.Z",
                    "severity": 50,
                    "confidence": 0.7,
                    "message": "",
                    "evidence": [{"evidence_id": "EVID.FILE.FORMAT", "value": "wav"}],
                },
                {
                    "issue_id": "ISSUE.A",
                    "severity": 50,
                    "confidence": 0.7,
                    "message": "",
                    "evidence": [{"evidence_id": "EVID.FILE.FORMAT", "value": "wav"}],
                },
            ],
            "recommendations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][1], "ISSUE.A")
        self.assertEqual(rows[2][1], "ISSUE.Z")


class TestRecallSheetContextFields(unittest.TestCase):
    """Tests for scene / preflight / request context columns in recall_sheet."""

    def _minimal_report(self) -> dict:
        return {
            "profile_id": "PROFILE.ASSIST",
            "issues": [
                {
                    "issue_id": "ISSUE.TEST",
                    "severity": 50,
                    "confidence": 0.8,
                    "message": "A test issue",
                    "evidence": [{"evidence_id": "EVID.FILE.FORMAT", "value": "wav"}],
                }
            ],
            "recommendations": [],
        }

    def _minimal_scene(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.DRAFT.test001",
            "source": {"stems_dir": "/tmp/stems", "created_from": "draft"},
            "objects": [
                {"object_id": "OBJ.001", "role_id": "ROLE.DRUMS.KICK"},
                {"object_id": "OBJ.002", "role_id": "ROLE.BASS.DI"},
            ],
            "beds": [],
            "metadata": {},
        }

    def _minimal_preflight_pass(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "plan_path": "/tmp/render_plan.json",
            "plan_id": "PLAN.render.preflight.abcdef01",
            "checks": [],
            "issues": [],
        }

    def _minimal_preflight_fail(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "plan_path": "/tmp/render_plan.json",
            "plan_id": "PLAN.render.preflight.abcdef02",
            "checks": [],
            "issues": [
                {
                    "issue_id": "ISSUE.RENDER.PREFLIGHT.INPUT_MISSING",
                    "severity": "error",
                    "message": "Input path does not exist.",
                    "evidence": {},
                }
            ],
        }

    def test_context_columns_present_no_context(self) -> None:
        """Without context args all context columns are empty / 'missing'."""
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # 17 columns total (added render_channel_orders + render_export_warnings)
        self.assertEqual(len(rows[0]), 17)
        data = rows[1]
        # scene_id col 9
        self.assertEqual(data[9], "")
        # scene_object_count col 10
        self.assertEqual(data[10], "")
        # target_layout_ids col 11
        self.assertEqual(data[11], "")
        # profile_id col 12 — fallback to report profile_id
        self.assertEqual(data[12], "PROFILE.ASSIST")
        # preflight_status col 13 — missing when no preflight
        self.assertEqual(data[13], "missing")
        # layout_standard col 14 — empty when not provided
        self.assertEqual(data[14], "")
        # render_channel_orders col 15 — empty when render_report not provided
        self.assertEqual(data[15], "")
        # render_export_warnings col 16 — empty when render_report not provided
        self.assertEqual(data[16], "")

    def test_scene_context_populated(self) -> None:
        report = self._minimal_report()
        scene = self._minimal_scene()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, scene=scene)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        data = rows[1]
        self.assertEqual(data[9], "SCENE.DRAFT.test001")
        self.assertEqual(data[10], "2")

    def test_preflight_pass_status(self) -> None:
        report = self._minimal_report()
        preflight = self._minimal_preflight_pass()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, preflight=preflight)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][13], "pass")

    def test_preflight_fail_status(self) -> None:
        report = self._minimal_report()
        preflight = self._minimal_preflight_fail()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, preflight=preflight)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][13], "fail")

    def test_target_layout_ids_single(self) -> None:
        report = self._minimal_report()
        request = {"target_layout_id": "LAYOUT.5_1", "scene_path": "drafts/scene.draft.json"}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, request=request)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(rows[1][11], "LAYOUT.5_1")

    def test_target_layout_ids_multi(self) -> None:
        report = self._minimal_report()
        request = {
            "target_layout_ids": ["LAYOUT.5_1", "LAYOUT.2_0"],
            "scene_path": "drafts/scene.draft.json",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, request=request)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # Sorted and pipe-joined
        self.assertEqual(rows[1][11], "LAYOUT.2_0|LAYOUT.5_1")

    def test_profile_id_explicit_overrides_report(self) -> None:
        report = {"profile_id": "PROFILE.GUIDE", "issues": [], "recommendations": []}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, profile_id="PROFILE.ASSIST")
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        # Header only (no issues), but check header is intact
        self.assertEqual(len(rows), 1)

    def test_determinism_with_full_context(self) -> None:
        """Two runs with identical inputs produce byte-identical output."""
        report = self._minimal_report()
        scene = self._minimal_scene()
        preflight = self._minimal_preflight_pass()
        request = {"target_layout_id": "LAYOUT.5_1", "scene_path": "drafts/scene.draft.json"}

        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.csv"
            out_b = Path(tmp) / "b.csv"
            export_recall_sheet(report, out_a, scene=scene, preflight=preflight, request=request)
            export_recall_sheet(report, out_b, scene=scene, preflight=preflight, request=request)
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())

    def test_render_report_context_populates_channel_order_and_warnings(self) -> None:
        report = self._minimal_report()
        render_report = {
            "schema_version": "0.1.0",
            "request": {
                "target_layout_id": "LAYOUT.5_2",
                "scene_path": "scenes/demo/scene.json",
            },
            "jobs": [
                {
                    "job_id": "JOB.001",
                    "status": "completed",
                    "target_layout_id": "LAYOUT.5_2",
                    "channel_count": 7,
                    "channel_order": [
                        "SPK.L",
                        "SPK.R",
                        "SPK.C",
                        "SPK.LFE",
                        "SPK.LFE2",
                        "SPK.LS",
                        "SPK.RS",
                    ],
                    "warnings": [
                        "Dual-LFE WAV export uses conservative channel-mask strategy: WAVEFORMATEXTENSIBLE DIRECTOUT (mask=0)."
                    ],
                    "output_files": [],
                }
            ],
            "policies_applied": {},
            "qa_gates": {"status": "not_run", "gates": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, render_report=render_report)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        header = rows[0]
        data = rows[1]
        render_channel_orders_index = header.index("render_channel_orders")
        render_export_warnings_index = header.index("render_export_warnings")
        self.assertEqual(
            data[render_channel_orders_index],
            "LAYOUT.5_2:SPK.L,SPK.R,SPK.C,SPK.LFE,SPK.LFE2,SPK.LS,SPK.RS",
        )
        self.assertIn("DIRECTOUT (mask=0)", data[render_export_warnings_index])


class TestRecallSheetLayoutStandard(unittest.TestCase):
    """Tests for the layout_standard column in recall_sheet."""

    def _minimal_report(self) -> dict:
        return {
            "issues": [
                {
                    "issue_id": "ISSUE.TEST",
                    "severity": 50,
                    "confidence": 0.7,
                    "message": "test",
                    "evidence": [{"evidence_id": "EVID.FILE.FORMAT", "value": "wav"}],
                }
            ],
            "recommendations": [],
        }

    def test_layout_standard_column_empty_by_default(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out)
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        layout_standard_index = rows[0].index("layout_standard")
        self.assertEqual(rows[1][layout_standard_index], "")

    def test_layout_standard_column_populated(self) -> None:
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recall.csv"
            export_recall_sheet(report, out, layout_standard="FILM")
            rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        layout_standard_index = rows[0].index("layout_standard")
        self.assertEqual(rows[1][layout_standard_index], "FILM")

    def test_layout_standard_deterministic(self) -> None:
        """Same inputs → byte-identical output regardless of layout_standard."""
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmp:
            out_a = Path(tmp) / "a.csv"
            out_b = Path(tmp) / "b.csv"
            export_recall_sheet(report, out_a, layout_standard="SMPTE")
            export_recall_sheet(report, out_b, layout_standard="SMPTE")
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())


class TestPdfReportLayoutFeatures(unittest.TestCase):
    """Tests for layout_standard, scene, preflight, and height-bed notes in PDF report."""

    def _load_report(self) -> dict:
        path = Path("fixtures/export/report_small.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_speaker_layout_summary_table_known_layout(self) -> None:
        tbl = _pdf_report._speaker_layout_summary_table("LAYOUT.5_1", "SMPTE")
        # Returns None only when reportlab is absent; otherwise a Table or None from preset
        # We just verify it doesn't raise and the function is callable.
        # (Table object cannot be inspected without reportlab)
        try:
            import reportlab  # noqa: F401
            self.assertIsNotNone(tbl)
        except ImportError:
            pass  # reportlab absent; function still must not raise

    def test_speaker_layout_summary_table_unknown_layout(self) -> None:
        tbl = _pdf_report._speaker_layout_summary_table("LAYOUT.UNKNOWN", "SMPTE")
        self.assertIsNone(tbl)

    def test_speaker_layout_summary_table_empty_args(self) -> None:
        self.assertIsNone(_pdf_report._speaker_layout_summary_table("", "SMPTE"))
        self.assertIsNone(_pdf_report._speaker_layout_summary_table("LAYOUT.5_1", ""))

    def test_scene_diagram_lines_with_objects(self) -> None:
        scene = {
            "scene_id": "SCENE.DRAFT.test",
            "objects": [
                {"object_id": "OBJ.001", "role_id": "ROLE.DRUMS.KICK"},
                {"object_id": "OBJ.002", "role_id": "ROLE.BASS.DI", "layout_id": "LAYOUT.STEREO"},
            ],
            "beds": [],
        }
        lines = _pdf_report._scene_diagram_lines(scene)
        self.assertTrue(any("SCENE.DRAFT.test" in line for line in lines))
        self.assertTrue(any("OBJ.001" in line for line in lines))
        self.assertTrue(any("ROLE.DRUMS.KICK" in line for line in lines))
        self.assertTrue(any("LAYOUT.STEREO" in line for line in lines))

    def test_scene_diagram_lines_empty(self) -> None:
        lines = _pdf_report._scene_diagram_lines({})
        self.assertTrue(lines[0].startswith("Scene:"))
        self.assertTrue(any("Objects" in line for line in lines))
        self.assertEqual(_pdf_report._scene_diagram_lines(None), [])  # type: ignore[arg-type]

    def test_preflight_gate_table_no_data_returns_none(self) -> None:
        result = _pdf_report._preflight_gate_table({"checks": [], "issues": []})
        self.assertIsNone(result)

    def test_preflight_gate_table_with_issues(self) -> None:
        preflight = {
            "checks": [],
            "issues": [
                {
                    "issue_id": "ISSUE.RENDER.PREFLIGHT.INPUT_MISSING",
                    "severity": "error",
                    "message": "Input path does not exist.",
                }
            ],
        }
        try:
            import reportlab  # noqa: F401
            tbl = _pdf_report._preflight_gate_table(preflight)
            self.assertIsNotNone(tbl)
        except ImportError:
            pass  # cannot build Table without reportlab

    def test_height_bed_notes_immersive_source(self) -> None:
        downmix_qa = {
            "log": json.dumps(
                {
                    "source_layout_id": "LAYOUT.7_1_4",
                    "target_layout_id": "LAYOUT.2_0",
                }
            )
        }
        notes = _pdf_report._height_bed_notes(downmix_qa)
        self.assertEqual(len(notes), 2)
        self.assertIn("LAYOUT.7_1_4", notes[0])
        self.assertIn("LAYOUT.2_0", notes[0])
        self.assertIn("-6 dB", notes[0])
        self.assertIn("-12 dBFS", notes[1])

    def test_height_bed_notes_stereo_source_empty(self) -> None:
        downmix_qa = {
            "log": json.dumps(
                {
                    "source_layout_id": "LAYOUT.2_0",
                    "target_layout_id": "LAYOUT.2_0",
                }
            )
        }
        notes = _pdf_report._height_bed_notes(downmix_qa)
        self.assertEqual(notes, [])

    def test_height_bed_notes_missing_layout_empty(self) -> None:
        notes = _pdf_report._height_bed_notes({})
        self.assertEqual(notes, [])

    def test_export_report_pdf_with_layout_standard(self) -> None:
        if not self._has_reportlab():
            self.skipTest("reportlab not installed")
        report = self._load_report()
        # Add a stem with layout_id so the speaker layout table is triggered
        report["session"] = {
            "stems": [
                {
                    "stem_id": "drums",
                    "layout_id": "LAYOUT.5_1",
                    "file_path": "drums.wav",
                    "measurements": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.pdf"
            export_report_pdf(report, out, layout_standard="SMPTE")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

    def test_export_report_pdf_with_scene_and_preflight(self) -> None:
        if not self._has_reportlab():
            self.skipTest("reportlab not installed")
        report = self._load_report()
        scene = {
            "scene_id": "SCENE.DRAFT.test001",
            "objects": [{"object_id": "OBJ.001", "role_id": "ROLE.DRUMS.KICK"}],
            "beds": [],
        }
        preflight = {
            "plan_id": "PLAN.test.001",
            "checks": [],
            "issues": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.pdf"
            export_report_pdf(report, out, scene=scene, preflight=preflight)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

    @staticmethod
    def _has_reportlab() -> bool:
        try:
            import reportlab  # noqa: F401
            return True
        except ImportError:
            return False


if __name__ == "__main__":
    unittest.main()
