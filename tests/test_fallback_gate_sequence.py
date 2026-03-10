from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "fixtures" / "fallback_gate_fail"
_PLACEHOLDER_STEMS_DIR = "__FIXTURE_STEMS_DIR__"
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_FULL_SEQUENCE = [
    "reduce_surround",
    "reduce_height",
    "reduce_decorrelation",
    "disable_wideners",
    "front_bias",
    "safety_collapse",
]
_SURROUND_SEQUENCE = [
    "reduce_surround",
    "reduce_decorrelation",
    "disable_wideners",
    "safety_collapse",
]
_METRIC_KEYS = (
    "loudness_delta_lufs",
    "correlation_over_time_min",
    "spectral_distance_db",
    "true_peak_delta_dbtp",
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_placement_only_plugins_dir(path: Path) -> Path:
    renderers_dir = path / "renderers"
    renderers_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _PLUGINS_DIR / "renderers" / "placement_mixdown_renderer.plugin.yaml"
    renderers_dir.joinpath(source_manifest.name).write_text(
        source_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _materialize_fixture_template(template_path: Path, *, out_path: Path) -> Path:
    stems_dir = (_FIXTURE_ROOT / "stems").resolve().as_posix()
    rendered = template_path.read_text(encoding="utf-8").replace(
        _PLACEHOLDER_STEMS_DIR,
        stems_dir,
    )
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def _attempts_by_layout(receipt: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in receipt.get("fallback_attempts", []):
        if not isinstance(row, dict):
            continue
        layout_id = str(row.get("layout_id") or "").strip()
        if not layout_id:
            continue
        grouped.setdefault(layout_id, []).append(row)
    return grouped


class TestFallbackGateSequence(unittest.TestCase):
    def test_safe_render_reports_documented_fallback_sequence_after_gate_fail(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is required for rendered downmix similarity QA")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            plugins_dir = _write_placement_only_plugins_dir(temp / "plugins")
            report_path = _materialize_fixture_template(
                _FIXTURE_ROOT / "report.json",
                out_path=temp / "report.json",
            )
            scene_path = _materialize_fixture_template(
                _FIXTURE_ROOT / "scene.json",
                out_path=temp / "scene.json",
            )
            receipt_path = temp / "receipt.json"

            exit_code, _stdout, stderr = _run_main(
                [
                    "safe-render",
                    "--report",
                    str(report_path),
                    "--plugins",
                    str(plugins_dir),
                    "--scene",
                    str(scene_path),
                    "--scene-locks",
                    str(_FIXTURE_ROOT / "scene_locks.yaml"),
                    "--render-many",
                    "--render-many-targets",
                    "LAYOUT.5_1,LAYOUT.7_1_4",
                    "--out-dir",
                    str(temp / "renders"),
                    "--receipt-out",
                    str(receipt_path),
                    "--export-layouts",
                    "LAYOUT.2_0,LAYOUT.5_1,LAYOUT.7_1_4",
                    "--force",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            immersive_receipt_path = temp / "receipt.LAYOUT_7_1_4.json"
            surround_receipt_path = temp / "receipt.LAYOUT_5_1.json"
            self.assertTrue(immersive_receipt_path.is_file())
            self.assertTrue(surround_receipt_path.is_file())

            immersive_receipt = json.loads(immersive_receipt_path.read_text(encoding="utf-8"))
            attempts_by_layout = _attempts_by_layout(immersive_receipt)
            immersive_attempts = attempts_by_layout.get("LAYOUT.7_1_4", [])
            surround_attempts = attempts_by_layout.get("LAYOUT.5_1", [])

            self.assertGreaterEqual(len(immersive_receipt.get("fallback_attempts", [])), 1)
            self.assertEqual(
                [row.get("step_id") for row in immersive_attempts],
                _FULL_SEQUENCE,
            )
            self.assertEqual(
                [row.get("step_id") for row in surround_attempts],
                _SURROUND_SEQUENCE,
            )
            self.assertFalse(bool(immersive_attempts[0].get("qa_before", {}).get("passed")))
            self.assertFalse(bool(surround_attempts[0].get("qa_before", {}).get("passed")))

            self.assertTrue(
                any(
                    any(
                        change.get("speaker_id") in {
                            "SPK.LS",
                            "SPK.RS",
                            "SPK.LRS",
                            "SPK.RRS",
                            "SPK.TFL",
                            "SPK.TFR",
                            "SPK.TRL",
                            "SPK.TRR",
                        }
                        and change.get("from") != change.get("to")
                        for change in attempt.get("changes", [])
                        if isinstance(change, dict)
                    )
                    for attempt in immersive_attempts
                )
            )

            for attempt in immersive_attempts + surround_attempts:
                for key in ("qa_before", "qa_after"):
                    qa_payload = attempt.get(key, {})
                    self.assertIsInstance(qa_payload, dict)
                    metrics = qa_payload.get("metrics", {})
                    self.assertIsInstance(metrics, dict)
                    for metric_key in _METRIC_KEYS:
                        self.assertIn(metric_key, metrics)

            fallback_final = immersive_receipt.get("fallback_final", {})
            self.assertEqual(fallback_final.get("applied_steps"), _FULL_SEQUENCE)
            final_outcome = str(fallback_final.get("final_outcome") or "")
            if final_outcome == "fail":
                self.assertTrue(bool(fallback_final.get("safety_collapse_applied")))
                gate_issue = next(
                    (
                        issue
                        for issue in immersive_receipt.get("qa_issues", [])
                        if isinstance(issue, dict)
                        and issue.get("issue_id") == "ISSUE.DOWNMIX.QA.SIMILARITY_GATE_FAILED"
                    ),
                    None,
                )
                self.assertIsNotNone(gate_issue)
                if isinstance(gate_issue, dict):
                    self.assertIn("still failed", str(gate_issue.get("message") or "").lower())
            else:
                self.assertIn(final_outcome, {"pass", "pass_with_safety_collapse"})
            self.assertEqual(final_outcome, "pass_with_safety_collapse")
            self.assertTrue(bool(fallback_final.get("safety_collapse_applied")))

            notes = immersive_receipt.get("notes", [])
            self.assertIn("fallback_applied=true", notes)
            self.assertIn("safety_collapse_applied=true", notes)
            self.assertIn("fallback_final_outcome=pass_with_safety_collapse", notes)


if __name__ == "__main__":
    unittest.main()
